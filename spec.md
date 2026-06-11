# Goal

The goal is identify the most popular cards used by various investigators in the customizable card game Arkham Horror: The Card Game. Players craft decklists that use a particular investigator and a deck of cards. A naive approach to calculate the popularity of a `card_id` for investigator (`canonical_front`, `canonical_back`) tuple is to find all decklists with (`canonical_front`, `canonical_back`) and sum the number of copies of `card_id` in those decklists. We will modify this approach to reflect various aspects of the game.

The following has similarities to `combined.ipynb` and `from_earthborne_rangers\prepare_data.ipynb` and an earlier version of `prepare_arkham_data.ipynb` but describes a new variation on the same idea.

# Data

The cells 2 and 4 in `combined.ipynb` are used to scrape decklist and card data, respectively, from the arkhamdb API. To avoid overloading the API, we load previously scraped data, request only the new data, and save the updated data as a pickle file. While the structure of decklist dict's are almost uniform, there are variations, so we save the raw data as a dict using pickle.

Only the scrapper functions are allowed to overwrite the pickled data. The functions that calculate popularity are forbidden from saving pickled data.

## Scraping and cleaning

- **Decklists:** scrape via `combined.ipynb` (cell 2) or equivalent; store as `{decklist_id: dict}` in `decklist_json.pickle`. Drop empty entries (`None`). Remove known joke decklists (`44599`, `43839`).
- **Cards:** scrape via `combined.ipynb` (cell 4); store as `{card_id: dict}` in `card_json.pickle`. (Done: ~~Re-scrape before canonicalization.~~)
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

When a player creates a decklist, they do not always consider all cards published to date. Typically, players will buy cycles in order and build decklists from the packs they own, i.e., players own cycles 1 through X and build decklists using cards from 1 through X. Let the `Decklist.cycle` of a decklist be the maximum ordered `cycle` among the `canonical_id`s it contains (ignore slots whose `CanonicalCard.cycle` is `None`). If every slot is out-of-order, `Decklist.cycle = None`. This creates a bias because players who have access to a larger pool of cards are more likely to make better decks.

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

D2. Let `Decklist.cycle` equal the max over its non-`None` `CanonicalCard.cycle` values in `slots`, or `None` if all are out-of-order.

D3. Let `Decklist.xp_cost` be the total XP cost of the decklist (reminder: customizable, exceptional, and myriad cases).

D4. Set `Decklist.is_ignore=False` if the `Decklist.taboo_id` is in every `CanonicalCard.taboo_set` in its `slots`; otherwise True.

## Initial Cycle Data Prep

Y1. Count decklists by (`user_id`, `canonical_front`, `canonical_back`). Let `Decklist.user_weight` = 1 / that count. This down-weights users who published many decklists for the same investigator (e.g., some users have duplicates of their own decklist).

    *(Optional future refinement: weight by upgrade chain using `previous_deck` / `next_deck`, giving each chain total weight 1. Legacy name: `chain_weight`.)*

Y2. For each `cycle`, consider all decklists with `Decklist.cycle = cycle`. Let `sum_user_weight` = Σ `Decklist.user_weight` over those decklists. Let `raw_cycle_weight[cycle] = 1 / sum_user_weight`.

