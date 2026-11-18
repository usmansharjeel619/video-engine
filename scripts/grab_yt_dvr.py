#!/usr/bin/env python3
"""
Download any exact time window [start-sec, end-sec] from a live YouTube DVR stream
using DASH sequence fragments (sq=0 is stream start t=0:00:00, 2s per fragment).
Produces a clean, zero-PTS-offset MP4 with locked A/V sync.
"""

import argparse
import concurrent.futures
import json
import subprocess
import sys
import urllib.request
from pathlib import Path


def fetch_fragment(url: str, headers: dict[str, str], sq: int) -> tuple[int, bytes]:
    req = urllib.request.Request(f"{url}&sq={sq}", headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return sq, resp.read()


def download_stream_tracks(
    url: str,
    headers: dict[str, str],
    sq_start: int,
    sq_end: int,
    out_path: Path,
    workers: int = 8,
) -> None:
    indices = list(range(sq_start, sq_end + 1))
    chunks: dict[int, bytes] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(fetch_fragment, url, headers, sq) for sq in indices]
        for fut in concurrent.futures.as_completed(futs):
            sq, data = fut.result()
            chunks[sq] = data

    with out_path.open("wb") as f:
        for sq in indices:
            f.write(chunks[sq])


def main() -> None:
    parser = argparse.ArgumentParser(description="Grab exact time range from YouTube live DVR stream.")
    parser.add_argument("--url", required=True, help="YouTube live/DVR URL.")
    parser.add_argument("--start-min", type=float, default=0.0, help="Start minute from stream beginning.")
    parser.add_argument("--end-min", type=float, default=12.0, help="End minute from stream beginning.")
    parser.add_argument("--output", "-o", type=Path, required=True, help="Output MP4 path.")
    args = parser.parse_args()

    print(f"Resolving DASH DVR streams for {args.url}...")
    raw = subprocess.check_output(
        [sys.executable, "-m", "yt_dlp", "--live-from-start", "-j", "-f", "299+140", args.url],
        stderr=subprocess.DEVNULL,
    )
    info = json.loads(raw)
    fmts = {f["format_id"]: f for f in info["requested_formats"]}

    sq_start = max(0, int(args.start_min * 60 / 2))
    sq_end = max(sq_start + 1, int(args.end_min * 60 / 2))
    print(f"Downloading sq={sq_start}..{sq_end} ({args.start_min}m -> {args.end_min}m)...")

    out_mp4: Path = args.output.resolve()
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    v_tmp = out_mp4.with_suffix(".video.mp4")
    a_tmp = out_mp4.with_suffix(".audio.m4a")

    download_stream_tracks(fmts["299"]["url"], fmts["299"].get("http_headers", {}), sq_start, sq_end, v_tmp)
    download_stream_tracks(fmts["140"]["url"], fmts["140"].get("http_headers", {}), sq_start, sq_end, a_tmp)

    print("Muxing clean A/V-locked MP4...")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-fflags",
            "+genpts",
            "-i",
            str(v_tmp),
            "-i",
            str(a_tmp),
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ],
        check=True,
    )
    v_tmp.unlink(missing_ok=True)
    a_tmp.unlink(missing_ok=True)
    print(f"Saved clean DVR slice -> {out_mp4}")


if __name__ == "__main__":
    main()
