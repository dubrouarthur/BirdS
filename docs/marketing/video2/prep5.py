"""v5: prepare the real Playwright captures (capture5.js) for promo.html.

Converts each PNG frame to JPEG (format/quality only, no retouching) and writes data5.js with the
capture clock of every frame.  Usage: .venv/bin/python docs/marketing/video2/prep5.py
"""

import json
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = "/tmp/claude-0/-home-user-BirdS/27eb98ec-b9ba-5cf1-a125-8008c93c0d55/scratchpad/video5"
CAP = os.path.join(SCR, "cap")
OUT = os.path.join(SCR, "assets")
SCENES = {"mail": "mail", "deck": "deck", "chart": "chart", "rich": "rich_b"}

data = {}
for key, d in SCENES.items():
    timing = json.load(open(os.path.join(CAP, d, "timing.json")))
    os.makedirs(os.path.join(OUT, key), exist_ok=True)
    frames = []
    for f in timing["frames"]:
        src = os.path.join(CAP, d, "%04d.png" % f["i"])
        dst = os.path.join(OUT, key, "%04d.jpg" % f["i"])
        im = Image.open(src).convert("RGB")
        if not os.path.exists(dst):
            im.save(dst, quality=94, subsampling=0)
        # colour of the app's top edge: the phone's status strip above the capture uses it
        top = "#%02x%02x%02x" % im.getpixel((5, 3))
        frames.append([f["i"], round(f["t"], 3), top])
    marks = {k: v for k, v in timing.items() if k not in ("frames",)}
    data[key] = {"marks": marks, "frames": frames}

with open(os.path.join(HERE, "data5.js"), "w") as fh:
    fh.write("window.CAPTURES = " + json.dumps(data, ensure_ascii=False) + ";\n")
print("ok", {k: len(v["frames"]) for k, v in data.items()})
