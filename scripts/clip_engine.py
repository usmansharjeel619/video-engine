#!/usr/bin/env python3
"""
Automated Portrait Clipping Engine v2 (Streamer & Content Rewards Edition).
- Downloads (via yt-dlp) or reads local VOD/stream video (with optional start/end bounds)
- Extracts audio & transcribes with word-level timestamps (faster-whisper)
- Scores moments using audio energy peaks + speech density/hook signals
- Layouts:
  * center: 9:16 vertical center crop
  * blur:   sharp 16:9 centered over darkened blurred 9:16 background
  * split:  Streamer Mode — top facecam (auto-detected or corner preset) + bottom gameplay
- Optional --trim-silence dead-air jump cuts with caption re-timing
- Optional --sfx strategic transition/impact cues (whoosh on hook, boom on peak reaction)
- Burns kinetic word-by-word ASS captions in the safe zone + normalizes audio to -14 LUFS
"""

import argparse
import json
import math
import re
import struct
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SFX_DIR = REPO_ROOT / "sfx"
YUNET_MODEL_PATH = REPO_ROOT / "models" / "face_detection_yunet_2023mar.onnx"


def default_cookies_path() -> Path | None:
    cand = REPO_ROOT / ".creds" / "youtube_cookies.txt"
    return cand if cand.exists() else None


