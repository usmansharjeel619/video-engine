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
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def default_cookies_path() -> Path | None:
    cand = REPO_ROOT / ".creds" / "youtube_cookies.txt"
    return cand if cand.exists() else None


def _make_session(proxy: str | None) -> Any:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    sess = requests.Session()
    retry = Retry(total=4, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    return sess


def fetch_fragment(url: str, headers: dict[str, str], sq: int, session: Any = None) -> tuple[int, bytes]:
    frag_url = f"{url}&sq={sq}"
    if session is not None:
        resp = session.get(frag_url, headers=headers, timeout=25)
        resp.raise_for_status()
        return sq, resp.content
    req = urllib.request.Request(frag_url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return sq, resp.read()


def download_stream_tracks(
    url: str,
    headers: dict[str, str],
    sq_start: int,
    sq_end: int,
    out_path: Path,
    workers: int = 8,
    proxy: str | None = None,
) -> None:
    indices = list(range(sq_start, sq_end + 1))
    chunks: dict[int, bytes] = {}
    session = _make_session(proxy) if proxy else None
    eff_workers = min(workers, 3) if proxy else workers
    with concurrent.futures.ThreadPoolExecutor(max_workers=eff_workers) as pool:
        futs = [pool.submit(fetch_fragment, url, headers, sq, session) for sq in indices]
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
    parser.add_argument("--cookies", type=Path, default=None, help="Optional Netscape cookies.txt for yt-dlp.")
    parser.add_argument("--proxy", default=None, help="Optional HTTP/SOCKS5 proxy URL (e.g. socks5h://127.0.0.1:1080).")
    args = parser.parse_args()

    import os
    proxy = args.proxy or (os.environ.get("YTDLP_PROXY") or "").strip() or None
    cookies = args.cookies if args.cookies is not None else default_cookies_path()
    cmd = [sys.executable, "-m", "yt_dlp", "--live-from-start"]
    if proxy:
        cmd.extend(["--proxy", proxy])
    if cookies and cookies.exists() and not proxy:
        cmd.extend(["--cookies", str(cookies)])
    cmd.extend(["-j", "-f", "299+140", args.url])

    print(f"Resolving DASH DVR streams for {args.url}...")
    raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
    info = json.loads(raw)
    fmts = {f["format_id"]: f for f in info["requested_formats"]}

    sq_start = max(0, int(args.start_min * 60 / 2))
    sq_end = max(sq_start + 1, int(args.end_min * 60 / 2))
    print(f"Downloading sq={sq_start}..{sq_end} ({args.start_min}m -> {args.end_min}m)...")

    out_mp4: Path = args.output.resolve()
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    v_tmp = out_mp4.with_suffix(".video.mp4")
    a_tmp = out_mp4.with_suffix(".audio.m4a")

    download_stream_tracks(fmts["299"]["url"], fmts["299"].get("http_headers", {}), sq_start, sq_end, v_tmp, proxy=proxy)
    download_stream_tracks(fmts["140"]["url"], fmts["140"].get("http_headers", {}), sq_start, sq_end, a_tmp, proxy=proxy)

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
