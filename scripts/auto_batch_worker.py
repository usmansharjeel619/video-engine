#!/usr/bin/env python3
"""
Zero-Codex-Credit Continuous Batch Worker.

Runs sequentially in the background on the cloud server (`clip-worker`),
downloading bounded 15-minute slices from configured Twitch/local stream sources,
running viral_pipeline.py (--min-virality 80 --min-hook-score 85), cleaning up
heavy temp source files, and dropping `.ready_for_qa` markers so the scheduled
every-2-hour Codex QA cron only spends credits when new verified clips are ready.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
SOURCES_FILE = REPO_ROOT / "manifests" / "auto_sources.json"
BATCH_ROOT = REPO_ROOT / "output" / "auto_batches"
STATE_FILE = BATCH_ROOT / "worker_state.json"

SLICE_SECONDS = 900  # 15-minute continuous slices keep disk & whisper fast
MIN_FREE_GB = 15.0
MAX_PENDING_QA_BATCHES = 15


def _load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"processed_slices": [], "batch_seq": 1}


def _save_state(state: dict[str, Any]) -> None:
    BATCH_ROOT.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _fmt_hhmmss(sec: int) -> str:
    h, rem = divmod(max(0, int(sec)), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _free_disk_gb() -> float:
    return shutil.disk_usage(str(REPO_ROOT)).free / (1024.0**3)


def _pending_qa_count() -> int:
    if not BATCH_ROOT.exists():
        return 0
    return sum(1 for _ in BATCH_ROOT.glob("*/.ready_for_qa"))


def _probe_vods(url: str, max_items: int = 3) -> list[dict[str, Any]]:
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--skip-download",
        "--flat-playlist",
        "--playlist-items",
        f"1-{max_items}",
        "--dump-single-json",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    data = json.loads(proc.stdout)
    if "entries" in data and isinstance(data["entries"], list):
        return [e for e in data["entries"] if e]
    return [data]


def _get_duration(vod_url: str) -> float:
    proc = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--skip-download", "--print", "%(duration)s", vod_url],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return float((proc.stdout or "0").strip().splitlines()[-1])
    except Exception:
        return 0.0


def _download_slice(vod_url: str, start_s: int, end_s: int, out_mp4: Path) -> bool:
    section = f"*{_fmt_hhmmss(start_s)}-{_fmt_hhmmss(end_s)}"
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    if out_mp4.exists():
        out_mp4.unlink()
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--download-sections",
        section,
        "-f",
        "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
        "--merge-output-format",
        "mp4",
        "-o",
        str(out_mp4),
        vod_url,
    ]
    print(f"[worker] Downloading {section} from {vod_url} -> {out_mp4}")
    proc = subprocess.run(cmd, check=False)
    return proc.returncode == 0 and out_mp4.exists() and out_mp4.stat().st_size > 1_000_000


def _run_slice_pipeline(
    source_mp4: Path,
    src_cfg: dict[str, Any],
    slice_label: str,
    batch_seq: int,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> tuple[bool, bool]:
    slug = src_cfg.get("slug", "stream")
    batch_id = f"{slug}_auto_{batch_seq:03d}"
    out_dir = BATCH_ROOT / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-u",
        str(SCRIPTS_DIR / "viral_pipeline.py"),
        "--input",
        str(source_mp4),
        "--output-dir",
        str(out_dir),
        "--layout",
        src_cfg.get("layout", "split"),
        "--cam-pos",
        src_cfg.get("cam_pos", "auto"),
        "--hook-style",
        src_cfg.get("hook_style", "pill"),
        "--caption-preset",
        src_cfg.get("caption_preset", "hormozi"),
        "--model",
        src_cfg.get("whisper_model", "small"),
        "--min-duration",
        str(src_cfg.get("min_duration", 18)),
        "--max-duration",
        str(src_cfg.get("max_duration", 45)),
        "--top-n",
        str(src_cfg.get("top_n", 4)),
        "--min-virality",
        str(src_cfg.get("min_virality", 80)),
        "--min-hook-score",
        str(src_cfg.get("min_hook_score", 85)),
        "--publish",
        "none",
    ]
    if start_ts:
        cmd.extend(["--start", start_ts])
    if end_ts:
        cmd.extend(["--end", end_ts])
    if src_cfg.get("instructions"):
        cmd.extend(["--instructions", src_cfg["instructions"]])
    if src_cfg.get("extra_tags"):
        cmd.extend(["--extra-tags", *src_cfg["extra_tags"]])

    print(f"[worker] Running viral_pipeline on {batch_id} ({slice_label})...")
    proc = subprocess.run(cmd, check=False)

    manifest_path = out_dir / "manifest.json"
    passed_items = []
    if manifest_path.exists():
        try:
            items = json.loads(manifest_path.read_text(encoding="utf-8"))
            passed_items = [i for i in items if i.get("qaPassed")]
        except Exception:
            passed_items = []

    # Clean heavy temporary audio/source caches regardless of hit count
    work_dir = out_dir / ".work"
    for tmp_name in ("audio_16k.wav", "source.mp4"):
        tmp_f = work_dir / tmp_name
        if tmp_f.exists():
            tmp_f.unlink()

    if proc.returncode == 0 and passed_items:
        marker = {
            "batch_id": batch_id,
            "folder": src_cfg.get("folder", "Auto Stream Clips"),
            "subtitle": src_cfg.get("subtitle", "Auto-Clipped Viral Highlights"),
            "batch_label": f"{src_cfg.get('batch_prefix', 'Batch')} #{batch_seq} ({slice_label}, {len(passed_items)} clips)",
            "release_tag": batch_id.replace("_", "-"),
            "clip_count": len(passed_items),
            "slice_label": slice_label,
        }
        (out_dir / ".ready_for_qa").write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
        print(f"[worker] Queued {batch_id} for Codex QA ({len(passed_items)} QA-passed clips).")
        return True, True

    print(
        f"[worker] Slice {batch_id} finished (rc={proc.returncode}, clips={len(passed_items)}); "
        "cleaning up batch dir."
    )
    shutil.rmtree(out_dir, ignore_errors=True)
    return (proc.returncode == 0), False


def process_one_iteration() -> bool:
    """Discover and process the next unclipped 15m slice. Returns True if work was done."""
    if _free_disk_gb() < MIN_FREE_GB:
        print(f"[worker] Low disk space ({_free_disk_gb():.1f}G < {MIN_FREE_GB}G); pausing.")
        return False
    if _pending_qa_count() >= MAX_PENDING_QA_BATCHES:
        print(f"[worker] {_pending_qa_count()} batches already waiting for Codex QA; pausing.")
        return False
    if not SOURCES_FILE.exists():
        print(f"[worker] Missing {SOURCES_FILE}")
        return False

    sources = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    state = _load_state()
    done_set = set(state.get("processed_slices", []))

    # 1. Process any locally staged MP4s first
    staged_dir = REPO_ROOT / "output" / "gta6-streams"
    if staged_dir.exists():
        for mp4 in sorted(staged_dir.glob("*.mp4")):
            key = f"local:{mp4.name}"
            if key in done_set:
                continue
            src_cfg = {
                "slug": mp4.stem.lower()[:20],
                "folder": "IShowSpeed — GTA 6",
                "subtitle": "Split-Screen Facecam + Gameplay · Outclass Hooks",
                "batch_prefix": "Auto Batch",
                "cam_pos": "auto",
                "instructions": "ONLY pick explosive, hilarious, or jaw-dropping GTA 6 moments where seconds 0-2 immediately stop a scroller.",
                "extra_tags": ["IShowSpeed", "GTA6", "GTAVI", "Gaming"],
            }
            seq = int(state.get("batch_seq", 1))
            pipeline_ok, _ = _run_slice_pipeline(mp4, src_cfg, mp4.name, seq)
            if pipeline_ok:
                state["processed_slices"].append(key)
            state["batch_seq"] = seq + 1
            _save_state(state)
            return True

    # 2. Walk configured remote VOD/channel sources in 15-minute slices
    for src_cfg in sources:
        if not src_cfg.get("enabled", True):
            continue
        entries = _probe_vods(src_cfg["url"], max_items=int(src_cfg.get("max_vods", 2)))
        for entry in entries:
            vod_url = entry.get("webpage_url") or entry.get("url")
            vod_id = str(entry.get("id") or vod_url)
            if not vod_url:
                continue
            title_filter = (src_cfg.get("title_contains") or "").strip().lower()
            title = str(entry.get("title") or "").lower()
            if title_filter and title_filter not in title:
                continue

            dur = float(entry.get("duration") or 0.0) or _get_duration(vod_url)
            if dur < 120:
                continue

            start_s = 0
            while start_s + 120 < dur:
                end_s = min(int(dur), start_s + SLICE_SECONDS)
                slice_key = f"{vod_id}:{start_s}-{end_s}"
                if slice_key not in done_set:
                    seq = int(state.get("batch_seq", 1))
                    tmp_mp4 = BATCH_ROOT / f"_dl_{vod_id}_{start_s}.mp4"
                    label = f"{_fmt_hhmmss(start_s)}–{_fmt_hhmmss(end_s)}"
                    if _download_slice(vod_url, start_s, end_s, tmp_mp4):
                        pipeline_ok, _ = _run_slice_pipeline(tmp_mp4, src_cfg, label, seq)
                    else:
                        pipeline_ok = False
                    if tmp_mp4.exists():
                        tmp_mp4.unlink()
                    if pipeline_ok:
                        state["processed_slices"].append(slice_key)
                    state["batch_seq"] = seq + 1
                    _save_state(state)
                    return True
                start_s += SLICE_SECONDS

    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuous zero-Codex-credit viral clip batch worker.")
    parser.add_argument("--once", action="store_true", help="Process at most one slice and exit.")
    parser.add_argument("--idle-sleep", type=int, default=900, help="Seconds to sleep when no new slices or awaiting QA (default: 900).")
    args = parser.parse_args()

    while True:
        try:
            did_work = process_one_iteration()
        except Exception as exc:
            print(f"[worker] Iteration error: {exc}")
            did_work = False

        if args.once:
            break
        time.sleep(20 if did_work else args.idle_sleep)


if __name__ == "__main__":
    main()
