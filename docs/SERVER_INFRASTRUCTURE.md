# Cloud Server Infrastructure & Deployment Reference

This document records the live topology, hardware constraints, secret locations (paths only — never secrets), Tailscale routes, and operational playbooks for the Oracle Cloud ARM64 server.

---

## 1. Server Identity & Specs

- **Hostname (Tailscale FQDN):** `instance-20260916-2320.tail256180.ts.net`
- **Tailscale IP:** `100.76.60.83`
- **SSH User / Key:** `ubuntu` with `%USERPROFILE%\.ssh\tarq_deploy` on Windows laptop
- **Architecture & OS:** `aarch64` (`linux/arm64`), Ubuntu 24.04 (`6.17.0-1020-oracle`)
- **Memory & Swap:** `11 GiB` RAM + `4.0 GiB` `/swapfile` (persisted in `/etc/fstab`)
- **Disk:** `/dev/sda1` `145G` total (keep clean; purge temporary VOD downloads after clipping)

---

## 2. Port & Tailscale Serve Map

> Check live state any time with:
> `sudo docker ps -a && sudo tailscale serve status && free -h && df -h /`

| Public / Tailnet URL | Tailscale Proxy Target | Service / Container | Status |
|---|---|---|---|
| `https://instance-20260916-2320.tail256180.ts.net:4007` | `http://127.0.0.1:4008` | **Postiz** (`postiz`, `postiz-postgres`, `postiz-redis`, `temporal*`, `temporal-ui` `:8080`) | Active |
| `https://instance-20260916-2320.tail256180.ts.net` (`:443`) | `:3201` / `:8003` | Legacy Tarq ERP demo routes (`tarq-nextdemo-*`) | **Backends Stopped** |
| `https://usmansharjeel619.github.io/video-engine/` | GitHub Pages (`docs/`) | **Mobile Upload Hub** | Active |
| Tailscale `:4010` (`openshorts-*` Docker stack) | *(removed)* | Standalone OpenShorts Web UI (`~/openshorts`) | **Stopped** (logic ported into `~/video-engine`) |

### Unrelated Pre-Existing Host Listeners (Do Not Kill/Modify)
- `127.0.0.1:8137` — `python3 /tmp/run_backend_devb.py 8137`
- `127.0.0.1:8134` — `python3 /tmp/devd-api-8134.py`
- `127.0.0.1:8002` — `python3 /home/ubuntu/devf_serve.py`

### Intentionally Stopped Services (Leave Stopped)
- `openshorts-backend` / `openshorts-frontend` (`~/openshorts`, Tailscale `:4010` disabled) — AI virality & hook logic now runs natively inside `~/video-engine/scripts/viral_pipeline.py`
- `hermes-dashboard.service`, `hermes-gateway-46612b04.service`
- `tarq-nextdemo-api.service`, `tarq-nextdemo-frontend.service`
- `ollama.service`
- `postgresql.service`, `postgresql@16-main.service`

---

## 3. Native Unified Clipping Pipeline (`~/video-engine/scripts/viral_pipeline.py`)

- **Python Venv (`~/video-engine/.venv`):** `faster-whisper`, `yt-dlp`, `opencv-python-headless`, `numpy`, `google-genai`, `pillow`, `pydantic`, `python-dotenv` + system `ffmpeg` + `fonts-noto-color-emoji`.
- **Untracked Secrets (`chmod 600`):**
  - `~/video-engine/.env`: `VIRAL_SELECTOR_BACKEND=codex`, `CODEX_SELECTOR_REASONING=medium`, `SOCIALCLAW_API_KEY`, `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-3.6-flash` (plus optional `POSTIZ_API_KEY`, `POSTIZ_BASE_URL=http://127.0.0.1:4008`, `POSTIZ_INTEGRATION_IDS`)
  - `~/video-engine/.creds/youtube_cookies.txt`: Netscape cookies auto-detected by `viral_pipeline.py`, `clip_engine.py`, and `grab_yt_dvr.py`
- **Auto-Worker + SocialClaw Monitoring Quick Commands:**
  - Check live pipeline & disk: `tmux attach -t clip-worker` (or `tail -n 40 output/auto_worker.log`), `tail -n 40 output/codex_qa.log`, `df -h /`
  - Check SocialClaw queue/published counts: `~/.local/bin/...` or `PATH=/home/ubuntu/opt/node22/bin:$PATH socialclaw posts list --limit 50 --json`
  - Clean published/rejected MP4s safely: remove `*.mp4`, `.work/`, `qa/` only inside batch dirs WITHOUT `.ready_for_qa`, and copytruncate `output/auto_worker.log` if large.
- **Example End-to-End Run (on Cloud Server):**
  ```bash
  cd ~/video-engine
  ~/video-engine/.venv/bin/python scripts/viral_pipeline.py \
    --input "<VIDEO_OR_STREAM_URL>" \
    --output-dir output/my_batch \
    --layout split --cam-pos auto \
    --hook-style pill --caption-preset hormozi \
    --top-n 5 --min-virality 65 \
    --folder "My Campaign" --batch "Batch 1" --release-tag my-batch-1 \
    --publish mobile-hub
  ```
- **Standby Reference Stack (`~/openshorts`, Stopped):** `mutonby/openshorts` remains cloned on disk with `docker-compose.selfhost.yml` as an optional standby Web UI if explicitly requested (`sudo docker compose -f docker-compose.selfhost.yml up -d` + `sudo tailscale serve --bg --https=4010 http://127.0.0.1:4010`), kept stopped by default.

---

## 4. Postiz Stack (`~/postiz`)

- **Compose File:** `~/postiz/docker-compose.yaml`
- **Tailscale HTTPS:** `https://instance-20260916-2320.tail256180.ts.net:4007` (`sudo tailscale serve --bg --https=4007 http://127.0.0.1:4008`)
- **Tailscale Cookie Fix:** Upstream Postiz strips to `.ts.net`, breaking browser cookies on Tailscale URLs. Mounted `~/postiz/subdomain.management.js` returns `url.hostname` (`instance-20260916-2320.tail256180.ts.net`). Do NOT revert this mount.
- **Database Note:** `sidemail619@gmail.com` was promoted to `isSuperAdmin = true` in `postiz-postgres`.

---

## 5. Direct CLI Clipping Engine (`~/video-engine`)

- **Python Venv:** `~/video-engine/.venv` (`faster-whisper`, `yt-dlp`, `opencv-python-headless`, `numpy`)
- **Secrets (Untracked, `chmod 600`):**
  - `~/video-engine/.env`: `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-3-flash-preview`
  - `~/video-engine/.creds/youtube_cookies.txt`: Netscape cookies for `yt-dlp`
- **Important FFmpeg Rule on Server:**
  - Always use `-copyts -ss <coarse>` coarse input seeking (`scripts/clip_engine.py` v2 handles this) when cutting sub-clips from multi-hour streams to prevent filter graph buffering OOMs.
  - Always verify output `start_time=0.000000` on video and audio streams with `ffprobe`.

---

## 6. Mobile Upload Hub & Releases

1. Render & QA batch on server (`~/video-engine/output/...`).
2. Transfer or publish via GitHub CLI (`gh release create <tag> *.mp4 ...`).
3. Add folder/batch entry in `manifests/hub_config.json` + clip JSON in `manifests/`.
4. Run `python scripts/build_mobile_pack.py` to regenerate `docs/index.html`.
5. Commit & push `manifests/` and `docs/` ONLY (never `.mp4`, `.env`, or `.creds/`).
6. Pull changes on cloud server (`cd ~/video-engine && git pull`) so laptop, GitHub, and server stay synced.
