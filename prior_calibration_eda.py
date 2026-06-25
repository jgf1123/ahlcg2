# -*- coding: utf-8 -*-
"""Compare empirical slot shares to spec prior b_C(k) by (Decklist.cycle, inv_cycle)."""

from __future__ import annotations

import json
import pickle
import sys
from collections import defaultdict

from arkham_canonical import MAX_CYCLE, CanonicalMapper
from arkham_popularity import (
    ArkhamPopularityEngine,
    InvCycleIndex,
    baseline_composition,
)


def prior_vector(deck_cycle: int, max_k: int = MAX_CYCLE) -> dict[int, float]:
    return {
        k: baseline_composition(deck_cycle, k)
        for k in range(1, max_k + 1)
        if k <= deck_cycle and baseline_composition(deck_cycle, k) > 0
    }


def l1_distance(emp: dict[int, float], prior: dict[int, float]) -> float:
    keys = set(emp) | set(prior)
    return sum(abs(emp.get(k, 0.0) - prior.get(k, 0.0)) for k in keys)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    with open("decklist_json.pickle", "rb") as handle:
        decklists = pickle.load(handle)
    with open("card_json.pickle", "rb") as handle:
        cards = pickle.load(handle)
    with open("taboo.json", encoding="utf-8") as handle:
        taboo = json.load(handle)

    mapper = CanonicalMapper(cards, chapter=1)
    engine = ArkhamPopularityEngine(cards, mapper, taboo)
    prepared = engine.prepare_all(decklists)
    active = engine.training_pool_decks(prepared)
    user_weights = engine.assign_user_weights(prepared)
    cycle_weights = engine.assign_cycle_weights(active, user_weights)
    inv_index = (
        InvCycleIndex(mapper, active) if engine.bias_compensation else None
    )

    # pivot[C][D][k] = weighted slot copies
    pivot: dict[int, dict[int, dict[int, float]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(float))
    )
    cell_decks: dict[tuple[int, int], int] = defaultdict(int)

    for deck in active:
        c = deck.cycle
        d = mapper.cycle_for_slot(deck.canonical_front)
        if d is None:
            continue
        weight = engine.investigator_deck_weight(
            deck, user_weights, cycle_weights, inv_index
        )
        if not weight:
            continue
        cell_decks[(c, d)] += 1
        for canonical_id, copies in deck.slots.items():
            k = mapper.cycle_for_slot(canonical_id)
            if k is None or k > c:
                continue
            pivot[c][d][k] += weight * copies

    print("Prior b_C(k) = (0.76/C + 0.22·I(k=1)) / 0.98")
    print("Empirical: weighted slot-copy shares; k > C excluded.\n")

    # --- Fixed C, vary D ---
    print("=" * 72)
    print("A. Fixed Decklist.cycle = C — does b_C(k) hold as inv_cycle D varies?")
    print("=" * 72)
    print(
        f"{'C':>3}  {'D':>3}  {'decks':>6}  "
        f"{'core emp':>8}  {'core pri':>8}  {'L1':>6}  note"
    )
    by_c_l1: dict[int, list[float]] = defaultdict(list)
    by_c_core_gap: dict[int, list[float]] = defaultdict(list)

    for c in sorted(pivot):
        prior = prior_vector(c)
        core_pri = prior.get(1, 0.0)
        for d in sorted(pivot[c]):
            total = sum(pivot[c][d].values())
            if total <= 0:
                continue
            emp = {k: pivot[c][d][k] / total for k in pivot[c][d]}
            core_emp = emp.get(1, 0.0)
            dist = l1_distance(emp, prior)
            by_c_l1[c].append(dist)
            by_c_core_gap[c].append(core_emp - core_pri)
            note = ""
            if dist > 0.15:
                note = "poor fit"
            elif dist > 0.10:
                note = "moderate"
            print(
                f"{c:3d}  {d:3d}  {cell_decks[(c, d)]:6d}  "
                f"{100 * core_emp:7.1f}%  {100 * core_pri:7.1f}%  "
                f"{dist:5.3f}  {note}"
            )
        if by_c_l1[c]:
            print(
                f"  >> C={c}: L1 mean={sum(by_c_l1[c])/len(by_c_l1[c]):.3f} "
                f"max={max(by_c_l1[c]):.3f}; "
                f"core gap mean={100*sum(by_c_core_gap[c])/len(by_c_core_gap[c]):+.1f}pp\n"
            )

    # --- Fixed D, vary C ---
    print("=" * 72)
    print("B. Fixed inv_cycle = D — does b_C(k) hold as Decklist.cycle C varies?")
    print("   (prior uses each row's C, not D)")
    print("=" * 72)
    print(
        f"{'D':>3}  {'C':>3}  {'decks':>6}  "
        f"{'core emp':>8}  {'core pri':>8}  {'L1':>6}  note"
    )
    by_d_l1: dict[int, list[float]] = defaultdict(list)

    # Re-index by D then C
    by_d: dict[int, dict[int, dict[int, float]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(float))
    )
    for c, d_map in pivot.items():
        for d, k_map in d_map.items():
            for k, v in k_map.items():
                by_d[d][c][k] += v

    for d in sorted(by_d):
        for c in sorted(by_d[d]):
            if c < d:
                pass  # still show — low C with high D investigator is valid
            total = sum(by_d[d][c].values())
            if total <= 0:
                continue
            prior = prior_vector(c)
            emp = {k: by_d[d][c][k] / total for k in by_d[d][c]}
            core_emp = emp.get(1, 0.0)
            core_pri = prior.get(1, 0.0)
            dist = l1_distance(emp, prior)
            by_d_l1[d].append(dist)
            note = ""
            if c < d and dist < 0.08:
                note = "C<D, ok"
            elif c >= d and dist > 0.12:
                note = "C≥D, poor"
            print(
                f"{d:3d}  {c:3d}  {cell_decks[(c, d)]:6d}  "
                f"{100 * core_emp:7.1f}%  {100 * core_pri:7.1f}%  "
                f"{dist:5.3f}  {note}"
            )
        if by_d_l1[d]:
            print(
                f"  >> D={d}: L1 mean={sum(by_d_l1[d])/len(by_d_l1[d]):.3f} "
                f"max={max(by_d_l1[d]):.3f}\n"
            )

    # --- Marginal C only (pool over D) vs prior ---
    print("=" * 72)
    print("C. Marginal by C only (pool over all D) vs b_C(k)")
    print("=" * 72)
    print(f"{'C':>3}  {'core emp':>8}  {'core pri':>8}  {'L1':>6}")
    for c in sorted(pivot):
        pooled: dict[int, float] = defaultdict(float)
        for d in pivot[c]:
            for k, v in pivot[c][d].items():
                pooled[k] += v
        total = sum(pooled.values())
        if not total:
            continue
        emp = {k: pooled[k] / total for k in pooled}
        prior = prior_vector(c)
        print(
            f"{c:3d}  {100 * emp.get(1, 0):7.1f}%  "
            f"{100 * prior.get(1, 0):7.1f}%  "
            f"{l1_distance(emp, prior):5.3f}"
        )

    # --- Marginal D only (pool over C) — no single prior; show core & tail ---
    print("\n" + "=" * 72)
    print("D. Marginal by inv_cycle D (pool over all C) — no b_D(k) prior in spec")
    print("=" * 72)
    print(f"{'D':>3}  {'core k=1':>8}  {'k=D':>8}  {'k>D tail':>8}  {'decks':>6}")
    for d in sorted(by_d):
        pooled: dict[int, float] = defaultdict(float)
        for c in by_d[d]:
            for k, v in by_d[d][c].items():
                pooled[k] += v
        total = sum(pooled.values())
        if not total:
            continue
        emp = {k: pooled[k] / total for k in pooled}
        tail = sum(v for k, v in emp.items() if k > d)
        deck_n = sum(cell_decks[(c, d)] for c in by_d[d])
        print(
            f"{d:3d}  {100 * emp.get(1, 0):7.1f}%  "
            f"{100 * emp.get(d, 0):7.1f}%  {100 * tail:7.1f}%  {deck_n:6d}"
        )


if __name__ == "__main__":
    main()
