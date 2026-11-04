"""The published page embeds the current code, and only calls allowlisted hosts."""

import importlib.util
import re
from pathlib import Path

from recall_agent import agent

ROOT = Path(__file__).resolve().parents[1]


def test_published_page_embeds_current_code():
    spec = importlib.util.spec_from_file_location("build", ROOT / "web" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (ROOT / "docs" / "demo.js").read_text(encoding="utf-8") == mod.build(), \
        "docs/demo.js is stale: run python web/build.py"


def test_page_allowlist_matches_the_agent():
    js = (ROOT / "web" / "page.js").read_text(encoding="utf-8")
    hosts = set(re.search(r"var HOSTS = \[(.*?)\];", js).group(1).replace('"', "").replace(" ", "").split(","))
    assert hosts == agent.HOSTS
