# -*- coding: utf-8 -*-
"""Per-investigator breakdown for (inv_cycle D, Decklist.cycle C) anomaly cells."""

from __future__ import annotations

import argparse
import json
import pickle
from collections import defaultdict

from arkham_canonical import CanonicalMapper, investigator_requirement_card_ids
from arkham_popularity import ArkhamPopularityEngine, InvCycleIndex


def cell_breakdown(
    engine: ArkhamPopularityEngine,
    prepared: list,
    cards: dict,
    mapper: CanonicalMapper,
    *,
    user_weights,
    cycle_weights,
    inv_index,
    d: int,
    c: int,
    k_focus: int | None = None,
) -> None:
    active = [x for x in prepared if not x.is_ignore and x.cycle is not None]
    print(f"=== inv_cycle D={d}, Decklist.cycle C={c} ===")
    by_inv: dict[str, dict] = defaultdict(
        lambda: {"decks": 0, "weight": 0.0, "k": defaultdict(float)}
    )
    for deck in active:
        inv_d = mapper.cycle_for_slot(deck.canonical_front)
        if inv_d != d or deck.cycle != c:
            continue
        weight = engine.investigator_deck_weight(
            deck, user_weights, cycle_weights, inv_index
        )
        if not weight:
            continue
        front = deck.canonical_front
        by_inv[front]["decks"] += 1
        by_inv[front]["weight"] += weight
        exclude = investigator_requirement_card_ids(
            cards, front, mapper.to_canonical
        )
        for canonical_id, copies in deck.slots.items():
            if canonical_id in exclude:
                continue
            card = cards.get(canonical_id)
            if card and card.get("subtype_code") == "basicweakness":
                continue
            k = mapper.cycle_for_slot(canonical_id)
            if k is None or k > c:
                continue
            by_inv[front]["k"][k] += weight * copies

    for front, data in sorted(by_inv.items(), key=lambda x: -x[1]["weight"]):
        total = sum(data["k"].values())
        if total <= 0:
            continue
        name = (cards.get(front) or {}).get("name", front)
        shares = {k: data["k"][k] / total for k in sorted(data["k"])}
        focus = ""
        if k_focus is not None:
            focus = f" k{k_focus}={shares.get(k_focus, 0.0):.3f}"
        print(
            f"  {name} ({front}): {data['decks']} decks, "
            f"w={data['weight']:.1f}{focus}"
        )
        if data["decks"] <= 8 or k_focus is not None:
            top = sorted(shares.items(), key=lambda x: -x[1])[:8]
            print(
                "    top k:",
                ", ".join(f"k{kk}={v:.3f}" for kk, v in top),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        nargs="*",
        default=[
            "7,6,4",
            "10,8,6",
            "10,6,5",
            "12,8,5",
            "6,9,4",
            "7,7,7",
        ],
        help="D,C,k_focus triples",
    )
    args = parser.parse_args()

    with open("card_json.pickle", "rb") as handle:
        cards = pickle.load(handle)
    with open("decklist_json.pickle", "rb") as handle:
        decklists = pickle.load(handle)
    with open("taboo.json", encoding="utf-8") as handle:
        taboo = json.load(handle)

    mapper = CanonicalMapper(cards, chapter=1)
    engine = ArkhamPopularityEngine(cards, mapper, taboo)
    prepared = engine.prepare_all(decklists)
    user_weights = engine.assign_user_weights(prepared)
    active = [d for d in prepared if not d.is_ignore and d.cycle is not None]
    cycle_weights = engine.assign_cycle_weights(active, user_weights)
    inv_index = (
        InvCycleIndex(mapper, active) if engine.bias_compensation else None
    )

    for case in args.cases:
        parts = [int(x) for x in case.split(",")]
        d, c = parts[0], parts[1]
        k_focus = parts[2] if len(parts) > 2 else None
        cell_breakdown(
            engine,
            prepared,
            cards,
            mapper,
            user_weights=user_weights,
            cycle_weights=cycle_weights,
            inv_index=inv_index,
            d=d,
            c=c,
            k_focus=k_focus,
        )
        print()


if __name__ == "__main__":
    main()
