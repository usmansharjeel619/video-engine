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
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
SOURCES_FILE = REPO_ROOT / "manifests" / "auto_sources.json"
BATCH_ROOT = REPO_ROOT / "output" / "auto_batches"
STATE_FILE = BATCH_ROOT / "worker_state.json"

SLICE_SECONDS = 900  # 15-minute continuous slices keep disk & whisper fast
MIN_FREE_GB = 15.0
MAX_PENDING_QA_BATCHES = 18
DAILY_CLIP_TARGET = 45
MAX_SLICE_RETRIES = 2


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


def parse_m3u8_slice(
    m3u8_text: str,
    m3u8_url: str,
    start_s: int,
    end_s: int,
) -> tuple[list[str], list[tuple[str, str, str | None]], int]:
    """Parse an HLS playlist and return (header_lines, [(extinf, seg_url, map_url)], muted_count)."""
    base = m3u8_url.rsplit("/", 1)[0] + "/"
    headers: list[str] = []
    segs: list[tuple[str, str, str | None]] = []
    cur_t = 0.0
    cur_map: str | None = None
    last_inf: tuple[str, float] | None = None

    for ln in m3u8_text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#EXT-X-MAP:"):
            m = re.search(r'URI="([^"]+)"', s)
            if m:
                cur_map = urllib.parse.urljoin(base, m.group(1))
        elif s.startswith(("#EXTM3U", "#EXT-X-VERSION", "#EXT-X-TARGETDURATION", "#EXT-X-PLAYLIST-TYPE")):
            headers.append(s)
        elif s.startswith("#EXTINF:"):
            try:
                dur = float(s.split(":", 1)[1].split(",")[0])
            except ValueError:
                dur = 2.0
            last_inf = (s, dur)
        elif not s.startswith("#") and last_inf is not None:
            inf_ln, dur = last_inf
            seg_end = cur_t + dur
            if seg_end > start_s and cur_t < end_s:
                seg_url = urllib.parse.urljoin(base, s)
                segs.append((inf_ln, seg_url, cur_map))
            cur_t = seg_end
            last_inf = None

    muted_count = sum(1 for _, seg_url, _ in segs if "-muted" in seg_url)
    return headers, segs, muted_count


