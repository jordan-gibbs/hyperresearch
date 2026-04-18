---
name: research-synthesize
description: >
  Interpretive and explanatory research. The user wants to know what
  something MEANS, how it WORKS, or WHY it is the way it is. Primary virtue
  is interpretation density — every paragraph fuses fact with an analytical
  claim. Covers everything from literary/humanities interpretation to
  conceptual explanation of scientific mechanisms.
---

# Synthesize Protocol

> You are in **synthesize** modality. The dispatcher routed you here because the output needs a defended thesis or a mechanism explanation — not enumeration, not comparison, not prediction. The reader leaves with an argument they can be persuaded by or disagree with.

Read the dispatcher (`.claude/skills/hyperresearch/SKILL.md`) for the process. This file is the SUBSTANCE reference for synthesize.

---

## What synthesize is for

| Prompt shape | Why it's synthesize |
|---|---|
| "What does Blood Meridian's violence mean" | Thesis-driven interpretation |
| "Explain how attention mechanisms work in transformers" | Mechanism explanation |
| "Why did the Roman Republic collapse" | Causal / explanatory |
| "What is Wittgenstein's private language argument and why does it matter" | Interpretive + conceptual |
| "How does CRISPR-Cas9 edit DNA and what are its limitations" | Mechanism + critique |

Synthesize is NOT for: "list all X" (collect), "which X is best" (compare), "will X happen" (forecast).

**Two legitimate sub-shapes:**
1. **Interpretive synthesis** — the subject is a text, work, tradition, cultural phenomenon, or philosophical position. The thesis is an interpretation. Sources are primary texts + established critical tradition + dissenting readings.
2. **Mechanism synthesis** — the subject is a process, system, or phenomenon. The thesis is a mechanism explanation with WHY it works the way it does. Sources are peer-reviewed literature + authoritative technical references.

The dispatcher picks synthesize when the output's primary virtue is *understanding*, regardless of which sub-shape applies.

---

## Source strategy

### If a peer-reviewed literature exists — academic API sweep BEFORE web search

For mechanism synthesis, or interpretive synthesis where scholarly criticism is the dominant tradition: run the academic APIs first. Web search returns derivative commentary; academic APIs return citation-ranked canonical papers.

**Semantic Scholar** — citation count + forward/backward chaining:

```python
import httpx, json, urllib.parse, os, time
SS_KEY = os.environ.get("SS_API_KEY", "")
HEADERS = {"x-api-key": SS_KEY} if SS_KEY else {}
q = urllib.parse.quote("<topic>")
url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={q}&fields=title,year,citationCount,externalIds&limit=10"
r = httpx.get(url, headers=HEADERS, timeout=15).json()
papers = sorted(r["data"], key=lambda p: p.get("citationCount", 0), reverse=True)
# Top 3 → backward chain (references) AND forward chain (citations)
for p in papers[:3]:
    pid = p["paperId"]
    refs = httpx.get(f"https://api.semanticscholar.org/graph/v1/paper/{pid}/references?fields=title,year,citationCount&limit=30", headers=HEADERS, timeout=15).json()
    cits = httpx.get(f"https://api.semanticscholar.org/graph/v1/paper/{pid}/citations?fields=title,year,citationCount,isInfluential&limit=50", headers=HEADERS, timeout=15).json()
    time.sleep(0.4)
```

Backward chaining finds the foundational canon; forward chaining finds everything built on it in the last 3 years.

**OpenAlex** for humanities, social science, medicine, or non-arXiv disciplines:

```
https://api.openalex.org/works?search=<topic>&sort=cited_by_count:desc&per-page=15&mailto=research@example.com
```

**arXiv** for cs / stat / q-bio / econ / math / physics:

```
https://export.arxiv.org/api/query?search_query=cat:cs.LG+AND+all:<topic>&sortBy=relevance&max_results=25
```

**PubMed eutils** for biomedical / clinical:

```
https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=<topic>&retmode=json&retmax=20
```

Feed PDF links directly to `$HPR fetch` — the fetcher handles PDF extraction automatically.

### If the subject has no peer-reviewed literature — start with primary sources + guided reading loop

For interpretive synthesis of pop-culture / contemporary / niche subjects where scholarly criticism is thin or absent, skip the academic sweep. The source strategy is:

**Ground truth:** the primary work itself (if available online; substantial excerpts if not), author/creator interviews stating intent, official materials.

**Institutional signal:** named critical essays, longform analyses, scholarly monographs, Wikipedia references harvest (curated for notability).

