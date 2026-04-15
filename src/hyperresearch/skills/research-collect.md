---
name: research-collect
description: >
  Enumerative coverage research. The user wants to know what exists, what
  happened, who did what — in full. Primary virtue is exhaustive per-entity
  coverage with every requested field. Sources are artifacts, official
  references, and anything that establishes ground truth on what's in the set.
---

# Collect Protocol

> You are in **collect** modality. The dispatcher routed you here because the output needs to enumerate a set of entities or facts, not advance a thesis. If the prompt said "for each X, provide Y / Z / W", the contract is clear: every X gets every field. If the prompt named a category without naming members, your job is to identify the significant members and cover them.

Read the dispatcher (`.claude/skills/hyperresearch/SKILL.md`) for the process. This file is the SUBSTANCE reference for collect.

---

## What collect is for

| Prompt shape | Why it's collect |
|---|---|
| "For each Napoleonic marshal, cover key campaigns, defeat, and death" | Per-entity field list |
| "Analyze the armor classes in Saint Seiya: for each significant character, provide power / technique / arc / fate" | Per-entity field list |
| "List the major infrastructure bills passed between 2020 and 2025 with their key provisions" | Enumerative scope |
| "What are all the endogenous opioid receptors and what does each do?" | Enumerative scope |
| "Survey the state capitals of India and their major industries" | Per-entity field list |

Collect is NOT for: "explain how X works" (synthesize), "which is best, X or Y" (compare), "will X happen in 2026" (forecast).

---

## Source strategy

Collect is **primary-source-heavy for the artifact itself, then secondary for the per-entity fields.**

**Ground truth (first priority):**
- Official / authoritative registries, directories, catalogs, databases — whatever lists the enumerable set
- The primary artifact itself (if the subject is a text, franchise, or body of work)
- For historical enumerations: primary documents, archival sources, official records
- For scientific enumerations: peer-reviewed classifications, reference databases (NCBI, ChEBI, PDB, etc.)

**Institutional signal (second priority):**
- Encyclopedia entries (Wikipedia, domain-specific wikis — these are load-bearing for collect because they often *are* the enumerable set)
- Reference books and field handbooks
- Academic reviews that enumerate and classify

**Practitioner triangulation (third priority):**
- Named practitioners who have catalogued the set (niche experts, fandom compilers, historical societies)
- Community-curated databases (TV Tropes, Fandom wikis, GitHub awesome-lists)

**Commentary (de-prioritized):**
- Listicles and "top N" posts are often derivative of the reference sources above. Use them only as leads, not as citations for per-entity facts.

### Academic sweep — only if peer-reviewed literature enumerates the set

Run Semantic Scholar / OpenAlex only if the enumerable set has a scholarly classification literature. For fictional / pop-culture / product / historical enumerations, skip it — the reference wikis and primary sources are the authoritative tier.

### Adversarial round — MANDATORY, run all three before proceeding

A collect report with no engagement with classification disputes is a transcription, not research. Run all three searches and **fetch at least one source that explicitly disputes the consensus list / classification**:

```
WebSearch("<topic> disputed contested membership classification")
WebSearch("missing from <consensus list> <topic> overlooked")
WebSearch("<topic> alternative classification non-mainstream taxonomy")
```

If the set has a "minor" / "non-canonical" / "rejected" / "lost" / "obscure" tier (e.g., apocryphal works, deprecated species, withdrawn standards), search for it explicitly and fetch one such source. The audit at Step 11 verifies at least one source flagged a missing or disputed member — a corpus that only contains consensus-list confirmations fails the comprehensiveness check.

Specific dispute patterns to watch for: members the consensus list omits, members whose membership is contested, members that get grouped differently in non-mainstream sources, ordering / hierarchy disputes within the set.

---

## Substance rules for Step 9 (writing)

These are the collect-specific rules that layer on top of the dispatcher's shared writing constraints.

### 1. The coverage contract is non-negotiable

If the prompt says "for each X, provide Y / Z / W", the draft must deliver every X with every field. If the prompt named 108 entities, the draft covers all 108. If the prompt said "each significant X", YOU define the significance threshold explicitly in the scaffold (e.g., "named in ≥2 primary sources" or "featured in a canonical arc"), state it in the opening, and then honor it without silent downgrades.

**Representative examples + thematic commentary is NOT a substitute for enumerative coverage.** If you cannot deliver the full set inside the draft, surface that to the user and ask — do not paper over it.

