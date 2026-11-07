"""Builds model.json: paytable, paylines, reel strips and feature rules for a 5x5, 15-line slot.

The strips are generated from per-reel symbol counts with a fixed seed, so the same
counts always give the same strips. Scatters are placed at least ROWS apart, so a
5-row window never shows two scatters on one reel.
"""
import hashlib
import json
import random
import sys
from pathlib import Path

ROWS = 5
REELS = 5

SYMBOLS = ["W", "S", "H1", "H2", "H3", "L1", "L2", "L3", "L4"]

# Line pays in multiples of the line bet (total bet = 15 line bets).
PAYTABLE = {
    "W":  {3: 60, 4: 250, 5: 1000},
    "H1": {3: 50, 4: 150, 5: 500},
    "H2": {3: 35, 4: 100, 5: 300},
    "H3": {3: 25, 4: 75, 5: 200},
    "L1": {3: 12, 4: 35, 5: 100},
    "L2": {3: 10, 4: 25, 5: 75},
    "L3": {3: 8, 4: 20, 5: 50},
    "L4": {3: 5, 4: 15, 5: 35},
}

# Scatter pays in multiples of the total bet, by number of reels showing a scatter.
SCATTER_PAY = {3: 2, 4: 10, 5: 50}

# Row index per reel for each of the 15 fixed lines (row 0 is the top row).
PAYLINES = [
    [2, 2, 2, 2, 2], [1, 1, 1, 1, 1], [3, 3, 3, 3, 3], [0, 0, 0, 0, 0], [4, 4, 4, 4, 4],
    [0, 1, 2, 3, 4], [4, 3, 2, 1, 0], [1, 2, 3, 2, 1], [3, 2, 1, 2, 3], [0, 1, 0, 1, 0],
    [4, 3, 4, 3, 4], [2, 1, 2, 3, 2], [2, 3, 2, 1, 2], [1, 0, 1, 2, 1], [3, 4, 3, 2, 3],
]

FREE_SPINS = {
    "trigger_scatters": 3,
    "spins_awarded": 10,
    "retrigger_spins": 10,
    "max_total_spins": 50,
    "line_multiplier": 3,
}

MAX_WIN_X_BET = 5000

# Symbol counts per reel, same order as SYMBOLS. Each strip has 60 stops.
BASE_COUNTS = [
    [1, 1, 4, 5, 6, 8, 10, 12, 13],
    [2, 1, 3, 5, 6, 8, 10, 12, 13],
    [2, 1, 3, 5, 6, 8, 10, 12, 13],
    [2, 1, 3, 5, 6, 8, 10, 12, 13],
    [2, 1, 3, 5, 6, 8, 10, 12, 13],
]
FREE_COUNTS = [
    [4, 1, 5, 5, 6, 8, 9, 10, 12],
    [7, 1, 5, 5, 6, 8, 8, 10, 10],
    [7, 1, 5, 5, 6, 8, 8, 10, 10],
    [7, 1, 5, 5, 6, 8, 8, 10, 10],
    [7, 1, 5, 5, 6, 8, 8, 10, 10],
]


def make_strip(counts, seed):
    """Shuffles the non-scatter symbols, then inserts scatters evenly spaced."""
    rng = random.Random(seed)
    n_scatter = counts[SYMBOLS.index("S")]
    body = []
    for sym, n in zip(SYMBOLS, counts):
        if sym != "S":
            body += [sym] * n
    rng.shuffle(body)
    length = len(body) + n_scatter
    strip = [None] * length
    if n_scatter:
        step = length / n_scatter
        for k in range(n_scatter):
            strip[int(k * step)] = "S"
    it = iter(body)
    strip = [s if s is not None else next(it) for s in strip]
    positions = [i for i, s in enumerate(strip) if s == "S"]
    for a, b in zip(positions, positions[1:] + [positions[0] + length]):
        assert b - a >= ROWS, "scatters closer than the window height"
    return strip


def build():
    model = {
        "name": "demo-5x5-15-lines",
        "reels": REELS,
        "rows": ROWS,
        "symbols": SYMBOLS,
        "wild": "W",
        "scatter": "S",
        "line_rule": "Left to right. The line pays the larger of the leading wild run "
                     "and the run of the first non-wild symbol with wilds substituting. "
                     "Scatters do not pay on lines and break a run.",
        "paytable_line_bet_x": {s: {str(k): v for k, v in p.items()} for s, p in PAYTABLE.items()},
        "scatter_pay_total_bet_x": {str(k): v for k, v in SCATTER_PAY.items()},
        "paylines": PAYLINES,
        "free_spins": FREE_SPINS,
        "max_win_total_bet_x": MAX_WIN_X_BET,
        "base_strips": [make_strip(c, 1000 + i) for i, c in enumerate(BASE_COUNTS)],
        "free_strips": [make_strip(c, 2000 + i) for i, c in enumerate(FREE_COUNTS)],
    }
    body = json.dumps(model, sort_keys=True, separators=(",", ":")).encode()
    model["version_sha256"] = hashlib.sha256(body).hexdigest()[:16]
    return model


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("model.json"))
    m = build()
    out.write_text(json.dumps(m, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out} version {m['version_sha256']}")
