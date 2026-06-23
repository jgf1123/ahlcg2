# -*- coding: utf-8 -*-
"""ArkhamDB deck_options parsing and legality for decklist generation."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

CHARLIE_KANE_CODE = "09018"
CLASS_CHOICE_FACTIONS = frozenset(
    {"guardian", "seeker", "rogue", "mystic", "survivor"}
)
WeightedTrainingDeck = tuple[dict[str, int], float, dict[str, Any] | None]

SUPPORTED_DECK_OPTION_KEYS = frozenset(
    {
        "faction",
        "level",
        "limit",
        "error",
        "trait",
        "tag",
        "text",
        "type",
        "not",
        "uses",
        "faction_select",
        "name",
        "id",
        "deck_size_select",
    }
)
UNSUPPORTED_DECK_OPTION_KEYS = frozenset(
    {
        "option_select",
        "atleast",
        "base_level",
        "permanent",
    }
)
_METADATA_KEYS = frozenset({"name", "id", "error", "deck_size_select"})
_TRAIT_SPLIT_RE = re.compile(r"[.,\s]+")
_USES_RE = re.compile(r"uses\s*\([^)]*\)", re.IGNORECASE)


def is_standard_deck_options(deck_options: list[dict[str, Any]] | None) -> bool:
    """True when every deck_options block is faction + level only (generation v1)."""
    if not deck_options:
        return False
    for option in deck_options:
        if set(option.keys()) != frozenset({"faction", "level"}):
            return False
        level = option.get("level")
        if not isinstance(level, dict) or set(level.keys()) - {"min", "max"}:
            return False
    return True


def deck_options_support(deck_options: list[dict[str, Any]] | None) -> tuple[bool, str | None]:
    """Return whether automatic generation can parse these deck_options."""
    if not deck_options:
        return False, "empty deck_options"
    keys: set[str] = set()
    for option in deck_options:
        keys |= set(option.keys())
    unsupported = keys & UNSUPPORTED_DECK_OPTION_KEYS
    if unsupported:
        return False, f"unsupported deck_options keys: {sorted(unsupported)}"
    unknown = keys - SUPPORTED_DECK_OPTION_KEYS
    if unknown:
        return False, f"unknown deck_options keys: {sorted(unknown)}"
    return True, None


def get_card_text(card: dict[str, Any]) -> str:
    text = card.get("real_text") or card.get("text") or ""
    return text if isinstance(text, str) else ""


def get_card_traits(card: dict[str, Any]) -> str:
    traits = card.get("real_traits") or card.get("traits") or ""
    return traits if isinstance(traits, str) else ""


def card_has_trait(card: dict[str, Any], target_trait: str) -> bool:
    traits = get_card_traits(card).lower()
    if not traits:
        return False
    target = target_trait.strip().lower()
    for part in _TRAIT_SPLIT_RE.split(traits):
        if part.strip() == target:
            return True
    return False


def card_has_tag(card: dict[str, Any], target_tag: str) -> bool:
    tags = card.get("tags")
    if not tags:
        return False
    if isinstance(tags, str):
        return target_tag in tags
    if isinstance(tags, list):
        return any(target_tag in str(tag) for tag in tags)
    return False


def _card_text_matches_patterns(
    card: dict[str, Any],
    patterns: list[str],
    *,
    text_regexes: dict[str, re.Pattern[str]] | None = None,
) -> bool:
    if not patterns:
        return False
    text = get_card_text(card)
    for pattern in patterns:
        regex = (text_regexes or {}).get(pattern)
        if regex is not None:
            if not regex.search(text):
                return False
        elif not re.search(f"(?i){pattern}", text):
            return False
    return True


def _matches_tag_or_text_constraints(
    card: dict[str, Any],
    option: dict[str, Any],
    *,
    text_regexes: dict[str, re.Pattern[str]] | None = None,
) -> bool:
    """When an option lists tag and/or text, ArkhamDB treats them as alternate paths."""
    tags = option.get("tag")
    patterns = _option_text_patterns(option)
    if not tags and not patterns:
        return True
    tag_match = any(card_has_tag(card, tag) for tag in tags) if tags else False
    text_match = _card_text_matches_patterns(
        card, patterns, text_regexes=text_regexes
    )
    if tags and patterns:
        return tag_match or text_match
    return tag_match if tags else text_match


def card_has_uses(card: dict[str, Any], uses_values: list[str]) -> bool:
    text = get_card_text(card).lower()
    for value in uses_values:
        if value.lower() in text:
            return True
    if _USES_RE.search(text):
        for value in uses_values:
            if value.lower() in text:
                return True
    return False


def card_faction_codes(card: dict[str, Any]) -> set[str]:
    factions = {card.get("faction_code")}
    faction2 = card.get("faction2_code")
    if faction2:
        factions.add(faction2)
    return {code for code in factions if code}


def deckbuilding_level(card: dict[str, Any]) -> int:
    """Printed XP level for deck_options level ranges (not taboo purchase cost)."""
    xp = card.get("xp")
    return 0 if xp is None else int(xp)


def is_scenario_reward_card(card: dict[str, Any]) -> bool:
    """Campaign/scenario reward (ArkhamDB star); legal in deck, no deck size."""
    if card.get("subtype_code") in ("weakness", "basicweakness"):
        return False
    if not card.get("encounter_code"):
        return False
    return card.get("type_code") in ("asset", "event")


def is_illegal_encounter_card_in_player_deck(card: dict[str, Any]) -> bool:
    """Encounter cards that must not appear in a player deck (e.g. locations)."""
    if not card.get("encounter_code"):
        return False
    if card.get("subtype_code") in ("weakness", "basicweakness"):
        return False
    return card.get("type_code") in ("location", "enemy")


def counts_toward_player_deck_size(card: dict[str, Any]) -> bool:
    """True when a card copy counts toward deck_requirements.size."""
    if card.get("permanent"):
        return False
    if card.get("subtype_code") in ("basicweakness", "weakness"):
        return False
    if is_scenario_reward_card(card):
        return False
    return True


def deck_requirement_signature_groups(
    deck_requirements: dict[str, Any],
    to_canonical: Any,
) -> list[frozenset[str]]:
    """OR-groups of interchangeable signature cards from deck_requirements.card."""
    groups: list[frozenset[str]] = []
    for key, value in (deck_requirements.get("card") or {}).items():
        if isinstance(value, dict):
            codes = {to_canonical(str(code)) for code in value.values()}
        else:
            codes = {to_canonical(str(key))}
        groups.append(frozenset(codes))
    return groups


def all_deck_requirement_card_ids(groups: list[frozenset[str]]) -> frozenset[str]:
    """Every signature printing in any OR-group (all exempt from deck size)."""
    combined: set[str] = set()
    for group in groups:
        combined |= group
    return frozenset(combined)


def choose_signature_from_group(
    group: frozenset[str],
    weights_by_id: dict[str, float],
) -> str:
    """Pick one signature from an OR-group by highest weight; tie-break by id."""
    return max(group, key=lambda canonical_id: (weights_by_id.get(canonical_id, 0.0), canonical_id))


CLASS_FACTIONS = ["guardian", "seeker", "rogue", "mystic", "survivor"]

DECK_SIZE_DELTA_RE = re.compile(
    r"(?:you get \+(\d+) deck size|increase your deck size by (\d+)|"
    r"reduce your deck size by (\d+))",
    re.IGNORECASE,
)

DECK_OPTION_GAIN_RE = re.compile(
    r"Deckbuilding Options gain[s]?:\s*\"([^\"]+)\"",
    re.IGNORECASE,
)


def permanent_deck_size_delta(card: dict[str, Any], copies: int) -> int:
    """Net deck size change from a permanent card's rules text."""
    if not card.get("permanent") or copies <= 0:
        return 0
    delta = 0
    for match in DECK_SIZE_DELTA_RE.finditer(get_card_text(card)):
        if match.group(1):
            delta += int(match.group(1)) * copies
        if match.group(2):
            delta += int(match.group(2)) * copies
        if match.group(3):
            delta -= int(match.group(3)) * copies
    return delta


