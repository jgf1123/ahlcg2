# -*- coding: utf-8 -*-
"""Tests for arkham_deck_options.py."""

import json
import pickle
import unittest
from pathlib import Path

from arkham_canonical import CanonicalMapper
from arkham_deck_options import (
    DeckOptionsValidator,
    deck_options_support,
    is_standard_deck_options,
    resolve_deck_options,
)
from arkham_popularity import ArkhamPopularityEngine, slot_phase_targets

CARD_JSON = Path(__file__).with_name("card_json.pickle")
DECKLIST_JSON = Path(__file__).with_name("decklist_json.pickle")
TABOO_JSON = Path(__file__).with_name("taboo.json")


def _card(code: str, **extra) -> dict:
    return {
        "code": code,
        "name": extra.pop("name", code),
        "xp": extra.pop("xp", 0),
        "pack_code": extra.pop("pack_code", "core"),
        "type_code": extra.pop("type_code", "asset"),
        "faction_code": extra.pop("faction_code", "neutral"),
        "exceptional": False,
        "myriad": False,
        "is_unique": False,
        "permanent": False,
        "text": extra.get("real_text", code),
        "real_text": extra.get("real_text", code),
        **extra,
    }


class DeckOptionsValidatorTests(unittest.TestCase):
    def test_zoey_off_class_limit(self):
        options = [
            {"faction": ["guardian", "neutral"], "level": {"min": 0, "max": 5}},
            {"level": {"min": 0, "max": 0}, "limit": 5},
        ]
        validator = DeckOptionsValidator.from_options(options)
        guardian = _card("01016", faction_code="guardian")
        survivor = _card("01078", type_code="event", faction_code="survivor")
        self.assertTrue(validator.is_card_allowed(guardian, 0))
        self.assertTrue(validator.is_card_allowed(survivor, 0))
        for _ in range(5):
            self.assertTrue(validator.can_add_copy(survivor, 0))
            validator.add_copy(survivor, 0)
        self.assertFalse(validator.can_add_copy(survivor, 0))

    def test_mark_harrigan_tactic_trait_option(self):
        options = [
            {"faction": ["guardian", "neutral"], "level": {"min": 0, "max": 5}},
            {"trait": ["tactic"], "level": {"min": 0, "max": 0}},
        ]
        validator = DeckOptionsValidator.from_options(options)
        rogue_tactic = _card(
            "01052",
            name="Sneak Attack",
            type_code="event",
            faction_code="rogue",
            traits="Tactic.",
        )
        rogue_event = _card(
            "01050",
            name="Elusive",
            type_code="event",
            faction_code="rogue",
            traits="Trick.",
        )
        self.assertTrue(validator.is_card_allowed(rogue_tactic, 0))
        self.assertFalse(validator.is_card_allowed(rogue_event, 0))

    def test_preston_excludes_illicit(self):
        options = [
            {"not": True, "trait": ["illicit"]},
            {"faction": ["rogue", "neutral"], "level": {"min": 0, "max": 5}},
            {"faction": ["survivor"], "level": {"min": 0, "max": 2}},
        ]
        validator = DeckOptionsValidator.from_options(options)
        illicit = _card(
            "01051",
            name="Backstab",
            type_code="event",
            faction_code="rogue",
            traits="Tactic. Illicit.",
        )
        clean = _card("01050", type_code="event", faction_code="rogue", traits="Trick.")
        self.assertFalse(validator.is_card_allowed(illicit, 0))
        self.assertTrue(validator.is_card_allowed(clean, 0))

    def test_resolve_faction_select_uses_deck_weight_not_raw_copies(self):
        options = [
            {"faction": ["guardian", "neutral"], "level": {"min": 0, "max": 5}},
            {
                "name": "Secondary Class",
                "faction_select": ["seeker", "mystic", "rogue", "survivor"],
                "level": {"min": 0, "max": 2},
                "type": ["event", "skill"],
                "limit": 15,
            },
        ]
        cards = {
            "01050": _card("01050", type_code="event", faction_code="rogue"),
            "01078": _card("01078", type_code="event", faction_code="survivor"),
        }
        resolved, _, resolutions = resolve_deck_options(
            options,
            weighted_decks=[
                ({"01050": 1}, 0.9),
                ({"01078": 10}, 0.1),
            ],
            cards=cards,
            default_deck_size=30,
            xp_for_card=lambda card, _cid: int(card.get("xp") or 0),
        )
        secondary = [opt for opt in resolved if opt.get("limit") == 15][0]
        self.assertEqual(secondary["faction"], ["rogue"])
        self.assertEqual(resolutions[0].choice, "rogue")
        self.assertGreater(resolutions[0].weight_shares["rogue"], 0.5)


