# -*- coding: utf-8 -*-
"""Promo vs published signature timing via decklist_id for promo investigators."""

from __future__ import annotations

import argparse
import json
import pickle
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from arkham_canonical import CanonicalMapper, parse_investigator_front_back

PROMO_PREFIXES = ("98", "99")

# Default canonical fronts for the eight promo investigators.
INVESTIGATOR_FRONTS: dict[str, str] = {
    "Jenny Barnes": "02003",
    "Roland Banks": "01001",
    "Norman Withers": "08004",
    "Silas Marsh": "07005",
    "Carolyn Fern": "05001",
    "Dexter Drake": "07004",
    "Gloria Goldberg": "11014",
    "Marie Lambeau": "05006",
}

# Marie promo is the investigator front 99001 (canonicalizes to 05006).
MARIE_PROMO_FRONT = "99001"


def is_promo_signature_id(card_id: str) -> bool:
    return card_id.startswith(PROMO_PREFIXES)


@dataclass
class InvestigatorPromoSpec:
    name: str
    canonical_front: str
    inv_cycle: int | None
    promo_signature_ids: frozenset[str]
    regular_signature_ids: frozenset[str]
    uses_promo_front: bool = False


def build_specs(cards: dict[str, dict[str, Any]], mapper: CanonicalMapper) -> list[InvestigatorPromoSpec]:
    from arkham_deck_options import deck_requirement_signature_groups

    specs: list[InvestigatorPromoSpec] = []
    for name, front in INVESTIGATOR_FRONTS.items():
        inv_card = cards.get(front) or {}
        groups = deck_requirement_signature_groups(
            inv_card.get("deck_requirements") or {},
            mapper.to_canonical,
        )
        promo: set[str] = set()
        regular: set[str] = set()
        for group in groups:
            for cid in group:
                if is_promo_signature_id(cid):
                    promo.add(cid)
                else:
                    regular.add(cid)
        specs.append(
            InvestigatorPromoSpec(
                name=name,
                canonical_front=front,
                inv_cycle=mapper.cycle_for_slot(front),
                promo_signature_ids=frozenset(promo),
                regular_signature_ids=frozenset(regular),
                uses_promo_front=name == "Marie Lambeau",
            )
        )
    return specs


def classify_deck(
    *,
    raw_front: str,
    slots_raw: dict[str, int],
    spec: InvestigatorPromoSpec,
) -> str:
    if spec.uses_promo_front and raw_front == MARIE_PROMO_FRONT:
        return "promo_front"

    promo_hits = [cid for cid in spec.promo_signature_ids if slots_raw.get(cid, 0) > 0]
    regular_hits = [cid for cid in spec.regular_signature_ids if slots_raw.get(cid, 0) > 0]
    if promo_hits and regular_hits:
        return "both"
    if promo_hits:
        return "promo_signature"
    if regular_hits:
        return "regular_signature"
    return "neither"


