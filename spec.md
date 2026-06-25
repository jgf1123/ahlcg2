# Goal

The goal is identify the most popular cards used by various investigators in the customizable card game Arkham Horror: The Card Game. Players craft decklists that use a particular investigator and a deck of cards. A naive approach to calculate the popularity of a `card_id` for investigator (`canonical_front`, `canonical_back`) tuple is to find all decklists with (`canonical_front`, `canonical_back`) and sum the number of copies of `card_id` in those decklists. We will modify this approach to reflect various aspects of the game.

The following describes the current pipeline (`prepare_arkham_data.ipynb` + `arkham_*.py` modules).

# Data

Scraping uses `scrape_arkhamdb.py` (`decklists`, `cards`, `discover-max` subcommands). To avoid overloading the API, we load previously scraped data, request only the new data, and save the updated data as a pickle file. While the structure of decklist dict's are almost uniform, there are variations, so we save the raw data as a dict using pickle.

Only the scrapper functions are allowed to overwrite the pickled data. The functions that calculate popularity are forbidden from saving pickled data.

## Scraping and cleaning

- **Decklists:** scrape via `scrape_arkhamdb.py decklists` (default `--mode incremental` from max pickle id to current public max) or `--mode gaps` to fill historical holes; store as `{decklist_id: dict}` in `decklist_json.pickle`. Empty API responses (HTTP 200, zero body) may be deleted or privatized — use `--store-empty` to record as `None`, or `--verify` to re-check existing entries. Drop empty entries (`None`) at clean time. Remove known joke decklists (`43839`, `44599`, `45550`) and any deck with a slot copy count `≥ 4` above `deck_limit` for that `card_id` (see `clean_decklist_json` in `arkham_popularity.py`).
- **Cards:** scrape via `scrape_arkhamdb.py cards` (missing ids only) or `cards --refresh-all` after a full card-data refresh; store as `{card_id: dict}` in `card_json.pickle`. Card discovery uses `slots` plus investigator front/back from `investigator_code` and `meta.alternate_front` / `alternate_back`. Skip list `SKIP_CARD_IDS` (e.g. `07062`) omits bogus slot codes with no ArkhamDB card page.
- **Taboo:** fetch `taboo.json` separately from the API.
- Only scraper code may overwrite pickles. Popularity code may write CSV outputs but must not overwrite pickles.

# Organization of `card_id`

## Legacy `pack_code`

When the game was first published, all players needed the Core set (`pack_code='core'`).

The game was then expanded with cycles. Originally, each cycle contained a deluxe expansion and then 6 mythos packs. (Some legacy of this is now in `arkham_canonical.py`.)

