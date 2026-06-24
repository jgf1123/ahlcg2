# -*- coding: utf-8 -*-
"""Scrape ArkhamDB public decklists and cards into pickle files.

Only this module (and manual one-offs) should overwrite card_json.pickle /
decklist_json.pickle. Popularity code must not.

Decklist empty responses (HTTP 200, zero-length body) may mean deleted OR
made private; the API does not distinguish. We store None to mark "fetched,
no public data" unless --no-store-empty is set.

ponytail: fixed ~4s delay between requests; upgrade: lower --delay if API
rate limits allow.
"""

from __future__ import annotations

import argparse
import json
import pickle
import random
import sys
import time
from pathlib import Path
from typing import Any

import requests

from arkham_canonical import parse_investigator_front_back

BASE_URL = "https://arkhamdb.com"
DECKLIST_PICKLE = Path("decklist_json.pickle")
CARD_PICKLE = Path("card_json.pickle")
DEFAULT_MIN_DECKLIST_ID = 15614  # Circle Undone on arkhamdb; older ids are sparse
# Bogus slot codes in scraped decklists; no public ArkhamDB card page exists.
SKIP_CARD_IDS = frozenset({"07062"})


def load_pickle(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return pickle.load(f)


def save_pickle(path: Path, data: dict) -> None:
    with path.open("wb") as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)


def request_delay(seconds: float) -> None:
    if seconds <= 0:
        return
    # ponytail: gauss jitter like legacy scrapers
    time.sleep(max(1.0, random.gauss(seconds, seconds / 6)))


def fetch_decklist(
    session: requests.Session, decklist_id: int
) -> tuple[str, dict[str, Any] | None]:
    """Return ('ok', deck), ('empty', None), or ('error', None)."""
    url = f"{BASE_URL}/api/public/decklist/{decklist_id}.json"
    try:
        response = session.get(url, timeout=60)
    except requests.RequestException as exc:
        print(f"decklist {decklist_id} error: {exc}", file=sys.stderr)
        return "error", None
    if response.status_code != 200:
        print(f"decklist {decklist_id} HTTP {response.status_code}", file=sys.stderr)
        return "error", None
    if not response.text.strip():
        return "empty", None
    return "ok", response.json()


def fetch_card(session: requests.Session, card_id: str) -> dict[str, Any] | None:
    url = f"{BASE_URL}/api/public/card/{card_id}.json"
    try:
        response = session.get(url, timeout=60)
    except requests.RequestException as exc:
        print(f"card {card_id} error: {exc}", file=sys.stderr)
        return None
    if response.status_code != 200 or not response.text.strip():
        print(f"card {card_id} HTTP {response.status_code}", file=sys.stderr)
        return None
    return response.json()


def discover_max_decklist_id(
    session: requests.Session,
    *,
    start: int,
    probe_limit: int = 5000,
) -> int:
    """Binary-search highest decklist_id with non-empty public JSON."""
    lo, hi = start, start + probe_limit
    while fetch_decklist(session, hi)[0] == "ok":
        lo = hi
        hi += probe_limit
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fetch_decklist(session, mid)[0] == "ok":
            lo = mid
        else:
            hi = mid - 1
        request_delay(1.0)
    return lo


def decklist_ids_to_fetch(
    decklists: dict[Any, Any],
    *,
    max_id: int,
    min_id: int,
    mode: str,
    rescrape_empty: bool,
    verify_present: bool,
) -> list[int]:
    ids: list[int] = []
    if mode == "incremental":
        floor = max((int(k) for k, v in decklists.items() if v), default=0)
        for decklist_id in range(floor + 1, max_id + 1):
            if decklist_id not in decklists:
                ids.append(decklist_id)
    elif mode == "gaps":
        for decklist_id in range(max_id, min_id - 1, -1):
            if decklist_id not in decklists:
                ids.append(decklist_id)
            elif rescrape_empty and decklists[decklist_id] is None:
                ids.append(decklist_id)
    else:
        raise ValueError(f"unknown mode: {mode}")

    if verify_present:
        for decklist_id, deck in sorted(decklists.items(), key=lambda x: int(x[0])):
            if deck:
                ids.append(int(decklist_id))
    return ids