def quantile(sorted_vals: list[int], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def summarize_ids(ids: list[int]) -> dict[str, Any]:
    if not ids:
        return {"n": 0}
    s = sorted(ids)
    return {
        "n": len(s),
        "min": s[0],
        "p25": round(quantile(s, 0.25)),
        "median": round(statistics.median(s)),
        "p75": round(quantile(s, 0.75)),
        "max": s[-1],
    }


def analyze(
    decklists: dict[Any, dict[str, Any]],
    mapper: CanonicalMapper,
    specs: list[InvestigatorPromoSpec],
    prepared_by_id: dict[Any, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in specs:
        by_class: dict[str, list[int]] = defaultdict(list)
        promo_pre_pool = 0
        promo_cohort = 0

        for decklist_id, deck in decklists.items():
            if not deck:
                continue
            try:
                raw_front, _raw_back = parse_investigator_front_back(deck)
            except (KeyError, ValueError):
                continue
            if mapper.to_canonical(raw_front) != spec.canonical_front:
                continue
            try:
                did = int(decklist_id)
            except (TypeError, ValueError):
                did = int(deck.get("id", decklist_id))

            slots_raw = deck.get("slots") or {}
            label = classify_deck(raw_front=raw_front, slots_raw=slots_raw, spec=spec)
            by_class[label].append(did)

            if label in ("promo_signature", "promo_front", "both"):
                prep = prepared_by_id.get(decklist_id) or prepared_by_id.get(did)
                if prep and prep.cycle is not None and spec.inv_cycle is not None:
                    if prep.cycle < spec.inv_cycle:
                        promo_pre_pool += 1
                    else:
                        promo_cohort += 1

        promo_ids = sorted(
            by_class.get("promo_signature", [])
            + by_class.get("promo_front", [])
            + by_class.get("both", [])
        )
        regular_ids = sorted(by_class.get("regular_signature", []))
        promo_only_ids = sorted(
            by_class.get("promo_signature", []) + by_class.get("promo_front", [])
        )

        promo_summary = summarize_ids(promo_only_ids)
        regular_summary = summarize_ids(regular_ids)
        all_promo_summary = summarize_ids(promo_ids)

        if promo_summary.get("n", 0) and regular_summary.get("n", 0):
            delta = promo_summary["median"] - regular_summary["median"]
            if delta < -5000:
                timing = "promo_earlier_median"
            elif delta > 5000:
                timing = "promo_later_median"
            else:
                timing = "overlapping_median"
        else:
            timing = "insufficient_regular"

        if promo_summary.get("n", 0) and regular_summary.get("n", 0):
            first_delta = promo_summary["min"] - regular_summary["min"]
            if first_delta > 1000:
                first_timing = "promo_first_appears_later"
            elif first_delta < -1000:
                first_timing = "promo_first_appears_earlier"
            else:
                first_timing = "promo_and_regular_same_era"
        elif promo_summary.get("n", 0):
            first_timing = "promo_only_in_data"
        else:
            first_timing = "no_promo_usage"

        rows.append(
            {
                "investigator": spec.name,
                "canonical_front": spec.canonical_front,
                "inv_cycle": spec.inv_cycle,
                "promo_signature_ids": sorted(spec.promo_signature_ids),
                "regular_signature_ids": sorted(spec.regular_signature_ids),
                "promo_front_raw_id": MARIE_PROMO_FRONT if spec.uses_promo_front else None,
                "counts": {k: len(v) for k, v in sorted(by_class.items())},
                "promo_only": promo_summary,
                "promo_including_both": all_promo_summary,
                "regular_signature": regular_summary,
                "promo_pre_pool_C_lt_inv_cycle": promo_pre_pool,
                "promo_cohort_C_ge_inv_cycle": promo_cohort,
                "median_timing": timing,
                "first_appearance_timing": first_timing,
            }
        )
    return rows


def print_report(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        print(f"\n{'=' * 72}")
        print(
            f"{row['investigator']} ({row['canonical_front']}) inv_cycle={row['inv_cycle']}"
        )
        if row["promo_signature_ids"]:
            print(f"  Promo sig ids: {', '.join(row['promo_signature_ids'])}")
        if row["promo_front_raw_id"]:
            print(f"  Promo front raw id: {row['promo_front_raw_id']}")
        print(f"  Regular sig ids: {', '.join(row['regular_signature_ids'])}")
        print(f"  Counts: {row['counts']}")
        print(
            f"  Promo-era proxy (promo use, C<inv_cycle): {row['promo_pre_pool_C_lt_inv_cycle']} | "
            f"cohort (C>=inv_cycle): {row['promo_cohort_C_ge_inv_cycle']}"
        )
        p = row["promo_only"]
        r = row["regular_signature"]
        if p.get("n"):
            print(
                f"  Promo-only: n={p['n']} first={p['min']} med={p['median']} max={p['max']}"
            )
        if r.get("n"):
            print(
                f"  Regular sig: n={r['n']} first={r['min']} med={r['median']} max={r['max']}"
            )
        print(f"  First appearance: {row['first_appearance_timing']}")
        print(f"  Median comparison: {row['median_timing']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="promo_signature_timing.json")
    args = parser.parse_args()

    with open("card_json.pickle", "rb") as handle:
        cards = pickle.load(handle)
    with open("decklist_json.pickle", "rb") as handle:
        decklists = pickle.load(handle)
    with open("taboo.json", encoding="utf-8") as handle:
        taboo = json.load(handle)

    from arkham_popularity import ArkhamPopularityEngine

    mapper = CanonicalMapper(cards)
    engine = ArkhamPopularityEngine(cards, mapper, taboo)
    prepared = {
        d.decklist_id: d
        for d in engine.prepare_all(decklists)
        if not d.is_ignore and d.cycle is not None
    }

    specs = build_specs(cards, mapper)
    rows = analyze(decklists, mapper, specs, prepared)
    print_report(rows)

    with open(args.json, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    print(f"\nWrote {args.json}")


if __name__ == "__main__":
    main()
