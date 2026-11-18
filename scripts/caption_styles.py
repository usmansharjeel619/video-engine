#!/usr/bin/env python3
"""
Kinetic Animated ASS Subtitle Generator (OpusClip / OpenShorts Presets).

Supports 6 curated short-form caption presets (hormozi, pop, pill, lime,
oneword, clean), smooth pop scaling transitions, opaque active-word highlight
boxes, word-by-word Hormozi reveal mode, smart punctuation/pause block breaking,
and safe lower-third positioning for split-screen and single-frame layouts.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

CAPTION_PRESETS: dict[str, dict[str, Any]] = {
    "hormozi": {
        "font_name": "Montserrat ExtraBold",
        "font_size": 74,
        "font_color": "#FFFFFF",
        "highlight_color": "#FFE500",
        "border_color": "#000000",
        "outline_width": 7,
        "shadow": 4,
        "effect": "pop",
        "uppercase": True,
        "base_opacity": 1.0,
        "max_chars": 14,
        "max_duration": 1.4,
    },
    "pop": {
        "font_name": "Anton",
        "font_size": 86,
        "font_color": "#FFFFFF",
        "highlight_color": "#FFE500",
        "border_color": "#000000",
        "outline_width": 6,
        "shadow": 3,
        "effect": "pop",
        "uppercase": True,
        "base_opacity": 1.0,
        "max_chars": 18,
        "max_duration": 1.4,
    },
    "pill": {
        "font_name": "Montserrat ExtraBold",
        "font_size": 70,
        "font_color": "#FFFFFF",
        "highlight_color": "#7C3AED",
        "active_text_color": "#FFFFFF",
        "border_color": "#000000",
        "outline_width": 6,
        "shadow": 3,
        "effect": "highlight",
        "uppercase": True,
        "base_opacity": 1.0,
        "max_chars": 14,
        "max_duration": 1.4,
    },
    "lime": {
        "font_name": "Montserrat ExtraBold",
        "font_size": 70,
        "font_color": "#FFFFFF",
        "highlight_color": "#A3FF12",
        "active_text_color": "#000000",
        "border_color": "#000000",
        "outline_width": 6,
        "shadow": 3,
        "effect": "highlight",
        "uppercase": True,
        "base_opacity": 1.0,
        "max_chars": 14,
        "max_duration": 1.4,
    },
    "oneword": {
        "font_name": "Anton",
        "font_size": 116,
        "font_color": "#FFFFFF",
        "highlight_color": "#FFE500",
        "border_color": "#000000",
        "outline_width": 8,
        "shadow": 4,
        "effect": "pop",
        "uppercase": True,
        "base_opacity": 1.0,
        "max_chars": 1,
        "max_duration": 1.4,
    },
    "clean": {
        "font_name": "Montserrat ExtraBold",
        "font_size": 62,
        "font_color": "#FFFFFF",
        "highlight_color": "#FFFFFF",
        "border_color": "#000000",
        "outline_width": 0,
        "shadow": 4,
        "effect": "none",
        "uppercase": False,
        "base_opacity": 0.65,
        "max_chars": 16,
        "max_duration": 1.5,
    },
}


def format_ass_time(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    hours, rem = divmod(cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _parse_hex_rgb(hex_color: str, fallback: str = "FFFFFF") -> tuple[int, int, int]:
    clean = re.sub(r"[^0-9A-Fa-f]", "", str(hex_color or ""))
    if len(clean) != 6:
        clean = fallback
    return int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16)


def hex_to_ass_bgr(hex_color: str, fallback: str = "FFFFFF") -> str:
    r, g, b = _parse_hex_rgb(hex_color, fallback)
    return f"&H{b:02X}{g:02X}{r:02X}&"


def hex_to_ass_abgr(hex_color: str, opacity: float = 1.0, fallback: str = "FFFFFF") -> str:
    r, g, b = _parse_hex_rgb(hex_color, fallback)
    alpha = max(0, min(255, int(round((1.0 - max(0.0, min(1.0, opacity))) * 255))))
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}&"


def _dim_hex(hex_color: str, factor: float) -> str:
    r, g, b = _parse_hex_rgb(hex_color)
    f = max(0.05, min(1.0, factor))
    return f"#{int(r * f):02X}{int(g * f):02X}{int(b * f):02X}"


def _clean_token(raw: str) -> str:
    return raw.replace("{", "").replace("}", "").replace("\n", " ").strip()


def _normalize_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize {'word','start','end'} or {'w','s','e'} and merge stray punctuation/contractions."""
    merged: list[dict[str, Any]] = []
    for w in words or []:
        tok = _clean_token(str(w.get("word") if "word" in w else w.get("w", "")))
        if not tok:
            continue
        ws = float(w["start"] if "start" in w else w.get("s", 0.0))
        we = max(ws + 0.04, float(w["end"] if "end" in w else w.get("e", ws + 0.1)))
        if merged and (tok[0] in ",.?!;:%" or tok.startswith("'") or tok.lower() in ("n't", "'s", "'re", "'ve", "'ll", "'d", "'m")):
            merged[-1]["word"] += tok
            merged[-1]["end"] = we
        else:
            merged.append({"word": tok, "start": ws, "end": we})
    return merged


