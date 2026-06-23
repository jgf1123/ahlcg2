# -*- coding: utf-8 -*-
"""Per-cycle copy-count distribution for one popularity option on one investigator."""

from __future__ import annotations

import argparse
import json
import pickle
from collections import defaultdict
from typing import Any

from arkham_canonical import CanonicalMapper
from arkham_popularity import ArkhamPopularityEngine, investigator_decks


def option_copy_count(slots: dict[str, int], canonical_id: str, upgrades: Any) -> int:
    return upgrades.count_option_in_slots(slots, canonical_id)


def analyze_option_by_cycle(
    engine: ArkhamPopularityEngine,
    prepared: list[Any],
    *,
    canonical_front: str,
    canonical_back: str,
    option_id: str,
) -> list[dict[str, Any]]:
    """Return rows: cycle, copies, deck_count, sum_weight."""
    inv_decks = investigator_decks(
        prepared,
        canonical_front,
        canonical_back,
        exclude_ignored=True,
        require_cycle=True,
    )
    user_weights = engine.assign_user_weights(prepared)
    cycle_weights = engine.assign_cycle_weights(inv_decks, user_weights)

    by_cycle: dict[int, dict[int, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"deck_count": 0, "sum_weight": 0.0})
    )
    for deck in inv_decks:
        if deck.cycle is None:
            continue
        copies = min(
            2,
            option_copy_count(deck.slots, option_id, engine.upgrades),
        )
        weight = engine.deck_weight(deck, user_weights, cycle_weights)
        bucket = by_cycle[deck.cycle][copies]
        bucket["deck_count"] += 1
        bucket["sum_weight"] += weight

    rows: list[dict[str, Any]] = []
    for cycle in sorted(by_cycle):
        cycle_total_count = 0
        cycle_total_weight = 0.0
        for copies in (0, 1, 2):
            stats = by_cycle[cycle].get(copies, {"deck_count": 0, "sum_weight": 0.0})
            cycle_total_count += stats["deck_count"]
            cycle_total_weight += stats["sum_weight"]
            rows.append(
                {
                    "cycle": cycle,
                    "copies": copies,
                    "deck_count": stats["deck_count"],
                    "sum_weight": stats["sum_weight"],
                }
            )
        rows.append(
            {
                "cycle": cycle,
                "copies": "total",
                "deck_count": cycle_total_count,
                "sum_weight": cycle_total_weight,
            }
        )
    return rows


def print_table(
    rows: list[dict[str, Any]],
    *,
    investigator_name: str,
    option_id: str,
    option_name: str,
) -> None:
    print(f"{investigator_name}: {option_name} ({option_id}) by Decklist.cycle")
    print(f"{'cycle':>6}  {'copies':>6}  {'deck_count':>11}  {'sum_weight':>12}")
    for row in rows:
        copies = row["copies"]
        copies_label = str(copies).rjust(6)
        print(
            f"{row['cycle']:>6}  {copies_label}  "
            f"{row['deck_count']:>11}  {row['sum_weight']:>12.4f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--front", default="08010", help="canonical_front")
    parser.add_argument("--back", default="08010", help="canonical_back")
    parser.add_argument("--option", default="01025", help="canonical_id to count")
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
    inv_card = cards.get(args.front) or {}
    option_card = cards.get(args.option) or {}
    rows = analyze_option_by_cycle(
        engine,
        prepared,
        canonical_front=args.front,
        canonical_back=args.back,
        option_id=args.option,
    )
    print_table(
        rows,
        investigator_name=inv_card.get("name", args.front),
        option_id=args.option,
        option_name=option_card.get("name", args.option),
    )


if __name__ == "__main__":
    main()
