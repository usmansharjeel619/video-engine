# CLAUDE.md

See **[AGENTS.md](AGENTS.md)** and **[docs/SERVER_INFRASTRUCTURE.md](docs/SERVER_INFRASTRUCTURE.md)** for full onboarding instructions, active services, cloud server details, and editing rules.

## Critical Reminders
1. **Heavy processing belongs on `ubuntu@100.76.60.83`** (`aarch64`, SSH key `%USERPROFILE%\.ssh\tarq_deploy`), never on the Windows laptop `C:` drive.
2. **Primary Pipeline Command:** Run `~/video-engine/.venv/bin/python scripts/viral_pipeline.py` on the server for end-to-end ingestion, Whisper, 2-pass Gemini virality scoring + Pass-3 Vision hook grounding, Pillow hook banners, kinetic ASS captions, split-screen rendering, QA verification, and Mobile Hub / Postiz publishing.
3. **Verified Gemini model:** `gemini-3-flash-preview` (keys live ONLY in untracked server `.env` — never commit secrets).
4. **Never start stopped services** (`openshorts-*`, `hermes-*`, `tarq-*`, `ollama`, host `postgresql`). Only Postiz (`:4007`) + native `viral_pipeline.py` run on the server.
5. **Always inspect clips** with `ffprobe` (`start_time=0.000000`) and PNG frame stills (`<out_dir>/qa/*.png`) before publishing.
6. Follow `.agents/skills/viral-stream-clipper/SKILL.md` for all stream-clipping and Content Rewards work.
