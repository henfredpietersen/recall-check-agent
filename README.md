# recall-check-agent

Paste a shop's product list, or type a vehicle or a VIN, and this checks it against live US government recall data. It's a small tool-calling agent: it decides which public API to call, one call at a time, and shows every step. When it can't tell, it asks instead of guessing.

**Try it live:** https://outview.co.za/case-study-recall-agent/

Built AI-assisted under my direction. I chose the data sources, the tools and the rules for when it's allowed to answer. Claude generated the code, and I reviewed it, ran it and checked the tests. I didn't hand-write it.

## What it does

| You give it | It calls | You get |
|---|---|---|
| A product list, one per line | CPSC recalls from the last 12 months (or "last 3 months", up to 24) | Each line marked **recalled**, **check** or **no match**, with the words that matched and a link to the recall notice |
| A vehicle: "2019 Toyota Corolla" | NHTSA's model list for that make and year, then NHTSA recalls | Every recall campaign, with do-not-drive and park-outside warnings first |
| A VIN | NHTSA's VIN decoder, then NHTSA recalls | The same, for the decoded make, model and year |

The rules it keeps:

- **Four tools, three hosts.** `www.saferproducts.gov`, `vpic.nhtsa.dot.gov` and `api.nhtsa.gov`, https only. The agent builds every URL and refuses anything else, and the page checks the host again before fetching. At most four calls per question.
- **It doesn't trust an empty answer.** NHTSA's recall API returns an empty list for a misspelt model as well as for a model with no recalls. So before saying "no recalls", the agent checks NHTSA lists that model for that make and year. If it doesn't, the agent asks ("Did you mean Accord?") and never reaches the recall call.
- **VIN check digit first.** A VIN that fails the check digit stops before any call. It's either mistyped or not a US-market vehicle, and NHTSA only covers US-market vehicles.
- **A VIN answer isn't about that one car.** It lists recalls for the make, model and year. Whether that car has been repaired needs the VIN lookup on nhtsa.gov or the manufacturer's site, and the answer says so.
- **It never says a product is safe.** "No match" means no recall was found in the records checked.

### How product lines are matched

Plain text rules (`recall_agent/match.py`):

- **recalled**: the UPC matches, or the brand and a model number both match.
- **check**: the brand matches and at least two product words overlap, or a model number of six or more characters matches without the brand.
- **no match**: nothing above.

Brands come from the recall title ("Acme Recalls …", "Acme Power Banks Recalled …", "… Expands Recall of Acme …"), the first word of each product name, and the listed manufacturers, importers and distributors. A brand must match as whole words, so "Acmeville" doesn't match "Acme". Sizes like "10000mAh" or "12oz" don't count as model numbers, and plurals are folded ("brushes" matches "brush").

On 4 November 2026 I ran a list of 20 everyday unbranded and big-brand products against the 575 CPSC recalls from the previous 12 months: none were flagged. That shows it doesn't raise false alarms on that list. It doesn't prove it catches everything; see "What this isn't".

There's no language model anywhere. The router is rules in `recall_agent/agent.py`, which makes it predictable and testable, and every decision can be shown on the page.

## Run it

```bash
python -m pytest -q                                   # 42 tests, offline, standard library + pytest
python -m recall_agent "2003 Honda Accord"            # live calls from your machine
python -m recall_agent "Check VIN 1HGCM82633A004352"
python -m recall_agent --file my_products.txt
python web/build.py                                   # rebuild docs/demo.js after changing recall_agent/ or web/
```

## What was tested

- `tests/test_match.py`: brand extraction from real-shaped CPSC records, UPC and model matches, whole-word brands, sizes ignored, a brand alone isn't enough, and results sorted worst first.
- `tests/test_agent.py`: the full loop with each API answer taken from a fixture. Product lists go to CPSC and drop the instruction line; vehicles check the model list before the recall call; a typo leads to a question, not "no recalls"; "Civic Type R" falls back to NHTSA's "Civic" and says so; a bad VIN stops before any call; the call limit and host allowlist hold; and URL arguments are escaped.
- `tests/test_page.py`: the published page embeds the current code, and its host allowlist matches the agent's.
- The fixtures copy the APIs' real field names (checked on 4 November 2026). The products and companies in them are made up, so the tests can't be mistaken for claims about real products.
- I also ran the page live on 4 November 2026 against all three services; the results are on the demo page.

CI runs lint, the tests and the page drift check on every push.

## What this isn't

- US data only. CPSC covers consumer products sold in the US and NHTSA covers US-market vehicles. Food, medicines and cosmetics belong to other agencies and aren't checked.
- Text matching misses products sold under another name or recalled under a supplier's name, and a **check** is a prompt for a person, not a finding. The linked recall notice is the source of truth.

## Files

```
recall_agent/agent.py   router, tools, allowlist, the step loop
recall_agent/match.py   product-line matching against CPSC records
recall_agent/vin.py     VIN format and check digit
recall_agent/__main__.py  command line, with real calls
web/page.js, build.py   the demo page; build.py embeds the package into docs/demo.js
```

MIT licence. Data: U.S. Consumer Product Safety Commission and National Highway Traffic Safety Administration, public.
