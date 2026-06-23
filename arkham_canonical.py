# -*- coding: utf-8 -*-
"""Map ArkhamDB card_id values to canonical_id per spec.md."""

from __future__ import annotations

import json
import pickle
import re
from collections import defaultdict
from typing import Any

from arkham_deck_options import investigator_requirement_card_ids

CORE_PACK = "core"
RCORE_PACK = "rcore"
CORE_PACKS = (CORE_PACK, RCORE_PACK)
DUNWICH = ("dwl", "tmm", "tece", "bota", "uau", "wda", "litas")
CARCOSA = ("ptc", "eotp", "tuo", "apot", "tpm", "bsr", "dca")
FORGOTTEN = ("tfa", "tof", "tbb", "hote", "tcoa", "tdoy", "sha")
CIRCLE = ("tcu", "tsn", "wos", "fgg", "uad", "icc", "bbt")
DREAM = ("tde", "sfk", "tsh", "dsm", "pnr", "wgd", "woc")
INVESTIGATOR_STARTERS = ("nat", "har", "win", "jac", "ste")
INNSMOUTH = ("tic", "itd", "def", "hhg", "lif", "lod", "itm")
EDGE = ("eoep", "eoec")
SCARLET = ("tskp", "tskc")
HEMLOCK = ("fhvp", "fhvc")
DROWNED = ("tdcp", "tdcc")

CHAPTER_2_PACKS = frozenset({"core_2026", "tom", "car", "and", "mar", "mig"})

MAX_CYCLE = 12

# Sort rank for unordered packs when picking earliest printing (after ordered cycles).
_UNORDERED_SORT_RANK = MAX_CYCLE + 100
# Revised Core reprints sort after true first printings (not earliest for canonical_id).
_RCORE_SORT_RANK = MAX_CYCLE + 50

_TRAIT_RE = re.compile(r"\[\[([^\]]+)\]\]")
_WHITESPACE_RE = re.compile(r"\s+")
_DASHES = str.maketrans({"−": "-", "–": "-", "—": "-"})


def _build_pack_to_cycle() -> dict[str, int]:
    """Map only publication-ordered packs to cycle numbers (spec Pack Order)."""
    mapping: dict[str, int] = {}

    for pack in CORE_PACKS:
        mapping[pack] = 1
    for pack in DUNWICH:
        mapping[pack] = 2
    for pack in CARCOSA:
        mapping[pack] = 3
    mapping["rtnotz"] = 3
    for pack in FORGOTTEN:
        mapping[pack] = 4
    mapping["rtdwl"] = 4
    for pack in CIRCLE:
        mapping[pack] = 5
    mapping["rtptc"] = 5
    for pack in DREAM:
        mapping[pack] = 6
    mapping["rttfa"] = 6
    for pack in INVESTIGATOR_STARTERS:
        mapping[pack] = 7
    for pack in INNSMOUTH:
        mapping[pack] = 8
    mapping["rttcu"] = 8
    for pack in EDGE:
        mapping[pack] = 9
    for pack in SCARLET:
        mapping[pack] = 10
    for pack in HEMLOCK:
        mapping[pack] = 11
    for pack in DROWNED:
        mapping[pack] = 12
    for pack in CHAPTER_2_PACKS:
        mapping[pack] = 13

    return mapping


PACK_TO_CYCLE = _build_pack_to_cycle()


def pack_to_cycle(pack_code: str) -> int | None:
    """Return publication cycle for an ordered pack, or None if out-of-order/unknown."""
    return PACK_TO_CYCLE.get(pack_code)


def _pack_sort_rank(pack_code: str) -> int:
    if pack_code == RCORE_PACK:
        return _RCORE_SORT_RANK
    cycle = pack_to_cycle(pack_code)
    return cycle if cycle is not None else _UNORDERED_SORT_RANK


def _member_card_cycle(card: dict[str, Any]) -> int | None:
    """First-printing cycle for a constituent card_id (excludes rcore reprints)."""
    pack_code = card.get("pack_code", "")
    if pack_code == RCORE_PACK:
        return None
    return pack_to_cycle(pack_code)


