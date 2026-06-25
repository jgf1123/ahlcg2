# -*- coding: utf-8 -*-
"""Estimate b_{C,D}(k) components from published-training-pool pivots.

Outputs b_c_d_estimate.json with re-fit hand prior, sparse gamma_k, alpha(D),
beta(C), rho(D) pre-era boost, tau(D) tail deficit, and assembled b[C][D][k].
"""

from __future__ import annotations

import argparse
import json
import pickle
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from arkham_canonical import MAX_CYCLE, CanonicalMapper
from arkham_popularity import ArkhamPopularityEngine, baseline_composition
from export_inv_cycle_card_cycle_pivots import build_pivot

# Cell / component shrinkage defaults
N_MIN_CELL = 30
LAMBDA_HAND = 80.0
LAMBDA_COMPONENT = 60.0
GAMMA_MIN_N = 40
GAMMA_THRESHOLD = 0.008
LEGACY_EPS_1 = 0.22
LEGACY_EPS_U = 0.76
LEGACY_NOVELTY = 0.02


def l1_distance(emp: dict[int, float], ref: dict[int, float]) -> float:
    keys = set(emp) | set(ref)
    return sum(abs(emp.get(k, 0.0) - ref.get(k, 0.0)) for k in keys)


def weighted_median(values: list[tuple[float, float]]) -> float:
    """values = [(value, weight), ...]"""
    if not values:
        return 0.0
    pairs = sorted(values, key=lambda x: x[0])
    total = sum(w for _, w in pairs)
    if total <= 0:
        return statistics.median(v for v, _ in pairs)
    half = total / 2.0
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= half:
            return value
    return pairs[-1][0]


def shrink(raw: float, n_eff: float, lam: float) -> float:
    return (n_eff / (n_eff + lam)) * raw if n_eff > 0 else 0.0


def hand_prior_vector(
    c: int,
    eps_1: float,
    eps_u: float,
    eps_c: float,
) -> dict[int, float]:
    """Structural + novelty at k=C; sums to 1 over k=1..C."""
    out: dict[int, float] = {}
    for k in range(1, c + 1):
        if k == c:
            out[k] = eps_c
        elif k == 1:
            out[k] = eps_u / c + eps_1
        else:
            out[k] = eps_u / c
    total = sum(out.values())
    if total <= 0:
        return out
    return {k: v / total for k, v in out.items()}


def legacy_hand_vector(c: int) -> dict[int, float]:
    return {k: baseline_composition(c, k) for k in range(1, c + 1)}


def is_pre_interior(k: int, d: int) -> bool:
    return 1 < k < d


def is_tail_interior(k: int, d: int, c: int) -> bool:
    return d < k < c


def fit_hand_per_c(
    mu: dict[int, dict[int, dict[int, float]]],
    weights: dict[tuple[int, int], float],
    deck_counts: dict[tuple[int, int], int],
) -> dict[int, dict[str, float]]:
    """Fit (eps_1, eps_u, eps_c) per Decklist.cycle C."""
    by_c: dict[int, list[tuple[int, int, int, float, float]]] = defaultdict(list)
    for c, d_map in mu.items():
        for d, k_map in d_map.items():
            if deck_counts.get((c, d), 0) < N_MIN_CELL:
                continue
            w_cell = weights.get((c, d), 0.0)
            for k, share in k_map.items():
                if k == c or k == d:
                    continue
                if is_pre_interior(k, d) or is_tail_interior(k, d, c):
                    continue
                by_c[c].append((c, d, k, share, w_cell))

    global_eps = _fit_eps_from_obs(
        [obs for obs_list in by_c.values() for obs in obs_list]
    )
    fitted: dict[int, dict[str, float]] = {}
    for c in range(1, MAX_CYCLE + 1):
        obs = by_c.get(c, [])
        if len(obs) < 5:
            fitted[c] = {
                "epsilon_1": global_eps["epsilon_1"],
                "epsilon_uniform": global_eps["epsilon_uniform"],
                "epsilon_C_novelty": global_eps["epsilon_C_novelty"],
                "n_obs": len(obs),
                "source": "global_fallback",
            }
            continue
        raw = _fit_eps_from_obs(obs)
        n_obs = len(obs)
        blend = n_obs / (n_obs + LAMBDA_HAND)
        e1 = blend * raw["epsilon_1"] + (1 - blend) * global_eps["epsilon_1"]
        eu = blend * raw["epsilon_uniform"] + (1 - blend) * global_eps["epsilon_uniform"]
        ec = blend * raw["epsilon_C_novelty"] + (1 - blend) * global_eps["epsilon_C_novelty"]
        struct = e1 + eu + ec
        fitted[c] = {
            "epsilon_1": e1 / struct,
            "epsilon_uniform": eu / struct,
            "epsilon_C_novelty": ec / struct,
            "n_obs": n_obs,
            "source": "per_C",
        }
    fitted["_global"] = {**global_eps, "n_obs": sum(len(v) for v in by_c.values())}
    return fitted


