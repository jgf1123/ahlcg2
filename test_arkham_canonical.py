# -*- coding: utf-8 -*-
"""Tests for card_id -> canonical_id mapping."""

import pickle
import unittest
from pathlib import Path

from arkham_canonical import (
    CanonicalMapper,
    build_canonical_map,
    compare_text,
    load_canonical_mapper,
    normalize_text,
    pack_to_cycle,
    parse_investigator_front_back,
)

CARD_JSON = Path(__file__).with_name("card_json.pickle")


def _load_cards():
    with CARD_JSON.open("rb") as file:
        return pickle.load(file)


@unittest.skipUnless(CARD_JSON.exists(), "card_json.pickle not found")
class CanonicalIdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards = _load_cards()
        cls.mapper = CanonicalMapper(cls.cards, chapter=1)

    def assert_same_canonical(self, card_ids, expected):
        canonical_ids = {self.mapper.to_canonical(card_id) for card_id in card_ids}
        self.assertEqual(canonical_ids, {expected})
        for card_id in card_ids:
            self.assertEqual(self.mapper.to_canonical(card_id), expected)

    def assert_distinct_canonical(self, card_ids):
        canonical_ids = [self.mapper.to_canonical(card_id) for card_id in card_ids]
        self.assertEqual(len(canonical_ids), len(set(canonical_ids)))

    def test_physical_training_reprints(self):
        self.assert_same_canonical(["01017", "01517", "60108"], "01017")

    def test_sure_gamble_reprints(self):
        self.assert_same_canonical(["01056", "01556"], "01056")

    def test_taboo_placeholder_reprints(self):
        self.assert_same_canonical(["01095", "01595"], "01095")
        self.assert_same_canonical(["01072", "01572"], "01072")
        self.assert_same_canonical(["01094", "01594"], "01094")

    def test_upgrade_pairs_stay_separate(self):
        self.assert_distinct_canonical(["60120", "01022"])
        self.assert_distinct_canonical(["60520", "03114"])

    def test_faction_upgrade_branches(self):
        self.assert_distinct_canonical(["05186", "05187"])

    def test_tekeli_li_weaknesses(self):
        self.assert_distinct_canonical([f"0872{i}" for i in range(3, 10)])

    def test_on_your_own_permanent_exceptional(self):
        self.assert_distinct_canonical(["04236", "53010"])

    def test_agatha_parallel_backs(self):
        self.assert_distinct_canonical(["11007", "11008"])

    def test_default_agnes_canonical_front_back(self):
        self.assertEqual(
            self.mapper.canonical_front_back("01004", "01004"),
            ("01004", "01004"),
        )

    def test_agatha_canonical_front_back_distinct(self):
        self.assertEqual(
            self.mapper.canonical_front_back("11007", "11008"),
            ("11007", "11008"),
        )
        self.assertEqual(
            self.mapper.canonical_front_back("11008", "11008"),
            ("11008", "11008"),
        )

    def test_decklist_canonical_front_back_from_meta(self):
        decklist = {
            "investigator_code": "01004",
            "meta": '{"alternate_front":"01004","alternate_back":"01004"}',
        }
        self.assertEqual(
            self.mapper.decklist_canonical_front_back(decklist),
            ("01004", "01004"),
        )

    def test_canonical_cycle_is_earliest_printing(self):
        self.assertEqual(self.mapper.cycle_for("01517"), 1)
        self.assertEqual(self.mapper.cycle_for("60108"), 1)

    def test_rcore_reprint_uses_expansion_cycle(self):
        if "01694" not in self.cards or "02158" not in self.cards:
            self.skipTest("Charisma rcore/tece not in card_json.pickle")
        self.assertEqual(self.mapper.to_canonical("01694"), "02158")
        self.assertEqual(self.mapper.cycle_for("01694"), 2)
        self.assertEqual(self.mapper.cycle_for("02158"), 2)

    def test_rcore_with_core_stays_cycle_one(self):
        self.assertEqual(self.mapper.to_canonical("01017"), "01017")
        self.assertEqual(self.mapper.cycle_for("01017"), 1)

    def test_rcore_starter_without_core_uses_starter_cycle(self):
        if "01685" not in self.cards:
            self.skipTest("Seeking Answers rcore not in card_json.pickle")
        self.assertEqual(self.mapper.to_canonical("01685"), "60227")
        self.assertEqual(self.mapper.cycle_for("01685"), 7)

    def test_cycle_for_slot_unknown_card(self):
        self.assertIsNone(self.mapper.cycle_for_slot("07062"))

    def test_decklist_cycle_ignores_unknown_slots(self):
        slots = {"01017": 2, "07062": 1}
        self.assertEqual(self.mapper.decklist_cycle(slots), 1)
        self.assertTrue(self.mapper.decklist_has_unknown_slots(slots))

    def test_unordered_slots_are_known_not_unknown(self):
        rod_slots = {
            card_id
            for card_id, card in self.cards.items()
            if card.get("pack_code") == "rod"
        }
        if not rod_slots:
            self.skipTest("no parallel Roland cards in card_json.pickle")
        rod_id = sorted(rod_slots)[0]
        slots = {"01017": 1, rod_id: 1}
        self.assertTrue(self.mapper.is_known_card(rod_id))
        self.assertIsNone(self.mapper.cycle_for_slot(rod_id))
        self.assertFalse(self.mapper.decklist_has_unknown_slots(slots))

    def test_decklist_cycle_is_max_over_slots(self):
        self.assertEqual(
            self.mapper.decklist_cycle({"01017": 1, "05186": 1}),
            5,
        )

    def test_decklist_cycle_excludes_norman_signatures(self):
        if "08005" not in self.cards:
            self.skipTest("Norman signatures not in card_json.pickle")
        slots = {"01017": 25, "08005": 1, "08006": 1}
        self.assertEqual(self.mapper.decklist_cycle(slots), 9)
        self.assertEqual(
            self.mapper.decklist_cycle(slots, canonical_front="08004"),
            1,
        )

    def test_decklist_cycle_excludes_basicweakness(self):
        basic = [
            card_id
            for card_id, card in self.cards.items()
            if card.get("subtype_code") == "basicweakness"
            and (cycle := self.mapper.cycle_for_slot(card_id)) is not None
            and cycle > 1
        ]
        if not basic:
            self.skipTest("no ordered non-core basic weakness in card_json.pickle")
        weakness_id = basic[0]
        self.assertEqual(
            self.mapper.decklist_cycle({"01017": 25, weakness_id: 1}),
            1,
        )

    def test_identity_for_singletons(self):
        singletons = [
            card_id
            for card_id, card in self.cards.items()
            if card.get("duplicate_of_code") is None
        ]
        for card_id in singletons[:200]:
            fingerprint_peers = [
                other_id
                for other_id, other in self.cards.items()
                if other_id != card_id
                and other.get("name") == self.cards[card_id].get("name")
            ]
            if not fingerprint_peers:
                self.assertEqual(self.mapper.to_canonical(card_id), card_id)


