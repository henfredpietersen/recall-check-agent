"""A small tool-calling agent over US government recall data.

The agent reads a plain-English request and decides which public API to call, one call at a
time. Whoever runs it (the browser page, or the CLI) does the fetching and hands the result
back with `step()`. The agent then either asks for another call, asks the person a question,
stops with a reason, or gives a final answer.

Rules it keeps:
- Only four tools, each building a URL on an allowlisted government host. Anything else is refused.
- At most MAX_CALLS calls per request.
- It never says "no recalls" for a vehicle until it has confirmed the model exists for that
  make and year, because the recall API returns an empty list for a misspelt model too.
- A VIN lookup gives the recalls for that make, model and year. It does not say whether this
  particular car has been repaired; the answer says so.
- For products it never says "safe", only "no recall found" in the recalls it checked.

The router is plain rules, not a language model, so every decision can be tested.
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import re
import urllib.parse

from . import match, vin

MAX_CALLS = 4
MAX_LINES = 200
DEFAULT_MONTHS = 12
MAX_MONTHS = 24
HOSTS = {"www.saferproducts.gov", "vpic.nhtsa.dot.gov", "api.nhtsa.gov"}
MAKES = sorted("""acura alfa-romeo aston-martin audi bentley bmw buick cadillac chevrolet chrysler dodge ferrari fiat
ford genesis gmc harley-davidson honda hummer hyundai infiniti isuzu jaguar jeep kawasaki kia lamborghini land-rover
lexus lincoln lucid maserati mazda mclaren mercedes-benz mercury mini mitsubishi nissan polestar pontiac porsche ram
rivian rolls-royce saab saturn scion smart subaru suzuki tesla toyota volkswagen volvo yamaha""".split(),
               key=lambda m: -len(m))
ALIASES = {"vw": "volkswagen", "chevy": "chevrolet", "mercedes": "mercedes-benz", "benz": "mercedes-benz",
           "land rover": "land-rover", "range rover": "land-rover", "alfa romeo": "alfa-romeo",
           "rolls royce": "rolls-royce", "harley": "harley-davidson", "harley davidson": "harley-davidson",
           "aston martin": "aston-martin"}
INSTRUCTION = re.compile(r"^\s*(please\s+)?(check|are any|is any|scan|look|can you|could you|find)\b.*"
                         r"(catalog|catalogue|products?|list|items?|stock|below|these|recall)", re.I)


# ---------- tools: each returns a URL on an allowlisted host ----------

def _q(s) -> str:
    return urllib.parse.quote(str(s), safe="")


def tool_url(name: str, args: dict) -> str:
    if name == "cpsc_recalls":
        return ("https://www.saferproducts.gov/RestWebServices/Recall?format=json&RecallDateStart="
                + _q(args["since"]))
    if name == "vpic_models":
        return (f"https://vpic.nhtsa.dot.gov/api/vehicles/GetModelsForMakeYear/make/{_q(args['make'])}"
                f"/modelyear/{int(args['year'])}?format=json")
    if name == "vpic_decode":
        return f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{_q(args['vin'])}?format=json"
    if name == "nhtsa_recalls":
        return ("https://api.nhtsa.gov/recalls/recallsByVehicle?make=" + _q(args["make"]) + "&model="
                + _q(args["model"]) + "&modelYear=" + str(int(args["year"])))
    raise ValueError(f"unknown tool {name!r}")


def allowed(url: str) -> bool:
    u = urllib.parse.urlparse(url)
    return u.scheme == "https" and u.hostname in HOSTS


# ---------- understanding the request ----------

FILLER = {"recall", "recalls", "recalled", "any", "open", "is", "my", "a", "an", "the", "on", "for", "please", "check",
          "have", "has", "there", "are", "does", "car", "truck", "suv", "vehicle", "model", "year", "what", "about"}
MONTHS = re.compile(r"(?:in the |over the )?last\s+(\d{1,2})\s+months?", re.I)


def months_ago(today: dt.date, n: int) -> dt.date:
    y, m = divmod(today.month - 1 - n, 12)
    year, month = today.year + y, m + 1
    for day in (today.day, 30, 29, 28):
        try:
            return dt.date(year, month, day)
        except ValueError:
            continue
    raise ValueError("unreachable")

def _norm_make(text: str) -> tuple[str | None, str]:
    """Find a vehicle make in the text. Returns (make, text after the make)."""
    low = " " + re.sub(r"\s+", " ", text.lower()) + " "
    for alias, make in sorted(ALIASES.items(), key=lambda kv: -len(kv[0])):
        i = low.find(" " + alias + " ")
        if i >= 0:
            return make, low[i + len(alias) + 2:]
    for make in MAKES:
        for form in {make, make.replace("-", " ")}:
            i = low.find(" " + form + " ")
            if i >= 0:
                return make, low[i + len(form) + 2:]
    return None, ""


def understand(request: str, today: dt.date) -> dict:
    text = request.strip()
    if not text:
        return {"intent": "ask", "question": "Paste a product list, or type a vehicle (e.g. 2019 Honda Civic) or a VIN."}
    found_vin = vin.find_vin(text)
    if found_vin:
        return {"intent": "vin", "vin": found_vin}
    year_m = re.search(r"\b(19[5-9]\d|20[0-4]\d)\b", text)
    make, rest = _norm_make(text)
    lines = [ln.strip(" -•*\t") for ln in text.splitlines() if ln.strip(" -•*\t")]
    if make and year_m and len(lines) <= 2:
        year = int(year_m.group(1))
        if year > today.year + 1:
            return {"intent": "ask", "question": f"{year} is in the future. Which model year did you mean?"}
        rest = re.sub(r"\b(19|20)\d\d\b", " ", rest)
        if "range rover" in text.lower() and "range rover" not in rest:
            rest = "range rover " + rest
        model_words = []
        for w in re.findall(r"[a-z0-9][a-z0-9\-]*", rest):
            if w in FILLER:
                if model_words:
                    break
                continue
            model_words.append(w)
        model = " ".join(model_words[:4])
        if not model:
            return {"intent": "ask", "question": f"Which {make.replace('-', ' ').title()} model?"}
        return {"intent": "vehicle", "make": make, "model": model, "year": year}
    if make and not year_m and len(lines) <= 2:
        return {"intent": "ask", "question": "Which model year? NHTSA lists recalls by make, model and year."}
    months = DEFAULT_MONTHS
    m = MONTHS.search(text)
    if m:
        months = max(1, min(MAX_MONTHS, int(m.group(1))))
    items = [ln for ln in lines if not INSTRUCTION.match(ln) and not MONTHS.fullmatch(ln.strip(" .:"))
             and re.search(r"[a-zA-Z]{2,}", ln)]
    if not items:
        return {"intent": "ask", "question": "Paste the product names, one per line (brand, product and model if you have it)."}
    return {"intent": "products", "lines": items[:MAX_LINES], "truncated": len(items) > MAX_LINES,
            "months": months, "since": months_ago(today, months).isoformat()}


# ---------- the loop ----------

def _call(tool: str, args: dict, why: str) -> dict:
    url = tool_url(tool, args)
    if not allowed(url):  # defence in depth: tool_url only builds allowlisted URLs
        return {"action": "stop", "reason": f"refused to call {url}: host not on the allowlist"}
    return {"action": "call", "tool": tool, "args": args, "url": url, "why": why}


def _last(obs: list[dict], tool: str) -> dict | None:
    for o in reversed(obs):
        if o["tool"] == tool:
            return o
    return None


def iso_date(s: str | None) -> str | None:
    """NHTSA sends report dates day first ("27/06/2019"), whatever the caller's language. Checked 4 Nov 2026."""
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", (s or "").strip())
    if not m:
        return s
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return s