**Practitioner triangulation:** professional reviews, interviews with domain experts, conference keynote transcripts.

**Commentary (de-prioritized):** listicles and YouTube reviews — lead-generation only, not load-bearing.

Use the **guided reading loop** from the dispatcher as the default discovery mechanism. The critical tradition for interpretive subjects is discoverable only by reading — the essay names three critics, those critics cite a 1998 monograph, the monograph references a specific passage.

### Non-English sources when the subject has non-English reception

If the subject has major non-English reception (a franchise bigger in France than the US, a philosopher with denser German scholarship, a movement with foundational French literature), run searches in those languages:

```
WebSearch("<topic> análise crítica")      # Portuguese
WebSearch("<topic> critique analyse")     # French
WebSearch("<topic> analisi critica")      # Italian
WebSearch("<topic> Kritik Rezeption")     # German
WebSearch("<topic> 批評 論文")              # Japanese
```

Non-English sources count toward voice diversity at Checkpoint 1.

### Adversarial round — MANDATORY, run all four before proceeding

Find the strongest dissenting reading / dissenting mechanism explanation / dissenting theoretical position. Your thesis must engage it with substance, not a one-sentence dismissal. **Fetch at least one source that explicitly argues against the dominant interpretation.**

```
WebSearch("<topic> criticism limitations")
WebSearch("against <dominant reading> <topic>")
WebSearch("<topic> reappraisal revisionist new reading")
WebSearch("<topic> overrated wrong contested")
```

The audit at Step 11 verifies at least one body section engages the dissenting reading with substance (a paragraph or more, not a sentence). A synthesize draft built entirely from sources that agree with each other is advocacy — the corpus must contain the strongest counter-voice you could find, even if your draft ultimately rejects it.

If the dominant reading has a named opponent (e.g., "the Lacanians say X but Žižek argues Y"), search for the opponent by name, not just by topic. Named-critic search produces sharper dissent than generic "criticism of X".

### Source diversity — at least one non-academic voice

If the subject has practitioners (applied economists, engineers, policy analysts, industry users, operators), **at least one non-academic voice is mandatory.** A synthesize corpus built entirely of peer-reviewed papers plus lecture notes is a monoculture — the thesis loses its grip on reality when nobody in the corpus has actually *used* the thing.

Examples of required non-academic voices:
- "Is there a general method for solving first-price auctions?" — the academic corpus says "here are 5 methods"; an applied voice (FTC economist blog, procurement handbook, named practitioner postmortem) tells you whether any of them is actually used in the wild.
- "How does CRISPR edit DNA?" — the academic papers explain the mechanism; a biotech industry voice (Moderna process description, patent litigation commentary) tells you which off-target effects matter in production.
- "What does Blood Meridian mean?" — the scholarly tradition sets the interpretive axes; a named critic blog or longform essay brings the thesis into the present.

Search for these explicitly:

```
WebSearch("<topic> in practice applied industry")
WebSearch("<topic> practitioner guide used by")
WebSearch("<topic> does anyone actually use")
```

If no such voice exists (genuinely novel topic, purely theoretical subject), state that explicitly in the scaffold and explain why — otherwise Checkpoint 1 flags the corpus as under-diverse.

---

## Substance rules for Step 9 (writing)

These are the synthesize-specific rules that layer on top of the dispatcher's shared writing constraints.

### 1. Commit to a thesis

The draft is built around ONE defensible claim: what you are arguing about the subject. State it clearly — ideally in a single short sentence in the opening — then spend the draft defending it.

A thesis is NOT a summary ("Blood Meridian is about violence"). A thesis is an arguable position ("Blood Meridian's violence is structural, not expressive — it enacts a theological claim that human agency is a ventriloquism of geology"). A neutral reader could read your thesis and disagree.

### 2. Interpretation density — every paragraph fuses fact with claim

Every body paragraph must do both: report a fact / quote / source AND make an interpretive claim about what the fact MEANS within your thesis. A paragraph that only reports facts is a textbook excerpt, not synthesis.

**Bad:** "Transformers use a self-attention mechanism. The mechanism computes a weighted sum where weights come from query-key similarity."

**Good:** "Transformers use self-attention — but the substantive move is not the attention itself, it is what attention *replaces*. Recurrence imposes a temporal bottleneck: position N can only reach position N-1 through the sequence of hidden states. Self-attention obliterates this bottleneck and treats the sequence as a set, which is why transformers scale but LSTMs don't. The mechanism is a structural concession, not just an engineering trick."

