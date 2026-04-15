---
name: research-compare
description: >
  Comparative evaluation research. The user wants to know which option is
  better for what, how alternatives differ, and which one to pick. Primary
  virtue is proportionate per-entity depth plus a committed recommendation.
  Covers vendor scans, tool evaluations, approach selection, and any
  prompt that names multiple alternatives.
---

# Compare Protocol

> You are in **compare** modality. The dispatcher routed you here because the output needs to evaluate N alternatives against each other and commit to a recommendation. The reader leaves knowing which option to pick and why, plus the conditions under which alternatives win.

Read the dispatcher (`.claude/skills/hyperresearch/SKILL.md`) for the process. This file is the SUBSTANCE reference for compare.

---

## What compare is for

| Prompt shape | Why it's compare |
|---|---|
| "TigerBeetle vs Postgres vs FoundationDB for write-heavy workloads" | Named alternatives, explicit comparison |
| "Which JavaScript framework should I pick for a new SaaS startup" | Unnamed set, evaluation ask |
| "How does Kubernetes compare to Nomad for stateful workloads" | Two named alternatives |
| "What's the best reinforcement learning approach for robotic manipulation" | Named alternatives, selection ask |
| "Compare TLS 1.3 with QUIC for mobile apps" | Two named alternatives, comparison ask |

Compare is NOT for: "what exists" (collect), "explain how X works" (synthesize), "will X win" (forecast — if the ask is future-tense).

**Two variants:**
1. **market-scan** — entity set is discovered through research (the user asked about a space, not specific alternatives)
2. **comparison** — entity set is named explicitly in the prompt

Both use this file. The variants differ only in how you acquire the entity list.

---

## Source strategy

Compare is a **3-tier source hierarchy** that privileges the artifact itself, then authoritative synthesis, then practitioner reality checks.

### Ground truth (first priority — fetch for every entity)

- Official product / project pages, feature lists, pricing pages, API documentation, release notes
- Company filings, official announcements, specs
- Benchmark results (both official and independent)
- Source code / README / architecture docs for open-source entities
- Standards documents (RFC, ISO, IEEE) when the entities implement a standard

**For comparison variant:** fetch ground-truth sources for EACH named entity before moving to Tier 2. Imbalanced ground-truth coverage (entity A has 5 primary sources, entity B has 1) propagates to imbalanced body sections later.

### Institutional signal (second priority)

- Authoritative analyst reports and research firm writing
- Named expert reviews and long-form evaluations by recognized practitioners
- Academic / technical papers when the comparison is between methods rather than products
- Industry benchmarking bodies and standards organizations

**Paywall fallback:** when reports are gated: (1) search for "[report title] key findings"; (2) look for press coverage of the report; (3) find earlier free editions; (4) check the organization's free-publications section.

### Practitioner triangulation (third priority)

- Named practitioner postmortems and migration reports (the most honest signal in the ecosystem)
- Conference talks with transcripts (by practitioners who built the thing, not evangelists)
- StackOverflow canonical answers (accepted + high-upvote)
- Community threads (Hacker News, Reddit, Lobste.rs) on specific failure modes
- User reviews on professional review sites (not single-line "it's great" reviews)

### Commentary (load-bearing only for reception, not facts)

- News articles about product launches
- Blog summaries by authors who haven't used the thing
- Listicles

Never use commentary as the sole source for a factual claim about an entity. Use it only to characterize positioning or reception.

### Adversarial round — MANDATORY, run all four before proceeding

Required — specifically for the market leader. A compare report without at least one source critical of the dominant entity is advocacy, not evaluation. **Fetch at least one source that explicitly criticizes the leading entity** (a postmortem, a "why we migrated away" blog, a dissenting analyst report, a public outage retrospective, a regulatory complaint).

```
WebSearch("<market-leader entity> problems limitations")
WebSearch("<market-leader entity> alternatives why leave")
WebSearch("moving away from <market-leader entity>")
WebSearch("<method A> vs <method B> when <method A> wins")
```

The audit at Step 11 verifies at least one body section engages the critique with substance. A compare draft that recommends X without engaging "people who tried X and switched to Y" lacks the experiential evidence that distinguishes a real evaluation from a marketing summary.

For symmetric comparisons (no clear leader, e.g., "Postgres vs MySQL"), run the adversarial searches against EACH entity — every option must have at least one critical voice in the corpus.

### Academic sweep — only when comparing methods, not products

If the comparison is between academic methods, algorithms, or theoretical approaches (e.g., "PPO vs SAC for continuous control"), run Semantic Scholar first. If the comparison is between products or services, skip the academic sweep and go straight to vendor docs + analyst reports.

---

## Substance rules for Step 9 (writing)

These are the compare-specific rules that layer on top of the dispatcher's shared writing constraints.

### 1. Scoring dimensions declared upfront

The opening establishes WHICH dimensions the entities will be evaluated on — and WHY those dimensions matter for the user's question. "Throughput", "correctness guarantees", "operational complexity", "ecosystem maturity" are dimensions; "performance" alone is not. Dimensions should reflect where the entities actually differ, not generic attributes.

A compare draft with undeclared or arbitrary dimensions is a set of entity descriptions pretending to be an evaluation. Declare them first; score against them throughout.

### 2. Proportionate depth per entity is the PRIMARY substance rule

