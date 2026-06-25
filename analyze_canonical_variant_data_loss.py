# -*- coding: utf-8 -*-
"""Training-data loss from restricting to published + alt-art front/back/signatures.

Alternative art (mechanically identical reprints) is allowed.
Parallel and promo printings that change game mechanics are excluded.
Charlie Kane faction_select splits are not collapsed.
"""

from __future__ import annotations

import argparse
import csv
import json
import pickle
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from arkham_canonical import CanonicalMapper
from arkham_deck_options import deck_requirement_signature_groups
from arkham_popularity import (
    ArkhamPopularityEngine,
    InvCycleIndex,
    investigator_decks,
)

PROMO_PACKS = frozenset({"promo"})


def is_promo_signature_id(card_id: str) -> bool:
    return card_id.startswith(("98", "99"))


def is_promo_investigator_printing(
    raw_id: str,
    cards: dict[str, dict[str, Any]],
) -> bool:
    card = cards.get(raw_id) or {}
    if card.get("pack_code") in PROMO_PACKS:
        return True
    return False


def is_mechanical_parallel_investigator(
    raw_id: str,
    target_canonical: str,
    cards: dict[str, dict[str, Any]],
    mapper: CanonicalMapper,
) -> bool:
    """Parallel investigator product (own rules), not alt-art of target."""
    if mapper.to_canonical(raw_id) != target_canonical:
        return False
    if raw_id == target_canonical:
        return False
    card = cards.get(raw_id) or {}
    if card.get("duplicate_of_code") == target_canonical:
        return False
    # Fingerprint-merged alt art (e.g. dre Gloria -> tdcp canonical): allowed.
    return False


def is_allowed_investigator_printing(
    raw_id: str,
    target_canonical: str,
    cards: dict[str, dict[str, Any]],
    mapper: CanonicalMapper,
) -> bool:
    if mapper.to_canonical(raw_id) != target_canonical:
        return False
    if is_promo_investigator_printing(raw_id, cards):
        return False
    if is_mechanical_parallel_investigator(raw_id, target_canonical, cards, mapper):
        return False
    return True


def is_parallel_signature_printing(
    card_id: str,
    cards: dict[str, dict[str, Any]],
) -> bool:
    """Parallel signature option in an OR-group (mechanical alternate)."""
    if is_promo_signature_id(card_id):
        return False
    if card_id.startswith("900"):
        return True
    return False


def published_signature_ids_for_group(
    group: frozenset[str],
    cards: dict[str, dict[str, Any]],
) -> frozenset[str]:
    """Allowed signature printings: published + alt-art reprints; no promo/parallel."""
    primaries = sorted(
        cid
        for cid in group
        if not is_promo_signature_id(cid)
        and not is_parallel_signature_printing(cid, cards)
    )
    if not primaries:
        return frozenset()

    allowed: set[str] = set()
    for primary in primaries:
        allowed.add(primary)
        for cid in group:
            if (cards.get(cid) or {}).get("duplicate_of_code") == primary:
                allowed.add(cid)
    return frozenset(allowed)


def allowed_signature_groups(
    groups: list[frozenset[str]],
    cards: dict[str, dict[str, Any]],
) -> list[frozenset[str]]:
    return [published_signature_ids_for_group(group, cards) for group in groups]


