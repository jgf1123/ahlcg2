# -*- coding: utf-8 -*-
"""Iterate Charlie Kane deck quality classification with improved rules."""

from __future__ import annotations

import json
import pickle
from collections import Counter, defaultdict

from arkham_canonical import CanonicalMapper
from arkham_deck_options import (
    DeckOptionsValidator,
    _card_matches_option_criteria,
    card_faction_codes,
    counts_toward_player_deck_size,
    effective_deck_size_from_slots,
    is_illegal_encounter_card_in_player_deck,
    merge_deck_options_with_permanents,
)
from arkham_popularity import (
    ArkhamPopularityEngine,
    _effective_xp,
    build_taboo_card_lookup,
    card_restricted_to_investigator,
    deck_limit_violations,
)

INV = "09018"
REQUIREMENTS = {"09019", "09020"}
BASE_DECK_SIZE = 30
CANDIDATE_FACTIONS = {"guardian", "seeker", "rogue", "mystic", "survivor"}

# User-confirmed low-effort / joke decklist_ids
CONFIRMED_JOKE_IDS = frozenset({40916, 45966, 39497})
# Not actually this investigator's deck (e.g. Barkham placeholder on Charlie shell)
EXCLUDED_DECKLIST_IDS = frozenset({48218})


def parse_meta(deck: dict) -> dict | None:
    raw = deck.get("meta") or ""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def meta_factions(meta: dict | None) -> tuple[str | None, str | None, str | None]:
    """Return (f1, f2, meta_issue). issue describes selection problems."""
    if meta is None:
        return None, None, "missing_meta"
    f1 = meta.get("faction_1")
    f2 = meta.get("faction_2")
    if f1 and f2:
        if f1 not in CANDIDATE_FACTIONS or f2 not in CANDIDATE_FACTIONS:
            return f1, f2, "invalid_faction"
        if f1 == f2:
            return f1, f2, "duplicate_class"
        return f1, f2, None
    # Legacy / UI-failed single field — not auto-resolvable
    if meta.get("faction_selected"):
        return meta["faction_selected"], None, "incomplete_meta"
    return None, None, "missing_factions"


def effective_deck_size(slots: dict, cards: dict, base: int = BASE_DECK_SIZE) -> int:
    return effective_deck_size_from_slots(slots, cards, base_size=base)


def player_card_count(slots: dict, cards: dict) -> int:
    total = 0
    for cid, copies in slots.items():
        if cid in REQUIREMENTS:
            continue
        card = cards.get(cid)
        if card is None:
            continue
        if counts_toward_player_deck_size(card):
            total += copies
    return total


def resolve_options(base_options: list, f1: str, f2: str) -> list:
    choices = iter([f1, f2])
    resolved = []
    for opt in base_options:
        if opt.get("faction_select"):
            faction = next(choices)
            new_opt = {
                k: v
                for k, v in opt.items()
                if k not in {"faction_select", "name", "id"}
            }
            new_opt["faction"] = [faction]
            resolved.append(new_opt)
        else:
            resolved.append(dict(opt))
    return resolved


def build_validator(
    base_options: list,
    f1: str,
    f2: str,
    slots: dict,
    cards: dict,
) -> DeckOptionsValidator:
    resolved = resolve_options(base_options, f1, f2)
    merged = merge_deck_options_with_permanents(resolved, slots, cards)
    return DeckOptionsValidator.from_options(merged)


def player_deck_card_ids(slots: dict, cards: dict) -> list[str]:
    """Non-weakness, non-signature player-deck cards with positive copies."""
    ids: list[str] = []
    for cid, copies in slots.items():
        if copies <= 0 or cid in REQUIREMENTS:
            continue
        card = cards.get(cid)
        if card is None:
            continue
        if card.get("type_code") in ("treachery", "enemy", "investigator"):
            continue
        if card.get("subtype_code") in ("basicweakness", "weakness"):
            continue
        ids.append(cid)
    return ids