Every entity named in the prompt (or discovered during market-scan) gets proportionate body coverage. If entity A has a 1,200-word section and entity B has a 400-word section, rebalance — either expand B's coverage or trim A's.

**This rule holds regardless of section structure.** Whether the draft has per-entity sections, per-dimension sections, clustered sections, or prose-embedded comparisons, count substantive claims per entity across the whole body. If one entity ends up with half the coverage of another, the research was lopsided, not the draft.

### 3. A mandatory comparison matrix

Somewhere in the body there is a table (or equivalent structured view) that places every entity against every scoring dimension. This is non-negotiable — no compare draft is complete without it. If the prompt requests prose comparison over a table, the matrix can be rendered as a structured prose section ("On throughput: A leads with X; B follows at Y; C lags at Z because..."), but every entity must be parseable on every dimension in a single view.

If a dimension cannot be scored for an entity (e.g., a private company with no public pricing), note the gap and explain why. Do not silently omit cells.

### 4. A committed recommendation

Compare drafts MUST end with a committed pick: "For [primary use case], use X because [reason]. For [condition A], Y wins because [reason]. For [condition B], Z wins because [reason]." "It depends" alone is not acceptable — it must be followed by the conditions that determine the answer.

The recommendation is a claim the reader can act on, not a balanced list.

### 5. Entities in tension, not in isolation

Body sections must put entities in direct tension: "A and B both claim to handle C; the difference is that A does C1 well while B does C2 well." A draft that describes each entity in isolation and then synthesizes at the end is missing the comparative substance that justifies the modality.

### 6. Opening establishes the question the evaluation answers

What is the user trying to decide? The draft frames this explicitly in the opening, then every body section is a step toward that decision. The opening is NOT a description of the first entity — it is the problem statement + the dimensions the solution will be scored on.

### 7. Entity sections open with mechanism, then method

For each entity: first explain what it IS and HOW it works (mechanism), then what you DO with it (method / usage / interface). Readers evaluate alternatives best when they understand the underlying model, not just the surface API.

### 8. Honest about maturity asymmetry

If the entities have dramatically different maturity (A has 10 years of production use and benchmarks; B is a 2024 research prototype with no independent replication), flag this explicitly in the opening AND in each affected section. Treating asymmetric alternatives as if they were evenly characterized is a form of dishonesty — the reader needs to know the evidence bases are uneven.

---

## Conformance checks (auditor reads this at Step 11, mode=conformance)

(0) **Verbatim prompt check.** Open `research/scaffold.md` — does its first section contain the user's verbatim prompt (unchanged)? FAIL if missing or modified.

(1) **All prompt-named entities appear.** If the prompt named specific entities, every one must appear in the draft with substantive coverage. FAIL if any named entity is missing or relegated to a passing mention.

(2) **Scoring dimensions declared.** Read the opening. Are the comparison dimensions named and their relevance explained? FAIL if dimensions are undeclared or arbitrary.

(3) **Proportionate depth per entity.** Count substantive claims per entity across the whole body. Flag any entity with less than ~50% the depth of the most-covered entity. FAIL if the draft over-develops one entity and thin-covers others.

(4) **Comparison matrix present.** Find the matrix (table or structured prose). Verify every entity is scored on every declared dimension. FAIL if the matrix is missing, incomplete, or present only as a synthesis afterthought.

(5) **Committed recommendation.** Read the recommendation section. Does it commit to a specific pick for the primary use case? If it uses "it depends", does it immediately enumerate the conditions and their answers? FAIL if the draft hedges without committing.

(6) **Entities in tension.** Count body sections where entities are put in direct tension (not described in isolation). FAIL if fewer than two — isolation descriptions are not comparisons.

(7) **Adversarial engagement with the market leader.** Find sources critical of the dominant entity. Is the draft's body engaging with those critiques, or is the recommendation a consensus echo? FAIL if there is zero engagement with dissent on the leader.

(8) **Scaffold + comparisons + extract artifacts exist.** Run `$HPR search 'scaffold' -j`, `$HPR search 'comparisons' -j`, `$HPR note list --tag extract -j`. All non-empty. FAIL otherwise.

(9) **Provenance chain.** Run `$HPR lint --rule provenance -j`. FAIL if any issues.

(10) **Analyst coverage.** Run `$HPR lint --rule analyst-coverage -j`. FAIL if below 30%.

(11) **Mechanism-before-method per entity.** Sample 3 entity sections. Does each open with mechanism (what it is, how it works) before method (how to use it)? FAIL if sections jump straight to usage without the underlying model.

(12) **Maturity asymmetry flagged if present.** If the entities have dramatically different evidence bases, is this flagged in the opening and in affected sections? FAIL if the draft presents asymmetric alternatives as if they were evenly characterized.

(13) **Citation density.** Count inline citations in the body. FAIL if density < 8 per 1000 words, FAIL if any entity section runs ≥300 words without a citation, FAIL if < 50% of fetched sources are cited at least once. Per-entity evaluation requires per-entity evidence — an entity description with 0-1 citations is a description, not an evaluation.

(14) **Prompt-named entity coverage.** For every explicitly named entity in the user's verbatim prompt, verify a dedicated section exists with its own H2 or H3. FAIL if any named entity is collapsed or silently dropped.

Auditor output: list every violation with a one-line quote from the report.
