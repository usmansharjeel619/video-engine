#!/usr/bin/env python3
"""
AI Viral Moment Selection, Virality Scoring, and Vision Hook Grounding.

Adapted from OpenShorts (mutonby/openshorts, MIT License) 2-pass Gemini
selection + Pass-3 vision grounding, enhanced with audio RMS energy signals
for high-hype livestream & gameplay reactions.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"


def load_dotenv_if_available(env_path: Path | None = None) -> None:
    """Load environment variables from .env without failing if python-dotenv is absent."""
    target = env_path or (REPO_ROOT / ".env")
    if not target.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=target, override=False)
        return
    except ImportError:
        pass

    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def get_gemini_model(explicit_model: str | None = None) -> str:
    if explicit_model and explicit_model.strip():
        return explicit_model.strip()
    load_dotenv_if_available()
    env_model = (os.environ.get("GEMINI_MODEL") or "").strip()
    return env_model or DEFAULT_GEMINI_MODEL


def get_gemini_api_key(explicit_key: str | None = None) -> str:
    if explicit_key and explicit_key.strip():
        return explicit_key.strip()
    load_dotenv_if_available()
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to ~/video-engine/.env or pass GEMINI_API_KEY."
        )
    return key


# --- Structured Output Pydantic Schemas ---


class ScoredWindowModel(BaseModel):
    id: str
    start: float
    end: float
    score: int
    reason: str


class ScoreResponse(BaseModel):
    windows: list[ScoredWindowModel]


class DetailClipModel(BaseModel):
    start: float
    end: float
    source_window_id: str
    predicted_score: int
    video_description_for_tiktok: str
    video_description_for_instagram: str
    video_title_for_youtube_short: str
    viral_hook_text: str
    pinned_comment: str = Field(default="")
    why: str = Field(default="")


class DetailResponse(BaseModel):
    shorts: list[DetailClipModel]


class GroundedHook(BaseModel):
    on_screen: str
    viral_hook_text: str
    video_title_for_youtube_short: str


# --- Prompt Templates ---

SCORE_PROMPT_TEMPLATE = """
You are a senior short-form video strategist specializing in viral streamer, gaming, and creator clips.
RANK these candidate windows by how well each would work as a standalone viral vertical short (TikTok / Reels / Shorts).

Rules:
- Return only valid JSON matching the schema.
- Score EVERY window in this batch: exactly one entry per input window with the id you were given.
- `score` must be an integer from 0 to 100 across the full spread:
  - Reserve 75-100 for moments that unambiguously pass THE 2-SECOND TEST below.
  - Put mid conversations or slow buildup in 40-69.
  - Put filler, housekeeping, dead air, outros, or context-dependent rambling under 30.
- THE 2-SECOND TEST (Primary Criterion): Would the first 2 seconds of this moment stop a cold viewer scrolling with zero prior context?
- Prioritize conflict, shock, screams/hype reactions, comedy, outrageous reveals, big numbers, tight twists, or intense gameplay payoffs.
- Each window includes `peak_audio_energy` (0.0-1.0) and `avg_audio_energy` (0.0-1.0) from the audio waveform. High `peak_audio_energy` (>= 0.70) strongly indicates loud reactions, laughter, screams, or dramatic gameplay peaks even when speech is sparse — weigh it alongside the transcript.
{instructions_block}
TRANSCRIPT_LANGUAGE: {language}
VIDEO_DURATION_SECONDS: {video_duration}
WINDOWS_JSON:
{windows_json}
"""

DETAIL_PROMPT_TEMPLATE = """
You are a senior short-form viral video editor and copywriter.
Extract the BEST standalone short clips from these shortlisted candidate windows.

