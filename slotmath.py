"""Exact RTP and Monte Carlo simulation for the 5x5, 15-line model in model.json.

All wins are in multiples of the total bet (15 line bets).
"""
import itertools
import json
from functools import lru_cache
from pathlib import Path

import numpy as np


class Model:
    def __init__(self, path):
        m = json.loads(Path(path).read_text(encoding="utf-8"))
        self.raw = m
        self.symbols = m["symbols"]
        self.n_sym = len(self.symbols)
        self.W = self.symbols.index(m["wild"])
        self.S = self.symbols.index(m["scatter"])
        self.rows = m["rows"]
        self.reels = m["reels"]
        self.lines = np.array(m["paylines"], dtype=np.int64)
        self.n_lines = len(self.lines)
        # pay[s, k]: line pay in line bets for k of a kind (k = 0..5)
        self.pay = np.zeros((self.n_sym, self.reels + 1))
        for s, table in m["paytable_line_bet_x"].items():
            for k, v in table.items():
                self.pay[self.symbols.index(s), int(k)] = v
        self.scatter_pay = np.zeros(self.reels + 1)
        for k, v in m["scatter_pay_total_bet_x"].items():
            self.scatter_pay[int(k)] = v
        fs = m["free_spins"]
        self.trigger = fs["trigger_scatters"]
        self.fs_awarded = fs["spins_awarded"]
        self.fs_retrigger = fs["retrigger_spins"]
        self.fs_max = fs["max_total_spins"]
        self.fs_mult = fs["line_multiplier"]
        self.cap = m["max_win_total_bet_x"]
        idx = {s: i for i, s in enumerate(self.symbols)}
        self.base = [np.array([idx[s] for s in strip], dtype=np.int8) for strip in m["base_strips"]]
        self.free = [np.array([idx[s] for s in strip], dtype=np.int8) for strip in m["free_strips"]]
        self.version = m.get("version_sha256", "")


def line_pay(model, sym):
    """sym[..., 5] symbol ids on a line, left to right. Returns pay in line bets."""
    is_w = sym == model.W
    w_run = np.cumprod(is_w, axis=-1).sum(axis=-1)
    non_w = ~is_w
    has_non_w = non_w.any(axis=-1)
    first = np.argmax(non_w, axis=-1)
    f = np.take_along_axis(sym, first[..., None], axis=-1)[..., 0]
    match = (sym == f[..., None]) | is_w
    f_run = np.cumprod(match, axis=-1).sum(axis=-1)
    pay_f = np.where(has_non_w & (f != model.S), model.pay[f, f_run], 0.0)
    pay_w = model.pay[model.W, w_run]
    return np.maximum(pay_f, pay_w)


# ---------------------------------------------------------------- exact

def symbol_probs(strips, n_sym):
    return np.array([np.bincount(s, minlength=n_sym) / len(s) for s in strips])


def exact_line_ev(model, strips):
    """Expected pay of one line in line bets. Every row of a circular strip has the
    strip's symbol frequencies, so all 15 lines share this value, and 15 lines at
    1/15 of the bet each make it the line RTP in total-bet units."""
    p = symbol_probs(strips, model.n_sym)
    combos = np.array(list(itertools.product(range(model.n_sym), repeat=model.reels)), dtype=np.int8)
    prob = np.prod(p[np.arange(model.reels), combos], axis=1)
    return float(np.dot(prob, line_pay(model, combos)))


def scatter_dist(model, strips):
    """P(k reels show a scatter). Scatters are at least `rows` apart, so a window
    holds at most one, and P(reel shows one) = n_scatter * rows / length."""
    dist = np.array([1.0])
    for s in strips:
        q = np.count_nonzero(s == model.S) * model.rows / len(s)
        dist = np.convolve(dist, [1 - q, q])
    return dist


def expected_free_spins(model, q):
    """Expected spins played in a free-spin round with retriggers and a spin cap."""
    @lru_cache(maxsize=None)
    def f(remaining, awarded):
        if remaining == 0:
            return 0.0
        can = awarded + model.fs_retrigger <= model.fs_max
        nxt_hit = (remaining - 1 + model.fs_retrigger, awarded + model.fs_retrigger) if can else (remaining - 1, awarded)
        return 1.0 + q * f(*nxt_hit) + (1 - q) * f(remaining - 1, awarded)
    return f(model.fs_awarded, model.fs_awarded)


def exact(model):
    base_line = exact_line_ev(model, model.base)
    sd = scatter_dist(model, model.base)
    base_scatter = float(np.dot(sd, model.scatter_pay))
    p_trigger = float(sd[model.trigger:].sum())
    fs_line = exact_line_ev(model, model.free)
    fsd = scatter_dist(model, model.free)
    fs_scatter = float(np.dot(fsd, model.scatter_pay))
    q_retrigger = float(fsd[model.trigger:].sum())
    n_spins = expected_free_spins(model, q_retrigger)
    per_spin = model.fs_mult * fs_line + fs_scatter
    bonus_ev = n_spins * per_spin  # Wald's identity: the spin count is a stopping time
    rtp = base_line + base_scatter + p_trigger * bonus_ev
    return {
        "rtp": rtp,
        "base_line": base_line,
        "base_scatter": base_scatter,
        "bonus": p_trigger * bonus_ev,
        "p_trigger": p_trigger,
        "bonus_ev": bonus_ev,
        "fs_expected_spins": n_spins,
        "fs_win_per_spin": per_spin,
        "fs_retrigger_per_spin": q_retrigger,
        "p_five_wild_line_base": float(np.prod(symbol_probs(model.base, model.n_sym)[:, model.W])),
        "p_five_wild_line_free": float(np.prod(symbol_probs(model.free, model.n_sym)[:, model.W])),
    }