def extra_off_class_card_ids(
    slots: dict,
    *,
    cards: dict,
    validator: DeckOptionsValidator,
    meta_set: set[str],
    prior_options: list,
) -> list[str]:
    """Card IDs not legal under meta classes, permanent grants, or dual-class."""
    offenders: list[str] = []
    for cid in player_deck_card_ids(slots, cards):
        card = cards[cid]
        if any(
            _card_matches_option_criteria(card, 0, prior)
            for prior in prior_options
        ):
            continue
        if card_allowed_under_options(card, validator, meta_set):
            continue
        offenders.append(cid)
    return offenders


def illegal_player_card_ids(
    slots: dict,
    *,
    cards: dict,
    validator: DeckOptionsValidator,
    meta_set: set[str],
) -> list[str]:
    illegal: list[str] = []
    for cid in player_deck_card_ids(slots, cards):
        card = cards[cid]
        if card_restricted_to_investigator(card, INV):
            illegal.append(f"{cid}(restricted)")
        elif not card_allowed_under_options(card, validator, meta_set):
            illegal.append(f"{cid}({card.get('name')})")
    return illegal


def card_allowed_under_options(
    card: dict,
    validator: DeckOptionsValidator,
    meta_factions_set: set[str],
) -> bool:
    """True if card is legal, including multi-class matching either meta class."""
    if validator.is_card_allowed(card, 0):
        return True
    # Multi-class: legal if ANY faction matches a meta class option
    factions = card_faction_codes(card)
    if len(factions) <= 1:
        return False
    for faction in factions & meta_factions_set:
        for opt in validator.deck_options:
            if opt.get("faction") == [faction]:
                if validator.card_matches_option(card, 0, opt):
                    return True
    return False


def taboo_violations_for_deck(
    slots: dict,
    taboo_id: int,
    engine: ArkhamPopularityEngine,
) -> list[str]:
    issues = []
    canonical = engine.merge_slots_to_canonical(slots)
    for cid in canonical:
        info = engine.canonical_cards.get(cid)
        card = engine.cards.get(cid)
        if info is None:
            issues.append(f"unknown:{cid}")
            continue
        if taboo_id not in info.taboo_set:
            issues.append(f"out_of_taboo_cycle:{cid}({card.get('name') if card else '?'})")
        if engine.taboo.is_forbidden(cid, taboo_id):
            issues.append(f"forbidden:{cid}({card.get('name') if card else '?'})")
    return issues


def classify_deck(
    decklist_id,
    deck: dict,
    *,
    cards: dict,
    engine: ArkhamPopularityEngine,
    taboo_lookup: dict,
    base_options: list,
    prior_options: list,
) -> dict:
    slots = deck.get("slots") or {}
    taboo_id = deck.get("taboo_id") or 0
    meta = parse_meta(deck)
    f1, f2, meta_issue = meta_factions(meta)

    violations: list[str] = []
    notes: list[str] = []

    if decklist_id in CONFIRMED_JOKE_IDS:
        violations.append("confirmed_joke")
    if decklist_id in EXCLUDED_DECKLIST_IDS:
        violations.append("excluded_deck")

    target_size = effective_deck_size(slots, cards)
    pc = player_card_count(slots, cards)
    if pc != target_size:
        violations.append(f"deck_size:{pc}!={target_size}")

    for req in REQUIREMENTS:
        if slots.get(req, 0) < 1:
            violations.append(f"missing_requirement:{req}")

    for row in deck_limit_violations(deck, cards, taboo_lookup):
        violations.append(
            f"deck_limit:{row['card_code']}:{row['count']}>{row['limit']}"
        )

    for cid, copies in slots.items():
        card = cards.get(cid)
        if card is None or copies <= 0 or cid in REQUIREMENTS:
            continue
        if card.get("subtype_code") in ("basicweakness", "weakness"):
            continue
        if is_illegal_encounter_card_in_player_deck(card):
            violations.append(f"illegal_encounter_card:{cid}")

    taboo_issues = taboo_violations_for_deck(slots, taboo_id, engine)
    violations.extend(taboo_issues)

    if meta_issue:
        violations.append(f"meta:{meta_issue}")

    # Card legality when meta is complete and valid
    if f1 and f2 and not meta_issue:
        validator = build_validator(base_options, f1, f2, slots, cards)
        meta_set = {f1, f2}

        extra_ids = extra_off_class_card_ids(
            slots,
            cards=cards,
            validator=validator,
            meta_set=meta_set,
            prior_options=prior_options,
        )
        if extra_ids:
            violations.append(f"extra_off_class:{','.join(extra_ids)}")

        illegal = illegal_player_card_ids(
            slots, cards=cards, validator=validator, meta_set=meta_set
        )
        if illegal:
            violations.append("illegal_card:" + ";".join(illegal[:6]))

    # Quality tier
    if (
        "confirmed_joke" in violations
        or "excluded_deck" in violations
        or any(v.startswith("deck_size:") for v in violations)
        or any(v.startswith("meta:") for v in violations)
    ):
        tier = "low_effort"
    elif violations:
        only_soft = all(
            v.startswith(("out_of_taboo_cycle", "missing_requirement"))
            for v in violations
        )
        tier = "reasonable_effort_fixable" if only_soft else "illegal"
    else:
        tier = "legal"

    return {
        "decklist_id": decklist_id,
        "name": deck.get("name"),
        "meta": meta,
        "f1": f1,
        "f2": f2,
        "player_count": pc,
        "target_size": target_size,
        "violations": violations,
        "tier": tier,
        "notes": notes,
    }


