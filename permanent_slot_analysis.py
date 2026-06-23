# -*- coding: utf-8 -*-
"""Compare asset-slot usage in decks with vs without key permanents.

Exploratory analysis: for each permanent and investigator, split decks into
those with 1+ copies of the permanent vs without, then compare per-deck slot
occupancy (mean, sample variance, Welch t-test) and — more importantly —
whether the **weighted averages** map to different generation phase targets
(phase1_goal, phase1_cap, phase2_ceiling) via slot_phase_targets().

Slot permanents: test only the slot type(s) the card affects.
Deck-size permanents: test every standard asset slot type.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pickle
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arkham_canonical import CanonicalMapper
from arkham_popularity import (
    ArkhamPopularityEngine,
    STANDARD_ASSET_SLOT_TYPES,
    build_canonical_card_infos,
    deck_asset_slot_totals,
    generation_slot_targets_differ,
    slot_phase_targets,
)

# Permanent card_id -> asset slot type(s) whose usage we expect to shift.
SLOT_PERMANENTS: dict[str, list[str]] = {
    "01694": ["Ally"],  # Charisma
    "60232": ["Ally"],  # Miskatonic Archaeology Funding
    "10132": ["Hand", "Accessory", "Arcane"],  # Occult Reliquary (player picks one)
    "53010": ["Ally"],  # On Your Own (no ally-slot assets)
    "01695": ["Accessory"],  # Relic Hunter
}

DECK_SIZE_PERMANENTS: list[str] = [
    "07303",  # Ancestral Knowledge (+5 deck size, 10 skills)
    "08031",  # Forced Learning (+15)
    "09077",  # Underworld Market (+10)
    "08046",  # Underworld Support (-5, singleton-by-title)
    "06167",  # Versatile (+5, extra level-0 off-class)
]

PERMANENT_NAMES: dict[str, str] = {}


def permanent_in_deck(deck_slots: dict[str, int], permanent_id: str, mapper: CanonicalMapper) -> bool:
    """True if deck has 1+ copies of this permanent (any printing)."""
    canonical_id = mapper.to_canonical(permanent_id)
    if deck_slots.get(canonical_id, 0) > 0:
        return True
    if canonical_id != permanent_id and deck_slots.get(permanent_id, 0) > 0:
        return True
    return False


def load_permanent_names(cards: dict[str, dict[str, Any]]) -> None:
    for cid in list(SLOT_PERMANENTS) + DECK_SIZE_PERMANENTS:
        card = cards.get(cid)
        if card:
            PERMANENT_NAMES[cid] = card.get("name", cid)


def weighted_average(entries: list[tuple[float, float]]) -> float | None:
    """Weighted mean of (value, weight) pairs."""
    total_weight = sum(weight for _, weight in entries)
    if total_weight == 0:
        return None
    return sum(value * weight for value, weight in entries) / total_weight


def sample_variance(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return statistics.variance(values)


def welch_mean_pvalue(with_values: list[float], without_values: list[float]) -> float | None:
    """Two-sided Welch t-test p-value (normal approximation)."""
    if len(with_values) < 2 or len(without_values) < 2:
        return None
    mean_with = statistics.mean(with_values)
    mean_without = statistics.mean(without_values)
    var_with = statistics.variance(with_values)
    var_without = statistics.variance(without_values)
    n_with = len(with_values)
    n_without = len(without_values)
    denom = var_with / n_with + var_without / n_without
    if denom == 0:
        return 1.0 if mean_with == mean_without else 0.0
    t_stat = (mean_with - mean_without) / math.sqrt(denom)
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t_stat) / math.sqrt(2))))
    return min(max(p, 0.0), 1.0)


def format_phase_targets(avg: float | None) -> str:
    if avg is None:
        return ""
    goal, cap, ceiling = slot_phase_targets(avg)
    return f"{goal}/{cap}/{ceiling}"


@dataclass
class ComparisonRow:
    permanent_id: str
    permanent_name: str
    analysis_kind: str
    slot_type: str
    canonical_front: str
    canonical_back: str
    investigator_name: str
    n_with: int
    n_without: int
    mean_with: float | None
    var_with: float | None
    mean_without: float | None
    var_without: float | None
    weighted_avg_with: float | None
    weighted_avg_without: float | None
    phase_targets_with: str
    phase_targets_without: str
    mean_diff: float | None
    weighted_avg_diff: float | None
    welch_pvalue: float | None
    generation_relevant: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "permanent_id": self.permanent_id,
            "permanent_name": self.permanent_name,
            "analysis_kind": self.analysis_kind,
            "slot_type": self.slot_type,
            "canonical_front": self.canonical_front,
            "canonical_back": self.canonical_back,
            "investigator_name": self.investigator_name,
            "n_with": self.n_with,
            "n_without": self.n_without,
            "mean_with": self.mean_with,
            "var_with": self.var_with,
            "mean_without": self.mean_without,
            "var_without": self.var_without,
            "weighted_avg_with": self.weighted_avg_with,
            "weighted_avg_without": self.weighted_avg_without,
            "phase_targets_with": self.phase_targets_with,
            "phase_targets_without": self.phase_targets_without,
            "mean_diff": self.mean_diff,
            "weighted_avg_diff": self.weighted_avg_diff,
            "welch_pvalue": self.welch_pvalue,
            "generation_relevant": self.generation_relevant,
        }


def compare_groups(
    *,
    permanent_id: str,
    analysis_kind: str,
    slot_type: str,
    investigator_name: str,
    canonical_front: str,
    canonical_back: str,
    with_entries: list[tuple[float, float]],
    without_entries: list[tuple[float, float]],
    min_with: int,
) -> ComparisonRow:
    name = PERMANENT_NAMES.get(permanent_id, permanent_id)
    with_values = [value for value, _weight in with_entries]
    without_values = [value for value, _weight in without_entries]
    mean_with = statistics.mean(with_values) if with_values else None
    mean_without = statistics.mean(without_values) if without_values else None
    weighted_avg_with = weighted_average(with_entries)
    weighted_avg_without = weighted_average(without_entries)
    var_with = sample_variance(with_values)
    var_without = sample_variance(without_values)
    mean_diff = (
        (mean_with - mean_without)
        if mean_with is not None and mean_without is not None
        else None
    )
    weighted_avg_diff = (
        (weighted_avg_with - weighted_avg_without)
        if weighted_avg_with is not None and weighted_avg_without is not None
        else None
    )
    pvalue = welch_mean_pvalue(with_values, without_values)
    generation_relevant = (
        len(with_values) >= min_with
        and weighted_avg_with is not None
        and weighted_avg_without is not None
        and generation_slot_targets_differ(weighted_avg_with, weighted_avg_without)
    )
    return ComparisonRow(
        permanent_id=permanent_id,
        permanent_name=name,
        analysis_kind=analysis_kind,
        slot_type=slot_type,
        canonical_front=canonical_front,
        canonical_back=canonical_back,
        investigator_name=investigator_name,
        n_with=len(with_values),
        n_without=len(without_values),
        mean_with=mean_with,
        var_with=var_with,
        mean_without=mean_without,
        var_without=var_without,
        weighted_avg_with=weighted_avg_with,
        weighted_avg_without=weighted_avg_without,
        phase_targets_with=format_phase_targets(weighted_avg_with),
        phase_targets_without=format_phase_targets(weighted_avg_without),
        mean_diff=mean_diff,
        weighted_avg_diff=weighted_avg_diff,
        welch_pvalue=pvalue,
        generation_relevant=generation_relevant,
    )


def run_analysis(
    prepared: list[Any],
    *,
    engine: ArkhamPopularityEngine,
    cards: dict[str, dict[str, Any]],
    canonical_cards: dict[str, Any],
    mapper: CanonicalMapper,
    min_with: int = 5,
) -> list[ComparisonRow]:
    rows: list[ComparisonRow] = []

    by_investigator: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for deck in prepared:
        if deck.is_ignore or deck.cycle is None:
            continue
        by_investigator[(deck.canonical_front, deck.canonical_back)].append(deck)

    for (canonical_front, canonical_back), inv_decks in sorted(
        by_investigator.items()
    ):
        inv_name = inv_decks[0].investigator_name if inv_decks else canonical_front
        user_weights = engine.assign_user_weights(prepared)
        cycle_weights = engine.assign_cycle_weights(inv_decks, user_weights)
        slot_totals_by_deck = [
            deck_asset_slot_totals(
                deck.slots, cards=cards, canonical_cards=canonical_cards
            )
            for deck in inv_decks
        ]

        def split_entries(
            permanent_id: str, slot_type: str
        ) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
            with_entries: list[tuple[float, float]] = []
            without_entries: list[tuple[float, float]] = []
            for deck, slot_totals in zip(inv_decks, slot_totals_by_deck):
                weight = engine.deck_weight(deck, user_weights, cycle_weights)
                if not weight:
                    continue
                value = float(slot_totals.get(slot_type, 0.0))
                entry = (value, weight)
                if permanent_in_deck(deck.slots, permanent_id, mapper):
                    with_entries.append(entry)
                else:
                    without_entries.append(entry)
            return with_entries, without_entries

        for permanent_id, slot_types in SLOT_PERMANENTS.items():
            for slot_type in slot_types:
                with_entries, without_entries = split_entries(permanent_id, slot_type)
                if not with_entries or not without_entries:
                    continue
                rows.append(
                    compare_groups(
                        permanent_id=permanent_id,
                        analysis_kind="slot_permanent",
                        slot_type=slot_type,
                        investigator_name=inv_name,
                        canonical_front=canonical_front,
                        canonical_back=canonical_back,
                        with_entries=with_entries,
                        without_entries=without_entries,
                        min_with=min_with,
                    )
                )

        for permanent_id in DECK_SIZE_PERMANENTS:
            for slot_type in STANDARD_ASSET_SLOT_TYPES:
                with_entries, without_entries = split_entries(permanent_id, slot_type)
                if not with_entries or not without_entries:
                    continue
                rows.append(
                    compare_groups(
                        permanent_id=permanent_id,
                        analysis_kind="deck_size_permanent",
                        slot_type=slot_type,
                        investigator_name=inv_name,
                        canonical_front=canonical_front,
                        canonical_back=canonical_back,
                        with_entries=with_entries,
                        without_entries=without_entries,
                        min_with=min_with,
                    )
                )

    return rows


def print_summary(rows: list[ComparisonRow], *, min_with: int) -> None:
    relevant = [row for row in rows if row.generation_relevant]
    stat_sig_not_relevant = [
        row
        for row in rows
        if not row.generation_relevant
        and row.welch_pvalue is not None
        and row.welch_pvalue < 0.05
        and row.n_with >= min_with
        and row.weighted_avg_diff is not None
        and abs(row.weighted_avg_diff) >= 0.25
    ]
    print(f"Comparisons run: {len(rows)}")
    print(
        f"Generation-relevant (different phase targets, n_with>={min_with}): "
        f"{len(relevant)}"
    )
    print(
        f"Statistically different but same phase targets: {len(stat_sig_not_relevant)}"
    )
    print("  (phase targets = phase1_goal/phase1_cap/phase2_ceiling)")
    print()
    if not relevant:
        print("No generation-relevant differences under default thresholds.")
    else:
        print("Generation-relevant (sorted by |weighted_avg_diff|):")
        for row in sorted(
            relevant,
            key=lambda r: -abs(r.weighted_avg_diff or 0.0),
        )[:40]:
            line = (
                f"  {row.investigator_name} ({row.canonical_front}): "
                f"{row.permanent_name} [{row.analysis_kind}] {row.slot_type} "
                f"E_with={row.weighted_avg_with:.2f} ({row.phase_targets_with}) vs "
                f"E_without={row.weighted_avg_without:.2f} ({row.phase_targets_without}) "
                f"n={row.n_with}"
            )
            print(line.encode("ascii", errors="replace").decode("ascii"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare asset slot usage with vs without permanents."
    )
    parser.add_argument(
        "--card-json",
        type=Path,
        default=Path("card_json.pickle"),
    )
    parser.add_argument(
        "--decklist-json",
        type=Path,
        default=Path("decklist_json.pickle"),
    )
    parser.add_argument(
        "--taboo-json",
        type=Path,
        default=Path("taboo.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("permanent_slot_analysis.csv"),
    )
    parser.add_argument("--min-with", type=int, default=5)
    args = parser.parse_args()

    with args.card_json.open("rb") as handle:
        cards = pickle.load(handle)
    with args.decklist_json.open("rb") as handle:
        decklists = pickle.load(handle)
    with args.taboo_json.open(encoding="utf-8") as handle:
        taboo_json = json.load(handle)

    load_permanent_names(cards)
    mapper = CanonicalMapper(cards, chapter=1)
    engine = ArkhamPopularityEngine(cards, mapper, taboo_json)
    prepared = engine.prepare_all(decklists)
    canonical_cards = build_canonical_card_infos(cards, mapper, engine.taboo)

    rows = run_analysis(
        prepared,
        engine=engine,
        cards=cards,
        canonical_cards=canonical_cards,
        mapper=mapper,
        min_with=args.min_with,
    )

    fieldnames = list(
        ComparisonRow(
            permanent_id="",
            permanent_name="",
            analysis_kind="",
            slot_type="",
            canonical_front="",
            canonical_back="",
            investigator_name="",
            n_with=0,
            n_without=0,
            mean_with=None,
            var_with=None,
            mean_without=None,
            var_without=None,
            weighted_avg_with=None,
            weighted_avg_without=None,
            phase_targets_with="",
            phase_targets_without="",
            mean_diff=None,
            weighted_avg_diff=None,
            welch_pvalue=None,
            generation_relevant=False,
        ).to_dict().keys()
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())

    print_summary(rows, min_with=args.min_with)
    print(f"\nWrote {args.output.resolve()}")


if __name__ == "__main__":
    main()
