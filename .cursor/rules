# User Background

User has a data analysis background, not software engineering. Prefer simple data structures over abstractions. Explain architectural decisions as if talking to someone who thinks in dataframes and SQL, not class hierarchies.

# Clarification

If a requirement seems underspecified, ask a clarifying question before implementing.

“Underspecified” includes: the spec names a feature but not the resolution rule, weighting, or stop condition. Naming a feature in the spec is not the same as approving an implementation.

# Implementation decisions

Distinguish **what** (required behavior) from **how** (algorithm, heuristics, tie-breaks, defaults).

Before writing code, get explicit user approval when the spec (or user) defines *what* but not *how*, including:

- Inference rules (e.g. picking secondary class, deck size, or branch from training data)
- Aggregation choices (raw counts vs decklist weight vs user weight only)
- Tie-breaks and fallbacks when data is missing or tied
- Scope expansions beyond the current spec milestone (e.g. implementing a “deferred” item)

**Do not** pick a reasonable default and implement it. Instead:

1. State 2–3 concrete options in plain language (dataframe/SQL analogy if helpful)
2. Recommend one briefly
3. Wait for user choice before coding

If the user says “proceed” without choosing, ask once more with a default labeled **“proposed default — confirm?”**

# Updating Spec

When making a decision not explicitly covered by the spec, flag it rather than silently resolve it.

If code written during development contradicts or outgrows spec, flag the discrepancy to be resolved in the spec rather than Cursor silently updating the spec to match the code.

# Cursor Responsibilities

Spec updates can include terse, technical language easy for Cursor to parse but accompany it with a plain language translation. Similarly, dense code blocks should have inline comments clarifying intent and/or approach.

When Cursor updates specs:

- **Important:** If a spec update resolves an ambiguity that the user never explicitly decided, flag it as an assumption rather than stating it as fact.
- record what technical decisions were made
- what approach was chosen and why
- constraints and complications that emerged during development
- factual record of what currently exists
- data structure definitions and function signatures, where appropriate

When extending a “spec only” or “defer” item into code:

1. Propose the algorithm in chat first (inputs, formula, edge cases, diagnostics).
2. Update spec with the **assumption** wording.
3. Implement only after user confirms (or explicitly says “use your recommendation”).

## Example: deck_options resolution

Bad: “Resolve `faction_select` from training decks by counting off-class copies.”

Good: Implementation requires resolving `faction_select` but spec does not specify how. Options: (A) raw copy totals, (B) decklist weight with per-deck proportional split, (C) plurality of decks by dominant off-class. Which should we use?”

# User Responsibilities

User has complete control over `.cursor/rules`. Cursor may suggest changes but may not directly make edits.

User has ultimate control over the following; do not update these sections yourself. Cursor may draft changes in agent chat but explicitly prompt the user to address them before continuing:

- priorities and questions being asked
- what done looks like for current version
- Open Questions / Known Unknowns section

# Jupyter / Imports

The IPython notebook kernel keeps stale modules and old class instances.

- Use a module to reload modules in dependency order.
- Make sure the notebook recreates existing instances, which are not updated by reloading modules.