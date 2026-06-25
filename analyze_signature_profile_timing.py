# -*- coding: utf-8 -*-
"""Promo vs published signature timing using (canonical_front, canonical_back, signature_profile)."""

from __future__ import annotations

import json
import pickle
import statistics
from collections import defaultdict
from typing import Any

from arkham_canonical import CanonicalMapper
from arkham_deck_options import deck_requirement_signature_groups
from arkham_popularity import ArkhamPopularityEngine, InvCycleIndex


def is_promo_sig(card_id: str) -> bool:
    return card_id.startswith(("98", "99"))


def is_parallel_sig(card_id: str) -> bool:
    return card_id.startswith("900") and not is_promo_sig(card_id)


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


def profile_class(profile: tuple[str, ...]) -> str:
    if any(is_promo_sig(cid) for cid in profile):
        return "promo"
    if any(is_parallel_sig(cid) for cid in profile):
        return "parallel"
    return "published"


def published_profile(
    groups: list[frozenset[str]],
) -> tuple[str, ...]:
    """Lowest non-promo, non-parallel id per group."""
    out: list[str] = []
    for group in groups:
        candidates = sorted(
            cid
            for cid in group
            if not is_promo_sig(cid) and not is_parallel_sig(cid)
        )
        out.append(candidates[0] if candidates else sorted(group)[0])
    return tuple(out)


def summarize(ids: list[int]) -> dict[str, Any]:
    if not ids:
        return {"n": 0}
    s = sorted(ids)
    return {
        "n": len(s),
        "min": s[0],
        "median": round(statistics.median(s)),
        "max": s[-1],
    }


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

    # Per (canonical_front, canonical_back): decklist_ids by profile class
    by_tuple: dict[tuple[str, str], dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    by_tuple_weight: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    profile_counts: dict[tuple[str, str, tuple[str, ...]], int] = defaultdict(int)

    groups_cache: dict[str, list[frozenset[str]]] = {}

    for deck in active:
        key = (deck.canonical_front, deck.canonical_back)
        if deck.canonical_front not in groups_cache:
            inv_card = cards.get(deck.canonical_front) or {}
            groups_cache[deck.canonical_front] = deck_requirement_signature_groups(
                inv_card.get("deck_requirements") or {},
                mapper.to_canonical,
            )
        groups = groups_cache[deck.canonical_front]
        if not groups:
            continue
        prof = signature_profile(deck.slots, groups)
        if prof is None:
            continue
        pclass = profile_class(prof)
        did = int(deck.decklist_id)
        weight = engine.investigator_deck_weight(
            deck, user_weights, cycle_weights, inv_index
        )
        by_tuple[key][pclass].append(did)
        by_tuple_weight[key][pclass] += weight
        profile_counts[(deck.canonical_front, deck.canonical_back, prof)] += 1

    promo_investigators = {
        "Jenny Barnes": "02003",
        "Roland Banks": "01001",
        "Norman Withers": "08004",
        "Silas Marsh": "07005",
        "Carolyn Fern": "05001",
        "Dexter Drake": "07004",
        "Gloria Goldberg": "11014",
        "Marie Lambeau": "05006",
    }

    print("=== Timing: promo vs published signature_profile")
    print("Stratum: (canonical_front, canonical_back); compare profile classes")
    print("(Earlier analysis used canonical_front only + sig class; see notes)\n")

    rows: list[dict[str, Any]] = []
    for name, front in promo_investigators.items():
        # primary tuple front==back
        key = (front, front)
        buckets = by_tuple.get(key, {})
        promo_ids = buckets.get("promo", [])
        pub_ids = buckets.get("published", [])
        if not promo_ids or not pub_ids:
            print(f"{name} ({front}): insufficient promo or published profiles")
            continue
        promo_med = statistics.median(promo_ids)
        pub_med = statistics.median(pub_ids)
        delta = promo_med - pub_med
        if delta < -5000:
            verdict = "promo_earlier"
        elif delta > 5000:
            verdict = "promo_later"
        else:
            verdict = "overlapping"

        pub_prof = published_profile(groups_cache[front])
        promo_profiles = [
            prof
            for (cf, cb, prof), n in profile_counts.items()
            if cf == front and cb == front and profile_class(prof) == "promo"
        ]

        row = {
            "investigator": name,
            "canonical_front": front,
            "canonical_back": front,
            "published_profile": pub_prof,
            "promo_profiles_seen": sorted(set(promo_profiles)),
            "promo": summarize(promo_ids),
            "published": summarize(pub_ids),
            "median_delta_promo_minus_pub": round(delta),
            "verdict": verdict,
        }
        rows.append(row)
        print(
            f"{name} ({front}, {front}):"
            f"\n  published profile {pub_prof}"
            f"\n  promo profiles    {row['promo_profiles_seen']}"
            f"\n  promo:      n={row['promo']['n']} med={row['promo']['median']} "
            f"min={row['promo']['min']}"
            f"\n  published:  n={row['published']['n']} med={row['published']['median']} "
            f"min={row['published']['min']}"
            f"\n  => {verdict} (delta median {round(delta):+d})\n"
        )

    # Compare with canonical_front-only method (old)
    print("=== Method comparison: tuple vs canonical_front-only ===")
    print("(Should match when front==back and ambiguous decks excluded)\n")

    # Non-primary tuples with promo sigs
    print("=== Non-primary (front!=back) tuples with promo signature profiles ===")
    found = False
    for (cf, cb), buckets in sorted(by_tuple.items()):
        if cf == cb:
            continue
        if not buckets.get("promo"):
            continue
        found = True
        name = (cards.get(cf) or {}).get("name", cf)
        promo_ids = buckets["promo"]
        pub_ids = buckets.get("published", [])
        print(
            f"  {name} ({cf}, {cb}): promo n={len(promo_ids)}"
            + (
                f" med={round(statistics.median(promo_ids))}"
                if promo_ids
                else ""
            )
            + (
                f"; published n={len(pub_ids)} med={round(statistics.median(pub_ids))}"
                if pub_ids
                else ""
            )
        )
    if not found:
        print("  (none)")

    with open("signature_profile_timing.json", "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    print("\nWrote signature_profile_timing.json")


if __name__ == "__main__":
    main()
