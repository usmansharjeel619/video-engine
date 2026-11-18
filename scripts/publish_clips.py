#!/usr/bin/env python3
"""
Automated Multi-Platform Publisher for Content Rewards Clips.
Reads manifest.json produced by clip_engine.py and publishes clips to
TikTok, Instagram Reels, and YouTube Shorts via Upload-Post or Postiz API.
"""

import argparse
import json
import os
import urllib.request
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


def build_caption(transcript: str, extra_tags: list[str]) -> str:
    words = transcript.strip().split()
    hook = " ".join(words[:35]).rstrip(".,!?")
    if len(words) > 35:
        hook += "..."
    tags = " ".join(f"#{t.lstrip('#')}" for t in extra_tags if t.strip() and f"#{t.lstrip('#').lower()}" not in hook.lower())
    return f"{hook}\n\n{tags}".strip()


def publish_upload_post(
    video_path: Path,
    title: str,
    platforms: list[str],
    api_key: str,
    profile_user: str,
) -> dict[str, Any]:
    from upload_post import UploadPostClient

    client = UploadPostClient(api_key)
    return client.upload_video(
        str(video_path),
        title=title,
        user=profile_user,
        platforms=platforms,
    )


def fetch_postiz_integrations(base_url: str, api_key: str) -> list[dict[str, Any]]:
    """Fetch connected social integrations from Postiz public API."""
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/public/v1/integrations",
        headers={"Authorization": api_key},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, list):
            return data
        return list(data.get("integrations") or [])


def publish_postiz(
    video_path: Path,
    caption: str,
    base_url: str,
    api_key: str,
    integration_ids: list[str],
) -> dict[str, Any]:
    """Upload video to Postiz public API and schedule immediate post."""
    import mimetypes
    import uuid

    boundary = f"----AntigravityBoundary{uuid.uuid4().hex}"
    mime = mimetypes.guess_type(str(video_path))[0] or "video/mp4"
    file_bytes = video_path.read_bytes()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{video_path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    upload_req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/public/v1/upload",
        data=body,
        headers={
            "Authorization": api_key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(upload_req, timeout=120) as resp:
        media = json.loads(resp.read().decode("utf-8"))

    post_payload = json.dumps(
        {
            "type": "now",
            "shortLink": False,
            "tags": [],
            "posts": [
                {
                    "integration": {"id": iid},
                    "value": [{"content": caption, "image": [media]}],
                }
                for iid in integration_ids
            ],
        }
    ).encode("utf-8")

    post_req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/public/v1/posts",
        data=post_payload,
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(post_req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-publish clipped videos from manifest.json.")
    parser.add_argument("--manifest", "-m", type=Path, required=True, help="Path to manifest.json.")
    parser.add_argument(
        "--platforms",
        nargs="+",
        default=["tiktok", "instagram", "youtube"],
        help="Target platforms (default: tiktok instagram youtube).",
    )
    parser.add_argument(
        "--tags",
        nargs="+",
        default=["shorts", "viral", "clips"],
        help="Hashtags to append to captions.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without publishing.")
    args = parser.parse_args()

    load_env(Path(__file__).resolve().parent.parent / ".env")
    manifest: list[dict[str, Any]] = json.loads(args.manifest.read_text(encoding="utf-8"))
    provider = os.getenv("PUBLISH_PROVIDER", "upload-post").lower()

    results = []
    for item in manifest:
        video_path = Path(item["path"])
        preferred = (
            item.get("tiktokCaption")
            or item.get("instagramCaption")
            or item.get("caption")
            or item.get("youtubeTitle")
            or item.get("title")
        )
        if preferred and str(preferred).strip():
            caption = str(preferred).strip()
        else:
            caption = build_caption(item.get("transcript", ""), args.tags)

        if args.dry_run:
            print(f"[DRY RUN] {video_path.name} -> {args.platforms}\n{caption}\n")
            results.append({"clip": video_path.name, "status": "dry-run", "caption": caption})
            continue

        if provider == "upload-post":
            api_key = os.environ["UPLOAD_POST_API_KEY"]
            user = os.environ["UPLOAD_POST_USER"]
            res = publish_upload_post(video_path, caption, args.platforms, api_key, user)
        elif provider == "postiz":
            base_url = os.getenv("POSTIZ_BASE_URL") or os.getenv("POSTIZ_URL") or "http://127.0.0.1:4008"
            api_key = os.environ["POSTIZ_API_KEY"]
            raw_ids = os.getenv("POSTIZ_INTEGRATION_IDS", "")
            ids = [i.strip() for i in raw_ids.split(",") if i.strip()]
            if not ids:
                integrations = fetch_postiz_integrations(base_url, api_key)
                ids = [str(it["id"]) for it in integrations if it.get("id")]
            if not ids:
                raise RuntimeError("No Postiz integrations found. Connect social accounts in Postiz first.")
            res = publish_postiz(video_path, caption, base_url, api_key, ids)
        else:
            raise ValueError(f"Unsupported PUBLISH_PROVIDER: {provider}")

        print(f"Published {video_path.name}: {res}")
        results.append({"clip": video_path.name, "status": "published", "response": res})

    out_log = args.manifest.parent / "publish_results.json"
    out_log.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"Saved publish log -> {out_log}")


if __name__ == "__main__":
    main()