def taboo_cycle_rows(slots, deck_taboo_id, engine):
    rows = []
    max_taboo = engine.taboo.max_taboo
    for cid in sorted(engine.merge_slots_to_canonical(slots)):
        info = engine.canonical_cards.get(cid)
        card = engine.cards.get(cid)
        if info is None or card is None:
            continue
        if deck_taboo_id in info.taboo_set:
            continue
        rows.append(
            {
                "card_id": cid,
                "name": card.get("name", cid),
                "xp_at_deck_taboo": _effective_xp(
                    card, cid, deck_taboo_id, engine.taboo
                ),
                "xp_at_current_taboo": _effective_xp(
                    card, cid, max_taboo, engine.taboo
                ),
                "deck_taboo_id": deck_taboo_id,
                "current_taboo_id": max_taboo,
            }
        )
    return rows


def violations_to_kinds(violations: list[str], *, cards: dict) -> dict[str, list]:
    kinds: dict[str, list] = defaultdict(list)
    for v in violations:
        kind, _, rest = v.partition(":")
        if kind == "extra_off_class":
            for cid in rest.split(","):
                card = cards.get(cid, {})
                kinds[kind].append(
                    {"card_id": cid, "name": card.get("name", cid)}
                )
        elif kind == "illegal_card":
            kinds[kind].extend(rest.split(";"))
        else:
            kinds[kind].append(rest or v)
    if any(v == "confirmed_joke" for v in violations):
        kinds["confirmed_joke"].append("user-flagged joke")
    if any(v == "excluded_deck" for v in violations):
        kinds["excluded_deck"].append("not investigator deck")
    return dict(kinds)


def load_charlie_context():
    cards = pickle.load(open("card_json.pickle", "rb"))
    raw = pickle.load(open("decklist_json.pickle", "rb"))
    taboo_json = json.load(open("taboo.json", encoding="utf-8"))
    taboo_lookup = build_taboo_card_lookup(taboo_json)
    mapper = CanonicalMapper(cards, chapter=1)
    engine = ArkhamPopularityEngine(cards, mapper, taboo_json)
    base_options = cards[INV]["deck_options"]
    prior_options = []
    for opt in base_options:
        if opt.get("faction_select"):
            break
        prior_options.append(opt)
    return cards, raw, taboo_lookup, engine, base_options, prior_options


