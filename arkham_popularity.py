# -*- coding: utf-8 -*-
"""Popularity pipeline per spec.md (C3–C4, D3–D4, Y1–Y2, P1–P5, I1–I5)."""

from __future__ import annotations

import csv
import json
import math
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
from arkham_deck_options import (
    DeckOptionResolution,
    DeckOptionsValidator,
    InvestigatorOptionInput,
    apply_permanent_composition_rules,
    card_has_trait,
    counts_toward_player_deck_size,
    deck_options_support,
    deck_requirement_signature_groups,
    all_deck_requirement_card_ids,
    effective_deck_size_from_slots,
    investigator_requirement_card_ids,
    investigator_option_slug,
    merge_deck_options_with_permanents,
    parse_investigator_option,
    resolve_deck_options,
    resolve_signature_groups,
)

UPGRADE_PATTERN = re.compile(r"\d+\|\d+.*")

# Spec B3: floor on p_d(k) when computing tilt (one slot in a 30-card deck).
P_D_FLOOR = 1.0 / 30.0
# Spec B2: floor on P(i|C) when i = C to avoid division by zero.
INV_PROB_FLOOR = 0.01

# Spec: relative-mass smoothing for conditional slot averages (Phase 0.5).
SLOT_AVERAGE_SMOOTHING_RHO = 0.05

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
IN_THE_THICK_OF_IT_CANONICAL_ID = "08125"
DEFAULT_XP_THRES = 29
STANDARD_DECK_OPTION_KEYS = frozenset({"faction", "level"})


def deck_xp_weight(xp_cost: int, *, xp_thres: int = DEFAULT_XP_THRES) -> float:
    """Down-weight high-XP deck snapshots (Y3). Full weight at or below xp_thres."""
    if xp_cost <= xp_thres:
        return 1.0
    return xp_thres / xp_cost


def slots_have_upgrade_cards(
    slots: dict[str, int],
    cards: dict[str, dict[str, Any]],
    taboo_id: int,
    taboo: TabooIndex,
) -> bool:
    """True when any slotted card has effective XP > 0 at taboo_id."""
    for card_code, count in slots.items():
        if count <= 0:
            continue
        card = cards.get(card_code)
        if card is None:
            continue
        if _effective_xp(card, card_code, taboo_id, taboo) > 0:
            return True
    return False


STANDARD_ASSET_SLOT_TYPES = (
    "Accessory",
    "Ally",
    "Arcane",
    "Body",
    "Hand",
    "Head",
    "Mask",
    "Tarot",
)


def apply_runtime_card_patches(cards: dict[str, dict[str, Any]]) -> None:
    """In-memory card fixes after pickle load; never persisted to pickle."""
    for card in cards.values():
        if card.get("type_code") != "asset":
            continue
        if not card_has_trait(card, "Mask"):
            continue
        if slot_display_label(card.get("slot"), card.get("real_slot")):
            continue
        card["slot"] = "Mask"
        card["real_slot"] = "Mask"


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


def accumulate_asset_slot_usage(
    slots: dict[str, int],
    weight: float,
    slot_totals: dict[str, float],
    *,
    cards: dict[str, dict[str, Any]],
    canonical_cards: dict[str, Any],
) -> None:
    """Add weighted asset-slot copies from a deck's slots into slot_totals."""
    for canonical_id, count in slots.items():
        card = cards.get(canonical_id)
        if card is None or card.get("type_code") != "asset":
            continue
        info = canonical_cards.get(canonical_id)
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


def deck_asset_slot_totals(
    slots: dict[str, int],
    *,
    cards: dict[str, dict[str, Any]],
    canonical_cards: dict[str, Any],
) -> dict[str, float]:
    """Per asset-slot-type copies used by assets in one deck."""
    totals: dict[str, float] = defaultdict(float)
    accumulate_asset_slot_usage(
        slots, 1.0, totals, cards=cards, canonical_cards=canonical_cards
    )
    return dict(totals)


def investigator_decks(
    decks: list[PreparedDecklist],
    canonical_front: str,
    canonical_back: str,
    *,
    exclude_ignored: bool = False,
    require_cycle: bool = False,
) -> list[PreparedDecklist]:
    """Filter prepared decks for one (canonical_front, canonical_back) tuple."""
    matched: list[PreparedDecklist] = []
    for deck in decks:
        if (
            deck.canonical_front != canonical_front
            or deck.canonical_back != canonical_back
        ):
            continue
        if exclude_ignored and deck.is_ignore:
            continue
        if require_cycle and deck.cycle is None:
            continue
        matched.append(deck)
    return matched


