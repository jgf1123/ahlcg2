# -*- coding: utf-8 -*-
"""Gloria Goldberg: front printing vs signature pairing."""

from __future__ import annotations

import json
import pickle
from collections import Counter, defaultdict

from arkham_canonical import CanonicalMapper
from arkham_popularity import ArkhamPopularityEngine, InvCycleIndex


def signature_class(slots: dict[str, int]) -> str:
    promo = slots.get("98020", 0) > 0 or slots.get("98021", 0) > 0
    pub = slots.get("11015", 0) > 0 or slots.get("11016", 0) > 0
    if promo and pub:
        return "both"
    if promo:
        return "promo_sig"
    if pub:
        return "pub_sig"
    return "neither"


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
    inv_index = (
        InvCycleIndex(mapper, active) if engine.bias_compensation else None
    )

    gloria = [
        d
        for d in active
        if mapper.to_canonical(d.investigator_front) == "11014"
    ]
    print(f"Active Gloria decks (canonical_front=11014): {len(gloria)}")
    print("Raw fronts:", dict(Counter(d.investigator_front for d in gloria)))

    counts: Counter[tuple[str, str]] = Counter()
    weights: dict[tuple[str, str], float] = defaultdict(float)
    for deck in gloria:
        sig = signature_class(deck.slots)
        front = deck.investigator_front
        counts[(front, sig)] += 1
        weights[(front, sig)] += engine.investigator_deck_weight(
            deck, user_weights, cycle_weights, inv_index
        )

    print("\nCross-tab (deck count):")
    for key in sorted(counts):
        print(f"  front={key[0]} sig={key[1]}: n={counts[key]}")

    print("\nCross-tab (investigator_deck_weight):")
    for key in sorted(weights):
        print(f"  front={key[0]} sig={key[1]}: wt={weights[key]:.4f}")

    promo_only = [
        d for d in gloria if signature_class(d.slots) == "promo_sig"
    ]
    pub_only = [d for d in gloria if signature_class(d.slots) == "pub_sig"]

    def weighted_share(decks: list, pred) -> tuple[float, int, int]:
        total = sum(
            engine.investigator_deck_weight(
                d, user_weights, cycle_weights, inv_index
            )
            for d in decks
        )
        hit = sum(
            engine.investigator_deck_weight(
                d, user_weights, cycle_weights, inv_index
            )
            for d in decks
            if pred(d)
        )
        n_hit = sum(1 for d in decks if pred(d))
        return (100.0 * hit / total if total else 0.0, n_hit, len(decks))

    p_promo_front, n1, t1 = weighted_share(
        promo_only, lambda d: d.investigator_front == "98019"
    )
    p_pub_front, n2, t2 = weighted_share(
        pub_only, lambda d: d.investigator_front == "11014"
    )

    print(f"\nPromo sig only (98020/98021, not 11015/11016): {t1} decks")
    print(f"  front=98019: {n1}/{t1} decks, {p_promo_front:.1f}% weighted")
    print(f"  front=11014: {t1 - n1}/{t1} decks")

    print(f"\nPub sig only (11015/11016, not promo sigs): {t2} decks")
    print(f"  front=11014: {n2}/{t2} decks, {p_pub_front:.1f}% weighted")
    print(f"  front=98019: {t2 - n2}/{t2} decks")

    # What if we keep (canonical_front, primary sig) but NOT filter front?
    total_wt = sum(
        engine.investigator_deck_weight(
            d, user_weights, cycle_weights, inv_index
        )
        for d in gloria
    )
    kept_wt = sum(
        engine.investigator_deck_weight(
            d, user_weights, cycle_weights, inv_index
        )
        for d in gloria
        if signature_class(d.slots) == "pub_sig"
    )
    print(
        f"\nIf filter=primary signatures only (pub sig): "
        f"kept {100*kept_wt/total_wt:.1f}% Gloria weight"
    )
    print(
        f"If filter=primary signatures AND front=11014: "
        f"kept {100*sum(engine.investigator_deck_weight(d,user_weights,cycle_weights,inv_index) for d in pub_only if d.investigator_front=='11014')/total_wt:.1f}%"
    )


if __name__ == "__main__":
    main()
