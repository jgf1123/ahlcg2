# -*- coding: utf-8 -*-
"""Check decklists for deck_limit / copy-count violations."""

from __future__ import annotations

import json
import pickle
from collections import Counter, defaultdict
from pathlib import Path

from arkham_popularity import (
    ArkhamPopularityEngine,
    KNOWN_JOKE_DECKLIST_IDS,
    build_taboo_card_lookup,
    deck_limit_violations,
    effective_deck_limit,
)
from arkham_canonical import CanonicalMapper, build_canonical_map

ROOT = Path(__file__).resolve().parent
CARD_JSON = ROOT / "card_json.pickle"
DECKLIST_JSON = ROOT / "decklist_json.pickle"
TABOO_JSON = ROOT / "taboo.json"
JOKE_IDS = set(KNOWN_JOKE_DECKLIST_IDS)


def check_decklist(
    decklist: dict,
    card_json: dict,
    taboo_lookup: dict[int, dict[str, dict]],
) -> list[dict]:
    """Return violation records for one decklist."""
    violations: list[dict] = []
    for row in deck_limit_violations(decklist, card_json, taboo_lookup):
        violations.append({"kind": "card_id", **row})

    # Per name (sum copies of all printings with same name)
    by_name: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for card_code, count in slots.items():
        if card_code not in card_json:
            continue
        name = card_json[card_code].get("name") or card_code
        by_name[name].append((card_code, count))

    for name, entries in by_name.items():
        total = sum(c for _, c in entries)
        # Use the strictest applicable limit among printings present
        limits = []
        for card_code, _ in entries:
            card = card_json[card_code]
            limits.append(effective_deck_limit(card, taboo_id, taboo_lookup))
        limit = min(limits) if limits else None
        if limit is not None and total > limit:
            violations.append(
                {
                    "kind": "name",
                    "name": name,
                    "card_codes": entries,
                    "count": total,
                    "limit": limit,
                }
            )

    return violations


