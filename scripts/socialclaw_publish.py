#!/usr/bin/env python3
"""
SocialClaw Multi-Platform Auto-Scheduler.

Uploads QA-verified vertical clips to SocialClaw (or uses a base release URL),
computes staggered publishAt slots per platform (30-50 posts/day per platform,
defaulting to 45/day spaced >= 30 mins apart), validates via /v1/posts/validate,
and schedules via /v1/posts/apply across TikTok, Instagram Reels, and YouTube Shorts.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / "output" / "socialclaw_state.json"
DEFAULT_BASE_URL = "https://getsocialclaw.com"
DEFAULT_DAILY_CAP = 45
DEFAULT_SPACING_MINUTES = 30
DEFAULT_PROVIDERS = ("tiktok", "instagram", "youtube")


def _load_env_if_needed() -> None:
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
    _load_env_if_needed()
    key = (os.environ.get("SOCIALCLAW_API_KEY") or os.environ.get("SC_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("SOCIALCLAW_API_KEY is not set in environment or .env.")
    return key


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"uploaded_assets": {}, "scheduled": {}}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _parse_iso_utc(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_next_slot(
    existing_times: list[datetime],
    now_utc: datetime,
    spacing_minutes: int = DEFAULT_SPACING_MINUTES,
    daily_cap: int = DEFAULT_DAILY_CAP,
) -> datetime:
    """
    Pick the earliest UTC publish timestamp >= now + 3m spaced >= spacing_minutes
    from the latest scheduled post on that account while keeping each UTC date
    under daily_cap posts.
    """
    floor = (now_utc.astimezone(timezone.utc) + timedelta(minutes=3)).replace(second=0, microsecond=0)
    future_or_recent = sorted(t.astimezone(timezone.utc) for t in existing_times if t >= now_utc - timedelta(hours=24))
    candidate = floor
    if future_or_recent:
        last = future_or_recent[-1]
        candidate = max(floor, (last + timedelta(minutes=spacing_minutes)).replace(second=0, microsecond=0))

    counts_by_day: dict[str, int] = {}
    for t in existing_times:
        day_key = t.astimezone(timezone.utc).strftime("%Y-%m-%d")
        counts_by_day[day_key] = counts_by_day.get(day_key, 0) + 1

    while counts_by_day.get(candidate.strftime("%Y-%m-%d"), 0) >= max(1, int(daily_cap)):
        next_day = (candidate + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
        candidate = next_day

    return candidate


def _ensure_shorts_suffix(title: str, max_len: int = 100) -> str:
    clean = " ".join((title or "Viral Stream Clip").split()).strip()
    if "#shorts" in clean.lower():
        return clean[:max_len]
    suffix = " #Shorts"
    if len(clean) + len(suffix) <= max_len:
        return clean + suffix
    return clean[: max_len - len(suffix)].rstrip() + suffix


def build_platform_post(
    provider: str,
    account_handle: str,
    item: dict[str, Any],
    media_link: str,
    publish_at_iso: str,
) -> dict[str, Any]:
    """Build a validated SocialClaw post entry tailored to TikTok, Instagram Reels, or YouTube Shorts."""
    base_caption = str(item.get("caption") or item.get("title") or "").strip()
    if provider == "tiktok":
        desc = str(item.get("tiktokCaption") or base_caption).strip()[:2200]
        return {
            "account": account_handle,
            "provider": "tiktok",
            "description": desc,
            "status": "scheduled",
            "publishAt": publish_at_iso,
            "settings": {
                "tiktokPostMode": "direct_post",
                "privacyLevel": "PUBLIC_TO_EVERYONE",
                "duetEnabled": True,
                "commentEnabled": True,
                "stitchEnabled": True,
            },
            "assets": [{"mediaLink": media_link}],
        }
    if provider == "instagram":
        title = str(item.get("title") or item.get("hook") or "Stream Highlight")[:100]
        desc = str(item.get("instagramCaption") or base_caption).strip()[:2200]
        return {
            "account": account_handle,
            "provider": "instagram",
            "name": title,
            "description": desc,
            "status": "scheduled",
            "publishAt": publish_at_iso,
            "settings": {
                "instagramPublishMode": "reel",
                "instagramShareToFeed": True,
            },
            "assets": [{"mediaLink": media_link}],
        }
    if provider == "youtube":
        raw_title = str(item.get("youtubeTitle") or item.get("title") or "GTA 6 Stream Highlight")
        yt_title = _ensure_shorts_suffix(raw_title, max_len=100)
        desc_parts = [base_caption]
        if item.get("pin"):
            desc_parts.append(f"\nPinned thought: {item['pin']}")
        desc = "\n".join(p for p in desc_parts if p).strip()[:5000]
        return {
            "account": account_handle,
            "provider": "youtube",
            "name": yt_title,
            "description": desc,
            "status": "scheduled",
            "publishAt": publish_at_iso,
            "settings": {
                "privacyStatus": "public",
                "notifySubscribers": True,
                "madeForKids": False,
            },
            "assets": [{"mediaLink": media_link}],
        }
    raise ValueError(f"Unsupported SocialClaw provider: {provider}")


def _fetch_accounts(session: requests.Session, base_url: str, api_key: str) -> dict[str, dict[str, Any]]:
    resp = session.get(f"{base_url}/v1/accounts", headers=_headers(api_key), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    by_provider: dict[str, dict[str, Any]] = {}
    for acct in data.get("accounts", []):
        if acct.get("revokedAt") or not acct.get("publishable"):
            continue
        prov = acct.get("provider")
        if prov and prov not in by_provider:
            by_provider[prov] = acct
    return by_provider


def _fetch_existing_schedule_times(
    session: requests.Session,
    base_url: str,
    api_key: str,
) -> dict[str, list[datetime]]:
    times_by_provider: dict[str, list[datetime]] = {}
    resp = session.get(
        f"{base_url}/v1/posts",
        params={"limit": 200},
        headers=_headers(api_key),
        timeout=30,
    )
    if not resp.ok:
        return times_by_provider
    for p in resp.json().get("posts", []):
        if p.get("status") in ("canceled", "failed"):
            continue
        prov = p.get("provider")
        dt = _parse_iso_utc(p.get("publishAt") or p.get("publishAtUtc") or p.get("scheduledFor"))
        if prov and dt:
            times_by_provider.setdefault(prov, []).append(dt)
    return times_by_provider


def _upload_asset(
    session: requests.Session,
    base_url: str,
    api_key: str,
    file_path: Path,
    state: dict[str, Any],
) -> str:
    cache_key = str(file_path.resolve())
    cached = state.get("uploaded_assets", {}).get(cache_key)
    if cached:
        return cached
    with file_path.open("rb") as fh:
        resp = session.post(
            f"{base_url}/v1/assets/upload",
            headers=_headers(api_key),
            files={"file": (file_path.name, fh, "video/mp4")},
            timeout=180,
        )
    resp.raise_for_status()
    asset = resp.json().get("asset") or {}
    media_url = asset.get("useAsMediaLink") or asset.get("publicUrl") or ""
    if not media_url:
        raise RuntimeError(f"SocialClaw asset upload missing URL: {resp.text[:300]}")
    state.setdefault("uploaded_assets", {})[cache_key] = media_url
    _save_state(state)
    return media_url


def _resolve_clip_path(item: dict[str, Any], manifest_dir: Path) -> Path | None:
    p = item.get("path")
    if p and Path(p).exists():
        return Path(p)
    clip_name = item.get("clip")
    if clip_name:
        cand = manifest_dir / clip_name
        if cand.exists():
            return cand
    return None


def publish_manifest_to_socialclaw(
    manifest_path: Path,
    providers: list[str] | tuple[str, ...] = DEFAULT_PROVIDERS,
    base_url: str | None = None,
    release_base_url: str | None = None,
    daily_cap: int = DEFAULT_DAILY_CAP,
    spacing_minutes: int = DEFAULT_SPACING_MINUTES,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Upload clips from a manifest and schedule them across all enabled SocialClaw platforms."""
    api_key = _api_key()
    sc_base = (os.environ.get("SOCIALCLAW_BASE_URL") or base_url or DEFAULT_BASE_URL).rstrip("/")
    items = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(items, list) or not items:
        return {"ok": True, "scheduled_count": 0, "reason": "empty manifest"}

    batch_key = manifest_path.parent.name if manifest_path.parent.name != "manifests" else manifest_path.stem
    state = _load_state()
    session = requests.Session()
    accounts = _fetch_accounts(session, sc_base, api_key)
    times_by_provider = _fetch_existing_schedule_times(session, sc_base, api_key)
    now_utc = datetime.now(timezone.utc)

    results: dict[str, Any] = {"ok": True, "batch": batch_key, "providers": {}, "scheduled_count": 0}
    clip_media_urls: dict[str, str] = {}

    for item in items:
        if item.get("qaPassed") is False:
            continue
        clip_name = str(item.get("clip") or "").strip()
        if not clip_name:
            continue

        for prov in providers:
            if prov not in accounts:
                continue
            dedup_key = f"{batch_key}:{clip_name}:{prov}"
            if dedup_key in state.get("scheduled", {}):
                continue

            if clip_name not in clip_media_urls:
                local_path = _resolve_clip_path(item, manifest_path.parent)
                if local_path is not None and not dry_run:
                    clip_media_urls[clip_name] = _upload_asset(session, sc_base, api_key, local_path, state)
                elif release_base_url:
                    clip_media_urls[clip_name] = f"{release_base_url.rstrip('/')}/{clip_name}"
                elif local_path is not None and dry_run:
                    clip_media_urls[clip_name] = f"https://example.invalid/{clip_name}"
                else:
                    raise RuntimeError(
                        f"Clip file {clip_name} not found locally and no --release-base-url provided."
                    )

            media_url = clip_media_urls[clip_name]
            acct_handle = accounts[prov]["handle"]
            prov_times = times_by_provider.setdefault(prov, [])
            slot_dt = compute_next_slot(
                prov_times,
                now_utc=now_utc,
                spacing_minutes=spacing_minutes,
                daily_cap=daily_cap,
            )
            slot_iso = slot_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            post_obj = build_platform_post(prov, acct_handle, item, media_url, slot_iso)
            payload = {"posts": [post_obj]}

            if dry_run:
                results["providers"].setdefault(prov, []).append({"clip": clip_name, "publishAt": slot_iso, "dry_run": True})
                prov_times.append(slot_dt)
                continue

            val_resp = session.post(
                f"{sc_base}/v1/posts/validate",
                headers={**_headers(api_key), "Content-Type": "application/json"},
                json=payload,
                timeout=30,
            )
            if not val_resp.ok or not val_resp.json().get("ok"):
                err = f"validate failed ({prov}/{clip_name}): {val_resp.text[:300]}"
                print(f"[SocialClaw] WARN {err}")
                results["providers"].setdefault(prov, []).append({"clip": clip_name, "error": err})
                continue

            app_resp = session.post(
                f"{sc_base}/v1/posts/apply",
                headers={**_headers(api_key), "Content-Type": "application/json"},
                json=payload,
                timeout=30,
            )
            if not app_resp.ok or not app_resp.json().get("ok"):
                err = f"apply failed ({prov}/{clip_name}): {app_resp.text[:300]}"
                print(f"[SocialClaw] WARN {err}")
                results["providers"].setdefault(prov, []).append({"clip": clip_name, "error": err})
                continue

            prov_times.append(slot_dt)
            applied = app_resp.json()
            state.setdefault("scheduled", {})[dedup_key] = {
                "publishAt": slot_iso,
                "account": acct_handle,
                "runId": applied.get("runId") or applied.get("run", {}).get("id"),
                "mediaLink": media_url,
            }
            _save_state(state)
            results["scheduled_count"] += 1
            results["providers"].setdefault(prov, []).append({"clip": clip_name, "publishAt": slot_iso, "status": "scheduled"})
            print(f"[SocialClaw] Scheduled {prov} | {clip_name} @ {slot_iso}")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Schedule manifest clips across SocialClaw connected accounts.")
    parser.add_argument("--manifest", "-m", type=Path, required=True, help="Path to batch manifest.json.")
    parser.add_argument("--providers", nargs="+", default=list(DEFAULT_PROVIDERS), help="Providers to target.")
    parser.add_argument("--release-base-url", default=None, help="Optional GitHub Release download URL base if local MP4s are absent.")
    parser.add_argument("--daily-cap", type=int, default=DEFAULT_DAILY_CAP, help="Max posts/UTC day per platform (default: 45).")
    parser.add_argument("--spacing-minutes", type=int, default=DEFAULT_SPACING_MINUTES, help="Minutes between scheduled posts per platform (default: 30).")
    parser.add_argument("--dry-run", action="store_true", help="Compute slots without uploading or applying.")
    args = parser.parse_args()

    res = publish_manifest_to_socialclaw(
        manifest_path=args.manifest,
        providers=args.providers,
        release_base_url=args.release_base_url,
        daily_cap=args.daily_cap,
        spacing_minutes=args.spacing_minutes,
        dry_run=args.dry_run,
    )
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