CLIP RULES:
- Return only valid JSON matching the schema.
- Each clip must be {min_secs:g} to {max_secs:g} seconds long, using exact timestamps in absolute seconds from the start of the video.
- Stay within the candidate window boundaries (referencing exact word timestamps provided).
- THE 2-SECOND RULE: The clip MUST open on an immediate hook, high-energy reaction, provocative claim, or compelling action. If a moment starts weak, trim the start closer to the tension or skip it.
- Do not cut mid-word or mid-phrase; snap cleanly to natural pauses around word boundaries.
- STANDS ALONE: A cold viewer scrolling TikTok/Reels/Shorts must immediately understand the premise without seeing the rest of the VOD. Never start on an unexplained pronoun ("that thing", "so anyway"). Move start slightly earlier if 2-4s of setup makes the payoff land harder — never cut off the payoff!
- HOW MANY: Return {min_clips} to {max_clips} clips sorted best-to-worst by `predicted_score`. Inspect EVERY shortlisted window and pick genuine bangers (never pad with weak filler).
- DIVERSITY: Never return two clips covering the same joke, point, or beat.
{instructions_block}{keyword_block}
HOOK PLAYBOOK — craft `viral_hook_text` (max 10 words + 1-2 fitting emojis in {language}):
- Make it laser-specific to THIS clip's concrete event, number, character, or reaction — NEVER a generic video summary.
- Strong proven patterns (adapt in {language}):
  * Reaction/Shock: "HE ACTUALLY LOST IT OVER THIS 😭🔥"
  * Reveal/Twist: "Wait until you see what appeared... 💀"
  * Hot Take / Mistake: "Nobody expected this to happen 🚨"
  * Question Loop: "Why did he stop mid-chase?! 🤯"

COPY RULES (all text in {language}):
- `video_description_for_tiktok` & `video_description_for_instagram`: 1-2 punchy curiosity sentences teasing the payoff + 3-5 relevant hashtags{extra_tags_hint}.
- `video_title_for_youtube_short`: <= 100 chars, curiosity-driven, truthful.
- `pinned_comment`: 1 relatable, conversational viewer comment to drive replies.
- `why`: <= 20 words naming the concrete hook/payoff that makes this clip viral.
- `predicted_score`: honest integer 0-100 estimate of viral potential.

TRANSCRIPT_LANGUAGE: {language}
VIDEO_DURATION_SECONDS: {video_duration}
CANDIDATE_WINDOWS_JSON:
{windows_json}
"""

GROUNDED_HOOK_PROMPT = """
These 3 frames come in order from ONE vertical/streamer clip, and the transcript below is what was spoken during it.
The draft hook/title were written from transcript alone without seeing the webcam reaction or on-screen action.

1. `on_screen`: Name the concrete visual action, expression, game/scene element, character, or text visible in the frames (1 line).
2. `viral_hook_text`: Rewrite a scroll-stopping overlay (STRICT MAX 10 WORDS + 1-2 fitting emojis, in {language}). Ground it in what is ACTUALLY visible in the frames + the single strongest concrete fact/reaction in the transcript. Never write generic summaries that could apply to any clip.
3. `video_title_for_youtube_short`: <= 100 chars in {language}, grounded in both visuals and speech, truthful and curiosity-driven.

TRANSCRIPT_LANGUAGE: {language}
CURRENT_HOOK: {current_hook}
CURRENT_TITLE: {current_title}
CLIP_TRANSCRIPT:
{transcript}

