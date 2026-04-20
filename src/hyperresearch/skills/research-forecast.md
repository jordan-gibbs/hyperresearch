---
name: research-forecast
description: >
  Forward-looking research. The user wants to know what will happen or
  what should be done. Primary virtue is a committed prediction or
  recommendation grounded in past + current state with an explicit time
  horizon. Sources are ground-truth statistics, institutional analysis,
  policy documents, and practitioner positioning. NOT academic papers.
---

# Forecast Protocol

> You are in **forecast** modality. The dispatcher routed you here because the output needs a committed position on something that has not yet happened: a prediction, a recommendation, a strategy. The reader leaves knowing what you expect / recommend and the reasoning chain that got you there. **Do not hedge.** Use probability language, not "it is possible".

Read the dispatcher (`.claude/skills/hyperresearch/SKILL.md`) for the process. This file is the SUBSTANCE reference for forecast.

---

## What forecast is for

| Prompt shape | Why it's forecast |
|---|---|
| "Will US inflation stay above 3% through 2026" | Prediction |
| "What should the US Navy do about the China shipbuilding gap" | Strategy / recommendation |
| "How will LLM pricing evolve over the next 2 years" | Forward-looking |
| "Is the AI bubble going to burst and when" | Prediction |
| "What's the right architecture for building a trading firm in 2026" | Forward-looking recommendation |

Forecast is NOT for: "what exists now" (collect), "how does X work" (synthesize), "which option is best today" (compare).

---

## Source strategy

Forecast is **secondary-heavy** — triangulation across many institutional perspectives matters more than any single primary source. BUT the forecast must still be **anchored in ground-truth** (official stats, filings, policy text). The structure is:

**Ground truth (anchoring evidence):**
- Official policy documents, regulatory filings, legislative text
- Government statistics and economic data (central banks, national statistics offices, international bodies)
- Company earnings guidance, SEC filings, official roadmaps and announcements
- Primary datasets with time-series data for trend establishment

**Time-horizon rule:** for 6–12 month forecasts, prioritize data from the last 12 months. For 3–5 year forecasts, prioritize structural trend data spanning 5–20 years. A short-horizon forecast built on 20-year structural data will miss the current regime; a long-horizon forecast built only on last-quarter data is noise-chasing.

**Institutional signal (main triangulation layer):**
- Research organizations and think-tanks relevant to your domain
- Industry analysts and sector research firms
- International organizations (IMF, OECD, World Bank for macro; ITU for telecom; IEA for energy)
- Named economists, strategists, and domain experts in institutional roles

**Find the right institutional voice for the domain.** Do not default to generic management consultants — find the analyst body with domain authority. Energy forecasts come from the IEA and industry-specific firms, not from McKinsey. Tech forecasts come from Gartner / IDC / 451 Research and specialized analysts, not general news.

**Paywall fallback:** when reports are gated: (1) search for "[report title] key findings"; (2) press coverage of the report; (3) the organization's free-publications section; (4) earlier free editions.

**Practitioner triangulation:**
- Expert commentary — op-eds and essays by named practitioners (not anonymous)
- Practitioner forecasts and positioning signals (how people operating in this domain are actually betting)
- Conference keynotes with transcripts

**Contrarian and dissenting voices:** independent analysts who challenge the consensus. These are load-bearing for forecast — the contrarian case is not optional; it must be represented with substance.

### Do NOT run academic API sweeps

Academic papers are the wrong sources for forecasting. Citation-ranked scholarship describes what's known about the past, not what will happen. Skip Semantic Scholar / arXiv / OpenAlex / PubMed for forecast queries.

### Adversarial round — MANDATORY, run all five before proceeding

A forecast without explicit engagement with the failure case is not analysis — it is advocacy. Run all five searches and **fetch at least one source that explicitly argues the bear case** (a contrarian analyst report, a named-skeptic op-ed, a historical-failure post-mortem):

```
WebSearch("<topic> bear case downside risk")
WebSearch("<topic> contrarian view dissenting forecast")
WebSearch("why <dominant forecast> is wrong")
WebSearch("<topic> worst case scenario")
WebSearch("<topic> historical failure analogous case")
```

The audit at Step 11 verifies the bear case gets substantive coverage — at minimum a full paragraph engaging the contrarian position at its strongest, ideally a full section. A one-paragraph dismissal is strawmanning, not stress-testing.

If the dominant forecast has a named skeptic (e.g., "consensus says soft landing but Roubini predicts X"), search for the skeptic by name. Named-contrarian search produces sharper dissent than generic "criticism of X".

---

## Substance rules for Step 9 (writing)

These are the forecast-specific rules that layer on top of the dispatcher's shared writing constraints.

### 1. Commit to a position

The draft is built around a committed forecast or recommendation. Use probability language: "more likely than not", "substantial probability", "unlikely unless", "approaches certainty in the 12-month horizon". Do NOT use hedge language: "it is possible", "some experts believe", "time will tell". Probability language commits to a distribution; hedging commits to nothing.

### 2. Time horizon is explicit

Every forecast claim carries a time scope. If the user specified a horizon ("what happens by 2026"), deliver claims scoped to that horizon. If the prompt is silent on time, distinguish between:
- **Short-term** (6–12 months): near-certain / high-confidence dynamics
- **Medium-term** (1–3 years): trend-dependent, structural moves
- **Long-term** (3–5+ years): speculative, path-dependent