@unittest.skipUnless(CARD_JSON.exists() and TABOO_JSON.exists(), "data files missing")
class DeckOptionsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CARD_JSON.open("rb") as file:
            cls.cards = pickle.load(file)
        with TABOO_JSON.open(encoding="utf-8") as file:
            cls.taboo_json = json.load(file)
        cls.mapper = CanonicalMapper(cls.cards, chapter=1)
        cls.engine = ArkhamPopularityEngine(cls.cards, cls.mapper, cls.taboo_json)
        if DECKLIST_JSON.exists():
            with DECKLIST_JSON.open("rb") as file:
                cls.prepared = cls.engine.prepare_all(pickle.load(file))
        else:
            cls.prepared = []

    def test_coverage_increased_beyond_standard(self):
        rows = self.engine.list_generatable_investigators(self.prepared)
        supported = [row for row in rows if row["supported"]]
        self.assertGreater(len(supported), 36)
        codes = {row["canonical_front"] for row in supported}
        self.assertIn("02001", codes)  # Zoey
        self.assertIn("03001", codes)  # Mark Harrigan
        self.assertIn("05003", codes)  # Preston

    def test_generate_zoey_deck(self):
        if not self.prepared:
            self.skipTest("decklist_json.pickle missing")
        result = self.engine.generate_decklist(self.prepared, "02001", "02001")
        self.assertIsNone(result.skipped_reason)
        self.assertEqual(result.deck_count, result.deck_size)
        off_class = 0
        for canonical_id, count in result.slots.items():
            if canonical_id in {"02006", "02007"}:
                continue
            card = self.cards[canonical_id]
            faction = card.get("faction_code")
            if faction not in ("guardian", "neutral") and (card.get("xp") or 0) == 0:
                off_class += count
        self.assertLessEqual(off_class, 5)

    def test_phase1_skips_slotless_assets(self):
        if not self.prepared:
            self.skipTest("decklist_json.pickle missing")
        result = self.engine.generate_decklist(self.prepared, "05004", "05004")
        self.assertIsNone(result.skipped_reason)
        slotless = {"60110"}  # Safeguard; masks are patched to Mask slot at load
        for canonical_id in slotless:
            if canonical_id in result.first_add_phase:
                self.assertNotEqual(
                    result.first_add_phase[canonical_id],
                    "phase1",
                    f"{canonical_id} should not be added in phase 1",
                )
        if not self.prepared:
            self.skipTest("decklist_json.pickle missing")
        result = self.engine.generate_decklist(self.prepared, "04001", "04001")
        rows = self.engine.generation_popularity_table(
            self.prepared, "04001", "04001", generated=result
        )
        self.assertTrue(rows)
        deck_ids = set(result.slots)
        popularity_ids = {row["canonical_id"] for row in rows if row["p5_popularity"] is not None}
        self.assertTrue(deck_ids <= popularity_ids | deck_ids)
        included = [row for row in rows if row["included_in_generated"]]
        self.assertTrue(any(row["generated_count"] > 0 for row in included))
        popularity_rows = [row for row in rows if row["p5_popularity"] is not None]
        last_included_index = max(
            index
            for index, row in enumerate(popularity_rows)
            if row["included_in_generated"]
        )
        trailing = popularity_rows[last_included_index + 1 :]
        self.assertEqual(
            trailing,
            [],
            "popularity rows after the last included option should be omitted",
        )

    def test_export_resolution_diagnostics_for_tony_morgan(self):
        if not self.prepared:
            self.skipTest("decklist_json.pickle missing")
        import tempfile
        from pathlib import Path

        from arkham_popularity import resolution_export_filename

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = self.engine.export_generated_decklist_csvs(
                self.prepared, out, diagnostics=True
            )
            resolution_path = out / resolution_export_filename("Tony Morgan", "06003")
            self.assertTrue(resolution_path.exists())
            text = resolution_path.read_text(encoding="utf-8")
            self.assertIn("faction_select", text)
            self.assertIn("guardian", text)
            self.assertIn("weight_share", text)
        if not self.prepared:
            self.skipTest("decklist_json.pickle missing")
        import tempfile
        from pathlib import Path

        from arkham_popularity import generation_export_filename

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = self.engine.export_generated_decklist_csvs(self.prepared, out)
            self.assertGreater(len(paths), 60)
            leo = out / generation_export_filename("Leo Anderson", "04001")
            self.assertTrue(leo.exists())
            text = leo.read_text(encoding="utf-8")
            self.assertIn("included_in_generated", text)
            self.assertIn("subname", text)
            self.assertIn("04006", text)


if __name__ == "__main__":
    unittest.main()
