from pathlib import Path
import re
import subprocess
import tempfile
import os

out = Path(os.environ["TEMP"]) / "aero-dom.html"
chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
subprocess.run(
    [chrome, "--headless=new", "--disable-gpu", "--virtual-time-budget=25000",
     "--dump-dom", "http://127.0.0.1:8765/index.html"],
    stdout=open(out, "w", encoding="utf-8", errors="ignore"),
    stderr=subprocess.DEVNULL,
    timeout=60,
)
t = out.read_text(encoding="utf-8", errors="ignore")
print("dom chars", len(t))
for name in ("flow-readout", "ml-readout", "aero-error", "loading"):
    m = re.search(rf'id="{name}"([^>]*)>([^<]*)', t)
    print(name, m.group(0)[:200] if m else None)
print("streams live" in t, "aero error" in t.lower(), "cambered" in t)
