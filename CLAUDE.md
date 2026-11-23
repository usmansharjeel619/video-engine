# CLAUDE.md

See **[AGENTS.md](AGENTS.md)** and **[docs/SERVER_INFRASTRUCTURE.md](docs/SERVER_INFRASTRUCTURE.md)** for full onboarding instructions, active services, cloud server details, and editing rules.

## Critical Reminders
1. **Heavy processing belongs on `ubuntu@100.76.60.83`** (`aarch64`, SSH key `%USERPROFILE%\.ssh\tarq_deploy`), never on the Windows laptop `C:` drive.
2. **Primary Pipeline Command:** Run `~/video-engine/.venv/bin/python scripts/viral_pipeline.py` on the server for end-to-end ingestion, Whisper, 2-pass Codex (`gpt-6.2-sol` medium) or Gemini virality scoring, Pillow hook banners, kinetic ASS captions, split-screen rendering, QA verification, and Mobile Hub / SocialClaw publishing.
3. **Secrets & Selector:** `VIRAL_SELECTOR_BACKEND=codex`, `CODEX_SELECTOR_REASONING=medium`, `SOCIALCLAW_API_KEY`, and `GEMINI_API_KEY` live ONLY in untracked server `~/video-engine/.env` — never commit secrets.
4. **Never start stopped services** (`openshorts-*`, `hermes-*`, `tarq-*`, `ollama`, host `postgresql`). Only `clip-worker` (`tmux`), `codex_qa_cron.sh`, and Postiz (`:4007`) run on the server.
5. **Always inspect clips** with `ffprobe` (`start_time=0.000000`, `1080x1920`) and PNG frame stills (`<out_dir>/qa/*.png`) before publishing, and schedule SocialClaw via `scripts/socialclaw_publish.py` (`YouTube` capped at `9/24h` rolling).
6. **Keep disk clean:** Purge `.mp4`/`.work`/`qa` inside `.published` and `.qa_rejected` batches and trim `output/auto_worker.log` if disk free drops or daily cleanup is requested.
7. Follow `.agents/skills/viral-stream-clipper/SKILL.md` and `.agents/skills/socialclaw/SKILL.md` for all stream-clipping and SocialClaw work.
