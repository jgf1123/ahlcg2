# -*- coding: utf-8 -*-
"""Tests for scrape_arkhamdb.py (no network)."""

import unittest

from scrape_arkhamdb import (
    card_ids_needed,
    decklist_ids_to_fetch,
    patch_myriad_flags,
)


class ScrapeArkhamdbTests(unittest.TestCase):
    def test_incremental_only_new_ids(self):
        decklists = {100: {"slots": {}}, 102: {"slots": {}}}
        ids = decklist_ids_to_fetch(
            decklists,
            max_id=105,
            min_id=0,
            mode="incremental",
            rescrape_empty=False,
            verify_present=False,
        )
        self.assertEqual(ids, [103, 104, 105])

    def test_gaps_rescrape_empty(self):
        decklists = {10: None, 11: {"slots": {}}}
        ids = decklist_ids_to_fetch(
            decklists,
            max_id=12,
            min_id=10,
            mode="gaps",
            rescrape_empty=True,
            verify_present=False,
        )
        self.assertEqual(ids, [12, 10])

    def test_card_ids_needed(self):
        decklists = {
            1: {"slots": {"01001": 2, "01002": 1}, "investigator_code": "01001"},
            2: None,
        }
        cards = {"01001": {}}
        self.assertEqual(card_ids_needed(decklists, cards), ["01002"])

    def test_patch_myriad(self):
        cards = {
            "x": {"text": "Myriad. Limit 3.", "myriad": False},
            "y": {"text": "Normal", "myriad": False},
        }
        self.assertEqual(patch_myriad_flags(cards), 1)
        self.assertTrue(cards["x"]["myriad"])


if __name__ == "__main__":
    unittest.main()
