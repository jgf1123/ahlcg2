# -*- coding: utf-8 -*-
"""Tests for arkham_popularity.py."""

import json
import pickle
import unittest
from pathlib import Path

from arkham_canonical import CanonicalMapper, build_canonical_map
from arkham_popularity import (
    ArkhamPopularityEngine,
    InvCycleIndex,
    UpgradeGraph,
    baseline_composition,
    build_canonical_card_infos,
    enforce_monotonic_cycle_weights,
    parse_customizable,
    tilt_factor,
)

CARD_JSON = Path(__file__).with_name("card_json.pickle")
TABOO_JSON = Path(__file__).with_name("taboo.json")


def _card(
    code: str,
    *,
    name: str = "Test Card",
    xp: int = 0,
    pack_code: str = "core",
    **extra,
) -> dict:
    return {
        "code": code,
        "name": name,
        "xp": xp,
        "pack_code": pack_code,
        "type_code": "asset",
        "faction_code": "neutral",
        "exceptional": False,
        "myriad": False,
        "is_unique": False,
        "permanent": False,
        "text": name,
        "real_text": name,
        **extra,
    }


class BiasCompensationTests(unittest.TestCase):
    def test_baseline_composition_sums_to_one(self):
        for deck_cycle in range(1, 13):
            total = sum(
                baseline_composition(deck_cycle, k) for k in range(1, deck_cycle + 1)
            )
            self.assertAlmostEqual(total, 1.0)

    def test_baseline_cycle_ten_core(self):
        self.assertAlmostEqual(baseline_composition(10, 1), (0.076 + 0.22) / 0.98)

    def test_baseline_cycle_ten_novelty_slot(self):
        # Structural only: cycle C gets uniform share, no novelty bump.
        self.assertAlmostEqual(baseline_composition(10, 10), 0.076 / 0.98)

    def test_tilt_downweights_core_heavy_deck(self):
        shares = {1: 0.5, 2: 0.5}
        self.assertLess(tilt_factor(10, 1, shares), 1.0)
        self.assertEqual(tilt_factor(10, 1, {1: 0.1, 2: 0.9}), 1.0)

    def test_tilt_none_for_unordered_cards(self):
        self.assertEqual(tilt_factor(5, None, {1: 1.0}), 1.0)

    def test_inv_cycle_adjust_only_on_diagonal(self):
        index = InvCycleIndex.__new__(InvCycleIndex)
        index._prob = {(10, 1): 0.07, (10, 10): 0.35}
        self.assertEqual(index.adjust(10, 1), 1.0)
        self.assertAlmostEqual(index.adjust(10, 10), min(1.0, 0.1 / 0.35))

    def test_inv_cycle_adjust_caps_at_one(self):
        index = InvCycleIndex.__new__(InvCycleIndex)
        index._prob = {(10, 10): 0.05}
        self.assertEqual(index.adjust(10, 10), 1.0)
        index._prob = {(10, 10): 0.5}
        self.assertAlmostEqual(index.adjust(10, 10), 0.2)

    def test_bias_off_matches_legacy_pooling(self):
        cards = {
            "01004": _card("01004", name="Agnes", type_code="investigator", faction_code="mystic"),
            "01017": _card("01017", name="Physical Training"),
            "01023": _card("01023", name="Dodge"),
        }
        decklists = {
            1: {"id": 1, "user_id": 1, "investigator_code": "01004", "investigator_name": "Agnes",
                "slots": {"01017": 2}},
            2: {"id": 2, "user_id": 2, "investigator_code": "01004", "investigator_name": "Agnes",
                "slots": {"01023": 2}},
        }
        mapper = CanonicalMapper(cards, chapter=1)
        taboo = [{"id": 1, "cards": "[]"}]
        on = ArkhamPopularityEngine(cards, mapper, taboo, bias_compensation=True)
        off = ArkhamPopularityEngine(cards, mapper, taboo, bias_compensation=False)
        prepared = on.prepare_all(decklists)
        row_on = on.popularity_for_investigator(prepared, "01004", "01004")
        row_off = off.popularity_for_investigator(prepared, "01004", "01004")
        pt_on = next(r for r in row_on if r["canonical_id"] == "01017" and r["card_index"] == 1)
        pt_off = next(r for r in row_off if r["canonical_id"] == "01017" and r["card_index"] == 1)
        self.assertAlmostEqual(pt_off["p5_popularity"], 0.5)
        self.assertAlmostEqual(pt_on["p5_popularity"], 0.5)