def _vehicle_answer(make: str, model: str, year: int, data: dict, via_vin: str | None) -> dict:
    rs = data.get("results") or []
    recalls = [{
        "campaign": r.get("NHTSACampaignNumber"),
        "date": iso_date(r.get("ReportReceivedDate")),
        "component": r.get("Component"),
        "summary": (r.get("Summary") or "")[:400],
        "consequence": (r.get("Consequence") or "")[:300],
        "remedy": (r.get("Remedy") or "")[:300],
        "do_not_drive": bool(r.get("parkIt")),
        "park_outside": bool(r.get("parkOutSide")),
    } for r in rs]
    recalls.sort(key=lambda r: (not r["do_not_drive"], not r["park_outside"], r["campaign"] or ""))
    name = f"{year} {make.replace('-', ' ').title()} {model}"
    if recalls:
        urgent = sum(r["do_not_drive"] or r["park_outside"] for r in recalls)
        text = f"NHTSA lists {len(recalls)} recall campaign{'s' if len(recalls) != 1 else ''} for the {name}."
        if urgent:
            text += f" {urgent} of them carr{'y' if urgent != 1 else 'ies'} a do-not-drive or park-outside warning."
    else:
        text = f"NHTSA lists no recall campaigns for the {name}."
    caveat = ("These are recalls for every vehicle of this make, model and year. Whether this car has already been "
              "repaired needs the VIN check on nhtsa.gov/recalls or the manufacturer's site.") if via_vin else (
              "These cover every vehicle of this make, model and year, sold in the US.")
    return {"kind": "vehicle", "vehicle": name, "vin": via_vin, "text": text, "caveat": caveat, "recalls": recalls}