### 2. Proportionate depth across entities

Every entity the prompt asked about gets proportionate treatment. If Gold Saint #1 gets 200 words, Gold Saint #12 gets approximately 200 words. Deeply over-covering the famous entries and thin-covering the obscure ones is a violation — the prompt asked for "each", not "the ones you find interesting".

### 3. Structured entity treatment is allowed and expected

Collect is the one activity where **structured per-entity treatment** (including tight dossier-style subsections, roundup tables, or densely packed per-entity paragraphs) is the correct shape. You do NOT have to write full essayistic paragraphs for every entity. A per-entity subsection with clear field labels (technique, role, fate, outcome) and 2–4 sentences of prose per field is correct, efficient, and legible.

However: **dense roundup is not license for bullet-only listicles.** Each field still needs a sentence of context or consequence, not just a 3-word noun phrase. And the section as a whole still needs an opening orientation paragraph and a closing analytical beat — the per-entity dossier is flanked by interpretive framing, not presented raw.

### 4. Grouping is legitimate when the set is very large

For sets larger than you can cover with individual treatment (100+ entities), group by natural categorical structure (rank, era, region, function). Every entity still appears, but less-significant entities can share a subsection with shorter per-entity lines. The scaffold's coverage checklist records the grouping strategy; the auditor verifies every entity from the source set is accounted for.

### 5. Opening establishes the scope and the significance threshold

The opening answers: *what is the set you're enumerating, how did you define its boundaries, and what significance threshold did you apply*. A reader must understand in the first 200 words what "every X" means in this draft. If the set has disputed membership, the opening names the dispute and states your inclusion rule.

### 6. Closing synthesizes the set

The closing section (before the Opinionated Synthesis) draws out what the enumeration as a whole reveals. This is where a collect draft earns its analytical beat: what pattern does the full set expose? What does the coverage reveal that no single entity could? This is NOT a thesis replacement — the draft is primarily enumerative — but every corpus-level report should have one moment where the whole is more than the sum.

---

## Conformance checks (auditor reads this at Step 11, mode=conformance)

When the auditor runs in conformance mode on a collect draft, it applies these checks in order. Each is a PASS / FAIL with a one-line quote from the report or the vault.

(0) **Verbatim prompt check.** Open `research/scaffold.md` — does its first section contain the user's verbatim prompt (unchanged, not paraphrased)? FAIL if missing or modified.

(1) **Coverage contract check.** Read the scaffold's "What the user explicitly asked for" section. For each explicit entity or field requirement, verify the draft delivers it. If the user said "for each of 108 Specters provide techniques and fate", count the draft's Specter entries and verify every entry has both fields. FAIL if any entity or field is silently dropped.

(2) **Proportionate depth check.** Count substantive claims per entity across the draft (not raw word count — count assertions about the entity's attributes, actions, or fate). Flag any entity with less than ~50% the depth of the most-covered entity in the same category. FAIL if the draft over-develops the famous entries and thins the obscure ones.

(3) **Scaffold + comparisons + extract artifacts exist.** Run `$HPR search 'scaffold' -j`, `$HPR search 'comparisons' -j`, and `$HPR note list --tag extract -j`. All must return non-empty. FAIL otherwise.

(4) **Provenance chain.** Run `$HPR lint --rule provenance -j`. FAIL if any `--suggested-by` issues.

(5) **Analyst coverage.** Run `$HPR lint --rule analyst-coverage -j`. FAIL if the extract:source ratio is below 30%.

(6) **Opening scope + significance threshold.** Read the opening. Does it state what set is being enumerated, how boundaries were defined, and what significance threshold was applied? FAIL if any of the three is missing.

(7) **Corpus-level analytical beat.** Read the closing body section (not the Opinionated Synthesis). Does it draw out a pattern the full set reveals? FAIL if the closing is just a transition to synthesis without a substantive pattern claim.

(8) **Adversarial engagement.** Does the draft acknowledge at least one disputed / ambiguous / contested classification? FAIL if the enumeration is presented as uncontested when the adversarial search round found disputes.

(9) **Cross-source tension at least twice.** At least two body sections must put specific sources in tension with explicit "Source A says X; Source B says Y; I hold Z because..." structure. FAIL if the draft only cites, never contrasts.

Auditor output: list every violation with a one-line quote from the report. The parent agent applies fixes.
