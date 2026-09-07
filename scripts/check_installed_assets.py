"""Run with python -I after installation to avoid importing the source checkout."""
import re
from importlib.resources import files

root = files("draft_assistant") / "web/static"
html = (root / "index.html").read_text(encoding="utf-8")
assets = re.findall(r'(?:src|href)="([^"]+)"', html)
missing = [asset for asset in assets if not (root / asset).is_file()]
if not assets or missing:
    raise SystemExit(f"Installed web assets missing: {missing or 'no asset references'}")
print(f"Installed web assets: PASS ({len(assets)} files)")