def _fit_eps_from_obs(
    obs: list[tuple[int, int, int, float, float]],
) -> dict[str, float]:
    if not obs:
        return {
            "epsilon_1": LEGACY_EPS_1,
            "epsilon_uniform": LEGACY_EPS_U,
            "epsilon_C_novelty": LEGACY_NOVELTY,
        }
    best = (1e18, LEGACY_EPS_1, LEGACY_EPS_U, LEGACY_NOVELTY)
    for eps_1 in [x / 100 for x in range(5, 45)]:
        for eps_u in [x / 100 for x in range(40, 90)]:
            for eps_c in [x / 1000 for x in range(5, 60)]:
                if eps_1 + eps_u + eps_c > 1.0:
                    continue
                err = 0.0
                for c, _d, k, share, w in obs:
                    pred = hand_prior_vector(c, eps_1, eps_u, eps_c).get(k, 0.0)
                    err += w * (share - pred) ** 2
                if err < best[0]:
                    best = (err, eps_1, eps_u, eps_c)
    return {
        "epsilon_1": best[1],
        "epsilon_uniform": best[2],
        "epsilon_C_novelty": best[3],
    }


@dataclass
class ModelParams:
    hand: dict[int, dict[str, float]] = field(default_factory=dict)
    gamma: dict[int, float] = field(default_factory=dict)
    alpha: dict[int, float] = field(default_factory=dict)
    beta: dict[int, float] = field(default_factory=dict)
    rho: dict[int, float] = field(default_factory=dict)
    tau: dict[int, float] = field(default_factory=dict)
    b_cd: dict[int, dict[int, dict[int, float]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(dict))
    )


def _hand_params(c: int, hand: dict) -> dict[str, float]:
    if c in hand:
        return hand[c]
    return hand["_global"]


def _hand_vec_for_c(c: int, hand: dict) -> dict[int, float]:
    hp = _hand_params(c, hand)
    return hand_prior_vector(
        c, hp["epsilon_1"], hp["epsilon_uniform"], hp.get("epsilon_C_novelty", 0.0)
    )


def base_mass(
    c: int,
    d: int,
    k: int,
    hand: dict,
) -> float:
    return _hand_vec_for_c(c, hand).get(k, 0.0)


def assemble_positive_mass(
    c: int,
    d: int,
    k: int,
    params: ModelParams,
) -> float:
    mass = base_mass(c, d, k, params.hand)
    mass += params.gamma.get(k, 0.0)
    if k == d:
        if c == d:
            mass += params.alpha.get(d, 0.0) + params.beta.get(c, 0.0)
        else:
            mass += params.alpha.get(d, 0.0)
    elif k == c:
        mass += params.beta.get(c, 0.0)
    if is_pre_interior(k, d):
        n_pre = max(d - 2, 1)
        mass += params.rho.get(d, 0.0) / n_pre
    if is_tail_interior(k, d, c):
        n_tail = max(c - d - 1, 1)
        mass += params.tau.get(d, 0.0) / n_tail
    return max(mass, 0.0)


