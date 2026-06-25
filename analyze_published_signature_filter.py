# -*- coding: utf-8 -*-
"""Impact of published-signature-only filter on Decklist.cycle distributions."""

from __future__ import annotations

import json
import pickle
import statistics
from collections import Counter, defaultdict
from typing import Any

from arkham_canonical import CanonicalMapper
from arkham_deck_options import deck_requirement_signature_groups
from arkham_popularity import ArkhamPopularityEngine, InvCycleIndex, investigator_decks


def is_promo_sig(card_id: str) -> bool:
    return card_id.startswith(("98", "99"))


def is_parallel_sig(card_id: str) -> bool:
    return card_id.startswith("900") and not is_promo_sig(card_id)


def allowed_published_group(
    group: frozenset[str],
) -> frozenset[str]:
    primaries = sorted(
        cid for cid in group if not is_promo_sig(cid) and not is_parallel_sig(cid)
    )
    return frozenset(primaries)


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


def is_published_signature_profile(
    slots: dict[str, int],
    groups: list[frozenset[str]],
) -> bool:
    profile = signature_profile(slots, groups)
    if profile is None:
        return False
    for chosen, group in zip(profile, groups, strict=True):
        if chosen not in allowed_published_group(group):
            return False
    return True


def distribution(decks: list, weight_fn) -> dict[int, float]:
    dist: dict[int, float] = defaultdict(float)
    for deck in decks:
        if deck.cycle is None:
            continue
        dist[deck.cycle] += weight_fn(deck)
    total = sum(dist.values())
    if total <= 0:
        return {}
    return {c: w / total for c, w in sorted(dist.items())}


def l1_distance(a: dict[int, float], b: dict[int, float]) -> float:
    keys = set(a) | set(b)
    return sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys)


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

    groups_cache: dict[str, list[frozenset[str]]] = {}

    def groups_for(front: str) -> list[frozenset[str]]:
        if front not in groups_cache:
            inv_card = cards.get(front) or {}
            groups_cache[front] = deck_requirement_signature_groups(
                inv_card.get("deck_requirements") or {},
                mapper.to_canonical,
            )
        return groups_cache[front]

    # Primary tuples only
    tuples = sorted(
        {
            (d.canonical_front, d.canonical_back)
            for d in active
            if d.canonical_front == d.canonical_back
            and mapper.cycle_for_slot(d.canonical_front) is not None
        }
    )

    per_inv: list[dict[str, Any]] = []
    by_inv_cycle: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for cf, cb in tuples:
        inv_decks = investigator_decks(active, cf, cb, require_cycle=True)
        groups = groups_for(cf)
        if not groups:
            kept = inv_decks
            rejected = []
        else:
            kept = [
                d
                for d in inv_decks
                if is_published_signature_profile(d.slots, groups)
            ]
            rejected = [
                d
                for d in inv_decks
                if not is_published_signature_profile(d.slots, groups)
            ]

        total_wt = sum(weight(d) for d in inv_decks)
        kept_wt = sum(weight(d) for d in kept)
        inv_cycle = mapper.cycle_for_slot(cf)
        name = (cards.get(cf) or {}).get("name", cf)

        dist_all = distribution(inv_decks, weight)
        dist_kept = distribution(kept, weight)

        row = {
            "investigator": name,
            "canonical_front": cf,
            "inv_cycle": inv_cycle,
            "deck_count": len(inv_decks),
            "kept_count": len(kept),
            "pct_kept": round(100 * len(kept) / len(inv_decks), 1) if inv_decks else 0,
            "weighted_pct_kept": round(100 * kept_wt / total_wt, 1) if total_wt else 0,
            "dist_all": dist_all,
            "dist_kept": dist_kept,
            "has_sig_or_groups": bool(groups),
        }
        per_inv.append(row)
        by_inv_cycle[inv_cycle].append(row)

    # L1 distance to cohort median distribution (kept vs all peers at inv_cycle)
    print("=== Published-signature filter impact (primary tuples) ===\n")
    print(
        f"{'investigator':<22} {'icy':>3} {'kept%':>6} {'wt%':>6}  "
        f"L1(all vs cohort_med) L1(kept vs cohort_med)"
    )

    promo_names = {
        "Jenny Barnes", "Roland Banks", "Norman Withers", "Silas Marsh",
        "Carolyn Fern", "Dexter Drake", "Gloria Goldberg", "Marie Lambeau",
    }

    cohort_medians: dict[int, dict[int, float]] = {}
    for icy, rows in by_inv_cycle.items():
        # median share per C across investigators (using kept dist for reference peers)
        all_c = set()
        for r in rows:
            all_c |= set(r["dist_all"])
        med: dict[int, float] = {}
        for c in sorted(all_c):
            shares = [r["dist_all"].get(c, 0.0) for r in rows if r["dist_all"]]
            if shares:
                med[c] = statistics.median(shares)
        cohort_medians[icy] = med

    results_for_json: list[dict] = []
    for row in sorted(per_inv, key=lambda r: r["weighted_pct_kept"]):
        icy = row["inv_cycle"]
        med = cohort_medians.get(icy, {})
        l1_all = l1_distance(row["dist_all"], med)
        l1_kept = l1_distance(row["dist_kept"], med)
        flag = "*" if row["investigator"] in promo_names else " "
        print(
            f"{flag}{row['investigator']:<21} {icy:>3} "
            f"{row['pct_kept']:>5.1f}% {row['weighted_pct_kept']:>5.1f}%  "
            f"{l1_all:.3f}  {l1_kept:.3f}"
        )
        results_for_json.append(
            {
                "investigator": row["investigator"],
                "inv_cycle": icy,
                "pct_kept": row["pct_kept"],
                "weighted_pct_kept": row["weighted_pct_kept"],
                "l1_all_vs_cohort_median": round(l1_all, 4),
                "l1_kept_vs_cohort_median": round(l1_kept, 4),
                "dist_all": {str(k): round(v, 4) for k, v in row["dist_all"].items()},
                "dist_kept": {str(k): round(v, 4) for k, v in row["dist_kept"].items()},
            }
        )

    print("\n* = promo-signature investigator cohort")
    print("\n=== Promo investigators: Decklist.cycle before vs after ===")
    for name in sorted(promo_names):
        row = next((r for r in per_inv if r["investigator"] == name), None)
        if not row or not row["has_sig_or_groups"]:
            if row and name == "Marie Lambeau":
                print(f"\n{name}: signatures identical — filter does not split profiles")
            continue
        print(f"\n{name} (inv_cycle={row['inv_cycle']}, kept {row['weighted_pct_kept']}%)")
        icy = row["inv_cycle"]
        med = cohort_medians[icy]
        print(f"  Cohort median at inv_cycle {icy}: " + ", ".join(
            f"C{k}={v:.0%}" for k, v in sorted(med.items()) if v >= 0.05
        ))
        print("  Before filter: " + ", ".join(
            f"C{k}={v:.0%}" for k, v in sorted(row["dist_all"].items()) if v >= 0.03
        ))
        print("  After filter:  " + ", ".join(
            f"C{k}={v:.0%}" for k, v in sorted(row["dist_kept"].items()) if v >= 0.03
        ))

    with open("published_signature_filter_impact.json", "w", encoding="utf-8") as f:
        json.dump(results_for_json, f, indent=2)
    print("\nWrote published_signature_filter_impact.json")


if __name__ == "__main__":
    main()
