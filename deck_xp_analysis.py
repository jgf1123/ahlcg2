# -*- coding: utf-8 -*-
"""Deck XP distribution and P2 / In the Thick of It breakdown."""

from __future__ import annotations

import argparse
import json
import pickle
import statistics
from collections import Counter

from arkham_canonical import CanonicalMapper
from arkham_popularity import (
    IN_THE_THICK_OF_IT_CANONICAL_ID,
    ArkhamPopularityEngine,
    slots_have_upgrade_cards,
)


def percentile(values: list[int], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(p * (len(ordered) - 1))
    return float(ordered[idx])


def summarize(label: str, values: list[int]) -> None:
    print(f"\n{label} (n={len(values)})")
    if not values:
        print("  (empty)")
        return
    nonzero_values = [v for v in values if v > 0]
    print(
        f"  min={min(nonzero_values)}  p10={percentile(nonzero_values, 0.10):.0f}  "
        f"p20={percentile(nonzero_values, 0.20):.0f}  "
        f"p30={percentile(nonzero_values, 0.30):.0f}  "
        f"p40={percentile(nonzero_values, 0.40):.0f}  "
        f"median={statistics.median(nonzero_values):.0f}  "
        f"p60={percentile(nonzero_values, 0.60):.0f}  "
        f"p70={percentile(nonzero_values, 0.70):.0f}  "
        f"p80={percentile(nonzero_values, 0.80):.0f}  "
        f"p90={percentile(nonzero_values, 0.90):.0f}  "
        f"p95={percentile(nonzero_values, 0.95):.0f}  max={max(nonzero_values)}"
    )
    print(f"  mean={statistics.mean(values):.1f}")
    buckets = Counter()
    for xp in values:
        if xp == 0:
            buckets["0"] += 1
        elif xp <= 5:
            buckets["01-05"] += 1
        elif xp <= 10:
            buckets["06-10"] += 1
        elif xp <= 15:
            buckets["11-15"] += 1
        elif xp <= 20:
            buckets["16-20"] += 1
        elif xp <= 25:
            buckets["21-25"] += 1
        elif xp <= 30:
            buckets["26-30"] += 1
        elif xp <= 35:
            buckets["31-35"] += 1
        elif xp <= 40:
            buckets["36-40"] += 1
        elif xp <= 45:
            buckets["41-45"] += 1
        elif xp <= 50:
            buckets["46-50"] += 1
        elif xp <= 55:
            buckets["51-55"] += 1
        elif xp <= 60:
            buckets["56-60"] += 1
        elif xp <= 65:
            buckets["61-65"] += 1
        elif xp <= 70:
            buckets["66-70"] += 1
        else:
            buckets["71+"] += 1
    print("  buckets:", dict(sorted(buckets.items())))


def cmd_distribution(engine: ArkhamPopularityEngine, raw: dict) -> None:
    chain_xp: list[int] = []
    standalone_xp: list[int] = []
    chain_charlie: list[int] = []
    standalone_charlie: list[int] = []

    for _did, deck in raw.items():
        if not deck:
            continue
        slots = engine.merge_slots_to_canonical(deck.get("slots") or {})
        xp = engine.decklist_xp(deck, slots)
        in_chain = bool(deck.get("previous_deck") or deck.get("next_deck"))
        if in_chain:
            chain_xp.append(xp)
        else:
            standalone_xp.append(xp)
        if deck.get("investigator_code") == "09018":
            if in_chain:
                chain_charlie.append(xp)
            else:
                standalone_charlie.append(xp)

    print("=== All decklists ===")
    summarize("In upgrade chain (has previous_deck or next_deck)", chain_xp)
    summarize("Not in upgrade chain", standalone_xp)

    print("\n=== Charlie Kane (09018) only ===")
    summarize("Charlie in upgrade chain", chain_charlie)
    summarize("Charlie standalone", standalone_charlie)

    print("\n=== Charlie high-XP standalone (>=50) ===")
    for did, deck in raw.items():
        if not deck or deck.get("investigator_code") != "09018":
            continue
        if deck.get("previous_deck") or deck.get("next_deck"):
            continue
        xp = engine.decklist_xp(deck)
        if xp >= 50:
            print(f"  {did}\t{xp}\t{deck.get('name', '')[:60]}")


def cmd_p2(engine: ArkhamPopularityEngine, raw: dict, cards: dict) -> None:
    no_upgrade_cards = 0
    itt_zero_with_upgrades = 0
    without_itt: dict[str, int] = {str(k): 0 for k in range(6)}
    without_itt["6+"] = 0
    with_itt: dict[str, int] = {str(k): 0 for k in range(6)}
    with_itt["6+"] = 0
    total = 0

    for deck in raw.values():
        if not deck:
            continue
        total += 1
        slots = engine.merge_slots_to_canonical(deck.get("slots") or {})
        taboo_id = engine._normalize_taboo_id(deck.get("taboo_id"))
        xp = engine.decklist_xp(deck, slots)
        upgrades = slots_have_upgrade_cards(slots, cards, taboo_id, engine.taboo)
        itt = slots.get(IN_THE_THICK_OF_IT_CANONICAL_ID, 0) > 0

        if not upgrades:
            no_upgrade_cards += 1
        if xp == 0 and upgrades and itt:
            itt_zero_with_upgrades += 1

        bucket = str(xp) if xp <= 5 else "6+"
        if itt:
            with_itt[bucket] += 1
        else:
            without_itt[bucket] += 1

    print(f"Total non-empty decklists: {total}")
    print()
    print("P2 context (all decklists)")
    print(
        f"  No 1+ XP cards in slots:     {no_upgrade_cards:6d}  "
        f"({100 * no_upgrade_cards / total:.1f}%)"
    )
    print(
        f"  deck.xp=0, has 1+ XP cards,  {itt_zero_with_upgrades:6d}  "
        f"({100 * itt_zero_with_upgrades / total:.1f}%)"
    )
    print("    with In the Thick of It (08125)")
    print()
    print(f"{'deck.xp':>8}  {'no ITT':>10}  {'with ITT':>10}")
    for k in range(6):
        key = str(k)
        print(f"{key:>8}  {without_itt[key]:10d}  {with_itt[key]:10d}")
    print(f"{'6+':>8}  {without_itt['6+']:10d}  {with_itt['6+']:10d}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deck XP analysis.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("distribution", help="XP distribution by upgrade chain.")
    sub.add_parser("p2", help="P2 / In the Thick of It breakdown.")
    args = parser.parse_args()

    cards = pickle.load(open("card_json.pickle", "rb"))
    raw = pickle.load(open("decklist_json.pickle", "rb"))
    taboo = json.load(open("taboo.json", encoding="utf-8"))
    engine = ArkhamPopularityEngine(cards, CanonicalMapper(cards), taboo)

    if args.command == "distribution":
        cmd_distribution(engine, raw)
    else:
        cmd_p2(engine, raw, cards)


if __name__ == "__main__":
    main()
