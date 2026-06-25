# -*- coding: utf-8 -*-
"""Export 12 tables: at fixed inv_cycle=D, slot-share by card cycle k vs Decklist.cycle C.

Writes one CSV per D to --out-dir (default inv_cycle_pivots/).
Rows = Decklist.cycle C; columns = k_1 .. k_12 (share of weighted slot copies).
Cells with k > C are left blank. Companion *_counts.csv has deck counts per (C, D).
"""

from __future__ import annotations

import argparse
import csv
import json
import pickle
from collections import defaultdict
from pathlib import Path

from arkham_canonical import MAX_CYCLE, CanonicalMapper
from arkham_popularity import ArkhamPopularityEngine, InvCycleIndex


def build_pivot(
    engine: ArkhamPopularityEngine,
    prepared: list,
    mapper: CanonicalMapper,
) -> tuple[
    dict[int, dict[int, dict[int, float]]],
    dict[tuple[int, int], int],
]:
    """Return pivot[D][C][k] weighted slot copies and deck counts per (C, D)."""
    user_weights = engine.assign_user_weights(prepared)
    active = engine.training_pool_decks(prepared)
    cycle_weights = engine.assign_cycle_weights(active, user_weights)
    inv_index = (
        InvCycleIndex(mapper, active) if engine.bias_compensation else None
    )

    pivot: dict[int, dict[int, dict[int, float]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(float))
    )
    deck_counts: dict[tuple[int, int], int] = defaultdict(int)

    for deck in active:
        c = deck.cycle
        d = mapper.cycle_for_slot(deck.canonical_front)
        if d is None or c is None:
            continue
        weight = engine.investigator_deck_weight(
            deck, user_weights, cycle_weights, inv_index
        )
        if not weight:
            continue
        deck_counts[(c, d)] += 1
        for canonical_id, copies in deck.slots.items():
            k = mapper.cycle_for_slot(canonical_id)
            if k is None or k > c:
                continue
            pivot[d][c][k] += weight * copies

    return pivot, deck_counts


def write_d_table(
    path: Path,
    inv_cycle: int,
    d_slice: dict[int, dict[int, float]],
    deck_counts: dict[tuple[int, int], int],
) -> None:
    k_cols = [f"k_{k}" for k in range(1, MAX_CYCLE + 1)]
    fieldnames = ["Decklist.cycle_C", "deck_count"] + k_cols
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for c in sorted(d_slice):
            total = sum(d_slice[c].values())
            if total <= 0:
                continue
            row: dict[str, str | int | float] = {
                "Decklist.cycle_C": c,
                "deck_count": deck_counts.get((c, inv_cycle), 0),
            }
            for k in range(1, MAX_CYCLE + 1):
                key = f"k_{k}"
                if k > c:
                    row[key] = ""
                else:
                    row[key] = round(d_slice[c].get(k, 0.0) / total, 6)
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default="inv_cycle_pivots",
        help="directory for D=1..12 CSV files",
    )
    parser.add_argument("--card-json", default="card_json.pickle")
    parser.add_argument("--decklist-json", default="decklist_json.pickle")
    parser.add_argument("--taboo", default="taboo.json")
    args = parser.parse_args()

    with open(args.card_json, "rb") as handle:
        cards = pickle.load(handle)
    with open(args.decklist_json, "rb") as handle:
        decklists = pickle.load(handle)
    with open(args.taboo, encoding="utf-8") as handle:
        taboo = json.load(handle)

    mapper = CanonicalMapper(cards, chapter=1)
    engine = ArkhamPopularityEngine(cards, mapper, taboo)
    prepared = engine.prepare_all(decklists)
    pivot, deck_counts = build_pivot(engine, prepared, mapper)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    readme = out_dir / "README.txt"
    readme.write_text(
        "inv_cycle_pivots: fixed inv_cycle=D, rows=Decklist.cycle C, columns=k_1..k_12.\n"
        "Values = weighted slot-copy share (investigator_deck_weight). "
        "Blank where k > C (card not in pool).\n"
        "All slots with defined CanonicalCard.cycle; k > Decklist.cycle excluded.\n"
        "Decks: published training pool only (see spec.md Published training pool).\n",
        encoding="utf-8",
    )

    for d in range(1, MAX_CYCLE + 1):
        if d not in pivot:
            path = out_dir / f"inv_cycle_{d:02d}.csv"
            path.write_text(
                "Decklist.cycle_C,deck_count\n",
                encoding="utf-8",
            )
            continue
        path = out_dir / f"inv_cycle_{d:02d}.csv"
        write_d_table(path, d, pivot[d], deck_counts)
        print(f"Wrote {path} ({len(pivot[d])} C rows)")

    print(f"\nDone. See {out_dir}/")


if __name__ == "__main__":
    main()
