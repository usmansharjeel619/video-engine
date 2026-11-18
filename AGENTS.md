# AGENTS.md — Agent Onboarding & Operations Guide

> Read this file first before making changes, running scripts, or starting services.
> This repository powers the user's **automated viral stream clipping, AI moment detection, Content Rewards campaign production, self-hosted OpenShorts UI, Postiz scheduling, and Mobile Upload Hub**.

---

## 1. Golden Rules (What To Do / What NOT To Do)

### DO
- **Run heavy work on the cloud server (`ubuntu@100.76.60.83`)**: Use the Oracle Cloud ARM64 (`aarch64`, Ubuntu 24.04) server for `yt-dlp` downloads, `faster-whisper`, FFmpeg renders, Docker containers, and OpenShorts jobs.
- **Read `.agents/skills/viral-stream-clipper/SKILL.md`** before creating custom FFmpeg clips or Content Rewards batches.
- **Use `gemini-3-flash-preview`** as the Gemini model (`GEMINI_MODEL=gemini-3-flash-preview`). It is the verified free-tier working model on the user's key.
- **Pass YouTube cookies** from `~/video-engine/.creds/youtube_cookies.txt` when calling `yt-dlp` on the cloud server (Oracle IPs hit YouTube bot checks otherwise).
- **Verify every rendered clip before delivering**:
  - Run `ffprobe` to confirm `start_time=0.000000` on both video and audio streams (no A/V desync).
  - Extract PNG stills (`ffmpeg -ss ... -frames:v 1`) and visually inspect framing, facecam crop, seam captions, and hook placement.
- **Update the Mobile Upload Hub (`docs/index.html`)** via `scripts/build_mobile_pack.py` after uploading a batch to GitHub Releases (`gh release create ...`), then commit and push `manifests/` + `docs/` (excluding video binaries).

### DO NOT
- **NEVER store VODs or render batches on the Windows laptop (`C:` drive is space-constrained; `D:\Freelance Projects\video-engine` is for code, manifests, docs, and lightweight orchestration only).**
- **NEVER commit secrets**: `.env`, `.env.selfhost`, `.creds/`, cookies, API keys, or `.mp4`/`.mov`/`.wav` binaries (except `sfx/*.wav`) must stay untracked per `.gitignore`.
- **NEVER start stopped services on the cloud server** (`hermes-*`, `tarq-*`, `ollama`, host `postgresql`) unless the user explicitly asks — they were stopped to keep RAM free (`11 GiB` RAM + `4.0 GiB` swap).
- **NEVER use `hydrogen`, `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-3.1-pro-preview`, or `gemini-3.8-flash`** on this Gemini key (verified `404`/`429`/`503`/unavailable).
- **NEVER use FFmpeg `trim` on long videos without `-copyts -ss` coarse input seeking** (causes 1000-buffer RAM OOM).
- **NEVER use `.ts.net` as a cookie `Domain` behind Tailscale Serve** — cookies must use the full FQDN `url.hostname` (`instance-20260916-2320.tail256180.ts.net`) or omit `Domain`.
- **NEVER install CUDA/x86_64 binaries on the cloud server** — it is CPU-only **`aarch64` (`linux/arm64`)**.

---

## 2. Environment & Server Map

| Environment | Location / Host | Purpose |
|---|---|---|
| **Laptop Repo (Control/Git)** | `D:\Freelance Projects\video-engine` (GitHub: `usmansharjeel619/video-engine`) | Code editing, manifests, docs, GitHub Pages Mobile Hub (`docs/`), GitHub CLI releases |
| **Cloud Server Repo** | `/home/ubuntu/video-engine` on `ubuntu@100.76.60.83` | Python `.venv` (`faster-whisper`, `yt-dlp`, `opencv-python-headless`, `numpy`, `google-genai`, `pillow`, `pydantic`, `python-dotenv`), FFmpeg clipping & `viral_pipeline.py` |
| **Cloud OpenShorts Reference (Stopped)** | `/home/ubuntu/openshorts` on `ubuntu@100.76.60.83` | Reference clone of `mutonby/openshorts` (containers stopped to save RAM; AI logic ported into `~/video-engine/scripts/`) |
| **Cloud Postiz Stack** | `/home/ubuntu/postiz` on `ubuntu@100.76.60.83` | Self-hosted social scheduler (`docker-compose.yaml`) |

### SSH Access (from Windows PowerShell)
```powershell
ssh -i "$env:USERPROFILE\.ssh\tarq_deploy" ubuntu@100.76.60.83
```
> **PowerShell Quoting Rule:** Do NOT put unescaped `$var` or `|` inside `ssh ... "..."`. Pipe a single-quoted PowerShell here-string through `tr -d '\r' | bash -s`:
> ```powershell
> @'
> echo "running cleanly on linux"
> '@ | ssh -i "$env:USERPROFILE\.ssh\tarq_deploy" ubuntu@100.76.60.83 "tr -d '\r' | bash -s"
> ```

---

## 3. Running vs Stopped Services (Cloud Server `100.76.60.83`)

Detailed port maps, Tailscale Serve proxy routes, and maintenance commands live in [docs/SERVER_INFRASTRUCTURE.md](docs/SERVER_INFRASTRUCTURE.md).

