#!/usr/bin/env python3
"""Render 4 true viral GTA 6 first-reaction IShowSpeed clips with locked A/V sync."""

import json
from pathlib import Path
from clip_engine import (
    build_kinetic_ass,
    compute_rms_per_second,
    find_peak_offset,
    prepend_flash_hook,
    render_portrait_clip,
)

BASE = Path(__file__).resolve().parent.parent / "output" / "gta6-ishowspeed"
WORK = BASE / ".work"
SOURCE = WORK / "stream_boot_11_25m.mp4"
TRANSCRIPT = json.loads((WORK / "boot_11_25m_transcript.json").read_text(encoding="utf-8"))
ENERGIES = json.loads((WORK / "boot_11_25m_energy.json").read_text(encoding="utf-8"))

CAM_BOX = "0.0,0.425,0.205,0.225"

CLIPS = [
    {
        "name": "gta6_viral_01_first_reaction.mp4",
        "start": 4.50,
        "end": 39.50,
        "flash": False,  # Already starts at 0.0s with Speed screaming at the GTA VI logo!
        "hook": "SPEED'S FIRST REACTION BOOTING UP GTA 6!",
        "title": "IShowSpeed's LIVE First Reaction Booting Up GTA 6 For the First Time! 🤯",
        "caption": "IShowSpeed losing his mind seeing GTA 6 boot up for the very first time! 😭🔥 #IShowSpeed #GTA6 #GTAVI #Gaming #Viral",
        "pin": "Waited 13 years for this exact moment 😭🔥",
    },
    {
        "name": "gta6_viral_02_first_sight_lucia.mp4",
        "start": 376.00,
        "end": 412.50,
        "flash": True,
        "hook": "SPEED LOST HIS MIND SEEING LUCIA IN GTA 6",
        "title": "IShowSpeed's Insane Reaction Seeing Lucia For the First Time in GTA 6 💀",
        "caption": "Bro could not stay calm for 5 seconds seeing Lucia in GTA 6 💀😂 #IShowSpeed #GTA6 #Lucia #GTAVI #Gaming",
        "pin": "Speed within 30 seconds of seeing Lucia 😭💀",
    },
    {
        "name": "gta6_viral_03_graphics_mid_chase.mp4",
        "start": 689.50,
        "end": 727.00,
        "flash": True,
        "hook": "SPEED REACTS TO GTA 6 GRAPHICS MID-ROBBERY!",
        "title": "IShowSpeed Screams Over GTA 6 Graphics During First Police Chase! 🚨",
        "caption": "Speed literally stopped mid-robbery escape in GTA 6 just to scream at the graphics 🤯🚨 #IShowSpeed #GTA6 #GTAVI #Gaming",
        "pin": "Those GTA 6 graphics mid-chase actually look insane 🤯🔥",
    },
    {
        "name": "gta6_viral_04_lucia_baby_twist.mp4",
        "start": 778.50,
        "end": 811.80,
        "flash": True,
        "hook": "WAIT LUCIA HAS A BABY?! CRAZIEST GTA 6 TWIST",
        "title": "WAIT LUCIA HAS A BABY?! IShowSpeed Reacts to Craziest GTA 6 Twist! 😱",
        "caption": "Wait... Lucia left what behind during the robbery?! Craziest GTA 6 twist! 😱👶 #IShowSpeed #GTA6 #Lucia #GTAVI #Gaming",
        "pin": "Calling CPS mid-heist is wild 😭💀",
    },
]


def fix_words(words: list[dict]) -> list[dict]:
    fixed = []
    i = 0
    while i < len(words):
        w = words[i].copy()
        wl = w["word"].lower().strip(".,?!")
        if i + 1 < len(words) and wl == "lucy" and words[i + 1]["word"].lower().strip(".,?!") == "a":
            fixed.append({"word": "Lucia", "start": w["start"], "end": words[i + 1]["end"]})
            i += 2
            continue
        if wl in ("lucy", "lucia"):
            w["word"] = "Lucia" + ("?" if "?" in w["word"] else ("," if "," in w["word"] else ""))
        elif wl == "nookie":
            w["word"] = "dookie"
        fixed.append(w)
        i += 1
    return fixed


all_words = [w for seg in TRANSCRIPT["segments"] for w in seg["words"]]
manifest = []

for idx, cfg in enumerate(CLIPS, start=1):
    clip_words = [w for w in all_words if w["start"] >= cfg["start"] and w["end"] <= cfg["end"]]
    clip_words = fix_words(clip_words)
    peak_off = find_peak_offset(ENERGIES, cfg["start"], cfg["end"])
    rel_dur = round(cfg["end"] - cfg["start"], 3)

    if cfg["flash"]:
        kept_intervals, retimed_words = prepend_flash_hook(
            [(0.0, rel_dur)], clip_words, cfg["start"], cfg["end"], peak_off, flash_dur=1.7
        )
        is_rel = True
    else:
        kept_intervals = None
        retimed_words = clip_words
        is_rel = False

    ass_path = WORK / f"gta6_viral_{idx:02d}.ass"
    out_mp4 = BASE / cfg["name"]
    build_kinetic_ass(
        retimed_words,
        cfg["start"],
        ass_path,
        hook_title=cfg["hook"],
        is_relative=is_rel,
        hook_margin_v=650,
    )
    print(f"Rendering {idx}/4: {cfg['name']} (flash={cfg['flash']}, peak={peak_off}s)...")
    render_portrait_clip(
        SOURCE,
        cfg["start"],
        cfg["end"],
        ass_path,
        out_mp4,
        layout="split",
        cam_pos=CAM_BOX,
        kept_intervals=kept_intervals,
        use_sfx=True,
        peak_offset=peak_off,
    )
    manifest.append(
        {
            "clip": cfg["name"],
            "path": str(out_mp4),
            "hook": cfg["hook"],
            "title": cfg["title"],
            "caption": cfg["caption"],
            "pin": cfg["pin"],
        }
    )

(BASE / "manifest_gta6_viral.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print("All 4 true viral GTA 6 clips rendered!")