class NormalizeTextTests(unittest.TestCase):
    def test_trait_brackets(self):
        self.assertEqual(
            normalize_text("Play a [[Spell]] card."),
            "Play a [Spell] card.",
        )

    def test_whitespace_and_dashes(self):
        self.assertEqual(
            normalize_text("a\nb  c − d – e"),
            "a b c - d - e",
        )

    def test_compare_text_coalesce(self):
        self.assertEqual(
            compare_text({"text": None, "real_text": ""}),
            "",
        )
        self.assertEqual(
            compare_text({"text": None, "real_text": None}),
            "",
        )
        self.assertEqual(
            compare_text({"text": "Hello", "real_text": "Ignored"}),
            "Hello",
        )


class ParseInvestigatorFrontBackTests(unittest.TestCase):
    def test_defaults_to_investigator_code(self):
        decklist = {"investigator_code": "01004"}
        self.assertEqual(parse_investigator_front_back(decklist), ("01004", "01004"))

    def test_empty_alternate_fields_fall_back(self):
        decklist = {
            "investigator_code": "01004",
            "meta": '{"alternate_front":"","alternate_back":""}',
        }
        self.assertEqual(parse_investigator_front_back(decklist), ("01004", "01004"))

    def test_parallel_front_back(self):
        decklist = {
            "investigator_code": "01004",
            "meta": '{"alternate_front":"90017","alternate_back":"90017"}',
        }
        self.assertEqual(parse_investigator_front_back(decklist), ("90017", "90017"))


class DecklistCycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapper = load_canonical_mapper()

    def test_empty_slots(self):
        self.assertIsNone(self.mapper.decklist_cycle({}))
        self.assertFalse(self.mapper.decklist_has_unknown_slots({}))


class PackCycleTests(unittest.TestCase):
    def test_return_packs_inherit_prior_cycle(self):
        self.assertEqual(pack_to_cycle("rtnotz"), 3)
        self.assertEqual(pack_to_cycle("rtdwl"), 4)
        self.assertEqual(pack_to_cycle("rtptc"), 5)
        self.assertEqual(pack_to_cycle("rttfa"), 6)
        self.assertEqual(pack_to_cycle("rttcu"), 8)

    def test_starter_decks_are_cycle_7(self):
        self.assertEqual(pack_to_cycle("nat"), 7)
        self.assertEqual(pack_to_cycle("ste"), 7)

    def test_unordered_packs_return_none(self):
        self.assertIsNone(pack_to_cycle("promo"))
        self.assertIsNone(pack_to_cycle("rod"))
        self.assertIsNone(pack_to_cycle("enc"))

    def test_unknown_pack_does_not_break_canonical_map(self):
        cards = {
            "99001": {
                "name": "New Side Story Card",
                "pack_code": "enc",
                "text": "test",
                "real_text": "test",
                "type_code": "event",
                "faction_code": "neutral",
                "exceptional": False,
                "myriad": False,
                "is_unique": False,
                "permanent": False,
                "duplicate_of_code": None,
            }
        }
        canonical_id_map, canonical_cycle = build_canonical_map(cards)
        self.assertEqual(canonical_id_map["99001"], "99001")
        self.assertIsNone(canonical_cycle["99001"])


class BuildCanonicalMapTests(unittest.TestCase):
    def test_duplicate_of_merges_despite_text_difference(self):
        cards = {
            "A": {
                "name": "Test",
                "pack_code": "core",
                "text": "version one",
                "real_text": "version one",
                "type_code": "event",
                "faction_code": "neutral",
                "exceptional": False,
                "myriad": False,
                "is_unique": False,
                "permanent": False,
                "duplicate_of_code": None,
            },
            "B": {
                "name": "Test",
                "pack_code": "rcore",
                "text": "version two",
                "real_text": "version two",
                "type_code": "event",
                "faction_code": "neutral",
                "exceptional": False,
                "myriad": False,
                "is_unique": False,
                "permanent": False,
                "duplicate_of_code": "A",
            },
        }
        canonical_id_map, _ = build_canonical_map(cards)
        self.assertEqual(canonical_id_map["A"], "A")
        self.assertEqual(canonical_id_map["B"], "A")


if __name__ == "__main__":
    unittest.main()
