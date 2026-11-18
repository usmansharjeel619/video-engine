#!/usr/bin/env python3
"""
Unified End-to-End Streamer Viral Clipping Pipeline (v3 — OpenShorts + Streamer Edition).

Combines OpenShorts' 2-pass Gemini virality scoring, Pass-3 Vision hook
grounding, styled Pillow emoji hook banners, and kinetic animated ASS captions
with native Streamer Split-Screen (facecam + gameplay), 0-2s flash-forward cold
opens, silence jump-cuts, strategic SFX, automated ffprobe + frame QA, and
1-command Mobile Upload Hub / Postiz publishing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from caption_styles import build_styled_ass
from clip_engine import (
    compute_jump_cut_segments,
    compute_rms_per_second,
    default_cookies_path,
    extract_wav,
    find_peak_offset,
    parse_timestamp,
    prepend_flash_hook,
    render_portrait_clip,
    transcribe_audio,
)
from hook_renderer import compute_hook_y, create_hook_image
from publish_clips import fetch_postiz_integrations, publish_postiz
from viral_selector import analyze_and_select_viral_clips, load_dotenv_if_available


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:40] or "clip"


def _append_tags(caption: str, extra_tags: list[str]) -> str:
    text = (caption or "").strip()
    additions = []
    lower = text.lower()
    for raw in extra_tags or []:
        t = raw.strip().lstrip("#")
        if t and f"#{t.lower()}" not in lower:
            additions.append(f"#{t}")
    if not additions:
        return text
    return f"{text} {' '.join(additions)}".strip()


def qa_verify_clip(mp4_path: Path, qa_dir: Path) -> tuple[bool, dict[str, Any]]:
    """
    Verify rendered MP4 has 1080x1920 video, A/V start_time=0.000000, >= 5s duration,
    and extract 2 visual QA PNG stills (hook + mid-clip caption).
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,width,height,start_time",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(mp4_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return False, {"error": proc.stderr.strip()}

    info = json.loads(proc.stdout or "{}")
    streams = info.get("streams", [])
    duration = float((info.get("format") or {}).get("duration") or 0.0)
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    issues: list[str] = []
    if not v_stream:
        issues.append("missing video stream")
    else:
        if int(v_stream.get("width") or 0) != 1080 or int(v_stream.get("height") or 0) != 1920:
            issues.append(f"bad dimensions {v_stream.get('width')}x{v_stream.get('height')}")
        v_start = abs(float(v_stream.get("start_time") or 0.0))
        if v_start >= 0.05:
            issues.append(f"video start_time={v_start:.3f}")

    if not a_stream:
        issues.append("missing audio stream")
    else:
        a_start = abs(float(a_stream.get("start_time") or 0.0))
        if a_start >= 0.05:
            issues.append(f"audio start_time={a_start:.3f}")

    if duration < 5.0:
        issues.append(f"duration too short ({duration:.2f}s)")

    qa_dir.mkdir(parents=True, exist_ok=True)
    stem = mp4_path.stem
    stills = [
        (qa_dir / f"{stem}_t1_hook.png", min(1.5, max(0.3, duration * 0.25))),
        (qa_dir / f"{stem}_tmid_cap.png", max(0.5, duration * 0.45)),
    ]
    for img_path, ts in stills:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{ts:.2f}",
                "-i",
                str(mp4_path),
                "-frames:v",
                "1",
                str(img_path),
            ],
            capture_output=True,
            check=False,
        )

    passed = len(issues) == 0
    return passed, {"duration": round(duration, 2), "issues": issues, "qa_stills": [str(p) for p, _ in stills]}


def _ingest_source(args: argparse.Namespace, work_dir: Path, cookies: Path | None) -> Path:
    if args.input.startswith("http://") or args.input.startswith("https://"):
        source_video = work_dir / "source.mp4"
        if source_video.exists() and source_video.stat().st_size > 0:
            print(f"Reusing cached source video -> {source_video}")
            return source_video

        if args.dvr:
            dvr_cmd = [
                sys.executable,
                str(SCRIPTS_DIR / "grab_yt_dvr.py"),
                "--url",
                args.input,
                "--start-min",
                str(args.start_min),
                "--end-min",
                str(args.end_min),
                "--output",
                str(source_video),
            ]
            if cookies and cookies.exists():
                dvr_cmd.extend(["--cookies", str(cookies)])
            subprocess.run(dvr_cmd, check=True)
            return source_video

        dl_cmd = [sys.executable, "-m", "yt_dlp"]
        if cookies and cookies.exists():
            dl_cmd.extend(["--cookies", str(cookies)])
        dl_cmd.extend(
            [
                "-f",
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "--merge-output-format",
                "mp4",
                "-o",
                str(source_video),
                args.input,
            ]
        )
        print(f"Downloading source video via yt-dlp -> {source_video}")
        subprocess.run(dl_cmd, check=True)
        return source_video

    local = Path(args.input).resolve()
    if not local.exists():
        raise FileNotFoundError(f"Input video not found: {local}")
    return local


