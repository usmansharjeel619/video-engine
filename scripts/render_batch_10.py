#!/usr/bin/env python3
"""Render 10 high-hook viral Expedia x IShowSpeed portrait clips with official logo & accurate captions."""

import json
from pathlib import Path
from clip_engine import build_kinetic_ass, render_portrait_clip

BASE = Path(r"D:\Freelance Projects\video-engine\output\expedia-ishowspeed")
WORK = BASE / ".work"
SOURCE = WORK / "source_segment.mp4"
LOGO = WORK / "expedia_logos" / "Expedia_Logo-RegistrationMark-Horizontal-Inverted.png"
TRANSCRIPT = json.loads((WORK / "transcript.json").read_text(encoding="utf-8"))

BATCH = [
    {
        "name": "batch2_clip_01_hudson_japan_reveal.mp4",
        "start": 134.00,
        "end": 172.00,
        "hook": "ISHOWSPEED SURPRISES FAN WITH FREE TRIP TO JAPAN!",
        "title": "IShowSpeed & Expedia Surprise Fan With Free Trip to Japan! 🇯🇵✈️",
        "caption": "Expedia & IShowSpeed surprise Hudson with a dream trip to Japan! 🇯🇵✈️ #IShowSpeed #Expedia #Japan #Travel",
        "pin": "W Speed & Expedia for changing his life 🙏🇯🇵 Where would you fly?",
    },
    {
        "name": "batch2_clip_02_hudson_japan_story.mp4",
        "start": 104.88,
        "end": 133.10,
        "hook": "WHY THIS FAN DESERVES A FREE EXPEDIA TRIP TO JAPAN ❤️",
        "title": "Why This Fan Wanted Expedia to Send Him to Japan ❤️🇯🇵",
        "caption": "Hudson shares the wholesome story behind his Expedia dream trip to Japan! #IShowSpeed #Expedia #Japan #Travel",
        "pin": "Wholesome reason to visit Japan ❤️🇯🇵",
    },
    {
        "name": "batch2_clip_03_hudson_expedia_intro.mp4",
        "start": 78.72,
        "end": 104.00,
        "hook": "ISHOWSPEED & EXPEDIA ARE SENDING FANS AROUND THE WORLD!",
        "title": "IShowSpeed & Expedia Give Fans the Ultimate Travel Gift 🌍✈️",
        "caption": "Expedia teamed up with IShowSpeed to send lucky fans on dream trips like Japan! #IShowSpeed #Expedia #Travel #Japan",
        "pin": "If Expedia paid for your flight anywhere, where are you going? ✈️👇",
    },
    {
        "name": "batch2_clip_04_worldcup_fullcircle.mp4",
        "start": 182.62,
        "end": 221.64,
        "hook": "FROM WATCHING SPEED AT THE WORLD CUP TO A FREE JAPAN TRIP!",
        "title": "Full Circle Moment: Expedia Sends IShowSpeed Fan to Japan! 🇯🇵",
        "caption": "From seeing IShowSpeed at the World Cup to winning an Expedia trip to Japan! #IShowSpeed #Expedia #Japan #Travel",
        "pin": "Full circle moments hit different 🔥🇯🇵",
    },
    {
        "name": "batch2_clip_05_never_left_country.mp4",
        "start": 261.62,
        "end": 300.24,
        "hook": "HE'S NEVER LEFT THE COUNTRY... UNTIL EXPEDIA & SPEED CALLED!",
        "title": "He's Never Left the Country—Expedia & IShowSpeed Ask His Dream Trip!",
        "caption": "Anthony has never left the country—now Expedia & IShowSpeed ask where he wants to go: Hong Kong! 🇭🇰 #IShowSpeed #Expedia #HongKong #Travel",
        "pin": "First time ever leaving the country to Hong Kong 🇭🇰🙏",
    },
    {
        "name": "batch2_clip_06_10k_shock_reaction.mp4",
        "start": 310.22,
        "end": 338.12,
        "hook": "WAIT FOR HIS REACTION TO WINNING $10,000 FROM EXPEDIA! 🤯",
        "title": "Fan's Reaction to Winning $10,000 From Expedia for Hong Kong! 🤯",
        "caption": "Wait for his reaction when Expedia & IShowSpeed give him $10,000 for Hong Kong! 🇭🇰💸 #IShowSpeed #Expedia #HongKong #Travel",
        "pin": "His jaw literally dropped 😭💸🇭🇰",
    },
    {
        "name": "batch2_clip_07_college_student_call.mp4",
        "start": 46.98,
        "end": 87.44,
        "hook": "COLLEGE STUDENT GETS LIFE-CHANGING CALL FROM ISHOWSPEED!",
        "title": "College Baseball Player Gets Surprise Call From IShowSpeed & Expedia!",
        "caption": "College student Hudson gets a surprise call from IShowSpeed & Expedia about traveling to Japan! 🇯🇵 #IShowSpeed #Expedia #Japan #Travel",
        "pin": "Imagine getting a FaceTime like this mid-day 😭🔥",
    },
    {
        "name": "batch2_clip_08_how_winners_picked.mp4",
        "start": 172.44,
        "end": 198.80,
        "hook": "HOW ISHOWSPEED & EXPEDIA PICKED THE WINNERS FOR JAPAN!",
        "title": "How IShowSpeed & Expedia Chose Fans for Dream Trips to Japan ✈️",
        "caption": "IShowSpeed explains how he & Expedia read thousands of fan stories and sent Hudson to Japan! 🇯🇵 #IShowSpeed #Expedia #Japan #Travel",
        "pin": "W Expedia for actually reading the fan stories 🙏✈️",
    },
    {
        "name": "batch2_clip_09_cantonese_check.mp4",
        "start": 339.20,
        "end": 364.00,
        "hook": "SPEED THOUGHT HE WAS LYING ABOUT SPEAKING CANTONESE 😂",
        "title": "IShowSpeed Checks If $10K Expedia Winner Speaks Cantonese for Hong Kong!",
        "caption": "Speed thought he was capping about speaking Cantonese before winning $10,000 from Expedia for Hong Kong! 🇭🇰😂 #IShowSpeed #Expedia #HongKong #Travel",
        "pin": "Bro passed the Cantonese test on the spot 💀🇭🇰",
    },
    {
        "name": "batch2_clip_10_full_hongkong_arc.mp4",
        "start": 284.60,
        "end": 329.00,
        "hook": "NEVER LEFT THE USA -> EXPEDIA GIVES HIM $10,000 FOR HONG KONG!",
        "title": "Never Left the Country -> Expedia Gives Him $10,000 for Hong Kong!",
        "caption": "Never been out of the country in his life—Expedia & IShowSpeed just gave him $10,000 to visit Hong Kong! 🇭🇰✈️ #IShowSpeed #Expedia #HongKong #Travel",
        "pin": "Best stream moment of the year 🇭🇰✈️🔥",
    },
]


