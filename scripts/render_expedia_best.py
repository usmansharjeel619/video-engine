#!/usr/bin/env python3
"""Render polished 9:16 blur-layout Expedia x IShowSpeed clips with accurate destinations & hooks."""

import json
from pathlib import Path
from clip_engine import build_kinetic_ass, render_portrait_clip

BASE = Path(r"D:\Freelance Projects\video-engine\output\expedia-ishowspeed")
WORK = BASE / ".work"
SOURCE = WORK / "source_segment.mp4"
TRANSCRIPT = json.loads((WORK / "transcript.json").read_text(encoding="utf-8"))

CLIPS = [
    {
        "name": "expedia_clip_01_hong_kong_10k.mp4",
        "start": 300.9,
        "end": 343.22,
        "hook": "EXPEDIA GIVES FAN $10,000 TO HONG KONG!",
        "caption": "Expedia & IShowSpeed surprise Anthony with $10,000 to travel to Hong Kong! #IShowSpeed #Expedia #HongKong #Travel",
    },
    {
        "name": "expedia_clip_02_cantonese_hong_kong.mp4",
        "start": 346.0,
        "end": 369.4,
        "hook": "HE ACTUALLY SPEAKS CANTONESE! ($10K EXPEDIA TRIP)",
        "caption": "Anthony speaks Cantonese and wins $10,000 from Expedia to visit Hong Kong! #IShowSpeed #Expedia #HongKong #Travel",
    },
    {
        "name": "expedia_clip_03_japan_trip.mp4",
        "start": 211.4,
        "end": 251.22,
        "hook": "EXPEDIA & ISHOWSPEED SEND FAN TO JAPAN!",
        "caption": "Full circle moment: Expedia & IShowSpeed are sending this fan to Japan! #IShowSpeed #Expedia #Japan #Travel",
    },
]

REPLACEMENTS = [
    ("home call", "Hong Kong"),
    ("home call?", "Hong Kong?"),
    ("home call,", "Hong Kong,"),
    ("steve?", "Speed?"),
    ("steve", "Speed"),
]


def fix_words(words: list[dict]) -> list[dict]:
    fixed = []
    i = 0
    while i < len(words):
        w = words[i].copy()
        if i + 1 < len(words) and w["word"].lower().strip(".,?!") == "home" and words[i + 1]["word"].lower().strip(".,?!") == "call":
            punct = "?" if "?" in words[i + 1]["word"] else ("," if "," in words[i + 1]["word"] else "")
            fixed.append({"word": f"Hong Kong{punct}", "start": w["start"], "end": words[i + 1]["end"]})
            i += 2
            continue
        if w["word"].lower().strip(".,?!") == "steve":
            w["word"] = w["word"].replace("Steve", "Speed").replace("steve", "Speed")
        fixed.append(w)
        i += 1
    return fixed


all_words = [w for seg in TRANSCRIPT["segments"] for w in seg["words"]]
manifest = []

for idx, cfg in enumerate(CLIPS, start=1):
    clip_words = [w for w in all_words if w["start"] >= cfg["start"] and w["end"] <= cfg["end"]]
    clip_words = fix_words(clip_words)
    ass_path = WORK / f"polished_{idx:02d}.ass"
    out_mp4 = BASE / cfg["name"]
    build_kinetic_ass(clip_words, cfg["start"], ass_path, hook_title=cfg["hook"])
    print(f"Rendering {cfg['name']}...")
    render_portrait_clip(SOURCE, cfg["start"], cfg["end"], ass_path, out_mp4, layout="blur")
    manifest.append(
        {
            "clip": cfg["name"],
            "path": str(out_mp4),
            "sourceStart": cfg["start"],
            "sourceEnd": cfg["end"],
            "duration": round(cfg["end"] - cfg["start"], 2),
            "transcript": cfg["caption"],
        }
    )

(BASE / "manifest_polished.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print("All 3 polished clips rendered!")