def _print_viral_summary(clips: list[dict[str, Any]]) -> None:
    print("\n=== Selected Viral Clips ===")
    print(f"{'#':<3} {'Score':<6} {'Span':<15} {'Hook':<46} {'Why'}")
    print("-" * 110)
    for idx, c in enumerate(clips, start=1):
        span = f"{c['start']:.1f}s-{c['end']:.1f}s"
        hook = (c.get("viral_hook_text") or "")[:44]
        why = (c.get("why") or "")[:40]
        print(f"{idx:<3} {c.get('predicted_score', 0):<6} {span:<15} {hook:<46} {why}")
    print("")


def _publish_mobile_hub(
    args: argparse.Namespace,
    out_dir: Path,
    manifest_path: Path,
    manifest: list[dict[str, Any]],
) -> None:
    tag = args.release_tag or _slugify(args.batch or out_dir.name)
    mp4s = [item["path"] for item in manifest if item.get("qaPassed") and Path(item["path"]).exists()]
    if not mp4s:
        print("Mobile Hub publish skipped: no QA-passed MP4 files found.")
        return

    repo_slug = "usmansharjeel619/video-engine"
    try:
        slug_out = subprocess.check_output(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            cwd=str(REPO_ROOT),
            text=True,
        ).strip()
        if slug_out:
            repo_slug = slug_out
    except Exception:
        pass

    exists = subprocess.run(
        ["gh", "release", "view", tag],
        cwd=str(REPO_ROOT),
        capture_output=True,
        check=False,
    ).returncode == 0

    if exists:
        subprocess.run(["gh", "release", "upload", tag, *mp4s, "--clobber"], cwd=str(REPO_ROOT), check=True)
    else:
        subprocess.run(
            [
                "gh",
                "release",
                "create",
                tag,
                *mp4s,
                "--title",
                args.batch or tag,
                "--notes",
                f"Automated viral clip batch ({len(mp4s)} clips)",
            ],
            cwd=str(REPO_ROOT),
            check=True,
        )

    manifests_dir = REPO_ROOT / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    target_manifest = manifests_dir / f"{tag}.json"
    shutil.copy2(manifest_path, target_manifest)

    hub_cfg_path = manifests_dir / "hub_config.json"
    folders: list[dict[str, Any]] = []
    if hub_cfg_path.exists():
        folders = json.loads(hub_cfg_path.read_text(encoding="utf-8"))

    folder_name = args.folder or "Viral Streamer Batches"
    batch_name = args.batch or tag
    base_url = f"https://github.com/{repo_slug}/releases/download/{tag}"
    new_batch = {
        "batch": batch_name,
        "baseUrl": base_url,
        "manifest": f"manifests/{tag}.json",
    }

    matched = next((f for f in folders if f.get("folder") == folder_name), None)
    if matched is not None:
        matched["batches"] = [b for b in matched.get("batches", []) if b.get("manifest") != new_batch["manifest"]]
        matched["batches"].insert(0, new_batch)
    else:
        folders.insert(
            0,
            {
                "folder": folder_name,
                "subtitle": args.subtitle or "Automated Viral Pipeline · Split-Screen & Hooks",
                "batches": [new_batch],
            },
        )

    hub_cfg_path.write_text(json.dumps(folders, indent=2) + "\n", encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "build_mobile_pack.py"),
            "--config",
            str(hub_cfg_path),
            "--output",
            str(REPO_ROOT / "docs" / "index.html"),
        ],
        check=True,
    )

    if not args.no_git_push:
        subprocess.run(["git", "add", "manifests/", "docs/"], cwd=str(REPO_ROOT), check=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(REPO_ROOT), check=False)
        if diff.returncode != 0:
            subprocess.run(
                ["git", "commit", "-m", f"publish: {folder_name} / {batch_name} ({len(mp4s)} clips)"],
                cwd=str(REPO_ROOT),
                check=True,
            )
            subprocess.run(["git", "push", "origin", "main"], cwd=str(REPO_ROOT), check=True)
    print(f"Published {len(mp4s)} clips to GitHub Release '{tag}' & updated docs/index.html.")