Return only JSON matching the schema.
"""


# --- Pure Helpers (Windowing, Snapping, Dedupe, Ranking) ---


def _word_text(w: dict[str, Any]) -> str:
    return str(w.get("word") if "word" in w else w.get("w", "")).strip()


def _word_start(w: dict[str, Any]) -> float:
    return float(w["start"] if "start" in w else w.get("s", 0.0))


def _word_end(w: dict[str, Any]) -> float:
    return float(w["end"] if "end" in w else w.get("e", 0.0))


def compact_words(words: list[dict[str, Any]], precision: int = 2) -> list[dict[str, Any]]:
    """Compact word list to {'w','s','e'} with rounded timestamps to minimize tokens."""
    return [
        {
            "w": _word_text(w),
            "s": round(_word_start(w), precision),
            "e": round(_word_end(w), precision),
        }
        for w in (words or [])
        if _word_text(w)
    ]


def shortlist_target(video_duration: float) -> int:
    try:
        seconds = float(video_duration or 0.0)
    except (TypeError, ValueError):
        seconds = 0.0
    return max(3, min(10, int(seconds // 90) + 2))


def score_batches(windows: list[dict[str, Any]], batch_size: int = 8) -> list[list[dict[str, Any]]]:
    """Split windows into near-equal batches so trailing windows never form tiny uncompetitive batches."""
    items = list(windows or [])
    n = len(items)
    if not n:
        return []
    size = max(1, int(batch_size or 1))
    n_batches = max(1, -(-n // size))
    base, extra = divmod(n, n_batches)
    out: list[list[dict[str, Any]]] = []
    start = 0
    for idx in range(n_batches):
        take = base + (1 if idx < extra else 0)
        batch = items[start : start + take]
        start += take
        if batch:
            out.append(batch)
    return out


def clip_count_targets(n_windows: int, top_n: int) -> tuple[int, int]:
    """Ask Gemini for enough high-scoring clips to comfortably select top_n after filtering."""
    n = max(1, int(n_windows or 1))
    wanted = max(1, int(top_n or 1))
    low = max(wanted, min(6, n // 2 + 2))
    high = min(14, max(wanted * 2, n * 2, low + 2))
    low = min(low, high)
    return low, high


def _window_energy_stats(
    energies: list[float] | None, start_s: float, end_s: float
) -> tuple[float, float]:
    if not energies:
        return 0.0, 0.0
    s_idx = max(0, int(math.floor(start_s)))
    e_idx = min(len(energies), int(math.ceil(end_s)))
    if e_idx <= s_idx:
        idx = min(len(energies) - 1, max(0, s_idx))
        val = float(energies[idx])
        return round(val, 3), round(val, 3)
    sl = energies[s_idx:e_idx]
    return round(float(max(sl)), 3), round(float(sum(sl) / len(sl)), 3)


def build_transcript_windows(
    transcript_result: dict[str, Any],
    video_duration: float,
    energies: list[float] | None = None,
    window_seconds: float = 90.0,
    overlap_seconds: float = 30.0,
) -> list[dict[str, Any]]:
    """Build segment-aligned overlapping candidate windows enriched with RMS audio energy."""
    segments: list[dict[str, Any]] = []
    for seg in transcript_result.get("segments", []):
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            {
                "start": float(seg.get("start", 0.0)),
                "end": float(seg.get("end", 0.0)),
                "text": text,
                "words": seg.get("words") or [],
            }
        )

    windows: list[dict[str, Any]] = []
    w_idx = 1
    i = 0
    n = len(segments)
    while i < n:
        w_start = segments[i]["start"]
        j = i
        while j + 1 < n and segments[j + 1]["end"] - w_start <= window_seconds * 1.25:
            j += 1
            if segments[j]["end"] - w_start >= window_seconds:
                break
        w_end = segments[j]["end"]
        peak_e, avg_e = _window_energy_stats(energies, w_start, w_end)
        chunk_segs = segments[i : j + 1]
        chunk_words = [w for s in chunk_segs for w in s["words"]]
        windows.append(
            {
                "id": f"window_{w_idx:03d}",
                "start": round(w_start, 3),
                "end": round(w_end, 3),
                "text": " ".join(s["text"] for s in chunk_segs),
                "peak_audio_energy": peak_e,
                "avg_audio_energy": avg_e,
                "_words": chunk_words,
            }
        )
        w_idx += 1

        if j >= n - 1:
            break
        target = w_end - overlap_seconds
        k = i + 1
        while k <= j and segments[k]["start"] < target:
            k += 1
        i = max(k, i + 1)

    if not windows:
        peak_e, avg_e = _window_energy_stats(energies, 0.0, float(video_duration or 0.0))
        all_words = [w for s in transcript_result.get("segments", []) for w in (s.get("words") or [])]
        windows.append(
            {
                "id": "window_001",
                "start": 0.0,
                "end": round(float(video_duration), 3),
                "text": str(transcript_result.get("text") or ""),
                "peak_audio_energy": peak_e,
                "avg_audio_energy": avg_e,
                "_words": all_words,
            }
        )
    return windows


def snap_clip_to_words(
    start: float,
    end: float,
    words: list[dict[str, Any]],
    video_duration: float,
    min_duration: float = 15.0,
    max_duration: float = 60.0,
    search_window: float = 1.5,
    max_lead: float = 0.35,
    max_tail: float = 0.45,
) -> tuple[float, float]:
    """Snap Gemini boundaries onto real word start/end edges plus surrounding pause lead/tail."""
    original = (round(float(start), 3), round(float(end), 3))
    if not words:
        return original

    starts = [_word_start(w) for w in words]
    ends = [_word_end(w) for w in words]

    new_start = float(start)
    cand_starts = [s for s in starts if abs(s - new_start) <= search_window]
    if cand_starts:
        word_start = min(cand_starts, key=lambda s: abs(s - new_start))
        prev_ends = [e for e in ends if e <= word_start]
        lead = min(max_lead, max(0.0, word_start - max(prev_ends)) / 2.0) if prev_ends else max_lead
        new_start = max(0.0, word_start - lead)

    new_end = float(end)
    cand_ends = [e for e in ends if abs(e - new_end) <= search_window]
    if cand_ends:
        word_end = min(cand_ends, key=lambda e: abs(e - new_end))
        next_starts = [s for s in starts if s >= word_end]
        tail = min(max_tail, max(0.0, min(next_starts) - word_end) / 2.0) if next_starts else max_tail
        new_end = min(float(video_duration), word_end + tail)

    if new_end - new_start < min_duration:
        target = new_start + min_duration
        later = sorted(e for e in ends if e >= target)
        if later and later[0] - new_start <= max_duration:
            new_end = min(float(video_duration), later[0] + 0.2)
        else:
            return original
    if new_end - new_start > max_duration:
        target = new_start + max_duration
        earlier = [e for e in ends if new_start < e <= target]
        new_end = (max(earlier) + 0.2) if earlier else target
        new_end = min(new_end, new_start + max_duration, float(video_duration))

    if new_end <= new_start or new_end - new_start < min_duration:
        return original
    return (round(new_start, 3), round(new_end, 3))


def dedupe_overlapping(shorts: list[dict[str, Any]], ratio: float = 0.25) -> list[dict[str, Any]]:
    """Drop clips overlapping >= ratio of the shorter clip, keeping higher predicted_score."""
    def _score(c: dict[str, Any]) -> float:
        try:
            return float(c.get("predicted_score") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _span(c: dict[str, Any]) -> tuple[float, float]:
        try:
            return float(c.get("start", 0.0)), float(c.get("end", 0.0))
        except (TypeError, ValueError):
            return 0.0, 0.0

    indexed = list(enumerate(shorts or []))
    kept: list[tuple[int, dict[str, Any]]] = []
    for idx, clip in sorted(indexed, key=lambda p: (-_score(p[1]), p[0])):
        s, e = _span(clip)
        clash = False
        for _, other in kept:
            os_, oe = _span(other)
            overlap = min(e, oe) - max(s, os_)
            shorter = max(1e-6, min(e - s, oe - os_))
            if overlap > 0 and overlap / shorter >= ratio:
                clash = True
                break
        if not clash:
            kept.append((idx, clip))
    return [c for _, c in sorted(kept, key=lambda p: p[0])]


def trim_to_best(shorts: list[dict[str, Any]], max_clips: int) -> list[dict[str, Any]]:
    """Keep top max_clips by predicted_score, returned in chronological/original order."""
    if max_clips <= 0 or len(shorts) <= max_clips:
        return list(shorts)

    def _score(pair: tuple[int, dict[str, Any]]) -> float:
        try:
            return float(pair[1].get("predicted_score") or 0)
        except (TypeError, ValueError):
            return 0.0

    best = sorted(enumerate(shorts), key=lambda p: (-_score(p), p[0]))[:max_clips]
    return [item for _, item in sorted(best, key=lambda p: p[0])]


# --- JSON Extraction & Parsing Helpers ---


def _strip_code_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _extract_json_candidate(text: str) -> str:
    cleaned = _strip_code_fences(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned


def _escape_invalid_unicode_escapes(text: str) -> str:
    chars: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] == "u":
            hex_digits = text[i + 2 : i + 6]
            if len(hex_digits) < 4 or any(c not in "0123456789abcdefABCDEF" for c in hex_digits):
                chars.append("\\\\u")
                i += 2
                continue
        chars.append(text[i])
        i += 1
    return "".join(chars)


def _parse_json_response_text(text: str) -> dict[str, Any]:
    if not text:
        raise ValueError("Gemini returned an empty response body.")
    candidate = _extract_json_candidate(text).replace("\x00", "").strip()
    if not candidate:
        raise ValueError("Gemini response did not contain a JSON object.")
    attempts = [candidate]
    sanitized = _escape_invalid_unicode_escapes(candidate)
    if sanitized != candidate:
        attempts.append(sanitized)
    last_err: Exception | None = None
    for attempt in attempts:
        try:
            return json.loads(attempt)
        except json.JSONDecodeError as e:
            last_err = e
    raise ValueError(f"Failed to parse Gemini JSON response: {last_err}")


def _response_to_dict(response: Any) -> dict[str, Any]:
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        if isinstance(parsed, BaseModel):
            return parsed.model_dump()
        if isinstance(parsed, dict):
            return parsed
    text = getattr(response, "text", None) or ""
    if not text and getattr(response, "candidates", None):
        parts = response.candidates[0].content.parts
        text = "".join(getattr(p, "text", "") or "" for p in parts)
    return _parse_json_response_text(text)


def _log_token_usage(stage: str, response: Any) -> None:
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return
    in_tok = getattr(usage, "prompt_token_count", 0) or 0
    out_tok = getattr(usage, "candidates_token_count", 0) or 0
    print(f"  [Gemini:{stage}] tokens in={in_tok} out={out_tok}")


# --- Gemini Pipeline Passes ---


def score_windows_gemini(
    client: Any,
    model_name: str,
    windows: list[dict[str, Any]],
    video_duration: float,
    language: str = "en",
    instructions: str | None = None,
    batch_size: int = 8,
) -> list[dict[str, Any]]:
    """Pass 1: Score every overlapping candidate window on the 2-Second Test and shortlist top N."""
    from google.genai import types as genai_types

    if not windows:
        return []

    win_lookup = {w["id"]: w for w in windows}
    instr_block = (
        f"- CAMPAIGN / CREATOR INSTRUCTIONS (apply heavily when ranking): {instructions.strip()}\n"
        if instructions and instructions.strip()
        else ""
    )
    scored_by_id: dict[str, dict[str, Any]] = {}
    batches = score_batches(windows, batch_size=batch_size)

    for b_idx, batch in enumerate(batches, start=1):
        payload = [
            {
                "id": w["id"],
                "start": w["start"],
                "end": w["end"],
                "peak_audio_energy": w.get("peak_audio_energy", 0.0),
                "avg_audio_energy": w.get("avg_audio_energy", 0.0),
                "text": w["text"],
            }
            for w in batch
        ]
        prompt = SCORE_PROMPT_TEMPLATE.format(
            language=language or "en",
            video_duration=round(float(video_duration), 2),
            windows_json=json.dumps(payload, ensure_ascii=False),
            instructions_block=instr_block,
        )
        print(f"Pass 1: Scoring batch {b_idx}/{len(batches)} ({len(batch)} windows) via {model_name}...")
        resp = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ScoreResponse,
                temperature=0.3,
            ),
        )
        _log_token_usage(f"score-{b_idx}", resp)
        data = _response_to_dict(resp)
        for item in data.get("windows", []):
            wid = item.get("id")
            if wid in win_lookup:
                merged = dict(win_lookup[wid])
                merged["window_score"] = int(item.get("score") or 0)
                merged["window_reason"] = str(item.get("reason") or "").strip()
                scored_by_id[wid] = merged

    ranked = sorted(
        scored_by_id.values(),
        key=lambda w: (-int(w.get("window_score", 0)), float(w.get("start", 0.0))),
    )
    if not ranked:
        return list(windows[: shortlist_target(video_duration)])

    target = shortlist_target(video_duration)
    shortlisted = sorted(ranked[:target], key=lambda w: float(w["start"]))
    return shortlisted


def select_clips_gemini(
    client: Any,
    model_name: str,
    shortlisted_windows: list[dict[str, Any]],
    all_words: list[dict[str, Any]],
    video_duration: float,
    min_duration: float = 20.0,
    max_duration: float = 55.0,
    top_n: int = 5,
    min_virality: int = 65,
    allow_below_min: bool = False,
    language: str = "en",
    instructions: str | None = None,
    require_keyword: str | None = None,
    extra_tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Pass 2: Extract exact viral clips, hooks, platform copy & snap edges to words."""
    from google.genai import types as genai_types

    if not shortlisted_windows:
        return []

    min_clips, max_clips = clip_count_targets(len(shortlisted_windows), top_n=top_n)
    instr_block = (
        f"- CAMPAIGN / CREATOR INSTRUCTIONS: {instructions.strip()}\n"
        if instructions and instructions.strip()
        else ""
    )
    kw_block = (
        f"- REQUIRED KEYWORD/TOPIC: Every selected clip MUST feature or discuss '{require_keyword.strip()}'.\n"
        if require_keyword and require_keyword.strip()
        else ""
    )
    tags_hint = (
        f" (always include {' '.join('#' + t.lstrip('#') for t in extra_tags if t.strip())})"
        if extra_tags
        else ""
    )

    detail_payload = [
        {
            "id": w["id"],
            "start": w["start"],
            "end": w["end"],
            "window_score": w.get("window_score", 0),
            "peak_audio_energy": w.get("peak_audio_energy", 0.0),
            "words": compact_words(w.get("_words") or []),
        }
        for w in shortlisted_windows
    ]

    prompt = DETAIL_PROMPT_TEMPLATE.format(
        min_secs=min_duration,
        max_secs=max_duration,
        min_clips=min_clips,
        max_clips=max_clips,
        language=language or "en",
        video_duration=round(float(video_duration), 2),
        windows_json=json.dumps(detail_payload, ensure_ascii=False),
        instructions_block=instr_block,
        keyword_block=kw_block,
        extra_tags_hint=tags_hint,
    )
    print(f"Pass 2: Extracting clips & hooks from {len(shortlisted_windows)} shortlisted windows via {model_name}...")
    resp = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DetailResponse,
            temperature=0.4,
        ),
    )
    _log_token_usage("detail", resp)
    data = _response_to_dict(resp)
    raw_shorts = list(data.get("shorts") or [])

    processed: list[dict[str, Any]] = []
    for item in raw_shorts:
        s0 = max(0.0, float(item.get("start") or 0.0))
        e0 = min(float(video_duration), float(item.get("end") or 0.0))
        if e0 - s0 < 5.0:
            continue
        snapped_s, snapped_e = snap_clip_to_words(
            s0, e0, all_words, video_duration, min_duration=min_duration, max_duration=max_duration
        )
        clip_words = [
            w for w in all_words if _word_end(w) >= snapped_s - 0.05 and _word_start(w) <= snapped_e + 0.05
        ]
        clip_text = " ".join(_word_text(w) for w in clip_words).strip()
        if require_keyword and require_keyword.strip().lower() not in clip_text.lower():
            continue

        processed.append(
            {
                "start": snapped_s,
                "end": snapped_e,
                "duration": round(snapped_e - snapped_s, 2),
                "source_window_id": item.get("source_window_id", ""),
                "predicted_score": int(item.get("predicted_score") or 0),
                "viral_hook_text": str(item.get("viral_hook_text") or "").strip(),
                "video_title_for_youtube_short": str(item.get("video_title_for_youtube_short") or "").strip(),
                "video_description_for_tiktok": str(item.get("video_description_for_tiktok") or "").strip(),
                "video_description_for_instagram": str(item.get("video_description_for_instagram") or "").strip(),
                "pinned_comment": str(item.get("pinned_comment") or "").strip(),
                "why": str(item.get("why") or "").strip(),
                "text": clip_text,
                "words": clip_words,
            }
        )

    deduped = dedupe_overlapping(processed, ratio=0.25)
    if min_virality > 0:
        passing = [c for c in deduped if c["predicted_score"] >= min_virality]
        if not passing and deduped and allow_below_min:
            print(
                f"Warning: 0 clips reached min_virality={min_virality}; falling back to top candidates due to --allow-below-min."
            )
            passing = deduped
        deduped = passing

    best = trim_to_best(deduped, max_clips=top_n)
    return sorted(best, key=lambda c: -int(c.get("predicted_score", 0)))