def signature_profile_from_slots(
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


@dataclass
class DeckMatch:
    ok: bool
    reason: str


def classify_deck(
    deck: Any,
    *,
    canonical_front: str,
    canonical_back: str,
    allowed_groups: list[frozenset[str]],
    all_groups: list[frozenset[str]],
    cards: dict[str, dict[str, Any]],
    mapper: CanonicalMapper,
) -> DeckMatch:
    if not is_allowed_investigator_printing(
        deck.investigator_front, canonical_front, cards, mapper
    ):
        return DeckMatch(False, "bad_front")
    if not is_allowed_investigator_printing(
        deck.investigator_back, canonical_back, cards, mapper
    ):
        return DeckMatch(False, "bad_back")
    profile = signature_profile_from_slots(deck.slots, all_groups)
    if profile is None:
        return DeckMatch(False, "ambiguous_signature")
    for chosen, allowed in zip(profile, allowed_groups, strict=True):
        if chosen not in allowed:
            return DeckMatch(False, "bad_signature")
    return DeckMatch(True, "kept")


def primary_tuple(row: dict[str, Any]) -> bool:
    return (
        row["canonical_front"] == row["canonical_back"]
        and row.get("inv_cycle") is not None
    )


def analyze(
    engine: ArkhamPopularityEngine,
    prepared: list[Any],
    *,
    cards: dict[str, dict[str, Any]],
    mapper: CanonicalMapper,
    user_weights: dict[Any, float],
    cycle_weights: dict[int, float],
    inv_index: InvCycleIndex | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    active = [d for d in prepared if not d.is_ignore and d.cycle is not None]
    tuples = sorted({(d.canonical_front, d.canonical_back) for d in active})

    rows: list[dict[str, Any]] = []
    global_kept = 0.0
    global_total = 0.0
    reason_mass: dict[str, float] = defaultdict(float)

    for canonical_front, canonical_back in tuples:
        inv_decks = investigator_decks(
            active, canonical_front, canonical_back, require_cycle=True
        )
        if not inv_decks:
            continue

        all_groups = deck_requirement_signature_groups(
            (cards.get(canonical_front) or {}).get("deck_requirements") or {},
            mapper.to_canonical,
        )
        allowed_groups = allowed_signature_groups(all_groups, cards)
        published_sigs = tuple(
            sorted(allowed)[0] if allowed else ""
            for allowed in allowed_groups
        )
        inv_card = cards.get(canonical_front) or {}
        inv_name = inv_card.get("name", canonical_front)

        tuple_total = 0.0
        tuple_kept = 0.0
        reason_counts: dict[str, int] = defaultdict(int)
        tuple_reason_mass: dict[str, float] = defaultdict(float)

        for deck in inv_decks:
            weight = engine.investigator_deck_weight(
                deck, user_weights, cycle_weights, inv_index
            )
            if not weight:
                continue
            tuple_total += weight
            global_total += weight
            match = classify_deck(
                deck,
                canonical_front=canonical_front,
                canonical_back=canonical_back,
                allowed_groups=allowed_groups,
                all_groups=all_groups,
                cards=cards,
                mapper=mapper,
            )
            if match.ok:
                tuple_kept += weight
                global_kept += weight
            else:
                reason_counts[match.reason] += 1
                tuple_reason_mass[match.reason] += weight
                reason_mass[match.reason] += weight

        if tuple_total <= 0:
            continue

        rows.append(
            {
                "investigator_name": inv_name,
                "canonical_front": canonical_front,
                "canonical_back": canonical_back,
                "inv_cycle": mapper.cycle_for_slot(canonical_front),
                "published_signatures": published_sigs,
                "allowed_signature_groups": [
                    sorted(group) for group in allowed_groups
                ],
                "deck_count": len(inv_decks),
                "weighted_total": tuple_total,
                "weighted_kept": tuple_kept,
                "weighted_lost": tuple_total - tuple_kept,
                "pct_kept": round(100.0 * tuple_kept / tuple_total, 2),
                "pct_lost": round(100.0 * (tuple_total - tuple_kept) / tuple_total, 2),
                "lost_decks_bad_front": reason_counts.get("bad_front", 0),
                "lost_decks_bad_back": reason_counts.get("bad_back", 0),
                "lost_decks_bad_signature": reason_counts.get("bad_signature", 0),
                "lost_decks_ambiguous_signature": reason_counts.get(
                    "ambiguous_signature", 0
                ),
                "charlie_faction_split_preserved": inv_name == "Charlie Kane",
            }
        )

    rows.sort(key=lambda r: (-r["weighted_lost"], r["investigator_name"]))

    primary = [r for r in rows if primary_tuple(r)]
    primary_total = sum(r["weighted_total"] for r in primary)
    primary_kept = sum(r["weighted_kept"] for r in primary)

    summary = {
        "weighted_total": global_total,
        "weighted_kept": global_kept,
        "weighted_lost": global_total - global_kept,
        "pct_kept": round(100.0 * global_kept / global_total, 2)
        if global_total
        else 0.0,
        "primary_tuple_weighted_total": primary_total,
        "primary_tuple_weighted_kept": primary_kept,
        "primary_tuple_pct_kept": round(100.0 * primary_kept / primary_total, 2)
        if primary_total
        else 0.0,
        "lost_weight_by_reason": dict(reason_mass),
        "definition": {
            "allowed": (
                "published printing + alternative art (duplicate_of or fingerprint-merged "
                "reprint of same mechanics)"
            ),
            "excluded": (
                "promo front/back/signatures (98***/99***, pack_code=promo) and "
                "parallel front/back/signatures (900** signature alts, separate "
                "parallel investigator tuples)"
            ),
            "signatures": (
                "each OR-group: exactly one printing from allowed set (non-promo, "
                "non-parallel, plus duplicate_of reprints)"
            ),
            "charlie_kane": "faction_select splits unchanged",
            "weight": "investigator_deck_weight (B1+B2, no B3)",
        },
    }
    return rows, summary


def print_report(rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    print("=== Global (all investigator tuples) ===")
    print(
        f"  Kept: {summary['weighted_kept']:.4f} ({summary['pct_kept']}%)\n"
        f"  Lost: {summary['weighted_lost']:.4f}"
    )
    print(
        f"\n=== Primary tuples only (front==back, inv_cycle set) ===\n"
        f"  Kept: {summary['primary_tuple_weighted_kept']:.4f} "
        f"({summary['primary_tuple_pct_kept']}%)"
    )
    by_reason = summary["lost_weight_by_reason"]
    if by_reason:
        print("\n  Lost weight by reason (all tuples):")
        total_lost = summary["weighted_lost"]
        for reason, mass in sorted(by_reason.items(), key=lambda x: -x[1]):
            pct = 100.0 * mass / total_lost if total_lost else 0
            print(f"    {reason}: {mass:.4f} ({pct:.1f}%)")

    print("\n=== Largest losses (primary tuples, weighted) ===")
    primary = sorted(
        [r for r in rows if primary_tuple(r)],
        key=lambda r: -r["weighted_lost"],
    )
    for row in primary[:12]:
        if row["weighted_lost"] < 0.001:
            break
        sigs = ",".join(row["published_signatures"]) if row["published_signatures"] else "-"
        print(
            f"  {row['investigator_name']:<20} {row['canonical_front']} "
            f"kept {row['pct_kept']:5.1f}%  "
            f"front={row['lost_decks_bad_front']} sig={row['lost_decks_bad_signature']} "
            f"ambig={row['lost_decks_ambiguous_signature']}  [{sigs}]"
        )

    charlie = next((r for r in rows if r["investigator_name"] == "Charlie Kane"), None)
    if charlie:
        print(
            f"\nCharlie Kane: kept {charlie['pct_kept']}% "
            f"({charlie['deck_count']} decks; factions not collapsed)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="canonical_variant_data_loss.csv")
    parser.add_argument("--json", default="canonical_variant_data_loss.json")
    args = parser.parse_args()

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

    rows, summary = analyze(
        engine,
        prepared,
        cards=cards,
        mapper=mapper,
        user_weights=user_weights,
        cycle_weights=cycle_weights,
        inv_index=inv_index,
    )
    print_report(rows, summary)

    with open(args.csv, "w", newline="", encoding="utf-8") as handle:
        if rows:
            fieldnames = [k for k in rows[0] if k != "allowed_signature_groups"]
            fieldnames.append("allowed_signature_groups")
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                out = {k: row[k] for k in fieldnames if k != "allowed_signature_groups"}
                out["published_signatures"] = "|".join(row["published_signatures"])
                out["allowed_signature_groups"] = ";".join(
                    ",".join(group) for group in row["allowed_signature_groups"]
                )
                writer.writerow(out)

    export_rows = []
    for row in rows:
        copy = dict(row)
        copy["published_signatures"] = list(row["published_signatures"])
        copy["allowed_signature_groups"] = [
            list(group) for group in row["allowed_signature_groups"]
        ]
        export_rows.append(copy)

    with open(args.json, "w", encoding="utf-8") as handle:
        json.dump({"summary": summary, "rows": export_rows}, handle, indent=2)

    print(f"\nWrote {args.csv} and {args.json}")


if __name__ == "__main__":
    main()