def slot_phase_targets(weighted_avg: float) -> tuple[int, int, int]:
    """Return (phase1_goal, phase1_cap, phase2_ceiling) per spec tie-break rules."""
    floor_e = math.floor(weighted_avg)
    ceil_e = math.ceil(weighted_avg)
    if floor_e == ceil_e:
        if weighted_avg == 0:
            phase1_goal = 0
        else:
            phase1_goal = math.ceil(weighted_avg - 1)
        phase1_cap = floor_e
        phase2_ceiling = math.floor(weighted_avg + 1)
    else:
        phase1_goal = floor_e
        phase1_cap = floor_e
        phase2_ceiling = ceil_e
    return phase1_goal, phase1_cap, phase2_ceiling


def generation_slot_targets_differ(avg_a: float, avg_b: float) -> bool:
    """True when two weighted averages map to different phase 1/2 slot targets."""
    return slot_phase_targets(avg_a) != slot_phase_targets(avg_b)


def card_restricted_to_investigator(
    card: dict[str, Any],
    investigator_code: str,
) -> bool:
    """True when card.restrictions limits it to a specific investigator."""
    restrictions = card.get("restrictions") or {}
    investigators = restrictions.get("investigator")
    if not investigators:
        return False
    return investigator_code not in investigators


@dataclass
class GeneratedDecklist:
    canonical_front: str
    canonical_back: str
    investigator_name: str
    deck_size: int
    slots: dict[str, int]
    entries: list[dict[str, Any]]
    slot_targets: dict[str, dict[str, float | int]]
    deck_count: int
    base_deck_size: int | None = None
    skipped_reason: str | None = None
    first_add_phase: dict[str, str] = field(default_factory=dict)
    option_resolutions: list[DeckOptionResolution] = field(default_factory=list)


_FILENAME_INVALID_RE = re.compile(r'[<>:"/\\|?*]')


def sanitize_export_filename(name: str) -> str:
    """Remove characters invalid on common filesystems."""
    cleaned = _FILENAME_INVALID_RE.sub("", name)
    return cleaned.strip() or "investigator"


def generation_export_filename(
    name: str,
    canonical_front: str,
    *,
    option_suffix: str | None = None,
) -> str:
    base = f"{sanitize_export_filename(name)} {canonical_front}"
    if option_suffix:
        return f"{base} {option_suffix}.csv"
    return f"{base}.csv"