def ground_hook_with_vision(
    client: Any,
    model_name: str,
    source_video: Path,
    abs_start: float,
    abs_end: float,
    transcript_text: str,
    current_hook: str,
    current_title: str,
    language: str = "en",
) -> dict[str, str] | None:
    """Pass 3: Inspect 3 frames from the clip via Gemini Vision and ground hook + title to screen action."""
    from google.genai import types as genai_types

    dur = max(1.0, float(abs_end) - float(abs_start))
    timestamps = [abs_start + dur * frac for frac in (0.15, 0.50, 0.85)]

    try:
        with tempfile.TemporaryDirectory(prefix="vframe_") as tmpdir:
            parts: list[Any] = []
            for idx, ts in enumerate(timestamps, start=1):
                jpg = Path(tmpdir) / f"f{idx}.jpg"
                proc = subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-ss",
                        f"{max(0.0, ts):.3f}",
                        "-i",
                        str(source_video),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=1024:-2",
                        "-q:v",
                        "3",
                        str(jpg),
                    ],
                    capture_output=True,
                    check=False,
                )
                if proc.returncode == 0 and jpg.exists() and jpg.stat().st_size > 0:
                    parts.append(
                        genai_types.Part.from_bytes(
                            data=jpg.read_bytes(),
                            mime_type="image/jpeg",
                        )
                    )

            if not parts:
                return None

            prompt = GROUNDED_HOOK_PROMPT.format(
                language=language or "en",
                current_hook=current_hook,
                current_title=current_title,
                transcript=transcript_text[:2500],
            )
            parts.append(prompt)
            resp = client.models.generate_content(
                model=model_name,
                contents=parts,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=GroundedHook,
                    temperature=0.35,
                ),
            )
            _log_token_usage("vision-hook", resp)
            data = _response_to_dict(resp)
            hook = str(data.get("viral_hook_text") or "").strip()
            title = str(data.get("video_title_for_youtube_short") or "").strip()
            on_screen = str(data.get("on_screen") or "").strip()
            if hook:
                return {
                    "on_screen": on_screen,
                    "viral_hook_text": hook,
                    "video_title_for_youtube_short": title or current_title,
                }
            return None
    except Exception as exc:
        print(f"Warning: Vision hook grounding skipped (keeping draft hook): {exc}")
        return None


