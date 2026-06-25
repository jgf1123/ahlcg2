# Research notes (not yet implemented)

Scratch pad for generation/popularity hypotheses and known quirks. See `spec.md` for implemented behavior.

## Research priorities (2026-06)

Manual review of **~35 generated decklists** (~3 most popular investigators per `inv_cycle`) surfaced several issues documented below. **Most pressing open question:**

> **How does `inv_cycle` relate to `CanonicalCard.cycle` in training data (and generated decks)?**

Unlike `Decklist.cycle × CanonicalCard.cycle`, the pair **`inv_cycle × k`** is not constrained by definition (`k` may be above or below the investigator’s publication cycle). If legacy investigators’ weighted slot mass stays on `k ≤ inv_cycle` despite cards from later cycles being legal and present in P5 pools, generation will look “era-locked” — either faithfully reflecting stale ArkhamDB lists or missing a weighting fix.

| Priority | Topic | Section |
|----------|--------|---------|
| **1** | `inv_cycle` × `CanonicalCard.cycle` | [below](#priority-invcycle--canonicalcardcycle-2026-06) |
| 2 | Option co-occurrence / lift | [Option co-occurrence](#option-co-occurrence--lift-future-eda) |
| 3 | Global 0 XP popularity | [Global list](#global-0-xp-popularity-list-future-eda) |
| 4 | Faction vs investigator-specific P5 | [Faction vs investigator](#faction-vs-investigator-specific-popularity-future-eda) |
| 5 | Investigator popularity / promo / cohort vs global | `spec.md` I1–I5 |

---

## Priority: `inv_cycle` × `CanonicalCard.cycle` (2026-06)

**Core question:** For investigator with `inv_cycle = I`, what fraction of **player-chosen** slot copies (weighted) come from `CanonicalCard.cycle = k`? Does mass beyond `k > I` (“tail”) differ by investigator and by `inv_cycle` cohort?

**Why it matters for generation:** P5 eligibility uses `Decklist.cycle ≥ k` per card, not “would a cycle-`I` investigator pick cycle-`k` cards today.” Marginal P5 can be high for a new card while **composition** of that investigator’s training decks remains Core-heavy. Generated lists inherit that mix unless tail mass in training is large enough (and weighted enough) to pull picks forward.

### Hypotheses to test

1. **Investigator era lock:** Tail mass `T_i = Σ_{k > I} share_i(k)` is low for early `inv_cycle`, even when many training decks have high `Decklist.cycle` (large card pool, old-era picks).

2. **Cohort pattern:** Investigators grouped by `inv_cycle` show similar `share(k)` curves — suggesting analysis at **inv_cycle** stratum is the right aggregation (not only per-investigator).

3. **Core overhang within investigator:** Cycle-1 share stays elevated for all `inv_cycle` (cf. global B3 baseline); tail `k > I` is the distinct signal for “new cards for old investigators.”

4. **Generated vs training:** Compare card-cycle histogram of generated decks to per-investigator (or per-`inv_cycle`) training shares; flag large negative tail gap.

### Metrics

| Metric | Definition |
|--------|------------|
| **`share_i(k)`** | Weighted slot-copy fraction from card cycle `k` for investigator `i` (exclude signatures + random basic weaknesses). |
| **Tail mass** `T_i` | `Σ_{k > inv_cycle} share_i(k)`. |
| **Own-era mass** | `Σ_{k ≤ inv_cycle} share_i(k)`. |
| **Cohort** `share_I(k)`** | Weight-averaged `share_i(k)` over investigators with `inv_cycle = I`. |
| **Generated gap** | Tail mass (or full distribution) of generated deck minus training for same investigator. |

### Tools

- **`export_inv_cycle_card_cycle_pivots.py`** — twelve CSVs in `inv_cycle_pivots/inv_cycle_{D:02d}.csv`: fixed `inv_cycle=D`, rows `Decklist.cycle` `C`, columns `k_1…k_12` (weighted slot-share; blank if `k > C`). For calibrating `b_{C,D}(k)` vs `b_C(k)`.
- **`prior_calibration_eda.py`** — compare empirical `(C,D)` slices to hand prior `b_C(k)` (L1 distances).
- **`investigator_card_cycle_eda.py`** — per-investigator and group-by-`inv_cycle` tables; `--front` detail; `--csv` export.
- **`analyze_cycle_confounding.py`** — global `Decklist.cycle` × `k` pivot (complementary; not the same question).
- **`investigator_decklist_cycle.py`** — per-investigator `Decklist.cycle` histogram (pool depth vs card-era mix).
- **Generated exports** — `generated/*.csv` from the ~35-deck review batch.

### If confirmed — generation directions

- Stratum- or tail-aware P5 pooling (e.g. emphasize training decks with high tail mass when scoring `k > I` cards).
- Report card-cycle mix in generated export / version changelog.
- Optional `inv_cycle` cohort defaults when investigator-specific tail is sparse.

**Related:** `Decklist.cycle` distribution and list age (`decklist_id`); investigator popularity (`spec.md` I1–I5); promo / `popularity_global` caveat; [published training pool](#published-training-pool-2026-06); [card-cycle prior `b_{C,D}(k)`](#card-cycle-prior-bc-dk-2026-06).

---

## Published training pool (2026-06)

**Implemented:** `PreparedDecklist.excluded_from_published_pool` + `ArkhamPopularityEngine.published_training_filter` (default on). Card popularity (P3–P5), B2/B3 weights, composition EDA, and `inv_cycle × k` pivots use `engine.training_pool_decks()` / `in_published_training_pool()`. **`is_ignore` unchanged** (taboo, unknown slots, Chapter 2).

### Rule

Keep decklists in the **published training pool** when **all** of:

1. **Canonical investigator printing** — `to_canonical(investigator_front) == canonical_front` (and back). Alt-art reprints allowed (`01501`→`01001`, `98007`→`08004`, `98019`→`11014`, **`99001`→`05006` Marie**).
2. **Primary published signatures** — exactly one printing per `deck_requirements` OR-group; no promo (`98***`/`99***`) or parallel (`900***`) signature alts. Ambiguous groups (both/neither) excluded.

**Not filtered:** Charlie Kane `faction_select` strata; Marie promo **front** (`99001`); parallel **investigator** tuples (`90084` Jenny) — excluded by (1), not signature rule.

### Why

Promo **signature** kits (Norman `98008`/`98009`, Gloria `98020`/`98021`, …) correlate with **low `Decklist.cycle`** relative to `inv_cycle` and older `decklist_id` — a pre-release pool artifact, not sparse mis-tags. Filtering removes Norman’s `C<9` spike (36%→4% weight below `inv_cycle`) while keeping ~97% of non-promo investigators.

### Data loss (primary tuples, weighted)

| Tier | Examples | Kept |
|------|----------|-----:|
| Most investigators | Core, starters | 97–100% |
| Moderate | Roland, Jenny, Carolyn | 86–90% |
| Heavy | Norman 63%, Dexter 54%, **Gloria 35%** | promo stratum is large |

**Gloria** remains an edge case (last Chapter 1 `inv_cycle`); even after filter, ~46% of weight has `C<12`. **No clean fix** — accept or keep separate promo stratum for diagnostics.

**Tools:** `analyze_canonical_pubsig_filter.py`, `analyze_published_signature_filter.py`, `analyze_signature_profile_timing.py`.

---

## Card-cycle prior `b_{C,D}(k)` (2026-06)

**Motivation:** Spec B3 prior `b_C(k) = (0.76/C + 0.22·I(k=1))/0.98` pools over all `inv_cycle` at fixed `Decklist.cycle = C`. EDA shows structure depends on **`(C, D)`** where `D = inv_cycle`.

### Components (from `inv_cycle_pivots/` — use **published training pool**)

| Component | Pattern |
|-----------|---------|
| **k = 1** | Core basis elevated across all `D`, `C` |
| **k = D** | Investigator-kit ridge (e.g. Nathaniel `k=7` at `C=7`); often **larger than k = C** novelty |
| **k = C** | Decklist-cycle novelty (B3 tilt target) |
| **k ∈ {4, 6, 8}** | Era dips (Forgotten Age, Dream-Eaters, Innsmouth) |
| **1 < k < D** vs **D < k < C** | Pre-investigator cycles higher than post-investigator adoption tail |
| **δ_{investigator,k}** | Investigator-specific bumps (Patrice `k=4` at `D=6`); shrink unless sustained across `C` |

**`b_C(k)` calibration:** Rough at `C≈6–9`; poor at `C=2–3`, starter `C=7`, `C=12`. Does **not** hold uniformly across `D` at fixed `C` (L1 up to ~0.89). Same-cycle novelty in marginal `b_C(k)` was **underestimated** when `k=D` ridge folded into uniform tail.

### Factorization (research; estimated by `estimate_b_c_d.py`)

\[
b_{C,D}(k) \propto b^{\mathrm{hand}}_C(k) + \alpha(D)\,I(k{=}D) + \beta(C)\,I(k{=}C) + \gamma_k
+ \frac{\rho(D)}{|{k : 1<k<D}|}\,I(1{<}k{<}D)
+ \frac{\tau(D)}{|{k : D<k<C}|}\,I(D{<}k{<}C)
\]

Positive masses are clipped, then normalized over `k=1..C`. At **`C=D`**, `α(D)` and `β(C)` both apply at `k=D` (kit + novelty on the diagonal).

| Term | Role |
|------|------|
| **`b^hand_C(k)`** | Re-fit `(ε_1, ε_u, ε_C)` per `C`: `ε_u/C + ε_1·I(k=1)` on `k<C`, `ε_C` at `k=C`; **not** the legacy `0.76/C` anchor |
| **`α(D)`** | Investigator-kit ridge at `k=D` (`C≥D`, `C≠D` cells) |
| **`β(C)`** | Decklist-cycle novelty at `k=C` (B3 tilt target) |
| **`γ_k`** | Sparse global era bumps/dips — **screened from data**, not fixed `{4,6,8}` |
| **`ρ(D)`** | Legacy-pool boost on **pre-era** interior `1 < k < D` |
| **`τ(D)`** | Adoption-tail **deficit** on `D < k < C` (typically ≤ 0) |

**`δ_{investigator,k}`** (Patrice-style) is deferred until a stratum has enough `N` across `C`; not in the first-pass estimator.

### Estimation procedure (`estimate_b_c_d.py`)

**Input:** same weighted pivot as `export_inv_cycle_card_cycle_pivots.py` (published training pool, `investigator_deck_weight`).

**Cell filter:** `(C,D)` with `deck_count ≥ 30` (`N_MIN_CELL`).

1. **Hand prior `b^hand_C`** — grid search `(ε_1, ε_u, ε_C)` minimizing weighted SSE on observations where `k ∉ {C,D}`, `k` not in `(1,D)` or `(D,C)` interiors. Global fit pooled over all `C`; per-`C` fit shrunk toward global (`λ=80`). Legacy `(0.76, 0.22, 0.02)` is fallback only when `n_obs < 5`.

2. **`γ_k`** — weighted median residual `μ_{C,D}(k) − b^hand_C(k)` over generic `k` (exclude diagonals and both interiors); shrink (`λ=60`); keep only `|γ_k| ≥ 0.008` with `n_eff ≥ 40`.

3. **`α(D)`** — at `k=D`, `C≥D`, `C≠D`: median residual after hand + γ; shrink; clip ≥ 0.

4. **`β(C)`** — at `k=C`: median residual after hand + γ (+ `α` when `C=D`); shrink; clip ≥ 0 (or hand `ε_C` if negative).

5. **`ρ(D)`** — mean/median boost on `1 < k < D` after hand + γ; shrink; clip ≥ 0.

6. **`τ(D)`** — median residual on `D < k < C` after hand + γ; shrink; clip ≤ 0 (deficit spread on tail).

7. **Assemble** — sum components, normalize per `(C,D)`; write **`b_c_d_estimate.json`** (`hand_per_C`, `gamma_k`, `alpha_D`, `beta_C`, `rho_D_pre_era`, `tau_D_tail`, `b_C_D`).

**B3 use:** `prepare_arkham_data.ipynb` cell 7 sets `USE_B_CD_PRIOR = True` (default) and loads `b_c_d_estimate.json` via `popularity_engine_kwargs`. Set `USE_B_CD_PRIOR = False` for legacy `b_C(k)`. `tilt_scope="core_novelty"` tilts only `k ∈ {1, C}`. Re-run `python estimate_b_c_d.py` after training-pool changes, then re-run notebook cells 7+.

### Initial estimator run (2026-06, published pool)

`python estimate_b_c_d.py` → `b_c_d_estimate.json`.

| Finding | Detail |
|---------|--------|
| **Hand re-fit** | Global `ε_1≈0.10`, `ε_u≈0.40`, `ε_C≈0.06` (vs legacy `0.22/0.76/0.02`); per-`C` at `C≥5` drifts toward `ε_1≈0.17`, `ε_u≈0.72`, `ε_C≈0.10` |
| **`γ_k`** | None passed `|γ|≥0.008` after shrink — era structure largely absorbed by re-fit hand + `α`/`τ` in this pass |
| **`α(D)`** | Strong kit ridges `D=7` (+0.23), `D=1` (+0.14), `D=11` (+0.14); others ~0.07–0.12 |
| **`ρ(D)`** | No separate pre-era boost above display threshold (legacy interior mass may be in higher `ε_u`) |
| **`τ(D)`** | Consistent tail deficits ~−0.02 to −0.03 on `D<k<C` |
| **L1** | Mean L1 `μ_{C,D}` vs prior: legacy `b_C` **0.29** → fitted `b_{C,D}` **0.21** (cells `N≥30`) |

### Tools

- **`export_inv_cycle_card_cycle_pivots.py`** — `inv_cycle_pivots/inv_cycle_{D:02d}.csv` (rows `C`, cols `k`; published pool).
- **`estimate_b_c_d.py`** — component fit + `b_c_d_estimate.json`.
- **`prior_calibration_eda.py`** — L1 vs legacy `b_C(k)` by `(C,D)` slices (compare to fitted `b_{C,D}` separately).

### Investigator stratum key (research)

`(canonical_front, canonical_back, signature_profile)` separates promo vs published **mechanical** kits (Norman/Gloria promo sigs tightly pair with promo art fronts). **Marie** shares one signature profile across `05006`/`99001` — era signal is **front printing**, not signatures; keep `99001` per user decision.

---

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

## Option co-occurrence / lift (future EDA)

**Goal:** Find **pairs** of distinct 0 XP options `(canonical_id_A, index_A)` and `(canonical_id_B, index_B)` that appear together more often than independence would predict — synergy, packages, or enforced pairs (e.g. two copies of a line for Shrewd).

**Lift (per investigator):**

\[
\text{lift}(A, B) = \frac{P_5(A \cap B)}{P_5(A) \cdot P_5(B)}
\]

- **Numerator** \(P_5(A \cap B)\): same weights as P5; fraction of P3-eligible decks that **contain both** options (use existing “decklist contains option” rules, including upgrade-family containment where relevant).
- **Denominator:** product of marginal P5 for each option on that investigator.
- **Independence baseline:** lift \(= 1\). Lift \(> 1\) → positive association; \(< 1\) → substitutes or anti-correlation.

**Filters and scope:**

1. **Exclude deckbuilding requirement cards** — signatures, chosen OR-group printings, and other `deck_requirements.card` ids (same set excluded from `Decklist.cycle` / player-deck-size counting). Do not score pairs where either side is a forced requirement.
2. **Distinct `canonical_id` only** — do not pair `(card_0, index=1)` with `(card_0, index=2)`. Players often run 2× the same card; that mechanical correlation would dominate and is not interesting synergy. (Separate analysis if we ever want “second copy” behavior.)
3. **Top \(D^2\) pairs only** — let \(D\) = investigator **deck size** (`deck_requirements.size`, typically 30–50). Restrict to unordered pairs drawn from the top \(D\) options by P5 (or top \(D\) distinct `canonical_id`s by max P5 per card). Full cross-product is \(O(n^2)\) and noisy at the tail.
4. **Small-P5 sensitivity** — when \(P_5(A)\) or \(P_5(B)\) is tiny, lift is unstable (ratio blows up on rare co-includes). The top-\(D^2\) gate mitigates this; optional floor on marginals (e.g. only pairs with \(P_5 \geq 1/D\)) if needed.
5. **Ceiling on high marginals** — if \(P_5(A)\) is already high (e.g. 0.8), \(P_5(A \cap B) \leq P_5(B)\), so lift \(\leq P_5(B) / P_5(A)\). Staples with \(P_5 \approx 1\) cannot show large lift even when always paired; interpret lift alongside raw \(P_5(A \cap B)\) and co-include weight.

**Uses:**

- Detect **packages** (permanent + supporting assets, faction pairs, engine pieces).
- Inform generation beyond marginal P5 (conditional adds, composition rules — cf. [Shrewd + unid](#shrewd-analysis-04106--unidentifieduntranslated-seeker-assets-not-yet-enforced)).
- Compare lift at different `Decklist.cycle` strata (do pairs strengthen as the card pool grows?).

**Not yet implemented.** Reuse `ArkhamPopularityEngine` P3/P4 weights and `deck_contains_*_option` / upgrade-family containment for the joint numerator.

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

