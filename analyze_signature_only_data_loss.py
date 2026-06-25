# -*- coding: utf-8 -*-
"""Data loss filtering to primary signatures only (no front/back printing filter)."""

from __future__ import annotations

import json
import pickle
from collections import Counter, defaultdict

from arkham_canonical import CanonicalMapper
from arkham_deck_options import deck_requirement_signature_groups
from arkham_popularity import (
    ArkhamPopularityEngine,
    InvCycleIndex,
    investigator_decks,
)


def is_promo_sig(card_id: str) -> bool:
    return card_id.startswith(("98", "99"))


def is_parallel_sig(card_id: str) -> bool:
    return not is_promo_sig(card_id) and card_id.startswith("900")


def allowed_sigs_for_group(
    group: frozenset[str],
    cards: dict,
) -> frozenset[str]:
    primaries = sorted(
        cid
        for cid in group
        if not is_promo_sig(cid) and not is_parallel_sig(cid)
    )
    allowed: set[str] = set()
    for primary in primaries:
        allowed.add(primary)
        for cid in group:
            if (cards.get(cid) or {}).get("duplicate_of_code") == primary:
                allowed.add(cid)
    return frozenset(allowed)


def signature_profile(
    slots: dict[str, int],
    groups: list[frozenset[str]],
) -> tuple[str, ...] | None:
    profile: list[str] = []
    for group in groups:
        present = sorted(cid for cid in group if slots.get(cid, 0) > 0)
        if len(present) != 1:
            return None
        profile.append(present[0])
    return tuple(profile)


def signatures_match_primary(
    slots: dict[str, int],
    groups: list[frozenset[str]],
    cards: dict,
) -> tuple[bool, str]:
    profile = signature_profile(slots, groups)
    if profile is None:
        return False, "ambiguous_signature"
    for chosen, group in zip(profile, groups, strict=True):
        if chosen not in allowed_sigs_for_group(group, cards):
            return False, "non_primary_signature"
    return True, "kept"


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

    tuples = sorted({(d.canonical_front, d.canonical_back) for d in active})
    global_total = 0.0
    global_kept = 0.0
    reason_mass: dict[str, float] = defaultdict(float)
    rows: list[dict] = []

    for canonical_front, canonical_back in tuples:
        inv_decks = investigator_decks(
            active, canonical_front, canonical_back, require_cycle=True
        )
        groups = deck_requirement_signature_groups(
            (cards.get(canonical_front) or {}).get("deck_requirements") or {},
            mapper.to_canonical,
        )
        primary = tuple(
            sorted(allowed)[0] if allowed else ""
            for allowed in (allowed_sigs_for_group(g, cards) for g in groups)
        )
        name = (cards.get(canonical_front) or {}).get("name", canonical_front)
        tuple_total = 0.0
        tuple_kept = 0.0
        reason_counts: dict[str, int] = defaultdict(int)

        for deck in inv_decks:
            weight = engine.investigator_deck_weight(
                deck, user_weights, cycle_weights, inv_index
            )
            if not weight:
                continue
            tuple_total += weight
            global_total += weight
            ok, reason = signatures_match_primary(deck.slots, groups, cards)
            if ok:
                tuple_kept += weight
                global_kept += weight
            else:
                reason_counts[reason] += 1
                reason_mass[reason] += weight

        if tuple_total <= 0:
            continue

        rows.append(
            {
                "investigator_name": name,
                "canonical_front": canonical_front,
                "canonical_back": canonical_back,
                "inv_cycle": mapper.cycle_for_slot(canonical_front),
                "primary_signatures": primary,
                "deck_count": len(inv_decks),
                "weighted_total": tuple_total,
                "weighted_kept": tuple_kept,
                "pct_kept": 100.0 * tuple_kept / tuple_total,
                "reason_counts": dict(reason_counts),
            }
        )

    primary_rows = [
        r
        for r in rows
        if r["canonical_front"] == r["canonical_back"]
        and r["inv_cycle"] is not None
    ]
    primary_total = sum(r["weighted_total"] for r in primary_rows)
    primary_kept = sum(r["weighted_kept"] for r in primary_rows)

    print("Filter: (canonical_front, canonical_back, primary signatures)")
    print("Investigator front/back printing NOT filtered (05006 and 99001 both kept)")
    print()
    print(
        f"Global all tuples: kept {100 * global_kept / global_total:.2f}% "
        f"({global_kept:.4f} / {global_total:.4f})"
    )
    print(
        f"Primary tuples:    kept {100 * primary_kept / primary_total:.2f}% "
        f"({primary_kept:.4f} / {primary_total:.4f})"
    )
    print("Lost weight by reason:", dict(reason_mass))

    marie = next((r for r in rows if r["canonical_front"] == "05006"), None)
    if marie:
        print()
        print("Marie Lambeau (05006):")
        print(f"  primary signatures: {marie['primary_signatures']}")
        print(f"  kept {marie['pct_kept']:.2f}%")
        print(f"  rejections: {marie['reason_counts']}")

        marie_decks = [
            d
            for d in active
            if d.canonical_front == "05006"
            and d.investigator_front in ("05006", "99001")
        ]
        kept_front: Counter[str] = Counter()
        for deck in marie_decks:
            weight = engine.investigator_deck_weight(
                deck, user_weights, cycle_weights, inv_index
            )
            if not weight:
                continue
            groups = deck_requirement_signature_groups(
                cards["05006"].get("deck_requirements") or {},
                mapper.to_canonical,
            )
            ok, _ = signatures_match_primary(deck.slots, groups, cards)
            if ok:
                kept_front[deck.investigator_front] += weight
        print(f"  kept weight by raw front: {dict(kept_front)}")

    print()
    print("Largest primary-tuple losses:")
    for row in sorted(primary_rows, key=lambda r: -r["weighted_total"] + r["weighted_kept"])[:10]:
        lost = row["weighted_total"] - row["weighted_kept"]
        if lost < 0.0001:
            continue
        print(
            f"  {row['investigator_name']:<20} {row['canonical_front']} "
            f"kept {row['pct_kept']:5.1f}%  {row['reason_counts']}"
        )


if __name__ == "__main__":
    main()