def classify_all_charlie():
    cards, raw, taboo_lookup, engine, base_options, prior_options = load_charlie_context()
    results = []
    for did, deck in raw.items():
        if not deck or deck.get("investigator_code") != INV:
            continue
        results.append(
            classify_deck(
                did,
                deck,
                cards=cards,
                engine=engine,
                taboo_lookup=taboo_lookup,
                base_options=base_options,
                prior_options=prior_options,
            )
        )
    return cards, raw, engine, results


def print_summary(results: list[dict], raw: dict, engine: ArkhamPopularityEngine) -> None:
    by_tier = defaultdict(list)
    for r in results:
        by_tier[r["tier"]].append(r["decklist_id"])

    print(f"Charlie decks: {len(results)}")
    for tier in sorted(by_tier, key=lambda tier: -len(by_tier[tier])):
        print(f"  {tier}: {len(by_tier[tier])}")

    by_kind = defaultdict(list)
    for r in results:
        if r["tier"] == "legal":
            continue
        for v in r["violations"]:
            kind = v.split(":", 1)[0]
            if r["decklist_id"] not in by_kind[kind]:
                by_kind[kind].append(r["decklist_id"])

    print("\n--- Violation kinds (non-legal only) ---")
    for kind in sorted(by_kind, key=lambda k: -len(by_kind[k])):
        print(f"\n{kind} ({len(by_kind[kind])})")
        print(sorted(by_kind[kind]))


def print_violation_report(results: list[dict], raw: dict, cards: dict, engine) -> None:
    reports = []
    for result in results:
        if not result["violations"]:
            continue
        deck = raw[result["decklist_id"]]
        kinds = violations_to_kinds(result["violations"], cards=cards)
        taboo_id = deck.get("taboo_id") or 0
        if any(v.startswith("out_of_taboo_cycle") for v in result["violations"]):
            kinds["out_of_taboo_cycle"] = taboo_cycle_rows(
                deck.get("slots") or {}, taboo_id, engine
            )
        reports.append(
            {
                **result,
                "kinds": kinds,
                "meta": f"{result['f1']}+{result['f2']}"
                if result["f1"] and result["f2"]
                else str(result.get("meta")),
            }
        )

    kind_counts = Counter()
    for r in reports:
        for k in r["kinds"]:
            kind_counts[k] += 1

    print(f"Charlie Kane decks with any flag: {len(reports)} / {len(results)}")
    print("\nViolation kinds (deck counts):")
    for kind, n in kind_counts.most_common():
        print(f"  {kind}: {n}")

    print("\n=== out_of_taboo_cycle (decklist_id, card_id, name, xp@deck_taboo, xp@current_taboo) ===")
    for r in reports:
        for row in r["kinds"].get("out_of_taboo_cycle", []):
            if isinstance(row, dict) and "xp_at_deck_taboo" in row:
                print(
                    f"{r['decklist_id']}\t{row['card_id']}\t{row['name']}\t"
                    f"{row['xp_at_deck_taboo']}\t{row['xp_at_current_taboo']}\t"
                    f"(deck taboo {row['deck_taboo_id']}, current {row['current_taboo_id']})"
                )

    print("\n=== extra_off_class (decklist_id, meta, card_id, name) ===")
    for r in reports:
        for row in r["kinds"].get("extra_off_class", []):
            print(
                f"{r['decklist_id']}\t{r['meta']}\t{row['card_id']}\t{row['name']}"
            )

    other_kinds = [
        k for k in kind_counts if k not in ("out_of_taboo_cycle", "extra_off_class")
    ]
    for kind in sorted(other_kinds):
        print(f"\n=== {kind} ===")
        for r in reports:
            items = r["kinds"].get(kind, [])
            if items:
                print(f"{r['decklist_id']}\t{r.get('name', '')[:50]}\t{items}")


def main() -> None:
    import argparse
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Charlie Kane deck quality classification.")
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print detailed violation report (charlie_violations format).",
    )
    args = parser.parse_args()

    _, raw, engine, results = classify_all_charlie()
    if args.report:
        cards, _, _, _, _, _ = load_charlie_context()
        print_violation_report(results, raw, cards, engine)
    else:
        print_summary(results, raw, engine)


if __name__ == "__main__":
    main()