def _collect_word_blocks(
    words: list[dict[str, Any]],
    clip_start: float,
    max_chars: int,
    max_duration: float,
    max_pause: float = 0.45,
) -> list[list[dict[str, Any]]]:
    """Group words into tight readable lines breaking cleanly on chars, duration, pauses, and sentence stops."""
    norm = _normalize_words(words)
    if not norm:
        return []

    rel_words = []
    for w in norm:
        s = max(0.0, w["start"] - clip_start)
        e = max(s + 0.04, w["end"] - clip_start)
        rel_words.append({"word": w["word"], "start": s, "end": e})

    if max_chars <= 1:
        return [[w] for w in rel_words]

    blocks: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    cur_chars = 0

    for w in rel_words:
        tok = w["word"]
        tok_len = len(tok)
        if cur:
            pause = w["start"] - cur[-1]["end"]
            span = w["end"] - cur[0]["start"]
            prev_ends_sentence = cur[-1]["word"].endswith((".", "!", "?"))
            if (
                prev_ends_sentence
                or pause > max_pause
                or span > max_duration
                or (cur_chars + 1 + tok_len > max_chars and len(cur) >= 1)
            ):
                blocks.append(cur)
                cur = []
                cur_chars = 0

        cur.append(w)
        cur_chars = tok_len if len(cur) == 1 else cur_chars + 1 + tok_len

    if cur:
        blocks.append(cur)
    return blocks


def build_styled_ass(
    words: list[dict[str, Any]],
    clip_start: float,
    ass_path: Path,
    preset: str = "hormozi",
    layout: str = "split",
    is_relative: bool = False,
    reveal: bool = False,
) -> bool:
    """
    Generate animated ASS subtitles using one of CAPTION_PRESETS.
    Returns True if subtitle events were written, False if no words were found.
    """
    cfg = CAPTION_PRESETS.get(preset, CAPTION_PRESETS["hormozi"])
    offset = 0.0 if is_relative else float(clip_start)
    blocks = _collect_word_blocks(
        words,
        clip_start=offset,
        max_chars=int(cfg["max_chars"]),
        max_duration=float(cfg["max_duration"]),
    )

    margin_v = 460 if layout == "split" else 440
    font_name = cfg["font_name"]
    font_size = int(cfg["font_size"])
    base_rgb = _dim_hex(cfg["font_color"], float(cfg["base_opacity"]))
    primary_ass = hex_to_ass_abgr(base_rgb, 1.0)
    secondary_ass = hex_to_ass_abgr(cfg["highlight_color"], 1.0)
    outline_ass = hex_to_ass_abgr(cfg["border_color"], 1.0)
    back_ass = hex_to_ass_abgr("#000000", 0.55 if cfg["shadow"] else 0.0)
    outline_w = int(cfg["outline_width"])
    shadow_d = int(cfg["shadow"])

    styles_lines = [
        f"Style: Caption,{font_name},{font_size},{primary_ass},{secondary_ass},{outline_ass},{back_ass},"
        f"-1,0,0,0,100,100,0,0,1,{outline_w},{shadow_d},2,60,60,{margin_v},1"
    ]

    if cfg["effect"] == "highlight":
        box_bg = hex_to_ass_abgr(cfg["highlight_color"], 0.96)
        box_fg = hex_to_ass_abgr(cfg.get("active_text_color", "#FFFFFF"), 1.0)
        styles_lines.append(
            f"Style: CaptionActiveBox,{font_name},{font_size},{box_fg},{box_fg},{box_bg},&H00000000&,"
            f"-1,0,0,0,100,100,0,0,3,16,0,2,60,60,{margin_v},1"
        )

    header = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            *styles_lines,
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )

    events: list[str] = [header]
    hl_bgr = hex_to_ass_bgr(cfg["highlight_color"])
    effect = cfg["effect"]
    uppercase = bool(cfg["uppercase"])

    for block in blocks:
        b_end = max(block[0]["start"] + 0.15, block[-1]["end"])
        for active_idx, active_w in enumerate(block):
            w_start = active_w["start"]
            if active_idx + 1 < len(block):
                w_end = max(w_start + 0.05, block[active_idx + 1]["start"])
            else:
                w_end = max(w_start + 0.08, b_end)

            parts: list[str] = []
            for idx, w in enumerate(block):
                tok = w["word"].upper() if uppercase else w["word"]
                if reveal and idx > active_idx:
                    parts.append(r"{\alpha&HFF&}" + tok + r"{\alpha&H00&}")
                elif idx == active_idx:
                    if effect == "pop":
                        parts.append(
                            rf"{{\c{hl_bgr}\fscx118\fscy118\t(0,90,\fscx106\fscy106)}}"
                            + tok
                            + r"{\rCaption}"
                        )
                    elif effect == "highlight":
                        parts.append(r"{\rCaptionActiveBox}" + tok + r"{\rCaption}")
                    else:
                        parts.append(rf"{{\c{hl_bgr}}}" + tok + r"{\rCaption}")
                else:
                    parts.append(tok)

            events.append(
                f"Dialogue: 0,{format_ass_time(w_start)},{format_ass_time(w_end)},Caption,,0,0,0,,{' '.join(parts)}"
            )

    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text("\n".join(events) + "\n", encoding="utf-8")
    return bool(blocks)