def effective_deck_size_from_slots(
    slots: dict[str, int],
    cards: dict[str, dict[str, Any]],
    *,
    base_size: int = 30,
) -> int:
    size = base_size
    for cid, copies in slots.items():
        card = cards.get(cid)
        if card is None:
            continue
        size += permanent_deck_size_delta(card, copies)
    return size


def parse_granted_deck_option(grant_text: str) -> dict[str, Any] | None:
    """Parse a permanent-card deckbuilding grant into a deck_options block."""
    text = grant_text.strip().lower()
    if "one other level 0 card from any class" in text:
        return {
            "faction": list(CLASS_FACTIONS),
            "level": {"min": 0, "max": 0},
        }
    if (
        "relic" in text
        and "charm" in text
        and "asset" in text
        and "level 0-3" in text
    ):
        return {
            "faction": list(CLASS_FACTIONS),
            "level": {"min": 0, "max": 3},
            "type": ["asset"],
            "trait": ["Relic", "Charm"],
        }
    return None


def permanent_granted_deck_options(
    slots: dict[str, int],
    cards: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """One deck_options entry per permanent copy that grants deckbuilding."""
    granted: list[dict[str, Any]] = []
    for cid, copies in slots.items():
        if copies <= 0:
            continue
        card = cards.get(cid)
        if card is None or not card.get("permanent"):
            continue
        for match in DECK_OPTION_GAIN_RE.finditer(get_card_text(card)):
            parsed = parse_granted_deck_option(match.group(1))
            if parsed is None:
                continue
            for _ in range(copies):
                granted.append({**parsed, "limit": 1})
    return granted


def merge_deck_options_with_permanents(
    deck_options: list[dict[str, Any]],
    slots: dict[str, int],
    cards: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return list(deck_options) + permanent_granted_deck_options(slots, cards)


def _option_text_patterns(option: dict[str, Any]) -> list[str]:
    text = option.get("text")
    if text is None:
        return []
    if isinstance(text, str):
        return [text]
    if isinstance(text, list):
        return [str(item) for item in text]
    return []


def _option_is_size_only(option: dict[str, Any]) -> bool:
    return bool(option.get("deck_size_select")) and not option.get("faction")


def _option_can_allow_cards(option: dict[str, Any]) -> bool:
    if _option_is_size_only(option):
        return False
    if option.get("faction") or option.get("faction_select"):
        return True
    if option.get("trait") and not option.get("not"):
        return True
    if option.get("tag"):
        return True
    if option.get("text"):
        return True
    if option.get("type"):
        return True
    if option.get("uses"):
        return True
    if option.get("level") and not option.get("not"):
        return True
    return False


@dataclass
class DeckOptionResolution:
    """How a `faction_select` or `deck_size_select` choice was resolved."""

    kind: str
    option_name: str | None
    choice: str
    weighted_totals: dict[str, float]
    weight_shares: dict[str, float]

    def to_csv_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for option_value in sorted(
            self.weighted_totals,
            key=lambda value: (-self.weighted_totals[value], value),
        ):
            rows.append(
                {
                    "resolution_kind": self.kind,
                    "option_name": self.option_name or "",
                    "choice": option_value,
                    "weighted_total": self.weighted_totals[option_value],
                    "weight_share": self.weight_shares.get(option_value, 0.0),
                    "selected": option_value == self.choice,
                }
            )
        return rows


def asset_takes_ally_slot(card: dict[str, Any]) -> bool:
    """True when an asset uses the ally slot."""
    if card.get("type_code") != "asset":
        return False
    slot = card.get("real_slot") or card.get("slot") or ""
    for part in slot.split(". "):
        base = part.split(" x2", 1)[0].strip()
        if base == "Ally":
            return True
    return False


def _title_counts_from_slots(
    slots: dict[str, int],
    cards: dict[str, dict[str, Any]],
    *,
    requirement_ids: frozenset[str],
) -> Counter:
    counts: Counter = Counter()
    for canonical_id, count in slots.items():
        if count <= 0:
            continue
        if canonical_id in requirement_ids:
            continue
        card = cards.get(canonical_id)
        if card is None:
            continue
        if card.get("subtype_code") in ("basicweakness", "weakness"):
            continue
        name = card.get("name")
        if name:
            counts[name] += count
    return counts


def apply_permanent_composition_rules(
    validator: DeckOptionsValidator,
    slots: dict[str, int],
    cards: dict[str, dict[str, Any]],
    *,
    requirement_ids: set[str],
) -> None:
    """Configure validator flags from permanent cards already in the deck."""
    req = frozenset(requirement_ids)
    validator.requirement_ids = req
    validator.forbid_ally_slot_assets = False
    validator.singleton_by_title = False
    validator.minimum_skills = 0
    for canonical_id, copies in slots.items():
        if copies <= 0:
            continue
        card = cards.get(canonical_id)
        if card is None or not card.get("permanent"):
            continue
        text = get_card_text(card).lower()
        if "no assets that take up an ally slot" in text:
            validator.forbid_ally_slot_assets = True
        if "cannot include more than 1 copy of each" in text and "by title" in text:
            validator.singleton_by_title = True
        if "must include at least 10 skills" in text:
            validator.minimum_skills = max(validator.minimum_skills, 10)
    if validator.singleton_by_title:
        validator.title_counts = _title_counts_from_slots(
            slots, cards, requirement_ids=req
        )
    else:
        validator.title_counts = Counter()


@dataclass
class DeckOptionsValidator:
    """Check card legality and option limits for an investigator."""

    deck_options: list[dict[str, Any]]
    text_regexes: dict[str, re.Pattern[str]] = field(default_factory=dict)
    option_counts: list[int] = field(default_factory=list)
    forbid_ally_slot_assets: bool = False
    singleton_by_title: bool = False
    minimum_skills: int = 0
    title_counts: Counter = field(default_factory=Counter)
    requirement_ids: frozenset[str] = frozenset()

    @classmethod
    def from_options(cls, deck_options: list[dict[str, Any]]) -> DeckOptionsValidator:
        text_regexes: dict[str, re.Pattern[str]] = {}
        for option in deck_options:
            for pattern in _option_text_patterns(option):
                if pattern not in text_regexes:
                    text_regexes[pattern] = re.compile(f"(?i){pattern}")
        return cls(
            deck_options=deck_options,
            text_regexes=text_regexes,
            option_counts=[0] * len(deck_options),
        )

    def reset_counts(self) -> None:
        self.option_counts = [0] * len(self.deck_options)

    def seed_counts_from_slots(
        self,
        slots: dict[str, int],
        cards: dict[str, dict[str, Any]],
        *,
        requirement_ids: set[str],
        xp_for_card: Any,
    ) -> None:
        """Initialize per-option counts from existing deck slots."""
        self.reset_counts()
        for canonical_id, count in slots.items():
            if canonical_id in requirement_ids:
                continue
            card = cards.get(canonical_id)
            if card is None:
                continue
            if card.get("type_code") in ("treachery", "enemy"):
                continue
            if card.get("subtype_code") in ("basicweakness", "weakness"):
                continue
            xp = xp_for_card(card, canonical_id)
            option_index = self.first_matching_option_index(card, xp)
            if option_index >= 0:
                self.option_counts[option_index] += count

    def is_globally_excluded(self, card: dict[str, Any], xp: int) -> bool:
        for option in self.deck_options:
            if not option.get("not"):
                continue
            criteria = {
                key: value
                for key, value in option.items()
                if key not in {"not", "error", "limit", "name", "id"}
            }
            if criteria and self.card_matches_option(card, xp, criteria):
                return True
        return False

    def card_matches_option(
        self,
        card: dict[str, Any],
        xp: int,
        option: dict[str, Any],
    ) -> bool:
        factions = option.get("faction")
        if factions:
            card_factions = card_faction_codes(card)
            faction_match = bool(card_factions & set(factions))
            if option.get("not"):
                if faction_match:
                    return False
            elif not faction_match:
                return False

        level = option.get("level")
        if level is not None:
            min_level = int(level.get("min", 0))
            max_level = int(level.get("max", 5))
            card_level = deckbuilding_level(card)
            if card_level < min_level or card_level > max_level:
                return False

        types = option.get("type")
        if types:
            card_type = card.get("type_code")
            if card_type not in types:
                return False

        traits = option.get("trait")
        if traits:
            trait_match = any(card_has_trait(card, trait) for trait in traits)
            if option.get("not"):
                if trait_match:
                    return False
            elif not trait_match:
                return False

        tags = option.get("tag")
        patterns = _option_text_patterns(option)
        if tags or patterns:
            if not _matches_tag_or_text_constraints(
                card, option, text_regexes=self.text_regexes
            ):
                return False

        uses = option.get("uses")
        if uses:
            if not card_has_uses(card, uses):
                return False

        return True

    def is_card_allowed(self, card: dict[str, Any], xp: int) -> bool:
        if self.is_globally_excluded(card, xp):
            return False
        for option in self.deck_options:
            if not _option_can_allow_cards(option):
                continue
            if self.card_matches_option(card, xp, option):
                return True
        return False

    def first_matching_option_index(self, card: dict[str, Any], xp: int) -> int:
        for index, option in enumerate(self.deck_options):
            if not _option_can_allow_cards(option):
                continue
            if self.card_matches_option(card, xp, option):
                return index
        return -1

    def can_add_copy(self, card: dict[str, Any], xp: int) -> bool:
        if not self.is_card_allowed(card, xp):
            return False
        if self.forbid_ally_slot_assets and asset_takes_ally_slot(card):
            return False
        if self.singleton_by_title:
            name = card.get("name")
            if name and self.title_counts.get(name, 0) >= 1:
                return False
        option_index = self.first_matching_option_index(card, xp)
        if option_index < 0:
            return False
        limit = int(self.deck_options[option_index].get("limit") or 0)
        if limit > 0 and self.option_counts[option_index] >= limit:
            return False
        return True

    def add_copy(self, card: dict[str, Any], xp: int) -> None:
        option_index = self.first_matching_option_index(card, xp)
        if option_index >= 0:
            self.option_counts[option_index] += 1
        name = card.get("name")
        if self.singleton_by_title and name:
            self.title_counts[name] += 1


def primary_factions_from_options(deck_options: list[dict[str, Any]]) -> set[str]:
    factions: set[str] = set()
    for option in deck_options:
        if option.get("faction_select") or option.get("not"):
            continue
        for faction in option.get("faction") or []:
            if faction != "neutral":
                factions.add(faction)
    return factions


def _compile_option_text_regexes(option: dict[str, Any]) -> dict[str, re.Pattern[str]]:
    text_regexes: dict[str, re.Pattern[str]] = {}
    for pattern in _option_text_patterns(option):
        if pattern not in text_regexes:
            text_regexes[pattern] = re.compile(f"(?i){pattern}")
    return text_regexes


def _card_matches_option_criteria(
    card: dict[str, Any],
    xp: int,
    option: dict[str, Any],
    *,
    text_regexes: dict[str, re.Pattern[str]] | None = None,
) -> bool:
    regexes = text_regexes if text_regexes is not None else _compile_option_text_regexes(
        option
    )
    factions = option.get("faction")
    if factions:
        card_factions = card_faction_codes(card)
        faction_match = bool(card_factions & set(factions))
        if option.get("not"):
            if faction_match:
                return False
        elif not faction_match:
            return False

    level = option.get("level")
    if level is not None:
        min_level = int(level.get("min", 0))
        max_level = int(level.get("max", 5))
        card_level = deckbuilding_level(card)
        if card_level < min_level or card_level > max_level:
            return False

    types = option.get("type")
    if types:
        if card.get("type_code") not in types:
            return False

    traits = option.get("trait")
    if traits:
        trait_match = any(card_has_trait(card, trait) for trait in traits)
        if option.get("not"):
            if trait_match:
                return False
        elif not trait_match:
            return False

    tags = option.get("tag")
    patterns = _option_text_patterns(option)
    if tags or patterns:
        if not _matches_tag_or_text_constraints(
            card, option, text_regexes=regexes
        ):
            return False

    uses = option.get("uses")
    if uses:
        if not card_has_uses(card, uses):
            return False

    return True


def parse_deck_meta_json(meta: Any) -> dict[str, Any] | None:
    if not meta:
        return None
    if isinstance(meta, dict):
        return meta
    if isinstance(meta, str):
        try:
            parsed = json.loads(meta)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def meta_class_pair(meta: dict[str, Any] | None) -> tuple[str, str] | None:
    """Return an unordered class pair from Charlie-style deck meta."""
    if meta is None:
        return None
    f1 = meta.get("faction_1")
    f2 = meta.get("faction_2")
    if not f1 or not f2:
        return None
    if f1 not in CLASS_CHOICE_FACTIONS or f2 not in CLASS_CHOICE_FACTIONS:
        return None
    return tuple(sorted((f1, f2)))


def is_charlie_dual_class_select(deck_options: list[dict[str, Any]]) -> bool:
    faction_selects = [option for option in deck_options if option.get("faction_select")]
    if len(faction_selects) != 2:
        return False
    return {option.get("id") for option in faction_selects} == {
        "faction_1",
        "faction_2",
    }


def format_faction_pair(f1: str, f2: str) -> str:
    ordered = sorted((f1, f2))
    return f"{ordered[0]}+{ordered[1]}"


InvestigatorOptionInput = str | int | tuple[str, str] | dict[str, Any] | None


@dataclass
class InvestigatorOptionOverride:
    """Explicit deck_options branches to use instead of popularity resolution."""

    deck_size: int | None = None
    factions_by_option_id: dict[str, str] = field(default_factory=dict)


def is_dual_class_select(deck_options: list[dict[str, Any]]) -> bool:
    return is_charlie_dual_class_select(deck_options)


def faction_select_options(
    deck_options: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [option for option in deck_options if option.get("faction_select")]


def deck_size_select_option(
    deck_options: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for option in deck_options:
        if option.get("deck_size_select"):
            return option
    return None


def _faction_select_option_key(option: dict[str, Any]) -> str:
    return str(option.get("id") or "")


def _normalize_class_pair(
    value: str | tuple[str, str] | list[str],
    *,
    candidate_factions: set[str],
) -> tuple[str, str]:
    if isinstance(value, str):
        if "+" not in value:
            raise ValueError(f"class pair must contain '+', got {value!r}")
        left, right = value.split("+", 1)
        f1, f2 = left.strip(), right.strip()
    else:
        if len(value) != 2:
            raise ValueError(f"class pair must have exactly two factions, got {value!r}")
        f1, f2 = value[0], value[1]
    if f1 not in candidate_factions or f2 not in candidate_factions:
        raise ValueError(f"invalid class pair factions: {f1!r}, {f2!r}")
    if f1 == f2:
        raise ValueError(f"class pair factions must differ: {f1!r}")
    return tuple(sorted((f1, f2)))


def parse_investigator_option(
    spec: InvestigatorOptionInput,
    deck_options: list[dict[str, Any]],
) -> InvestigatorOptionOverride | None:
    """Parse user-facing investigator_option into a normalized override."""
    if spec is None:
        return None

    faction_selects = faction_select_options(deck_options)
    size_option = deck_size_select_option(deck_options)
    size_choices = (
        [int(value) for value in size_option["deck_size_select"]]
        if size_option is not None
        else []
    )
    candidate_factions = (
        set(faction_selects[0]["faction_select"]) if faction_selects else set()
    )
    override = InvestigatorOptionOverride()

    if isinstance(spec, int):
        override.deck_size = spec
    elif isinstance(spec, str):
        if "+" in spec:
            pair = _normalize_class_pair(spec, candidate_factions=candidate_factions)
            override.factions_by_option_id["faction_1"] = pair[0]
            override.factions_by_option_id["faction_2"] = pair[1]
        elif spec.isdigit() and size_choices:
            override.deck_size = int(spec)
        else:
            if len(faction_selects) != 1:
                raise ValueError(
                    f"ambiguous faction option {spec!r}; use a dict for investigators "
                    "with multiple choices"
                )
            if spec not in candidate_factions:
                raise ValueError(f"invalid faction {spec!r}")
            override.factions_by_option_id[_faction_select_option_key(faction_selects[0])] = spec
    elif isinstance(spec, tuple):
        pair = _normalize_class_pair(spec, candidate_factions=candidate_factions)
        override.factions_by_option_id["faction_1"] = pair[0]
        override.factions_by_option_id["faction_2"] = pair[1]
    elif isinstance(spec, dict):
        if "deck_size" in spec or "size" in spec:
            override.deck_size = int(spec.get("deck_size", spec.get("size")))
        pair_value = spec.get("class_pair", spec.get("classes"))
        if pair_value is not None:
            pair = _normalize_class_pair(pair_value, candidate_factions=candidate_factions)
            override.factions_by_option_id["faction_1"] = pair[0]
            override.factions_by_option_id["faction_2"] = pair[1]
        faction_value = (
            spec.get("faction")
            or spec.get("faction_select")
            or spec.get("secondary_class")
            or spec.get("faction_selected")
        )
        if faction_value is not None:
            if faction_value not in candidate_factions:
                raise ValueError(f"invalid faction {faction_value!r}")
            if len(faction_selects) != 1:
                raise ValueError(
                    "ambiguous faction override; use faction_1/faction_2 for dual class "
                    "investigators"
                )
            override.factions_by_option_id[
                _faction_select_option_key(faction_selects[0])
            ] = str(faction_value)
        for option in faction_selects:
            option_id = _faction_select_option_key(option)
            if option_id in spec:
                faction = spec[option_id]
                if faction not in option["faction_select"]:
                    raise ValueError(f"invalid faction {faction!r} for {option_id}")
                override.factions_by_option_id[option_id] = faction
    else:
        raise TypeError(f"unsupported investigator_option type: {type(spec).__name__}")

    if override.deck_size is not None and size_choices:
        if override.deck_size not in size_choices:
            raise ValueError(
                f"invalid deck size {override.deck_size}; choices are {size_choices}"
            )
    elif override.deck_size is not None and not size_choices:
        raise ValueError("investigator has no deck_size_select option")

    if is_dual_class_select(deck_options):
        f1 = override.factions_by_option_id.get("faction_1")
        f2 = override.factions_by_option_id.get("faction_2")
        if (f1 is None) ^ (f2 is None):
            raise ValueError("dual class override requires both faction_1 and faction_2")
        if f1 and f2 and f1 == f2:
            raise ValueError(f"class pair factions must differ: {f1!r}")

    return override


def investigator_option_slug(
    *,
    override: InvestigatorOptionOverride | None = None,
    resolutions: list[DeckOptionResolution] | None = None,
) -> str | None:
    """Build a filename suffix for a specific investigator option variant."""
    parts: list[str] = []
    if override is not None:
        if override.deck_size is not None:
            parts.append(str(override.deck_size))
        if is_dual_class_select_resolved(override):
            parts.append(
                format_faction_pair(
                    override.factions_by_option_id["faction_1"],
                    override.factions_by_option_id["faction_2"],
                )
            )
        else:
            for faction in override.factions_by_option_id.values():
                if faction not in parts:
                    parts.append(faction)
    elif resolutions:
        for resolution in resolutions:
            if resolution.kind == "deck_size_select":
                parts.append(resolution.choice)
            elif resolution.kind in {"faction_select", "faction_pair"}:
                parts.append(resolution.choice)
    if not parts:
        return None
    return " ".join(parts)


def is_dual_class_select_resolved(override: InvestigatorOptionOverride) -> bool:
    return (
        "faction_1" in override.factions_by_option_id
        and "faction_2" in override.factions_by_option_id
    )


def _apply_forced_choice(
    resolution: DeckOptionResolution,
    choice: str,
) -> DeckOptionResolution:
    return DeckOptionResolution(
        kind=resolution.kind,
        option_name=resolution.option_name,
        choice=choice,
        weighted_totals=resolution.weighted_totals,
        weight_shares=resolution.weight_shares,
    )


def _unpack_weighted_deck(
    entry: WeightedTrainingDeck | tuple[dict[str, int], float],
) -> WeightedTrainingDeck:
    slots, weight = entry[0], entry[1]
    meta = entry[2] if len(entry) > 2 else None
    return slots, weight, meta


def _faction_select_criteria(option: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in option.items()
        if key not in {"faction_select", "name", "id"}
    }


def _weighted_meta_faction_pair_resolution(
    option: dict[str, Any],
    *,
    candidate_factions: list[str],
    weighted_decks: list[WeightedTrainingDeck | tuple[dict[str, int], float]],
) -> tuple[str, str, DeckOptionResolution]:
    """Resolve Charlie Kane's two classes from meta.faction_1 / faction_2 only."""
    pair_weights: Counter[str] = Counter()
    for entry in weighted_decks:
        _, deck_weight, meta = _unpack_weighted_deck(entry)
        if deck_weight <= 0:
            continue
        pair = meta_class_pair(meta)
        if pair is None:
            continue
        pair_weights[format_faction_pair(pair[0], pair[1])] += deck_weight

    all_pair_labels = [
        format_faction_pair(a, b)
        for a, b in combinations(sorted(candidate_factions), 2)
    ]
    duplicate_labels = [f"{faction}+{faction}" for faction in sorted(candidate_factions)]
    totals = {
        label: pair_weights.get(label, 0.0)
        for label in all_pair_labels + duplicate_labels
    }
    pool_total = sum(pair_weights.values())
    shares = {
        label: (totals[label] / pool_total if pool_total else 0.0) for label in totals
    }
    valid_totals = {
        label: weight
        for label, weight in totals.items()
        if label.split("+", 1)[0] != label.split("+", 1)[1]
    }
    if valid_totals:
        choice_label = max(
            valid_totals,
            key=lambda label: (valid_totals[label], label),
        )
    else:
        choice_label = all_pair_labels[0]
    f1, f2 = choice_label.split("+", 1)
    resolution = DeckOptionResolution(
        kind="faction_pair",
        option_name=option.get("name"),
        choice=choice_label,
        weighted_totals=totals,
        weight_shares=shares,
    )
    return f1, f2, resolution


def _weighted_meta_faction_selected_resolution(
    option: dict[str, Any],
    *,
    choices: list[str],
    weighted_decks: list[WeightedTrainingDeck | tuple[dict[str, int], float]],
) -> DeckOptionResolution:
    """Resolve a single faction_select from meta.faction_selected only."""
    faction_weights: Counter[str] = Counter()
    for entry in weighted_decks:
        _, deck_weight, meta = _unpack_weighted_deck(entry)
        if deck_weight <= 0:
            continue
        faction = (meta or {}).get("faction_selected")
        if faction in choices:
            faction_weights[faction] += deck_weight

    totals = {faction: faction_weights.get(faction, 0.0) for faction in choices}
    pool_total = sum(totals.values())
    shares = {
        faction: (totals[faction] / pool_total if pool_total else 0.0)
        for faction in choices
    }
    choice = max(choices, key=lambda faction: (totals[faction], faction))
    return DeckOptionResolution(
        kind="faction_select",
        option_name=option.get("name"),
        choice=choice,
        weighted_totals=totals,
        weight_shares=shares,
    )


def _weighted_faction_select_resolution(
    option: dict[str, Any],
    *,
    choices: list[str],
    primary_factions: set[str],
    weighted_decks: list[WeightedTrainingDeck | tuple[dict[str, int], float]],
    cards: dict[str, dict[str, Any]],
    xp_for_card: Any,
) -> DeckOptionResolution:
    criteria = _faction_select_criteria(option)
    text_regexes = _compile_option_text_regexes(criteria)
    faction_weights: Counter[str] = Counter()

    for entry in weighted_decks:
        slots, deck_weight, _meta = _unpack_weighted_deck(entry)
        if deck_weight <= 0:
            continue
        deck_counts: Counter[str] = Counter()
        for canonical_id, copies in slots.items():
            card = cards.get(canonical_id)
            if card is None:
                continue
            if card.get("type_code") in ("treachery", "enemy", "investigator"):
                continue
            if card.get("subtype_code") in ("basicweakness", "weakness"):
                continue
            xp = xp_for_card(card, canonical_id)
            for faction in choices:
                if faction in primary_factions or faction == "neutral":
                    continue
                test_option = {**criteria, "faction": [faction]}
                if _card_matches_option_criteria(
                    card, xp, test_option, text_regexes=text_regexes
                ):
                    deck_counts[faction] += copies
        deck_total = sum(deck_counts.values())
        if not deck_total:
            continue
        for faction, copies in deck_counts.items():
            faction_weights[faction] += deck_weight * (copies / deck_total)

    totals = {faction: faction_weights.get(faction, 0.0) for faction in choices}
    pool_total = sum(totals.values())
    shares = {
        faction: (totals[faction] / pool_total if pool_total else 0.0)
        for faction in choices
    }
    choice = max(choices, key=lambda faction: (totals[faction], faction))
    return DeckOptionResolution(
        kind="faction_select",
        option_name=option.get("name"),
        choice=choice,
        weighted_totals=totals,
        weight_shares=shares,
    )


def _weighted_deck_size_resolution(
    option: dict[str, Any],
    *,
    weighted_decks: list[WeightedTrainingDeck | tuple[dict[str, int], float]],
    cards: dict[str, dict[str, Any]],
    default_deck_size: int,
) -> tuple[int, DeckOptionResolution]:
    choices = [int(value) for value in option["deck_size_select"]]
    size_weights: Counter[int] = Counter()
    for entry in weighted_decks:
        slots, deck_weight, _meta = _unpack_weighted_deck(entry)
        if deck_weight <= 0:
            continue
        player_cards = sum(
            count
            for canonical_id, count in slots.items()
            if cards.get(canonical_id, {}).get("type_code")
            not in ("treachery", "enemy", "investigator")
        )
        if player_cards in choices:
            size_weights[player_cards] += deck_weight
    totals = {str(size): size_weights.get(size, 0.0) for size in choices}
    pool_total = sum(totals.values())
    shares = {
        key: (totals[key] / pool_total if pool_total else 0.0) for key in totals
    }
    if pool_total:
        deck_size = max(choices, key=lambda size: (size_weights[size], size))
    else:
        deck_size = default_deck_size
    resolution = DeckOptionResolution(
        kind="deck_size_select",
        option_name=option.get("name"),
        choice=str(deck_size),
        weighted_totals=totals,
        weight_shares=shares,
    )
    return deck_size, resolution


def resolve_deck_options(
    deck_options: list[dict[str, Any]],
    *,
    weighted_decks: list[WeightedTrainingDeck | tuple[dict[str, int], float]],
    cards: dict[str, dict[str, Any]],
    default_deck_size: int,
    xp_for_card: Any,
    investigator_code: str | None = None,
    investigator_option: InvestigatorOptionInput = None,
) -> tuple[list[dict[str, Any]], int, list[DeckOptionResolution]]:
    """Expand faction_select / deck_size_select using weighted training decks."""
    del investigator_code  # retained for API compatibility
    override = parse_investigator_option(investigator_option, deck_options)
    deck_size = default_deck_size
    resolved: list[dict[str, Any]] = []
    resolutions: list[DeckOptionResolution] = []
    selected_secondaries: list[str] = []
    dual_class_pair: tuple[str, str] | None = None
    dual_class_resolution: DeckOptionResolution | None = None

    if is_dual_class_select(deck_options):
        class_option = faction_select_options(deck_options)[0]
        dual_class_resolution = _weighted_meta_faction_pair_resolution(
            class_option,
            candidate_factions=list(class_option["faction_select"]),
            weighted_decks=weighted_decks,
        )[2]
        dual_class_pair = tuple(
            dual_class_resolution.choice.split("+", 1)
        )
        if override is not None and is_dual_class_select_resolved(override):
            dual_class_pair = (
                override.factions_by_option_id["faction_1"],
                override.factions_by_option_id["faction_2"],
            )
            dual_class_resolution = _apply_forced_choice(
                dual_class_resolution,
                format_faction_pair(dual_class_pair[0], dual_class_pair[1]),
            )
        resolutions.append(dual_class_resolution)

    for option in deck_options:
        if option.get("deck_size_select"):
            deck_size, resolution = _weighted_deck_size_resolution(
                option,
                weighted_decks=weighted_decks,
                cards=cards,
                default_deck_size=default_deck_size,
            )
            if override is not None and override.deck_size is not None:
                deck_size = override.deck_size
                resolution = _apply_forced_choice(resolution, str(deck_size))
            resolutions.append(resolution)
            continue

        if option.get("faction_select"):
            option_id = _faction_select_option_key(option)
            if dual_class_pair is not None:
                if option_id == "faction_1":
                    faction = dual_class_pair[0]
                elif option_id == "faction_2":
                    faction = dual_class_pair[1]
                else:
                    faction = dual_class_pair[0]
            elif override is not None and option_id in override.factions_by_option_id:
                faction = override.factions_by_option_id[option_id]
                resolution = _weighted_meta_faction_selected_resolution(
                    option,
                    choices=list(option["faction_select"]),
                    weighted_decks=weighted_decks,
                )
                resolution = _apply_forced_choice(resolution, faction)
                resolutions.append(resolution)
            else:
                choices = [
                    faction
                    for faction in option["faction_select"]
                    if faction not in selected_secondaries
                ]
                if not choices:
                    choices = list(option["faction_select"])
                resolution = _weighted_meta_faction_selected_resolution(
                    option,
                    choices=choices,
                    weighted_decks=weighted_decks,
                )
                faction = resolution.choice
                selected_secondaries.append(faction)
                resolutions.append(resolution)
            new_option = {
                key: value
                for key, value in option.items()
                if key not in {"faction_select", "name", "id"}
            }
            new_option["faction"] = [faction]
            resolved.append(new_option)
            continue

        resolved.append(dict(option))

    return resolved, deck_size, resolutions