class CycleWeightTests(unittest.TestCase):
    def test_enforce_monotonic_cycle_weights(self):
        raw = {1: 0.001, 2: 0.0005, 3: 0.0008, 4: 0.0007}
        result = enforce_monotonic_cycle_weights(raw)
        self.assertEqual(result[1], min(raw.values()))
        self.assertEqual(result[2], min(raw[2], raw[3], raw[4]))
        self.assertEqual(result[3], min(raw[3], raw[4]))
        self.assertEqual(result[4], raw[4])
        cycles = sorted(result)
        for left, right in zip(cycles, cycles[1:]):
            self.assertLessEqual(result[left], result[right])


class ParseCustomizableTests(unittest.TestCase):
    def test_parse_indices_and_xp(self):
        indices, xp_list = parse_customizable("0|1,3|1,6|5,1|1,4|2")
        self.assertEqual(indices, ["0", "3", "6", "1", "4"])
        self.assertEqual(xp_list, [1, 1, 5, 1, 2])


class UpgradeGraphTests(unittest.TestCase):
    def test_linear_upgrades(self):
        from arkham_popularity import CanonicalCardInfo

        cards = {
            "A": CanonicalCardInfo("A", "Family", 1, 0, False, frozenset({0}), False, None, None),
            "A2": CanonicalCardInfo("A2", "Family", 1, 2, True, frozenset({0}), False, None, None),
            "A3": CanonicalCardInfo("A3", "Family", 1, 3, True, frozenset({0}), False, None, None),
        }
        graph = UpgradeGraph(cards)
        self.assertEqual(graph.upgrades_of("A"), frozenset({"A", "A2", "A3"}))
        self.assertEqual(graph.upgrades_of("A2"), frozenset({"A2", "A3"}))
        self.assertEqual(graph.count_option_in_slots({"A3": 1, "A2": 1}, "A"), 2)

    def test_sibling_branches_do_not_upgrade_each_other(self):
        from arkham_popularity import CanonicalCardInfo

        cards = {
            "A00": CanonicalCardInfo("A00", "Branch", 1, 0, False, frozenset({0}), False, None, None),
            "A01": CanonicalCardInfo("A01", "Branch", 1, 0, False, frozenset({0}), False, None, None),
            "A20": CanonicalCardInfo("A20", "Branch", 1, 2, True, frozenset({0}), False, None, None),
            "A21": CanonicalCardInfo("A21", "Branch", 1, 2, True, frozenset({0}), False, None, None),
        }
        graph = UpgradeGraph(cards)
        self.assertEqual(graph.upgrades_of("A00"), frozenset({"A00", "A20", "A21"}))
        self.assertEqual(graph.upgrades_of("A20"), frozenset({"A20"}))
        self.assertEqual(graph.count_option_in_slots({"A20": 1, "A21": 1}, "A00"), 2)
        self.assertEqual(graph.count_option_in_slots({"A20": 1, "A21": 1}, "A20"), 1)