def normalize_b_cd(
    c: int,
    d: int,
    params: ModelParams,
) -> dict[int, float]:
    masses = {k: assemble_positive_mass(c, d, k, params) for k in range(1, c + 1)}
    total = sum(masses.values())
    if total <= 0:
        return legacy_hand_vector(c)
    return {k: masses[k] / total for k in masses}


def build_mu_and_weights(
    pivot: dict[int, dict[int, dict[int, float]]],
    deck_counts: dict[tuple[int, int], int],
) -> tuple[
    dict[int, dict[int, dict[int, float]]],
    dict[tuple[int, int], float],
]:
    """Re-index pivot[D][C][k] -> mu[C][D][k] shares; cell weights from deck counts."""
    mu: dict[int, dict[int, dict[int, float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    weights: dict[tuple[int, int], float] = {}
    for d, c_map in pivot.items():
        for c, k_mass in c_map.items():
            total = sum(k_mass.values())
            if total <= 0:
                continue
            mu[c][d] = {k: k_mass[k] / total for k in k_mass}
            weights[(c, d)] = float(deck_counts.get((c, d), 0))
    return mu, weights


def estimate_gamma_clean(
    mu: dict[int, dict[int, dict[int, float]]],
    weights: dict[tuple[int, int], float],
    deck_counts: dict[tuple[int, int], int],
    hand: dict[int, dict[str, float]],
) -> dict[int, float]:
    residuals: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for c, d_map in mu.items():
        hv = _hand_vec_for_c(c, hand)
        for d, shares in d_map.items():
            if deck_counts.get((c, d), 0) < N_MIN_CELL:
                continue
            w = weights[(c, d)]
            for k, share in shares.items():
                if k in (c, d) or is_pre_interior(k, d) or is_tail_interior(k, d, c):
                    continue
                residuals[k].append((share - hv.get(k, 0.0), w))
    gamma: dict[int, float] = {}
    for k in range(1, MAX_CYCLE + 1):
        pairs = residuals.get(k, [])
        n_eff = sum(w for _, w in pairs)
        if n_eff < GAMMA_MIN_N:
            continue
        med = weighted_median(pairs)
        shrunk = shrink(med, n_eff, LAMBDA_COMPONENT)
        if abs(shrunk) >= GAMMA_THRESHOLD:
            gamma[k] = shrunk
    return gamma


def estimate_model(
    pivot: dict[int, dict[int, dict[int, float]]],
    deck_counts: dict[tuple[int, int], int],
) -> ModelParams:
    mu, weights = build_mu_and_weights(pivot, deck_counts)
    hand_fitted = fit_hand_per_c(mu, weights, deck_counts)
    hand: dict[int, dict[str, float]] = {
        c: v for c, v in hand_fitted.items() if c != "_global"
    }
    hand["_global"] = hand_fitted["_global"]

    gamma = estimate_gamma_clean(mu, weights, deck_counts, hand)

    params = ModelParams(hand=hand, gamma=gamma)

    # alpha(D) at k=D, C>=D, C!=D
    alpha_res: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for c, d_map in mu.items():
        for d, shares in d_map.items():
            if deck_counts.get((c, d), 0) < N_MIN_CELL or c < d or c == d:
                continue
            if d not in shares:
                continue
            w = weights[(c, d)]
            pred = (
                _hand_vec_for_c(c, hand).get(d, 0.0)
                + gamma.get(d, 0.0)
                + params.rho.get(d, 0.0)  # 0 initially
            )
            alpha_res[d].append((shares[d] - pred, w))
    for d, pairs in alpha_res.items():
        n_eff = sum(w for _, w in pairs)
        if n_eff < 15:
            continue
        params.alpha[d] = max(0.0, shrink(weighted_median(pairs), n_eff, LAMBDA_COMPONENT))

    # beta(C) at k=C
    beta_res: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for c, d_map in mu.items():
        for d, shares in d_map.items():
            if deck_counts.get((c, d), 0) < N_MIN_CELL or c not in shares:
                continue
            w = weights[(c, d)]
            pred = _hand_vec_for_c(c, hand).get(c, 0.0) + gamma.get(c, 0.0)
            if c == d:
                pred += params.alpha.get(d, 0.0)
            beta_res[c].append((shares[c] - pred, w))
    for c, pairs in beta_res.items():
        n_eff = sum(w for _, w in pairs)
        if n_eff < 15:
            continue
        raw = shrink(weighted_median(pairs), n_eff, LAMBDA_COMPONENT)
        hp = hand.get(c, hand["_global"])
        params.beta[c] = max(
            0.0,
            raw if raw > 0 else hp.get("epsilon_C_novelty", LEGACY_NOVELTY),
        )

    # rho(D): pre-era interior 1 < k < D
    rho_res: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for c, d_map in mu.items():
        for d, shares in d_map.items():
            if deck_counts.get((c, d), 0) < N_MIN_CELL or d < 3:
                continue
            w = weights[(c, d)]
            for k in range(2, d):
                if k not in shares:
                    continue
                pred = _hand_vec_for_c(c, hand).get(k, 0.0) + gamma.get(k, 0.0)
                rho_res[d].append((shares[k] - pred, w))
    for d, pairs in rho_res.items():
        n_eff = sum(w for _, w in pairs)
        if n_eff < 20:
            continue
        params.rho[d] = max(0.0, shrink(weighted_median(pairs), n_eff, LAMBDA_COMPONENT))

    # tau(D): tail interior D < k < C (expect negative -> store negative deficit)
    tau_res: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for c, d_map in mu.items():
        for d, shares in d_map.items():
            if deck_counts.get((c, d), 0) < N_MIN_CELL or c <= d + 1:
                continue
            w = weights[(c, d)]
            for k in range(d + 1, c):
                if k not in shares:
                    continue
                pred = (
                    _hand_vec_for_c(c, hand).get(k, 0.0)
                    + gamma.get(k, 0.0)
                    + params.alpha.get(d, 0.0) * 0  # not at k=D
                )
                tau_res[d].append((shares[k] - pred, w))
    for d, pairs in tau_res.items():
        n_eff = sum(w for _, w in pairs)
        if n_eff < 20:
            continue
        raw = shrink(weighted_median(pairs), n_eff, LAMBDA_COMPONENT)
        params.tau[d] = min(0.0, raw)  # deficit

    # Assemble b_{C,D}
    for c in range(1, MAX_CYCLE + 1):
        for d in range(1, MAX_CYCLE + 1):
            if c not in mu or d not in mu[c]:
                continue
            if deck_counts.get((c, d), 0) < N_MIN_CELL:
                continue
            params.b_cd[c][d] = normalize_b_cd(c, d, params)

    return params


def summarize_hand_vs_legacy(hand: dict[int, dict[str, float]]) -> None:
    print("\n=== Re-fit hand prior vs legacy (0.76/C + 0.22·I(k=1)) / 0.98 ===")
    print(f"{'C':>3}  {'eps_1':>6} {'eps_u':>6} {'eps_C':>6}  legacy_1  legacy_u  n_obs")
    g = hand["_global"]
    print(
        f"{'*':>3}  {g['epsilon_1']:6.3f} {g['epsilon_uniform']:6.3f} "
        f"{g.get('epsilon_C_novelty', LEGACY_NOVELTY):6.3f}  "
        f"{LEGACY_EPS_1:8.3f} {LEGACY_EPS_U:8.3f}  {g.get('n_obs', 0)}"
    )
    for c in range(1, MAX_CYCLE + 1):
        if c not in hand:
            continue
        hp = hand[c]
        print(
            f"{c:3d}  {hp['epsilon_1']:6.3f} {hp['epsilon_uniform']:6.3f} "
            f"{hp.get('epsilon_C_novelty', LEGACY_NOVELTY):6.3f}  "
            f"{LEGACY_EPS_1:8.3f} {LEGACY_EPS_U:8.3f}  {hp.get('n_obs', 0)}"
        )


def print_calibration(mu, deck_counts, params: ModelParams) -> None:
    legacy_l1: list[float] = []
    model_l1: list[float] = []
    for c, d_map in mu.items():
        for d, emp in d_map.items():
            if deck_counts.get((c, d), 0) < N_MIN_CELL:
                continue
            leg = legacy_hand_vector(c)
            mod = params.b_cd.get(c, {}).get(d, {})
            if not mod:
                continue
            legacy_l1.append(l1_distance(emp, leg))
            model_l1.append(l1_distance(emp, mod))
    if legacy_l1:
        print("\n=== L1 distance mu_{C,D} vs prior (cells with N >= N_MIN) ===")
        print(
            f"  legacy b_C:  mean={statistics.mean(legacy_l1):.4f}  "
            f"max={max(legacy_l1):.4f}"
        )
        print(
            f"  b_{{C,D}}:    mean={statistics.mean(model_l1):.4f}  "
            f"max={max(model_l1):.4f}"
        )


def export_json(params: ModelParams, path: str) -> None:
    hand_out = {
        str(c): v for c, v in params.hand.items() if isinstance(c, int)
    }
    if "_global" in params.hand:
        hand_out["_global"] = params.hand["_global"]
    payload = {
        "hand_per_C": hand_out,
        "gamma_k": {str(k): v for k, v in sorted(params.gamma.items())},
        "alpha_D": {str(d): v for d, v in sorted(params.alpha.items())},
        "beta_C": {str(c): v for c, v in sorted(params.beta.items())},
        "rho_D_pre_era": {str(d): v for d, v in sorted(params.rho.items())},
        "tau_D_tail": {str(d): v for d, v in sorted(params.tau.items())},
        "b_C_D": {
            str(c): {
                str(d): {str(k): round(v, 6) for k, v in sorted(kvec.items())}
                for d, kvec in sorted(dmap.items())
            }
            for c, dmap in sorted(params.b_cd.items())
        },
        "parameters": {
            "N_MIN_CELL": N_MIN_CELL,
            "LAMBDA_HAND": LAMBDA_HAND,
            "LAMBDA_COMPONENT": LAMBDA_COMPONENT,
            "GAMMA_THRESHOLD": GAMMA_THRESHOLD,
        },
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--card-json", default="card_json.pickle")
    parser.add_argument("--decklist-json", default="decklist_json.pickle")
    parser.add_argument("--taboo", default="taboo.json")
    parser.add_argument("--json", default="b_c_d_estimate.json")
    args = parser.parse_args()

    with open(args.card_json, "rb") as handle:
        cards = pickle.load(handle)
    with open(args.decklist_json, "rb") as handle:
        decklists = pickle.load(handle)
    with open(args.taboo, encoding="utf-8") as handle:
        taboo = json.load(handle)

    mapper = CanonicalMapper(cards, chapter=1)
    engine = ArkhamPopularityEngine(cards, mapper, taboo)
    prepared = engine.prepare_all(decklists)
    pivot, deck_counts = build_pivot(engine, prepared, mapper)
    mu, _weights = build_mu_and_weights(pivot, deck_counts)

    params = estimate_model(pivot, deck_counts)

    summarize_hand_vs_legacy(params.hand)
    print("\n=== Sparse gamma_k (|value| >= threshold after shrink) ===")
    for k, v in sorted(params.gamma.items()):
        print(f"  k={k:2d}: {v:+.4f}")
    if not params.gamma:
        print("  (none)")

    print("\n=== alpha(D) kit ridge at k=D ===")
    for d, v in sorted(params.alpha.items()):
        if v > 0.005:
            print(f"  D={d:2d}: {v:+.4f}")

    print("\n=== rho(D) pre-era boost (1 < k < D) ===")
    for d, v in sorted(params.rho.items()):
        if v > 0.003:
            print(f"  D={d:2d}: {v:+.4f}")

    print("\n=== tau(D) tail deficit (D < k < C) ===")
    for d, v in sorted(params.tau.items()):
        if v < -0.003:
            print(f"  D={d:2d}: {v:+.4f}")

    print_calibration(mu, deck_counts, params)
    export_json(params, args.json)
    print(f"\nWrote {args.json}")


if __name__ == "__main__":
    main()
