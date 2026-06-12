# -*- coding: utf-8 -*-
"""Popularity pipeline per spec.md (C3–C4, D3–D4, Y1–Y2, P1–P5, I1–I5)."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from arkham_canonical import (
    MAX_CYCLE,
    CanonicalMapper,
    is_chapter_2_pack,
    parse_investigator_front_back,
)

UPGRADE_PATTERN = re.compile(r"\d+\|\d+.*")

# Spec B3: floor on p_d(k) when computing tilt (one slot in a 30-card deck).
P_D_FLOOR = 1.0 / 30.0
# Spec B2: floor on P(i|C) when i = C to avoid division by zero.
INV_PROB_FLOOR = 0.01

# Scraping/cleaning: manually confirmed joke decklists.
KNOWN_JOKE_DECKLIST_IDS = frozenset({43839, 44599, 45550})


def build_taboo_card_lookup(
    taboo_json: list[dict[str, Any]],
) -> dict[int, dict[str, dict[str, Any]]]:
    """Map taboo_id -> card_code -> taboo entry (per printing, not canonical)."""
    lookup: dict[int, dict[str, dict[str, Any]]] = {}
    for taboo in taboo_json:
        taboo_id = taboo["id"]
        lookup[taboo_id] = {
            entry["code"]: entry for entry in json.loads(taboo["cards"])
        }
    return lookup


def effective_deck_limit(
    card: dict[str, Any],
    taboo_id: int | None,
    taboo_lookup: dict[int, dict[str, dict[str, Any]]],
) -> int:
    """Max copies of card_id allowed in a deck under the decklist's taboo list."""
    code = card["code"]
    limit = card.get("deck_limit")
    if taboo_id is not None and taboo_id in taboo_lookup:
        entry = taboo_lookup[taboo_id].get(code)
        if entry is not None:
            if entry.get("text") == "Forbidden.":
                return 0
            if "deck_limit" in entry:
                limit = entry["deck_limit"]
    if limit is None:
        if card.get("myriad"):
            return 3
        if card.get("exceptional"):
            return 1
        return 2
    return int(limit)