class ArkhamPopularityEngineTests(unittest.TestCase):
    def _engine(self, cards: dict, decklists: dict, taboo=None):
        mapper = CanonicalMapper(cards, chapter=1)
        taboo_json = taboo or [{"id": 1, "cards": "[]"}]
        return ArkhamPopularityEngine(cards, mapper, taboo_json)

    def test_prepare_marks_unknown_slots(self):
        cards = {"01017": _card("01017", name="Physical Training")}
        engine = self._engine(
            cards,
            {1: {"id": 1, "user_id": 1, "investigator_code": "01004", "investigator_name": "Agnes",
                 "slots": {"01017": 1, "07062": 1}}},
        )
        prepared = engine.prepare_all({1: {"id": 1, "user_id": 1, "investigator_code": "01004",
                                           "investigator_name": "Agnes", "slots": {"01017": 1, "07062": 1}}})
        self.assertTrue(prepared[0].has_unknown_slots)
        self.assertTrue(prepared[0].is_ignore)

    def test_user_weight_splits_by_investigator_tuple(self):
        cards = {
            "01004": _card("01004", name="Agnes", type_code="investigator", faction_code="mystic"),
            "01017": _card("01017", name="Physical Training"),
        }
        decklists = {
            1: {"id": 1, "user_id": 9, "investigator_code": "01004", "investigator_name": "Agnes",
                "slots": {"01017": 1}},
            2: {"id": 2, "user_id": 9, "investigator_code": "01004", "investigator_name": "Agnes",
                "slots": {"01017": 2}},
        }
        engine = self._engine(cards, decklists)
        prepared = engine.prepare_all(decklists)
        weights = engine.assign_user_weights(prepared)
        self.assertAlmostEqual(weights[1], 0.5)
        self.assertAlmostEqual(weights[2], 0.5)

    def test_unordered_card_includes_all_cycle_decklists(self):
        cards = {
            "01004": _card("01004", name="Agnes", type_code="investigator", faction_code="mystic"),
            "01017": _card("01017", name="Physical Training"),
            "98001": _card("98001", name="Promo Only", pack_code="promo"),
        }
        decklists = {
            1: {"id": 1, "user_id": 1, "investigator_code": "01004", "investigator_name": "Agnes",
                "slots": {"01017": 1}},
            2: {"id": 2, "user_id": 2, "investigator_code": "01004", "investigator_name": "Agnes",
                "slots": {"98001": 1, "01017": 1}},
        }
        engine = self._engine(cards, decklists)
        prepared = engine.prepare_all(decklists)
        rows = engine.popularity_for_investigator(prepared, "01004", "01004")
        promo = next(row for row in rows if row["canonical_id"] == "98001")
        self.assertAlmostEqual(promo["p3_opportunity_weight"], 1.0)
        self.assertAlmostEqual(promo["p4_choice_weight"], 0.5)
        self.assertAlmostEqual(promo["p5_popularity"], 0.5)
        self.assertFalse(prepared[1].has_unknown_slots)
        self.assertIsNone(engine.canonical_cards["98001"].cycle)

    def test_popularity_ratio(self):
        cards = {
            "01004": _card("01004", name="Agnes", type_code="investigator", faction_code="mystic"),
            "01017": _card("01017", name="Physical Training"),
            "01023": _card("01023", name="Dodge"),
        }
        decklists = {
            1: {"id": 1, "user_id": 1, "investigator_code": "01004", "investigator_name": "Agnes",
                "slots": {"01017": 2}},
            2: {"id": 2, "user_id": 2, "investigator_code": "01004", "investigator_name": "Agnes",
                "slots": {"01023": 2}},
        }
        engine = self._engine(cards, decklists)
        prepared = engine.prepare_all(decklists)
        rows = engine.popularity_for_investigator(prepared, "01004", "01004")
        pt = next(row for row in rows if row["canonical_id"] == "01017" and row["card_index"] == 1)
        self.assertAlmostEqual(pt["p5_popularity"], 0.5)
        self.assertAlmostEqual(pt["p3_opportunity_weight"], 1.0)
        self.assertAlmostEqual(pt["p4_choice_weight"], 0.5)


@unittest.skipUnless(CARD_JSON.exists() and TABOO_JSON.exists(), "data files missing")
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CARD_JSON.open("rb") as file:
            cls.cards = pickle.load(file)
        with TABOO_JSON.open(encoding="utf-8") as file:
            cls.taboo_json = json.load(file)
        cls.mapper = CanonicalMapper(cls.cards, chapter=1)
        cls.engine = ArkhamPopularityEngine(cls.cards, cls.mapper, cls.taboo_json)

    def test_canonical_cards_built(self):
        self.assertGreater(len(self.engine.canonical_cards), 1000)

    def test_physical_training_upgrade_family(self):
        upgrades = self.engine.upgrades.upgrades_of("01017")
        self.assertIn("01017", upgrades)
        self.assertNotIn("60120", upgrades)

    def test_evidence_stays_separate_from_physical_training(self):
        pt = self.engine.upgrades.upgrades_of("01017")
        ev = self.engine.upgrades.upgrades_of("01022")
        self.assertNotEqual(pt, ev)


if __name__ == "__main__":
    unittest.main()