def scrape_decklists(args: argparse.Namespace) -> None:
    decklists = load_pickle(args.decklist_pickle)
    session = requests.Session()

    max_id = args.max_id
    if max_id is None:
        start = max((int(k) for k in decklists if decklists[k]), default=1)
        print(f"Discovering max public decklist_id from {start}...")
        max_id = discover_max_decklist_id(session, start=start)
        print(f"max public decklist_id ≈ {max_id}")

    ids = decklist_ids_to_fetch(
        decklists,
        max_id=max_id,
        min_id=args.min_id,
        mode=args.mode,
        rescrape_empty=args.rescrape_empty,
        verify_present=args.verify_present,
    )
    print(f"Fetching {len(ids)} decklist(s) (mode={args.mode})...")

    stats = {"ok": 0, "empty": 0, "error": 0, "now_empty": 0}
    for decklist_id in ids:
        status, deck = fetch_decklist(session, decklist_id)
        if status == "ok":
            decklists[decklist_id] = deck
            stats["ok"] += 1
            print(decklist_id)
        elif status == "empty":
            stats["empty"] += 1
            if args.verify_present and decklists.get(decklist_id):
                stats["now_empty"] += 1
                print(f"{decklist_id} now empty (was public)")
            else:
                print(f"{decklist_id} empty")
            if args.store_empty:
                decklists[decklist_id] = None
            elif decklist_id in decklists and decklists[decklist_id] is None:
                pass
            elif args.verify_present and decklists.get(decklist_id):
                decklists[decklist_id] = None
        else:
            stats["error"] += 1
        save_pickle(args.decklist_pickle, decklists)
        request_delay(args.delay)

    print(
        f"Done: {stats['ok']} ok, {stats['empty']} empty, "
        f"{stats['error']} errors, {stats['now_empty']} privatized/deleted"
    )


def card_ids_needed(decklists: dict[Any, Any], cards: dict[str, Any]) -> list[str]:
    needed: set[str] = set()
    for deck in decklists.values():
        if not deck:
            continue
        needed.update(deck.get("slots") or {})
        inv_front, inv_back = parse_investigator_front_back(deck)
        needed.add(inv_front)
        needed.add(inv_back)
    return sorted(
        cid
        for cid in needed
        if cid not in cards and cid not in SKIP_CARD_IDS
    )


def patch_myriad_flags(cards: dict[str, Any]) -> int:
    patched = 0
    for card in cards.values():
        text = card.get("text") or ""
        if "Myriad" in text and not card.get("myriad"):
            card["myriad"] = True
            patched += 1
    return patched


def scrape_cards(args: argparse.Namespace) -> None:
    decklists = load_pickle(args.decklist_pickle)
    cards = load_pickle(args.card_pickle)
    session = requests.Session()

    if args.refresh_all:
        card_ids = card_ids_needed(decklists, {})
    else:
        card_ids = card_ids_needed(decklists, cards)

    print(f"Fetching {len(card_ids)} card(s)...")
    for card_id in card_ids:
        card = fetch_card(session, card_id)
        if card is not None:
            cards[card_id] = card
            print(card_id)
        save_pickle(args.card_pickle, cards)
        request_delay(args.delay)

    patched = patch_myriad_flags(cards)
    if patched:
        save_pickle(args.card_pickle, cards)
        print(f"Patched myriad flag on {patched} card(s)")
    print("Done.")


def cmd_discover_max(args: argparse.Namespace) -> None:
    decklists = load_pickle(args.decklist_pickle)
    session = requests.Session()
    start = args.start or max((int(k) for k in decklists if decklists[k]), default=1)
    max_id = discover_max_decklist_id(session, start=start)
    print(max_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape ArkhamDB into pickle files.")
    parser.add_argument(
        "--decklist-pickle", type=Path, default=DECKLIST_PICKLE
    )
    parser.add_argument("--card-pickle", type=Path, default=CARD_PICKLE)
    parser.add_argument(
        "--delay",
        type=float,
        default=4.0,
        help="Mean seconds between API requests (default 4).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    deck = sub.add_parser("decklists", help="Scrape public decklists.")
    deck.add_argument(
        "--max-id",
        type=int,
        default=None,
        help="Highest decklist_id to consider (default: auto-discover).",
    )
    deck.add_argument(
        "--min-id",
        type=int,
        default=DEFAULT_MIN_DECKLIST_ID,
        help=f"Lowest id for --mode gaps (default {DEFAULT_MIN_DECKLIST_ID}).",
    )
    deck.add_argument(
        "--mode",
        choices=("incremental", "gaps"),
        default="gaps",
        help="incremental: ids above pickle max only; gaps: fill missing down to min-id.",
    )
    deck.add_argument(
        "--rescrape-empty",
        action="store_true",
        help="With --mode gaps, retry ids stored as None.",
    )
    deck.add_argument(
        "--verify",
        dest="verify_present",
        action="store_true",
        help="Re-fetch decklists already in pickle; mark now-empty as None.",
    )
    deck.add_argument(
        "--store-empty",
        action="store_true",
        default=True,
        help="Store empty API responses as None (default: on).",
    )
    deck.add_argument(
        "--no-store-empty",
        dest="store_empty",
        action="store_false",
        help="Do not record empty responses (will re-fetch next run).",
    )
    deck.set_defaults(func=scrape_decklists)

    cards = sub.add_parser("cards", help="Scrape cards referenced by decklists.")
    cards.add_argument(
        "--refresh-all",
        action="store_true",
        help="Re-fetch every card_id in decklists (full card refresh).",
    )
    cards.set_defaults(func=scrape_cards)

    discover = sub.add_parser(
        "discover-max", help="Print highest public decklist_id."
    )
    discover.add_argument("--start", type=int, default=None)
    discover.set_defaults(func=cmd_discover_max)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
