# -*- coding: utf-8 -*-
"""EDA: inv_cycle × CanonicalCard.cycle slot-copy composition per investigator."""

from __future__ import annotations

import argparse
import csv
import json
import pickle
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from arkham_canonical import MAX_CYCLE, CanonicalMapper, investigator_requirement_card_ids
from arkham_popularity import (
    ArkhamPopularityEngine,
    InvCycleIndex,
    investigator_decks,
)


def _exclude_ids(
    mapper: CanonicalMapper,
    cards: dict[str, dict[str, Any]],
    canonical_front: str,
) -> set[str]:
    return investigator_requirement_card_ids(
        cards, canonical_front, mapper.to_canonical
    )


def weighted_card_cycle_counts(
    deck_slots: dict[str, int],
    weight: float,
    *,
    mapper: CanonicalMapper,
    cards: dict[str, dict[str, Any]],
    exclude: set[str],
    pivot: dict[int, float],
) -> float:
    """Add weighted slot copies by card cycle; return total weighted copies."""
    total = 0.0
    for canonical_id, copies in deck_slots.items():
        if canonical_id in exclude:
            continue
        card = cards.get(canonical_id)
        if card is not None and card.get("subtype_code") == "basicweakness":
            continue
        card_cycle = mapper.cycle_for_slot(canonical_id)
        if card_cycle is None:
            continue
        weighted = weight * copies
        pivot[card_cycle] += weighted
        total += weighted
    return total


def analyze_investigators(
    engine: ArkhamPopularityEngine,
    prepared: list[Any],
    *,
    cards: dict[str, dict[str, Any]],
    mapper: CanonicalMapper,
) -> list[dict[str, Any]]:
    user_weights = engine.assign_user_weights(prepared)
    active = engine.training_pool_decks(prepared)
    cycle_weights = engine.assign_cycle_weights(active, user_weights)
    inv_index = (
        InvCycleIndex(mapper, active) if engine.bias_compensation else None
    )

    tuples = sorted(
        {
            (d.canonical_front, d.canonical_back)
            for d in active
        }
    )
    rows: list[dict[str, Any]] = []
    for canonical_front, canonical_back in tuples:
        inv_cycle = mapper.cycle_for_slot(canonical_front)
        if inv_cycle is None:
            continue
        inv_decks = investigator_decks(
            active, canonical_front, canonical_back
        )
        if not inv_decks:
            continue
        exclude = _exclude_ids(mapper, cards, canonical_front)
        pivot: dict[int, float] = defaultdict(float)
        deck_count = 0
        total_deck_weight = 0.0
        for deck in inv_decks:
            weight = engine.investigator_deck_weight(
                deck, user_weights, cycle_weights, inv_index
            )
            if not weight:
                continue
            deck_count += 1
            total_deck_weight += weight
            weighted_card_cycle_counts(
                deck.slots,
                weight,
                mapper=mapper,
                cards=cards,
                exclude=exclude,
                pivot=pivot,
            )
        slot_weight_total = sum(pivot.values())
        if slot_weight_total <= 0:
            continue
        shares = {k: pivot[k] / slot_weight_total for k in pivot}
        tail_mass = sum(share for k, share in shares.items() if k > inv_cycle)
        own_era = sum(share for k, share in shares.items() if k <= inv_cycle)
        inv_card = cards.get(canonical_front) or {}
        rows.append(
            {
                "canonical_front": canonical_front,
                "canonical_back": canonical_back,
                "investigator_name": inv_card.get("name", canonical_front),
                "inv_cycle": inv_cycle,
                "deck_count": deck_count,
                "total_weight": total_deck_weight,
                "slot_weight_total": slot_weight_total,
                "shares": shares,
                "tail_mass": tail_mass,
                "own_era_mass": own_era,
            }
        )
    return rows


