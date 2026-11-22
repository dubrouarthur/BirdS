"""Prepare assets for promo.html: converts the real Playwright captures to JPEG
(no retouching, only format/quality) and writes data.js with the frame timings.

Usage: .venv/bin/python docs/marketing/video2/prep.py
"""

import json
import os
import shutil

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = "/tmp/claude-0/-home-user-BirdS/27eb98ec-b9ba-5cf1-a125-8008c93c0d55/scratchpad/video2"
CAP = os.path.join(SCR, "cap")
OUT = os.path.join(SCR, "assets")
SCENES = {"mail": "scene2", "deck": "scene3_alt3", "invoice": "scene4", "receipt": "scene5"}

os.makedirs(OUT, exist_ok=True)
data = {}
for key, d in SCENES.items():
    timing = json.load(open(os.path.join(CAP, d, "timing.json")))
    os.makedirs(os.path.join(OUT, key), exist_ok=True)
    frames = []
    for f in timing["frames"]:
        src = os.path.join(CAP, d, "%04d.png" % f["i"])
        dst = os.path.join(OUT, key, "%04d.jpg" % f["i"])
        if not os.path.exists(dst):
            Image.open(src).convert("RGB").save(dst, quality=93, subsampling=0)
        frames.append([f["i"], round(f["t"], 3)])
    data[key] = {"tSend": timing.get("tSend"), "tDone": timing.get("tDone"), "frames": frames}

os.makedirs(os.path.join(OUT, "slides"), exist_ok=True)
for n in range(1, 7):
    shutil.copy(os.path.join(CAP, "scene3_alt3", "slides", "slide%d.png" % n), os.path.join(OUT, "slides"))
shutil.copy(os.path.join(SCR, "invoice.png"), OUT)
shutil.copy(os.path.join(HERE, "..", "..", "..", "birds", "web", "static", "brand", "mark.svg"), OUT)

with open(os.path.join(HERE, "data.js"), "w") as fh:
    fh.write("window.CAPTURES = " + json.dumps(data) + ";\n")
print("ok", {k: len(v["frames"]) for k, v in data.items()})