def resolution_export_filename(
    name: str,
    canonical_front: str,
    *,
    option_suffix: str | None = None,
) -> str:
    base = f"{sanitize_export_filename(name)} {canonical_front}"
    if option_suffix:
        return f"{base} {option_suffix} resolution.csv"
    return f"{base} resolution.csv"


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
    subname: str
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

    def deck_limit_at_taboo(
        self,
        card: dict[str, Any],
        canonical_id: str,
        taboo_id: int | None,
    ) -> int:
        """Max copies allowed under taboo (mirrors effective_deck_limit)."""
        entry = self.entry(canonical_id, taboo_id)
        if entry is not None:
            if entry.get("text") == "Forbidden.":
                return 0
            if "deck_limit" in entry:
                return int(entry["deck_limit"])
        limit = card.get("deck_limit")
        if limit is None:
            if card.get("myriad"):
                return 3
            if card.get("exceptional"):
                return 1
            return 2
        return int(limit)


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
            subname=card.get("subname") or "",
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
    deck_xp_weight: float
    has_unknown_slots: bool
    has_chapter_2_cards: bool
    is_ignore: bool
    previous_deck: Any = None
    next_deck: Any = None
    date_creation: Any = None
    customizations: dict[str, str] = field(default_factory=dict)
    meta: dict[str, Any] | None = None


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
        xp_thres: int = DEFAULT_XP_THRES,
    ) -> None:
        self.cards = cards
        self.mapper = mapper
        self.taboo = TabooIndex(taboo_json, mapper)
        self.min_xp_cost = min_xp_cost
        self.bias_compensation = bias_compensation
        self.xp_thres = xp_thres
        apply_runtime_card_patches(cards)
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
        meta_dict: dict[str, Any] | None = None
        meta = decklist.get("meta") or ""
        if meta:
            meta_json = json.loads(meta)
            if isinstance(meta_json, dict):
                meta_dict = meta_json
            for key, value in meta_json.items():
                if key.startswith("cus_"):
                    customizations[key.removeprefix("cus_")] = value

        xp_cost = self.decklist_xp(decklist, slots)

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
            cycle=self.mapper.decklist_cycle(slots, canonical_front=canon_front),
            xp_cost=xp_cost,
            deck_xp_weight=deck_xp_weight(xp_cost, xp_thres=self.xp_thres),
            has_unknown_slots=has_unknown,
            has_chapter_2_cards=has_chapter_2,
            is_ignore=is_ignore,
            previous_deck=decklist.get("previous_deck"),
            next_deck=decklist.get("next_deck"),
            date_creation=decklist.get("date_creation"),
            customizations=customizations,
            meta=meta_dict,
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
        return (
            user_weights[deck.deck_id]
            * cycle_weights.get(deck.cycle, 0.0)
            * deck.deck_xp_weight
        )

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
        inv_decks = investigator_decks(decks, canonical_front, canonical_back)
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
                        "subname": card_info.subname,
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
                        "subname": card_info.subname,
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
                    for deck in investigator_decks(
                        pool, canonical_front, canonical_back
                    )
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
        inv_decks = investigator_decks(
            decks,
            canonical_front,
            canonical_back,
            exclude_ignored=True,
            require_cycle=True,
        )
        user_weights = self.assign_user_weights(decks)
        cycle_weights = self.assign_cycle_weights(inv_decks, user_weights)

        slot_totals: dict[str, float] = defaultdict(float)
        total_weight = 0.0
        for deck in inv_decks:
            weight = self.deck_weight(deck, user_weights, cycle_weights)
            if not weight:
                continue
            total_weight += weight
            accumulate_asset_slot_usage(
                deck.slots,
                weight,
                slot_totals,
                cards=self.cards,
                canonical_cards=self.canonical_cards,
            )

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

    def supports_decklist_generation(
        self,
        canonical_front: str,
        canonical_back: str,
    ) -> tuple[bool, str | None]:
        """Return (supported, skip_reason) for automatic decklist generation."""
        if canonical_front != canonical_back:
            return False, "parallel investigator (canonical_front != canonical_back)"
        inv_card = self.cards.get(canonical_front)
        if inv_card is None or inv_card.get("type_code") != "investigator":
            return False, "missing investigator card"
        return deck_options_support(inv_card.get("deck_options"))

    def list_generatable_investigators(
        self,
        decks: list[PreparedDecklist] | None = None,
    ) -> list[dict[str, Any]]:
        """Return investigators supported for generation, with optional training counts."""
        deck_counts: dict[str, int] = defaultdict(int)
        if decks is not None:
            for deck in decks:
                if deck.is_ignore:
                    continue
                if deck.canonical_front != deck.canonical_back:
                    continue
                deck_counts[deck.canonical_front] += 1
        rows: list[dict[str, Any]] = []
        for canonical_id, card in sorted(self.cards.items()):
            if card.get("type_code") != "investigator":
                continue
            supported, skip_reason = self.supports_decklist_generation(
                canonical_id, canonical_id
            )
            rows.append(
                {
                    "canonical_front": canonical_id,
                    "canonical_back": canonical_id,
                    "name": card.get("name", canonical_id),
                    "supported": supported,
                    "skip_reason": skip_reason,
                    "training_decks": deck_counts.get(canonical_id, 0),
                }
            )
        return rows

    def _deck_limit_at_current_taboo(self, card: dict[str, Any], canonical_id: str) -> int:
        return self.taboo.deck_limit_at_taboo(
            card, canonical_id, self.taboo.max_taboo
        )

    def _xp_at_current_taboo(self, card: dict[str, Any], canonical_id: str) -> int:
        return _effective_xp(
            card,
            canonical_id,
            self.taboo.max_taboo,
            self.taboo,
            use_max_taboo=True,
        )

    def _generation_eligible_row(
        self,
        row: dict[str, Any],
        *,
        investigator_code: str,
        options_validator: DeckOptionsValidator,
        requirement_ids: set[str],
    ) -> bool:
        canonical_id = row["canonical_id"]
        if canonical_id in requirement_ids:
            return False
        if canonical_id == IN_THE_THICK_OF_IT_CANONICAL_ID:
            return False
        if self.taboo.is_forbidden(canonical_id, self.taboo.max_taboo):
            return False
        card = self.cards.get(canonical_id)
        if card is None:
            return False
        if card.get("type_code") == "investigator":
            return False
        if card.get("type_code") in ("treachery", "enemy"):
            return False
        if card.get("subtype_code") == "basicweakness":
            return False
        if card_restricted_to_investigator(card, investigator_code):
            return False
        if row.get("is_customizable"):
            option_index = row.get("option_index")
            if option_index is not None and str(option_index) != "0":
                return False
        xp = self._xp_at_current_taboo(card, canonical_id)
        if xp != 0:
            return False
        if not options_validator.is_card_allowed(card, xp):
            return False
        return True

    def _can_add_generation_copy(
        self,
        canonical_id: str,
        slots: dict[str, int],
    ) -> bool:
        card = self.cards.get(canonical_id)
        if card is None:
            return False
        limit = self._deck_limit_at_current_taboo(card, canonical_id)
        count = self.upgrades.count_option_in_slots(slots, canonical_id)
        return count < limit

    def _slot_vector_for_card(self, canonical_id: str) -> dict[str, float]:
        card = self.cards.get(canonical_id)
        info = self.canonical_cards.get(canonical_id)
        if card is None or info is None or card.get("type_code") != "asset":
            return {}
        return asset_slot_counts(
            canonical_id,
            info.slot,
            info.real_slot,
            1,
            name=info.name,
        )

    def _permanent_set_in_slots(self, slots: dict[str, int]) -> frozenset[str]:
        return frozenset(
            canonical_id
            for canonical_id, count in slots.items()
            if count > 0 and self.cards.get(canonical_id, {}).get("permanent")
        )

    def _deck_includes_all_permanents(
        self,
        deck_slots: dict[str, int],
        required_permanents: frozenset[str],
    ) -> bool:
        if not required_permanents:
            return True
        return required_permanents.issubset(self._permanent_set_in_slots(deck_slots))

    def _accumulate_weighted_slot_usage(
        self,
        deck: PreparedDecklist,
        weight: float,
        slot_totals: dict[str, float],
    ) -> None:
        accumulate_asset_slot_usage(
            deck.slots,
            weight,
            slot_totals,
            cards=self.cards,
            canonical_cards=self.canonical_cards,
        )

    def _smoothed_slot_averages(
        self,
        inv_decks: list[PreparedDecklist],
        user_weights: dict[Any, float],
        cycle_weights: dict[int, float],
        required_permanents: frozenset[str],
        *,
        rho: float = SLOT_AVERAGE_SMOOTHING_RHO,
    ) -> tuple[dict[str, float], dict[str, float | int]]:
        slot_all: dict[str, float] = defaultdict(float)
        slot_subset: dict[str, float] = defaultdict(float)
        weight_all = 0.0
        weight_subset = 0.0
        for deck in inv_decks:
            weight = self.deck_weight(deck, user_weights, cycle_weights)
            if not weight:
                continue
            weight_all += weight
            self._accumulate_weighted_slot_usage(deck, weight, slot_all)
            if self._deck_includes_all_permanents(deck.slots, required_permanents):
                weight_subset += weight
                self._accumulate_weighted_slot_usage(deck, weight, slot_subset)

        meta: dict[str, float | int] = {
            "weight_all": weight_all,
            "weight_subset": weight_subset,
            "smoothing_rho": rho,
        }
        if not weight_all:
            return {}, meta

        average_all = {
            slot_type: slot_all.get(slot_type, 0.0) / weight_all
            for slot_type in STANDARD_ASSET_SLOT_TYPES
        }
        if not required_permanents or weight_subset == 0:
            meta["smoothing_lambda"] = 0.0
            return average_all, meta

        average_subset = {
            slot_type: slot_subset.get(slot_type, 0.0) / weight_subset
            for slot_type in STANDARD_ASSET_SLOT_TYPES
        }
        smoothing_lambda = min(1.0, weight_subset / (rho * weight_all))
        meta["smoothing_lambda"] = smoothing_lambda
        smoothed = {
            slot_type: (
                smoothing_lambda * average_subset.get(slot_type, 0.0)
                + (1.0 - smoothing_lambda) * average_all.get(slot_type, 0.0)
            )
            for slot_type in STANDARD_ASSET_SLOT_TYPES
        }
        return smoothed, meta

    def _slot_targets_from_averages(
        self,
        averages: dict[str, float],
        *,
        smoothing_meta: dict[str, float | int] | None = None,
    ) -> dict[str, dict[str, float | int]]:
        targets: dict[str, dict[str, float | int]] = {}
        for slot_type in STANDARD_ASSET_SLOT_TYPES:
            avg = averages.get(slot_type, 0.0)
            goal, cap, ceiling = slot_phase_targets(avg)
            row: dict[str, float | int] = {
                "weighted_avg": avg,
                "phase1_goal": goal,
                "phase1_cap": cap,
                "phase2_ceiling": ceiling,
            }
            if smoothing_meta is not None:
                row.update(smoothing_meta)
            targets[slot_type] = row
        return targets

    def _select_phase05_permanents(
        self,
        popularity_rows: list[dict[str, Any]],
        deck_size: int,
        *,
        slots: dict[str, int],
        requirement_ids: set[str],
        investigator_code: str,
        options_validator: DeckOptionsValidator,
    ) -> list[str]:
        cutoff_index: int | None = None
        counting = 0
        for index, row in enumerate(popularity_rows):
            if self._row_already_satisfied(row, slots):
                continue
            if not self._generation_eligible_row(
                row,
                investigator_code=investigator_code,
                options_validator=options_validator,
                requirement_ids=requirement_ids,
            ):
                continue
            card = self.cards[row["canonical_id"]]
            if card.get("permanent"):
                continue
            if not counts_toward_player_deck_size(card):
                continue
            counting += 1
            if counting == deck_size:
                cutoff_index = index
                break

        if cutoff_index is None:
            return []

        selected: list[str] = []
        seen: set[str] = set()
        for index in range(cutoff_index):
            row = popularity_rows[index]
            if self._row_already_satisfied(row, slots):
                continue
            canonical_id = row["canonical_id"]
            if canonical_id in seen:
                continue
            card = self.cards.get(canonical_id)
            if card is None or not card.get("permanent"):
                continue
            if not self._generation_eligible_row(
                row,
                investigator_code=investigator_code,
                options_validator=options_validator,
                requirement_ids=requirement_ids,
            ):
                continue
            selected.append(canonical_id)
            seen.add(canonical_id)
        return selected

    def _slot_targets_for_investigator(
        self,
        decks: list[PreparedDecklist],
        canonical_front: str,
        canonical_back: str,
        *,
        required_permanents: frozenset[str] | None = None,
    ) -> dict[str, dict[str, float | int]]:
        inv_decks = investigator_decks(
            decks,
            canonical_front,
            canonical_back,
            exclude_ignored=True,
            require_cycle=True,
        )
        user_weights = self.assign_user_weights(decks)
        cycle_weights = self.assign_cycle_weights(inv_decks, user_weights)
        permanent_set = required_permanents or frozenset()
        averages, meta = self._smoothed_slot_averages(
            inv_decks,
            user_weights,
            cycle_weights,
            permanent_set,
        )
        return self._slot_targets_from_averages(averages, smoothing_meta=meta)

    def _zero_xp_popularity_rows(
        self,
        decks: list[PreparedDecklist],
        canonical_front: str,
        canonical_back: str,
    ) -> list[dict[str, Any]]:
        rows = self.popularity_for_investigator(
            decks, canonical_front, canonical_back
        )
        return [row for row in rows if (row.get("xp") or 0) == 0]

    def _build_generation_entries(
        self,
        slots: dict[str, int],
        requirement_ids: set[str],
        *,
        include_weaknesses: bool = False,
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for canonical_id, count in sorted(
            slots.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            card = self.cards.get(canonical_id)
            info = self.canonical_cards.get(canonical_id)
            if card is None or info is None:
                continue
            if not include_weaknesses and card.get("type_code") in ("treachery", "enemy"):
                continue
            entries.append(
                {
                    "canonical_id": canonical_id,
                    "count": count,
                    "name": info.name,
                    "cycle": info.cycle,
                    "slot": slot_display_label(info.slot, info.real_slot),
                    "xp": 0,
                    "type_code": card.get("type_code"),
                    "is_requirement": canonical_id in requirement_ids,
                }
            )
        return entries

    def generate_decklist(
        self,
        decks: list[PreparedDecklist],
        canonical_front: str,
        canonical_back: str,
        *,
        investigator_option: InvestigatorOptionInput = None,
    ) -> GeneratedDecklist:
        """Build a synthetic 0 XP decklist per spec Automatic Decklist Generation."""
        supported, skip_reason = self.supports_decklist_generation(
            canonical_front, canonical_back
        )
        inv_card = self.cards.get(canonical_front) or {}
        inv_name = inv_card.get("name", canonical_front)
        requirements = inv_card.get("deck_requirements") or {}
        deck_size_target = int(requirements.get("size", 30))
        deck_options = inv_card.get("deck_options") or []

        if not supported:
            return GeneratedDecklist(
                canonical_front=canonical_front,
                canonical_back=canonical_back,
                investigator_name=inv_name,
                deck_size=deck_size_target,
                slots={},
                entries=[],
                slot_targets={},
                deck_count=0,
                base_deck_size=deck_size_target,
                skipped_reason=skip_reason,
            )

        popularity_rows = self._zero_xp_popularity_rows(
            decks, canonical_front, canonical_back
        )
        inv_decks = investigator_decks(
            decks, canonical_front, canonical_back, exclude_ignored=True
        )
        active_inv = investigator_decks(
            decks,
            canonical_front,
            canonical_back,
            exclude_ignored=True,
            require_cycle=True,
        )
        user_weights = self.assign_user_weights(decks)
        cycle_weights = self.assign_cycle_weights(active_inv, user_weights)
        weighted_decks = [
            (
                deck.slots,
                self.deck_weight(deck, user_weights, cycle_weights),
                deck.meta,
            )
            for deck in active_inv
        ]
        resolved_deck_options, base_deck_size, option_resolutions = resolve_deck_options(
            deck_options,
            weighted_decks=weighted_decks,
            cards=self.cards,
            default_deck_size=deck_size_target,
            xp_for_card=self._xp_at_current_taboo,
            investigator_code=canonical_front,
            investigator_option=investigator_option,
        )

        slots: dict[str, int] = {}
        current_slots: dict[str, float] = defaultdict(float)
        first_add_phase: dict[str, str] = {}

        signature_groups = deck_requirement_signature_groups(
            requirements, self.mapper.to_canonical
        )
        requirement_ids = set(all_deck_requirement_card_ids(signature_groups))
        signature_resolutions = resolve_signature_groups(
            signature_groups,
            weighted_decks=weighted_decks,
            cards=self.cards,
        )
        option_resolutions = [
            resolution for _chosen_id, resolution in signature_resolutions
        ] + option_resolutions

        for chosen_id, _resolution in signature_resolutions:
            card = self.cards.get(chosen_id)
            copy_count = int(card.get("quantity") or 1) if card is not None else 1
            slots[chosen_id] = slots.get(chosen_id, 0) + copy_count
            first_add_phase[chosen_id] = "requirement"
            if card is not None and card.get("type_code") == "asset":
                for slot_type, amount in self._slot_vector_for_card(chosen_id).items():
                    current_slots[slot_type] += amount * copy_count

        base_options_validator = DeckOptionsValidator.from_options(resolved_deck_options)
        base_options_validator.seed_counts_from_slots(
            slots,
            self.cards,
            requirement_ids=requirement_ids,
            xp_for_card=self._xp_at_current_taboo,
        )

        phase05_permanents = self._select_phase05_permanents(
            popularity_rows,
            base_deck_size,
            slots=slots,
            requirement_ids=requirement_ids,
            investigator_code=canonical_front,
            options_validator=base_options_validator,
        )
        for canonical_id in phase05_permanents:
            if not self._can_add_generation_copy(canonical_id, slots):
                continue
            card = self.cards.get(canonical_id)
            if card is None:
                continue
            xp = self._xp_at_current_taboo(card, canonical_id)
            if not base_options_validator.can_add_copy(card, xp):
                continue
            slots[canonical_id] = slots.get(canonical_id, 0) + 1
            first_add_phase[canonical_id] = "phase05"
            base_options_validator.add_copy(card, xp)

        merged_deck_options = merge_deck_options_with_permanents(
            resolved_deck_options,
            slots,
            self.cards,
        )
        final_deck_size = effective_deck_size_from_slots(
            slots,
            self.cards,
            base_size=base_deck_size,
        )
        permanent_set = self._permanent_set_in_slots(slots)
        slot_averages, smoothing_meta = self._smoothed_slot_averages(
            active_inv,
            user_weights,
            cycle_weights,
            permanent_set,
        )
        slot_targets = self._slot_targets_from_averages(
            slot_averages,
            smoothing_meta=smoothing_meta,
        )

        options_validator = DeckOptionsValidator.from_options(merged_deck_options)
        options_validator.seed_counts_from_slots(
            slots,
            self.cards,
            requirement_ids=requirement_ids,
            xp_for_card=self._xp_at_current_taboo,
        )
        apply_permanent_composition_rules(
            options_validator,
            slots,
            self.cards,
            requirement_ids=requirement_ids,
        )
        minimum_skills = options_validator.minimum_skills

        def phase1_goals_met() -> bool:
            return all(
                current_slots.get(slot_type, 0.0) >= slot_targets[slot_type]["phase1_goal"]
                for slot_type in STANDARD_ASSET_SLOT_TYPES
            )

        def fits_phase1_cap(slot_vector: dict[str, float]) -> bool:
            for slot_type in STANDARD_ASSET_SLOT_TYPES:
                addition = slot_vector.get(slot_type, 0.0)
                if addition == 0:
                    continue
                cap = int(slot_targets[slot_type]["phase1_cap"])
                if current_slots.get(slot_type, 0.0) + addition > cap:
                    return False
            return True

        def fits_phase2_ceiling(slot_vector: dict[str, float]) -> bool:
            for slot_type in STANDARD_ASSET_SLOT_TYPES:
                addition = slot_vector.get(slot_type, 0.0)
                if addition == 0:
                    continue
                ceiling = int(slot_targets[slot_type]["phase2_ceiling"])
                if current_slots.get(slot_type, 0.0) + addition > ceiling:
                    return False
            return True

        def non_permanent_count() -> int:
            total = 0
            for canonical_id, count in slots.items():
                if canonical_id in requirement_ids:
                    continue
                card = self.cards.get(canonical_id)
                if card is None or card.get("permanent"):
                    continue
                total += count
            return total

        def skills_in_deck() -> int:
            total = 0
            for canonical_id, count in slots.items():
                if canonical_id in requirement_ids:
                    continue
                card = self.cards.get(canonical_id)
                if card is None or card.get("type_code") != "skill":
                    continue
                total += count
            return total

        def remaining_skill_reserve() -> int:
            return max(0, minimum_skills - skills_in_deck())

        def phase2_complete() -> bool:
            if non_permanent_count() < final_deck_size:
                return False
            if skills_in_deck() < minimum_skills:
                return False
            return True

        def try_add_copy(canonical_id: str, phase: str) -> bool:
            card = self.cards.get(canonical_id)
            if card is None:
                return False
            if not self._can_add_generation_copy(canonical_id, slots):
                return False
            xp = self._xp_at_current_taboo(card, canonical_id)
            if not options_validator.can_add_copy(card, xp):
                return False
            if canonical_id not in first_add_phase:
                first_add_phase[canonical_id] = phase
            slots[canonical_id] = slots.get(canonical_id, 0) + 1
            for slot_type, amount in self._slot_vector_for_card(canonical_id).items():
                current_slots[slot_type] += amount
            options_validator.add_copy(card, xp)
            return True

        if not phase1_goals_met():
            for row in popularity_rows:
                if phase1_goals_met():
                    break
                if self._row_already_satisfied(row, slots):
                    continue
                if not self._generation_eligible_row(
                    row,
                    investigator_code=canonical_front,
                    options_validator=options_validator,
                    requirement_ids=requirement_ids,
                ):
                    continue
                canonical_id = row["canonical_id"]
                card = self.cards[canonical_id]
                if card.get("type_code") != "asset":
                    continue
                slot_vector = self._slot_vector_for_card(canonical_id)
                if not slot_vector:
                    continue
                if not fits_phase1_cap(slot_vector):
                    continue
                try_add_copy(canonical_id, "phase1")

        for row in popularity_rows:
            if phase2_complete():
                break
            if self._row_already_satisfied(row, slots):
                continue
            if not self._generation_eligible_row(
                row,
                investigator_code=canonical_front,
                options_validator=options_validator,
                requirement_ids=requirement_ids,
            ):
                continue
            canonical_id = row["canonical_id"]
            card = self.cards[canonical_id]
            if card.get("permanent"):
                continue
            if minimum_skills and card.get("type_code") != "skill":
                slots_left = final_deck_size - non_permanent_count()
                if slots_left <= remaining_skill_reserve():
                    continue
            if card.get("type_code") == "asset":
                slot_vector = self._slot_vector_for_card(canonical_id)
                if not fits_phase2_ceiling(slot_vector):
                    continue
            try_add_copy(canonical_id, "phase2")

        entries = self._build_generation_entries(
            slots, requirement_ids, include_weaknesses=False
        )
        return GeneratedDecklist(
            canonical_front=canonical_front,
            canonical_back=canonical_back,
            investigator_name=inv_name,
            deck_size=final_deck_size,
            slots=slots,
            entries=entries,
            slot_targets=slot_targets,
            deck_count=non_permanent_count(),
            base_deck_size=base_deck_size,
            skipped_reason=None,
            first_add_phase=first_add_phase,
            option_resolutions=option_resolutions,
        )

    def _requirement_ids_for_investigator(self, canonical_front: str) -> set[str]:
        return set(
            investigator_requirement_card_ids(
                self.cards, canonical_front, self.mapper.to_canonical
            )
        )

    def _popularity_row_in_slots(
        self,
        row: dict[str, Any],
        slots: dict[str, int],
    ) -> bool:
        canonical_id = row["canonical_id"]
        count = self.upgrades.count_option_in_slots(slots, canonical_id)
        if row.get("is_customizable"):
            return count >= 1
        card_index = row.get("card_index")
        if card_index is None:
            return count >= 1
        return count >= int(card_index)

    def _row_already_satisfied(self, row: dict[str, Any], slots: dict[str, int]) -> bool:
        return self._popularity_row_in_slots(row, slots)

    def generation_popularity_table(
        self,
        decks: list[PreparedDecklist],
        canonical_front: str,
        canonical_back: str,
        *,
        generated: GeneratedDecklist | None = None,
        investigator_option: InvestigatorOptionInput = None,
    ) -> list[dict[str, Any]]:
        """0 XP popularity rows through the last included generated option."""
        if generated is None:
            generated = self.generate_decklist(
                decks,
                canonical_front,
                canonical_back,
                investigator_option=investigator_option,
            )
        if generated.skipped_reason:
            return []

        popularity_rows = self._zero_xp_popularity_rows(
            decks, canonical_front, canonical_back
        )
        deck_ids = {
            canonical_id
            for canonical_id, count in generated.slots.items()
            if count > 0
        }

        last_index = -1
        for index, row in enumerate(popularity_rows):
            if self._row_already_satisfied(row, generated.slots):
                last_index = index

        truncated = popularity_rows[: last_index + 1] if last_index >= 0 else []
        covered_ids = {
            row["canonical_id"]
            for row in truncated
            if self._row_already_satisfied(row, generated.slots)
        }
        missing_ids = sorted(deck_ids - covered_ids)

        export_rows: list[dict[str, Any]] = []
        for rank, row in enumerate(truncated, start=1):
            canonical_id = row["canonical_id"]
            info = self.canonical_cards.get(canonical_id)
            export_rows.append(
                {
                    "rank": rank,
                    "canonical_id": canonical_id,
                    "card_index": row.get("card_index"),
                    "option_index": row.get("option_index"),
                    "name": row.get("name"),
                    "subname": row.get("subname") or (info.subname if info else ""),
                    "cycle": info.cycle if info else None,
                    "slot": row.get("slot"),
                    "p5_popularity": row.get("p5_popularity"),
                    "included_in_generated": self._row_already_satisfied(
                        row, generated.slots
                    ),
                    "generated_count": generated.slots.get(canonical_id, 0),
                }
            )

        next_rank = len(export_rows) + 1
        for canonical_id in missing_ids:
            card = self.cards.get(canonical_id)
            info = self.canonical_cards.get(canonical_id)
            if card is None or info is None:
                continue
            export_rows.append(
                {
                    "rank": next_rank,
                    "canonical_id": canonical_id,
                    "card_index": None,
                    "option_index": None,
                    "name": info.name,
                    "subname": info.subname,
                    "cycle": info.cycle,
                    "slot": slot_display_label(info.slot, info.real_slot),
                    "p5_popularity": None,
                    "included_in_generated": True,
                    "generated_count": generated.slots.get(canonical_id, 0),
                }
            )
            next_rank += 1

        return export_rows

    def export_generated_decklist(
        self,
        decks: list[PreparedDecklist],
        canonical_front: str,
        canonical_back: str,
        output_dir: str | Path = "generated",
        *,
        investigator_option: InvestigatorOptionInput = None,
        diagnostics: bool = False,
    ) -> list[Path]:
        """Write one generated deck CSV (and optional resolution CSV) for an investigator."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        inv_card = self.cards.get(canonical_front) or {}
        inv_name = inv_card.get("name", canonical_front)
        generated = self.generate_decklist(
            decks,
            canonical_front,
            canonical_back,
            investigator_option=investigator_option,
        )
        override = parse_investigator_option(
            investigator_option,
            inv_card.get("deck_options") or [],
        )
        option_suffix = investigator_option_slug(
            override=override,
            resolutions=generated.option_resolutions,
        )
        fieldnames = [
            "rank",
            "canonical_id",
            "card_index",
            "option_index",
            "name",
            "subname",
            "cycle",
            "slot",
            "p5_popularity",
            "included_in_generated",
            "generated_count",
        ]
        resolution_fieldnames = [
            "resolution_kind",
            "option_name",
            "choice",
            "weighted_total",
            "weight_share",
            "selected",
        ]
        written: list[Path] = []
        rows = self.generation_popularity_table(
            decks,
            canonical_front,
            canonical_back,
            generated=generated,
            investigator_option=investigator_option,
        )
        path = out / generation_export_filename(
            inv_name, canonical_front, option_suffix=option_suffix
        )
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        written.append(path)

        if diagnostics and generated.option_resolutions:
            resolution_path = out / resolution_export_filename(
                inv_name, canonical_front, option_suffix=option_suffix
            )
            resolution_rows: list[dict[str, Any]] = []
            for resolution in generated.option_resolutions:
                resolution_rows.extend(resolution.to_csv_rows())
            with resolution_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=resolution_fieldnames)
                writer.writeheader()
                for row in resolution_rows:
                    writer.writerow(row)
            written.append(resolution_path)
        return written

    def export_generated_decklist_csvs(
        self,
        decks: list[PreparedDecklist],
        output_dir: str | Path = "generated",
        *,
        diagnostics: bool = False,
    ) -> list[Path]:
        """Write one CSV per supported investigator with training data."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        fieldnames = [
            "rank",
            "canonical_id",
            "card_index",
            "option_index",
            "name",
            "subname",
            "cycle",
            "slot",
            "p5_popularity",
            "included_in_generated",
            "generated_count",
        ]
        resolution_fieldnames = [
            "resolution_kind",
            "option_name",
            "choice",
            "weighted_total",
            "weight_share",
            "selected",
        ]

        for investigator in self.list_generatable_investigators(decks):
            if not investigator["supported"]:
                continue
            if investigator["training_decks"] <= 0:
                continue
            canonical_front = investigator["canonical_front"]
            canonical_back = investigator["canonical_back"]
            generated = self.generate_decklist(
                decks, canonical_front, canonical_back
            )
            rows = self.generation_popularity_table(
                decks,
                canonical_front,
                canonical_back,
                generated=generated,
            )
            filename = generation_export_filename(
                investigator["name"], canonical_front
            )
            path = out / filename
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
            written.append(path)

            if diagnostics and generated.option_resolutions:
                resolution_path = out / resolution_export_filename(
                    investigator["name"], canonical_front
                )
                resolution_rows: list[dict[str, Any]] = []
                for resolution in generated.option_resolutions:
                    resolution_rows.extend(resolution.to_csv_rows())
                with resolution_path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=resolution_fieldnames)
                    writer.writeheader()
                    for row in resolution_rows:
                        writer.writerow(row)
                written.append(resolution_path)

        return written


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
                "deck_xp_weight": deck.deck_xp_weight,
                "cycle": deck.cycle,
                "has_unknown_slots": deck.has_unknown_slots,
                "has_chapter_2_cards": deck.has_chapter_2_cards,
                "is_ignore": deck.is_ignore,
                "customizations": deck.customizations,
            }
        )
    return pd.DataFrame.from_records(records)