def _publish_postiz(manifest: list[dict[str, Any]], out_dir: Path) -> None:
    load_dotenv_if_available(REPO_ROOT / ".env")
    base_url = os.getenv("POSTIZ_BASE_URL") or os.getenv("POSTIZ_URL") or "http://127.0.0.1:4008"
    api_key = (os.getenv("POSTIZ_API_KEY") or "").strip()
    if not api_key:
        print(
            "Postiz publish skipped: POSTIZ_API_KEY is not set in .env.\n"
            "Generate an API key at https://instance-20260916-2320.tail256180.ts.net:4007 and set POSTIZ_API_KEY in ~/video-engine/.env."
        )
        return

    raw_ids = os.getenv("POSTIZ_INTEGRATION_IDS", "")
    ids = [i.strip() for i in raw_ids.split(",") if i.strip()]
    if not ids:
        try:
            integrations = fetch_postiz_integrations(base_url, api_key)
            ids = [str(it["id"]) for it in integrations if it.get("id")]
        except Exception as exc:
            print(f"Postiz publish skipped: failed to list integrations from {base_url}: {exc}")
            return

    if not ids:
        print(
            "Postiz publish skipped: 0 social channels connected in Postiz.\n"
            "Open https://instance-20260916-2320.tail256180.ts.net:4007 to connect TikTok/Instagram/YouTube accounts."
        )
        return

    results = []
    for item in manifest:
        if not item.get("qaPassed"):
            continue
        p = Path(item["path"])
        caption = item.get("tiktokCaption") or item.get("instagramCaption") or item.get("caption") or item.get("title")
        res = publish_postiz(p, str(caption), base_url, api_key, ids)
        print(f"Postiz published {p.name}: {res}")
        results.append({"clip": p.name, "response": res})

    (out_dir / "postiz_publish_results.json").write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="End-to-end Streamer Viral Clipping Pipeline (Whisper + 2-Pass Gemini + Vision Hooks + Split-Screen + QA + Publish)."
    )
    p.add_argument("--input", "-i", required=True, help="Local video file or YouTube/Twitch/Kick URL.")
    p.add_argument("--output-dir", "-o", type=Path, default=Path("output/viral_batch"), help="Output directory.")
    p.add_argument("--dvr", action="store_true", help="Grab live YouTube DVR window via grab_yt_dvr.py.")
    p.add_argument("--start-min", type=float, default=0.0, help="DVR start minute (--dvr only).")
    p.add_argument("--end-min", type=float, default=12.0, help="DVR end minute (--dvr only).")
    p.add_argument("--start", default=None, help="Optional slice start timestamp (e.g. 00:05:00).")
    p.add_argument("--end", default=None, help="Optional slice end timestamp.")
    p.add_argument("--cookies", type=Path, default=None, help="Path to Netscape cookies.txt for yt-dlp.")

    p.add_argument("--layout", choices=["split", "center", "blur"], default="split", help="Portrait layout (default: split).")
    p.add_argument("--cam-pos", default="auto", help="Facecam position in split mode: auto, tl, tr, bl, br, center, or x,y,w,h.")
    p.add_argument("--no-flash-hook", action="store_true", help="Disable 0-2s peak reaction cold-open flash-forward.")
    p.add_argument("--no-trim-silence", action="store_true", help="Disable silence/dead-air jump cutting.")
    p.add_argument("--no-sfx", action="store_true", help="Disable whoosh & boom SFX cues.")
    p.add_argument("--no-ground-hooks", action="store_true", help="Disable Pass-3 Gemini Vision hook grounding.")

    p.add_argument(
        "--caption-preset",
        choices=["hormozi", "pop", "pill", "lime", "oneword", "clean"],
        default="hormozi",
        help="Kinetic caption preset (default: hormozi).",
    )
    p.add_argument("--caption-reveal", action="store_true", help="Reveal words progressively inside caption blocks.")
    p.add_argument(
        "--hook-style",
        choices=["pill", "yellow", "red", "dark", "classic", "outline", "outline_yellow"],
        default="pill",
        help="Pillow hook overlay banner style (default: pill).",
    )
    p.add_argument("--hook-font", default=None, help="Optional hook font key: montserrat, anton, archivoblack, serif.")
    p.add_argument("--hook-duration", type=float, default=4.2, help="Hook overlay duration in seconds (default: 4.2).")

    p.add_argument("--model", default="small", help="Faster-Whisper model size (tiny, base, small, medium).")
    p.add_argument("--language", default=None, help="Optional audio language code (e.g. en).")
    p.add_argument("--gemini-model", default=None, help="Override GEMINI_MODEL (default: gemini-3-flash-preview).")
    p.add_argument("--min-duration", type=float, default=20.0, help="Min clip duration seconds.")
    p.add_argument("--max-duration", type=float, default=55.0, help="Max clip duration seconds.")
    p.add_argument("--top-n", type=int, default=5, help="Max clips to export (default: 5).")
    p.add_argument("--min-virality", type=int, default=65, help="Minimum Gemini predicted_score 0-100 (default: 65).")
    p.add_argument("--allow-below-min", action="store_true", help="Allow lower-scoring clips if none hit --min-virality.")

    p.add_argument("--require-keyword", default=None, help="Require this keyword in selected clips.")
    p.add_argument("--instructions", default=None, help="Custom AI steering instructions (campaign brief focus, tone, etc.).")
    p.add_argument("--extra-tags", nargs="*", default=[], help="Hashtags to append to generated captions.")
    p.add_argument("--logo", type=Path, default=None, help="Optional transparent PNG campaign logo overlay.")

    p.add_argument("--folder", default=None, help="Mobile Hub folder name.")
    p.add_argument("--batch", default=None, help="Mobile Hub batch name.")
    p.add_argument("--subtitle", default=None, help="Mobile Hub folder subtitle.")
    p.add_argument("--release-tag", default=None, help="GitHub Release tag for Mobile Hub assets.")
    p.add_argument(
        "--publish",
        choices=["none", "mobile-hub", "postiz", "both"],
        default="none",
        help="Publish destination after rendering & QA (default: none).",
    )
    p.add_argument("--no-git-push", action="store_true", help="Skip git commit/push during mobile-hub publish.")
    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    out_dir = args.output_dir.resolve()
    work_dir = out_dir / ".work"
    qa_dir = out_dir / "qa"
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    cookies = args.cookies if args.cookies is not None else default_cookies_path()
    source_video = _ingest_source(args, work_dir, cookies)

    start_sec = parse_timestamp(args.start) if args.start else None
    end_sec = parse_timestamp(args.end) if args.end else None
    offset = start_sec or 0.0
    range_sig = f"{source_video}|{start_sec}|{end_sec}|{args.model}|{args.language}"

    wav_path = work_dir / "audio_16k.wav"
    transcript_path = work_dir / "transcript.json"
    energies_path = work_dir / "energies.json"
    meta_path = work_dir / "meta.json"

    cached_ok = False
    if transcript_path.exists() and energies_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            cached_ok = meta.get("range_sig") == range_sig
        except Exception:
            cached_ok = False

    if cached_ok:
        print("Reusing cached WAV energies and Whisper transcript...")
        energies = json.loads(energies_path.read_text(encoding="utf-8"))
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    else:
        print("Extracting 16kHz audio and computing RMS energy...")
        extract_wav(source_video, wav_path, start_sec, end_sec)
        energies = compute_rms_per_second(wav_path)
        print(f"Transcribing audio with faster-whisper ({args.model})...")
        transcript = transcribe_audio(wav_path, args.model, args.language)
        energies_path.write_text(json.dumps(energies), encoding="utf-8")
        transcript_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
        meta_path.write_text(json.dumps({"range_sig": range_sig}), encoding="utf-8")

    selected = analyze_and_select_viral_clips(
        transcript_result=transcript,
        energies=energies,
        source_video=source_video,
        offset_seconds=offset,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        top_n=args.top_n,
        min_virality=args.min_virality,
        allow_below_min=args.allow_below_min,
        ground_hooks=not args.no_ground_hooks,
        instructions=args.instructions,
        require_keyword=args.require_keyword,
        extra_tags=args.extra_tags,
        model_name=args.gemini_model,
    )
    if not selected:
        raise RuntimeError(
            f"No clips passed virality criteria (min_virality={args.min_virality}). "
            "Try lowering --min-virality or passing --allow-below-min."
        )

    _print_viral_summary(selected)

    logo = args.logo.resolve() if args.logo else None
    manifest: list[dict[str, Any]] = []

    for idx, clip in enumerate(selected, start=1):
        hook_text = clip.get("viral_hook_text") or clip.get("video_title_for_youtube_short") or "WAIT FOR THIS"
        yt_title = clip.get("video_title_for_youtube_short") or hook_text
        slug = _slugify(yt_title)
        mp4_path = out_dir / f"clip_{idx:02d}_{slug}.mp4"
        ass_path = work_dir / f"clip_{idx:02d}.ass"
        hook_png_path = work_dir / f"hook_{idx:02d}.png"

        peak_offset = find_peak_offset(energies, clip["start"], clip["end"])
        abs_start = offset + float(clip["start"])
        abs_end = offset + float(clip["end"])

        kept_intervals: list[tuple[float, float]] | None = None
        if not args.no_trim_silence:
            kept_intervals, retimed_words = compute_jump_cut_segments(
                clip["words"], clip["start"], clip["end"]
            )
            if not args.no_flash_hook:
                kept_intervals, retimed_words = prepend_flash_hook(
                    kept_intervals, clip["words"], clip["start"], clip["end"], peak_offset
                )
            words_for_ass = retimed_words
            ass_offset = 0.0
            ass_is_rel = True
        elif not args.no_flash_hook:
            base_iv = [(0.0, round(clip["end"] - clip["start"], 3))]
            kept_intervals, retimed_words = prepend_flash_hook(
                base_iv, clip["words"], clip["start"], clip["end"], peak_offset
            )
            words_for_ass = retimed_words
            ass_offset = 0.0
            ass_is_rel = True
        else:
            words_for_ass = clip["words"]
            ass_offset = clip["start"]
            ass_is_rel = False

        build_styled_ass(
            words_for_ass,
            ass_offset,
            ass_path,
            preset=args.caption_preset,
            layout=args.layout,
            is_relative=ass_is_rel,
            reveal=args.caption_reveal,
        )

        hook_png, _, hook_h = create_hook_image(
            hook_text,
            hook_png_path,
            style=args.hook_style,
            font_name=args.hook_font,
        )
        hook_y = compute_hook_y(
            args.layout,
            hook_h,
            source_video=source_video,
            sample_time=abs_start + 1.0,
        )

        print(
            f"Rendering {idx}/{len(selected)}: {mp4_path.name} "
            f"(score={clip['predicted_score']}, span={abs_start:.1f}s->{abs_end:.1f}s, hook_y={hook_y})..."
        )
        render_portrait_clip(
            source_video=source_video,
            abs_start=abs_start,
            abs_end=abs_end,
            ass_path=ass_path,
            output_mp4=mp4_path,
            layout=args.layout,
            logo_path=logo,
            cam_pos=args.cam_pos,
            kept_intervals=kept_intervals,
            use_sfx=not args.no_sfx,
            peak_offset=peak_offset,
            hook_png=hook_png,
            hook_y=hook_y,
            hook_duration=args.hook_duration,
        )

        qa_ok, qa_info = qa_verify_clip(mp4_path, qa_dir)
        status_str = "PASS" if qa_ok else f"FAIL ({qa_info.get('issues')})"
        print(f"  QA [{mp4_path.name}]: {status_str} (dur={qa_info.get('duration')}s)")

        tt_cap = _append_tags(clip.get("video_description_for_tiktok", ""), args.extra_tags)
        ig_cap = _append_tags(clip.get("video_description_for_instagram", ""), args.extra_tags)
        caption = tt_cap or ig_cap or yt_title

        manifest.append(
            {
                "clip": mp4_path.name,
                "path": str(mp4_path),
                "hook": hook_text,
                "title": yt_title,
                "caption": caption,
                "pin": clip.get("pinned_comment", "") or "What did I just watch 😭🔥",
                "viralityScore": int(clip.get("predicted_score") or 0),
                "why": clip.get("why", ""),
                "onScreen": clip.get("on_screen", ""),
                "tiktokCaption": tt_cap,
                "instagramCaption": ig_cap,
                "youtubeTitle": yt_title,
                "sourceStart": round(abs_start, 2),
                "sourceEnd": round(abs_end, 2),
                "duration": qa_info.get("duration", clip.get("duration")),
                "qaPassed": qa_ok,
                "qaInfo": qa_info,
            }
        )

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nExported {len(manifest)} clips -> {manifest_path}")

    if args.publish in ("mobile-hub", "both"):
        _publish_mobile_hub(args, out_dir, manifest_path, manifest)
    if args.publish in ("postiz", "both"):
        _publish_postiz(manifest, out_dir)


if __name__ == "__main__":
    main()
