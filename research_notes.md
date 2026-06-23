# Research notes (not yet implemented)

Scratch pad for generation/popularity hypotheses and known quirks. See `spec.md` for implemented behavior.

## Jenny Barnes `02003` export quirks (2026-06)

### Flashlight `01087` / `card_index=2`

The generated deck has **one** Flashlight (`generated_count=1`). In `generated/Jenny Barnes 02003.csv`:

| rank | card_index | included_in_generated | generated_count |
|------|------------|----------------------|-----------------|
| 16   | 1          | True                 | 1               |
| 32   | 2          | **False**            | 1               |

So generation did **not** include the index=2 option. The index=2 row appears because the export truncates at the **last included row in P5 order**; intermediate rows (even with `included_in_generated=False`) are kept for context.

**Export bug / confusion (fix later):** `generated_count` is keyed by `canonical_id` only, not by `(canonical_id, card_index)`. Both Flashlight rows show `1`, which reads like “index 2 is included once.” Prefer per-option counts or a column that makes the index semantics explicit.

### Many cards at a single copy

Jenny’s export shows ~19 included rows with `generated_count=1` vs ~14 with `2` (26 unique cards total in deck). Plausible causes to investigate:

- Phase 2 stops at `final_deck_size` while walking P5 once; lower-ranked second copies never reached.
- Slot ceilings (`phase2_ceiling`) block duplicate assets (e.g. Hand slots).
- `_row_already_satisfied` / popularity ordering spreads picks across many distinct cards before revisiting copy 2.

Compare to training decks: do real Jenny lists run more 2× staples at 0 XP?

---

## Global 0 XP popularity list (future EDA)

**Goal:** Rank the top **N** (start with **N=100**) 0 XP `(canonical_id, card_index)` options **across all investigators**.

**Popularity (same as P5 per investigator):**

\[
P = \frac{\sum \text{weight of decks that include the option}}{\sum \text{weight of decks that *can* include the option}}
\]

**“Can include” set (important):** investigators for whom the card is legal under **natural** deckbuilding only — do **not** expand eligibility because an investigator *could* take Versatile (or another permanent) and thereby gain access to off-class level-0 cards. Permanent-granted access is conditional; the global denominator should reflect baseline legality.

**Uses:**

- Sanity-check per-investigator generation (are we picking globally popular cards that are only niche for that investigator?).
- Prioritize Phase 0.5 / staple permanents vs card picks.
- Compare investigator-specific P5 to global P5 for the same option.

---

## Cycle / investigator-age hypotheses (future EDA)

1. **Investigator dominated by own era:** For investigator with `inv_cycle = C`, is P5 mass concentrated on cards with `cycle ≤ C` (signature + core pool) vs later cycles?

2. **Inclusion skew vs eligibility:** For a card with cycle `k`, among investigators who *can* naturally include it, is the subset that *do* include it skewed toward investigators with `inv_cycle ≤ k` (or equal to card cycle)?

**Possible metrics:**

- Weighted share of P5 or slot usage from cards by cycle bucket.
- For each `(card, investigator)` pair: include rate vs investigator cycle relative to card cycle.
- Compare early investigators (Agnes, Roland) vs late (Marble) on the same Core card.

**If confirmed:** generation might need cycle-aware popularity pools or inv_cycle floor when slicing training decks (related to existing `Decklist.cycle` bias in spec, but investigator-card cycle vs card cycle).

---

## Faction vs investigator-specific popularity (future EDA)

**Motivation:** Some cards are **faction staples** (high P5 across many investigators in Guardian / Seeker / …). Others are **investigator-specific** — high P5 for one (or a few) investigators, low elsewhere despite being legal.

**Example — Ursula Downs + Tooth of Eztli (`04023`):**

| Investigator | P5 (index 1) |
|--------------|--------------|
| Ursula Downs (`04002`) | **0.37** |
| Mandy Thompson | 0.25 |
| Daisy Walker | 0.05 |

