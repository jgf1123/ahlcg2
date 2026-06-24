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

---

## Shrewd Analysis (`04106`) + unidentified/untranslated Seeker assets (not yet enforced)

**Symptom:** Generated **Carolyn Fern** (`05001`) includes *Shrewd Analysis* (`04106`, Phase 0.5 permanent) but no `(Unidentified)` / `(Untranslated)` Seeker asset — e.g. no `08033` *Archive of Conduits* at deck creation, even though training decks often pair them.

**Card rule:** `04106` is a **permanent**. When you upgrade an `(Unidentified)` or `(Untranslated)` card, you may upgrade a **second copy** of that card at no XP; the two upgraded versions are chosen **at random** among eligible options (subject to deckbuilding). In practice you want **two copies of the same base line** in the deck at creation so Shrewd's discount applies to a pair.

**Seeker unidentified / untranslated base assets** (10 lines in card data):

| `canonical_id` | Name | Subtitle | ArkhamDB `xp` |
|----------------|------|----------|---------------|
| `02021` | Strange Solution | Unidentified | 0 |
| `03025` | Archaic Glyphs | Untranslated | 0 |
| `04022` | Ancient Stone | Unidentified | 1 |
| `06112` | Dream Diary | Untranslated | 0 |
| `07022` | Cryptic Grimoire | Untranslated | 0 |
| `08033` | Archive of Conduits | Unidentified | 0 |
| `10044` | Ravenous Myconid | Unidentified | 0 |
| `11035` | Dial of Ancients | Unidentified | 0 |
| `60210` | Forbidden Tome | Untranslated | 0 |
| `60259` | Scroll of the Pharaohs | Untranslated | 0 |

### Popularity fragmentation

Players typically commit to **one** (sometimes two) unidentified **lines** per deck, not all ten. P5 is computed per `(canonical_id, card_index)`; mass splits across lines, so no single line reaches the Phase 0.5 / early Phase 1/2 ranks that *Shrewd Analysis* enjoys as a **single** permanent (~25% P5 for Carolyn).

| Carolyn metric | Value |
|----------------|-------|
| Shrewd in training decks | 27% of deck weight |
| Pooled P(any unid line, base in `slots`) | P5 ≈ 0.16 |
| Shrewd P5 | ≈ 0.25 |
| Archive of Conduits (`08033`) P5 | ≈ 0.19 (rank ~43; deck often full before pick) |
| Ancient Stone (`04022`) P5 | ≈ 0.18 — **excluded from v1 0 XP generation** (ArkhamDB marks base at `xp=1`; Carolyn may still take 0–1 Seeker in real decks) |

**Generation split:** Shrewd enters in **Phase 0.5** (permanent above cutoff). Unid assets compete in **Phase 1/2** on individual P5. Only Carolyn currently gets Shrewd in generated output (highest Shrewd rate in training data).

### Co-occurrence — use upgrade-family “contains option”

Raw `slots` often show **upgraded** printings, not the base unid card. Under [Definition of a decklist containing an option](spec.md#definition-of-a-decklist-containing-an-option), a deck with `04231` *Ancient Stone: Minds in Harmony* **contains** option (`04022`, 1) because upgrades count toward the family.

Re-counting Carolyn **Shrewd** decks with `UpgradeGraph.count_option_in_slots` (not base-id-only):

| Metric | % of Shrewd deck weight |
|--------|-------------------------|
| Contains **any** unid/untranslated line (family) | **59%** |
| No unid family in `slots` | **41%** |
| Contains (`04022`, 1) — Ancient Stone family | **52%** |
| Contains (`08033`, 1) — Archive family | **24%** |
| **2+ copies** in same family (Shrewd-relevant pair) | **46%** (almost all Ancient Stone) |

The earlier “55% of Shrewd weight has no **base** unid in `slots`” figure **understates** pairing: many lists already show upgraded printings only. The upgrade-aware figure is still **~41%** with no unid family at all (theorycraft, not yet upgraded, or unrelated Shrewd include).

**One copy is not enough:** Shrewd's benefit targets upgrading **two** copies of the same line. Training data weighted toward **two-copy Ancient Stone** families (~46% of Shrewd decks); Archive pairs are rarer at two copies.

### Carolyn-specific: upgrades are not random

Carolyn's `deck_options` include:

- **0–1 Seeker/Mystic** (15-card cap) — allows base unid Seeker assets at level 0–1.
- A **heal horror** text option (`[Hh]eals? … horror`) — cards must match that pattern to be legal picks.

For the two dominant Shrewd partners, each unidentified line has only **one** horror-healing researched upgrade that fits Carolyn:

| Base | Researched upgrade | Heals horror? |
|------|-------------------|---------------|
| `08033` Archive of Conduits | `08044` Gateway to Paradise | Yes |
| `04022` Ancient Stone | `04231` Minds in Harmony | Yes |

So Carolyn + Shrewd + Archive/Ancient Stone is **not** “random branch” behavior in training data — deckbuilding leaves **one** eligible upgrade per line. Shrewd's random-upgrade text matters less here than for investigators with multiple researched branches.

**Design implication:** a pairing rule for Carolyn (and similar investigators) should prefer **two copies of one 0 XP unid line** (or one line with room for a second copy), not merely “any one unid asset.” Ancient Stone is the usual pair target in data; Archive is second.

### Proposed directions (not implemented)

1. **Composition rule:** if `04106 ∈ S` (Phase 0.5), require **≥2 copies** of the **same** unidentified/untranslated Seeker line at 0 XP (pick line by pooled P5 or investigator-conditional P5), before Phase 2 fills with events/skills.
2. **OR-group popularity** for “one unid Seeker package (copy 1)” when scoring — analogous to signature OR-groups — then pick a representative `canonical_id` for the deck.
3. **0 XP eligibility:** treat `04022` base as 0 XP at deck **creation** for generation (Carolyn's 0–1 Seeker access) if we confirm rules intent vs ArkhamDB `xp=1` on the unidentified printing.
4. **Export / version diff:** flag generated decks with Shrewd but no unid family as incomplete.

**Related:** global vs investigator-specific popularity ([faction vs investigator](#faction-vs-investigator-specific-popularity-future-eda)); Phase 0.5 permanent selection ([spec.md](spec.md#phase-05--select-permanents)).

