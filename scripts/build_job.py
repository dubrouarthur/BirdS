"""Build the self-contained job script: jobs/bird_job.py with the `birds` package embedded.

python scripts/build_job.py            # writes dist/bird_job.py
"""

import base64
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted((ROOT / "birds").rglob("*.py")):
        z.write(f, f.relative_to(ROOT))
src = (ROOT / "jobs" / "bird_job.py").read_text(encoding="utf-8")
marker = 'PAYLOAD = ""'
assert src.count(marker) == 1
out = ROOT / "dist" / "bird_job.py"
out.parent.mkdir(exist_ok=True)
out.write_text(src.replace(marker, f'PAYLOAD = "{base64.b64encode(buf.getvalue()).decode()}"'), encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size // 1024} KiB)")