def group_by_inv_cycle(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Weighted-mean card-cycle shares across investigators per inv_cycle."""
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[row["inv_cycle"]].append(row)

    grouped: list[dict[str, Any]] = []
    for inv_cycle in sorted(buckets):
        members = buckets[inv_cycle]
        weight_sum = sum(r["total_weight"] for r in members)
        if not weight_sum:
            continue
        shares: dict[int, float] = defaultdict(float)
        for row in members:
            frac = row["total_weight"] / weight_sum
            for k, share in row["shares"].items():
                shares[k] += frac * share
        tail = sum(share for k, share in shares.items() if k > inv_cycle)
        grouped.append(
            {
                "inv_cycle": inv_cycle,
                "investigator_count": len(members),
                "deck_count": sum(r["deck_count"] for r in members),
                "total_weight": weight_sum,
                "shares": dict(shares),
                "tail_mass": tail,
            }
        )
    return grouped


def print_share_row(
    label: str,
    shares: dict[int, float],
    *,
    inv_cycle: int | None = None,
    tail_mass: float | None = None,
    max_cycle: int = MAX_CYCLE,
) -> None:
    cycles = [k for k in range(1, max_cycle + 1) if shares.get(k, 0) > 0.001]
    if not cycles:
        cycles = list(range(1, min(max_cycle, 12) + 1))
    header = f"{'k':>3}" + "".join(f"{k:6d}" for k in cycles)
    cells = f"{'%':>3}" + "".join(
        f"{100 * shares.get(k, 0):5.1f}%" for k in cycles
    )
    tail = tail_mass
    if tail is None and inv_cycle is not None:
        tail = sum(shares.get(k, 0) for k in shares if k > inv_cycle)
    print(f"\n=== {label} ===")
    print(header)
    print(cells)
    if tail is not None:
        print(f"  tail (k > inv_cycle): {100 * tail:.1f}%")


def print_group_summary(grouped: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 72)
    print("GROUP BY inv_cycle (weight-averaged across investigators)")
    print("=" * 72)
    print(
        f"{'I':>3}  {'#inv':>4}  {'decks':>6}  {'tail%':>6}  "
        f"{'k=1%':>6}  {'k=I%':>6}  {'k>I%':>6}"
    )
    for row in grouped:
        inv_cycle = row["inv_cycle"]
        shares = row["shares"]
        own = shares.get(inv_cycle, 0)
        tail = row["tail_mass"]
        core = shares.get(1, 0)
        print(
            f"{inv_cycle:3d}  {row['investigator_count']:4d}  "
            f"{row['deck_count']:6d}  {100 * tail:5.1f}%  "
            f"{100 * core:5.1f}%  {100 * own:5.1f}%  {100 * tail:5.1f}%"
        )
        print_share_row(
            f"inv_cycle = {inv_cycle} (n={row['investigator_count']} investigators)",
            shares,
            inv_cycle=inv_cycle,
            tail_mass=tail,
        )


def print_investigator_summary(rows: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 72)
    print("PER INVESTIGATOR (sorted by tail mass descending)")
    print("=" * 72)
    print(
        f"{'inv':>3}  {'tail%':>6}  {'k=1%':>6}  {'decks':>6}  "
        f"name / canonical_front"
    )
    for row in sorted(rows, key=lambda r: r["tail_mass"], reverse=True):
        shares = row["shares"]
        print(
            f"{row['inv_cycle']:3d}  {100 * row['tail_mass']:5.1f}%  "
            f"{100 * shares.get(1, 0):5.1f}%  {row['deck_count']:6d}  "
            f"{row['investigator_name']} ({row['canonical_front']})"
        )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "investigator_name",
        "canonical_front",
        "canonical_back",
        "inv_cycle",
        "deck_count",
        "total_weight",
        "tail_mass",
        "own_era_mass",
    ] + [f"share_k{k}" for k in range(1, MAX_CYCLE + 1)]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = {
                "investigator_name": row["investigator_name"],
                "canonical_front": row["canonical_front"],
                "canonical_back": row["canonical_back"],
                "inv_cycle": row["inv_cycle"],
                "deck_count": row["deck_count"],
                "total_weight": row["total_weight"],
                "tail_mass": row["tail_mass"],
                "own_era_mass": row["own_era_mass"],
            }
            for k in range(1, MAX_CYCLE + 1):
                out[f"share_k{k}"] = row["shares"].get(k, 0.0)
            writer.writerow(out)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--front", help="canonical_front for detail pivot")
    parser.add_argument(
        "--csv",
        metavar="PATH",
        help="write per-investigator shares to CSV",
    )
    parser.add_argument("--card-json", default="card_json.pickle")
    parser.add_argument("--decklist-json", default="decklist_json.pickle")
    parser.add_argument("--taboo", default="taboo.json")
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
    rows = analyze_investigators(
        engine, prepared, cards=cards, mapper=mapper
    )

    print(
        "Slot-copy shares by CanonicalCard.cycle (player choices; "
        "excludes signatures + random basic weaknesses)."
    )
    print(f"Investigators with defined inv_cycle: {len(rows)}")

    print_investigator_summary(rows)
    print_group_summary(group_by_inv_cycle(rows))

    if args.front:
        match = next(
            (r for r in rows if r["canonical_front"] == args.front),
            None,
        )
        if match is None:
            print(f"\nNo data for canonical_front={args.front}")
        else:
            print_share_row(
                f"{match['investigator_name']} ({args.front}) "
                f"inv_cycle={match['inv_cycle']}",
                match["shares"],
                inv_cycle=match["inv_cycle"],
                tail_mass=match["tail_mass"],
            )

    if args.csv:
        write_csv(Path(args.csv), rows)
        print(f"\nWrote {args.csv}")


if __name__ == "__main__":
    main()
