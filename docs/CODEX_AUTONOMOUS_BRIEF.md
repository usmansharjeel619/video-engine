# Codex (`GPT-6.2-Sol` Medium) — Autonomous Overnight Clipping & QA Context

Read [AGENTS.md](../AGENTS.md), [SERVER_INFRASTRUCTURE.md](SERVER_INFRASTRUCTURE.md), and [.agents/skills/viral-stream-clipper/SKILL.md](../.agents/skills/viral-stream-clipper/SKILL.md) first.

---

## 1. Two-Stage Architecture (Credit-Saver Mode)
- **`clip-worker` (`tmux` session running `scripts/auto_batch_worker.py`)** runs 24/7 with **0 Codex credits**: it downloads 15-minute slices from `manifests/auto_sources.json` (plus any local files in `output/gta6-streams/`), runs `viral_pipeline.py` (`--min-virality 80 --min-hook-score 85`) via free-tier Gemini + Faster-Whisper + FFmpeg, cleans `.work/source.mp4` & `.wav`, and writes `.ready_for_qa` markers under `output/auto_batches/<batch_id>/`.
- **`codex_qa_cron.sh` (runs via `crontab` every 2 hours: `0 */2 * * *`)** checks if any `.ready_for_qa` (or unpublished `output/gta6-batch3-tail`) exists. **If nothing is waiting, it exits without invoking Codex (0 credits).** Only when batches are waiting does it launch a single `codex exec` QA & publish pass.

---

## 2. Current State (Start Point)
- **Already Published on Mobile Hub (`IShowSpeed — GTA 6`):**
  - `Batch 2`: `gta6-batch2` (4 strict bangers from `0m–11m28s` of `stream_boot_11_25m.mp4`, `hook2s >= 89`, `virality >= 91`).
  - `Batch 1`: `gta6-batch1` (4 earlier first-boot/Lucia/robbery clips from `stream_boot_11_25m.mp4`).
- **Staged Source Streams on Server Disk (`~/video-engine/output/gta6-streams/`):**
  - Check `ls -lh ~/video-engine/output/gta6-streams/` first for downloaded MP4 slices (`stream_25_45m.mp4`, etc.).
- **Important YouTube Download Constraint:**
  - Oracle Cloud's IP hits YouTube bot-checks without valid residential traffic or fresh cookies. **Do NOT waste cycles retrying `yt-dlp` on YouTube URLs directly from the cloud IP when `--proxy socks5h://127.0.0.1:1080` (laptop tunnel) is offline.**
  - Process all staged local MP4 chunks in `~/video-engine/output/gta6-streams/` cleanly first.
  - For additional streams when the laptop is off, Twitch VODs (e.g., **YourRAGE GTA 6** `https://www.twitch.tv/yourragegaming/videos`) can be probed/downloaded directly from the server with `yt-dlp` without YouTube cookies.

---

## 3. Exact Viral Pipeline Command (One Job At A Time)

Never run multiple FFmpeg/Whisper jobs concurrently (`11 GiB` RAM + `4 GiB` swap). Run strictly sequentially:

```bash
cd ~/video-engine
~/video-engine/.venv/bin/python -u scripts/viral_pipeline.py \
  --input "<LOCAL_STREAM_MP4>" \
  --output-dir output/<batch_dir> \
  --layout split --cam-pos auto \
  --hook-style pill --caption-preset hormozi \
  --model small --min-duration 18 --max-duration 45 \
  --top-n 5 --min-virality 80 --min-hook-score 85 \
  --instructions "ONLY pick explosive, hilarious, or jaw-dropping moments where seconds 0.0-2.0 immediately stop a cold TikTok/Reels viewer scrolling. Drop slow setups, walking around, or weak hooks." \
  --extra-tags IShowSpeed GTA6 GTAVI Gaming \
  --publish none
```

- For `stream_boot_11_25m.mp4` / same IShowSpeed overlay layout (`1920x1080` mid-left webcam), `--cam-pos 0.0,0.425,0.205,0.225` is razor-exact; for new streamers/layouts use `--cam-pos auto` (YuNet) and **verify visually in `qa/*.png`**.
- Keep `--min-virality 76 --min-hook-score 80`. Drop weak setups, slow dialogue, or generic hooks so every published clip has genuine viral upside.

---

## 4. Mandatory Batch Review & Self-Healing Checklist (Every Batch)

After each `viral_pipeline.py` run completes, YOU MUST check **all 4 items** before publishing:
1. **Check `manifest.json`:** Ensure `qaPassed == true`, `hookScore >= 74`, `viralityScore >= 70`, and `hook` / `title` / `caption` / `pin` match the clip cleanly without truncations or placeholder text.
2. **Check `ffprobe`:** Confirm `1080x1920`, `start_time=0.000000` on BOTH video and audio streams, and reasonable duration (`>= 10s`).
3. **Visually Inspect `output/<batch_dir>/qa/*.png`:** Open the extracted `*_t1_hook.png` and `*_tmid_cap.png` frames. Confirm:
   - Top half shows full streamer webcam face (no cropped forehead, no sub-counter bleed).
   - Hook pill banner sits cleanly at `y=724` below the split seam (`2` balanced lines with color emojis rendered properly, no overlapping faces or captions).
   - Bottom half shows crisp gameplay + Hormozi active yellow captions in the lower third (`y~1400`).
4. **Fix & Re-render if Needed:** If webcam crop is off (update `--cam-pos`), hook wraps poorly (adjust `hook_renderer.py`), or a weak clip slipped through (drop it from `manifest.json`), fix the root cause, commit any code improvement cleanly, and re-verify before publishing!

---

## 5. Publishing Batch to Mobile Upload Hub

Once all clips in the batch pass review:
1. Create clean GitHub Release (`gh release create <tag> output/<batch>/*.mp4 ...`).
2. Save lean clip list to `manifests/<tag>.json` (keep `clip`, `path`, `hook`, `title`, `caption`, `pin`, `viralityScore`, `why`).
3. Insert batch at index `0` of the matching folder in `manifests/hub_config.json` (or create a new folder object at index `0`).
4. Rebuild HTML:
   ```bash
   ~/video-engine/.venv/bin/python scripts/build_mobile_pack.py \
     --config manifests/hub_config.json --output docs/index.html
   ```
5. Commit ONLY code/manifests/docs (NEVER `.env`, `.creds/`, `.mp4`, or `.work/`) and `git push origin main`.
6. Auto-schedule verified clips exclusively via **Buffer** (`scripts/buffer_publish.py --refill-from-hub`), **NEVER SocialClaw**. Keep in mind: Buffer Free allows **at most 10 concurrent scheduled posts per channel at a time** (`tiktok`, `instagram`, `youtube`). Do NOT retry past 10 or touch SocialClaw; remaining released clips stay in `manifests/hub_config.json` and the 30-minute refill cron automatically schedules more as soon as queued Buffer posts go live and open slots. Never commit `BUFFER_API_KEY`.
7. Remove processed temporary MP4 caches under `output/<batch>/.work/` (and source chunks already completely processed) if `df -h /` free space drops below `25G`.