def _ffmpeg_filter_escape(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:")


def parse_timestamp(ts: str) -> float:
    """Convert HH:MM:SS, MM:SS, or seconds string to float seconds."""
    ts = ts.strip()
    if re.fullmatch(r"\d+(\.\d+)?", ts):
        return float(ts)
    parts = [float(p) for p in ts.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"Invalid timestamp format: {ts}")


def format_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp H:MM:SS.cc."""
    cs = max(0, int(round(seconds * 100)))
    hours, rem = divmod(cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def run_cmd(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr}")
    return proc.stdout


def extract_wav(video_path: Path, wav_path: Path, start: float | None, end: float | None) -> None:
    cmd = ["ffmpeg", "-y"]
    if start is not None:
        cmd.extend(["-ss", str(start)])
    if end is not None:
        cmd.extend(["-to", str(end)])
    cmd.extend(["-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(wav_path)])
    run_cmd(cmd)


def compute_rms_per_second(wav_path: Path) -> list[float]:
    """Compute normalized RMS energy per second from a 16kHz mono 16-bit WAV."""
    energies: list[float] = []
    with wave.open(str(wav_path), "rb") as wf:
        rate = wf.getframerate()
        chunk_frames = rate
        while True:
            data = wf.readframes(chunk_frames)
            if not data:
                break
            n_samples = len(data) // 2
            if n_samples == 0:
                break
            samples = struct.unpack(f"<{n_samples}h", data)
            sq = sum(s * s for s in samples) / n_samples
            energies.append(math.sqrt(sq))
    max_e = max(energies) if energies else 1.0
    if max_e <= 0:
        max_e = 1.0
    return [e / max_e for e in energies]


def transcribe_audio(wav_path: Path, model_size: str, language: str | None) -> dict[str, Any]:
    import numpy as np
    from faster_whisper import WhisperModel

    with wave.open(str(wav_path), "rb") as wf:
        raw_bytes = wf.readframes(wf.getnframes())
    audio_np = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments_iter, info = model.transcribe(audio_np, language=language, word_timestamps=True)
    segments = []
    for idx, seg in enumerate(segments_iter, start=1):
        raw_words = [w for w in (seg.words or []) if w.word.strip()]
        words: list[dict[str, Any]] = []
        for w in raw_words:
            tok = w.word.strip()
            if words and (tok[0] in ",.?!;:%" or tok.startswith("'")):
                words[-1]["word"] += tok
                words[-1]["end"] = round(w.end, 3)
            else:
                words.append({"word": tok, "start": round(w.start, 3), "end": round(w.end, 3)})
        segments.append(
            {
                "id": idx,
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
                "words": words,
            }
        )
    return {"language": info.language, "duration": round(info.duration, 3), "segments": segments}


HOOK_KEYWORDS = {
    "what", "why", "how", "wait", "bro", "yo", "no way", "crazy", "insane",
    "stop", "look", "listen", "never", "actually", "literally", "watch", "omg",
    "secret", "money", "million", "win", "lost", "fight", "run", "help",
}


def find_peak_offset(energies: list[float], start_t: float, end_t: float) -> float:
    """Return offset in seconds (relative to start_t) of the highest audio energy spike."""
    s_idx = max(0, int(start_t))
    e_idx = min(len(energies), int(math.ceil(end_t)))
    if e_idx <= s_idx:
        return max(1.5, (end_t - start_t) * 0.5)
    window = energies[s_idx:e_idx]
    best_i = max(range(len(window)), key=lambda i: window[i])
    return round(max(0.5, min(end_t - start_t - 0.5, float(best_i) + 0.3)), 2)


def score_windows(
    segments: list[dict[str, Any]],
    energies: list[float],
    min_dur: float,
    max_dur: float,
    top_n: int,
    require_keyword: str | None = None,
) -> list[dict[str, Any]]:
    """Find top non-overlapping viral candidate windows snapped to segment boundaries."""
    if not segments:
        return []

    candidates: list[dict[str, Any]] = []
    n = len(segments)

    for i in range(n):
        start_t = segments[i]["start"]
        for j in range(i, n):
            end_t = segments[j]["end"]
            dur = end_t - start_t
            if dur < min_dur:
                continue
            if dur > max_dur:
                break

            window_segs = segments[i : j + 1]
            text = " ".join(s["text"] for s in window_segs)
            if require_keyword and require_keyword.lower() not in text.lower():
                continue
            words = [w for s in window_segs for w in s["words"]]
            word_count = len(words)
            if word_count < 15:
                continue

            wps = word_count / max(dur, 1.0)
            pace_score = min(wps / 3.2, 1.2)

            s_idx = max(0, int(start_t))
            e_idx = min(len(energies), int(math.ceil(end_t)))
            win_e = energies[s_idx:e_idx] if e_idx > s_idx else [0.0]
            peak_e = max(win_e)
            avg_e = sum(win_e) / len(win_e)
            energy_score = peak_e * 1.4 + avg_e * 0.6

            first_text = " ".join(
                s["text"] for s in window_segs if s["start"] <= start_t + 6.0
            ).lower()
            hook_hits = sum(1 for kw in HOOK_KEYWORDS if kw in first_text)
            punct_hits = text.count("!") + text.count("?")
            hook_score = min(hook_hits * 0.25, 1.2) + min(punct_hits * 0.12, 0.8)

            total_score = round(energy_score + pace_score + hook_score, 3)
            candidates.append(
                {
                    "start": round(start_t, 3),
                    "end": round(end_t, 3),
                    "duration": round(dur, 2),
                    "score": total_score,
                    "peakOffset": find_peak_offset(energies, start_t, end_t),
                    "text": text,
                    "words": words,
                }
            )

    candidates.sort(key=lambda c: c["score"], reverse=True)

    selected: list[dict[str, Any]] = []
    for cand in candidates:
        overlaps = any(
            not (cand["end"] <= sel["start"] + 2.0 or cand["start"] >= sel["end"] - 2.0)
            for sel in selected
        )
        if not overlaps:
            selected.append(cand)
            if len(selected) >= top_n:
                break

    return selected


def compute_jump_cut_segments(
    words: list[dict[str, Any]],
    clip_start: float,
    clip_end: float,
    max_gap: float = 0.55,
    pad: float = 0.12,
) -> tuple[list[tuple[float, float]], list[dict[str, Any]]]:
    """
    Merge spoken intervals separated by <= max_gap and return:
      1. List of (rel_start, rel_end) kept intervals relative to clip_start
      2. Re-timed words list matching the concatenated timeline (0-based!)
    """
    rel_dur = max(0.5, clip_end - clip_start)
    if not words:
        return [(0.0, rel_dur)], []

    intervals: list[list[float]] = []
    for w in words:
        ws = max(0.0, w["start"] - clip_start - pad)
        we = min(rel_dur, w["end"] - clip_start + pad)
        if not intervals or ws - intervals[-1][1] > max_gap:
            intervals.append([ws, we])
        else:
            intervals[-1][1] = max(intervals[-1][1], we)

    # Always keep at least from 0.0 if first word is within 0.4s
    if intervals and intervals[0][0] < 0.4:
        intervals[0][0] = 0.0

    kept = [(round(a, 3), round(b, 3)) for a, b in intervals if b - a >= 0.25]
    if not kept:
        kept = [(0.0, rel_dur)]

    return kept, _retime_words(words, clip_start, kept)


def prepend_flash_hook(
    intervals: list[tuple[float, float]],
    words: list[dict[str, Any]],
    clip_start: float,
    clip_end: float,
    peak_offset: float,
    flash_dur: float = 1.7,
) -> tuple[list[tuple[float, float]], list[dict[str, Any]]]:
    """
    Prepend a 1.7s cold-open flash-forward from the peak moment at t=0.0s,
    followed by the main kept intervals, and re-time all captions accurately.
    """
    rel_dur = max(2.5, clip_end - clip_start)
    combined = intervals
    if peak_offset >= 3.0:
        f_start = round(max(0.0, peak_offset - 0.5), 3)
        f_end = round(min(rel_dur, f_start + flash_dur), 3)
        if f_end - f_start >= 1.0:
            combined = [(f_start, f_end), *intervals]

    return combined, _retime_words(words, clip_start, combined)


def _retime_words(
    words: list[dict[str, Any]], clip_start: float, intervals: list[tuple[float, float]]
) -> list[dict[str, Any]]:
    """Map source word timestamps to the rendered timeline."""
    retimed: list[dict[str, Any]] = []
    acc = 0.0
    for seg_s, seg_e in intervals:
        for w in words:
            rw_s = w["start"] - clip_start
            rw_e = w["end"] - clip_start
            if rw_e >= seg_s and rw_s <= seg_e:
                new_s = acc + max(0.0, rw_s - seg_s)
                new_e = acc + min(seg_e - seg_s, max(0.05, rw_e - seg_s))
                retimed.append({"word": w["word"], "start": round(new_s, 3), "end": round(new_e, 3)})
        acc += seg_e - seg_s
    return retimed


def remap_time_to_intervals(rel_t: float, intervals: list[tuple[float, float]] | None) -> float:
    """Remap a relative source timestamp into the concatenated jump-cut output timeline."""
    if not intervals:
        return round(max(0.5, float(rel_t)), 2)

    # Prefer matches inside the main story segments (skipping a prepended cold-open at idx 0 if >1 interval)
    search_order = list(enumerate(intervals))
    if len(intervals) > 1:
        search_order = search_order[1:] + search_order[:1]

    acc_starts: list[float] = []
    cur = 0.0
    for s, e in intervals:
        acc_starts.append(cur)
        cur += max(0.0, e - s)

    for idx, (s, e) in search_order:
        if s <= rel_t <= e:
            return round(max(0.5, acc_starts[idx] + (rel_t - s)), 2)

    # Nearest main interval edge fallback
    best_out = max(0.5, cur * 0.5)
    best_dist = float("inf")
    for idx, (s, e) in search_order:
        clamped = min(max(rel_t, s), e)
        dist = abs(rel_t - clamped)
        if dist < best_dist:
            best_dist = dist
            best_out = acc_starts[idx] + (clamped - s)
    return round(max(0.5, min(max(0.8, cur - 0.5), best_out)), 2)


def _detect_faces_normalized(frame: Any) -> list[tuple[float, float, float, float, float]]:
    """Return [(cx, cy, w_norm, h_norm, conf), ...] using YuNet (OpenCV 5+) or Haar cascade."""
    import cv2

    fh, fw = frame.shape[:2]
    results: list[tuple[float, float, float, float, float]] = []
    if YUNET_MODEL_PATH.exists() and hasattr(cv2, "FaceDetectorYN"):
        det = cv2.FaceDetectorYN.create(str(YUNET_MODEL_PATH), "", (fw, fh), 0.55, 0.3, 5000)
        _, faces = det.detect(frame)
        if faces is not None:
            for f in faces:
                fx, fy, f_w, f_h, conf = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[-1])
                results.append(((fx + f_w / 2.0) / fw, (fy + f_h / 2.0) / fh, f_w / fw, f_h / fh, conf))
            if results:
                return results

    if hasattr(cv2, "CascadeClassifier"):
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(45, 45))
        for (fx, fy, f_w, f_h) in faces:
            results.append(((fx + f_w / 2.0) / fw, (fy + f_h / 2.0) / fh, f_w / fw, f_h / fh, 0.7))
    return results


def resolve_split_crop(
    source_video: Path, sample_time: float, cam_pos: str
) -> tuple[str, tuple[float, float, float, float], str]:
    """
    Resolve effective layout and webcam/side alignment for a clip.
    Returns (effective_layout, (cx, cy, cw, ch), cam_side ['left'|'right'|'center']).
    In 'auto' mode, switches fullscreen talking-head / no-cam frames to 'center' so split
    never duplicates a fullscreen facecam or crops an empty corner wall.
    """
    presets: dict[str, tuple[float, float, float, float]] = {
        "tl": (0.0, 0.0, 0.34, 0.38),
        "tr": (0.66, 0.0, 0.34, 0.38),
        "bl": (0.0, 0.62, 0.34, 0.38),
        "br": (0.66, 0.62, 0.34, 0.38),
        "center": (0.25, 0.10, 0.50, 0.56),
    }
    if cam_pos in presets:
        side = "left" if cam_pos in ("tl", "bl") else ("right" if cam_pos in ("tr", "br") else "center")
        return ("split", presets[cam_pos], side)
    if "," in cam_pos:
        parts = [float(p.strip()) for p in cam_pos.split(",")]
        if len(parts) == 4:
            side = "left" if parts[0] < 0.3 else ("right" if parts[0] + parts[2] > 0.7 else "center")
            return ("split", (parts[0], parts[1], parts[2], parts[3]), side)

    try:
        import cv2

        cap = cv2.VideoCapture(str(source_video))
        all_faces: list[tuple[float, float, float, float, float]] = []
        for offset_s in (0.0, 2.0, 5.0, 8.0):
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, sample_time + offset_s) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            found = _detect_faces_normalized(frame)
            if found:
                all_faces = found
                break
        cap.release()
        if not all_faces:
            return ("center", presets["center"], "center")

        # Prioritize edge/perimeter streamer webcams over in-game characters near screen center
        edge_faces = [
            f for f in all_faces
            if (f[0] < 0.32 or f[0] > 0.68 or f[1] < 0.30 or f[1] > 0.72) and f[3] < 0.18
        ]
        chosen = max(edge_faces or all_faces, key=lambda f: f[4])
        cx, cy, _, fh_n, _ = chosen

        # If only a huge centered talking-head is found (e.g. Just Chatting), avoid duplicating in split
        if not edge_faces and fh_n >= 0.16 and 0.25 <= cx <= 0.75:
            return ("center", presets["center"], "center")

        # Tight 16:10 webcam window around detected face center; snaps cleanly to left/right borders
        box_w = max(0.22, min(0.34, fh_n * 3.8))
        box_h = max(0.24, min(0.38, box_w * 1.1))
        if cx < 0.18:
            bx = 0.0
        elif cx > 0.82:
            bx = 1.0 - box_w
        else:
            bx = max(0.0, min(1.0 - box_w, cx - box_w / 2.0))
        by = max(0.0, min(1.0 - box_h, cy - box_h * 0.42))
        side = "left" if bx < 0.20 else ("right" if bx + box_w > 0.80 else "center")
        return ("split", (round(bx, 3), round(by, 3), round(box_w, 3), round(box_h, 3)), side)
    except Exception:
        return ("split", presets["tl"], "left")


def detect_facecam_box(source_video: Path, sample_time: float, cam_pos: str) -> tuple[float, float, float, float]:
    """Return normalized (x, y, w, h) facecam crop rectangle for 16:9 -> 1080x700 top panel."""
    _, box, _ = resolve_split_crop(source_video, sample_time, cam_pos)
    return box


def build_kinetic_ass(
    words: list[dict[str, Any]],
    clip_start: float,
    ass_path: Path,
    hook_title: str | None = None,
    chunk_size: int = 3,
    is_relative: bool = False,
    hook_margin_v: int = 220,
) -> None:
    """Generate ASS subtitle file with 2-3 word chunks and active-word highlight in safe zone."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial Black,68,&H00FFFFFF,&H0000D7FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,3,2,60,60,460,1
Style: Hook,Arial Black,48,&H00000000,&H00000000,&H00FFFFFF,&H0000D7FF,-1,0,0,0,100,100,0,0,3,16,0,8,70,70,{hook_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    offset = 0.0 if is_relative else clip_start

    if hook_title:
        clean_hook = hook_title.encode("ascii", "ignore").decode("ascii").replace("{", "").replace("}", "").strip().upper()
        lines.append(
            f"Dialogue: 1,{format_ass_time(0.0)},{format_ass_time(3.2)},Hook,,0,0,0,,{clean_hook}"
        )

    chunks: list[list[dict[str, Any]]] = [
        words[i : i + chunk_size] for i in range(0, len(words), chunk_size)
    ]

    for chunk in chunks:
        c_start = max(0.0, chunk[0]["start"] - offset)
        c_end = max(c_start + 0.15, chunk[-1]["end"] - offset)

        for active_idx, active_w in enumerate(chunk):
            w_start = max(0.0, active_w["start"] - offset)
            if active_idx + 1 < len(chunk):
                w_end = max(w_start + 0.05, chunk[active_idx + 1]["start"] - offset)
            else:
                w_end = c_end

            styled_parts = []
            for idx, w in enumerate(chunk):
                token = w["word"].replace("{", "").replace("}", "").upper()
                if idx == active_idx:
                    styled_parts.append(
                        r"{\c&H0000D7FF&\fscx112\fscy112}" + token + r"{\c&H00FFFFFF&\fscx100\fscy100}"
                    )
                else:
                    styled_parts.append(token)
            text_line = " ".join(styled_parts)
            lines.append(
                f"Dialogue: 0,{format_ass_time(w_start)},{format_ass_time(w_end)},Caption,,0,0,0,,{text_line}"
            )

    ass_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_portrait_clip(
    source_video: Path,
    abs_start: float,
    abs_end: float,
    ass_path: Path,
    output_mp4: Path,
    layout: str,
    logo_path: Path | None = None,
    cam_pos: str = "auto",
    kept_intervals: list[tuple[float, float]] | None = None,
    use_sfx: bool = False,
    peak_offset: float | None = None,
    hook_png: Path | None = None,
    hook_y: int = 724,
    hook_duration: float = 4.2,
    fonts_dir: Path | None = None,
) -> None:
    """
    Render 1080x1920 portrait clip with ASS captions, optional split-screen facecam+gameplay,
    optional styled Pillow hook PNG banner, silence jump-cuts, punch-zoom, logo overlay,
    strategic SFX, and -14 LUFS normalization.
    """
    duration = abs_end - abs_start
    ass_escaped = _ffmpeg_filter_escape(ass_path)
    resolved_fonts = fonts_dir if fonts_dir is not None else (REPO_ROOT / "fonts")
    fonts_arg = f":fontsdir='{_ffmpeg_filter_escape(resolved_fonts)}'" if resolved_fonts.exists() else ""

    # Step 1: Accurate, low-memory A/V-locked seek + optional cold-open flash-forward + jump-cut concat
    # Give each segment its own coarse-seeked input (-copyts -ss max(0, s_t-4)) so FFmpeg only decodes
    # ~4s of frames per cut (prevents RAM OOM buffering on long streams while keeping 0ms A/V sync!).
    inputs: list[str] = []
    filter_parts: list[str] = []
    next_idx = 0

    segments_to_cut = (
        [(abs_start + ks, abs_start + ke) for ks, ke in kept_intervals]
        if kept_intervals
        else [(abs_start, abs_end)]
    )

    seg_labels = []
    for k, (s_t, e_t) in enumerate(segments_to_cut):
        coarse_s = max(0.0, s_t - 4.0)
        coarse_t = (e_t - coarse_s) + 1.0
        inputs.extend(["-copyts", "-ss", f"{coarse_s:.3f}", "-t", f"{coarse_t:.3f}", "-i", str(source_video)])
        in_i = next_idx
        next_idx += 1
        filter_parts.append(f"[{in_i}:v]trim=start={s_t:.3f}:end={e_t:.3f},setpts=PTS-STARTPTS[vseg{k}]")
        filter_parts.append(f"[{in_i}:a]atrim=start={s_t:.3f}:end={e_t:.3f},asetpts=PTS-STARTPTS[aseg{k}]")
        seg_labels.append(f"[vseg{k}][aseg{k}]")

    if len(segments_to_cut) > 1:
        filter_parts.append(f"{''.join(seg_labels)}concat=n={len(segments_to_cut)}:v=1:a=1[vsrc][asrc]")
        v_in, a_in = "[vsrc]", "[asrc]"
    else:
        v_in, a_in = "[vseg0]", "[aseg0]"

    # Step 2: Portrait framing
    effective_layout = layout
    cam_box = (0.0, 0.0, 0.34, 0.38)
    cam_side = "center"
    if layout == "split":
        effective_layout, cam_box, cam_side = resolve_split_crop(source_video, abs_start + duration * 0.3, cam_pos)

    if effective_layout == "blur":
        filter_parts.append(
            f"{v_in}split=2[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=25:5,eq=brightness=-0.08[bg_blur];"
            "[fg]scale=1080:-2:force_original_aspect_ratio=decrease[fg_scaled];"
            "[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[base]"
        )
    elif effective_layout == "split":
        cx, cy, cw, ch = cam_box
        cam_filter = (
            f"[vcam_src]crop=iw*{cw}:ih*{ch}:iw*{cx}:ih*{cy},"
            "scale=1080:700:force_original_aspect_ratio=increase,crop=1080:700"
        )
        if peak_offset is not None:
            p0 = max(0.1, peak_offset - 0.15)
            p1 = p0 + 1.25
            cam_filter += (
                f",scale=w='if(between(t,{p0:.2f},{p1:.2f}),1166,1080)':"
                f"h='if(between(t,{p0:.2f},{p1:.2f}),756,700)':eval=frame,crop=1080:700"
            )
        # Keep bottom gameplay crop clear of left/right corner webcam overlays
        if cam_side == "right":
            game_crop_x = "0"
        elif cam_side == "left":
            game_crop_x = "(iw-ih*1080/1220)"
        else:
            game_crop_x = "(iw-ih*1080/1220)/2"
        filter_parts.append(
            f"{v_in}split=2[vcam_src][vgame_src];"
            f"{cam_filter}[cam_top];"
            f"[vgame_src]crop=ih*1080/1220:ih:{game_crop_x}:0,"
            "scale=1080:1220:flags=lanczos[game_bot];"
            "[cam_top][game_bot]vstack=inputs=2,drawbox=x=0:y=698:w=1080:h=4:color=black@0.85:t=fill,setsar=1[base]"
        )
    else:
        filter_parts.append(
            f"{v_in}crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=lanczos,setsar=1[base]"
        )

    # Step 3: Optional logo + burned-in kinetic ASS captions + optional styled Pillow hook PNG
    if logo_path is not None:
        inputs.extend(["-i", str(logo_path)])
        logo_idx = next_idx
        next_idx += 1
        filter_parts.append(f"[{logo_idx}:v]scale=240:-1[logo]")
        filter_parts.append("[base][logo]overlay=(W-w)/2:110[with_logo]")
        cap_in = "[with_logo]"
    else:
        cap_in = "[base]"

    if hook_png is not None and hook_png.exists():
        h_dur = max(0.8, float(hook_duration))
        fade_st = max(0.4, h_dur - 0.35)
        effective_hook_y = 260 if (layout == "split" and effective_layout == "center") else int(hook_y)
        filter_parts.append(f"{cap_in}ass='{ass_escaped}'{fonts_arg}[with_caps]")
        inputs.extend(["-loop", "1", "-framerate", "30", "-i", str(hook_png)])
        hook_idx = next_idx
        next_idx += 1
        filter_parts.append(f"[{hook_idx}:v]format=rgba,fade=t=out:st={fade_st:.2f}:d=0.35:alpha=1[hook_ov]")
        filter_parts.append(
            f"[with_caps][hook_ov]overlay=(W-w)/2:{effective_hook_y}:enable='between(t,0,{h_dur:.2f})':shortest=1[v]"
        )
    else:
        filter_parts.append(f"{cap_in}ass='{ass_escaped}'{fonts_arg}[v]")

    # Step 4: Optional strategic SFX + -14 LUFS audio normalization
    sfx_tracks: list[tuple[Path, float, int]] = []
    if use_sfx:
        whoosh = SFX_DIR / "whoosh.wav"
        boom = SFX_DIR / "boom.wav"
        if whoosh.exists():
            sfx_tracks.append((whoosh, 0.25, 0))
        if boom.exists() and peak_offset is not None and peak_offset > 1.2:
            sfx_tracks.append((boom, 0.40, int(peak_offset * 1000)))

    if sfx_tracks:
        mix_labels = [a_in]
        for s_idx, (s_path, vol, delay_ms) in enumerate(sfx_tracks):
            inputs.extend(["-i", str(s_path)])
            in_i = next_idx
            next_idx += 1
            lbl = f"[sfx{s_idx}]"
            filter_parts.append(f"[{in_i}:a]volume={vol:.2f},adelay={delay_ms}|{delay_ms}{lbl}")
            mix_labels.append(lbl)
        filter_parts.append(
            f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=first:normalize=0,"
            "loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
        )
    else:
        filter_parts.append(f"{a_in}loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[v]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_mp4),
    ]
    run_cmd(cmd)


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated 9:16 portrait clipper v2 (Streamer Edition).")
    parser.add_argument("--input", "-i", required=True, help="Local video path or URL (downloaded via yt-dlp).")
    parser.add_argument("--output-dir", "-o", type=Path, default=Path("output/clips"), help="Output directory.")
    parser.add_argument("--start", default=None, help="Optional start timestamp in source video (e.g. 02:56:29).")
    parser.add_argument("--end", default=None, help="Optional end timestamp in source video.")
    parser.add_argument("--layout", choices=["center", "blur", "split"], default="split", help="Portrait framing mode.")
    parser.add_argument("--cam-pos", default="auto", help="Facecam position for split mode: auto, tl, tr, bl, br, center, or x,y,w,h (0..1).")
    parser.add_argument("--trim-silence", action="store_true", help="Jump-cut pauses > 0.55s while keeping captions synced.")
    parser.add_argument("--flash-hook", action="store_true", help="Prepend a 1.7s peak-reaction cold-open hook at 0.0s.")
    parser.add_argument("--sfx", action="store_true", help="Add subtle hook whoosh + peak reaction impact SFX.")
    parser.add_argument("--model", default="base", help="Whisper model size (tiny, base, small, medium).")
    parser.add_argument("--language", default=None, help="Optional language code (e.g. en).")
    parser.add_argument("--min-duration", type=float, default=22.0, help="Minimum clip duration in seconds.")
    parser.add_argument("--max-duration", type=float, default=45.0, help="Maximum clip duration in seconds.")
    parser.add_argument("--top-n", type=int, default=5, help="Number of top clips to export.")
    parser.add_argument("--logo", type=Path, default=None, help="Optional PNG logo overlay path.")
    parser.add_argument("--require-keyword", default=None, help="Only select clips containing this keyword.")
    parser.add_argument("--cookies", type=Path, default=None, help="Optional Netscape cookies.txt for yt-dlp.")
    parser.add_argument(
        "--caption-preset",
        choices=["hormozi", "pop", "pill", "lime", "oneword", "clean"],
        default=None,
        help="Optional kinetic caption preset from caption_styles.py.",
    )
    parser.add_argument(
        "--hook-style",
        choices=["pill", "yellow", "red", "dark", "classic", "outline", "outline_yellow"],
        default=None,
        help="Optional Pillow hook overlay banner style from hook_renderer.py.",
    )
    args = parser.parse_args()

    out_dir: Path = args.output_dir.resolve()
    work_dir = out_dir / ".work"
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    if args.input.startswith("http://") or args.input.startswith("https://"):
        source_video = work_dir / "source.mp4"
        if not source_video.exists():
            print(f"Downloading source video via yt-dlp -> {source_video}")
            cookies = args.cookies if args.cookies is not None else default_cookies_path()
            dl_cmd = [sys.executable, "-m", "yt_dlp"]
            if cookies and cookies.exists():
                dl_cmd.extend(["--cookies", str(cookies)])
            dl_cmd.extend([
                "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "--merge-output-format", "mp4",
                "-o", str(source_video),
                args.input,
            ])
            run_cmd(dl_cmd)
    else:
        source_video = Path(args.input).resolve()
        if not source_video.exists():
            raise FileNotFoundError(f"Input file not found: {source_video}")

    start_sec = parse_timestamp(args.start) if args.start else None
    end_sec = parse_timestamp(args.end) if args.end else None
    offset = start_sec or 0.0

    wav_path = work_dir / "audio_16k.wav"
    print("Extracting audio...")
    extract_wav(source_video, wav_path, start_sec, end_sec)
    energies = compute_rms_per_second(wav_path)

    print(f"Transcribing with faster-whisper ({args.model})...")
    transcript = transcribe_audio(wav_path, args.model, args.language)
    (work_dir / "transcript.json").write_text(json.dumps(transcript, indent=2), encoding="utf-8")

    clips = score_windows(
        transcript["segments"],
        energies,
        min_dur=args.min_duration,
        max_dur=args.max_duration,
        top_n=args.top_n,
        require_keyword=args.require_keyword,
    )
    if not clips:
        raise RuntimeError("No candidate clips matched the duration/speech criteria.")

    manifest = []
    logo = args.logo.resolve() if args.logo else None
    for idx, clip in enumerate(clips, start=1):
        ass_path = work_dir / f"clip_{idx:02d}.ass"
        mp4_path = out_dir / f"clip_{idx:02d}.mp4"
        first_sentence = clip["text"].split(".")[0][:48].strip()

        hook_margin = 650 if args.layout == "split" else 220
        kept_intervals: list[tuple[float, float]] | None = None
        if args.trim_silence:
            kept_intervals, retimed_words = compute_jump_cut_segments(
                clip["words"], clip["start"], clip["end"]
            )
            if args.flash_hook:
                kept_intervals, retimed_words = prepend_flash_hook(
                    kept_intervals, clip["words"], clip["start"], clip["end"], clip["peakOffset"]
                )
            words_for_ass = retimed_words
            ass_offset = 0.0
            ass_is_rel = True
        elif args.flash_hook:
            base_iv = [(0.0, round(clip["end"] - clip["start"], 3))]
            kept_intervals, retimed_words = prepend_flash_hook(
                base_iv, clip["words"], clip["start"], clip["end"], clip["peakOffset"]
            )
            words_for_ass = retimed_words
            ass_offset = 0.0
            ass_is_rel = True
        else:
            words_for_ass = clip["words"]
            ass_offset = clip["start"]
            ass_is_rel = False

        if args.caption_preset:
            from caption_styles import build_styled_ass

            build_styled_ass(
                words_for_ass,
                ass_offset,
                ass_path,
                preset=args.caption_preset,
                layout=args.layout,
                is_relative=ass_is_rel,
            )
        else:
            build_kinetic_ass(
                words_for_ass,
                ass_offset,
                ass_path,
                hook_title=None if args.hook_style else first_sentence,
                is_relative=ass_is_rel,
                hook_margin_v=hook_margin,
            )

        abs_start = offset + clip["start"]
        abs_end = offset + clip["end"]
        hook_png = None
        hook_y = 724
        if args.hook_style:
            from hook_renderer import compute_hook_y, create_hook_image

            hook_png, _, hook_h = create_hook_image(
                first_sentence, work_dir / f"hook_{idx:02d}.png", style=args.hook_style
            )
            hook_y = compute_hook_y(args.layout, hook_h, source_video=source_video, sample_time=abs_start + 1.0)

        print(f"Rendering clip {idx}/{len(clips)} ({abs_start:.1f}s -> {abs_end:.1f}s, score={clip['score']})...")
        render_portrait_clip(
            source_video,
            abs_start,
            abs_end,
            ass_path,
            mp4_path,
            args.layout,
            logo_path=logo,
            cam_pos=args.cam_pos,
            kept_intervals=kept_intervals,
            use_sfx=args.sfx,
            peak_offset=clip.get("peakOffset"),
            hook_png=hook_png,
            hook_y=hook_y,
        )
        manifest.append(
            {
                "clip": mp4_path.name,
                "path": str(mp4_path),
                "sourceStart": round(abs_start, 2),
                "sourceEnd": round(abs_end, 2),
                "duration": clip["duration"],
                "score": clip["score"],
                "transcript": clip["text"],
            }
        )

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Done! Exported {len(manifest)} portrait clips to {out_dir}")


if __name__ == "__main__":
    main()
