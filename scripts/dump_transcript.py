import json
import sys
from pathlib import Path

p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\Freelance Projects\video-engine\output\expedia-ishowspeed\.work\transcript.json")
t = json.loads(p.read_text(encoding="utf-8"))
for s in t["segments"]:
    print(f"{s['start']:6.2f} -> {s['end']:6.2f} :: {s['text']}")
