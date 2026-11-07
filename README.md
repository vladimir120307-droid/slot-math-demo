# Slot math demo: 5x5, 15 lines, free spins

A small, complete slot math model built to show the method: paytable, reel strips and rules in one
versioned JSON file, exact RTP by component, simulation cross-checks with confidence intervals,
worked examples and a report.

```
pip install -r requirements.txt
python build_model.py                                   # model.json from the counts in build_model.py
python run.py --spins 30000000 --bonus-rounds 2000000 --seed 7   # report.md, win_distribution.png, results.json
```

- `build_model.py`: paytable, 15 paylines, free-spin rules, symbol counts per reel. Strips are
  generated with fixed seeds, scatters spaced so a window shows at most one.
- `model.json`: the file a backend imports. `version_sha256` changes whenever anything in it changes.
- `slotmath.py`: line evaluation, exact RTP (base lines, scatter pays, free spins with retriggers and
  a spin limit), full-game and stratified Monte Carlo.
- `report.md`: results, rules, method, rare outcomes and worked examples.

Demonstration only, not a certified game.