def step(request: str, observations: list[dict], today: dt.date | None = None) -> dict:
    """Decide the next action. observations: [{"tool", "args", "data"} ...] from earlier calls."""
    today = today or dt.date.today()
    if len(observations) >= MAX_CALLS:
        return {"action": "stop", "reason": f"reached the limit of {MAX_CALLS} calls without an answer"}
    u = understand(request, today)
    intent = u["intent"]
    if intent == "ask":
        return {"action": "ask", "question": u["question"], "understood": u}

    if intent == "products":
        got = _last(observations, "cpsc_recalls")
        if not got:
            return _call("cpsc_recalls", {"since": u["since"]},
                         f"fetch CPSC recalls published since {u['since']} ({u['months']} months)")
        data = got["data"]
        if not isinstance(data, list):
            return {"action": "stop", "reason": "the CPSC service didn't return a list of recalls"}
        result = match.check_catalogue(u["lines"], data)
        c = result["counts"]
        text = (f"Checked {result['checked_lines']} product line{'s' if result['checked_lines'] != 1 else ''} against "
                f"{result['recalls_checked']} CPSC recalls published since {u['since']}: {c['recalled']} match a recall, "
                f"{c['check']} need a person to check, {c['none']} had no match.")
        return {"action": "done", "understood": u, "answer": {
            "kind": "products", "text": text, "truncated": u["truncated"],
            "caveat": "No match means no recall was found in these records, not that a product is safe. "
                      "CPSC covers consumer products sold in the US; cars, food and medicines are other agencies.",
            **result}}

    if intent == "vin":
        ok, why = vin.validate(u["vin"])
        if not ok:
            return {"action": "stop", "reason": why, "understood": u}
        got = _last(observations, "vpic_decode")
        if not got:
            return _call("vpic_decode", {"vin": u["vin"]}, "decode the VIN to make, model and year (NHTSA vPIC)")
        res = (got["data"].get("Results") or [{}])[0]
        make, model, year = res.get("Make"), res.get("Model"), res.get("ModelYear")
        if not (make and model and str(year).isdigit()):
            return {"action": "stop", "understood": u,
                    "reason": "NHTSA couldn't decode this VIN to a make, model and year: "
                              + (res.get("ErrorText") or "no details given")}
        rec = _last(observations, "nhtsa_recalls")
        if not rec:
            return _call("nhtsa_recalls", {"make": make, "model": model, "year": int(year)},
                         f"list recalls for the {year} {make.title()} {model}")
        return {"action": "done", "understood": u,
                "answer": _vehicle_answer(make.lower(), model, int(year), rec["data"], u["vin"])}

    # vehicle by make, model and year
    make, model, year = u["make"], u["model"], u["year"]
    models = _last(observations, "vpic_models")
    if not models:
        return _call("vpic_models", {"make": make, "year": year},
                     f"confirm NHTSA lists a {year} {make.replace('-', ' ').title()} '{model}' before trusting an empty answer")
    names = sorted({r.get("Model_Name", "") for r in models["data"].get("Results") or [] if r.get("Model_Name")})
    if not names:
        return {"action": "stop", "understood": u,
                "reason": f"NHTSA has no {year} models for '{make}'. Check the make and year."}
    canon, used = None, model
    parts = model.split()
    for k in range(len(parts), 0, -1):  # "civic type r" -> "civic type" -> "civic"
        cand = " ".join(parts[:k])
        sq = match.squash(cand)
        canon = next((n for n in names if n.lower() == cand), None) or \
            next((n for n in names if match.squash(n) == sq), None)
        if canon:
            used = cand
            break
    if not canon:
        close = difflib.get_close_matches(model, [n.lower() for n in names], n=4, cutoff=0.5)
        pick = [n for n in names if n.lower() in close] or [n for n in names if n.lower().startswith(model[:3])][:4]
        q = f"NHTSA doesn't list a {year} {make.replace('-', ' ').title()} '{model}'."
        q += f" Did you mean {', '.join(pick)}?" if pick else " Check the model name."
        return {"action": "ask", "question": q, "understood": u,
                "note": "Not answered as 'no recalls': the recall API returns nothing for unknown models too."}
    rec = _last(observations, "nhtsa_recalls")
    if not rec:
        return _call("nhtsa_recalls", {"make": make, "model": canon, "year": year},
                     f"list recalls for the {year} {make.replace('-', ' ').title()} {canon}")
    ans = _vehicle_answer(make, canon, year, rec["data"], None)
    if used != model:
        ans["text"] += f" (NHTSA lists it as '{canon}', so that's what was checked, not '{model}'.)"
    return {"action": "done", "understood": u, "answer": ans}


def step_json(request: str, observations_json: str, today_iso: str | None = None) -> str:
    """The page's entry point: JSON in, JSON out."""
    today = dt.date.fromisoformat(today_iso) if today_iso else None
    return json.dumps(step(request, json.loads(observations_json), today))