def main() -> None:
    card_json = pickle.loads(CARD_JSON.read_bytes())
    decklist_json = pickle.loads(DECKLIST_JSON.read_bytes())
    taboo_lookup = build_taboo_card_lookup(
        json.loads(TABOO_JSON.read_text(encoding="utf-8"))
    )

    # Non-blank: drop None/empty; keep is_ignore decks
    non_blank = {
        deck_id: deck
        for deck_id, deck in decklist_json.items()
        if deck
    }
    print(f"Total decklists in pickle: {len(decklist_json)}")
    print(f"Non-blank decklists: {len(non_blank)}")
    print(f"Known joke ids still present: {sorted(JOKE_IDS & non_blank.keys())}")

    card_id_violations: list[tuple] = []
    name_violations: list[tuple] = []

    for deck_id, deck in non_blank.items():
        violations = check_decklist(deck, card_json, taboo_lookup)
        for v in violations:
            if v["kind"] == "card_id":
                card_id_violations.append((deck_id, v))
            else:
                name_violations.append((deck_id, v))

    # Also flag via prepared is_ignore for cross-check
    mapper = CanonicalMapper(card_json, chapter=1)
    engine = ArkhamPopularityEngine(card_json, mapper, json.loads(TABOO_JSON.read_text(encoding="utf-8")))
    prepared = {d.decklist_id: d for d in engine.prepare_all(non_blank)}

    print()
    print("=== Per card_id (count > deck_limit for that printing) ===")
    print(f"Violating decklists: {len({d for d, _ in card_id_violations})}")
    print(f"Total violations: {len(card_id_violations)}")
    by_card = Counter(v["card_code"] for _, v in card_id_violations)
    print("Top cards by violation count:")
    for code, n in by_card.most_common(20):
        c = card_json[code]
        print(f"  {code} {c.get('name')!r} deck_limit={c.get('deck_limit')}: {n} decks")

    print()
    print("=== Per name (sum of printings > limit) ===")
    print(f"Violating decklists: {len({d for d, _ in name_violations})}")
    print(f"Total violations: {len(name_violations)}")
    by_name = Counter(v["name"] for _, v in name_violations)
    print("Top names by violation count:")
    for name, n in by_name.most_common(20):
        print(f"  {name!r}: {n} decks")

    # Decklists violating by name but not already removed as jokes
    violating_ids = sorted({d for d, _ in name_violations})
    print()
    print(f"All name-level violating deck ids ({len(violating_ids)}):")
    for deck_id in violating_ids[:50]:
        deck = non_blank[deck_id]
        inv = prepared.get(deck_id)
        ignore = inv.is_ignore if inv else "?"
        vios = [v for d, v in name_violations if d == deck_id]
        print(f"  {deck_id}: {deck.get('name')!r} inv={deck.get('investigator_name')!r} taboo={deck.get('taboo_id')} is_ignore={ignore}")
        for v in vios:
            print(f"    {v['name']!r}: {v['count']} copies (limit {v['limit']}) {v['card_codes']}")
    print()
    print("=== Active decks (is_ignore=False) with card_id violations ===")
    active_ids = sorted(
        {
            deck_id
            for deck_id, v in card_id_violations
            if deck_id in prepared and not prepared[deck_id].is_ignore
        }
    )
    print(f"Count: {len(active_ids)}")
    by_active_card = Counter(
        v["card_code"]
        for deck_id, v in card_id_violations
        if deck_id in prepared and not prepared[deck_id].is_ignore
    )
    for code, n in by_active_card.most_common(20):
        c = card_json[code]
        print(f"  {code} {c.get('name')!r} deck_limit={c.get('deck_limit')}: {n} decks")
    for deck_id in active_ids:
        deck = non_blank[deck_id]
        vios = [v for d, v in card_id_violations if d == deck_id]
        parts = [f"{v['count']}x {v['name']!r} (limit {v['limit']})" for v in vios]
        print(f"  {deck_id}: {deck.get('name')!r} -> {', '.join(parts)}")

    print(f"Active violating deck ids ({len(active_ids)}): {active_ids}")

    # Worst ratio violations (likely jokes)
    ratios = []
    for deck_id, v in card_id_violations:
        ratio = v["count"] / max(v["limit"], 1)
        ratios.append((ratio, deck_id, v, non_blank[deck_id], prepared.get(deck_id)))
    ratios.sort(key=lambda x: x[0], reverse=True)
    print()
    print("=== Top 30 worst count/limit ratios (card_id) ===")
    for ratio, deck_id, v, deck, prep in ratios[:30]:
        ign = prep.is_ignore if prep else "?"
        print(
            f"  {deck_id}: {v['count']}x {v['name']!r} ({v['card_code']}) "
            f"limit={v['limit']} ratio={ratio:.1f} ignore={ign} deck={deck.get('name')!r}"
        )

    for jid in sorted(JOKE_IDS):
        deck = non_blank.get(jid)
        print()
        if deck is None:
            print(f"Known joke {jid}: not in pickle")
            continue
        print(f"Known joke {jid}: {deck.get('name')!r}")
        vios = [(d, v) for d, v in card_id_violations if d == jid]
        if not vios:
            print("  No card_id deck_limit violations")
        for _, v in vios:
            print(f"  {v['count']}x {v['name']!r} ({v['card_code']}) limit={v['limit']}")

    # Extreme violations (likely jokes not yet on blocklist)
    joke_like = []
    by_deck: dict[int, list] = defaultdict(list)
    for deck_id, v in card_id_violations:
        by_deck[deck_id].append(v)
    for deck_id, vios in by_deck.items():
        max_count = max(v["count"] for v in vios)
        max_ratio = max(v["count"] / max(v["limit"], 1) for v in vios)
        if max_count >= 4 or max_ratio >= 3:
            joke_like.append(
                (max_ratio, max_count, deck_id, non_blank[deck_id].get("name"), vios)
            )
    joke_like.sort(reverse=True)
    print()
    print(f"=== Joke-like decks (count>=4 or count/limit>=3): {len(joke_like)} ===")
    for ratio, max_count, deck_id, name, vios in joke_like:
        prep = prepared.get(deck_id)
        ign = prep.is_ignore if prep else "?"
        print(f"  {deck_id}: {name!r} max_count={max_count} ratio={ratio:.1f} ignore={ign}")
        for v in vios:
            print(f"    {v['count']}x {v['name']!r} limit={v['limit']}")


import sys

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