Every paragraph earns its place by advancing the thesis or complicating it — not by restating source material.

### 3. Engage the strongest dissent

Find the reading / explanation / theoretical position that most directly contradicts your thesis. Give it substantive engagement — at minimum a full paragraph, ideally a full section. Represent it at its strongest, not strawmanned. Then explain why you reject it.

A thesis that never engages its opposite is advocacy, not argument.

### 4. Sources in tension at least twice

At least two body sections must put specific sources in direct tension: "Smith reads this passage as X; Jones reads it as Y. The textual evidence supports Z because..." This is the mark of synthesis — the reader sees you weighing evidence, not just citing it.

### 5. Quote the primary source directly

When the synthesis is interpretive, quote the primary work. Claim → direct quote → analysis of what the quote means. Paraphrase only when quotation is impossible or redundant.

When the synthesis is mechanism-explanation, quote the canonical paper's own description of the mechanism before you extend it.

### 6. Opening establishes the thesis AND the core tension

The opening answers: *what am I claiming, and why is this claim non-trivial*. If the thesis is obvious, the draft has no reason to exist. Name the tension: the paradox, the received view you're pushing against, the open problem, the tradeoff. That's the engine that drives the rest of the draft.

### 7. Section progression tracks the argument

Sections build on each other. Section 2's claim depends on section 1's setup; section 3 complicates section 2; the dissenting-view section is placed where the argument is strongest, so the reader feels the weight of the opposition before they see your counter. A shuffled set of thematic sections is not synthesis — it is a collage.

---

## Conformance checks (auditor reads this at Step 11, mode=conformance)

(0) **Verbatim prompt check.** Open `research/scaffold.md` — does its first section contain the user's verbatim prompt (unchanged, not paraphrased)? FAIL if missing or modified.

(1) **Thesis exists and is arguable.** Read the opening. Is there a clear thesis sentence? Is it a position a neutral reader could disagree with (not a neutral summary)? FAIL if the draft never commits to a claim.

(2) **Interpretation density.** Sample 5 random body paragraphs. For each: does it fuse a factual / source claim with an interpretive claim about what the fact means? FAIL any paragraph that is pure description or pure source-citation without an analytical move.

(3) **Dissenting view engaged substantively.** Find the section that engages the strongest opposing reading / explanation. Is the opposing position given a substantive paragraph (or more)? Is it represented at its strongest? FAIL if dissent is dismissed in one sentence or strawmanned.

(4) **Sources in tension at least twice.** Count body sections where specific sources are put in direct tension. FAIL if fewer than two.

(5) **Primary sources cited directly.** For interpretive synthesis: are there at least 3 direct quotations from the primary work? For mechanism synthesis: is the canonical source's own description of the mechanism quoted before the explanation extends it? FAIL if the draft only paraphrases.

(6) **Section progression.** Can sections be shuffled without loss? If yes, the draft is a collage, not an argument. FAIL.

(7) **Scaffold + comparisons + extract artifacts exist.** Run `$HPR search 'scaffold' -j`, `$HPR search 'comparisons' -j`, `$HPR note list --tag extract -j`. All must return non-empty. FAIL otherwise.

(8) **Provenance chain.** Run `$HPR lint --rule provenance -j`. FAIL if any issues.

(9) **Locus coverage.** Run `$HPR lint --rule locus-coverage -j`. FAIL if below 30%.

(10) **Tier weighting.** Are substantive claims anchored in `ground_truth` or `institutional` sources? Are load-bearing claims ever supported only by `commentary`? FAIL if any load-bearing claim rests solely on derivative commentary.

(11) **Core tension present in opening.** Does the opening state what makes the thesis non-trivial (the paradox, received view being pushed against, open problem)? FAIL if the opening is a neutral setup.

(12) **Citation density.** Count inline citations in the body. FAIL if density < 8 per 1000 words, FAIL if any H2 section runs ≥300 words without a citation, FAIL if < 50% of fetched sources are cited at least once. The thesis-driven synthesize register can LOOK deep while actually citing only a handful of sources; cite aggressively across the argument.

(13) **Prompt-named subtopic coverage.** For every explicitly named subtopic, entity, context, or field in the user's verbatim prompt, verify a dedicated H2 or H3 section exists. FAIL if any prompt-named item is collapsed into another section.

Auditor output: list every violation with a one-line quote from the report.
