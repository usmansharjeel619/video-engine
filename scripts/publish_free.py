#!/usr/bin/env python3
"""
100% FREE Multi-Platform Auto-Publisher (No Paid SaaS).
Supports:
  - YouTube Shorts: Official YouTube Data API v3 (OAuth2 refresh token)
  - Instagram Reels: instagrapi (session-cached login)
  - TikTok: tiktok-uploader (cookie-based free uploader, if installed)
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any


def load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def upload_youtube_short(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    client_secrets: Path,
    token_path: Path,
    privacy: str = "public",
) -> dict[str, Any]:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not client_secrets.exists():
                raise FileNotFoundError(
                    f"Missing YouTube OAuth client secrets file: {client_secrets}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), scopes)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": "24",  # Entertainment
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()
    video_id = response.get("id")
    return {"id": video_id, "url": f"https://youtube.com/shorts/{video_id}"}


def upload_instagram_reel(
    video_path: Path,
    caption: str,
    username: str,
    password: str,
    session_path: Path,
) -> dict[str, Any]:
    from instagrapi import Client

    cl = Client()
    if session_path.exists():
        cl.load_settings(session_path)
    cl.login(username, password)
    cl.dump_settings(session_path)

    media = cl.clip_upload(video_path, caption=caption)
    code = getattr(media, "code", None)
    return {
        "pk": str(getattr(media, "pk", "")),
        "url": f"https://www.instagram.com/reel/{code}/" if code else "",
    }


def upload_tiktok_free(
    video_path: Path,
    description: str,
    cookies_path: Path,
) -> dict[str, Any]:
    from tiktok_uploader.upload import upload_video

    if not cookies_path.exists():
        raise FileNotFoundError(f"Missing TikTok cookies file: {cookies_path}")
    failed = upload_video(
        str(video_path),
        description=description,
        cookies=str(cookies_path),
        headless=True,
    )
    return {"status": "failed" if failed else "uploaded", "failed": failed}


def main() -> None:
    parser = argparse.ArgumentParser(description="100% Free Multi-Platform Shorts/Reels/TikTok Publisher.")
    parser.add_argument("--manifest", "-m", type=Path, required=True, help="Path to manifest_polished.json.")
    parser.add_argument(
        "--platforms",
        nargs="+",
        default=["youtube", "instagram"],
        choices=["youtube", "instagram", "tiktok"],
        help="Platforms to publish to (default: youtube instagram).",
    )
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"], help="YouTube privacy.")
    parser.add_argument("--auth-youtube", action="store_true", help="Run 1-time YouTube OAuth login and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Preview uploads without posting.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    load_env(repo_root / ".env")
    creds_dir = repo_root / ".creds"
    creds_dir.mkdir(exist_ok=True)

    yt_secrets = Path(os.getenv("YOUTUBE_CLIENT_SECRETS", creds_dir / "youtube_client_secret.json"))
    yt_token = Path(os.getenv("YOUTUBE_TOKEN_PATH", creds_dir / "youtube_token.json"))
    ig_session = Path(os.getenv("IG_SESSION_PATH", creds_dir / "ig_session.json"))
    tt_cookies = Path(os.getenv("TIKTOK_COOKIES_PATH", creds_dir / "tiktok_cookies.txt"))

    if args.auth_youtube:
        from google_auth_oauthlib.flow import InstalledAppFlow
        if not yt_secrets.exists():
            raise FileNotFoundError(f"Put your Google OAuth JSON at: {yt_secrets}")
        flow = InstalledAppFlow.from_client_secrets_file(
            str(yt_secrets), ["https://www.googleapis.com/auth/youtube.upload"]
        )
        creds = flow.run_local_server(port=0)
        yt_token.write_text(creds.to_json(), encoding="utf-8")
        print(f"YouTube OAuth token saved -> {yt_token}")
        return

    manifest: list[dict[str, Any]] = json.loads(args.manifest.read_text(encoding="utf-8"))
    results = []

    for item in manifest:
        video_path = Path(item["path"])
        caption = item.get("transcript", "").strip()
        title = caption.split("#")[0].strip() or video_path.stem
        tags = [w.lstrip("#") for w in caption.split() if w.startswith("#")] or ["IShowSpeed", "Expedia", "Shorts"]

        if args.dry_run:
            print(f"[DRY RUN] {video_path.name} -> {args.platforms}\n  Title: {title}\n  Caption: {caption}\n")
            results.append({"clip": video_path.name, "status": "dry-run"})
            continue

        clip_res: dict[str, Any] = {"clip": video_path.name, "platforms": {}}

        if "youtube" in args.platforms:
            clip_res["platforms"]["youtube"] = upload_youtube_short(
                video_path, title, caption, tags, yt_secrets, yt_token, privacy=args.privacy
            )
            print(f"[YouTube] {video_path.name} -> {clip_res['platforms']['youtube']}")

        if "instagram" in args.platforms:
            ig_user = os.environ["IG_USERNAME"]
            ig_pass = os.environ["IG_PASSWORD"]
            clip_res["platforms"]["instagram"] = upload_instagram_reel(
                video_path, caption, ig_user, ig_pass, ig_session
            )
            print(f"[Instagram] {video_path.name} -> {clip_res['platforms']['instagram']}")

        if "tiktok" in args.platforms:
            clip_res["platforms"]["tiktok"] = upload_tiktok_free(video_path, caption, tt_cookies)
            print(f"[TikTok] {video_path.name} -> {clip_res['platforms']['tiktok']}")

        results.append(clip_res)

    out_log = args.manifest.parent / "publish_free_results.json"
    out_log.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"Saved results -> {out_log}")


if __name__ == "__main__":
    main()
