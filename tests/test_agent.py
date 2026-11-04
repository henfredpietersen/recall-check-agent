"""The agent loop, run offline: each tool result comes from a fixture instead of the network."""

import datetime as dt
import json
from pathlib import Path

import pytest

from recall_agent import agent, vin

FX = Path(__file__).parent / "fixtures"
TODAY = dt.date(2026, 11, 4)


def load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


FAKE_API = {
    "cpsc_recalls": lambda a: load("cpsc_recalls.json"),
    "vpic_models": lambda a: load("vpic_models_honda_2003.json") if (a["make"], a["year"]) == ("honda", 2003)
    else {"Count": 0, "Results": []},
    "vpic_decode": lambda a: load("vpic_decode_1HGCM82633A004352.json"),
    "nhtsa_recalls": lambda a: load("nhtsa_recalls_accord_2003.json") if a["model"] == "Accord"
    else {"Count": 0, "results": []},
}


def run(request, api=FAKE_API):
    """Drive the loop the way the page does. Returns (final step, calls made)."""
    obs, calls = [], []
    for _ in range(10):
        s = agent.step(request, obs, TODAY)
        if s["action"] != "call":
            return s, calls
        assert agent.allowed(s["url"]), s["url"]
        calls.append(s["tool"])
        obs.append({"tool": s["tool"], "args": s["args"], "data": api[s["tool"]](s["args"])})
    raise AssertionError("loop did not finish")


def test_product_list_goes_to_cpsc_and_drops_the_instruction_line():
    s, calls = run("Check these products for recalls:\nAcme Home heater AH-2041\nCotton bath towel")
    assert calls == ["cpsc_recalls"] and s["action"] == "done"
    assert s["understood"]["lines"] == ["Acme Home heater AH-2041", "Cotton bath towel"]
    assert s["understood"]["since"] == "2025-11-04"
    a = s["answer"]
    assert a["counts"] == {"recalled": 1, "check": 0, "none": 1}
    assert "not that a product is safe" in a["caveat"]


def test_months_window_is_read_and_capped():
    assert agent.understand("last 3 months\nAcme kettle", TODAY)["since"] == "2026-08-04"
    assert agent.understand("last 99 months\nAcme kettle", TODAY)["months"] == agent.MAX_MONTHS


def test_vehicle_checks_the_model_exists_then_lists_recalls():
    s, calls = run("Any recalls on a 2003 Honda Accord?")
    assert calls == ["vpic_models", "nhtsa_recalls"]
    a = s["answer"]
    assert a["vehicle"] == "2003 Honda Accord" and len(a["recalls"]) == 2
    assert a["recalls"][0]["do_not_drive"]  # the urgent one first
    assert "1 of them carries a do-not-drive" in a["text"]


def test_misspelt_model_asks_instead_of_saying_no_recalls():
    s, calls = run("2003 Honda Acord")
    assert calls == ["vpic_models"]  # never asks the recall API
    assert s["action"] == "ask" and "Accord" in s["question"]


def test_model_matching_ignores_case_and_hyphens():
    s, calls = run("2003 honda crv")
    assert s["action"] == "done" and calls == ["vpic_models", "nhtsa_recalls"]
    assert s["answer"]["vehicle"] == "2003 Honda CR-V"
    assert s["answer"]["recalls"] == [] and "no recall campaigns" in s["answer"]["text"]


def test_unknown_make_year_combination_stops():
    s, _ = run("1990 Tesla Model S")
    assert s["action"] == "stop" and "no 1990 models" in s["reason"]


def test_vin_flow_decodes_then_lists_and_says_it_is_not_vin_specific():
    s, calls = run("Check VIN 1HGCM82633A004352 please")
    assert calls == ["vpic_decode", "nhtsa_recalls"]
    assert s["answer"]["vin"] == "1HGCM82633A004352"
    assert "already been repaired" in s["answer"]["caveat"]


def test_bad_vin_stops_before_any_call():
    s, calls = run("1HGCM82633A004353")
    assert calls == [] and s["action"] == "stop" and "check digit" in s["reason"]


@pytest.mark.parametrize("v,ok", [("1HGCM82633A004352", True), ("11111111111111111", True),
                                  ("1HGCM82633A00435", False), ("1HGCM82633A004353", False)])
def test_vin_check_digit(v, ok):
    assert vin.validate(v)[0] is ok


def test_vin_with_i_o_q_is_not_taken_as_a_vin():
    assert vin.find_vin("1HGCM82633AOO4352") is None


@pytest.mark.parametrize("text,needle", [
    ("", "Paste a product list"),
    ("Toyota Corolla", "Which model year"),
    ("2031 Toyota Corolla", "future"),
    ("2020 Toyota", "Which Toyota model"),
])
def test_asks_when_it_cannot_tell(text, needle):
    s = agent.step(text, [], TODAY)
    assert s["action"] == "ask" and needle in s["question"]


def test_call_limit():
    obs = [{"tool": "x", "args": {}, "data": {}}] * agent.MAX_CALLS
    assert agent.step("2003 Honda Accord", obs, TODAY)["action"] == "stop"


def test_only_allowlisted_hosts():
    assert agent.allowed(agent.tool_url("cpsc_recalls", {"since": "2026-01-01"}))
    assert not agent.allowed("https://evil.example.com/x")
    assert not agent.allowed("http://api.nhtsa.gov/recalls")  # https only
    with pytest.raises(ValueError):
        agent.tool_url("send_email", {})


def test_url_arguments_are_escaped():
    url = agent.tool_url("nhtsa_recalls", {"make": "land-rover", "model": "range rover&x=1", "year": 2020})
    assert "range%20rover%26x%3D1" in url and agent.allowed(url)


def test_step_json_matches_step():
    out = json.loads(agent.step_json("2003 Honda Accord", "[]", "2026-11-04"))
    assert out == agent.step("2003 Honda Accord", [], TODAY)


def test_months_line_is_not_a_product_and_dates_are_calendar_months():
    u = agent.understand("last 3 months\nAcme kettle", TODAY)
    assert u["lines"] == ["Acme kettle"]
    assert agent.months_ago(dt.date(2026, 3, 31), 1) == dt.date(2026, 2, 28)
    assert agent.months_ago(dt.date(2026, 1, 15), 12) == dt.date(2025, 1, 15)


@pytest.mark.parametrize("text,make,model", [
    ("is my 2018 VW Golf recalled?", "volkswagen", "golf"),
    ("2021 ford f-150", "ford", "f-150"),
    ("range rover 2019 sport", "land-rover", "range rover sport"),
    ("any open recalls for a 2003 Honda Civic Type R", "honda", "civic type r"),
])
def test_vehicle_parsing(text, make, model):
    u = agent.understand(text, TODAY)
    assert (u["intent"], u["make"], u["model"]) == ("vehicle", make, model)


def test_longer_model_name_falls_back_to_the_listed_model():
    s, calls = run("2003 Honda Civic Type R")
    assert s["action"] == "done" and s["answer"]["vehicle"] == "2003 Honda Civic"
    assert "NHTSA lists it as 'Civic'" in s["answer"]["text"]
