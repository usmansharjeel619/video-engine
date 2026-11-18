#!/usr/bin/env python3
"""
Styled Hook Overlay Renderer & Smart Placement (adapted from OpenShorts).

Renders transparent RGBA PNG hook banners using Montserrat ExtraBold / Anton /
Noto Serif Bold + color emoji strike-size handling (NotoColorEmoji 109px /
Segoe UI Emoji), and computes collision-free Y placement for split-screen and
single-frame 1080x1920 vertical videos.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = REPO_ROOT / "fonts"

HOOK_FONTS: dict[str, tuple[str, float]] = {
    "montserrat": (str(FONT_DIR / "Montserrat-ExtraBold.ttf"), 0.064),
    "anton": (str(FONT_DIR / "Anton-Regular.ttf"), 0.080),
    "archivoblack": (str(FONT_DIR / "ArchivoBlack-Regular.ttf"), 0.062),
    "serif": (str(FONT_DIR / "NotoSerif-Bold.ttf"), 0.056),
}

_FALLBACK_TEXT_FONTS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
]

_EMOJI_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto-emoji/NotoColorEmoji.ttf",
    "C:\\Windows\\Fonts\\seguiemj.ttf",
    "/System/Library/Fonts/Apple Color Emoji.ttc",
]

# Bitmap strike size required by NotoColorEmoji.ttf (109px).
_BITMAP_EMOJI_STRIKE = 109

_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF"
    "\U0000FE0E\U0000FE0F"
    "\U0000200D"
    "\U000020E3"
    "]+"
)

HOOK_STYLES: dict[str, dict[str, Any]] = {
    "pill": {
        "box": (255, 255, 255, 250),
        "text": (0, 0, 0),
        "outline": None,
        "shadow": False,
        "font": "montserrat",
        "pills": True,
    },
    "classic": {
        "box": (255, 255, 255, 242),
        "text": (0, 0, 0),
        "outline": None,
        "shadow": True,
        "font": "serif",
        "pills": False,
    },
    "dark": {
        "box": (18, 18, 20, 235),
        "text": (255, 255, 255),
        "outline": None,
        "shadow": True,
        "font": "montserrat",
        "pills": False,
    },
    "yellow": {
        "box": (255, 214, 0, 245),
        "text": (0, 0, 0),
        "outline": None,
        "shadow": True,
        "font": "montserrat",
        "pills": False,
    },
    "red": {
        "box": (220, 38, 38, 245),
        "text": (255, 255, 255),
        "outline": None,
        "shadow": True,
        "font": "montserrat",
        "pills": False,
    },
    "outline": {
        "box": (0, 0, 0, 0),
        "text": (255, 255, 255),
        "outline": ((0, 0, 0), 8),
        "shadow": False,
        "font": "montserrat",
        "pills": False,
    },
    "outline_yellow": {
        "box": (0, 0, 0, 0),
        "text": (255, 214, 0),
        "outline": ((0, 0, 0), 8),
        "shadow": False,
        "font": "montserrat",
        "pills": False,
    },
}


def _load_text_font(font_key: str, font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path, _ = HOOK_FONTS.get(font_key, HOOK_FONTS["montserrat"])
    for candidate in (path, *_FALLBACK_TEXT_FONTS):
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, font_size)
            except OSError:
                continue
    return ImageFont.load_default()


def _load_emoji_font(target_px: int) -> tuple[ImageFont.FreeTypeFont, bool] | None:
    """Return (font, is_bitmap_strike) or None if no emoji font is available."""
    for candidate in _EMOJI_FONT_CANDIDATES:
        if not Path(candidate).exists():
            continue
        is_noto = "NotoColorEmoji" in Path(candidate).name
        if not is_noto:
            try:
                return ImageFont.truetype(candidate, target_px), False
            except OSError:
                pass
        try:
            return ImageFont.truetype(candidate, _BITMAP_EMOJI_STRIKE), True
        except OSError:
            continue
    return None


def _split_emoji_runs(text: str) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []
    pos = 0
    for m in _EMOJI_RE.finditer(text):
        if m.start() > pos:
            out.append((text[pos : m.start()], False))
        out.append((m.group(0), True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out


def _measure_run_width(
    probe: ImageDraw.ImageDraw,
    text: str,
    font: Any,
    emoji_info: tuple[Any, bool] | None,
    font_size: int,
) -> float:
    if not text:
        return 0.0
    total = 0.0
    emoji_target = max(14, int(font_size * 1.05))
    for chunk, is_emoji in _split_emoji_runs(text):
        if is_emoji and emoji_info is not None:
            efont, is_bitmap = emoji_info
            bbox = probe.textbbox((0, 0), chunk, font=efont)
            raw_w = max(1, bbox[2] - bbox[0])
            raw_h = max(1, bbox[3] - bbox[1])
            scale = (emoji_target / raw_h) if is_bitmap else 1.0
            total += raw_w * scale + 4
        else:
            total += probe.textlength(chunk, font=font)
    return total


def _draw_mixed_line(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: Any,
    emoji_info: tuple[Any, bool] | None,
    font_size: int,
    fill: tuple[int, int, int],
    outline: tuple[tuple[int, int, int], int] | None = None,
) -> None:
    x, y = xy
    emoji_target = max(14, int(font_size * 1.05))
    stroke_w = outline[1] if outline else 0
    stroke_fill = outline[0] if outline else None

    for chunk, is_emoji in _split_emoji_runs(text):
        if is_emoji and emoji_info is not None:
            efont, is_bitmap = emoji_info
            probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            bbox = probe.textbbox((0, 0), chunk, font=efont)
            ew = max(1, bbox[2] - bbox[0] + 4)
            eh = max(1, bbox[3] - bbox[1] + 4)
            tmp = Image.new("RGBA", (ew, eh), (0, 0, 0, 0))
            tdraw = ImageDraw.Draw(tmp)
            try:
                tdraw.text((2 - bbox[0], 2 - bbox[1]), chunk, font=efont, embedded_color=True)
            except TypeError:
                tdraw.text((2 - bbox[0], 2 - bbox[1]), chunk, font=efont, fill=fill)

            if is_bitmap or eh > emoji_target * 1.15:
                scale = emoji_target / max(1, eh)
                new_w = max(1, int(round(ew * scale)))
                new_h = max(1, int(round(eh * scale)))
                tmp = tmp.resize((new_w, new_h), Image.Resampling.LANCZOS)
            ey = int(round(y + (font_size - tmp.height) * 0.45))
            img.alpha_composite(tmp, (int(round(x)), max(0, ey)))
            x += tmp.width + 2
        else:
            if stroke_w > 0 and stroke_fill is not None:
                draw.text(
                    (x, y),
                    chunk,
                    font=font,
                    fill=fill,
                    stroke_width=stroke_w,
                    stroke_fill=stroke_fill,
                )
            else:
                draw.text((x, y), chunk, font=font, fill=fill)
            x += draw.textlength(chunk, font=font)


def _wrap_lines(
    text: str,
    font: Any,
    emoji_info: tuple[Any, bool] | None,
    font_size: int,
    max_text_width: int,
    max_lines: int = 3,
) -> list[str]:
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    words = text.strip().split()
    if not words:
        return [" "]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        if _measure_run_width(probe, trial, font, emoji_info, font_size) <= max_text_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
            if len(lines) >= max_lines - 1:
                # Pack remaining words into last line cleanly if short, else break anyway
                pass
    lines.append(cur)
    return lines[:max_lines]


def create_hook_image(
    text: str,
    output_image_path: Path | str,
    target_width: int = 900,
    style: str = "pill",
    font_name: str | None = None,
    font_scale: float = 1.0,
) -> tuple[Path, int, int]:
    """
    Render a hook banner to a transparent RGBA PNG and return (path, width, height).
    """
    out_path = Path(output_image_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    look = HOOK_STYLES.get(style, HOOK_STYLES["pill"])
    box_fill = look["box"]
    text_fill = look["text"]
    outline = look["outline"]
    draw_shadow = bool(look["shadow"])
    pills = bool(look.get("pills"))

    chosen_font_key = font_name or look.get("font") or "montserrat"
    _, size_factor = HOOK_FONTS.get(chosen_font_key, HOOK_FONTS["montserrat"])
    font_size = max(24, int(round(target_width * size_factor * font_scale)))
    font = _load_text_font(chosen_font_key, font_size)

    emoji_info = None
    clean_text = text.strip()
    if _EMOJI_RE.search(clean_text):
        emoji_info = _load_emoji_font(font_size)
        if emoji_info is None:
            clean_text = _EMOJI_RE.sub("", clean_text)
            clean_text = re.sub(r"[ \t]{2,}", " ", clean_text).strip()

    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    pad_x = int(font_size * 0.48)
    pad_y = int(font_size * 0.24)
    max_text_w = max(200, target_width - 2 * pad_x - 40)
    lines = _wrap_lines(clean_text or " ", font, emoji_info, font_size, max_text_w, max_lines=3)

    top_b, bot_b = probe.textbbox((0, 0), "ÁÉÍÓÚÑgjpqy!", font=font)[1::2]
    glyph_h = max(font_size, bot_b - top_b)
    widths = [int(round(_measure_run_width(probe, ln, font, emoji_info, font_size))) for ln in lines]

    if pills:
        line_h = glyph_h + 2 * pad_y
        canvas_w = max(widths) + 2 * pad_x + 40
        canvas_h = line_h * len(lines) + 40
        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        radius = int(font_size * 0.36)
        for idx, (ln, w) in enumerate(zip(lines, widths)):
            box_w = w + 2 * pad_x
            x0 = (canvas_w - box_w) // 2
            y0 = 20 + idx * line_h
            draw.rounded_rectangle([x0, y0, x0 + box_w, y0 + line_h], radius=radius, fill=box_fill)
            _draw_mixed_line(
                img,
                draw,
                (x0 + pad_x, y0 + pad_y - top_b),
                ln,
                font,
                emoji_info,
                font_size,
                fill=text_fill,
                outline=None,
            )
        img.save(out_path)
        return out_path, canvas_w, canvas_h

    line_gap = int(font_size * 0.25)
    box_pad_x = 32
    box_pad_y = 22
    block_w = max(widths) + 2 * box_pad_x
    block_h = len(lines) * glyph_h + max(0, len(lines) - 1) * line_gap + 2 * box_pad_y
    margin = 24
    canvas_w = block_w + margin * 2
    canvas_h = block_h + margin * 2

    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    if box_fill[3] > 0:
        if draw_shadow:
            shadow = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            sdraw = ImageDraw.Draw(shadow)
            sdraw.rounded_rectangle(
                [margin + 5, margin + 6, margin + block_w + 5, margin + block_h + 6],
                radius=22,
                fill=(0, 0, 0, 120),
            )
            shadow = shadow.filter(ImageFilter.GaussianBlur(8))
            img = Image.alpha_composite(img, shadow)
        bdraw = ImageDraw.Draw(img)
        bdraw.rounded_rectangle(
            [margin, margin, margin + block_w, margin + block_h],
            radius=22,
            fill=box_fill,
        )

    draw = ImageDraw.Draw(img)
    y_cursor = margin + box_pad_y - top_b
    for ln, w in zip(lines, widths):
        lx = margin + (block_w - w) // 2
        _draw_mixed_line(
            img,
            draw,
            (lx, y_cursor),
            ln,
            font,
            emoji_info,
            font_size,
            fill=text_fill,
            outline=outline,
        )
        y_cursor += glyph_h + line_gap

    img.save(out_path)
    return out_path, canvas_w, canvas_h


def _detect_face_band_y(source_video: Path, sample_time: float) -> tuple[float, float] | None:
    try:
        import cv2

        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        cap = cv2.VideoCapture(str(source_video))
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, sample_time) * 1000.0)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            return None
        fh, fw = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(45, 45))
        if len(faces) == 0:
            return None
        _, fy, _, f_h = max(faces, key=lambda b: b[2] * b[3])
        # Grow upward slightly to protect forehead/hair in vertical center crop
        top_norm = max(0.0, (fy - f_h * 0.35) / fh)
        bot_norm = min(1.0, (fy + f_h) / fh)
        return (top_norm * 1920.0, bot_norm * 1920.0)
    except Exception:
        return None


def compute_hook_y(
    layout: str,
    img_h: int,
    video_h: int = 1920,
    source_video: Path | None = None,
    sample_time: float = 0.0,
) -> int:
    """
    Choose collision-free vertical Y offset for the hook PNG overlay.
    - split layout: sits cleanly below y=698..702 facecam/gameplay seam (y=724),
      avoiding facecam (0..700) and lower-third kinetic captions (y~1360..1480).
    - center/blur: starts near y=260, nudges if OpenCV finds a face overlap,
      strictly clamped inside [220, 1280 - img_h].
    """
    if layout == "split":
        return max(706, min(724, 1200 - img_h))

    max_y = max(220, min(video_h - img_h - 640, 1280 - img_h))
    default_y = min(260, max_y)
    if source_video is None or not Path(source_video).exists():
        return default_y

    face_band = _detect_face_band_y(Path(source_video), sample_time)
    if face_band is None:
        return default_y

    f_top, f_bot = face_band
    best_y = default_y
    best_score = float("inf")
    for cand_y in range(220, max_y + 1, 20):
        overlap = max(0.0, min(cand_y + img_h, f_bot) - max(cand_y, f_top))
        score = overlap + abs(cand_y - default_y) * 0.05
        if score < best_score:
            best_score = score
            best_y = cand_y
    return best_y