# ---------------------------------------------------------------- simulation

def spin(model, strips, n, rng, mult=1):
    """n independent spins. Returns (win in total bets, scatter count)."""
    window = np.empty((n, model.reels, model.rows), dtype=np.int8)
    for r, strip in enumerate(strips):
        stops = rng.integers(0, len(strip), size=n)
        rows = (stops[:, None] + np.arange(model.rows)[None, :]) % len(strip)
        window[:, r, :] = strip[rows]
    line_syms = window[:, np.arange(model.reels)[None, :], model.lines]  # (n, lines, reels)
    line_win = line_pay(model, line_syms).sum(axis=1) / model.n_lines
    k = (window == model.S).any(axis=2).sum(axis=1)
    return mult * line_win + model.scatter_pay[k], k


def bonus_rounds(model, n, rng):
    """Plays n free-spin rounds in parallel. Returns (total win, spins played)."""
    remaining = np.full(n, model.fs_awarded)
    awarded = np.full(n, model.fs_awarded)
    total = np.zeros(n)
    played = np.zeros(n, dtype=np.int64)
    while True:
        idx = np.nonzero(remaining > 0)[0]
        if idx.size == 0:
            break
        win, k = spin(model, model.free, idx.size, rng, mult=model.fs_mult)
        total[idx] += win
        played[idx] += 1
        remaining[idx] -= 1
        re = (k >= model.trigger) & (awarded[idx] + model.fs_retrigger <= model.fs_max)
        remaining[idx[re]] += model.fs_retrigger
        awarded[idx[re]] += model.fs_retrigger
    return total, played


BUCKETS = [0, 1e-9, 1, 2, 5, 10, 20, 50, 100, 500, 1000, 5000, np.inf]
BUCKET_LABELS = ["0", "(0,1)", "[1,2)", "[2,5)", "[5,10)", "[10,20)", "[20,50)",
                 "[50,100)", "[100,500)", "[500,1000)", "[1000,5000)", "5000 (cap)"]


def simulate_game(model, spins, seed, batch=500_000):
    """Full game: base spins with any bonus they trigger, capped per round."""
    rng = np.random.default_rng(seed)
    acc = dict(n=0, s=0.0, s2=0.0, hits=0, triggers=0, line_scatter=0.0, bonus=0.0,
               max=0.0, cap_hits=0)
    hist = np.zeros(len(BUCKETS) - 1, dtype=np.int64)
    done = 0
    while done < spins:
        n = min(batch, spins - done)
        win, k = spin(model, model.base, n, rng)
        acc["line_scatter"] += win.sum()
        trig = np.nonzero(k >= model.trigger)[0]
        if trig.size:
            b, _ = bonus_rounds(model, trig.size, rng)
            acc["bonus"] += b.sum()
            win[trig] += b
            acc["triggers"] += trig.size
        acc["cap_hits"] += int(np.count_nonzero(win >= model.cap))
        win = np.minimum(win, model.cap)
        acc["n"] += n
        acc["s"] += win.sum()
        acc["s2"] += np.square(win).sum()
        acc["hits"] += int(np.count_nonzero(win > 0))
        acc["max"] = max(acc["max"], float(win.max()))
        hist += np.histogram(np.where(win >= model.cap, model.cap, win), bins=BUCKETS)[0]
        done += n
    n = acc["n"]
    mean = acc["s"] / n
    sd = np.sqrt(acc["s2"] / n - mean ** 2)
    return {
        "spins": n, "rtp": mean, "rtp_ci95": 1.96 * sd / np.sqrt(n), "sd_per_spin": sd,
        "hit_rate": acc["hits"] / n, "trigger_rate": acc["triggers"] / n,
        "base_part": acc["line_scatter"] / n, "bonus_part": acc["bonus"] / n,
        "max_win": acc["max"], "cap_hits": acc["cap_hits"], "hist": hist.tolist(),
    }


def simulate_stratified(model, base_spins, bonus_rounds_n, seed, batch=500_000):
    """Lower-variance RTP check: base game and bonus are simulated separately and
    combined with the exact trigger probability."""
    rng = np.random.default_rng(seed)
    s = s2 = 0.0
    done = 0
    while done < base_spins:
        n = min(batch, base_spins - done)
        win, _ = spin(model, model.base, n, rng)
        s += win.sum()
        s2 += np.square(win).sum()
        done += n
    base_mean = s / base_spins
    base_var = s2 / base_spins - base_mean ** 2
    b_tot = []
    b_played = []
    done = 0
    while done < bonus_rounds_n:
        n = min(batch // 10, bonus_rounds_n - done)
        b, played = bonus_rounds(model, n, rng)
        b_tot.append(b)
        b_played.append(played)
        done += n
    b = np.concatenate(b_tot)
    played = np.concatenate(b_played)
    p_trig = float(scatter_dist(model, model.base)[model.trigger:].sum())
    bonus_mean = b.mean()
    rtp = base_mean + p_trig * bonus_mean
    se = np.sqrt(base_var / base_spins + (p_trig ** 2) * b.var() / b.size)
    return {
        "rtp": rtp, "rtp_ci95": 1.96 * se, "base_part": base_mean, "bonus_ev": bonus_mean,
        "bonus_ev_ci95": 1.96 * b.std() / np.sqrt(b.size), "bonus_rounds": int(b.size),
        "bonus_max": float(b.max()), "bonus_p_over_500": float(np.mean(b >= 500)),
        "bonus_p_over_1000": float(np.mean(b >= 1000)), "fs_mean_spins": float(played.mean()),
    }