def fix_words(words: list[dict]) -> list[dict]:
    fixed = []
    i = 0
    while i < len(words):
        w = words[i].copy()
        wl = w["word"].lower().strip(".,?!")
        if i + 1 < len(words):
            nl = words[i + 1]["word"].lower().strip(".,?!")
            if wl == "home" and nl == "call":
                punct = "?" if "?" in words[i + 1]["word"] else ("," if "," in words[i + 1]["word"] else "")
                fixed.append({"word": f"Hong Kong{punct}", "start": w["start"], "end": words[i + 1]["end"]})
                i += 2
                continue
        if wl == "dramas":
            w["word"] = w["word"].replace("dramas", "dreams").replace("Dramas", "Dreams")
        elif wl == "steve":
            w["word"] = w["word"].replace("Steve", "Speed").replace("steve", "Speed")
        elif wl == "delby":
            w["word"] = "W"
        fixed.append(w)
        i += 1
    return fixed


all_words = [w for seg in TRANSCRIPT["segments"] for w in seg["words"]]
manifest = []

for idx, cfg in enumerate(BATCH, start=1):
    clip_words = [w for w in all_words if w["start"] >= cfg["start"] and w["end"] <= cfg["end"]]
    clip_words = fix_words(clip_words)
    ass_path = WORK / f"batch2_{idx:02d}.ass"
    out_mp4 = BASE / cfg["name"]
    build_kinetic_ass(clip_words, cfg["start"], ass_path, hook_title=cfg["hook"])
    if out_mp4.exists() and idx <= 6:
        print(f"Skipping {idx}/10 (already rendered): {cfg['name']}")
    else:
        print(f"Rendering {idx}/10: {cfg['name']}...")
        render_portrait_clip(
            SOURCE,
            cfg["start"],
            cfg["end"],
            ass_path,
            out_mp4,
            layout="blur",
            logo_path=LOGO if LOGO.exists() else None,
        )
    manifest.append(
        {
            "clip": cfg["name"],
            "path": str(out_mp4),
            "duration": round(cfg["end"] - cfg["start"], 2),
            "hook": cfg["hook"],
            "title": cfg["title"],
            "caption": cfg["caption"],
            "pin": cfg["pin"],
        }
    )

(BASE / "manifest_batch2.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print("Batch 2 (10 viral clips) complete!")