Y2b. Enforce monotonicity: after computing `raw_cycle_weight`, let `Cycle.weight[cycle] = min(raw_cycle_weight[j] for j from cycle through `MAX_CYCLE`). This guarantees `Cycle.weight` is non-decreasing in `cycle`, so earlier cycles never receive a larger per-deck multiplier than later ones when `sum_user_weight` happens to be smaller at low cycles.

**What Y2 does and does not do:**

- **Y2 compensates for deck-count imbalance.** Each `Decklist.cycle = C` stratum contributes total weight 1.0 (Σ `user_weight` × `Cycle.weight` over decks in C = 1). Middle cycles have more raw decklists than cycle 12, but without Y2 those extra lists would dominate pooled sums; Y2 prevents that.

- **Y2 does not compensate for composition drift across strata.** For fixed `CanonicalCard.cycle = k`, the expected slot share `b_C(k)` falls as `C` grows (e.g. cycle-2 is ~25% of slots at `Decklist.cycle = 3` but ~6% at `Decklist.cycle = 12` in a rough prior). Y2 gives strata 3 and 12 equal *total* weight, not equal *compositional* footing: lower-`C` strata are built from smaller pools, so older cycles occupy a larger fraction of each deck. Pooling eligible strata without further adjustment still mixes unlike deck environments.

- **Y2 does not prefer more informative strata.** If higher `Decklist.cycle` decks are better estimates of card utility (larger choice set), that requires B1 (`g(C)` increasing), not Y2.

## Bias compensation

Empirical analysis shows confounding beyond Y2 and P1 below:

1. **Core overhang** — cycle-1 slot share stays ~20–40% even at high `Decklist.cycle`.
2. **Investigator–cycle coupling** — `inv_cycle = Decklist.cycle` is ~2–3× more common than investigator-pool share would predict.
3. **Per-deck novelty tilt** — some decks at `Decklist.cycle = C` over-use cycle-`C` cards; others do not. A single adjustment for all decks in stratum `C` is too blunt.
4. **`Decklist.cycle = 7`** — starter-deck stratum is structurally different (many cycle-7 cards tuned to starter investigators). Cycle-7 **cards** must remain eligible for non–cycle-7 investigators; only the **deck stratum** is special.

Rejected approaches:

- **Global (C, I, k) normalization** — overfits sparse cells and penalizes genuinely strong cards (e.g. if cycle-9 cards are above-average, many decks will legitimately run more of them; shrinking all cycle-9 popularity to a stratum average would be wrong).
- **Exclude k = C slot copies** — invalid under P1: only `Decklist.cycle = 12` can include `CanonicalCard.cycle = 12` at all.

### B1. Stratify by `Decklist.cycle`, weight toward high C

For each `Decklist.cycle = C`, compute popularity statistics P3/P4/P5 **within that stratum only** (still applying P1/P2 inside the stratum). Combine:

$$
\text{pop}(option) = \frac{\sum_C g(C) \cdot \text{pop}_C(option)}{\sum_C g(C)}
$$

where `g(C)` is increasing. Rationale: decklists with higher `Decklist.cycle` draw from a larger card pool and are more informative about utility at the margin. This is separate from Y2: Y2 equalizes *within*-stratum contribution; `g(C)` tilts the *between*-stratum blend.

**Choosing `g(C)` (Core dominance caveat):** `g(C) = C` and `g(C) ∝ N_C` (cumulative canonical player cards published through cycle `C`) are both monotone proxies for pool size. They correlate strongly (`N_12 / N_1 ≈ 14×` vs `12/1` for linear `C`), with cumulative-card weight slightly *more* aggressive at high `C`. Neither accounts for the fact that **cycle 1 occupies ~20–40% of slots at every `Decklist.cycle`**, so most of the incremental pool from `C−1` to `C` is *not* cycle-1 cards — yet `g(C)` weights the entire decklist observation, including its Core staples.

| `g(C)` | Pros | Cons |
|--------|------|------|
| `g(C) = C` | Simple, interpretable | Coarse; same weight rationale for Core staples and marginal cycle-`C` picks |
| `g(C) ∝ N_C` (cumulative cards) | Tied to published pool size | Overweights late strata for **cycle-1** cards (Core is already saturated in low-`C` decks, which are the natural habitat for measuring Core staples) |
| `g(C) ∝ N_C - N_1` (pool beyond Core) | Emphasizes post-Core choice expansion | Ignores that Core-vs-non-Core tradeoffs matter at high `C` too |
| `g_k(C) = 0` if `C < k`, else increasing | For a cycle-`k` card, only blend strata that could include it; e.g. Core popularity leans on low/mid `C` | More complex; separate blend per card cycle |
| Moderate: `g(C) = √N_C` or cap `g(C)/g(C_min)` | Softens late-stratum dominance | Less principled |

**Practical recommendation:** start with **`g(C) = C`** (or `√N_C`) for a global default, but recognize that for **cycle-1 options** a flatter `g(C)` (or `g_1(C)` that peaks in mid strata) may be more appropriate than aggressive late weighting. B3 tilt on `k = 1` partially addresses Core-overhang within each stratum without changing `g(C)`. Decide whether B1's goal is "meta at maximum pool" (favor high `C`) vs "typical usage at each era" (flatter `g`).

### B2. Investigator–cycle reweighting

Let `P(inv_cycle = i | Decklist.cycle = C)` be the empirical fraction among non-ignored decks (or a smoothed prior). When a deck has investigator cycle `i`:

$$
w'_\text{deck} = w_\text{deck} / P(i \mid C)
$$

(optionally cap the divisor to avoid exploding weight for rare pairs). Rationale: down-weight decks that are "expected" from novelty coupling (playing the new cycle's investigator) relative to decks that are not.

### B3. Per-deck novelty tilt (not per-card, not (C, I, k))

Fix a **structural reference composition** `b_C(k)`: expected fraction of slot copies from `CanonicalCard.cycle = k` **absent novelty skew** — pool spread plus Core basis only. Use **(C, k)** only — never (C, I, k). Novelty (extra cycle-`C` cards) is **not** baked into `b_C(C)`; decks that over-represent cycle `C` relative to this baseline are down-weighted via `tilt_d(C)` when scoring cycle-`C` cards.

Sources (in order of preference):

1. **Hand-set prior** (default):

   For `Decklist.cycle = C` (except the cycle-7 stratum row; see B4):

   \[
   b_C(k) = \frac{0.76/C + 0.22 \cdot I(k=1)}{0.98}
   \]

   where `I(x)` is 1 if `x` is true else 0. The numerator is the ~98% structural mass (uniform across cycles 1…C plus Core bump); divide by `0.98` so \(\sum_{k=1}^{C} b_C(k) = 1\). The omitted ~2% corresponds to the empirical novelty share at cycle `C`, which tilt detects when `p_d(C) > b_C(C)`.

2. Column marginals from the `Decklist.cycle` × `CanonicalCard.cycle` pivot (Cell 5), with `Decklist.cycle = 7` as its own row — useful for calibration, not required if the prior is trusted.

For deck `d` with `Decklist.cycle = C`, let `p_d(k)` = its slot-copy share from card cycle `k`. When deck `d` contributes to popularity of options whose cards have `CanonicalCard.cycle = k`:

\[
\text{tilt}_d(k) = \min\!\left(1,\; \frac{b_C(k)}{p_d(k)}\right)
\]

\[
w''_\text{deck} = w'_\text{deck} \times \text{tilt}_d(k) \quad \text{(for P3/P4 involving cycle-}k \text{ cards only)}
\]

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

### B4. `Decklist.cycle = 7` stratum

Treat `Decklist.cycle = 7` as a separate stratum in B1 (its own `pop_7`, own `b_7(k)` prior). Do **not** exclude cycle-7 cards from other strata. Starter-tuned cards that are generically playable should still accrue popularity from `Decklist.cycle ≠ 7` decks at `b_C(7)` tilt.

### Combined deck weight

\[
w_\text{deck} = \text{user\_weight} \times \text{Cycle.weight} \times \text{inv\_adjust} \times \text{tilt}_d(k)
\]

with `inv_adjust = 1 / P(inv_cycle | Decklist.cycle)` from B2 and `tilt_d(k)` from B3 when scoring cycle-`k` cards. Apply B1 when aggregating across `Decklist.cycle` after per-stratum P5.

## Popularity by Investigator

For a given (`canonical_front`, `canonical_back`) tuple, slice the decklists with that tuple and with `is_ignore=False` and do the following for each option:

P1. Slice all decklists with `Decklist.cycle >= CanonicalCard.cycle`. When `CanonicalCard.cycle` is `None` (out-of-order card), treat the card as available in **all** cycles: skip the cycle comparison and include every non-ignored decklist that has a defined `Decklist.cycle`.
P2. If `CanonicalCard.has_xp_cost`, further restrict the DataFrame to decklists where `Decklist.xp_cost >= min_xp_cost`. (See Implementation Notes about `min_xp_cost`)
P3. These are all the decklists that could include the option. Calculate the total weight of these decklists. Base weight is `Decklist.user_weight * Cycle.weight` (Y1/Y2). With bias compensation enabled, multiply by `1 / P(inv_cycle | Decklist.cycle)` (B2) and `tilt_d(k)` for the option's card cycle `k` (B3). Compute P3/P4/P5 **within each `Decklist.cycle` stratum**, then blend strata with `g(C) = C` (B1).
P4. Similarly, calculate the total weight of the decklists that include the option. See "Definition of a decklist containing an option" below.
P5. An option's popularity is P4=(weight of decklists with it) over P3=(weight of decklists that had the opportunity to use it).

Return P4, P3, and P5. `prepare_arkham_data.ipynb` does this as a DataFrame.

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

NOTE: `prepare_arkham_data.ipynb` uses concepts of group and pack index. A group corresponds to an option described above, that is each unique tuple of given column names identifies the option the player has chosen for the decklist. (To further complicate this, `prepare_arkham_data.ipynb` was created by combining two different sources that used different meanings of "group". Here, we refer to `groupby_cols` and not the group ID that estabilishes temporal order.) Pack index corresponds to `cycle` / `Decklist.cycle`, that is it divides time into ordered intervals and identifies to which interval the decklist or card belongs to. However, the nomenclature of groups is not intuitive, so this spec suggests new variable names.

## Implementation Notes

In each decklist json, the `slots` field contains a dictionary {`card_id`: int}, where the value is the number of copies of `card_id`; call this `num_copies`. A decklist contains (`card_id`, `card_index`) tuples for `card_index` from 1 up to and including `num_copies` (i.e., `range(1, num_copies + 1)`). Note that we do not need to refer to the `exceptional` or `myriad` values from the card json; during deck construction, `exceptional` and `myriad` are used to determine the legal number of copies of a card. We assume all the scraped decks are legal and use the `num_copies` specified in `slots`.

For now, use `min_xp_cost=1`. I am considering useing `min_xp_cost = CanonicalCard.xp` or some weighting the decklists depending on total XP cost.

Previous iterations tried to filter out special cases such as weaknesses, enemies, treacheries, and signature cards. Such filters turned out to be imperfect. For this spec, include all cards the `slots` of the decklist.

Decklists also have a `sideSlots` field. These are not cards in the decklist but cards the user wants to make a note of, for example cards they want to buy in a future upgrade or cards that can be introduced to the deck via the Bonded mechanic. We ignore `sideSlots` and only concern ourselves with the cards actually in the decklist, which denoted in `slots`.

### Normalizing Cycles

`combined.ipynb` applied a penalty based on the number of decklists in a cycle while `prepare_arkham_data.ipynb` implements a new algorithm that does not. The above describes a third algorithm.

Legacy: The spec once used this. This accounts for number of cards published up to the cycle but not for more decklists being made for lower cycles.

1. For each cycle, find the number of cards with the same `CanonicalCard.cycle`.
2. For each cycle, calculate the cumulative number of cards published in all cycles up to it. Then let `Cycle.weight` equal to its cumulative counts normalized so that `MAX_CYCLE` (currently 12) has `Cycle.weight=1`.

Legacy: The spec also once used this. This has been superceded by `user_weight`, which does something similar but also accounts for users that make multiple decklists for the same investigator.

Y1. Some decklists form upgrade chains identified by `previous_deck` and `next_deck`. Give each decklist an `Decklist.chain_weight` that is 1 over the number of decklists in its upgrade chain. For decklists not in a chain, consider it to be in a chain of 1 decklist.
Y2. For each `cycle`, find all decklist with `Decklist.cycle = cycle`. Let `sum_chain_weight` be the sum of `Decklist.chain_weight`. Let `Cycle.weight = 1 / sum_chain_weight`.

# Other Useful Functions

## Number of assets in each slot

Note: slot here means something different from the `slots` field in decklist json.

See cell 13 in `combined.ipynb`. A card json may have a `slot` field, indicating limited capacity that it takes up. I believe there are now 7 different slots: 'Accessory', 'Ally', 'Arcane', 'Body', 'Hand', 'Hat' and 'Tarot'; we should double check that. Most items that take a slot only take up 1, but there are exceptions that can take up 2 Hands, 2 Arcane, or combinations of multiple types.

For each (`canonical_front`, `canonical_back`) tuple:

1. For each of its decklists (same set of decklists in Popularity by Investigator), count the number of slots of each type used by all of its cards. E.g., if a decklist has 2 copies of a card that takes up 1 Hand slot, together they account for 2 Hand slots.
2. For each slot type, calculate the weighted average using the same decklist weight as Popularity by Investigator: `Decklist.user_weight * Cycle.weight` for `Decklist.cycle`.

## Investigator Popularity

Within each cycle, we want to compare the popularity of `(canonical_front, canonical_back)` choices. This is analogous to "Popularity by Investigator":

I1. Let `inv_cycle` = `CanonicalCard.cycle` of `canonical_front` (the investigator card's first printing cycle).

For each `cycle` from 1 to `MAX_CYCLE`, and for each `(canonical_front, canonical_back)` with `inv_cycle = cycle`:

I2. Slice all decklists with `Decklist.cycle >= cycle` and `is_ignore = False`.
I3. Total weight of those decklists = Σ (`Decklist.user_weight` × `Cycle.weight` at `Decklist.cycle`).
I4. Total weight of decklists using this `(canonical_front, canonical_back)` tuple (same slice, same weight formula).
I5. Popularity = I4 / I3.

## Decklist Scrapper

Given `MAX_DECKLIST_ID`, use the arkhamdb API to scrape public decklists we have not already scraped and update the pickle (or save a new file). Note that even when limiting requests to 1 per second, arkhamdb sometimes will stop responding.

Also, we can check if a decklist is legal by checking it follows the `exceptional` and `myriad` keywords. However, a card's text can also change the maximum number of copies allowed in a deck, so it is difficult to make this error-proof.

# Action Items

- Re-scrape arkhamdb **card** data **only once**; verify pack list against API (`/api/public/packs/`)
- Implement `card_id` → `canonical_id` per fingerprint + `duplicate_of_code` rules above; add unit tests for confirmed cases (Physical Training, Sure Gamble, Evidence!/Cherished Keepsake upgrades, Tekeli-li ×7, FGG branches, Agatha fronts/backs, taboo placeholders)
- Implement `investigator_front` / `investigator_back` → `canonical_front` / `canonical_back`
- Remove manual `merge_cards` dict once algorithm is validated
- Map ordered `pack_code`s → `cycle` (split expansion packs, Return packs, Core); leave Side Stories / Promotional / Parallel / unknown packs as `None`