#!/usr/bin/env python3
"""Whisper transcription helper powered by faster-whisper."""

import argparse
import json
from pathlib import Path

from faster_whisper import WhisperModel


def format_srt_timestamp(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe audio/video with faster-whisper.")
    parser.add_argument("--input", "-i", type=Path, required=True, help="Input audio or video file.")
    parser.add_argument("--model", default="base", help="Whisper model size (tiny, base, small, medium, large-v3).")
    parser.add_argument("--language", default=None, help="Optional ISO language code (e.g. en).")
    parser.add_argument("--device", default="auto", help="Device: auto, cpu, cuda.")
    parser.add_argument("--compute-type", default="int8", help="Compute type: int8, float16, float32.")
    parser.add_argument("--output-json", type=Path, default=None, help="Write transcript + word timestamps as JSON.")
    parser.add_argument("--output-srt", type=Path, default=None, help="Write subtitles as SRT.")
    args = parser.parse_args()

    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    segments_iter, info = model.transcribe(
        str(args.input),
        language=args.language,
        word_timestamps=True,
    )

    segments: list[dict[str, object]] = []
    srt_lines: list[str] = []

    for idx, seg in enumerate(segments_iter, start=1):
        words = [
            {
                "word": w.word.strip(),
                "start": round(w.start, 3),
                "end": round(w.end, 3),
                "probability": round(w.probability, 3),
            }
            for w in (seg.words or [])
        ]
        segments.append(
            {
                "id": idx,
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
                "words": words,
            }
        )
        srt_lines.append(
            f"{idx}\n{format_srt_timestamp(seg.start)} --> {format_srt_timestamp(seg.end)}\n{seg.text.strip()}\n"
        )

    payload = {
        "language": info.language,
        "languageProbability": round(info.language_probability, 3),
        "duration": round(info.duration, 3),
        "segments": segments,
    }

    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if args.output_srt is not None:
        args.output_srt.parent.mkdir(parents=True, exist_ok=True)
        args.output_srt.write_text("\n".join(srt_lines), encoding="utf-8")

    if args.output_json is None and args.output_srt is None:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Transcribed {args.input} ({info.language}, {round(info.duration, 2)}s)")


if __name__ == "__main__":
    main()
