"""Match a product list against CPSC recall records.

Each catalogue line gets one of three verdicts:
- "recalled":  the UPC matches, or the brand and a model code both match.
- "check":     the brand matches and the product words overlap, or a long model code matches
               without the brand. A person should look.
- "none":      nothing matched in the recalls checked. That is not the same as "safe".

Matching is plain text rules, so every verdict comes with the exact words that matched.
"""

from __future__ import annotations

import re

WORD = re.compile(r"[a-z0-9]+")
CODE = re.compile(r"\b(?=[a-z0-9\-./]*\d)(?=[a-z0-9\-./]*[a-z])[a-z0-9][a-z0-9\-./]{2,}[a-z0-9]\b")
UPC = re.compile(r"\b\d{12,14}\b")
COMPANY_NOISE = {"inc", "llc", "ltd", "co", "corp", "corporation", "company", "of", "the", "usa", "us", "and",
                 "trading", "brand", "brands", "international", "group", "limited", "store", "shop", "official",
                 "products", "industries", "technology", "technologies"}
GENERIC = {"recall", "recalls", "recalled", "due", "risk", "serious", "injury", "death", "hazard", "hazards",
           "fire", "burn", "fall", "violate", "violates", "mandatory", "standard", "standards", "sold", "amazon",
           "exclusively", "with", "and", "the", "for", "of", "to", "in", "on", "or", "a", "an", "from", "by",
           "model", "models", "cup", "inch", "pack", "set", "sets", "new", "black", "white", "kids", "children",
           "childrens", "brand", "units", "about", "warning", "warnings", "federal", "ban", "banned", "products",
           "product", "temu", "walmart", "shein", "ebay", "tiktok", "expands", "reannounces", "announces", "issues",
           "ingestion", "suffocation", "choking", "entrapment", "tip", "over", "poisoning", "laceration", "strangulation",
           "electrocution", "shock", "carbon", "monoxide", "drowning", "injuries", "consumers", "impact"}


NOT_BRAND = GENERIC | {"children", "child", "women", "womens", "men", "mens", "boys", "girls", "baby", "babies", "infant",
                       "infants", "toddler", "kid", "adult", "adults", "youth", "portable", "electric", "rechargeable",
                       "wooden", "plastic", "glass", "metal", "stainless", "steel", "gas", "fabric", "cordless", "mini",
                       "large", "small", "these", "this", "certain", "various", "all", "two", "three", "one",
                       "nine", "six", "four", "five", "multiple", "assorted", "magnetic", "battery", "lithium", "dresser",
                       "dressers", "space", "heaters", "heater", "power", "toy", "toys", "chest", "bike", "bikes"}


def words(text: str) -> list[str]:
    return WORD.findall((text or "").lower())


