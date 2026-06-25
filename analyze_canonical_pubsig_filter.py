# -*- coding: utf-8 -*-
"""Canonical front/back + published signatures filter; Marie 99001 retention."""

from __future__ import annotations

import json
import pickle
from collections import Counter, defaultdict

from arkham_canonical import CanonicalMapper
from arkham_deck_options import deck_requirement_signature_groups
from arkham_popularity import ArkhamPopularityEngine, InvCycleIndex, investigator_decks


def is_promo_sig(card_id: str) -> bool:
    return card_id.startswith(("98", "99"))


def is_parallel_sig(card_id: str) -> bool:
    return card_id.startswith("900") and not is_promo_sig(card_id)


def published_signatures_ok(
    slots: dict[str, int],
    groups: list[frozenset[str]],
) -> bool:
    for group in groups:
        present = sorted(cid for cid in group if slots.get(cid, 0) > 0)
        if len(present) != 1:
            return False
        chosen = present[0]
        if is_promo_sig(chosen) or is_parallel_sig(chosen):
            return False
    return True


def passes_canonical_front_back(deck, mapper: CanonicalMapper) -> bool:
    """Alt-art allowed: raw front/back must map to deck canonical tuple."""
    return (
        mapper.to_canonical(deck.investigator_front) == deck.canonical_front
        and mapper.to_canonical(deck.investigator_back) == deck.canonical_back
    )


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

    def weight(deck):
        return engine.investigator_deck_weight(
            deck, user_weights, cycle_weights, inv_index
        )

    def below_icy(decks, icy: int) -> float:
        total = sum(weight(d) for d in decks)
        if not total:
            return 0.0
        return sum(weight(d) for d in decks if d.cycle < icy) / total

    investigators = {
        "Norman Withers": "08004",
        "Gloria Goldberg": "11014",
        "Marie Lambeau": "05006",
        "Carolyn Fern": "05001",
        "Dexter Drake": "07004",
        "Silas Marsh": "07005",
        "Jenny Barnes": "02003",
        "Roland Banks": "01001",
    }

    print("Filter: canonical front/back (alt-art ok) + primary published signatures")
    print("Does NOT filter Marie 99001 (same canonical_front as 05006)\n")
    print(
        f"{'investigator':<18} icy  kept%  C<icy all  C<icy filtered"
    )

    rows = []
    for name, front in investigators.items():
        decks = investigator_decks(active, front, front, require_cycle=True)
        groups = deck_requirement_signature_groups(
            (cards.get(front) or {}).get("deck_requirements") or {},
            mapper.to_canonical,
        )
        kept = [
            d
            for d in decks
            if passes_canonical_front_back(d, mapper)
            and (not groups or published_signatures_ok(d.slots, groups))
        ]
        icy = mapper.cycle_for_slot(front)
        pct = 100 * len(kept) / len(decks) if decks else 0
        row = {
            "investigator": name,
            "inv_cycle": icy,
            "pct_kept": round(pct, 1),
            "c_below_icy_all": round(below_icy(decks, icy), 4),
            "c_below_icy_filtered": round(below_icy(kept, icy), 4),
        }
        if name == "Marie Lambeau":
            row["kept_99001"] = sum(
                1 for d in kept if d.investigator_front == "99001"
            )
            row["kept_05006"] = sum(
                1 for d in kept if d.investigator_front == "05006"
            )
            row["kept_total"] = len(kept)
        rows.append(row)
        extra = ""
        if name == "Marie Lambeau":
            extra = f"  (99001: {row['kept_99001']}/{len(kept)} kept)"
        print(
            f"{name:<18} {icy:>2}  {pct:5.1f}%  "
            f"{row['c_below_icy_all']:6.1%}    {row['c_below_icy_filtered']:6.1%}{extra}"
        )

    # Norman: what gets removed
    norm = investigator_decks(active, "08004", "08004", require_cycle=True)
    groups = deck_requirement_signature_groups(
        cards["08004"].get("deck_requirements") or {},
        mapper.to_canonical,
    )
    removed = [
        d
        for d in norm
        if not (
            passes_canonical_front_back(d, mapper)
            and published_signatures_ok(d.slots, groups)
        )
    ]
    print("\nNorman removed decks (mostly promo sig): C<9 weight =", f"{below_icy(removed, 9):.1%}")
    print("  deck count by C:", dict(sorted(Counter(d.cycle for d in removed).items())))

    with open("canonical_pubsig_filter_check.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


if __name__ == "__main__":
    main()
