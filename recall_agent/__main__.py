"""Run the agent from the command line, with real network calls.

    python -m recall_agent "2003 Honda Accord"
    python -m recall_agent "Check VIN 1HGCM82633A004352"
    python -m recall_agent --file products.txt
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

from . import agent


def fetch(url: str):
    if not agent.allowed(url):
        raise SystemExit(f"Refusing {url}: host not on the allowlist")
    req = urllib.request.Request(url, headers={"User-Agent": "recall-check-agent (github.com/henfredpietersen)"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 (allowlisted https hosts only)
        return json.loads(r.read())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Check products or vehicles against US recall data.")
    p.add_argument("request", nargs="?", default="")
    p.add_argument("--file", help="read the request (e.g. a product list) from a file")
    a = p.parse_args(argv)
    request = open(a.file, encoding="utf-8").read() if a.file else a.request
    obs = []
    while True:
        s = agent.step(request, obs)
        if s["action"] == "call":
            print(f"-> {s['tool']}: {s['why']}", file=sys.stderr)
            obs.append({"tool": s["tool"], "args": s["args"], "data": fetch(s["url"])})
            continue
        if s["action"] == "done":
            ans = s["answer"]
            print(ans["text"])
            for r in ans.get("results", []):
                if r["verdict"] != "none":
                    print(f"  [{r['verdict']}] {r['line']} -> {r['recall']['title']} ({', '.join(r['reasons'])})")
            for r in ans.get("recalls", []):
                flag = " DO NOT DRIVE" if r["do_not_drive"] else " PARK OUTSIDE" if r["park_outside"] else ""
                print(f"  {r['campaign']} {r['component']}{flag}")
            print(ans["caveat"])
        else:
            print(s.get("question") or s.get("reason"))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