def _build_http_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(pool_connections=12, pool_maxsize=12, max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _download_slice_fast_hls(vod_url: str, start_s: int, end_s: int, out_mp4: Path) -> str:
    """
    Fast parallel 720p60 HLS segment downloader. Returns 'ok', 'muted_skip', or 'fallback'.
    Avoids ffmpeg remote HLS seek hangs on Twitch fMP4 / -muted.mp4 playlists.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "-g", "-f", "720p60/best[height<=720]/best", vod_url],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        m3u8_url = (proc.stdout or "").strip().splitlines()[0] if proc.returncode == 0 and proc.stdout.strip() else ""
        if not m3u8_url or ".m3u8" not in m3u8_url:
            return "fallback"

        session = _build_http_session()
        m3u8_resp = session.get(m3u8_url, timeout=20)
        m3u8_resp.raise_for_status()
        headers, segs, muted_count = parse_m3u8_slice(m3u8_resp.text, m3u8_url, start_s, end_s)
        if not segs:
            return "fallback"

        if muted_count / len(segs) >= 0.85:
            print(f"[worker] Skipping muted slice ({muted_count}/{len(segs)} muted segments) for {vod_url}")
            return "muted_skip"

        print(f"[worker] Fast parallel HLS ({len(segs)} segs, muted={muted_count}) -> {out_mp4.name}")
        with tempfile.TemporaryDirectory(prefix="hls_dl_") as tmpdir:
            tmp = Path(tmpdir)
            unique_urls: dict[str, Path] = {}
            for _, seg_url, map_url in segs:
                if map_url and map_url not in unique_urls:
                    idx = len(unique_urls)
                    unique_urls[map_url] = tmp / f"map_{idx}.mp4"
                if seg_url not in unique_urls:
                    ext = Path(urllib.parse.urlparse(seg_url).path).suffix or ".ts"
                    idx = len(unique_urls)
                    unique_urls[seg_url] = tmp / f"seg_{idx:04d}{ext}"

            def _fetch(item: tuple[str, Path]) -> None:
                url, dest = item
                r = session.get(url, timeout=(10, 30))
                r.raise_for_status()
                dest.write_bytes(r.content)

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(_fetch, unique_urls.items()))

            local_m3u8 = tmp / "slice.m3u8"
            out_lines = list(headers or ["#EXTM3U", "#EXT-X-VERSION:6"])
            prev_map: str | None = None
            for idx, (inf_ln, seg_url, map_url) in enumerate(segs):
                if map_url and map_url != prev_map:
                    if idx > 0:
                        out_lines.append("#EXT-X-DISCONTINUITY")
                    out_lines.append(f'#EXT-X-MAP:URI="{unique_urls[map_url].name}"')
                    prev_map = map_url
                out_lines.append(inf_ln)
                out_lines.append(unique_urls[seg_url].name)
            out_lines.append("#EXT-X-ENDLIST")
            local_m3u8.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

            remux = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-allowed_extensions",
                    "ALL",
                    "-i",
                    str(local_m3u8),
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(out_mp4),
                ],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if remux.returncode == 0 and out_mp4.exists() and out_mp4.stat().st_size > 1_000_000:
                return "ok"
            print(f"[worker] Local HLS remux failed ({remux.returncode}): {remux.stderr[:200]}")
            return "fallback"
    except Exception as exc:
        print(f"[worker] Fast HLS error ({exc}); falling back to yt-dlp.")
        return "fallback"


def _download_slice(vod_url: str, start_s: int, end_s: int, out_mp4: Path) -> str:
    """Download slice and return 'ok', 'muted_skip', or 'failed'."""
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    if out_mp4.exists():
        out_mp4.unlink()

    fast_status = _download_slice_fast_hls(vod_url, start_s, end_s, out_mp4)
    if fast_status in ("ok", "muted_skip"):
        return fast_status

    section = f"*{_fmt_hhmmss(start_s)}-{_fmt_hhmmss(end_s)}"
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--download-sections",
        section,
        "-f",
        "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best",
        "--merge-output-format",
        "mp4",
        "-o",
        str(out_mp4),
        vod_url,
    ]
    print(f"[worker] Fallback downloading {section} from {vod_url} -> {out_mp4}")
    try:
        proc = subprocess.run(cmd, timeout=360, check=False)
        if proc.returncode == 0 and out_mp4.exists() and out_mp4.stat().st_size > 1_000_000:
            return "ok"
    except subprocess.TimeoutExpired:
        print(f"[worker] Download timed out after 360s for {section}")
    return "failed"


def _utc_day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _surviving_clips_today(batch_root: Path, day_key: str | None = None) -> int:
    """Count non-rejected clips (.published or .ready_for_qa) from today's UTC date."""
    key = day_key or _utc_day_key()
    if not batch_root.exists():
        return 0
    total = 0
    for d in batch_root.iterdir():
        if not d.is_dir() or (d / ".qa_rejected").exists():
            continue
        marker = d / ".published" if (d / ".published").exists() else (d / ".ready_for_qa" if (d / ".ready_for_qa").exists() else None)
        if marker is None:
            continue
        mtime_day = datetime.fromtimestamp(marker.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
        if mtime_day != key:
            continue
        mf = d / "manifest.json"
        if mf.exists():
            try:
                items = json.loads(mf.read_text(encoding="utf-8"))
                total += len(items) if isinstance(items, list) else 1
                continue
            except Exception:
                pass
        total += 1
    return total


def _daily_clip_count(state: dict[str, Any], day_key: str | None = None, batch_root: Path | None = None) -> int:
    if batch_root is not None and batch_root.exists():
        return _surviving_clips_today(batch_root, day_key=day_key)
    key = day_key or _utc_day_key()
    return int((state.get("daily_clips") or {}).get(key, 0))


def _record_daily_clips(state: dict[str, Any], count: int, day_key: str | None = None) -> None:
    if count <= 0:
        return
    key = day_key or _utc_day_key()
    daily = state.setdefault("daily_clips", {})
    daily[key] = int(daily.get(key, 0)) + int(count)


def _run_slice_pipeline(
    source_mp4: Path,
    src_cfg: dict[str, Any],
    slice_label: str,
    batch_seq: int,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> tuple[bool, int]:
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
        "--no-trim-silence",
        "--no-ground-hooks",
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
        return True, len(passed_items)

    print(
        f"[worker] Slice {batch_id} finished (rc={proc.returncode}, clips={len(passed_items)}); "
        "cleaning up batch dir."
    )
    shutil.rmtree(out_dir, ignore_errors=True)
    return (proc.returncode == 0), 0


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
    today_clips = _daily_clip_count(state, batch_root=BATCH_ROOT)
    if today_clips >= DAILY_CLIP_TARGET:
        print(f"[worker] Daily surviving clip target reached ({today_clips}/{DAILY_CLIP_TARGET} clips today); pausing.")
        return False
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
            pipeline_ok, clip_count = _run_slice_pipeline(mp4, src_cfg, mp4.name, seq)
            if pipeline_ok:
                state["processed_slices"].append(key)
                _record_daily_clips(state, clip_count)
                state["batch_seq"] = seq + 1
            _save_state(state)
            return pipeline_ok

    # 2. Walk configured remote VOD/channel sources round-robin (1 slice per source per turn)
    if not sources:
        return False
    n_sources = len(sources)
    start_idx = int(state.get("next_source_idx", 0)) % n_sources

    for offset in range(n_sources):
        src_idx = (start_idx + offset) % n_sources
        src_cfg = sources[src_idx]
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
                    dl_status = _download_slice(vod_url, start_s, end_s, tmp_mp4)
                    if dl_status == "muted_skip":
                        pipeline_ok, clip_count = True, 0
                    elif dl_status == "ok":
                        pipeline_ok, clip_count = _run_slice_pipeline(tmp_mp4, src_cfg, label, seq)
                    else:
                        pipeline_ok, clip_count = False, 0

                    if tmp_mp4.exists():
                        tmp_mp4.unlink()

                    retries = state.setdefault("dl_retries", {})
                    if pipeline_ok:
                        state["processed_slices"].append(slice_key)
                        retries.pop(slice_key, None)
                        _record_daily_clips(state, clip_count)
                        state["batch_seq"] = seq + 1
                    else:
                        retries[slice_key] = int(retries.get(slice_key, 0)) + 1
                        if retries[slice_key] >= MAX_SLICE_RETRIES:
                            print(f"[worker] Skipping persistently failing slice {slice_key} after {retries[slice_key]} tries.")
                            state["processed_slices"].append(slice_key)
                    state["next_source_idx"] = (src_idx + 1) % n_sources
                    _save_state(state)
                    return pipeline_ok
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