After cycle 8 (that is, if we treat the Core set as cycle #1, Investigator Starter decks as cycle #7, and the first 6 expansions as cycles #2-6, 8), cycles were instead released as two `pack_code`s, an Investigator Expansion and a Campaign Expansion. By and large, players will build decklists using cards from the Investigator Expansion but under special circumstances add cards from the Campaign Expansion.

At some point, arkhamdb deprecated the old mythos pack organization. Done: ~~We should scrape the card data again to make sure we are using the most current data.~~

There are also "Return to the..." card sets. While they are related to a particular cycle (e.g., "The Dunwich Legacy" with `pack_code='dwl'` and "Return to the Dunwich Legacy with `pack_code='rtdwl`), treat them as separate packs.

## Cards with multiple `card_id`

ArkhamDB assigns a distinct `card_id` to many printings of the same physical card (Core vs Revised Core, investigator starters, etc.) and to genuinely different cards that share a `name`. We map every `card_id` to a **`canonical_id`**. Popularity, cycle assignment, and upgrade logic all use `canonical_id`, not raw `card_id`.

Note: previously, legacy code in `prepare_arkham_data.ipynb` used `mythos` where this spec uses **`cycle`**. Refactor toward `cycle` when implementing.

### Choosing `canonical_id`

Each `canonical_id` is the **`card_id` of the earliest printing** in the equivalence class (lowest first-printing `cycle`, then lowest numeric `card_id`; `rcore` reprints are not earliest — see `canonical_cycle`). Examples:
| `card_id`s | `canonical_id` | Reason |
|---|---|---|
| `01017`, `01517`, `60108` | `01017` | Reprints; `01517` and `60108` have `duplicate_of_code='01017'` |
| `01056`, `01556` | `01056` | Reprint; `01556` has `duplicate_of_code='01056'` |
| `01095`, `01595` | `01095` | Reprint; taboo-placeholder text; `01595` duplicates `01095` |
| `60120`, `01022` | *(separate)* | Different `xp` (1 vs 0) — upgrade, not reprint |
| `05186`, `05187` | *(separate)* | Same `name` and `xp`, different text and `faction_code` |
| `08723`–`08729` | *(seven ids)* | Same `name`, different revelation text (Tekeli-li) |

### Fingerprint (same card → same `canonical_id`)

Two `card_id`s belong to the same `canonical_id` if **all** of the following match:

1. **`name`**
2. **`subname`** — treat missing/`null` as `''` (384 cards use `subname` for branches, e.g. Strange Solution variants)
3. **`xp`** — treat missing/`null` as `0`
4. **Compare text** — see below
5. **Enumerable fields:** `type_code`, `faction_code`, `exceptional`, `myriad`, `cost`, `deck_limit`, `is_unique`, `permanent`

**Compare text** is:

```coalesce(normalize(text), normalize(real_text), '')```

- normalize: collapse whitespace; normalize [[Trait]] → [Trait]; normalize chaos-token symbols (-, −, –, skull icons) to a single form.

Do **not** use `real_text` alone: for taboo-placeholder reprints, `text` is often null on both printings while `real_text` may be '' vs null.

### Authoritative merge: `duplicate_of_code`

If ArkhamDB sets `duplicate_of_code`, that `card_id` belongs to the same `canonical_id` as `duplicate_of_code`, regardless of minor text encoding differences (e.g. Sure Gamble `01056` / `01556`). Apply fingerprint grouping first, then merge any card with `duplicate_of_code` into its target's class.

### Separate `canonical_id` (do not merge)

Keep distinct `canonical_id`s when any of the following hold:

- Different `xp` (upgrades are separate canonical nodes, linked later by upgrade family — see Popularity Calculation).
- Same `name`, `subname`, and `xp` but **different compare text** (after normalization). This includes:
  - **Advanced** signature cards (`90019` Dark Memory with "Advanced" in `text` vs `01013` Dark Memory)
  - **Same-XP upgrade branches** without subname (e.g. `05186` / `05187` .45 Thompson; `05188` / `05189` Scroll of Secrets)
  - Tekeli-li encounter weaknesses (seven different effects, same name)
- Different **enumerable fields** (e.g. `04236` On Your Own vs `53010`: permanent / exceptional; `11007` / `11008` Agatha Crane: `faction_code` = seeker vs mystic back)

When `name` and `xp` match but **`subname`** differs, they are **already** separate by the fingerprint (e.g. Strange Solution branches, Directive regulations).

### `canonical_cycle`

`CanonicalCard.cycle` = the **lowest** ordered `cycle` among constituent `card_id`s (first printing in pack order). Consider only `card_id`s whose `pack_code` maps to a cycle (see Pack Order), **except** `pack_code='rcore'`: Revised Core reprints are ignored when computing first-printing cycle (they are product-cycle 1 but not first printing). If every printing is from an out-of-order pack or only `rcore`, then `CanonicalCard.cycle = None`.

**`rcore` edge cases** (112 `rcore` cards in current scrape; all have `duplicate_of_code`):

| Pattern | Count | `CanonicalCard.cycle` | `canonical_id` |
|---------|------:|----------------------|----------------|
| `core` + `rcore` only | 91 | 1 (from `core`) | `core` `card_id` (not `rcore`) |
| `rcore` + one expansion / Return | 12 | min expansion cycle (e.g. `tece` → 2) | original expansion id |
| `core` + `rcore` + starter (`nat`/`har`/…) | 8 | 1 (from `core`; starter does not pull cycle to 7) | `core` `card_id` |
| `rcore` + starter, no `core` in class | 1 | starter cycle (7) | starter id (e.g. Seeking Answers) |

`pack_to_cycle('rcore')` remains **1** for **decklist** / pack-order purposes (`Decklist.cycle`). Only **card** first-printing logic excludes `rcore`.

### Choosing `canonical_id` with `rcore`

When picking the representative `card_id` in an equivalence class, sort by first-printing rank (as above), then lowest `card_id`. `rcore` printings sort **after** non-`rcore` members so `02158` Charisma wins over `01694`, and `01017` Physical Training wins over `01517`/`60108`.

### What we do not merge

- **Different versions with the same `name` but different gameplay** stay separate. If a human might consider them “the same card” with errata, they should be combined in one `canonical_id`; there should be very few instances so user can manually check.
- **Chapter 1 vs Chapter 2** cards are never merged across chapters (see Core 2026).
- Manual `merge_cards` dicts in old notebooks are **deprecated**; replace with this algorithm after re-scrape.

## Core 2026

There is a new Core set (`pack_code='core_2026'`) and 5 more Investigator Decks (`tom`, `car`, `and`, `mar`, `mig`). Some of the cards are identical to earlier cards. Some of the cards may be tweaked versions of earlier cards. These are not intended to be mixed with cards that came before. Everything that came before `core_2026` is Chapter 1 (cycles 1 to 12) and `core_2026` onward is Chapter 2 (cycles 13 and up).

For the purposes of this project, we will filter out all Chapter 2 cards and filter out all decklists with Chapter 2 cards.

## Pack Order

The publication order of the packs is:

- `core` (cycle 1)
- `dwl` (cycle 2)
- `ptc` (cycle 3)
- `rtnotz`
- `tfa` (cycle 4)
- `rtdwl`
- `tcu` (cycle 5)
- `rtptc`
- `tde` (cycle 6)
- `rttfa`
- The Investigator Starter Decks (`nat`, `har`, `win`, `jac`, `ste`) (we will call this cycle 7)
- `tic` (cycle 8) 
- `rttcu`
- `rcore` (cycle 1 except for publication order purposes)
- `eoe` (cycle 9)
- `tsk` (cycle 10)
- `fhv` (cycle 11)
- `tdc` (cycle 12)
- `core_2026`
- The Investigator Decks (`tom`, `car`, `and`, `mar`, `mig`)

Any cards from "Return to..." packs use the `cycle` of the cycle published immediately before it, e.g., `rtnotz` has `cycle=3`.

Cards from Side Stories, Promotional cards, and Parallel investigators are relatively rare, so for the purposes of this project, they are **not in the order**. Do not assign them a `cycle`. Any other `pack_code` not listed above (e.g. a new side story or promotional pack) also has `cycle = None` by default — there is no allowlist to maintain.

**Implementation:** map only the ordered packs above to `cycle` 1–12 (and Chapter 2 packs to `cycle` 13). `pack_to_cycle(pack_code)` returns `None` for everything else.

**Unknown vs out-of-order:** a slot is *unknown* only when its `card_id` is missing from scraped card data. A known card from an out-of-order pack is not unknown; it simply has `CanonicalCard.cycle = None`.

NOTE: Previous iterations described temporal order using "group" and "mythos". Group ID established the order in which mythos packs were released, and then `mythos` collected packs by cycle. Because the new pack organization does away with individual mythos packs, we do not need group ID, and we rename `mythos` to the more accurate label of `cycle`.

# Cycle Weighting

When a player creates a decklist, they do not always consider all cards published to date. Typically, players will buy cycles in order and build decklists from the packs they own, i.e., players own cycles 1 through X and build decklists using cards from 1 through X. Let the `Decklist.cycle` of a decklist be the maximum ordered `cycle` among the `canonical_id`s in its `slots` that reflect **player deckbuilding choices** (ignore slots whose `CanonicalCard.cycle` is `None`). Exclude from this max:

- **Deckbuilding requirements** — every signature printing listed in `deck_requirements.card` for `Decklist.canonical_front` (all OR alternatives, not only the printing present in the list). Signature assets and signature weaknesses are forced, not chosen.
- **Random basic weakness** — any slotted card with `subtype_code = basicweakness`.

The investigator card itself is not in `slots` and does not enter this calculation. If every remaining slot is out-of-order, `Decklist.cycle = None`. This creates a bias because players who have access to a larger pool of cards are more likely to make better decks.

**Rationale:** default signature printings can sit in a high `cycle` (e.g. Norman Withers' `08005` / `08006` are cycle 9) while parallel replacements are out-of-order (`cycle = None`). Counting requirements toward `Decklist.cycle` would force many decks to a high stratum based on printing choice, not on how far the player has bought into the product line. The same issue applies when a random basic weakness happens to come from a late cycle.

Furthermore, for a player building a decklist using cards from cycles 1 through X, we observe that, a *very rough* estimate is that ~76% of cards are evenly divided between cycles 1 through X, cycle 1 receives an additional ~22%, and cycle X receives ~2% for players picking cards because of novelty instead of utility (done: ~~recalibrated after the `rcore` card-cycle fix~~). Only the structural portion (~98%) enters `b_C(k)`; see B3.

- Exception: cycle 7, the Investigator Starter Decks, include many cards intended to work well with their investigator.
- The ~22% in cycle 1 is at least partially explained by it being the Core (`pack_code='core'` or `rcore`) set, which is intended to form the basis of deck construction.
- The ~2% in cycle X is treated as **novelty**, not part of `b_C(k)` — tilt at `k = C` down-weights decks that exceed the structural baseline.

Legacy: We previously asserted

> The lower `decklist_cycle`, the more decklists with that `decklist_cycle`.

This is demonstrably false. The misunderstanding came from counting slot copies by each card's `CanonicalCard.cycle` but interpreting it as `Decklist.cycle`.

# Investigator Front and Back

Decklists expose `investigator_code` plus optional alternates in `meta`:

- `meta.alternate_front` → `investigator_front`
- `meta.alternate_back` → `investigator_back`

If `meta` is absent or a field is missing, default to `investigator_code`. If `alternate_front` or `alternate_back` is the empty string `""`, treat it as missing and fall back to `investigator_code`.

## `canonical_front` and `canonical_back`

Apply the same idea as card canonicalization:

1. Map each front/back `card_id` to a **`canonical_front`** / **`canonical_back`** using the card fingerprint (investigator cards are still cards in `card_json`).
2. **`(canonical_front, canonical_back)`** is the investigator key for popularity — not `investigator_name` or `investigator_code` alone.
3. Treat each distinct `(canonical_front, canonical_back)` tuple as a **separate investigator** for analysis, even when `investigator_code` and display name match.

Examples:

- Default Agnes: `('01004', '01004')`
- Parallel Agnes: `('90017', '90017')` or mixed front/back pairs when players choose different sides
- Agatha Crane seeker back vs mystic back: `11007` and `11008` — same `name` and `text` in API, but different `faction_code`; **distinct** canonical ids and distinct `(canonical_front, canonical_back)` when used as front/back

## Art-only duplicates

Some parallel printings are functionally identical but have different `card_id` for artwork. When fingerprint fields match, merge to the same `canonical_front` or `canonical_back`. When in doubt, prefer merging only when `duplicate_of_code` agrees or all fingerprint fields match.

## Display name

Use `investigator_name` from the decklist for display only. Do not use it as a grouping key.

## Published training pool

Some investigators have **promo or parallel signature** printings in `deck_requirements.card` OR-groups (e.g. Norman `98008`/`98009` vs `08005`/`08006`). Decklists using non-published signature or parallel investigator printings skew **`Decklist.cycle`** low relative to `inv_cycle` (pre-release card pool). Card-popularity training therefore uses a **published training pool** separate from `is_ignore`.

On `prepare_decklist`, set **`excluded_from_published_pool = True`** when any of:

1. **`to_canonical(investigator_front) ≠ canonical_front`** or back mismatch — excludes parallel investigator products (`90084` Jenny, …). **Alt-art** reprints that map to the same canonical id are **allowed** (`01501`, `98007`, `98019`, **`99001` Marie**).
2. **Signature OR-groups** — not exactly one **primary published** printing per group (lowest non-promo, non-`900***` alt per group). Promo signatures (`98***`/`99***`) and parallel signature alts (`900***`) excluded. Both/neither in a group → excluded.

**`ArkhamPopularityEngine.published_training_filter`** (default `True`): `deck_weight`, P3–P5, B2/B3, and composition EDA use only decks with `excluded_from_published_pool = False`. **`is_ignore`** still handles taboo, unknown slots, and Chapter 2. Investigator popularity (I1–I5) still uses all non-ignored decks unless noted otherwise.

Set `published_training_filter=False` to reproduce unfiltered diagnostics. See [research_notes.md — Published training pool](research_notes.md#published-training-pool-2026-06).

# Multiple Copies of `card_id`

In general, a decklist can contain more than one copy of a single `canonical_id`. For the purposes of this project, we will treat each copy as a separate card, i.e., the popularity of (`canonical_id`, `card_index=1`) and (`canonical_id`, `card_index=2`) are calculated separately. This allows us to compare, say, the popularity of including a 2nd card A to including the 1st card B.

# Upgrading Decks

A player will create a decklist, play a campaign scenario using the decklist, earn some XP, and use that XP to upgrade their deck. This has several repercussions.

First, upgraded decks are evolutions of one design. Let's say users A and B create decklists for an investigator. If user A upgrades their decklist 7 times so there are 8 decklists total, that does not mean user A should have 8 times the voting power of user B.

At the start of the campaign, by and large players can only include 0 XP cards. Over the course of the campaign, they will replace some cards with cards that cost 1+ XP.

So second, 0 XP and 1+ XP cards should be handled separately.

Third, the 1+ XP cards that are bought first are more useful.

Fourth, when players upgrade their deck, usually they replace a 0 XP card with a 1+ XP card. We can conjecture at least two scenarios:

- The player picks a less useful card with the 1+ XP card, which signals a weak card.
- Due to deck building restrictions, players have a limit to how many cards with the same `name` can be included in a deck, generally 2. So if a decklist starts with 2 copies of card A and then replaces them with 2 copies of upgrade card A1, this is not necessarily a signal that card A is weak.

Note: cards A and A1 will have distinct `canonical_id`.

Upgrade families are defined **after** reprint canonicalization. Cards with different `canonical_id` but the same `name` may be upgrades, branches, or unrelated cards that share a name — the upgrade graph is built on `canonical_id` nodes, grouped by `name`, using `xp` and the rules in “Definition of a decklist containing an option”. Reprint merges (same fingerprint) happen **before** upgrade edges are drawn; upgrade tiers (different `xp`) are **never** merged into one `canonical_id`.

There are some edge cases to do with calculating XP cost of decklists:

- If the card has `exceptional=True`, then its actual XP cost is twice its `xp` field
- If the card has `myriad=True`, the XP cost of all of the card indices together is its `xp` field. (E.g., Card A3 is not myriad and has `xp=3`. If a decklist contains 2 copies of A3, then they cost a total of 6 XP. Card B2 is myriad and has `xp=2`. If a decklist contains 3 copies of B2, then they cost a total of 2 XP.)

Note: the `cost` field in each card json means something unrelated to XP cost.

# Taboo

Based on player experience, it was discovered after publication that a card is too powerful, rarely not powerful enough. The preferred approach is to alter the XP cost. A less common approach is to alter the text of the card. It is too difficult to parse if a change in wording makes a card significantly stronger or weaker. Instead, we will base our filtering on taboo XP cost, irrespective of wording changes.

The Taboo list is now up to version 10; all 10 are contained in `taboo.json`, which was fetched from the arkhamdb API. Players choose which taboo version to use for each decklist, which is stored in the `taboo_id` field. It is common for a decklist to built with taboo T when T was the most current version but, when newer versions of the taboo were released, players did not go back and update the decklist to fit the new taboo, so we cannot just ignore all decklists that do not have the current `taboo_id`.

For each `canonical_id`, check if its XP has been modified in the most recent taboo. A decklist only includes the current `canonical_id` if, according to the decklist's `taboo_id`, it paid at least that much XP for `canonical_id`. Treat missing `taboo_id` as **`0`** (no taboo list selected).

Example: Decklists A, B, C, and D contain card Z. The XP cost of card Z in the most recent taboo is 2 XP. Decklist A does not use a taboo while B, C, and D do. The XP cost of card Z in the `taboo_id` of B, C, and D are 1, 3, and 2, respectively. Then decklists C and D are considered to have the current card Z while decklists A and B do not. Furthermore, any decklists with `taboo_id` where card Z costs at least 2 XP are considered to be able to take card Z.

Our current approach will be to ignore all decklists where any of its cards are not the current version. Previous iterations tried to apply a soft weight to not throw out the entire decklist because of one card. For now, this spec plans to only use the hard filter.

# Customizable Cards

Some `card_id` are customizable. You can see code related to this in cell 6 of `prepare_arkham_data.ipynb`. All copies of `card_id` in a decklist should have the same `customizable_string`. We can think of this as a menu of upgrades. Each upgrade has its own XP cost. When a player pays the XP cost, they mark the upgrade on the menu, and now all copies of that `card_id` have the upgrade. Note that the XP cost is only paid once no matter how many copies of `card_id` are in the decklist.

# Deck Lineage

Two different lineage concepts:

**Copy / inspiration (not available).** Unlike Earthborne Rangers (`original_deck`), ArkhamDB does **not** link a decklist copied from another user's deck. We cannot weight decks that inspired others vs decks that copied others. No weighting for this.

**Same-user upgrade chains (available).** ArkhamDB sets `previous_deck` and `next_deck` when a user upgrades their own published deck. These form disjoint chains (no branching, no cross-user links). See Initial Cycle Data Prep (`user_weight`).

# Popularity Calculation

The general priciple we will use to calculate a card's popularity is to see what proportion of decklists that *could* contain it *do* contain it.

## Initial Card Data Prep

C1. Map `card_id` to `canonical_id`.

C2. Let `CanonicalCard.cycle` be the first publication order cycle among constituent `card_id`, or `None` if there is no ordered printing. 

C3. Identify decklist options:

- For non-customizable cards, construct an upgrade graph of `canonical_id` (see "Definition of a decklist containing an option" below).
- For customizable cards, identify the possible set of purchasable upgrades.

C4. For each option, calculate `xp` and `taboo_set`:

1. Create a mapping `taboo_index -> taboo_xp`. If the option is in `taboo_index`, use the XP cost in the taboo; otherwise fall back to the `xp` cost in `card_id = canonical_id`.
2. Let `CanonicalCard.xp` be its `taboo_xp` for the current taboo. Let `CanonicalCard.has_xp_cost = (xp > 0)`
3. Let `CanonicalCard.taboo_set` be the set of `taboo_index` where the `taboo_xp` is greater than or equal to `CanonicalCard.xp`. (Note: if the card is never in a taboo, then `taboo_set` should be the set of all `taboo_index`.)

## Initial Decklist Data Prep

For each decklist:

D1. Map its `investigator_front` and `investigator_back` to `Decklist.canonical_front` and `Decklist.canonical_back`. Simiilarly, for each `card_id` in `slots`, replace it with its `canonical_id`.

D2. Let `Decklist.cycle` equal the max over non-`None` `CanonicalCard.cycle` values in `slots`, **excluding** deckbuilding-requirement signatures (`deck_requirements.card` for `canonical_front`, all OR printings) and random basic weaknesses (`subtype_code = basicweakness`). `None` if every remaining slot is out-of-order.

D3. Let `Decklist.xp_cost` be the total XP cost of the decklist (reminder: customizable, exceptional, and myriad cases).

D4. Set `Decklist.is_ignore=False` if the `Decklist.taboo_id` is in every `CanonicalCard.taboo_set` in its `slots`; otherwise True.

## Initial Cycle Data Prep

Y1. Count decklists by (`user_id`, `canonical_front`, `canonical_back`). Let `Decklist.user_weight` = 1 / that count. This down-weights users who published many decklists for the same investigator (e.g., some users have duplicates of their own decklist).

    *(Optional future refinement: weight by upgrade chain using `previous_deck` / `next_deck`, giving each chain total weight 1. Legacy name: `chain_weight`.)*

Y2. For each `cycle`, consider all decklists with `Decklist.cycle = C`. Let `sum_user_weight` = Σ `Decklist.user_weight` over those decklists. Let `raw_cycle_weight[C] = 1 / sum_user_weight`.

Y2b. Enforce monotonicity: after computing `raw_cycle_weight`, let `Cycle.weight[C] = min(raw_cycle_weight[j] for j from C through MAX_CYCLE)`. This guarantees `Cycle.weight` is non-decreasing in `cycle`, so earlier cycles never receive a larger per-deck multiplier than later ones when `sum_user_weight` happens to be smaller at low cycles.

**What Y2 does and does not do:**

- **Y2 compensates for deck-count imbalance.** Each `Decklist.cycle = C` stratum contributes total weight 1.0, i.e., (Σ `user_weight` × `Cycle.weight` over decks in C) = 1. Middle cycles have more raw decklists than cycle 12, but without Y2 those extra lists would dominate pooled sums; Y2 prevents that.

- **Y2 does not compensate for composition drift across strata.** For fixed `CanonicalCard.cycle = k`, the expected slot share `b_C(k)` falls as `C` grows (e.g. cycle-2 is ~25% of slots at `Decklist.cycle = 3` but ~6% at `Decklist.cycle = 12` in a rough prior). Y2 gives strata 3 and 12 equal *total* weight, not equal *compositional* footing: lower-`C` strata are built from smaller pools, so older cycles occupy a larger fraction of each deck. Pooling eligible strata without further adjustment still mixes unlike deck environments.

- **Y2 does not prefer more informative strata.** If higher `Decklist.cycle` decks are better estimates of card utility (larger choice set), that requires B1 (`g(C)` increasing), not Y2.

Y3. **`Decklist.deck_xp_weight`** down-weights high-XP deck snapshots (upgrade-chain tips and standalone theorycraft). Let `XP_THRES` default to **29** (standalone construction breakpoint; configurable, e.g. 19). If `Decklist.xp_cost <= XP_THRES`, `deck_xp_weight = 1`; else `deck_xp_weight = XP_THRES / Decklist.xp_cost`. This is separate from Y1 (same-user duplicate lists) and does not replace P2 (`min_xp_cost` eligibility). Apply in `deck_weight` as `user_weight × Cycle.weight × deck_xp_weight` (and in `adjusted_deck_weight` via `deck_weight`).

## Bias compensation

Empirical analysis shows confounding beyond Y2 and P1 below:

1. **Core overhang** — cycle-1 slot share stays ~20–40% even at high `Decklist.cycle`.
2. **Investigator–cycle coupling** — `inv_cycle = Decklist.cycle` is ~2–3× more common than other investigators because players are selecting `cycle = C` investigators to play the `cycle = C` campaign.
3. **Per-deck novelty tilt** — some decks at `Decklist.cycle = C` over-use cycle-`C` cards; others do not. A single adjustment for all decks in stratum `C` is blunt.
4. **`Decklist.cycle = 7`** — starter-deck stratum is structurally different (many cycle-7 cards tuned to starter investigators). Cycle-7 **cards** must remain eligible for non–cycle-7 investigators; only the **deck stratum** is special.

Rejected approaches:

- **Global (C, I, k) normalization** — overfits sparse cells and penalizes genuinely strong cards (e.g. if cycle-9 cards are above-average, many decks will legitimately run more of them; shrinking all cycle-9 popularity to a stratum average would be wrong).
- **Exclude k = C slot copies** — invalid under P1: only `Decklist.cycle = 12` can include `CanonicalCard.cycle = 12` at all.

### B1. Weight toward high `Decklist.cycle` (`g(C)`)

Apply `g(C)` as a **per-deck multiplier** on the same footing as `user_weight`, `Cycle.weight`, and `deck_xp_weight`. Due to oversight, this was previously accidentally implemented as a post-hoc blend of per-stratum popularity rates.

After P1/P2 eligibility, each deck `d` with `Decklist.cycle = C` contributes weight:

$$
w_\text{deck}(d) = \text{user\_weight} \times \text{Cycle.weight} \times \text{deck\_xp\_weight} \times g(C) \times \text{inv\_adjust} \times \text{tilt}_d(k)
$$

where `inv_adjust` is from B2, `tilt_d(k)` from B3 for the option's card cycle `k`, and `g(C)` is increasing (default **`g(C) = C`**). Then, over all eligible decks in one pool:

$$
P3 = \sum_{d \in \text{eligible}} w_\text{deck}(d), \quad
P4 = \sum_{d \in \text{eligible},\,\text{has option}} w_\text{deck}(d), \quad
P5 = P4 / P3
$$

**Rationale:** decklists with higher `Decklist.cycle` draw from a larger card pool and are more informative about utility at the margin. This is separate from Y2: Y2 equalizes *within*-stratum contribution (`Cycle.weight`); `g(C)` then re-tilts the pooled sum toward high-`C` decks.

**Why not blend per-stratum `pop_C`?** Summing `g(C) \cdot P3_C` and `g(C) \cdot P4_C` is equivalent to the pooled formula above for P3/P4, but averaging stratum rates `P5_C = P4_C / P3_C` is **not** the same as `P4 / P3`. The pooled form matches the definition of P5 as a single weighted inclusion ratio (same pattern as `faction_select` / signature OR-groups: weight decks, then take the ratio).

**Per-stratum diagnostics:** optional `P3_C`, `P4_C`, `P5_C` for `Decklist.cycle = C` may still be computed for EDA (e.g. copy-count tables by cycle); they are not used to form reported P3/P4/P5.

**Choosing `g(C)` (Core dominance caveat):** `g(C) = C` and `g(C) ∝ N_C` (cumulative canonical player cards published through cycle `C`) are both monotone proxies for pool size. They correlate strongly (`N_12 / N_1 ≈ 14×` vs `12/1` for linear `C`), with cumulative-card weight slightly *more* aggressive at high `C`. Neither accounts for the fact that **cycle 1 occupies ~20–40% of slots at every `Decklist.cycle`**, so most of the incremental pool from `C−1` to `C` is *not* cycle-1 cards — yet `g(C)` weights the entire decklist observation, including its Core staples.

| `g(C)` | Pros | Cons |
|--------|------|------|
| `g(C) = C` | Simple, interpretable | Coarse; same weight rationale for Core staples and marginal cycle-`C` picks |
| `g(C) ∝ N_C` (cumulative cards) | Tied to published pool size | Overweights late strata for **cycle-1** cards (Core is already saturated in low-`C` decks, which are the natural habitat for measuring Core staples) |
| `g(C) ∝ N_C - N_1` (pool beyond Core) | Emphasizes post-Core choice expansion | Ignores that Core-vs-non-Core tradeoffs matter at high `C` too |
| `g_k(C) = 0` if `C < k`, else increasing | For a cycle-`k` card, zero weight below `C < k` (P1 already excludes those decks from eligibility; this flattens `g` among remaining strata) | Redundant with P1 unless `g` is defined per card cycle `k` |
| Moderate: `g(C) = √N_C` or cap `g(C)/g(C_min)` | Softens late-stratum dominance | Less principled |

**Practical recommendation:** start with **`g(C) = C`** (or `√N_C`) as a global default, but recognize that for **cycle-1 options** a flatter `g` (or card-specific `g_k`) may be more appropriate than aggressive late weighting. B3 tilt on `k = 1` partially addresses Core-overhang within each stratum without changing `g(C)`. Decide whether B1's goal is "meta at maximum pool" (favor high `C`) vs "typical usage at each era" (flatter `g`).

**Rejected:** $\text{pop}(\text{option}) = \sum_C g(C) \cdot \text{pop}_C(\text{option}) / \sum_C g(C)$ when `pop_C` is **P5** (or any rate). Use the pooled `P4/P3` form above instead.

### B2. Investigator–cycle reweighting

Let `P(inv_cycle = i | Decklist.cycle = C)` be the empirical fraction among non-ignored decks (with a floor on `P` when `i = C` to avoid division by zero). When a deck has investigator cycle `i`:

$$
w'_\text{deck} = w_\text{deck} \times \begin{cases}
1 & \text{if } i \neq C \\
\min \left(1, \dfrac{1/C}{P(i \mid C)}\right) & \text{if } i = C
\end{cases}
$$

Rationale: novelty coupling inflates **same-cycle** investigators (`i = C`) above a uniform `1/C` share. Down-weight those decks only; do **not** up-weight decks with `i != C` when older investigators are under-represented at stratum `C` (that would inflate legacy picks). Cap at 1 so under-represented same-cycle investigators are never boosted.

### B3. Per-deck novelty tilt (not per-card)

Fix a **structural reference composition** `b_C(k)`: expected fraction of slot copies from `CanonicalCard.cycle = k` **absent novelty skew** — pool spread plus Core basis only. Use (C, k) over (C, I, k). Novelty (extra cycle-`C` cards) is **not** baked into `b_C(C)`; decks that over-represent cycle `C` relative to this baseline are down-weighted via `tilt_d(C)` when scoring cycle-`C` cards.

Sources (in order of preference):

1. **Hand-set prior** (default):

   For `Decklist.cycle = C` (except the cycle-7 stratum row; see B4):

   $$
   b_C(k) = \frac{0.76/C + 0.22 \cdot I(k=1)}{0.98}
   $$

   where `I(B)` is 1 if `B` is true else 0. The numerator is the ~98% structural mass (uniform across cycles 1…C plus Core bump); divide by `0.98` so $\sum_{k=1}^{C} b_C(k) = 1$. The omitted ~2% corresponds to the empirical novelty share at cycle `C`, which tilt detects when `p_d(C) > b_C(C)`.

2. Column marginals from the `Decklist.cycle` × `CanonicalCard.cycle` pivot (Cell 5), with `Decklist.cycle = 7` as its own row — useful for calibration, not required if the prior is trusted.

3. **`inv_cycle × k` slices** — twelve tables `inv_cycle_pivots/inv_cycle_{D:02d}.csv` (rows `Decklist.cycle = C`, columns `k`; **published training pool**). Empirical **`b_{C,D}(k)`** for calibrating whether `b_C(k)` should absorb an **`inv_cycle`** ridge at `k = D` and era dips at `k ∈ {4,6,8}`. EDA: `prior_calibration_eda.py`, `export_inv_cycle_card_cycle_pivots.py`, **`estimate_b_c_d.py`** → `b_c_d_estimate.json`; findings in [research_notes.md](research_notes.md#card-cycle-prior-bc-dk-2026-06).

For deck `d` with `Decklist.cycle = C`, let `p_d(k)` = its slot-copy share from card cycle `k`. When deck `d` contributes to popularity of options whose cards have `CanonicalCard.cycle = k`:

$$
\text{tilt}_d(k) = \min \left(1, \frac{b_C(k)}{p_d(k)}\right) \\
w''_\text{deck} = w'_\text{deck} \times \text{tilt}_d(k) \quad \text{(for P3/P4 involving cycle-}k \text{ cards only)}
$$

Properties:

- Only **over**-representing decks are down-weighted; `tilt = 1` when `p_d(k) ≤ b_C(k)`.
- If cycle-9 cards are broadly strong, many decks sit near `b_C(9)` (structural share only) and keep full weight; only decks with **extra** cycle-9 share beyond the structural baseline are penalized.
- Tilt is **per deck**, so two decks at the same `Decklist.cycle` can receive different adjustments.
- Cycle-7 cards in a `Decklist.cycle = 10` deck use `b_{10}(7)`, not the cycle-7 stratum row.

**Tilt scope: all `k` vs only `k = C`?**

Apply `tilt_d(k)` when deck `d` contributes to popularity of **cycle-`k` cards** (always with `b_C(k)` where `Decklist.cycle = C`).

| | **Tilt all `k` (1 ≤ k ≤ C)** | **Tilt only `k = C` (diagonal)** |
|--|------------------------------|----------------------------------|
| **Targets** | Core overhang (`k=1`), novelty (`k=C`), and any mid-cycle skew | Novelty showcase decks only |
| **Pros** | One consistent rule; corrects Core-heavy decks when scoring cycle-1 cards; catches mid-cycle over-representation (e.g. cycle-7 salience in non-7 strata) | Minimal; avoids touching "normal" old-cycle usage; novelty at `k=C` is implicit (baseline excludes the ~2% novelty mass); less risk of punishing archetypes that legitimately run many cycle-2 cards |
| **Cons** | More priors to trust; small `b_C(k)` at high `C` for old `k` makes `p_d(k)` noisy (use a floor on `p_d(k)`); may down-weight synergy decks that *should* run extra copies of a cycle | Leaves Core overhang and mid-cycle skew to `g(C)` / B2 only; asymmetric (novelty adjusted, structural bias not) |
| **Strong cards** | If cycle-9 is genuinely strong, many decks have `p_d(9) ≈ b_C(9)` → `tilt = 1`; only outliers penalized | Same for `k=C`; other cycles never tilted |

**Practical recommendation:** implement **all-`k` tilt** with the hand prior above (and `p_d(k)` floor, e.g. treat `p_d(k) < ε` as `ε`). If results are too aggressive on mid/legacy cycles, fall back to **hybrid: tilt `k ∈ {1, C}` only** — Core basis + novelty, leave cycles 2…C−1 un-tilted.

**`b_{C,D}(k)` prior (optional, `arkham_popularity.py`):** load `b_c_d_estimate.json` via `ArkhamPopularityEngine(bcd_prior_path=...)` or `popularity_engine_kwargs(use_b_cd_prior=True)` (used in `prepare_arkham_data.ipynb` cell 7: `USE_B_CD_PRIOR` / `B_CD_TILT_SCOPE`). Tilt uses `b_{C,D}(k)` when `inv_cycle = D` is known; missing `(C,D)` cells fall back to the mean over available `D` at fixed `(C,k)`, then legacy `b_C(k)`. **Small-`b` safeguards** (both default to `1/30`, one slot in a 30-card deck):

- **`p_d(k)` floor** — caps tilt when observed share is tiny.
- **`b_{C,D}(k)` floor** — caps how aggressive tilt is when baseline mass is thin (tail interiors after `τ(D)` spread).
- **`tilt_scope="core_novelty"`** — skip tilt on mid cycles `2 … C−1`; use when all-`k` tilt is too twitchy.

### B4. `Decklist.cycle = 7` stratum

When `Decklist.cycle = 7`, use the cycle-7 row of `b_C(k)` for B3 tilt (starter-deck stratum is structurally different). Do **not** exclude cycle-7 cards from decks at other `Decklist.cycle`. Starter-tuned cards that are generically playable should still accrue popularity from `Decklist.cycle ≠ 7` decks at `b_C(7)` tilt.

### Combined deck weight

Bias-compensated popularity uses the full B1 formula in one pass (no separate stratum blend). With `C = Decklist.cycle` and card cycle `k`:

$$
w_\text{deck} = \text{user\_weight} \times \text{Cycle.weight} \times \text{deck\_xp\_weight} \times g(C) \times \text{inv\_adjust} \times \text{tilt}_d(k)
$$

`inv_adjust` from B2 (diagonal-only, capped at 1); `tilt_d(k)` from B3 when scoring cycle-`k` cards; `g(C)` from B1 (default `g(C) = C`).

## Popularity by Investigator

For a given (`canonical_front`, `canonical_back`) tuple, slice the decklists with that tuple and with `is_ignore=False` and do the following for each option:

P1. Slice all decklists with `Decklist.cycle >= CanonicalCard.cycle`. When `CanonicalCard.cycle` is `None` (out-of-order card), treat the card as available in **all** cycles: skip the cycle comparison and include every non-ignored decklist that has a defined `Decklist.cycle`.

P2. If `CanonicalCard.has_xp_cost`, further restrict the DataFrame to decklists where `Decklist.xp_cost >= min_xp_cost`. (See Implementation Notes about `min_xp_cost`)

P3. These are all the decklists that *could* include the option (P1/P2). Sum `w_deck` from B1 over eligible decks → **P3**.

P4. Similarly, sum `w_deck` over eligible decks that include the option → **P4**. See "Definition of a decklist containing an option" below.

P5. **P4 / P3** (single pooled ratio; do not average per-`Decklist.cycle` stratum rates).

Return P4, P3, and P5. `prepare_arkham_data.ipynb` does this as a DataFrame.

**Future EDA:** pairwise option **lift** \(P_5(A \cap B) / (P_5(A) \cdot P_5(B))\) per investigator — distinct `canonical_id`s, exclude deckbuilding requirements, top \(D^2\) pairs for deck size \(D\). See [research_notes.md — Option co-occurrence](research_notes.md#option-co-occurrence--lift-future-eda).

**Priority research (2026-06):** `inv_cycle` × `CanonicalCard.cycle` composition in training vs generated decks — see [research_notes.md — Priority: inv_cycle × CanonicalCard.cycle](research_notes.md#priority-invcycle--canonicalcardcycle-2026-06). EDA: `investigator_card_cycle_eda.py`.

Also create functions that display the most popular options with `CanonicalCard.has_xp_cost` and `not CanonicalCard.has_xp_cost`. The display should include the following:
   - `canonical_id`
   - `card_index`
   - Card `name`
   - For 1+ XP cards, `CanonicalCard.xp`
   - If the card occupies any slots, the slots it occupies
   - Result P4, the total weight of decklists that chose to include that option
   - Result P3, the total weight of decklists that could choose to include that option
   - Result P5, the popularity ratio

### Definition of a decklist containing an option

The general principle is that a decklist is considered to include that option if it uses that option or an upgraded version of that option. There are two subcases:

#### Non-customizable cards

For non-customizable cards, after reprint canonicalization, each `canonical_id` has a fixed `xp` and `name`. Cards with the same `name` are in the same upgrade family. Upgrade edges connect `canonical_id`s in the same `name`: strictly higher `xp` for linear upgrades; when different `canonical_id`s have the same `xp`, they either

- Are sibling branches upgraded from a lower-`xp` base
- Were put in different `canonical_id` because they have different text.

In either case, cards with the same `name`, same `xp`, and different `canonical_id` have no upgrade edge between them. Here are some examples:

- `canonical_id` A, A2, and A3 all have the same `name`. Card A has `xp=0`, A2 `xp=2`, and A3 `xp=3`. A2 and A3 are upgrades of A. A3 is an upgrade of A2.
- If `canonical_id` with the same `name` have the same `xp`, they are not upgrades of each other. Let `canonical_id` A00, A01, A20, and A21 all have the same `name`. Cards A00 and A01 have `xp=0` and A20 and A21 have `xp=2`. Then A20 and A21 are upgraded versions of both A00 and A01; A00 and A01 are not upgrades of each other; A20 and A21 are not upgrades of each other.

For non-customizable cards, options are a (`canonical_id`, `card_index`) tuple. A decklist contains option (`canonical_id`, `card_index`) if it contains `card_index` number of cards that are `canonical_id` or an upgrade of `canonical_id`. Examples:

- `canonical_id` A, A2, and A3 all have the same `name`. Card A has `xp=0`, A2 `xp=2`, and A3 `xp=3`. A decklist contains 1x A3 and 1x A2. The decklist contains (A, 1) and (A, 2) because A3 and A2 are both upgrades of A; the decklist contains (A2, 1) and (A2, 2) because A3 is an upgrade of A2 and there is another A2; the decklist contains (A3, 1) but not (A3, 2) because it has one A3 and no other card that is A3 or an upgrade of A3.
- `canonical_id` A, A20, and A21 all have the same `name`. Card A has `xp=0`, A20 and A21 `xp=2`. A decklist contains 1x A20 and 1x A21. The decklist contains (A, 1) and (A, 2) because A20 and A21 are both upgrades of A; the decklist contains (A20, 1) and (A21, 1) but neither (A20, 2) nor (A21, 2).

#### Customizable cards

We are interested in the popularity of each upgrade option. For upgrade options for customizable cards, there is no upgrade graph; either the decklist has the `card_id` and the upgrade option or it does not. For example, say customizable card X has upgrades Y and Z, and the following decklists all have X and the following upgrades:

- A: none
- B: Y
- C: Z
- D: Y, Z

Then decklists B and D have upgrade Y; decklists C and D have upgrade Z.

## Caveat

NOTE: Earlier versions of `prepare_arkham_data.ipynb` used concepts of group and pack index. A group corresponds to an option described above, that is each unique tuple of `groupby_cols` -- a set of column names identifing the option the player has chosen -- for the decklist. (To further complicate this, `prepare_arkham_data.ipynb` was created by combining two different sources that used different meanings of "group". Here, we refer to `groupby_cols` and not the group ID that estabilishes temporal order.) Pack index corresponds to `cycle` / `Decklist.cycle`, that is it divides time into ordered intervals and identifies to which interval the decklist or card belongs to. However, the nomenclature of groups is not intuitive, so this spec suggests new variable names.

## Implementation Notes

In each decklist json, the `slots` field contains a dictionary {`card_id`: int}, where the value is the number of copies of `card_id`; call this `num_copies`. A decklist contains (`card_id`, `card_index`) tuples for `card_index` from 1 up to and including `num_copies` (i.e., `range(1, num_copies + 1)`). Note that we do not need to refer to the `exceptional` or `myriad` values from the card json; during deck construction, `exceptional` and `myriad` are used to determine the legal number of copies of a card. We assume all the scraped decks are legal and use the `num_copies` specified in `slots`.

For now, use `min_xp_cost=1`. I am considering useing `min_xp_cost = CanonicalCard.xp` or some weighting the decklists depending on total XP cost. **`deck_xp_weight` (Y3)** provides soft down-weighting by total deck XP without changing P2 hard eligibility.

Previous iterations tried to filter out special cases such as weaknesses, enemies, treacheries, and signature cards. Such filters turned out to be imperfect. For this spec, include all cards the `slots` of the decklist.

Decklists also have a `sideSlots` field. These are not cards in the decklist but cards the user wants to make a note of, for example cards they want to buy in a future upgrade or cards that can be introduced to the deck via the Bonded mechanic. We ignore `sideSlots` and only concern ourselves with the cards actually in the decklist, which denoted in `slots`.

### Normalizing Cycles

Legacy: an older notebook applied a penalty based on the number of decklists in a cycle; `prepare_arkham_data.ipynb` implements the Y2 algorithm in this spec instead.

Legacy: The spec also once used the following to compensate for chained upgrades of decklists. This has been superceded by `user_weight`, which does something similar but also accounts for users that make multiple decklists for the same investigator.

Y1. Some decklists form upgrade chains identified by `previous_deck` and `next_deck`. Give each decklist an `Decklist.chain_weight` that is 1 over the number of decklists in its upgrade chain. For decklists not in a chain, consider it to be in a chain of 1 decklist.

Y2. For each `cycle`, find all decklist with `Decklist.cycle = cycle`. Let `sum_chain_weight` be the sum of `Decklist.chain_weight`. Let `Cycle.weight = 1 / sum_chain_weight`.

# Other Useful Functions

## Number of assets in each slot

Note: slot here means something different from the `slots` field in decklist json.

A card json may have a `slot` or `real_slot` field when the asset occupies one or more **asset slot types** (`Accessory`, `Ally`, `Arcane`, `Body`, `Hand`, `Head`, `Mask`, `Tarot` — note `Body` is a slot type name, not a generic term for all slots). Most assets use one slot; exceptions take 2 of one type or combinations (e.g. `Hand. Arcane`, `Hand x2`).

**Runtime patch (not saved to pickle):** After loading `card_json`, assets with the **Mask** trait and no `slot` / `real_slot` are patched in memory to `slot = real_slot = 'Mask'`. ArkhamDB omits a slot field for these cards, but the game limits each investigator to one Mask; treating Mask as an asset slot type lets Phase 1/2 enforce that limit like other slots.

For each (`canonical_front`, `canonical_back`) tuple:

1. For each of its decklists (same set of decklists in Popularity by Investigator), count **asset slot** usage by **assets** only (`type_code = asset`). E.g., if a decklist has 2 copies of a card that takes up 1 Hand slot, together they account for 2 Hand slots. Parse ArkhamDB `slot` / `real_slot`: split on `". "`, treat a trailing `" x2"` as doubling that slot type. **Bundled slot exceptions:** Sled Dog (`08127`) uses `ceil(N/2)` Ally slots for `N` copies; Uncanny Specimen (`11039`, max 3 copies) uses `ceil(N/3)` Arcane slots (1–3 copies → 1 slot).
2. For each slot type, calculate the weighted average using the same decklist weight as Investigator Popularity (I3/I4): `investigator_deck_weight` = `user_weight × Cycle.weight × deck_xp_weight × g(C) × inv_adjust` when bias compensation is on (no B3 tilt).

Implemented in `ArkhamPopularityEngine.slot_usage_for_investigator()`; notebook helper `show_slot_usage_for_investigator()`.

## Investigator Popularity

Within each `inv_cycle`, compare `(canonical_front, canonical_back)` choices. Investigator popularity reflects at least (1) perceived investigator strength and (2) interest in deckcrafting for that investigator as new cards enable new builds — see `research_notes.md` (priority: `inv_cycle` × card cycle).

I1. Let `inv_cycle` = `CanonicalCard.cycle` of `canonical_front` (the investigator card's first printing cycle).

For each `cycle` from 1 to `MAX_CYCLE`, and for each `(canonical_front, canonical_back)` with `inv_cycle = cycle`:

I2. Report **two pool slices** (same weight formula, different denominators):

- **Cohort pool (I2a):** all decklists with `Decklist.cycle >= cycle` and `is_ignore = False`. Answers: among players building with at least this investigator's release-era card pool, what share pick this investigator?
- **Global pool (I2b):** all non-ignored decklists with defined `Decklist.cycle`. Answers: what share of all weighted deck activity is this investigator?

**Caveat — `popularity_global` and promo investigators:** Some investigators were released first as **promotional** (or otherwise pre-cycle) printings before their campaign cycle. Their early ArkhamDB lists often have **`Decklist.cycle` below `inv_cycle`** — the deck’s max card cycle reflects the promo-era card pool, not the investigator’s eventual publication cycle. Those decks count in the **global** pool (and in the investigator’s numerator) but are excluded from the **cohort** pool (`Decklist.cycle >= inv_cycle`). `popularity_global` therefore tends to **overstate** such investigators relative to `popularity_cohort`. Keep computing `popularity_global` for diagnostics and future compensation (e.g. promo-era down-weighting or a minimum-`Decklist.cycle` floor per investigator); **use `popularity_cohort` (alias `popularity`) for primary comparisons** until a fix is defined.

I3. Per deck, `investigator_deck_weight` = `user_weight × Cycle.weight × deck_xp_weight`, multiplied by `g(C)` and `inv_adjust` (B1+B2) when `bias_compensation` is on. Do **not** apply B3 `tilt_d(k)` (no card cycle for an investigator tuple).

I4. **Cohort:** total cohort pool weight = Σ `investigator_deck_weight`; investigator cohort weight = Σ over decks with this tuple in the cohort pool. **Global:** same with the global pool.

I5. `popularity_cohort` = I4 cohort / I3 cohort; `popularity_global` = I4 global / I3 global. Legacy fields `popularity`, `pool_weight`, and `investigator_weight` remain aliases for the **cohort** metrics.

**EDA:** `investigator_decklist_cycle_distribution()` returns per-investigator `Decklist.cycle` counts and weights; CLI `investigator_decklist_cycle.py`. ArkhamDB `decklist_id` is chronological — use `min_decklist_id` / `max_decklist_id` per stratum to approximate when each cycle's card pool entered the dataset and to slice by era of list creation.

# Automatic Decklist Generation

**Plain language:** Build a synthetic 0 XP decklist for an investigator by following what the community actually plays. Resolve deck-size and class branches first, add required signatures, then pre-select popular **permanent** cards, derive **final deck size** and deckbuilding rules from that set, and compute **smoothed conditional slot averages** for phase targets. Fill popular assets until each slot type hits its targets, then fill remaining slots to **final deck size** with popular events/skills (and more assets if slot ceilings allow). Output is a display table like the popularity viewer, not a new scraped decklist.

**Status:** Implemented in `ArkhamPopularityEngine.generate_decklist()` including Phase 0.5 (permanent selection, `final_deck_size`, smoothed conditional `E[t]`). Slot-capacity enforcement during asset adds (e.g. Charisma +1 ally) remains deferred.

## Inputs

G0. **Card popularity** — 0 XP options from P1–P5 for `(canonical_front, canonical_back)`, sorted by P5 descending (`is_ignore=False` decks only). Uses full `adjusted_deck_weight` (B1+B2+B3) when `bias_compensation` is on.

G0b. **Slot averages** — per asset-slot type `t`, compute a **smoothed conditional** average `E[t]` (see *Conditional slot averages* below). Unconditional `E_all[t]` uses **`investigator_deck_weight`** (B1+B2, no B3) over all training decks for the investigator — same as Investigator Popularity (I3).

G0c. **Investigator rules** — `deck_requirements` and `deck_options` from the `canonical_front` investigator card in `card_json`. **Assumption:** rules are read from `canonical_front`; when front = back (typical case) this matches ArkhamDB. Parallel-only `(canonical_front, canonical_back)` tuples are out of scope for v1.

G0d. **Deck sizes:**

- **`deck_size`** — player-card target after resolving `deck_size_select` / `investigator_option` (base size for the Phase 0.5 popularity cutoff and for permanent deck-size deltas).
- **`final_deck_size`** — `deck_size` plus net modifiers from every permanent included in Phase 0.5 (and any other resolved deck-size rules). Phase 2 stops when non-permanent cards in the generated deck equal **`final_deck_size`**, not `deck_size`.

## Taboo: training vs generation

| Purpose | Taboo rule |
|---------|------------|
| Popularity / slot averages (training) | Existing D4: decklist `taboo_id` must be legal for every card in `slots`; else `is_ignore=True` and excluded from P3/P4 and slot averages. |
| Decklist generation (output) | Evaluate legality at **current taboo** (`MAX_TABOO`): hard-exclude **Forbidden** cards; apply taboo XP when considering 1+ XP cards (future). Wording-only taboo changes do not exclude 0 XP cards. |

Decklists that contain `08125` (*In the Thick of It*) remain in popularity training data. **Phase 0.5** may include `08125` when it meets the same conditions as other permanents (strictly above the player-card cutoff, legal at current taboo, allowed by base `deck_options`). The card is still **0 XP at current taboo** for generation eligibility; its **+3 XP deck-building budget** is **not** applied during 0 XP construction — defer spending that budget until the future 1+ XP upgrade phase.

## Investigator scope (v1 → v2)

**v1 (standard tree):** Original `(canonical_front, canonical_back)` pairs whose `deck_options` are only `faction` + `level` blocks.

**v2 (extended):** Also supports investigators whose `deck_options` use:

- `trait`, `tag`, `text`, `uses`, `type`, `not` filters
- Per-option `limit` counting (off-class caps, trait pools, …)
- `faction_select` resolved from weighted training-deck popularity (secondary class)
- `deck_size_select` resolved from weighted training-deck mode (e.g. Mandy 30/40/50)

Implemented in `arkham_deck_options.py` (`DeckOptionsValidator`, `resolve_deck_options()`).

### Resolving `faction_select` / `deck_size_select`

When an investigator’s `deck_options` include `faction_select` or `deck_size_select`, generation must pick one branch before building the deck. **Implementation decision (user-approved):** use the same decklist weights as popularity (`user_weight × Cycle.weight × deck_xp_weight` per `Decklist`), not raw card-copy totals.

For each `(canonical_front, canonical_back)` with training decks:

1. Compute `investigator_deck_weight` for every non-ignored training decklist (same B1+B2 stack as I3; no B3).
2. **`faction_select`:** For investigators with one secondary-class branch, pick the faction with the highest weighted total among decks whose `meta.faction_selected` matches a candidate (decks without meta do not vote). Tie-break: alphabetical faction name. **Dual class exception:** two `faction_select` blocks with ids `faction_1` / `faction_2` resolve jointly as one unordered class pair from `meta.faction_1` and `meta.faction_2` only. Diagnostics use `resolution_kind=faction_pair` with choices like `guardian+survivor`.
3. **`deck_size_select`:** Add each deck’s weight to its player-card-count bucket (among allowed sizes). Pick the size with the highest weighted total; tie-break: larger size.

**Diagnostics:** `export_generated_decklist_csvs(..., diagnostics=True)` also writes `generated/{name} {canonical_front} resolution.csv` listing each candidate choice, its `weighted_total`, `weight_share`, and whether it was `selected`.

**Explicit option variants:** pass `investigator_option` to `generate_decklist()` or `export_generated_decklist()` to build a specific branch instead of the popularity winner. When omitted, choices resolve from deck meta (`faction_1`/`faction_2` for dual class, `faction_selected` for secondary class) using decklist weights; decks without relevant meta do not vote. Supported forms:

- Dual class pair (Charlie Kane): `"guardian+survivor"` or `("guardian", "survivor")` or `{"faction_1": "guardian", "faction_2": "survivor"}`
- Secondary class: `"guardian"` or `{"faction": "guardian"}` / `{"secondary_class": "guardian"}`
- Deck size (Mandy): `40` or `{"deck_size": 40}`
- Combined (Mandy): `{"deck_size": 40, "faction": "rogue"}`

Variant exports add a suffix to filenames, e.g. `Charlie Kane 09018 guardian+survivor.csv`.

Resolve **`deck_size_select`** / **`investigator_option`** (and **`faction_select`** where applicable) **before** Phase 0.5 so **`deck_size`** is known for the permanent cutoff.

**Still deferred:**

- `option_select` trait branches (Marion Tavares, …)
- `atleast` multi-faction minimums (Lola Hayes, …)
- Parallel investigators as generation targets (`canonical_front != canonical_back`)
- Complex fan-content rules (`base_level`, `permanent`, …)

**Same algorithm, different deck size:** Non-30 base `deck_size` (33, 35, 40, …) — the Phase 0.5 cutoff and `final_deck_size` use the resolved base size for that investigator.

## Conditional slot averages

After Phase 0.5 selects a set of permanent cards `S`, slot targets use a **smoothed** average per slot type `t`:

1. **`E_all[t]`** — weighted average over **all** non-ignored training decks for `(canonical_front, canonical_back)` (same formula as `slot_usage_for_investigator()`).
2. **`E_S[t]`** — weighted average over training decks that **include every permanent in `S`** (deck permanent set ⊇ `S`; decks may contain additional permanents not in `S`). When `S` is empty, `E_S[t] = E_all[t]`.
3. **Weights:** `W_all` = total decklist weight in the all-decks pool; `W_S` = total weight in the ⊇ `S` pool (same `user_weight × Cycle.weight × deck_xp_weight` formula as popularity).
4. **Relative-mass interpolation** (investigator-relative; no global pseudocount):

   `λ = min(1, W_S / (ρ × W_all))`

   `E[t] = λ × E_S[t] + (1 − λ) × E_all[t]`

   **`ρ`** is a fixed fraction (implementation default e.g. `0.05`: trust `E_S` fully once ⊇ `S` decks account for at least 5% of investigator weight). When `W_S = 0`, use `E[t] = E_all[t]`.

   **Which slot types use `E_S`?**
   - **Deck-size permanents** in `S` (e.g. Forced Learning +15, Versatile +5): blend `E_S[t]` into **every** slot type `t`. Larger decks hold more assets on average in each slot category.
   - **Slot-capacity / composition permanents** (extra ally/accessory/arcane slot, Reliquary, On Your Own, …): blend only for the slot types they affect.
   - **Other permanents** (e.g. **In the Thick of It** — +3 XP at deck creation, **no** deck-size change): do **not** shift slot targets; use `E_all[t]`.

**Rationale:** `E` reflects both slot **capacity** and how an investigator is **played** (e.g. Hand usage often exceeds nominal capacity because deck slots compete on popularity). Conditioning on permanents in `S` shifts targets toward builds that actually take those cards; smoothing back to `E_all` avoids overfitting when few decks match. Superset matching (⊇ `S`) yields more training mass than exact-set equality while still requiring every selected permanent.

Apply `slot_phase_targets(E[t])` to the smoothed `E[t]` for phase 1 / phase 2 limits (see *Slot vectors and targets*).

## Slot vectors and targets

Parse each asset’s slot usage the same way as assets-in-each-slot: `asset_slot_counts()` — `. ` split, `" x2"` doubles that type; Sled Dog (`08127`) = `ceil(N/2)` Ally slots for `N` copies; Uncanny Specimen (`11039`) = `ceil(N/3)` Arcane slots. Phase 1/2 apply **marginal** increments when adding copies (`asset_slot_increment`). An asset maps to a **slot vector** `{t: copies}` over asset slot types `t` (possibly multiple types per card).

Let `current[t]` be asset-slot usage while building (starts at 0).

**Targets** from smoothed average `E[t]` (map via `slot_phase_targets()`):

| Name | Role | Rule |
|------|------|------|
| **phase1_goal** | Phase 1 stop: every slot `t` must reach at least this | Non-integer `E`: `floor(E)`; integer tie-break: `ceil(E − 1)` (or `0` when `E = 0`) |
| **phase1_cap** | Phase 1 max: do not add assets that would exceed this | Always `floor(E)` (spec Phase 1 inequality `current + v ≤ floor(E)`) |
| **phase2_ceiling** | Phase 2 max for assets | Non-integer `E`: `ceil(E)`; integer tie-break: `floor(E + 1)` |

Examples: `E = 1.8` → goal/cap/ceiling = `1/1/2`; `E = 2` → `1/2/3`; `E = 0` → `0/0/1`.

Apply targets to **global** `current[t]` (requirements count toward `current` before phase 1).

## Phase 0 — required signatures

Add all `deck_requirements.card` entries. Each entry is an **OR-group** when its value is a dict of interchangeable printings (e.g. Norman Withers: `08005` Livre d'Eibon **or** `98008` Split the Angle; `08006` The Harbinger **or** `98009` Vengeful Hound). Pick **one** card per group the same way as `deck_size_select` / `faction_select`: each training deck with exactly one printing from the group casts its full **`investigator_deck_weight`** to that choice; sum weights per alternative; pick the highest (tie-break by `canonical_id`). Decks with both or neither printing in the group are excluded from that group's pool. **Every** printing in every OR-group is a requirement id (does not count toward **`deck_size`** / **`final_deck_size`**, and Phase 2 must not add unchosen alternatives).

Single-code entries (no alternatives) behave as before. Copy count from `quantity` on the chosen card (default 1). Only **assets** among chosen signatures increment `current[t]` (per copy). Non-asset requirements (e.g. weaknesses) do not affect `current[t]`.

**Random basic weakness:** Omit from generated output (or use a placeholder only). Weakness is chosen at end of deck construction and does not affect slot-driven card selection.

## Phase 0.5 — select permanents

Run **after** resolving `deck_size_select` / `investigator_option` (so **`deck_size`** is known) and **after** Phase 0, **before** Phase 1.

Walk the 0 XP popularity list (P5 order). Count only cards that **count toward player deck size** (`counts_toward_player_deck_size`: not a signature/requirement, not a weakness, not a permanent). Skip rows already satisfied in the deck.

1. When the count reaches **`deck_size`**, the current row is the **cutoff** (a non-permanent card).
2. Include every **permanent** that appears **strictly above** the cutoff (earlier / more popular in the list). Do not include permanents at or below the cutoff.
3. A permanent is eligible only if legal at **current taboo** and under the investigator’s base **`deck_options`** (before merging permanent grants). Do not include forbidden or otherwise barred permanents.
4. Add each included permanent at one copy (typical). Recompute:
   - **`final_deck_size`** from included permanents (`effective_deck_size_from_slots()`).
   - **`deck_options`** = base options merged with permanent-granted options (`merge_deck_options_with_permanents()`).
   - Smoothed **`E[t]`** from the permanent set `S` (see *Conditional slot averages*).
5. Rebuild the deck-options validator from merged options and seeded Phase 0 slots.

**In the Thick of It (`08125`):** eligible in this step like any other permanent when it passes the cutoff and legality checks above. Inclusion does not enable 1+ XP purchases in v1.

**Phase 2 must not add further permanents** — Phase 0.5 is the only permanent-selection step.

**Hard composition rules** from included permanents must be enforced in all later phases (e.g. On Your Own — no ally-slot assets; Ancestral Knowledge — skill minimum; Underworld Support — singleton-by-title). **Occult Reliquary:** grants one movable slot among Hand / Accessory / Arcane; the player need not fix the slot at deck creation (it may be moved during play). For slot accounting, treat Reliquary as one flexible slot without forcing a branch at generation time.

**Still deferred (separate from Phase 0.5 selection), probably won't be needed:** slot-**capacity** enforcement during asset adds (e.g. Charisma +1 ally slot) — permanents are included and options merged, but asset slot limits during Phase 1/2 may not yet reflect capacity grants. Use `E[t]` instead.

**Shrewd Analysis + unidentified Seeker assets:** Phase 0.5 may include `04106` (*Shrewd Analysis*) without any matching `(Unidentified)` / `(Untranslated)` Seeker asset in Phase 1/2. See [research_notes.md — Shrewd Analysis](research_notes.md#shrewd-analysis-04106--unidentifieduntranslated-seeker-assets-not-yet-enforced).

## Phase 1 — fill slot floors (0 XP assets only)

Walk 0 XP asset options in P5 order. For each `(canonical_id, card_index)` not yet included:

- Must pass **deck_options** filter and **current-taboo** legality.
- Must respect **deck_limit** and name-level copy limits.
- **Customizable** cards: allowed at base, no customization indices, no XP upgrades.
- **Skip slotless assets:** Phase 1 only adds assets whose slot vector is non-empty (they consume at least one asset slot type). Other slotless assets (e.g. Safeguard) are deferred to Phase 2. Mask-trait assets without an ArkhamDB slot are patched to the Mask slot type at load time (see assets-in-each-slot).
- Let `v` = slot vector of one copy. Add if for **all** slot types `t`: `current[t] + v[t] ≤` **phase1_cap** (equivalently `≤ floor(E[t])` with integer tie-break).
- Stop phase 1 when every `t` has `current[t] ≥` **phase1_goal**, or the list is exhausted.

Multi-slot assets are allowed in phase 1 when the inequality holds for every coordinate (strict floor on global counts).

## Phase 2 — fill final deck size (0 XP)

Walk the **full** 0 XP popularity list (assets, events, skills). Skip options already included. **Do not add permanents** (already fixed in Phase 0.5).

- **Events / skills:** Does not interact with slot ceilings; each copy counts 1 toward **`final_deck_size`** unless `permanent=True`.
- **Assets:** Add only if for all `t`: `current[t] + v[t] ≤` **phase2_ceiling**.
- Stop when non-permanent cards in deck = **`final_deck_size`**, or list exhausted.

## Legality

Generated lists must be legal under `deck_options`, current-taboo forbidden/XP rules, and copy limits. Popularity training decks may be illegal under current taboo; those are already excluded via `is_ignore`.

## Output

Display table per generated deck (similar columns to `show_investigator_card_popularity`):

- `canonical_id`, `card_index` (or copy count), `name`, `cycle`, `slot`
- When 1+ XP cards are included (future): also `xp`

One generated list per in-scope `(canonical_front, canonical_back)` for v1.

**CSV export:** `export_generated_decklist_csvs()` writes `generated/{name} {canonical_front}.csv` for each supported investigator with training decks. Each file lists 0 XP popularity options through the last row with `included_in_generated=True`, with `p3_opportunity_weight`, `p4_choice_weight`, `p5_popularity`, `subname`, `included_in_generated`, and `generated_count` columns. Deck cards absent from the popularity list are appended at the end (P3/P4/P5 blank). Pass `diagnostics=True` to also write `{name} {canonical_front} resolution.csv` for `signature_select` / `faction_select` / `deck_size_select` weight calculations.

**Versioned updates:** `update_generated_decklist()` / `update_generated_decklist_csvs(changelog=...)` regenerate CSV(s), compare against the previous export on disk, and **prepend** to `generated/{name} {canonical_front} version.md` (create if missing):

1. The required `changelog` string (what changed in the generator/spec).
2. **Removed** — `(canonical_id, card_index) Name` options present before but not after.
3. **Added** — `(canonical_id, card_index) Name` options present after but not before.

Entries are separated by `---`. Diff keys off `included_in_generated=True` rows in the popularity export (one row per popularity option). Use this workflow instead of hand-diffing ArkhamDB imports when iterating on generation rules.

## Future: XP upgrades

Not in v1. Planned behavior:

- `08125` may already be included in Phase 0.5; when 1+ XP construction lands, apply its **+3 XP budget** then.
- Purchase 1+ XP options by popularity; **swap** out least popular eligible card (lowest P5), not add past deck size.
- Swap constraints: same-`name` limit, slot ceiling, legality.