def stem(w: str) -> str:
    """Plural to singular, roughly: brushes -> brush, heaters -> heater, glass stays glass."""
    if len(w) > 4 and w.endswith("es") and w[:-2].endswith(("sh", "ch", "x", "ss")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def squash(code: str) -> str:
    return re.sub(r"[^a-z0-9]", "", code.lower())


UNIT = re.compile(r"\d+(mah|wh|w|v|a|mm|cm|m|in|inch|oz|ml|l|kg|g|lb|lbs|ft|pk|pack|pc|pcs|cup|cups|qt|gal|hz|gb|tb|k|x)")


def codes(text: str) -> set[str]:
    """Model-like codes (letters and digits mixed), minus sizes like 10000mah or 12oz."""
    out = set()
    for c in CODE.findall((text or "").lower()):
        s = squash(c)
        if len(s) >= 4 and not UNIT.fullmatch(s):
            out.add(s)
    return out


def _company(name: str) -> str:
    # "Bodum USA, Inc., of New York, New York" -> "bodum"
    head = re.split(r",\s*(?:of\b|inc\b|llc\b|ltd\b)|\bof\b", name, maxsplit=1, flags=re.I)[0]
    w = [x for x in words(head) if x not in COMPANY_NOISE]
    return " ".join(w[:2])


def recall_profile(r: dict) -> dict:
    """Pull out what matching needs from one CPSC recall record."""
    title = r.get("Title") or ""
    brands = set()
    # "Acme Recalls ...", "Acme Expands Recall of ...", "Acme Reannounces Recall of ..."
    m = re.match(r"(.+?)\s+(?:(?:expands|reannounces|announces|issues)\s+)?(?:recalls|recall)\b", title, flags=re.I)
    if m:
        brands.add(_company(m.group(1)))
    # "Acme Power Banks Recalled ..."
    m = re.match(r"(.+?)\s+(?:[\w’'-]+\s+){0,4}recalled\b", title, flags=re.I)
    if m:
        brands.add(_company(m.group(1)))
    # "... Recall of Zestro Grill Brushes": the product's own brand, after "recall of"
    m = re.search(r"\brecall of ([A-Z][\w&’'-]+)", title)
    if m:
        brands.add(_company(m.group(1)))
    # Product names usually start with the brand: "Zestro grill brushes"
    for p in r.get("Products") or []:
        first = (p.get("Name") or "").split(" ")[0]
        if first[:1].isupper() and re.sub(r"[’']s$", "", first.lower()) not in NOT_BRAND:
            brands.add(_company(first))
    for key in ("Manufacturers", "Importers", "Distributors"):
        for c in r.get(key) or []:
            if c.get("Name"):
                brands.add(_company(c["Name"]))
    brands = {b for b in brands if b and len(b) >= 3}
    product_text = " ".join([title] + [f"{p.get('Name', '')} {p.get('Model', '')} {p.get('Type', '')}"
                                       for p in r.get("Products") or []])
    upcs = {u.get("UPC", "").strip() for u in r.get("ProductUPCs") or [] if u.get("UPC")}
    brand_words = {w for b in brands for w in b.split()}
    return {
        "id": r.get("RecallNumber") or str(r.get("RecallID")),
        "title": title,
        "date": (r.get("RecallDate") or "")[:10],
        "url": r.get("URL") or "",
        "brands": sorted(brands),
        "codes": codes(product_text),
        "upcs": {u for u in upcs if u},
        "product_words": {stem(w) for w in words(product_text) if w not in GENERIC and w not in brand_words and len(w) > 2},
        "hazard": ((r.get("Hazards") or [{}])[0].get("Name") or "")[:240],
        "remedy": ((r.get("Remedies") or [{}])[0].get("Name") or "")[:240],
    }


def _has_brand(line_words: list[str], brand: str) -> bool:
    b = brand.split()
    return any(line_words[i:i + len(b)] == b for i in range(len(line_words) - len(b) + 1))


def match_line(line: str, profiles: list[dict]) -> dict:
    lw = words(line)
    lcodes = codes(line)
    lupcs = set(UPC.findall(line))
    best = None
    for p in profiles:
        reasons, verdict = [], None
        brand = next((b for b in p["brands"] if _has_brand(lw, b)), None)
        shared_codes = sorted(lcodes & p["codes"])
        shared_words = sorted({stem(w) for w in lw} & p["product_words"])
        if lupcs & p["upcs"]:
            verdict = "recalled"
            reasons.append(f"UPC {sorted(lupcs & p['upcs'])[0]}")
        if brand and shared_codes:
            verdict = "recalled"
            reasons += [f"brand “{brand}”", f"model {shared_codes[0]}"]
        elif brand and len(shared_words) >= 2:
            verdict = verdict or "check"
            reasons += [f"brand “{brand}”", "words " + ", ".join(shared_words[:4])]
        elif not brand and any(len(c) >= 6 for c in shared_codes):
            verdict = verdict or "check"
            reasons.append(f"model {shared_codes[0]} (brand not named)")
        if verdict:
            rank = (verdict == "recalled", len(shared_codes), len(shared_words))
            if best is None or rank > best[0]:
                best = (rank, {"verdict": verdict, "reasons": reasons, "recall": {
                    k: p[k] for k in ("id", "title", "date", "url", "hazard", "remedy")}})
    if best:
        return {"line": line, **best[1]}
    return {"line": line, "verdict": "none", "reasons": [], "recall": None}


def check_catalogue(lines: list[str], recalls: list[dict]) -> dict:
    profiles = [recall_profile(r) for r in recalls]
    results = [match_line(line, profiles) for line in lines]
    order = {"recalled": 0, "check": 1, "none": 2}
    results.sort(key=lambda x: order[x["verdict"]])
    dates = sorted(p["date"] for p in profiles if p["date"])
    return {
        "checked_lines": len(lines),
        "recalls_checked": len(profiles),
        "from": dates[0] if dates else None,
        "to": dates[-1] if dates else None,
        "counts": {k: sum(r["verdict"] == k for r in results) for k in order},
        "results": results,
    }
