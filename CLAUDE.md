# CLAUDE.md

See **[AGENTS.md](AGENTS.md)** and **[docs/SERVER_INFRASTRUCTURE.md](docs/SERVER_INFRASTRUCTURE.md)** for full onboarding instructions, active services, cloud server details, and editing rules.

## Critical Reminders
1. **Heavy processing belongs on `ubuntu@100.76.60.83`** (`aarch64`, SSH key `%USERPROFILE%\.ssh\tarq_deploy`), never on the Windows laptop `C:` drive.
2. **Verified Gemini model:** `gemini-3-flash-preview` (keys live ONLY in untracked server `.env` / `.env.selfhost` — never commit secrets).
3. **Never start stopped services** (`hermes-*`, `tarq-*`, `ollama`, host `postgresql`).
4. **Always inspect clips** with `ffprobe` (`start_time=0.000000`) and PNG frame stills before delivering.
5. Follow `.agents/skills/viral-stream-clipper/SKILL.md` for all stream-clipping and Content Rewards work.