def analyze_and_select_viral_clips(
    transcript_result: dict[str, Any],
    energies: list[float],
    source_video: Path,
    offset_seconds: float = 0.0,
    min_duration: float = 20.0,
    max_duration: float = 55.0,
    top_n: int = 5,
    min_virality: int = 65,
    allow_below_min: bool = False,
    ground_hooks: bool = True,
    instructions: str | None = None,
    require_keyword: str | None = None,
    extra_tags: list[str] | None = None,
    model_name: str | None = None,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Run full Pass 1 -> Pass 2 -> Pass 3 Gemini viral moment selection."""
    from google import genai
    from google.genai import types as genai_types

    resolved_key = get_gemini_api_key(api_key)
    resolved_model = get_gemini_model(model_name)
    client = genai.Client(
        api_key=resolved_key,
        http_options=genai_types.HttpOptions(api_version="v1beta"),
    )

    all_words = [
        w for seg in transcript_result.get("segments", []) for w in (seg.get("words") or [])
    ]
    video_duration = float(transcript_result.get("duration") or 0.0)
    if video_duration <= 0.0 and all_words:
        video_duration = max(_word_end(w) for w in all_words)
    language = str(transcript_result.get("language") or "en")

    windows = build_transcript_windows(
        transcript_result,
        video_duration=video_duration,
        energies=energies,
    )
    shortlisted = score_windows_gemini(
        client=client,
        model_name=resolved_model,
        windows=windows,
        video_duration=video_duration,
        language=language,
        instructions=instructions,
    )
    selected = select_clips_gemini(
        client=client,
        model_name=resolved_model,
        shortlisted_windows=shortlisted,
        all_words=all_words,
        video_duration=video_duration,
        min_duration=min_duration,
        max_duration=max_duration,
        top_n=top_n,
        min_virality=min_virality,
        allow_below_min=allow_below_min,
        language=language,
        instructions=instructions,
        require_keyword=require_keyword,
        extra_tags=extra_tags,
    )

    if ground_hooks and selected and source_video.exists():
        print(f"Pass 3: Vision-grounding hooks on {len(selected)} selected clips via {resolved_model}...")
        for idx, clip in enumerate(selected, start=1):
            abs_s = offset_seconds + clip["start"]
            abs_e = offset_seconds + clip["end"]
            grounded = ground_hook_with_vision(
                client=client,
                model_name=resolved_model,
                source_video=source_video,
                abs_start=abs_s,
                abs_end=abs_e,
                transcript_text=clip.get("text", ""),
                current_hook=clip.get("viral_hook_text", ""),
                current_title=clip.get("video_title_for_youtube_short", ""),
                language=language,
            )
            if grounded:
                clip["on_screen"] = grounded["on_screen"]
                clip["viral_hook_text"] = grounded["viral_hook_text"]
                clip["video_title_for_youtube_short"] = grounded["video_title_for_youtube_short"]
                print(f"  [{idx}] Hook grounded -> {clip['viral_hook_text']} (screen: {clip['on_screen'][:70]})")

    return selected
