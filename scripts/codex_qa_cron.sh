#!/usr/bin/env bash
set -euo pipefail

export PATH="/home/ubuntu/.local/bin:/home/ubuntu/opt/node22/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
REPO="/home/ubuntu/video-engine"
LOG="$REPO/output/codex_qa.log"
LOCK="/tmp/codex_video_qa.lock"

mkdir -p "$REPO/output"
exec >>"$LOG" 2>&1

# Prevent overlapping Codex runs
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date -Iseconds)] Skipping: previous Codex QA check still running."
  exit 0
fi

cd "$REPO"
if [ -f "$REPO/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO/.env"
  set +a
fi

# Find batches ready for Codex QA (skip invoking Codex completely = 0 credits if none!)
READY=$(find output/auto_batches -maxdepth 2 -name ".ready_for_qa" 2>/dev/null || true)
TAIL_READY=""
if [ -f "output/gta6-batch3-tail/manifest.json" ] && [ ! -f "output/gta6-batch3-tail/.published" ]; then
  TAIL_READY="output/gta6-batch3-tail/manifest.json"
fi

if [ -z "$READY" ] && [ -z "$TAIL_READY" ]; then
  echo "[$(date -Iseconds)] No pending batches for QA (0 Codex credits used)."
  exit 0
fi

QA_BACKEND="${QA_BACKEND:-agy}"
AGY_QA_MODEL="${AGY_QA_MODEL:-gemini-4-hydrogen-medium}"
QA_PROMPT="Read AGENTS.md and docs/CODEX_AUTONOMOUS_BRIEF.md. Perform ONE single QA + publish pass ONLY over pending batches that have .ready_for_qa (inside output/auto_batches/*/) or output/gta6-batch3-tail/manifest.json (if .published does not exist). For each pending batch: (1) inspect manifest.json and run ffprobe verifying 1080x1920 + exact start_time=0.000000; (2) visually inspect every qa/*.png still for facecam framing, 2-line pill hook placement/emojis, and lower-third Hormozi captions; (3) drop or fix+rerender any broken clip; (4) release passing clips to GitHub via gh release create, save lean manifests/<tag>.json, insert into manifests/hub_config.json, rebuild docs/index.html with scripts/build_mobile_pack.py, commit manifests/ + docs/ + code fixes, and git push origin main; (5) schedule passing clips across all connected SocialClaw platforms (TikTok, Instagram, YouTube) via '.venv/bin/python scripts/socialclaw_publish.py --manifest <batch_dir>/manifest.json'; (6) remove .ready_for_qa and create .published (or .qa_rejected if 0 pass) and delete .work/ inside published batch dirs. After handling pending batches once, EXIT cleanly immediately."

if [ "$QA_BACKEND" = "codex" ]; then
  echo "[$(date -Iseconds)] Found pending batches -> starting Codex GPT-6.2-Sol Low QA pass..."
  codex exec \
    -m gpt-6.2-sol \
    -c 'model_reasoning_effort="low"' \
    -s danger-full-access \
    --skip-git-repo-check \
    "$QA_PROMPT"
else
  echo "[$(date -Iseconds)] Found pending batches -> starting Antigravity ($AGY_QA_MODEL) QA pass..."
  agy \
    --model "$AGY_QA_MODEL" \
    --mode auto \
    --dangerously-skip-permissions \
    -p "$QA_PROMPT"
fi

echo "[$(date -Iseconds)] Cleaning processed/rejected MP4 binaries to keep disk free..."
for d in output/auto_batches/*/; do
  [ -d "$d" ] || continue
  if [ ! -f "${d}.ready_for_qa" ] && { [ -f "${d}.published" ] || [ -f "${d}.qa_rejected" ]; }; then
    rm -f "${d}"*.mp4
    rm -rf "${d}.work" "${d}qa"
  fi
done

echo "[$(date -Iseconds)] Codex QA pass completed."

if [ -n "${BUFFER_API_KEY:-}" ]; then
  echo "[$(date -Iseconds)] Syncing Mobile Hub backlog to Buffer queue..."
  .venv/bin/python scripts/buffer_publish.py --refill-from-hub || true
fi
