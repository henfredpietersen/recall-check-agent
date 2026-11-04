"""Product matching against CPSC-shaped records (made-up companies; real field names)."""

import json
from pathlib import Path

import pytest

from recall_agent import match

RECALLS = json.loads((Path(__file__).parent / "fixtures" / "cpsc_recalls.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def profiles():
    return [match.recall_profile(r) for r in RECALLS]


def verdict(line, profiles):
    return match.match_line(line, profiles)


def test_brand_extraction(profiles):
    by_id = {p["id"]: p for p in profiles}
    assert "acme home" in by_id["90001"]["brands"]
    assert "brightlite" in by_id["90002"]["brands"]  # "<Brand> Power Banks Recalled ..."
    assert "cozynest" in by_id["90003"]["brands"]
    assert "ah2041" in by_id["90001"]["codes"]


def test_sizes_are_not_model_codes():
    assert match.codes("Brightlite 10000mAh 12oz 65W power bank") == set()
    assert match.codes("Model DR-HSH015 heater") == {"drhsh015"}


def test_brand_and_model_is_recalled(profiles):
    r = verdict("Acme Home ceramic heater AH2041", profiles)
    assert r["verdict"] == "recalled" and r["recall"]["id"] == "90001"
    assert any("ah2041" in x for x in r["reasons"])


def test_upc_alone_is_recalled(profiles):
    r = verdict("Space heater, UPC 012345678905", profiles)
    assert r["verdict"] == "recalled" and r["reasons"][0].startswith("UPC")


def test_brand_and_product_words_is_check_not_recalled(profiles):
    r = verdict("Brightlite portable power bank 10000mAh", profiles)
    assert r["verdict"] == "check" and r["recall"]["id"] == "90002"
    r = verdict("Cozynest infant lounger", profiles)
    assert r["verdict"] == "check" and r["recall"]["id"] == "90003"


def test_long_model_code_without_brand_is_check(profiles):
    r = verdict("Generic travel adapter AH-2041", profiles)
    assert r["verdict"] == "check" and "brand not named" in r["reasons"][0]


def test_brand_must_be_whole_words(profiles):
    assert verdict("Acmeville kettle", profiles)["verdict"] == "none"
    assert verdict("Northpeakers socks", profiles)["verdict"] == "none"


def test_brand_alone_is_not_enough(profiles):
    # same brand, unrelated product: no shared product words, no model
    assert verdict("Northpeak water bottle", profiles)["verdict"] == "none"


def test_unrelated_item_is_none(profiles):
    r = verdict("Cotton bath towel, grey", profiles)
    assert r == {"line": "Cotton bath towel, grey", "verdict": "none", "reasons": [], "recall": None}


def test_catalogue_summary_sorts_worst_first():
    lines = ["Cotton bath towel", "Cozynest infant lounger", "Northpeak NP-H300 harness"]
    out = match.check_catalogue(lines, RECALLS)
    assert out["counts"] == {"recalled": 1, "check": 1, "none": 1}
    assert [r["verdict"] for r in out["results"]] == ["recalled", "check", "none"]
    assert (out["from"], out["to"], out["recalls_checked"]) == ("2026-03-01", "2026-10-20", 5)


def test_brand_after_expands_recall_of(profiles):
    p = match.recall_profile(RECALLS[4])
    assert "zestro" in p["brands"] and "hairco" in p["brands"]
    assert not any("expands" in b for b in p["brands"])
    r = match.match_line("Zestro stainless grill brush", [p])
    assert r["verdict"] == "check" and r["recall"]["id"] == "90005"


def test_generic_first_words_are_not_brands():
    p = match.recall_profile({"Title": "Acme Recalls Space Heaters", "Products": [
        {"Name": "Children's space heaters", "Model": "", "Type": ""}, {"Name": "Space heaters", "Model": "", "Type": ""}]})
    assert p["brands"] == ["acme"]