def deck_limit_violations(
    decklist: dict[str, Any],
    card_json: dict[str, dict[str, Any]],
    taboo_lookup: dict[int, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Return slot copy counts that exceed deck_limit for their card_id."""
    violations: list[dict[str, Any]] = []
    taboo_id = decklist.get("taboo_id")
    for card_code, count in (decklist.get("slots") or {}).items():
        card = card_json.get(card_code)
        if card is None:
            continue
        limit = effective_deck_limit(card, taboo_id, taboo_lookup)
        if count > limit:
            violations.append(
                {
                    "card_code": card_code,
                    "name": card.get("name"),
                    "count": count,
                    "limit": limit,
                }
            )
    return violations


def clean_decklist_json(
    decklist_json: dict[Any, dict[str, Any] | None],
    card_json: dict[str, dict[str, Any]],
    taboo_json: list[dict[str, Any]] | str | Path,
    *,
    known_jokes: frozenset[int] = KNOWN_JOKE_DECKLIST_IDS,
    min_violation_count: int = 4,
) -> tuple[dict[Any, dict[str, Any]], list[tuple[Any, str, str]]]:
    """Drop empty decks, known jokes, and extreme deck_limit violators."""
    if isinstance(taboo_json, (str, Path)):
        taboo_json = json.loads(Path(taboo_json).read_text(encoding="utf-8"))
    taboo_lookup = build_taboo_card_lookup(taboo_json)

    removed: list[tuple[Any, str, str]] = []
    cleaned: dict[Any, dict[str, Any]] = {}
    for deck_id, deck in decklist_json.items():
        if not deck:
            removed.append((deck_id, "empty", ""))
            continue
        if deck_id in known_jokes:
            removed.append((deck_id, "known_joke", deck.get("name", "")))
            continue
        violations = deck_limit_violations(deck, card_json, taboo_lookup)
        extreme = [v for v in violations if v["count"] >= min_violation_count]
        if extreme:
            detail = ", ".join(
                f"{v['count']}x {v['name']!r} (limit {v['limit']})"
                for v in extreme
            )
            removed.append((deck_id, "deck_limit", detail))
            continue
        cleaned[deck_id] = deck
    return cleaned, removed


def slot_display_label(
    slot: str | None,
    real_slot: str | None,
) -> str:
    """Return asset slot label for display; empty string if the card takes no slot."""
    label = slot or real_slot
    return label.strip() if label else ""


SLED_DOG_CANONICAL_ID = "08127"
STANDARD_ASSET_SLOT_TYPES = (
    "Accessory",
    "Ally",
    "Arcane",
    "Body",
    "Hand",
    "Head",
    "Tarot",
)


def is_sled_dog(canonical_id: str, name: str | None = None) -> bool:
    return canonical_id == SLED_DOG_CANONICAL_ID or name == "Sled Dog"


def asset_slot_counts(
    canonical_id: str,
    slot: str | None,
    real_slot: str | None,
    copies: int,
    *,
    name: str | None = None,
) -> dict[str, float]:
    """Map asset slot type -> copies used (spec: Number of assets in each slot)."""
    if copies <= 0:
        return {}
    if is_sled_dog(canonical_id, name):
        return {"Ally": copies / 2}
    label = slot_display_label(slot, real_slot)
    if not label:
        return {}
    counts: dict[str, float] = {}
    for part in label.split(". "):
        part = part.strip()
        if not part:
            continue
        slot_copies = float(copies)
        if part.endswith(" x2"):
            part = part[:-3].strip()
            slot_copies *= 2
        if part:
            counts[part] = counts.get(part, 0.0) + slot_copies
    return counts


def stratum_blend_weight(deck_cycle: int) -> float:
    """Spec B1: g(C) = C."""
    return float(deck_cycle)


# Spec B3: structural composition (pool spread + Core); novelty is not in b_C(k).
_BASELINE_UNIFORM = 0.76
_BASELINE_CORE = 0.22
_BASELINE_STRUCTURAL_MASS = 0.98  # remaining 0.02 ≈ novelty, detected by tilt at k = C


def baseline_composition(deck_cycle: int, card_cycle: int) -> float:
    """Spec B3: b_C(k) = (0.76/C + 0.22*[k=1]) / 0.98; novelty excluded."""
    if card_cycle < 1 or card_cycle > deck_cycle:
        return 0.0
    share = _BASELINE_UNIFORM / deck_cycle
    if card_cycle == 1:
        share += _BASELINE_CORE
    return share / _BASELINE_STRUCTURAL_MASS


def deck_slot_cycle_shares(
    deck: PreparedDecklist,
    mapper: CanonicalMapper,
) -> dict[int, float]:
    """Slot-copy shares p_d(k) by CanonicalCard.cycle."""
    total = sum(deck.slots.values())
    if not total:
        return {}
    by_cycle: dict[int, int] = defaultdict(int)
    for canonical_id, count in deck.slots.items():
        card_cycle = mapper.cycle_for_slot(canonical_id)
        if card_cycle is not None:
            by_cycle[card_cycle] += count
    return {cycle: count / total for cycle, count in by_cycle.items()}


def tilt_factor(
    deck_cycle: int,
    card_cycle: int | None,
    slot_shares: dict[int, float],
    *,
    p_floor: float = P_D_FLOOR,
) -> float:
    """Spec B3: min(1, b_C(k) / p_d(k)); all-k tilt."""
    if card_cycle is None or deck_cycle is None:
        return 1.0
    baseline = baseline_composition(deck_cycle, card_cycle)
    observed = max(slot_shares.get(card_cycle, 0.0), p_floor)
    return min(1.0, baseline / observed)


class InvCycleIndex:
    """Empirical P(inv_cycle | Decklist.cycle) for spec B2."""

    def __init__(
        self,
        mapper: CanonicalMapper,
        decks: list[PreparedDecklist],
    ) -> None:
        counts: dict[tuple[int, int], int] = defaultdict(int)
        totals: dict[int, int] = defaultdict(int)
        for deck in decks:
            if deck.is_ignore or deck.cycle is None:
                continue
            inv_cycle = mapper.cycle_for_slot(deck.canonical_front)
            if inv_cycle is None:
                continue
            counts[(deck.cycle, inv_cycle)] += 1
            totals[deck.cycle] += 1
        self._prob = {
            key: count / totals[key[0]]
            for key, count in counts.items()
            if totals[key[0]]
        }

    def prob(self, deck_cycle: int, inv_cycle: int | None) -> float:
        if inv_cycle is None:
            return 0.0
        return self._prob.get((deck_cycle, inv_cycle), 0.0)

    def adjust(
        self,
        deck_cycle: int,
        inv_cycle: int | None,
        *,
        prob_floor: float = INV_PROB_FLOOR,
    ) -> float:
        """Spec B2: down-weight only when inv_cycle matches deck stratum."""
        if inv_cycle is None or inv_cycle != deck_cycle:
            return 1.0
        probability = max(self.prob(deck_cycle, inv_cycle), prob_floor)
        uniform_share = 1.0 / deck_cycle
        return min(1.0, uniform_share / probability)


def enforce_monotonic_cycle_weights(
    cycle_weights: dict[int, float],
) -> dict[int, float]:
    """Return cycle weights that are non-decreasing in cycle (spec Y2)."""
    if not cycle_weights:
        return {}
    max_cycle = max(cycle_weights)
    return {
        cycle: min(
            cycle_weights[j]
            for j in range(cycle, max_cycle + 1)
            if j in cycle_weights
        )
        for cycle in cycle_weights
    }


@dataclass(frozen=True)
class CanonicalCardInfo:
    canonical_id: str
    name: str
    cycle: int | None
    xp: int
    has_xp_cost: bool
    taboo_set: frozenset[int]
    is_customizable: bool
    slot: str | None
    real_slot: str | None


@dataclass(frozen=True)
class NonCustomOption:
    canonical_id: str
    card_index: int


@dataclass(frozen=True)
class CustomOption:
    canonical_id: str
    option_index: str


Option = NonCustomOption | CustomOption


def parse_customizable(customizable_string: str) -> tuple[list[str], list[int]]:
    """Parse ArkhamDB meta customizable string; return indices and xp costs > 0."""
    upgrade_list = customizable_string.split(",")
    upgrade_list = [part.split("|") for part in upgrade_list if UPGRADE_PATTERN.match(part)]
    indices = [part[0] for part in upgrade_list if int(part[1]) > 0]
    xp_list = [int(part[1]) for part in upgrade_list if int(part[1]) > 0]
    return indices, xp_list


class TabooIndex:
    """Taboo lookups keyed by canonical_id."""

    def __init__(
        self,
        taboo_json: list[dict[str, Any]],
        mapper: CanonicalMapper,
    ) -> None:
        self.mapper = mapper
        self.max_taboo = max(entry["id"] for entry in taboo_json)
        self.taboo_ids = frozenset({0, *{entry["id"] for entry in taboo_json}})
        self._entries: dict[int, dict[str, dict[str, Any]]] = {}
        for entry in taboo_json:
            taboo_id = entry["id"]
            cards: dict[str, dict[str, Any]] = {}
            for taboo_card in json.loads(entry["cards"]):
                cards[taboo_card["code"]] = taboo_card
            merged: dict[str, dict[str, Any]] = {}
            for card_code, taboo_card in cards.items():
                canonical_id = mapper.to_canonical(card_code)
                merged[canonical_id] = taboo_card
            self._entries[taboo_id] = merged

    def entry(self, canonical_id: str, taboo_id: int | None) -> dict[str, Any] | None:
        if taboo_id is None or taboo_id == 0:
            return None
        return self._entries.get(taboo_id, {}).get(canonical_id)

    def xp_modifier(self, canonical_id: str, taboo_id: int | None) -> int:
        entry = self.entry(canonical_id, taboo_id)
        if entry is None:
            return 0
        return entry.get("xp", 0)

    def is_forbidden(self, canonical_id: str, taboo_id: int | None) -> bool:
        entry = self.entry(canonical_id, taboo_id)
        if entry is None:
            return False
        return entry.get("text") == "Forbidden." or entry.get("deck_limit") == 0


class UpgradeGraph:
    """Upgrade families keyed by card name (non-customizable cards)."""

    def __init__(self, cards: dict[str, CanonicalCardInfo]) -> None:
        self.cards = cards
        self._by_name: dict[str, list[str]] = defaultdict(list)
        for canonical_id, info in cards.items():
            if info.is_customizable:
                continue
            self._by_name[info.name].append(canonical_id)
        self._upgrades_cache: dict[str, frozenset[str]] = {}

    def upgrades_of(self, canonical_id: str) -> frozenset[str]:
        if canonical_id in self._upgrades_cache:
            return self._upgrades_cache[canonical_id]
        base = self.cards[canonical_id]
        family = self._by_name[base.name]
        result = {
            cid
            for cid in family
            if self.cards[cid].xp > base.xp or cid == canonical_id
        }
        frozen = frozenset(result)
        self._upgrades_cache[canonical_id] = frozen
        return frozen

    def count_option_in_slots(
        self,
        slots: dict[str, int],
        canonical_id: str,
    ) -> int:
        upgrade_ids = self.upgrades_of(canonical_id)
        return sum(slots.get(cid, 0) for cid in upgrade_ids)


def _base_xp(card: dict[str, Any]) -> int:
    xp = card.get("xp")
    return 0 if xp is None else int(xp)


def _effective_xp(
    card: dict[str, Any],
    canonical_id: str,
    taboo_id: int | None,
    taboo: TabooIndex,
    *,
    use_max_taboo: bool = False,
) -> int:
    lookup_taboo = taboo.max_taboo if use_max_taboo else taboo_id
    xp = _base_xp(card)
    exceptional = bool(card.get("exceptional", False))
    modifier = taboo.xp_modifier(canonical_id, lookup_taboo)
    if modifier:
        xp += modifier
    entry = taboo.entry(canonical_id, lookup_taboo)
    if entry is not None and "exceptional" in entry:
        exceptional = bool(entry["exceptional"])
    if exceptional:
        xp *= 2
    return max(0, xp)


def _taboo_set_for_card(
    canonical_id: str,
    card: dict[str, Any],
    taboo: TabooIndex,
) -> frozenset[int]:
    reference_xp = _effective_xp(
        card, canonical_id, taboo.max_taboo, taboo, use_max_taboo=True
    )
    seen_in_taboo = any(
        taboo.entry(canonical_id, taboo_id) is not None
        for taboo_id in taboo.taboo_ids
        if taboo_id != 0
    )
    if not seen_in_taboo:
        return taboo.taboo_ids
    result = set()
    for taboo_id in taboo.taboo_ids:
        xp_at_taboo = _effective_xp(card, canonical_id, taboo_id, taboo)
        if xp_at_taboo >= reference_xp:
            result.add(taboo_id)
    return frozenset(result)


def build_canonical_card_infos(
    cards: dict[str, dict[str, Any]],
    mapper: CanonicalMapper,
    taboo: TabooIndex,
) -> dict[str, CanonicalCardInfo]:
    infos: dict[str, CanonicalCardInfo] = {}
    for canonical_id in sorted(set(mapper.canonical_id_map.values())):
        card = cards.get(canonical_id)
        if card is None:
            continue
        xp = _effective_xp(card, canonical_id, taboo.max_taboo, taboo, use_max_taboo=True)
        infos[canonical_id] = CanonicalCardInfo(
            canonical_id=canonical_id,
            name=card.get("name", canonical_id),
            cycle=mapper.cycle_for_slot(canonical_id),
            xp=xp,
            has_xp_cost=xp > 0,
            taboo_set=_taboo_set_for_card(canonical_id, card, taboo),
            is_customizable=bool(
                card.get("customization_text") or card.get("customization_change")
            ),
            slot=card.get("slot"),
            real_slot=card.get("real_slot"),
        )
    return infos


@dataclass
class PreparedDecklist:
    decklist_id: Any
    deck_id: Any
    user_id: Any
    investigator_name: str
    investigator_code: str | None
    investigator_front: str
    investigator_back: str
    canonical_front: str
    canonical_back: str
    slots: dict[str, int]
    taboo_id: int
    cycle: int | None
    xp_cost: int
    has_unknown_slots: bool
    has_chapter_2_cards: bool
    is_ignore: bool
    previous_deck: Any = None
    next_deck: Any = None
    date_creation: Any = None
    customizations: dict[str, str] = field(default_factory=dict)


class ArkhamPopularityEngine:
    """End-to-end decklist prep and popularity per spec.md."""

    def __init__(
        self,
        cards: dict[str, dict[str, Any]],
        mapper: CanonicalMapper,
        taboo_json: list[dict[str, Any]],
        *,
        min_xp_cost: int = 1,
        bias_compensation: bool = True,
    ) -> None:
        self.cards = cards
        self.mapper = mapper
        self.taboo = TabooIndex(taboo_json, mapper)
        self.min_xp_cost = min_xp_cost
        self.bias_compensation = bias_compensation
        self.canonical_cards = build_canonical_card_infos(cards, mapper, self.taboo)
        self.upgrades = UpgradeGraph(self.canonical_cards)

    def merge_slots_to_canonical(self, slots: dict[str, int]) -> dict[str, int]:
        merged: dict[str, int] = {}
        for card_id, count in slots.items():
            canonical_id = self.mapper.to_canonical(card_id)
            merged[canonical_id] = merged.get(canonical_id, 0) + count
        return merged

    def slots_have_unknown(self, slots: dict[str, int]) -> bool:
        return self.mapper.decklist_has_unknown_slots(slots)

    def slots_have_chapter_2(self, slots: dict[str, int]) -> bool:
        for card_id in slots:
            canonical_id = self.mapper.to_canonical(card_id)
            card = self.cards.get(canonical_id) or self.cards.get(card_id)
            if card is None:
                continue
            if is_chapter_2_pack(card.get("pack_code", "")):
                return True
        return False

    def decklist_xp(self, decklist: dict[str, Any], slots: dict[str, int] | None = None) -> int:
        slots = slots if slots is not None else self.merge_slots_to_canonical(
            decklist.get("slots") or {}
        )
        taboo_id = self._normalize_taboo_id(decklist.get("taboo_id"))
        xp = 0
        for card_code, num in slots.items():
            card = self.cards.get(card_code)
            if card is None:
                continue
            card_xp = _effective_xp(card, card_code, taboo_id, self.taboo)
            if card.get("myriad", False):
                xp += card_xp
            else:
                xp += card_xp * num

        meta = decklist.get("meta") or ""
        if meta:
            meta_json = json.loads(meta)
            for key, customizable_string in meta_json.items():
                if key.startswith("cus_"):
                    _, xp_list = parse_customizable(customizable_string)
                    xp += sum(xp_list)

        if "08125" in slots:
            xp = max(0, xp - 3)
        if decklist.get("investigator_name") == "Kymani Jones":
            xp = max(0, xp - 5)
        return xp

    def deck_passes_taboo(self, slots: dict[str, int], taboo_id: int) -> bool:
        for card_code in slots:
            info = self.canonical_cards.get(card_code)
            if info is None:
                return False
            if taboo_id not in info.taboo_set:
                return False
            if self.taboo.is_forbidden(card_code, taboo_id):
                return False
        return True

    def prepare_decklist(self, decklist_id: Any, decklist: dict[str, Any]) -> PreparedDecklist:
        raw_slots = decklist.get("slots") or {}
        slots = self.merge_slots_to_canonical(raw_slots)
        has_unknown = self.slots_have_unknown(slots)
        has_chapter_2 = self.slots_have_chapter_2(slots)
        taboo_id = self._normalize_taboo_id(decklist.get("taboo_id"))
        inv_front, inv_back = parse_investigator_front_back(decklist)
        canon_front, canon_back = self.mapper.canonical_front_back(inv_front, inv_back)

        is_ignore = has_unknown or has_chapter_2
        if not is_ignore:
            is_ignore = not self.deck_passes_taboo(slots, taboo_id)

        customizations = {}
        meta = decklist.get("meta") or ""
        if meta:
            for key, value in json.loads(meta).items():
                if key.startswith("cus_"):
                    customizations[key.removeprefix("cus_")] = value

        return PreparedDecklist(
            decklist_id=decklist_id,
            deck_id=decklist.get("id", decklist_id),
            user_id=decklist.get("user_id"),
            investigator_name=decklist.get("investigator_name", ""),
            investigator_code=decklist.get("investigator_code"),
            investigator_front=inv_front,
            investigator_back=inv_back,
            canonical_front=canon_front,
            canonical_back=canon_back,
            slots=slots,
            taboo_id=taboo_id,
            cycle=self.mapper.decklist_cycle(slots),
            xp_cost=self.decklist_xp(decklist, slots),
            has_unknown_slots=has_unknown,
            has_chapter_2_cards=has_chapter_2,
            is_ignore=is_ignore,
            previous_deck=decklist.get("previous_deck"),
            next_deck=decklist.get("next_deck"),
            date_creation=decklist.get("date_creation"),
            customizations=customizations,
        )

    def prepare_all(
        self, decklist_json: dict[Any, dict[str, Any]]
    ) -> list[PreparedDecklist]:
        prepared = []
        for decklist_id, decklist in decklist_json.items():
            if not decklist:
                continue
            prepared.append(self.prepare_decklist(decklist_id, decklist))
        return prepared

    def assign_user_weights(self, decks: list[PreparedDecklist]) -> dict[Any, float]:
        counts: dict[tuple[Any, str, str], int] = defaultdict(int)
        for deck in decks:
            key = (deck.user_id, deck.canonical_front, deck.canonical_back)
            counts[key] += 1
        weights: dict[Any, float] = {}
        for deck in decks:
            key = (deck.user_id, deck.canonical_front, deck.canonical_back)
            weights[deck.deck_id] = 1.0 / counts[key]
        return weights

    def assign_cycle_weights(
        self,
        decks: list[PreparedDecklist],
        user_weights: dict[Any, float],
    ) -> dict[int, float]:
        sums: dict[int, float] = defaultdict(float)
        for deck in decks:
            if deck.is_ignore or deck.cycle is None:
                continue
            sums[deck.cycle] += user_weights[deck.deck_id]
        raw = {cycle: (1.0 / total if total else 0.0) for cycle, total in sums.items()}
        return enforce_monotonic_cycle_weights(raw)

    def deck_weight(
        self,
        deck: PreparedDecklist,
        user_weights: dict[Any, float],
        cycle_weights: dict[int, float],
    ) -> float:
        if deck.is_ignore or deck.cycle is None:
            return 0.0
        return user_weights[deck.deck_id] * cycle_weights.get(deck.cycle, 0.0)

    def adjusted_deck_weight(
        self,
        deck: PreparedDecklist,
        card_cycle: int | None,
        user_weights: dict[Any, float],
        cycle_weights: dict[int, float],
        inv_index: InvCycleIndex,
        slot_shares: dict[int, float],
    ) -> float:
        """Spec B2 + B3: user_weight × Cycle.weight × inv_adjust × tilt_d(k)."""
        base = self.deck_weight(deck, user_weights, cycle_weights)
        if not base:
            return 0.0
        inv_cycle = self.mapper.cycle_for_slot(deck.canonical_front)
        inv_adjust = inv_index.adjust(deck.cycle, inv_cycle)
        tilt = tilt_factor(deck.cycle, card_cycle, slot_shares)
        return base * inv_adjust * tilt

    def _deck_passes_p1_p2(
        self,
        deck: PreparedDecklist,
        card_info: CanonicalCardInfo,
    ) -> bool:
        if deck.is_ignore or deck.cycle is None:
            return False
        if card_info.cycle is not None and deck.cycle < card_info.cycle:
            return False
        if card_info.has_xp_cost and deck.xp_cost < self.min_xp_cost:
            return False
        return True

    def _option_weight_in_stratum(
        self,
        deck: PreparedDecklist,
        card_info: CanonicalCardInfo,
        stratum: int,
        user_weights: dict[Any, float],
        cycle_weights: dict[int, float],
        inv_index: InvCycleIndex | None,
        slot_shares_by_deck: dict[Any, dict[int, float]],
    ) -> float:
        if deck.cycle != stratum:
            return 0.0
        if not self._deck_passes_p1_p2(deck, card_info):
            return 0.0
        if self.bias_compensation and inv_index is not None:
            shares = slot_shares_by_deck.get(deck.deck_id, {})
            return self.adjusted_deck_weight(
                deck,
                card_info.cycle,
                user_weights,
                cycle_weights,
                inv_index,
                shares,
            )
        return self.deck_weight(deck, user_weights, cycle_weights)

    def _stratum_popularity_for_option(
        self,
        inv_decks: list[PreparedDecklist],
        card_info: CanonicalCardInfo,
        stratum: int,
        user_weights: dict[Any, float],
        cycle_weights: dict[int, float],
        inv_index: InvCycleIndex | None,
        slot_shares_by_deck: dict[Any, dict[int, float]],
        *,
        contains_option: Any,
    ) -> tuple[float, float]:
        """Return (p3, p4) within Decklist.cycle = stratum."""
        p3 = 0.0
        p4 = 0.0
        for deck in inv_decks:
            weight = self._option_weight_in_stratum(
                deck,
                card_info,
                stratum,
                user_weights,
                cycle_weights,
                inv_index,
                slot_shares_by_deck,
            )
            if not weight:
                continue
            p3 += weight
            if contains_option(deck):
                p4 += weight
        return p3, p4

    def _blend_stratum_popularity(
        self,
        stratum_p3: dict[int, float],
        stratum_p4: dict[int, float],
    ) -> tuple[float, float, float]:
        """Spec B1: blend per-stratum P5 with g(C) = C."""
        blend_total = 0.0
        weighted_p3 = 0.0
        weighted_p4 = 0.0
        weighted_p5 = 0.0
        for stratum in sorted(stratum_p3):
            p3 = stratum_p3[stratum]
            if not p3:
                continue
            g_weight = stratum_blend_weight(stratum)
            p5 = stratum_p4[stratum] / p3
            blend_total += g_weight
            weighted_p3 += g_weight * p3
            weighted_p4 += g_weight * stratum_p4[stratum]
            weighted_p5 += g_weight * p5
        if not blend_total:
            return 0.0, 0.0, 0.0
        return (
            weighted_p3 / blend_total,
            weighted_p4 / blend_total,
            weighted_p5 / blend_total,
        )

    def _eligible_decks_for_option(
        self,
        decks: list[PreparedDecklist],
        card_info: CanonicalCardInfo,
        user_weights: dict[Any, float],
        cycle_weights: dict[int, float],
        inv_index: InvCycleIndex | None = None,
        slot_shares_by_deck: dict[Any, dict[int, float]] | None = None,
    ) -> list[tuple[PreparedDecklist, float]]:
        """Legacy pooled eligibility (no B1 stratification). Used when bias_compensation=False."""
        eligible: list[tuple[PreparedDecklist, float]] = []
        shares = slot_shares_by_deck or {}
        for deck in decks:
            if not self._deck_passes_p1_p2(deck, card_info):
                continue
            if self.bias_compensation and inv_index is not None:
                weight = self.adjusted_deck_weight(
                    deck,
                    card_info.cycle,
                    user_weights,
                    cycle_weights,
                    inv_index,
                    shares.get(deck.deck_id, {}),
                )
            else:
                weight = self.deck_weight(deck, user_weights, cycle_weights)
            if weight:
                eligible.append((deck, weight))
        return eligible

    def deck_contains_noncustom_option(
        self,
        deck: PreparedDecklist,
        canonical_id: str,
        card_index: int,
    ) -> bool:
        return self.upgrades.count_option_in_slots(deck.slots, canonical_id) >= card_index

    def deck_contains_custom_option(
        self,
        deck: PreparedDecklist,
        canonical_id: str,
        option_index: str,
    ) -> bool:
        if canonical_id not in deck.slots:
            return False
        custom = deck.customizations.get(canonical_id)
        if not custom:
            return False
        indices, _ = parse_customizable(custom)
        return option_index in indices

    def enumerate_options(self, decks: list[PreparedDecklist]) -> list[Option]:
        options: set[Option] = set()
        for deck in decks:
            if deck.is_ignore:
                continue
            for canonical_id, count in deck.slots.items():
                info = self.canonical_cards.get(canonical_id)
                if info is None:
                    continue
                if info.is_customizable:
                    custom = deck.customizations.get(canonical_id)
                    if custom:
                        indices, _ = parse_customizable(custom)
                        for option_index in indices:
                            options.add(CustomOption(canonical_id, option_index))
                    else:
                        options.add(CustomOption(canonical_id, "0"))
                else:
                    for card_index in range(1, count + 1):
                        options.add(NonCustomOption(canonical_id, card_index))
        return sorted(options, key=self._option_sort_key)

    def popularity_for_investigator(
        self,
        decks: list[PreparedDecklist],
        canonical_front: str,
        canonical_back: str,
    ) -> list[dict[str, Any]]:
        inv_decks = [
            deck
            for deck in decks
            if deck.canonical_front == canonical_front
            and deck.canonical_back == canonical_back
        ]
        user_weights = self.assign_user_weights(decks)
        active = [deck for deck in inv_decks if not deck.is_ignore]
        cycle_weights = self.assign_cycle_weights(active, user_weights)

        inv_index = (
            InvCycleIndex(self.mapper, decks) if self.bias_compensation else None
        )
        slot_shares_by_deck = {
            deck.deck_id: deck_slot_cycle_shares(deck, self.mapper)
            for deck in inv_decks
            if not deck.is_ignore
        }
        strata = sorted(
            {
                deck.cycle
                for deck in inv_decks
                if deck.cycle is not None and not deck.is_ignore
            }
        )

        rows: list[dict[str, Any]] = []
        for option in self.enumerate_options(inv_decks):
            if isinstance(option, NonCustomOption):
                card_info = self.canonical_cards[option.canonical_id]

                def contains_noncustom(deck: PreparedDecklist) -> bool:
                    return self.deck_contains_noncustom_option(
                        deck, option.canonical_id, option.card_index
                    )

                p3, p4, p5 = self._popularity_for_option(
                    inv_decks,
                    card_info,
                    strata,
                    user_weights,
                    cycle_weights,
                    inv_index,
                    slot_shares_by_deck,
                    contains_noncustom,
                )
                rows.append(
                    {
                        "canonical_id": option.canonical_id,
                        "card_index": option.card_index,
                        "option_index": None,
                        "name": card_info.name,
                        "xp": card_info.xp if card_info.has_xp_cost else None,
                        "slot": slot_display_label(
                            card_info.slot, card_info.real_slot
                        ),
                        "is_customizable": False,
                        "p3_opportunity_weight": p3,
                        "p4_choice_weight": p4,
                        "p5_popularity": p5,
                    }
                )
            else:
                card_info = self.canonical_cards[option.canonical_id]

                def contains_custom(deck: PreparedDecklist) -> bool:
                    return self.deck_contains_custom_option(
                        deck, option.canonical_id, option.option_index
                    )

                p3, p4, p5 = self._popularity_for_option(
                    inv_decks,
                    card_info,
                    strata,
                    user_weights,
                    cycle_weights,
                    inv_index,
                    slot_shares_by_deck,
                    contains_custom,
                )
                rows.append(
                    {
                        "canonical_id": option.canonical_id,
                        "card_index": None,
                        "option_index": option.option_index,
                        "name": card_info.name,
                        "xp": None,
                        "slot": slot_display_label(
                            card_info.slot, card_info.real_slot
                        ),
                        "is_customizable": True,
                        "p3_opportunity_weight": p3,
                        "p4_choice_weight": p4,
                        "p5_popularity": p5,
                    }
                )
        rows.sort(key=lambda row: row["p5_popularity"], reverse=True)
        return rows

    def _popularity_for_option(
        self,
        inv_decks: list[PreparedDecklist],
        card_info: CanonicalCardInfo,
        strata: list[int],
        user_weights: dict[Any, float],
        cycle_weights: dict[int, float],
        inv_index: InvCycleIndex | None,
        slot_shares_by_deck: dict[Any, dict[int, float]],
        contains_option: Any,
    ) -> tuple[float, float, float]:
        if self.bias_compensation:
            stratum_p3: dict[int, float] = {}
            stratum_p4: dict[int, float] = {}
            for stratum in strata:
                if card_info.cycle is not None and stratum < card_info.cycle:
                    continue
                p3, p4 = self._stratum_popularity_for_option(
                    inv_decks,
                    card_info,
                    stratum,
                    user_weights,
                    cycle_weights,
                    inv_index,
                    slot_shares_by_deck,
                    contains_option=contains_option,
                )
                if p3:
                    stratum_p3[stratum] = p3
                    stratum_p4[stratum] = p4
            return self._blend_stratum_popularity(stratum_p3, stratum_p4)

        eligible = self._eligible_decks_for_option(
            inv_decks,
            card_info,
            user_weights,
            cycle_weights,
            inv_index,
            slot_shares_by_deck,
        )
        p3 = sum(weight for _, weight in eligible)
        p4 = sum(weight for deck, weight in eligible if contains_option(deck))
        p5 = (p4 / p3) if p3 else 0.0
        return p3, p4, p5

    def investigator_popularity_by_cycle(
        self,
        decks: list[PreparedDecklist],
    ) -> list[dict[str, Any]]:
        user_weights = self.assign_user_weights(decks)
        active = [deck for deck in decks if not deck.is_ignore and deck.cycle is not None]
        cycle_weights = self.assign_cycle_weights(active, user_weights)

        tuples = {
            (deck.canonical_front, deck.canonical_back)
            for deck in active
        }
        inv_cycle = {
            key: self.mapper.cycle_for_slot(key[0])
            for key in tuples
        }

        rows: list[dict[str, Any]] = []
        for cycle in range(1, MAX_CYCLE + 1):
            pool = [
                deck
                for deck in active
                if deck.cycle is not None and deck.cycle >= cycle
            ]
            pool_weight = sum(
                self.deck_weight(deck, user_weights, cycle_weights) for deck in pool
            )
            for canonical_front, canonical_back in tuples:
                if inv_cycle.get((canonical_front, canonical_back)) != cycle:
                    continue
                inv_weight = sum(
                    self.deck_weight(deck, user_weights, cycle_weights)
                    for deck in pool
                    if deck.canonical_front == canonical_front
                    and deck.canonical_back == canonical_back
                )
                rows.append(
                    {
                        "canonical_front": canonical_front,
                        "canonical_back": canonical_back,
                        "cycle": cycle,
                        "inv_cycle": cycle,
                        "pool_weight": pool_weight,
                        "investigator_weight": inv_weight,
                        "popularity": (inv_weight / pool_weight) if pool_weight else 0.0,
                    }
                )
        return rows

    def slot_usage_for_investigator(
        self,
        decks: list[PreparedDecklist],
        canonical_front: str,
        canonical_back: str,
    ) -> list[dict[str, Any]]:
        """Weighted average asset copies per asset slot type (spec: assets in each slot)."""
        inv_decks = [
            deck
            for deck in decks
            if deck.canonical_front == canonical_front
            and deck.canonical_back == canonical_back
            and not deck.is_ignore
            and deck.cycle is not None
        ]
        user_weights = self.assign_user_weights(decks)
        cycle_weights = self.assign_cycle_weights(inv_decks, user_weights)

        slot_totals: dict[str, float] = defaultdict(float)
        total_weight = 0.0
        for deck in inv_decks:
            weight = self.deck_weight(deck, user_weights, cycle_weights)
            if not weight:
                continue
            total_weight += weight
            for canonical_id, count in deck.slots.items():
                card = self.cards.get(canonical_id)
                if card is None or card.get("type_code") != "asset":
                    continue
                info = self.canonical_cards.get(canonical_id)
                if info is None:
                    continue
                per_slot = asset_slot_counts(
                    canonical_id,
                    info.slot,
                    info.real_slot,
                    count,
                    name=info.name,
                )
                for slot_type, slot_copies in per_slot.items():
                    slot_totals[slot_type] += weight * slot_copies

        if not total_weight:
            return []
        return [
            {
                "canonical_front": canonical_front,
                "canonical_back": canonical_back,
                "slot_type": slot_type,
                "weighted_avg": slot_totals.get(slot_type, 0.0) / total_weight,
                "deck_count": len(inv_decks),
                "total_weight": total_weight,
            }
            for slot_type in STANDARD_ASSET_SLOT_TYPES
        ]

    @staticmethod
    def _normalize_taboo_id(taboo_id: Any) -> int:
        if taboo_id is None:
            return 0
        return int(taboo_id)

    @staticmethod
    def _option_sort_key(option: Option) -> tuple[Any, ...]:
        if isinstance(option, NonCustomOption):
            return (0, option.canonical_id, option.card_index)
        return (1, option.canonical_id, option.option_index)


def prepared_decks_to_dataframe(prepared: list[PreparedDecklist]):
    """Convert prepared decklists to a pandas DataFrame."""
    import pandas as pd

    records = []
    for deck in prepared:
        records.append(
            {
                "id": deck.deck_id,
                "decklist_id": deck.decklist_id,
                "user_id": deck.user_id,
                "investigator_code": deck.investigator_code,
                "investigator_name": deck.investigator_name,
                "investigator_front": deck.investigator_front,
                "investigator_back": deck.investigator_back,
                "canonical_front": deck.canonical_front,
                "canonical_back": deck.canonical_back,
                "slots": deck.slots,
                "taboo_id": deck.taboo_id,
                "previous_deck": deck.previous_deck,
                "next_deck": deck.next_deck,
                "date_creation": deck.date_creation,
                "xp_cost": deck.xp_cost,
                "cycle": deck.cycle,
                "has_unknown_slots": deck.has_unknown_slots,
                "has_chapter_2_cards": deck.has_chapter_2_cards,
                "is_ignore": deck.is_ignore,
                "customizations": deck.customizations,
            }
        )
    return pd.DataFrame.from_records(records)
