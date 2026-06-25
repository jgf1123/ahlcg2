# -*- coding: utf-8 -*-
"""Check if investigator k-spike persists across C>=k for fixed inv_cycle D."""

from __future__ import annotations

import json
import pickle
from collections import defaultdict

from arkham_canonical import CanonicalMapper, investigator_requirement_card_ids
from arkham_popularity import ArkhamPopularityEngine, InvCycleIndex, investigator_decks


def investigator_k_by_deck_cycle(
    engine, prepared, cards, mapper, user_weights, cycle_weights, inv_index,
    *, inv_cycle: int, canonical_front: str, k: int,
) -> None:
    name = (cards.get(canonical_front) or {}).get("name", canonical_front)
    inv_decks = [
        d for d in prepared
        if not d.is_ignore and d.cycle is not None
        and d.canonical_front == canonical_front
        and mapper.cycle_for_slot(d.canonical_front) == inv_cycle
    ]
    print(f"\n{name} ({canonical_front}) inv_cycle={inv_cycle}, card cycle k={k}")
    exclude = investigator_requirement_card_ids(cards, canonical_front, mapper.to_canonical)
    by_c: dict[int, dict] = defaultdict(lambda: {"decks": 0, "k_mass": 0.0, "total": 0.0})
    for deck in inv_decks:
        c = deck.cycle
        if c is None or c < k:
            continue
        w = engine.investigator_deck_weight(deck, user_weights, cycle_weights, inv_index)
        if not w:
            continue
        by_c[c]["decks"] += 1
        for cid, copies in deck.slots.items():
            if cid in exclude:
                continue
            card = cards.get(cid)
            if card and card.get("subtype_code") == "basicweakness":
                continue
            kk = mapper.cycle_for_slot(cid)
            if kk is None or kk > c:
                continue
            mass = w * copies
            by_c[c]["total"] += mass
            if kk == k:
                by_c[c]["k_mass"] += mass
    for c in sorted(by_c):
        d = by_c[c]
        share = d["k_mass"] / d["total"] if d["total"] else 0
        print(f"  C={c:2d}: {d['decks']:4d} decks  share(k={k})={share:.3f}")


def top_cards_at_k(
    engine, prepared, cards, mapper, user_weights, cycle_weights, inv_index,
    *, inv_cycle: int, canonical_front: str, deck_cycle: int, k: int, n: int = 8,
) -> None:
    name = (cards.get(canonical_front) or {}).get("name", canonical_front)
    print(f"\nTop cycle-{k} cards: {name} at C={deck_cycle}")
    exclude = investigator_requirement_card_ids(cards, canonical_front, mapper.to_canonical)
    counts: dict[str, float] = defaultdict(float)
    for deck in prepared:
        if deck.is_ignore or deck.cycle != deck_cycle:
            continue
        if deck.canonical_front != canonical_front:
            continue
        if mapper.cycle_for_slot(deck.canonical_front) != inv_cycle:
            continue
        w = engine.investigator_deck_weight(deck, user_weights, cycle_weights, inv_index)
        if not w:
            continue
        for cid, copies in deck.slots.items():
            if cid in exclude:
                continue
            if mapper.cycle_for_slot(cid) != k:
                continue
            counts[cid] += w * copies
    for cid, mass in sorted(counts.items(), key=lambda x: -x[1])[:n]:
        card = cards.get(cid) or {}
        print(f"  {card.get('name', cid)} ({cid}): {mass:.2f}")


def main() -> None:
    with open("card_json.pickle", "rb") as handle:
        cards = pickle.load(handle)
    with open("decklist_json.pickle", "rb") as handle:
        decklists = pickle.load(handle)
    with open("taboo.json", encoding="utf-8") as handle:
        taboo = json.load(handle)

    mapper = CanonicalMapper(cards)
    engine = ArkhamPopularityEngine(cards, mapper, taboo)
    prepared = engine.prepare_all(decklists)
    user_weights = engine.assign_user_weights(prepared)
    active = [d for d in prepared if not d.is_ignore and d.cycle is not None]
    cycle_weights = engine.assign_cycle_weights(active, user_weights)
    inv_index = InvCycleIndex(mapper, active) if engine.bias_compensation else None

    kw = dict(
        engine=engine, prepared=prepared, cards=cards, mapper=mapper,
        user_weights=user_weights, cycle_weights=cycle_weights, inv_index=inv_index,
    )

    # Patrice k=4 ridge at D=6
    investigator_k_by_deck_cycle(**kw, inv_cycle=6, canonical_front="06005", k=4)
    top_cards_at_k(**kw, inv_cycle=6, canonical_front="06005", deck_cycle=9, k=4)

    # Gloria k=5 at D=12
    investigator_k_by_deck_cycle(**kw, inv_cycle=12, canonical_front="11014", k=5)
    top_cards_at_k(**kw, inv_cycle=12, canonical_front="11014", deck_cycle=8, k=5)

    # Charlie Kane k=6 at D=10
    investigator_k_by_deck_cycle(**kw, inv_cycle=10, canonical_front="09018", k=6)
    top_cards_at_k(**kw, inv_cycle=10, canonical_front="09018", deck_cycle=8, k=6)

    # Jacqueline k=4 at D=7 (sparse C=6 only)
    investigator_k_by_deck_cycle(**kw, inv_cycle=7, canonical_front="60401", k=4)


if __name__ == "__main__":
    main()
