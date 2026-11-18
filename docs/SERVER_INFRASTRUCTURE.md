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
| `https://instance-20260916-2320.tail256180.ts.net:4010` | `http://127.0.0.1:4010` | **OpenShorts** (`openshorts-frontend` -> `openshorts-backend` on `127.0.0.1:8001`) | Active |
| `https://instance-20260916-2320.tail256180.ts.net:4007` | `http://127.0.0.1:4008` | **Postiz** (`postiz`, `postiz-postgres`, `postiz-redis`, `temporal*`, `temporal-ui` `:8080`) | Active |
| `https://instance-20260916-2320.tail256180.ts.net` (`:443`) | `:3201` / `:8003` | Legacy Tarq ERP demo routes (`tarq-nextdemo-*`) | **Backends Stopped** |
| `https://usmansharjeel619.github.io/video-engine/` | GitHub Pages (`docs/`) | **Mobile Upload Hub** | Active |

### Unrelated Pre-Existing Host Listeners (Do Not Kill/Modify)
- `127.0.0.1:8137` — `python3 /tmp/run_backend_devb.py 8137`
- `127.0.0.1:8134` — `python3 /tmp/devd-api-8134.py`
- `127.0.0.1:8002` — `python3 /home/ubuntu/devf_serve.py`

### Intentionally Stopped Systemd Services (Leave Stopped)
- `hermes-dashboard.service`, `hermes-gateway-46612b04.service`
- `tarq-nextdemo-api.service`, `tarq-nextdemo-frontend.service`
- `ollama.service`
- `postgresql.service`, `postgresql@16-main.service`

---

## 3. OpenShorts Self-Hosted Setup (`~/openshorts`)

- **Upstream Repo:** `mutonby/openshorts` (MIT license) — OpusClip alternative with Web UI, Gemini moment selection, virality scores, MediaPipe active-speaker/split-screen tracking, kinetic word-synced captions, `viral_hook_text` overlays (`AUTO_HOOK=1`), and side-by-side clip editor.
- **Browser First-Run Note:** `dashboard/src/App.jsx` checks `localStorage.getItem('gemini_key')` in self-host mode before enabling the UI Generate button; paste the Gemini API key once in the OpenShorts Web UI prompt (`https://instance-20260916-2320.tail256180.ts.net:4010/#app`) so it saves in browser `localStorage`. Backend/CLI/API requests also read `~/openshorts/.env.selfhost`.
- **Custom Self-Host Overlay Files (untracked in `~/openshorts`):**
  - `~/openshorts/.env.selfhost` (`chmod 600`): holds `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-3-flash-preview`, `WHISPER_MODEL=small`, `WHISPER_DEVICE=cpu`, `WHISPER_COMPUTE=int8`, `FFMPEG_ENCODER=x264`, `AUTO_HOOK=1`, `AUTO_HOOK_STYLE=pill`, `AUTO_HOOK_SECONDS=5`, `YOUTUBE_COOKIES_B64`.
  - `~/openshorts/nginx.selfhost.conf`: reverse-proxies `/api`, `/videos`, `/thumbnails`, `/video`, `/gallery`, `/health`, `/mcp`, `/openapi.json` to `http://backend:8000` (`client_max_body_size 4G`, `proxy_buffering off`, `600s` timeouts) and serves the SPA on `:80`.
  - `~/openshorts/docker-compose.selfhost.yml`: runs `backend` (`GPU=0`, `127.0.0.1:8001:8000`) and `frontend` (`prod` nginx target, `127.0.0.1:4010:80`). Omits the optional Remotion/Chromium `renderer` service (only used for paid-style AI UGC actors) to conserve RAM on `11 GiB` ARM64.
- **Data Volumes & Persistence:**
  - `./output` -> `/app/output` (`chmod 777` on host so `appuser` inside container can write)
  - `./uploads` -> `/app/uploads`
  - Docker named volume `openshorts_hf` -> `/app/.cache/huggingface`
- **Management Commands:**
  ```bash
  cd ~/openshorts
  sudo docker compose -f docker-compose.selfhost.yml ps
  sudo docker compose -f docker-compose.selfhost.yml logs -f backend
  sudo docker compose -f docker-compose.selfhost.yml up -d --build
  ```

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
