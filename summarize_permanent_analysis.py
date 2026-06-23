# -*- coding: utf-8 -*-
"""Quick summary of permanent_slot_analysis.csv."""
import csv
from collections import defaultdict
from pathlib import Path

SLOT_IDS = {"01694", "60232", "10132", "53010", "01695"}
DECK_IDS = {"07303", "08031", "09077", "08046", "06167"}


def perm_name(rows, pid):
    for r in rows:
        if r["permanent_id"] == pid:
            return r["permanent_name"]
    return pid


def summarize(rows, permanent_ids, kind_label):
    sub = [r for r in rows if r["permanent_id"] in permanent_ids]
    relevant = [r for r in sub if r["generation_relevant"] == "True"]
    by_perm = defaultdict(list)
    for r in relevant:
        by_perm[r["permanent_id"]].append(r)

    print(f"=== {kind_label} ===")
    print(f"Total comparisons: {len(sub)}, generation-relevant: {len(relevant)}")
    for pid in sorted(permanent_ids):
        ns = by_perm.get(pid, [])
        print(f"  {pid} {perm_name(rows, pid)}: {len(ns)} generation-relevant")
        for r in sorted(
            ns, key=lambda x: -abs(float(x["weighted_avg_diff"] or 0))
        )[:10]:
            line = (
                f"    {r['investigator_name']} {r['slot_type']}: "
                f"E {float(r['weighted_avg_with']):.2f} ({r['phase_targets_with']}) vs "
                f"{float(r['weighted_avg_without']):.2f} ({r['phase_targets_without']}) "
                f"n={r['n_with']}"
            )
            print(line.encode("ascii", errors="replace").decode("ascii"))
    inv_counts = defaultdict(set)
    for r in relevant:
        inv_counts[r["permanent_id"]].add(r["canonical_front"])
    print("  Investigators with >=1 generation-relevant slot:")
    for pid in sorted(permanent_ids):
        print(f"    {pid}: {len(inv_counts[pid])}")
    print()


def main():
    path = Path("permanent_slot_analysis.csv")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    summarize(rows, SLOT_IDS, "SLOT PERMANENTS")
    summarize(rows, DECK_IDS, "DECK-SIZE PERMANENTS")

    print("=== SLOT PERMANENT RATE ===")
    for pid in sorted(SLOT_IDS):
        sub = [r for r in rows if r["permanent_id"] == pid]
        rel = [r for r in sub if r["generation_relevant"] == "True"]
        with_n = [r for r in sub if int(r["n_with"]) >= 5]
        pct = 100 * len(rel) / max(len(sub), 1)
        print(
            f"{pid} {perm_name(rows, pid)}: "
            f"{len(rel)}/{len(sub)} generation-relevant ({pct:.1f}%), "
            f"pairs with n_with>=5: {len(with_n)}"
        )


if __name__ == "__main__":
    main()
