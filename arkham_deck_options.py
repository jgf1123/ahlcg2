# -*- coding: utf-8 -*-
"""ArkhamDB deck_options parsing and legality for decklist generation."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

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
        return target_tag in tags.split()
    if isinstance(tags, list):
        return target_tag in tags
    return False


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


@dataclass
class DeckOptionsValidator:
    """Check card legality and option limits for an investigator."""

    deck_options: list[dict[str, Any]]
    text_regexes: dict[str, re.Pattern[str]] = field(default_factory=dict)
    option_counts: list[int] = field(default_factory=list)

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
            if xp < min_level or xp > max_level:
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
        if tags:
            if not any(card_has_tag(card, tag) for tag in tags):
                return False

        uses = option.get("uses")
        if uses:
            if not card_has_uses(card, uses):
                return False

        for pattern in _option_text_patterns(option):
            regex = self.text_regexes.get(pattern)
            text = get_card_text(card)
            if regex is not None:
                if not regex.search(text):
                    return False
            elif not re.search(f"(?i){pattern}", text):
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
        if xp < min_level or xp > max_level:
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
    if tags:
        if not any(card_has_tag(card, tag) for tag in tags):
            return False

    uses = option.get("uses")
    if uses:
        if not card_has_uses(card, uses):
            return False

    for pattern in _option_text_patterns(option):
        regex = regexes.get(pattern)
        text = get_card_text(card)
        if regex is not None:
            if not regex.search(text):
                return False
        elif not re.search(f"(?i){pattern}", text):
            return False

    return True


def _faction_select_criteria(option: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in option.items()
        if key not in {"faction_select", "name", "id"}
    }


def _weighted_faction_select_resolution(
    option: dict[str, Any],
    *,
    choices: list[str],
    primary_factions: set[str],
    weighted_decks: list[tuple[dict[str, int], float]],
    cards: dict[str, dict[str, Any]],
    xp_for_card: Any,
) -> DeckOptionResolution:
    criteria = _faction_select_criteria(option)
    text_regexes = _compile_option_text_regexes(criteria)
    faction_weights: Counter[str] = Counter()

    for slots, deck_weight in weighted_decks:
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
    weighted_decks: list[tuple[dict[str, int], float]],
    cards: dict[str, dict[str, Any]],
    default_deck_size: int,
) -> tuple[int, DeckOptionResolution]:
    choices = [int(value) for value in option["deck_size_select"]]
    size_weights: Counter[int] = Counter()
    for slots, deck_weight in weighted_decks:
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
    weighted_decks: list[tuple[dict[str, int], float]],
    cards: dict[str, dict[str, Any]],
    default_deck_size: int,
    xp_for_card: Any,
) -> tuple[list[dict[str, Any]], int, list[DeckOptionResolution]]:
    """Expand faction_select / deck_size_select using weighted training decks."""
    deck_size = default_deck_size
    resolved: list[dict[str, Any]] = []
    resolutions: list[DeckOptionResolution] = []
    primary_factions = primary_factions_from_options(deck_options)
    selected_secondaries: list[str] = []

    for option in deck_options:
        if option.get("deck_size_select"):
            deck_size, resolution = _weighted_deck_size_resolution(
                option,
                weighted_decks=weighted_decks,
                cards=cards,
                default_deck_size=default_deck_size,
            )
            resolutions.append(resolution)
            continue

        if option.get("faction_select"):
            choices = [
                faction
                for faction in option["faction_select"]
                if faction not in selected_secondaries
            ]
            if not choices:
                choices = list(option["faction_select"])
            resolution = _weighted_faction_select_resolution(
                option,
                choices=choices,
                primary_factions=primary_factions,
                weighted_decks=weighted_decks,
                cards=cards,
                xp_for_card=xp_for_card,
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