A forecast that conflates short- and long-term claims is incoherent. Either scope every claim or dedicate sections to each horizon.

### 3. Directional commitment in the body, not only synthesis

At least one substantive body section must take a clear directional stance — a claim about what will happen or what should be done. "The synthesis will take a position" is not sufficient. The reasoning has to commit along the way, not just at the end.

If the user requested scenario-neutral analysis (e.g., "outline optimistic, central, and bear cases"), directional commitment lives *within each scenario branch*. Each scenario has a named probability and its own committed path — the branching is not an escape from commitment.

### 4. Engage the contrarian case with substance

Find the strongest argument against your forecast / recommendation. Give it real engagement — at minimum a full paragraph, ideally a full section. Represent it at its strongest. Then explain why you reject it.

If the consensus view gets 3 sections of analysis, the bear case deserves comparable substantive coverage. A one-paragraph dismissal of dissent is strawmanning, not stress-testing.

### 5. Historical precedent grounds the prediction

Anchor forward-looking claims in at least one analogous historical case. "This looks like 1998-99 in tech valuations" is stronger than "valuations are high". If the domain is genuinely unprecedented (which is rare), say so explicitly and explain why past cases don't apply.

A forecast with zero historical grounding has no epistemic floor — it is a guess.

### 6. Tier weighting

Anchor the forecast in `ground_truth` sources (official statistics, filings, policy text). Use `institutional` (analyst reports, think-tanks) for consensus positioning. Use `practitioner` (expert commentary, positioning signals) and `commentary` (contrarian op-eds) for the bear case and dissent.

Do NOT build a forecast on `commentary` alone. A forecast grounded in news opinions is an opinion amplifier, not a forecast.

### 7. Opening frames the decision and the forces

The opening answers: *what decision or question is this answering, and what are the 3–5 forces that will determine the outcome*. The reader understands in the first 300 words what is at stake and what the draft is actually measuring.

### 8. Explicit "what would change my mind"

The draft must include — in the body or in the synthesis — a statement of what evidence would shift your position. "My forecast of X would flip if Y happens, because Z" is load-bearing: it separates a real forecast from a religious conviction.

---

## Conformance checks (auditor reads this at Step 11, mode=conformance)

(0) **Verbatim prompt check.** Open `research/scaffold.md` — does its first section contain the user's verbatim prompt (unchanged)? FAIL if missing or modified.

(1) **Committed position stated.** Read the opening and the synthesis. Is there a clear committed forecast / recommendation? FAIL if the draft hedges without committing or hides commitment behind "it depends" language alone.

(2) **Probability language, not hedge language.** Sample 10 predictive claims in the body. Do they use probability language ("more likely than not", "substantial probability", "unlikely unless") or hedge language ("it is possible", "some experts believe")? FAIL if hedge language dominates.

(3) **Time horizon explicit.** Every forecast claim carries a time scope — either inline or via sectioning (short-term / medium-term / long-term). FAIL if horizon is ambiguous or claims conflate time scales.

(4) **Directional commitment in the body, not only synthesis.** At least one substantive body section takes a clear directional stance, not just the Opinionated Synthesis. FAIL if commitment is wholly deferred to the closing synthesis.

(5) **Contrarian case engaged with substance.** Find the bear-case section or engagement. Is it a substantive paragraph (or more), representing the opposing view at its strongest? FAIL if dissent is dismissed in one sentence or strawmanned.

(6) **Historical precedent present.** Find at least one analogous historical case used to ground the prediction. FAIL if the draft makes forward-looking claims with zero historical anchoring AND does not explicitly justify why the domain is unprecedented.

(7) **Tier weighting.** Are forecast claims anchored in `ground_truth` tier sources? Is any load-bearing claim resting solely on `commentary`? FAIL if commentary is the sole support for a substantive prediction.

(8) **Scaffold + comparisons + extract artifacts exist.** Run `$HPR search 'scaffold' -j`, `$HPR search 'comparisons' -j`, `$HPR note list --tag extract -j`. All non-empty. FAIL otherwise.

(9) **Provenance chain.** Run `$HPR lint --rule provenance -j`. FAIL if any issues.

(10) **Extract coverage.** Run `$HPR lint --rule extract-coverage -j`. FAIL if below 30%.

(11) **Opening frames the decision + forces.** Does the opening state what is being forecast, why it is uncertain, and what 3–5 forces will determine the outcome? FAIL if the opening is a history lesson or a definition.

(12) **Explicit "what would change my mind" statement.** Find a statement of what evidence would flip the forecast. FAIL if no such statement exists.

(13) **No academic API sweep was run.** Confirm via vault tags — if the corpus is dominated by `paper` content_type sources, the agent ran the wrong source strategy. FAIL (non-critical — correct the source mix and re-run).

(14) **Citation density.** Count inline citations in the body. FAIL if density < 8 per 1000 words, FAIL if any H2 section runs ≥300 words without a citation, FAIL if < 50% of fetched sources are cited at least once. Forecasts that cite a handful of sources read as opinion; forecasts that cite widely read as reasoned positions.

(15) **Prompt-named dimension coverage.** For every explicitly named force, driver, scenario, or time-horizon in the user's verbatim prompt, verify a dedicated section exists. FAIL if any prompt-named item is collapsed.

Auditor output: list every violation with a one-line quote from the report.
