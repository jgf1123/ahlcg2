# -*- coding: utf-8 -*-
"""Analyze Decklist.cycle vs CanonicalCard.cycle vs investigator cycle."""

from __future__ import annotations

import json
import pickle
from collections import defaultdict

from arkham_canonical import CanonicalMapper, MAX_CYCLE, parse_investigator_front_back
from arkham_popularity import ArkhamPopularityEngine

CHAPTER_1_MAX = 12


def pct(n: float, d: float) -> float:
    return 100.0 * n / d if d else 0.0


def main() -> None:
    with open("decklist_json.pickle", "rb") as f:
        decklist_json = pickle.loads(f.read())
    decklist_json = {k: v for k, v in decklist_json.items() if v}
    with open("card_json.pickle", "rb") as f:
        card_json = pickle.load(f)
    with open("taboo.json", encoding="utf-8") as f:
        taboo_json = json.load(f)

    mapper = CanonicalMapper(card_json, chapter=1)
    engine = ArkhamPopularityEngine(card_json, mapper, taboo_json)
    prepared = engine.prepare_all(decklist_json)

    active = [d for d in prepared if not d.is_ignore and d.cycle is not None]
    print(f"Active decks (non-ignored, cycle defined): {len(active):,}\n")

    # --- 1. Slot-copy composition by Decklist.cycle ---
    pivot: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    deck_count: dict[int, int] = defaultdict(int)
    inv_cycle_count: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    for deck in active:
        dc = deck.cycle
        deck_count[dc] += 1
        inv_cycle = mapper.cycle_for_slot(deck.canonical_front)
        if inv_cycle is not None:
            inv_cycle_count[dc][inv_cycle] += 1

        for canonical_id, num in deck.slots.items():
            card_cycle = mapper.cycle_for_slot(canonical_id)
            if card_cycle is None:
                continue
            pivot[dc][card_cycle] += num

    print("=" * 72)
    print("1. DECK COUNTS BY Decklist.cycle")
    print("=" * 72)
    for c in sorted(deck_count):
        print(f"  cycle {c:2d}: {deck_count[c]:5,} decks")

    print("\n" + "=" * 72)
    print("2. SLOT-COPY SHARE BY CanonicalCard.cycle (rows=Decklist.cycle, % of row)")
    print("   Conjecture: elevated col 1; cols 2..C similar if utility flat; col C novelty bump")
    print("=" * 72)

    card_cycles = sorted({cc for row in pivot.values() for cc in row if cc <= CHAPTER_1_MAX})
    header = "deck\\card " + "".join(f"{c:6d}" for c in card_cycles) + "   C-share  novelty"
    print(header)

    novelty_ratios: dict[int, float] = {}
    core_shares: dict[int, float] = {}

    for dc in sorted(pivot):
        row_total = sum(pivot[dc].get(cc, 0) for cc in card_cycles)
        if not row_total:
            continue
        cells = []
        for cc in card_cycles:
            share = pct(pivot[dc].get(cc, 0), row_total)
            cells.append(f"{share:5.1f}%")
        c_share = pct(pivot[dc].get(dc, 0), row_total)
        core_shares[dc] = pct(pivot[dc].get(1, 0), row_total)

        # Novelty: share at C vs mean share of cycles 2..C (excluding 1 and C)
        mid_cycles = [cc for cc in card_cycles if 2 <= cc < dc]
        if mid_cycles and dc in pivot[dc]:
            mean_mid = sum(pct(pivot[dc].get(cc, 0), row_total) for cc in mid_cycles) / len(
                mid_cycles
            )
            novelty = c_share / mean_mid if mean_mid else float("nan")
        else:
            novelty = float("nan")
        novelty_ratios[dc] = novelty

        print(
            f"  {dc:2d}      "
            + "".join(f"{v:>7}" for v in cells)
            + f"  {c_share:5.1f}%  {novelty:5.2f}x"
        )

    print("\n  C-share = % slot copies from same cycle as deck")
    print("  novelty = C-share / mean(share for cycles 2..C-1)")

    print("\n" + "=" * 72)
    print("3. CORE (cycle 1) SHARE vs DECK CYCLE")
    print("=" * 72)
    for dc in sorted(core_shares):
        print(f"  Decklist.cycle {dc:2d}: {core_shares[dc]:5.1f}% from Core")

    print("\n" + "=" * 72)
    print("4. INVESTIGATOR CYCLE vs DECKLIST.CYCLE (deck counts, % of row)")
    print("   Conjecture: diagonal elevated (novelty: play new investigators)")
    print("=" * 72)

    inv_cycles = sorted({ic for row in inv_cycle_count.values() for ic in row})
    print("deck\\inv  " + "".join(f"{c:6d}" for c in inv_cycles) + "  match%")
    for dc in sorted(inv_cycle_count):
        row_total = deck_count[dc]
        match = inv_cycle_count[dc].get(dc, 0)
        cells = [
            f"{pct(inv_cycle_count[dc].get(ic, 0), row_total):5.1f}%"
            for ic in inv_cycles
        ]
        print(
            f"  {dc:2d}     "
            + "".join(f"{v:>7}" for v in cells)
            + f"  {pct(match, row_total):5.1f}%"
        )

    print("\n" + "=" * 72)
    print("5. CYCLE 7 INVESTIGATOR STARTER SALIENCE")
    print("   Among decks with inv_cycle=7, card-cycle composition vs all decks")
    print("=" * 72)

    starter_slots: dict[int, int] = defaultdict(int)
    other_slots: dict[int, int] = defaultdict(int)
    starter_decks = 0
    for deck in active:
        inv_cycle = mapper.cycle_for_slot(deck.canonical_front)
        target = starter_slots if inv_cycle == 7 else other_slots
        if inv_cycle == 7:
            starter_decks += 1
        for canonical_id, num in deck.slots.items():
            card_cycle = mapper.cycle_for_slot(canonical_id)
            if card_cycle is None:
                continue
            target[card_cycle] += num

    starter_total = sum(starter_slots.values())
    other_total = sum(other_slots.values())
    print(f"  Decks with inv_cycle=7: {starter_decks:,}")
    print(f"  Slot copies (starter inv): {starter_total:,} | (other inv): {other_total:,}")
    print("\n  card_cycle   starter%   other%   ratio(starter/other)")
    for cc in range(1, CHAPTER_1_MAX + 1):
        s = pct(starter_slots[cc], starter_total)
        o = pct(other_slots[cc], other_total)
        ratio = s / o if o else float("nan")
        print(f"  {cc:10d}   {s:6.1f}%   {o:6.1f}%   {ratio:6.2f}x")

    # Starter-tagged cards: cards only in cycle-7 packs among player cards
    starter_only_cards = {
        cid
        for cid, card in card_json.items()
        if card.get("pack_code") in {"nat", "har", "win", "jac", "ste"}
        and card.get("type_code") != "investigator"
        and mapper.cycle_for_slot(cid) == 7
    }
    starter_pack_usage = 0
    all_usage = 0
    for deck in active:
        for canonical_id, num in deck.slots.items():
            if mapper.cycle_for_slot(canonical_id) != 7:
                continue
            all_usage += num
            if canonical_id in starter_only_cards or card_json.get(canonical_id, {}).get(
                "pack_code"
            ) in {"nat", "har", "win", "jac", "ste"}:
                starter_pack_usage += num

    print(
        f"\n  Cycle-7 slot copies from starter-deck packs: "
        f"{pct(starter_pack_usage, all_usage):.1f}% of all cycle-7 card slots"
    )

    print("\n" + "=" * 72)
    print("6. WITHIN-DECK CYCLE DISPERSION (median |card_cycle - deck_cycle|)")
    print("=" * 72)
    deviations: dict[int, list[float]] = defaultdict(list)
    for deck in active:
        dc = deck.cycle
        for canonical_id, num in deck.slots.items():
            cc = mapper.cycle_for_slot(canonical_id)
            if cc is None:
                continue
            for _ in range(num):
                deviations[dc].append(abs(cc - dc))

    for dc in sorted(deviations):
        vals = sorted(deviations[dc])
        mid = vals[len(vals) // 2]
        print(f"  Decklist.cycle {dc:2d}: median |card-deck| = {mid:.0f} cycles")

    print("\n" + "=" * 72)
    print("7. SUMMARY: SUPPORT FOR CONJECTURES")
    print("=" * 72)

    # Core elevated?
    avg_core_high_cycles = sum(core_shares[c] for c in range(5, 12)) / 7
    print(
        f"  Core share: cycle-1 decks {core_shares.get(1, 0):.1f}% vs "
        f"cycles 5-11 avg {avg_core_high_cycles:.1f}% "
        f"({'supports' if core_shares.get(1, 0) > avg_core_high_cycles else 'weak'})"
    )

    # Mid cycles similar?
    print("  Mid-cycle uniformity (cycles 2..C-1 CV):")
    for dc in [5, 8, 11]:
        if dc not in pivot:
            continue
        row_total = sum(pivot[dc].values())
        mids = [pivot[dc].get(cc, 0) / row_total for cc in range(2, dc)]
        if len(mids) < 2:
            continue
        mean = sum(mids) / len(mids)
        var = sum((x - mean) ** 2 for x in mids) / len(mids)
        cv = (var**0.5 / mean) if mean else 0
        print(f"    Decklist.cycle {dc}: CV={cv:.2f} ({'fairly uniform' if cv < 0.35 else 'uneven'})")

    # Novelty
    strong_novelty = [dc for dc, r in novelty_ratios.items() if r == r and r >= 1.3]
    print(
        f"  Card novelty (C-share >= 1.3x mid-cycle mean): cycles {strong_novelty}"
    )

    # Inv match diagonal
    diag = [pct(inv_cycle_count[dc].get(dc, 0), deck_count[dc]) for dc in deck_count]
    off_diag_avg = []
    for dc in sorted(inv_cycle_count):
        total = deck_count[dc]
        off = sum(
            inv_cycle_count[dc].get(ic, 0)
            for ic in inv_cycles
            if ic != dc
        )
        off_diag_avg.append(pct(off, total) / max(len(inv_cycles) - 1, 1))
    avg_match = sum(pct(inv_cycle_count[dc].get(dc, 0), deck_count[dc]) for dc in deck_count) / len(
        deck_count
    )
    avg_off = sum(off_diag_avg) / len(off_diag_avg) if off_diag_avg else 0
    print(
        f"  Investigator match on diagonal: avg {avg_match:.1f}% vs "
        f"avg off-diagonal cell {avg_off:.1f}%"
    )


if __name__ == "__main__":
    main()
