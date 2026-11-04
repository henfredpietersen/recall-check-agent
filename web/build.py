"""Build the live demo page.

    python web/build.py

Writes docs/demo.js (what the case-study page loads) and docs/demo.html (open it in a browser).
The page embeds the recall_agent package byte for byte and runs it with Pyodide. The visitor's
browser makes the API calls the agent asks for. CI rebuilds the page and fails if the committed
copy differs.

Embed on any page:
  <div id="ov-recall-agent"></div>
  <script defer src="https://cdn.jsdelivr.net/gh/henfredpietersen/recall-check-agent@<commit>/docs/demo.js"></script>
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMBED = {f"/home/pyodide/recall_agent/{n}": f"recall_agent/{n}"
         for n in ("__init__.py", "vin.py", "match.py", "agent.py")}

STANDALONE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Recall check agent</title>
<style>html,body{margin:0;background:#05070d}</style></head>
<body>
<div id="ov-recall-agent"></div>
<script src="demo.js"></script>
</body></html>
"""


def build() -> str:
    files = {dest: (ROOT / src).read_text(encoding="utf-8") for dest, src in EMBED.items()}
    template = (ROOT / "web" / "page.js").read_text(encoding="utf-8")
    assert template.count("__FILES__") == 1
    return template.replace("__FILES__", json.dumps(files).replace("</", "<\\/"))


def main() -> int:
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    script = build()
    (docs / "demo.js").write_text(script, encoding="utf-8")
    (docs / "demo.html").write_text(STANDALONE, encoding="utf-8")
    print(f"Wrote docs/demo.js ({len(script):,} bytes) and docs/demo.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