### Currently Running (Keep Running)
1. **Zero-Token Batch Worker (`tmux` session `clip-worker`)** — Runs `scripts/auto_batch_worker.py` continuously on `ubuntu@100.76.60.83`, clipping 15m slices from `manifests/auto_sources.json` via `scripts/viral_pipeline.py` (`gemini-3-flash-preview` + Faster-Whisper + FFmpeg) and writing `.ready_for_qa` markers.
2. **Scheduled Codex QA Cron (`scripts/codex_qa_cron.sh`, `0 */2 * * *`)** — Checks every 2 hours for `.ready_for_qa` batches (0 tokens used when idle), then invokes a single `codex exec` (`gpt-6.2-sol`, `medium`) pass to visually inspect `qa/*.png`, verify `ffprobe`, fix any crop/hook issues, release to GitHub, rebuild `docs/index.html`, and push.
3. **Postiz (`~/postiz`)** — Social scheduling UI + Temporal + Postgres + Redis + Elasticsearch.
   - Local port: `127.0.0.1:4008` (`postiz`), `127.0.0.1:8080` (`temporal-ui`), `127.0.0.1:7233` (`temporal`)
   - Tailscale HTTPS URL: `https://instance-20260916-2320.tail256180.ts.net:4007`
   - SuperAdmin login email: `sidemail619@gmail.com` (cookie fix in `~/postiz/subdomain.management.js`)
3. **GitHub Pages Mobile Upload Hub (Public Static UI)**
   - Live URL: `https://usmansharjeel619.github.io/video-engine/`
   - Built from `manifests/hub_config.json` -> `python scripts/build_mobile_pack.py` -> `docs/index.html`
4. **Pre-existing Dev Python Listeners (Leave Untouched)**
   - `127.0.0.1:8137` (`/tmp/run_backend_devb.py`), `127.0.0.1:8134` (`/tmp/devd-api-8134.py`), `127.0.0.1:8002` (`/home/ubuntu/devf_serve.py`)

### Intentionally Stopped (Do NOT Start)
- Standalone **OpenShorts** Docker stack (`~/openshorts`, `openshorts-backend` / `openshorts-frontend` & Tailscale `:4010`) — its AI selection, hook, and caption logic were ported natively into `scripts/viral_pipeline.py`; containers remain stopped to keep server RAM free.
- `hermes-dashboard.service`, `hermes-gateway-46612b04.service`
- `tarq-nextdemo-api.service`, `tarq-nextdemo-frontend.service` (Tailscale `:443` routes to `:3201`/`:8003` remain configured while backends stay off)
- `ollama.service`, `postgresql.service`, `postgresql@16-main.service`

---

## 4. Key Scripts & Repository Structure

| Path | Role |
|---|---|
| `scripts/viral_pipeline.py` | **Primary 1-command end-to-end orchestrator** (ingest -> Whisper -> 2-pass Gemini virality + Vision hooks -> Pillow banner + ASS captions + split-screen render -> `ffprobe`/still QA -> Mobile Hub / Postiz publish) |
| `scripts/viral_selector.py` | 2-pass Gemini virality scoring (`SCORE_PROMPT_TEMPLATE` + `DETAIL_PROMPT_TEMPLATE`), RMS audio signal enrichment, word-boundary snapping, overlap dedupe, Pass-3 Vision hook grounding (`GROUNDED_HOOK_PROMPT`) |
| `scripts/hook_renderer.py` | Styled RGBA Pillow hook banners (`pill`, `yellow`, `red`, `dark`, `classic`, `outline`, `outline_yellow`) with bitmap color emoji handling + collision-free Y placement |
| `scripts/caption_styles.py` | 6 kinetic ASS animated caption presets (`hormozi`, `pop`, `pill`, `lime`, `oneword`, `clean`) with active-word pop & highlight boxes |
| `scripts/clip_engine.py` | FFmpeg v2 portrait renderer (`split` facecam+gameplay, `auto` OpenCV cam box, `--trim-silence`, `--flash-hook`, `--sfx`, hook PNG overlay, `fontsdir`, `setsar=1`, `-14 LUFS`) |
| `scripts/grab_yt_dvr.py` | Downloads bounded `[start-min, end-min]` DASH `299+140` slices from YouTube live/VOD with auto cookies (`0.000000` A/V start_time) |
| `scripts/build_mobile_pack.py` | Generates `docs/index.html` Mobile Hub (Folders -> Batches -> `To Post` / `Posted` / `All` tabs + virality badge + `localStorage` tracking) |
| `scripts/publish_clips.py` | Publishes QA-passed manifest batches to Postiz (`POSTIZ_INTEGRATION_IDS` or auto-discovered `/integrations`) or Upload-Post |
| `fonts/`, `sfx/` | Bundled SIL OFL fonts (`Montserrat ExtraBold`, `Anton`, `Archivo Black`, `Noto Serif`) and WAV SFX (`whoosh.wav`, `boom.wav`, `ding.wav`) |
| `manifests/hub_config.json` | Folder/batch registry powering the Mobile Hub |
| `manifests/expedia_batch2.json`, `manifests/gta6_batch1.json` | Batch clip manifests backed by GitHub Releases (`batch-2`, `gta6-batch1`) |
| `.agents/skills/viral-stream-clipper/SKILL.md` | Complete viral clipping, pacing, hook, and Content Rewards QA playbook |
