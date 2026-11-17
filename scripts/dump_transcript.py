import json
from pathlib import Path

t = json.loads(Path(r"D:\Freelance Projects\video-engine\output\expedia-ishowspeed\.work\transcript.json").read_text(encoding="utf-8"))
for s in t["segments"]:
    print(f"{s['start']:6.2f} -> {s['end']:6.2f} :: {s['text']}")
