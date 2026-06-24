# -*- coding: utf-8 -*-
"""Per-investigator Decklist.cycle distribution (EDA)."""

from __future__ import annotations

import argparse
import json
import pickle
from collections import defaultdict

from arkham_canonical import CanonicalMapper
from arkham_popularity import ArkhamPopularityEngine


def estimate_cycle_decklist_id_bounds(
    rows: list[dict],
) -> list[dict]:
    """Min decklist_id per Decklist.cycle across all investigators."""
    by_cycle: dict[int, list] = defaultdict(list)
    for row in rows:
        decklist_cycle = row["decklist_cycle"]
        if row["min_decklist_id"] is not None:
            by_cycle[decklist_cycle].append(row["min_decklist_id"])
        if row["max_decklist_id"] is not None:
            by_cycle[decklist_cycle].append(row["max_decklist_id"])
    return [
        {
            "decklist_cycle": cycle,
            "min_decklist_id": min(ids),
            "max_decklist_id": max(ids),
        }
        for cycle, ids in sorted(by_cycle.items())
    ]


def print_investigator_table(
    rows: list[dict],
    *,
    canonical_front: str,
    cards: dict,
) -> None:
    inv_name = (cards.get(canonical_front) or {}).get("name", canonical_front)
    subset = [r for r in rows if r["canonical_front"] == canonical_front]
    if not subset:
        print(f"No rows for {inv_name} ({canonical_front})")
        return
    total_count = sum(r["deck_count"] for r in subset)
    total_weight = sum(r["sum_weight"] for r in subset)
    print(f"\n=== {inv_name} ({canonical_front}) inv_cycle={subset[0].get('inv_cycle')} ===")
    print(f"{'cycle':>5}  {'count':>6}  {'%cnt':>7}  {'weight':>10}  {'%wgt':>7}  {'id range'}")
    for row in sorted(subset, key=lambda r: r["decklist_cycle"]):
        pct_cnt = 100.0 * row["deck_count"] / total_count if total_count else 0.0
        pct_wgt = 100.0 * row["sum_weight"] / total_weight if total_weight else 0.0
        id_range = f"{row['min_decklist_id']}..{row['max_decklist_id']}"
        print(
            f"{row['decklist_cycle']:5d}  {row['deck_count']:6d}  {pct_cnt:6.1f}%  "
            f"{row['sum_weight']:10.4f}  {pct_wgt:6.1f}%  {id_range}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--front", help="canonical_front (optional; default all)")
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
    rows = engine.investigator_decklist_cycle_distribution(prepared)

    print("Estimated decklist_id bounds per Decklist.cycle (all investigators):")
    for row in estimate_cycle_decklist_id_bounds(rows):
        print(
            f"  cycle {row['decklist_cycle']:2d}: "
            f"id {row['min_decklist_id']} .. {row['max_decklist_id']}"
        )

    if args.front:
        print_investigator_table(rows, canonical_front=args.front, cards=cards)
    else:
        fronts = sorted({r["canonical_front"] for r in rows})
        for front in fronts:
            print_investigator_table(rows, canonical_front=front, cards=cards)


if __name__ == "__main__":
    main()
