#!/usr/bin/env python3
"""
Buffer GraphQL Multi-Platform Auto-Scheduler.

Connects to Buffer's official GraphQL API (https://api.buffer.com) using BUFFER_API_KEY,
discovers connected TikTok / Instagram / YouTube channels, respects Buffer Free's
10-queued-posts-per-channel limit (or Essentials higher queues) plus YouTube's
9/rolling-24h cap, and schedules verified GitHub Release MP4 clips cleanly.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from socialclaw_publish import (
    DEFAULT_DAILY_CAP,
    DEFAULT_SPACING_MINUTES,
    _ensure_shorts_suffix,
    compute_next_slot,
    provider_daily_cap,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / "output" / "buffer_state.json"
BUFFER_API_URL = "https://api.buffer.com"
DEFAULT_MAX_QUEUE = 10  # Buffer Free plan caps concurrent queued posts at 10 per channel


def _load_env() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _api_key() -> str:
    _load_env()
    key = (os.environ.get("BUFFER_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("BUFFER_API_KEY is not set in environment or .env.")
    return key


def _gql(
    session: requests.Session,
    api_key: str,
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = session.post(
        BUFFER_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=45,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(f"Buffer GraphQL error: {json.dumps(data['errors'])[:400]}")
    return data.get("data") or {}


def _load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"scheduled": {}}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _normalize_service(service: str | None) -> str:
    s = (service or "").strip().lower()
    if "tiktok" in s:
        return "tiktok"
    if "instagram" in s:
        return "instagram"
    if "youtube" in s:
        return "youtube"
    return s


def fetch_buffer_channels(session: requests.Session, api_key: str) -> list[dict[str, Any]]:
    orgs = _gql(
        session,
        api_key,
        "query { account { organizations { id name } } }",
    ).get("account", {}).get("organizations", [])
    channels: list[dict[str, Any]] = []
    for org in orgs:
        org_id = str(org["id"]).replace('"', "")
        res = _gql(
            session,
            api_key,
            f'query {{ channels(input: {{ organizationId: "{org_id}" }}) {{ id name displayName service isQueuePaused }} }}',
        )
        for ch in res.get("channels", []):
            ch["organizationId"] = org_id
            ch["provider"] = _normalize_service(ch.get("service"))
            channels.append(ch)
    return channels


def build_buffer_create_input(
    provider: str,
    channel_id: str,
    item: dict[str, Any],
    video_url: str,
    due_at_iso: str,
) -> dict[str, Any]:
    base_caption = str(item.get("caption") or item.get("title") or "").strip()
    if provider == "tiktok":
        text = str(item.get("tiktokCaption") or base_caption).strip()[:2200]
        metadata = {"tiktok": {"isAiGenerated": False}}
    elif provider == "instagram":
        text = str(item.get("instagramCaption") or base_caption).strip()[:2200]
        metadata = {"instagram": {"type": "reel", "shouldShareToFeed": True}}
    elif provider == "youtube":
        raw_title = str(item.get("youtubeTitle") or item.get("title") or "GTA 6 Highlight")
        yt_title = _ensure_shorts_suffix(raw_title, max_len=100)
        text = base_caption[:5000]
        metadata = {
            "youtube": {
                "title": yt_title,
                "categoryId": "20",
                "privacy": "public",
                "madeForKids": False,
                "isAiGenerated": False,
                "notifySubscribers": True,
                "embeddable": True,
            }
        }
    else:
        text = base_caption[:2000]
        metadata = {}

    return {
        "channelId": channel_id,
        "text": text,
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": due_at_iso,
        "assets": [
            {
                "video": {
                    "url": video_url,
                    "metadata": {"thumbnailOffset": 1500},
                }
            }
        ],
        "metadata": metadata,
    }


def _create_buffer_post(session: requests.Session, api_key: str, post_input: dict[str, Any]) -> dict[str, Any]:
    mutation = """
    mutation CreateVideoPost($input: CreatePostInput!) {
      createPost(input: $input) {
        __typename
        ... on PostActionSuccess {
          post { id dueAt status }
        }
        ... on MutationError {
          message
        }
      }
    }
    """
    data = _gql(session, api_key, mutation, variables={"input": post_input})
    res = data.get("createPost") or {}
    if res.get("__typename") == "MutationError" or res.get("message"):
        raise RuntimeError(f"Buffer createPost error: {res.get('message')}")
    return res.get("post") or res


def publish_to_buffer(
    manifest_items: list[tuple[str, dict[str, Any], str]],
    max_queue_per_channel: int = DEFAULT_MAX_QUEUE,
    daily_cap: int = DEFAULT_DAILY_CAP,
    spacing_minutes: int = DEFAULT_SPACING_MINUTES,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Schedule clip entries [(batch_key, item, public_mp4_url)] across connected Buffer channels."""
    api_key = _api_key()
    session = requests.Session()
    channels = fetch_buffer_channels(session, api_key)
    by_provider = {
        ch["provider"]: ch for ch in channels if ch.get("provider") in ("tiktok", "instagram", "youtube")
    }
    state = _load_state()
    now_utc = datetime.now(timezone.utc)

    # Track active future scheduled timestamps per provider from state
    future_by_prov: dict[str, list[datetime]] = {}
    all_times_by_prov: dict[str, list[datetime]] = {}
    for _, rec in state.get("scheduled", {}).items():
        prov = rec.get("provider")
        raw_due = rec.get("dueAt", "")
        if not prov or not raw_due:
            continue
        try:
            dt = datetime.fromisoformat(raw_due.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            continue
        all_times_by_prov.setdefault(prov, []).append(dt)
        if dt > now_utc:
            future_by_prov.setdefault(prov, []).append(dt)

    out: dict[str, Any] = {"ok": True, "channels": list(by_provider.keys()), "scheduled_count": 0, "posts": []}
    for batch_key, item, mp4_url in manifest_items:
        clip_name = str(item.get("clip") or "").strip()
        if not clip_name or item.get("qaPassed") is False:
            continue

        for prov, ch in by_provider.items():
            dedup_key = f"{batch_key}:{clip_name}:{prov}"
            if dedup_key in state.get("scheduled", {}):
                continue
            queued_now = future_by_prov.setdefault(prov, [])
            if max_queue_per_channel > 0 and len(queued_now) >= max_queue_per_channel:
                continue

            prov_times = all_times_by_prov.setdefault(prov, [])
            slot_dt = compute_next_slot(
                prov_times,
                now_utc=now_utc,
                spacing_minutes=spacing_minutes,
                daily_cap=provider_daily_cap(prov, daily_cap),
            )
            slot_iso = slot_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            post_input = build_buffer_create_input(prov, ch["id"], item, mp4_url, slot_iso)
            if dry_run:
                out["posts"].append({"provider": prov, "clip": clip_name, "dueAt": slot_iso, "dry_run": True})
                prov_times.append(slot_dt)
                queued_now.append(slot_dt)
                continue

            try:
                created = _create_buffer_post(session, api_key, post_input)
            except Exception as exc:
                print(f"[Buffer] WARN {prov}/{clip_name}: {exc}")
                out["posts"].append({"provider": prov, "clip": clip_name, "error": str(exc)})
                continue

            state.setdefault("scheduled", {})[dedup_key] = {
                "provider": prov,
                "channelId": ch["id"],
                "postId": created.get("id"),
                "dueAt": created.get("dueAt") or slot_iso,
                "videoUrl": mp4_url,
            }
            _save_state(state)
            prov_times.append(slot_dt)
            queued_now.append(slot_dt)
            out["scheduled_count"] += 1
            out["posts"].append({"provider": prov, "clip": clip_name, "dueAt": slot_iso, "status": "scheduled"})
            print(f"[Buffer] Scheduled {prov} | {clip_name} @ {slot_iso}")

    return out


def _collect_from_hub_config() -> list[tuple[str, dict[str, Any], str]]:
    cfg_path = REPO_ROOT / "manifests" / "hub_config.json"
    if not cfg_path.exists():
        return []
    folders = json.loads(cfg_path.read_text(encoding="utf-8"))
    collected: list[tuple[str, dict[str, Any], str]] = []
    for folder in folders:
        for batch in folder.get("batches", []):
            base_url = str(batch.get("baseUrl") or "").rstrip("/")
            mf = REPO_ROOT / str(batch.get("manifest") or "")
            if not base_url or not mf.exists():
                continue
            bkey = mf.stem
            items = json.loads(mf.read_text(encoding="utf-8"))
            for item in items:
                clip = str(item.get("clip") or "").strip()
                if clip:
                    collected.append((bkey, item, f"{base_url}/{clip}"))
    return collected


def main() -> None:
    parser = argparse.ArgumentParser(description="Schedule verified clips across Buffer connected channels.")
    parser.add_argument("--check", action="store_true", help="Verify Buffer API auth and list connected channels.")
    parser.add_argument("--manifest", "-m", type=Path, help="Manifest JSON to schedule.")
    parser.add_argument("--release-base-url", default="", help="Public HTTPS base URL hosting the MP4s.")
    parser.add_argument("--refill-from-hub", action="store_true", help="Top up open Buffer slots from manifests/hub_config.json.")
    parser.add_argument("--max-queue", type=int, default=DEFAULT_MAX_QUEUE, help="Max concurrent future queued posts per channel (10 on Buffer Free, 0=unlimited).")
    parser.add_argument("--daily-cap", type=int, default=DEFAULT_DAILY_CAP)
    parser.add_argument("--spacing-minutes", type=int, default=DEFAULT_SPACING_MINUTES)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.check:
        api_key = _api_key()
        channels = fetch_buffer_channels(requests.Session(), api_key)
        print(json.dumps({"ok": True, "channels": channels}, indent=2))
        return

    entries: list[tuple[str, dict[str, Any], str]] = []
    if args.refill_from_hub:
        entries = _collect_from_hub_config()
    elif args.manifest:
        if not args.release_base_url:
            raise SystemExit("--release-base-url is required with --manifest for Buffer.")
        bkey = args.manifest.stem
        for item in json.loads(args.manifest.read_text(encoding="utf-8")):
            clip = str(item.get("clip") or "").strip()
            if clip:
                entries.append((bkey, item, f"{args.release_base_url.rstrip('/')}/{clip}"))
    else:
        raise SystemExit("Pass --check, --refill-from-hub, or --manifest + --release-base-url.")

    res = publish_to_buffer(
        entries,
        max_queue_per_channel=args.max_queue,
        daily_cap=args.daily_cap,
        spacing_minutes=args.spacing_minutes,
        dry_run=args.dry_run,
    )
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