def _canonical_cycle_for_members(
    members: list[str], cards: dict[str, dict[str, Any]]
) -> int | None:
    cycles = [
        cycle
        for member in members
        if (cycle := _member_card_cycle(cards[member])) is not None
    ]
    if not cycles:
        return None
    return min(cycles)


def is_chapter_2_pack(pack_code: str) -> bool:
    return pack_code in CHAPTER_2_PACKS


def normalize_text(text: str | None) -> str:
    """Collapse whitespace and normalize trait / chaos-token formatting."""
    if not text:
        return ""
    normalized = text.translate(_DASHES)
    normalized = _TRAIT_RE.sub(r"[\1]", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()


def compare_text(card: dict[str, Any]) -> str:
    """coalesce(normalize(text), normalize(real_text), '')"""
    text = card.get("text")
    if text is not None:
        return normalize_text(text)
    real_text = card.get("real_text")
    if real_text is not None:
        return normalize_text(real_text)
    return ""


def card_fingerprint(card: dict[str, Any]) -> tuple[Any, ...]:
    """Fingerprint tuple for reprint equivalence (spec Canonicalization)."""
    return (
        card.get("name"),
        card.get("subname") or "",
        card.get("xp") if card.get("xp") is not None else 0,
        compare_text(card),
        card.get("type_code"),
        card.get("faction_code"),
        card.get("exceptional"),
        card.get("myriad"),
        card.get("cost"),
        card.get("deck_limit"),
        card.get("is_unique"),
        card.get("permanent"),
    )


class UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def _card_sort_key(card_id: str, card: dict[str, Any]) -> tuple[int, str]:
    return (_pack_sort_rank(card["pack_code"]), card_id)


def _pick_canonical_id(
    members: list[str], cards: dict[str, dict[str, Any]]
) -> str:
    return min(members, key=lambda card_id: _card_sort_key(card_id, cards[card_id]))


def build_canonical_map(
    cards: dict[str, dict[str, Any]],
    *,
    chapter: int = 1,
) -> tuple[dict[str, str], dict[str, int | None]]:
    """Build card_id -> canonical_id and canonical_id -> canonical_cycle maps.

    chapter=1 excludes Chapter 2 packs (core_2026 and new investigator decks).
    """
    if chapter == 1:
        scope = {
            card_id: card
            for card_id, card in cards.items()
            if not is_chapter_2_pack(card.get("pack_code", ""))
        }
    elif chapter == 2:
        scope = {
            card_id: card
            for card_id, card in cards.items()
            if is_chapter_2_pack(card.get("pack_code", ""))
        }
    else:
        scope = dict(cards)

    card_ids = list(scope.keys())
    uf = UnionFind(card_ids)

    by_fingerprint: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for card_id, card in scope.items():
        by_fingerprint[card_fingerprint(card)].append(card_id)
    for member_ids in by_fingerprint.values():
        first = member_ids[0]
        for other in member_ids[1:]:
            uf.union(first, other)

    for card_id, card in scope.items():
        duplicate_of = card.get("duplicate_of_code")
        if duplicate_of and duplicate_of in scope:
            uf.union(card_id, duplicate_of)

    components: dict[str, list[str]] = defaultdict(list)
    for card_id in card_ids:
        components[uf.find(card_id)].append(card_id)

    canonical_id_map: dict[str, str] = {}
    canonical_cycle: dict[str, int | None] = {}
    for members in components.values():
        canonical_id = _pick_canonical_id(members, scope)
        cycle = _canonical_cycle_for_members(members, scope)
        canonical_cycle[canonical_id] = cycle
        for member in members:
            canonical_id_map[member] = canonical_id

    return canonical_id_map, canonical_cycle


def parse_investigator_front_back(decklist: dict[str, Any]) -> tuple[str, str]:
    """Return raw investigator_front/back card_ids from a decklist."""
    investigator_code = decklist.get("investigator_code") or ""
    meta = decklist.get("meta") or ""
    if not meta:
        return investigator_code, investigator_code

    meta_json = json.loads(meta)
    inv_front = meta_json.get("alternate_front") or investigator_code
    inv_back = meta_json.get("alternate_back") or investigator_code
    if inv_front == "":
        inv_front = investigator_code
    if inv_back == "":
        inv_back = investigator_code
    return inv_front, inv_back


class CanonicalMapper:
    """card_id -> canonical_id lookup built from scraped card_json."""

    def __init__(
        self,
        cards: dict[str, dict[str, Any]],
        *,
        chapter: int = 1,
    ) -> None:
        self.cards = cards
        self.chapter = chapter
        self.canonical_id_map, self.canonical_cycle = build_canonical_map(
            cards, chapter=chapter
        )

    def to_canonical(self, card_id: str) -> str:
        return self.canonical_id_map.get(card_id, card_id)

    def to_canonical_front(self, card_id: str) -> str:
        """Map an investigator front card_id to canonical_front."""
        return self.to_canonical(card_id)

    def to_canonical_back(self, card_id: str) -> str:
        """Map an investigator back card_id to canonical_back."""
        return self.to_canonical(card_id)

    def canonical_front_back(self, front: str, back: str) -> tuple[str, str]:
        """Map raw front/back card_ids to (canonical_front, canonical_back)."""
        return self.to_canonical_front(front), self.to_canonical_back(back)

    def decklist_canonical_front_back(
        self, decklist: dict[str, Any]
    ) -> tuple[str, str]:
        """Parse a decklist and return (canonical_front, canonical_back)."""
        front, back = parse_investigator_front_back(decklist)
        return self.canonical_front_back(front, back)

    def is_known_card(self, card_id: str) -> bool:
        """True when the slot code exists in scraped card data."""
        canonical_id = self.to_canonical(card_id)
        return canonical_id in self.cards or card_id in self.cards

    def cycle_for_slot(self, card_id: str) -> int | None:
        """Return CanonicalCard.cycle for a slot code, or None if out-of-order."""
        canonical_id = self.to_canonical(card_id)
        if canonical_id in self.canonical_cycle:
            return self.canonical_cycle[canonical_id]
        card = self.cards.get(canonical_id) or self.cards.get(card_id)
        if card is None:
            return None
        return _member_card_cycle(card)

    def decklist_cycle(
        self,
        slots: dict[str, int] | None,
        *,
        canonical_front: str | None = None,
    ) -> int | None:
        """Return Decklist.cycle: max cycle among player-chosen ordered slot codes.

        Excludes random basic weaknesses and, when canonical_front is given,
        all signature printings from deck_requirements.card.
        """
        if not slots:
            return None
        exclude: set[str] = set()
        if canonical_front is not None:
            exclude |= investigator_requirement_card_ids(
                self.cards, canonical_front, self.to_canonical
            )
        for card_id in slots:
            canonical_id = self.to_canonical(card_id)
            card = self.cards.get(canonical_id) or self.cards.get(card_id)
            if card is not None and card.get("subtype_code") == "basicweakness":
                exclude.add(canonical_id)
        cycles = [
            cycle
            for card_id in slots
            if self.to_canonical(card_id) not in exclude
            and (cycle := self.cycle_for_slot(card_id)) is not None
        ]
        if not cycles:
            return None
        return max(cycles)

    def decklist_has_unknown_slots(self, slots: dict[str, int] | None) -> bool:
        if not slots:
            return False
        return any(not self.is_known_card(card_id) for card_id in slots)

    def cycle_for(self, card_id: str) -> int:
        cycle = self.cycle_for_slot(card_id)
        if cycle is None:
            raise KeyError(card_id)
        return cycle


def load_cards(path: str = "card_json.pickle") -> dict[str, dict[str, Any]]:
    with open(path, "rb") as file:
        return pickle.load(file)


def load_canonical_mapper(
    path: str = "card_json.pickle",
    *,
    chapter: int = 1,
) -> CanonicalMapper:
    return CanonicalMapper(load_cards(path), chapter=chapter)
