"""Exact math, simulation cross-checks, worked examples and a report for model.json.

    python build_model.py          # writes model.json from the counts in build_model.py
    python run.py --spins 30000000 --bonus-rounds 2000000 --seed 7
"""
import argparse
import json
import platform
import time
from pathlib import Path

import numpy as np

from slotmath import (BUCKET_LABELS, Model, bonus_rounds, exact, line_pay,
                      simulate_game, simulate_stratified, spin)

HERE = Path(__file__).parent


def window_at(model, strips, stops):
    return np.array([[strips[r][(stops[r] + k) % len(strips[r])] for k in range(model.rows)]
                     for r in range(model.reels)], dtype=np.int8)


def describe_spin(model, strips, stops, mult=1):
    """Text for one spin: the window, each paying line and the total."""
    w = window_at(model, strips, stops)
    names = model.symbols
    lines = []
    for row in range(model.rows):
        lines.append("  " + " ".join(f"{names[w[r, row]]:>2}" for r in range(model.reels)))
    syms = w[np.arange(model.reels)[None, :], model.lines]
    pays = line_pay(model, syms)
    out = ["Window (reels left to right, top row first):"] + lines
    total = 0.0
    for i in np.nonzero(pays)[0]:
        seq = " ".join(names[s] for s in syms[i])
        x_bet = mult * pays[i] / model.n_lines
        total += x_bet
        out.append(f"  line {i + 1:2d} {model.lines[i].tolist()}: {seq} -> {pays[i]:.0f} line bets"
                   + (f" x{mult}" if mult > 1 else "") + f" = {x_bet:.3f} x bet")
    k = int((w == model.S).any(axis=1).sum())
    if model.scatter_pay[k]:
        out.append(f"  scatters on {k} reels -> {model.scatter_pay[k]:.0f} x bet")
        total += model.scatter_pay[k]
    out.append(f"  total {total:.3f} x bet" + (f"; {k} scatters trigger free spins" if k >= model.trigger else ""))
    return "\n".join(out), total, k


def find_example(model, strips, rng, predicate, tries=200000):
    for _ in range(tries):
        stops = [int(rng.integers(0, len(s))) for s in strips]
        text, total, k = describe_spin(model, strips, stops)
        if predicate(total, k):
            return stops
    raise RuntimeError("no example found")


def worked_examples(model, seed):
    rng = np.random.default_rng(seed)
    base_stops = find_example(model, model.base, rng, lambda t, k: 2 <= t < 20 and k < 3)
    base_text, _, _ = describe_spin(model, model.base, base_stops)
    trig_stops = find_example(model, model.base, rng, lambda t, k: k >= 3)
    trig_text, _, _ = describe_spin(model, model.base, trig_stops)
    # one free-spin round, spin by spin
    remaining, awarded, total, rows = model.fs_awarded, model.fs_awarded, 0.0, []
    n = 0
    while remaining:
        n += 1
        stops = [int(rng.integers(0, len(s))) for s in model.free]
        _, win, k = describe_spin(model, model.free, stops, mult=model.fs_mult)
        total += win
        remaining -= 1
        note = ""
        if k >= model.trigger and awarded + model.fs_retrigger <= model.fs_max:
            remaining += model.fs_retrigger
            awarded += model.fs_retrigger
            note = f" retrigger +{model.fs_retrigger}"
        rows.append(f"  spin {n:2d}: stops {stops} -> {win:.3f} x bet{note}")
    rows.append(f"  round total {total:.3f} x bet over {n} spins")
    return base_stops, base_text, trig_stops, trig_text, "\n".join(rows)