Tooth is cycle-4, Accessory, legal for many Seekers; generated Ursula lists include it (rank 22 in her export). It is not a global Seeker staple — it is **Ursula-shaped** (Forgotten Age pool + relic option synergy).

**Possible analyses:**

1. **Per-faction global top-N** — same P5 formula as global list, but denominator = decks of investigators whose **primary faction** matches (natural deckbuilding only).

2. **Investigator specificity score** — for each `(card, index)`, compare P5 for investigator `i` to max/mean P5 over all investigators who can naturally include it:
   - High ratio → investigator-specific staple
   - Low ratio, high mean → faction staple

3. **Generation implication:** investigator-specific cards might need conditional popularity (only boost when P5(i, card) ≫ P5(faction, card)), or accept them when they rank highly on **that** investigator’s list (current behavior — Ursula gets Tooth because it is popular *for Ursula*).

---

## Joe Diamond hunch deck — 11 [[Insight]] events (not yet enforced)

**Game rule:** Joe has a **40-card main deck** plus an **11-card hunch deck**; hunch deck cards must be [[Insight]] **events** (signatures `05009`/`05010` are part of this structure; `Unsolved Case` has the Insight trait).

**Current generation:** **No enforcement.** `deck_options` in `card_json` for `05002` has no Insight trait block (unlike Agatha Crane `11007`, who *does* have an Insight-event option in ArkhamDB). The generator only uses P5 + slot targets; the latest generated Joe deck happened to include **17** Insight events by popularity, not because of a rule.

**Training data (1144 Joe decks, all cards in `slots`):** Insight-event counts vary widely (mode 11–15, but **min 0** — many ArkhamDB lists are incomplete or ignore hunch composition).

**How to enforce (when we implement):** mirror **Ancestral Knowledge’s 10-skill minimum** (already in `apply_permanent_composition_rules` + Phase 2 slot reserve):

1. **Investigator composition rule** for `05002`: `minimum_insight_events = 11` (count events with Insight trait; include required `05010` from Phase 0).
2. **Phase 2 reserve:** while `insight_events < 11`, skip non–Insight-event picks if remaining slots `≤ 11 - insight_events` (same pattern as `remaining_skill_reserve()`).
3. **Legality filter:** only [[Insight]] events eligible for hunch-fill picks (optionally restrict to Seeker/neutral level 0–5 per main deck rules).
4. **Export (later):** tag hunch vs main deck in CSV if we split output; ArkhamDB mixes them in `slots` today.

**Alternative:** add a synthetic `deck_options` minimum for Joe (and parse `atleast` / trait floors from ArkhamDB when present) so one code path handles Agatha, Kate Winthrop, Joe, etc.

---

## Norman Withers — replacement signatures + deck size 29 on ArkhamDB (fixed 2026-06)

**Symptom:** Building from an older export on ArkhamDB showed **29** cards toward deck size. User's correct list uses **Split the Angle** (`98008`) + **Vengeful Hound** (`98009`), not Livre + Harbinger.

**Root cause:** Phase 0 always added default keys (`08005`, `08006`) only. Unchosen alternatives (`98008`, `98009`) were **not** in `requirement_ids`, so Phase 2 could add Split the Angle as a regular card — yielding **both** signature sets partially (Livre + Harbinger + Split), stealing a deck slot.

**Fix:** Parse OR-groups from `deck_requirements.card`; pick one per group by exclusive training-deck count; treat **all** group members as requirement ids.

---

## Tommy Muldoon — Schoffner's Catalogue `08072` (expected, not generated)

**Schoffner's Catalogue** is a slotless campaign-adjacent asset (Circle Undone). Only **~1.5%** of Tommy training decks include it (rank **245**, P5 ≈ 0.035). Generation correctly skips it by popularity; thematic expectation (Tommy's story item) is not modeled separately. If desired later: investigator-specific allowlist or bonded/story cards.


