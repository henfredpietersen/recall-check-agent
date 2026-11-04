"""VIN checks done before any network call.

US-market VINs carry a check digit in position 9. A VIN that fails it is either mistyped or
from a market that doesn't use the check digit (many non-US vehicles), and NHTSA's data only
covers vehicles sold in the US, so the agent stops and says which.
"""

from __future__ import annotations

import re

VALUES = {**{str(d): d for d in range(10)},
          **dict(zip("ABCDEFGH", range(1, 9), strict=True)),
          **dict(zip("JKLMN", range(1, 6), strict=True)), "P": 7, "R": 9,
          **dict(zip("STUVWXYZ", range(2, 10), strict=True))}
WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")


def find_vin(text: str) -> str | None:
    m = VIN_RE.search(text.upper())
    return m.group(0) if m else None


def check_digit(vin: str) -> str:
    total = sum(VALUES[c] * w for c, w in zip(vin, WEIGHTS, strict=True))
    r = total % 11
    return "X" if r == 10 else str(r)


def validate(vin: str) -> tuple[bool, str]:
    vin = vin.strip().upper()
    if len(vin) != 17:
        return False, f"A VIN has 17 characters; this has {len(vin)}."
    bad = sorted(set(c for c in vin if c not in VALUES))
    if bad:
        return False, f"A VIN can't contain {', '.join(bad)} (I, O and Q are never used)."
    want = check_digit(vin)
    if vin[8] != want:
        return False, (f"The check digit (9th character) should be {want} but is {vin[8]}. Either it's mistyped, "
                       "or it's not a US-market vehicle, and NHTSA only covers US-market vehicles.")
    return True, "ok"
