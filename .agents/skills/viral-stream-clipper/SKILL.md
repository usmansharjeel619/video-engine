---
name: viral-stream-clipper
description: >-
  Pro workflow for turning long gaming/IRL livestreams (e.g., IShowSpeed, Kai Cenat, GTA 6)
  into viral 9:16 portrait clips with split-screen facecam+gameplay, cold-open flash-forward hooks,
  silence jump-cuts, kinetic word-by-word captions, strategic SFX, and Content Rewards compliance.
---

# Viral Stream Clipper Playbook

## 1. Outclass 0–2s Hook Engineering (Most Important Rule)
- **Zero Slow Starts:** Never open a clip on a greeting, throat clear, or quiet setup. Start on the **exact first spoken syllable** or an explosive action frame.
- **Cold-Open Flash-Forward (`--flash-hook`):** For setup->payoff moments, prepend a **1.5–1.8s tease of the peak scream/reveal** at `0.0s` before cutting into the story, paired with a crisp `whoosh` transition.
- **4 Proven Text Hook Formulas (4–7 words max, UPPERCASE):**
  1. **Stakes / Contrast:** `NEVER LEFT THE USA -> WINS $10,000 TRIP`
  2. **Shock / Disbelief:** `NO WAY SPEED DID THIS IN GTA 6 💀`
  3. **Test / Payoff:** `SPEAK CANTONESE = $10,000 EXPEDIA TRIP`
  4. **Wait-for-it Curiosity:** `WATCH SPEED'S JAW DROP AT 0:12 🤯`
- **Sweet-spot duration:** `22–45 seconds`. One clear setup -> payoff arc per clip.

## 2. Layout Selection (`1080x1920`)
- **`split` (Gaming / GTA 6 / Reaction Streams):**
  - Top `1080x700`: Tight facecam crop (`--cam-pos auto` or `tl`/`tr`/`bl`/`br`) with subtle `1.08x` punch-zoom on peak reaction.
  - Bottom `1080x1220`: Centered gameplay action.
- **`blur` (IRL / FaceTime / Full-frame Calls):**
  - Sharp 16:9 centered over darkened blurred 9:16 background so held phones or guests on screen are never cropped off.
- **`center` (Single-camera close-up):**
  - Full-bleed 9:16 vertical crop.

## 3. Pacing, Captions & Meme SFX Discipline
- **Dead-Air Jump Cuts (`--trim-silence`):** Trim pauses > `0.55s` between sentences while keeping `0.12s` natural breathing room and re-timing word timestamps.
- **Kinetic Captions:** 2–3 uppercase words per chunk in bold sans-serif (`Arial Black`), gold `#FFD700` active word highlight, positioned in the safe zone (`MarginV=460` above TikTok/Reels/Shorts bottom UI).
- **Strategic Meme SFX (`--sfx`):** Max **1–2 sound cues per 30s clip** (`whoosh` at 0.0s hook entrance, `boom` on the single peak shock/fail moment). Never spam SFX.
- **Audio Target:** Normalize final mix to `-14 LUFS` (`loudnorm=I=-14:TP=-1.5:LRA=11`).

## 4. Content Rewards & Distribution Rules
- **Brief Compliance First:** Always verify campaign rules (approved stream timestamps, required brand/hashtag mentions, exact destination/title accuracy, allowed logo overlays, no banned logos, no AI-generated footage).
- **Organic Only:** NEVER use paid Promote/Boost on Content Rewards clips (triggers rejection and bans).
- **Posting Schedule (UTC+3):** 2–3 clips/day spaced 3+ hours apart at **5:00 PM**, **8:00 PM**, and **11:30 PM** to hit US/UK/CA/AU peak hours.
- **Submission Window:** Submit live TikTok, Instagram Reels, and YouTube Shorts URLs to Content Rewards within **30 minutes of posting**.