def chart(model, game, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    hist = np.array(game["hist"], dtype=float)
    p = hist / hist.sum()
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.bar(range(len(p)), np.where(p > 0, p, np.nan), color="#3b6ea5")
    ax.set_yscale("log")
    ax.set_xticks(range(len(p)), BUCKET_LABELS, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("probability per spin")
    ax.set_xlabel("round win, x total bet")
    ax.set_title(f"Win distribution, {game['spins']:,} simulated spins "
                 f"(RTP {100 * game['rtp']:.2f}% ± {100 * game['rtp_ci95']:.2f}%)", fontsize=10)
    for i, v in enumerate(p):
        if v > 0:
            ax.text(i, v * 1.25, f"{v:.2e}" if v < 1e-3 else f"{v:.3f}", ha="center", fontsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(HERE / "model.json"))
    ap.add_argument("--spins", type=int, default=30_000_000)
    ap.add_argument("--bonus-rounds", type=int, default=2_000_000)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    model = Model(args.model)
    t0 = time.time()
    ex = exact(model)
    game = simulate_game(model, args.spins, seed=args.seed)
    strat = simulate_stratified(model, args.spins, args.bonus_rounds, seed=args.seed + 1)
    elapsed = time.time() - t0
    base_stops, base_text, trig_stops, trig_text, fs_text = worked_examples(model, args.seed + 2)

    max_line = model.pay.max() / model.n_lines
    max_base_spin = model.n_lines * max_line + model.scatter_pay.max()
    max_fs_spin = model.fs_mult * model.n_lines * max_line + model.scatter_pay.max()
    p = np.array(game["hist"], dtype=float) / game["spins"]
    dist_rows = "\n".join(f"| {lbl} | {c:,} | {q:.3e} |" for lbl, c, q in zip(BUCKET_LABELS, game["hist"], p))

    report = f"""# Demo slot math: 5x5, 15 fixed lines, free spins

Model `{model.raw['name']}`, version `{model.version}` (SHA-256 of model.json, first 16 hex).
Built with `python build_model.py`, checked with `python run.py --spins {args.spins} --bonus-rounds {args.bonus_rounds} --seed {args.seed}`
on Python {platform.python_version()}, numpy {np.__version__}. Run time {elapsed:.0f} s.

This is a demonstration model built for the brief, not a certified game.

## Rules

- 5 reels, 5 rows, 15 fixed lines (`paylines` in model.json), total bet = 15 line bets.
- Line wins pay left to right from reel 1. A line pays the larger of the leading wild run and
  the run of the first non-wild symbol with wilds substituting. Scatters never pay on lines.
- 3, 4 or 5 reels showing a scatter pay {model.scatter_pay[3]:.0f}, {model.scatter_pay[4]:.0f} or {model.scatter_pay[5]:.0f} x bet and award {model.fs_awarded} free spins.
- Free spins use their own reel strips with more wilds, line wins x{model.fs_mult}.
  3+ scatters during free spins add {model.fs_retrigger} spins, up to {model.fs_max} spins per round.
- Maximum win {model.cap:,} x bet per round (base spin plus its free spins).

## Exact results

| Measure | Value |
|---|---|
| RTP | **{100 * ex['rtp']:.4f}%** |
| base game lines | {100 * ex['base_line']:.4f}% |
| base game scatter pays | {100 * ex['base_scatter']:.4f}% |
| free spins | {100 * ex['bonus']:.4f}% |
| free spins trigger | 1 in {1 / ex['p_trigger']:.1f} spins |
| expected free spins per round | {ex['fs_expected_spins']:.4f} |
| retrigger chance per free spin | {100 * ex['fs_retrigger_per_spin']:.4f}% |
| average free-spin round | {ex['bonus_ev']:.3f} x bet |
| 5 wilds on a given line, base | 1 in {1 / ex['p_five_wild_line_base']:,.0f} |
| 5 wilds on a given line, free spins | 1 in {1 / ex['p_five_wild_line_free']:,.0f} |

Method: every row of a circular strip has the strip's symbol frequencies, so one line's expected
pay is a sum over all 9^5 symbol combinations with their exact probabilities, and 15 lines at
1/15 of the bet make it the line RTP. Scatters sit at least 5 stops apart, so a reel shows at most
one, and the number of scatter reels is a convolution of five Bernoulli terms. The free-spin round
value is expected spins (exact recursion over remaining and awarded spins, including the 50-spin
limit) times the expected win per free spin, which holds by Wald's identity because whether a spin
is played depends only on earlier spins.

## Simulation cross-check

Full game, {game['spins']:,} spins, seed {args.seed}:

| Measure | Value |
|---|---|
| RTP | {100 * game['rtp']:.3f}% ± {100 * game['rtp_ci95']:.3f}% (95%) |
| hit rate (any win) | {100 * game['hit_rate']:.2f}% |
| free spins trigger | 1 in {1 / game['trigger_rate']:.1f} spins |
| standard deviation per spin | {game['sd_per_spin']:.2f} x bet |
| largest round win | {game['max_win']:,.1f} x bet |
| rounds reaching the {model.cap:,} x cap | {game['cap_hits']} |

Stratified check (base game and free-spin rounds simulated separately, combined with the exact
trigger chance), {args.spins:,} base spins and {strat['bonus_rounds']:,} free-spin rounds:

| Measure | Simulated | Exact |
|---|---|---|
| RTP | {100 * strat['rtp']:.3f}% ± {100 * strat['rtp_ci95']:.3f}% | {100 * ex['rtp']:.3f}% |
| average free-spin round | {strat['bonus_ev']:.2f} ± {strat['bonus_ev_ci95']:.2f} x bet | {ex['bonus_ev']:.2f} x bet |
| spins per round | {strat['fs_mean_spins']:.4f} | {ex['fs_expected_spins']:.4f} |
| rounds of 500 x bet or more | {100 * strat['bonus_p_over_500']:.4f}% | |
| rounds of 1,000 x bet or more | {100 * strat['bonus_p_over_1000']:.4f}% | |
| largest free-spin round | {strat['bonus_max']:,.1f} x bet | |

## Win distribution (full game)

| Round win, x bet | Spins | Probability |
|---|---|---|
{dist_rows}

![win distribution](win_distribution.png)

## Rare and capped outcomes

- Structural maximum per spin: base {max_base_spin:,.0f} x bet (5 wilds on all 15 lines plus 5 scatters),
  free spin {max_fs_spin:,.0f} x bet. The real maximum is lower, because no strip holds 5 wilds in a row.
- Over a 50-spin round the structural bound is far above the {model.cap:,} x cap, so the cap is a
  real rule, but the simulation never reached it. In a full engagement its effect on RTP is
  measured with importance sampling (free-spin strips tilted toward wilds, results reweighted by
  the likelihood ratio), so the cap's share of RTP comes with an error bar instead of "zero hits".

## Worked examples

Base win, stops {base_stops}:

```
{base_text}
```

Free spins trigger, stops {trig_stops}:

```
{trig_text}
```

One free-spin round:

```
{fs_text}
```
"""
    (HERE / "report.md").write_text(report, encoding="utf-8")
    chart(model, game, HERE / "win_distribution.png")
    (HERE / "results.json").write_text(json.dumps(
        {"model_version": model.version, "exact": ex, "game": game, "stratified": strat},
        indent=1, default=float), encoding="utf-8")
    print(f"exact RTP {100 * ex['rtp']:.4f}%  game {100 * game['rtp']:.3f}% ± {100 * game['rtp_ci95']:.3f}%  "
          f"stratified {100 * strat['rtp']:.3f}% ± {100 * strat['rtp_ci95']:.3f}%  ({elapsed:.0f} s)")


if __name__ == "__main__":
    main()
