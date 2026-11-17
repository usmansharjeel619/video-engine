#!/usr/bin/env python3
"""Edge TTS synthesis helper with optional word-boundary timing export."""

import argparse
import asyncio
import json
from pathlib import Path

import edge_tts


async def synthesize(
    text: str,
    output_path: Path,
    voice: str,
    rate: str,
    pitch: str,
    timings_path: Path | None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
    submaker = edge_tts.SubMaker()
    word_timings: list[dict[str, object]] = []

    with output_path.open("wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                submaker.feed(chunk)
                if chunk["type"] == "WordBoundary":
                    offset_s = chunk["offset"] / 10_000_000
                    duration_s = chunk["duration"] / 10_000_000
                    word_timings.append(
                        {
                            "text": chunk["text"],
                            "start": round(offset_s, 3),
                            "end": round(offset_s + duration_s, 3),
                        }
                    )

    if timings_path is not None:
        timings_path.parent.mkdir(parents=True, exist_ok=True)
        if timings_path.suffix.lower() == ".srt":
            timings_path.write_text(submaker.get_srt(), encoding="utf-8")
        else:
            timings_path.write_text(
                json.dumps({"voice": voice, "words": word_timings}, indent=2),
                encoding="utf-8",
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize speech with Edge TTS.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="Text to synthesize.")
    source.add_argument("--text-file", type=Path, help="Path to a UTF-8 text file.")
    parser.add_argument("--output", "-o", type=Path, required=True, help="Output audio path (.mp3).")
    parser.add_argument("--voice", default="en-US-AndrewMultilingualNeural", help="Edge TTS voice name.")
    parser.add_argument("--rate", default="+0%", help="Speech rate adjustment (e.g. +10%%, -5%%).")
    parser.add_argument("--pitch", default="+0Hz", help="Pitch adjustment (e.g. +2Hz, -2Hz).")
    parser.add_argument("--timings", type=Path, default=None, help="Optional .json or .srt output for word timings.")
    args = parser.parse_args()

    text = args.text if args.text is not None else args.text_file.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit("Error: input text is empty.")

    asyncio.run(synthesize(text, args.output, args.voice, args.rate, args.pitch, args.timings))
    print(f"TTS saved to {args.output}")


if __name__ == "__main__":
    main()
