"""Run levers: per-run posture shims rendered into shim files.

Levers are run-time choices step 1 writes into prompt-decomposition.json:

    "levers": {
      "register": "teach" | "survey" | "analyze" | "advocate",
      "register_confidence": "high" | "low",
      "domain_notes": "<2-3 freeform sentences>",
      "inference_depth": "surface" | "standard" | "deep",
      "rationale": {...}
    }

`render_shims` composes them into four role-scoped shim files under
`research/runs/<tag>/shims/` which the orchestrator pastes VERBATIM into
subagent spawn prompts. Division of labor: install-time profiles own every
number (source targets, budgets, word ceilings); levers own posture only.
Shim text must never restate a numeric budget.

The cite-checker and the ship gate receive no shim by design: verification
is register-independent and never softens by mode.
"""

from __future__ import annotations

import json

REGISTERS = ("teach", "survey", "analyze", "advocate")
INFERENCE_DEPTHS = ("surface", "standard", "deep")
ROLES = ("research", "drafting", "critics", "polish")

DEFAULT_LEVERS = {
    "register": "analyze",
    "register_confidence": "high",
    "domain_notes": "",
    "inference_depth": "standard",
}


class LeverError(Exception):
    pass


# ---------------------------------------------------------------------------
# Register posture blocks, per role. Additive composition only: one register
# block + one domain block + one inference block per file. Never author the
# register x depth cross-product.
# ---------------------------------------------------------------------------

_REGISTER_DRAFTING = {
    "analyze": """\
Default evaluative posture (this run confirms your prompt's defaults).
Write authoritative analysis: commit to the positions the evidence
supports, engage the strongest counterarguments explicitly, and rank
when the query asks which option wins. No adjustment to your prompt.""",
    "teach": """\
TEACH register. The reader is a motivated non-specialist who wants to
UNDERSTAND this subject, not to receive a verdict. Voice: patient
expert. Extend the primer discipline downward: subsections open with
plain-language explanation too, and every term is defined at first
use. A short glossary section is permitted where the vocabulary is
heavy. Frame conclusions as "what the evidence supports" rather than
rankings; a committed top-pick is NOT required. On contested points,
present each side's best case fairly before saying which way the
evidence leans. Worked examples and concrete analogies are encouraged
wherever they make a mechanism click.""",
    "survey": """\
SURVEY register. The product is a map of the field, not a verdict.
Voice: neutral cartographer. Coverage and organization outrank
argument: name every school of thought, position each approach
relative to the others, and prefer comparison tables wherever three
or more entities share dimensions. A committed thesis or ranking is
NOT required; where the field disagrees, chart the disagreement and
attribute each position instead of resolving it. Keep evaluative
asides brief and clearly sourced. Dramatic standalone sentences do
not belong in this register.""",
    "advocate": """\
ADVOCATE register. The report defends ONE thesis, named early and
argued throughout. Every section either advances the thesis or
disarms an objection to it. A steel-man treatment of the strongest
opposing case is MANDATORY: state the objection at full strength,
then answer it with evidence. Commitment is maximal; hedges belong
only on unverified secondhand specifics, never on the thesis or its
supporting chain.""",
}

_REGISTER_CRITICS = {
    "analyze": """\
Default evaluative posture (this run confirms your prompt's defaults).
Commitment checks apply as written: a draft that hedges where its own
evidence supports a stronger claim is a finding.""",
    "teach": """\
TEACH register. Adjust your failure modes: hedged neutrality on
genuinely contested points is CORRECT in this register, not a
finding. Instead, flag places where a view is represented unfairly
or a mechanism is asserted without being explained. Do not demand a
committed ranking; the instruction-following standard is that the
reader comes away understanding the subject. Findings that would
convert patient explanation into verdict-first argument are wrong
for this run.""",
    "survey": """\
SURVEY register. Adjust your failure modes: the draft is a map, not
an argument. Do not flag the absence of a committed thesis or
ranking. DO flag: a school of thought the corpus supports that the
draft omits, imbalanced coverage (one approach detailed, a peer
approach skimmed), unattributed resolution of a live disagreement,
and comparisons left in prose that belong in tables.""",
    "advocate": """\
ADVOCATE register. Tighten the commitment checks: the draft defends
one thesis, and the quality of its steel-man is your central
standard. A weakly stated or strawmanned opposing case is a critical
finding. Hedging on the thesis or its supporting chain is a finding;
hedging on unverified secondhand specifics is honesty and stays.""",
}

_REGISTER_POLISH = {
    "analyze": """\
Default evaluative posture (this run confirms your prompt's defaults).
Hedge-striking and the one-kicker-per-section budget apply as
written.""",
    "teach": """\
TEACH register. Do NOT strike hedges to force commitment: on
contested points, even-handed language is correct here, and the
hedge rule applies only to hedge-stacks and filler softeners.
Kicker budget is effectively zero: fold dramatic standalone
sentences into plain prose. Preserve primers, definitions, worked
examples, and glossary material; they are the product, not filler.""",
    "survey": """\
SURVEY register. Do NOT strike hedges to force commitment: neutral,
attributed language on disagreements is correct here, and the hedge
rule applies only to hedge-stacks and filler softeners. Kicker
budget is effectively zero: fold dramatic standalone sentences into
plain prose. Preserve coverage material and comparison tables even
where they read as unopinionated; the map is the product.""",
    "advocate": """\
ADVOCATE register. Hedge-striking at maximum: any softener on the
thesis or its supporting chain goes, per the existing evidence-backed
rule. Preserve the steel-man section intact; trimming the opposing
case's best evidence is forbidden.""",
}

# ---------------------------------------------------------------------------
# Inference-depth blocks.
# ---------------------------------------------------------------------------

_INFERENCE_RESEARCH = {
    "standard": """\
Standard depth (this run confirms your prompt's defaults). Follow the
normal sourcing playbook.""",
    "surface": """\
SURFACE depth. The question is answerable from authoritative
consensus sources. Prefer canonical reviews, primary standards, and
high-citation papers; stop when they agree. Do not open rabbitholes
or chase gray literature; a consistent consensus answer ends the
search.""",
    "deep": """\
DEEP inference. The surface web underdetermines this question, so the
value is in what takes digging: gray literature, regulatory and
financial filings, conference posters, theses, and named-practitioner
forum or mailing-list posts are all in scope. Treat audited absences
as findings: when a figure SHOULD be published and is not, search for
it hard, then record the absence itself with what you searched.
Lower-authority sources are usable WITH their provenance and
reliability tagged in the note. Spend toward the top of your assigned
budgets when a lead is genuinely load-bearing.""",
}

_INFERENCE_DRAFTING = {
    "standard": """\
Standard depth (this run confirms your prompt's defaults).""",
    "surface": """\
SURFACE depth. Report the consensus; do not construct novel inference
chains beyond what sources state directly.""",
    "deep": """\
DEEP inference. Explicit inference chains are licensed WITH
provenance stated: when no source states X but sourced claims A and B
jointly imply it, say so in exactly that shape, citing A and B. Never
present an inference as a sourced fact; the citation checker verifies
number-bearing sentences pair-by-pair and an inference dressed as a
quote or finding will be flagged. Audited absences (what the record
should contain but does not) are reportable findings.""",
}

_INFERENCE_CRITICS = {
    "standard": """\
Standard depth (this run confirms your prompt's defaults).""",
    "surface": """\
SURFACE depth. Flag any inference chain that goes beyond what the
cited sources state; this run stays on consensus ground.""",
    "deep": """\
DEEP inference. Inferential syntheses are expected in this draft; do
not flag inference itself. DO flag inference without provenance
discipline: any derived claim that fails to name the sourced claims
it derives from, and any audited absence asserted without stating
what was searched.""",
}


def validate_levers(levers: dict) -> dict:
    """Merge with defaults and validate enums. Returns the resolved dict."""
    if not isinstance(levers, dict):
        raise LeverError("levers must be an object")
    resolved = {**DEFAULT_LEVERS, **{k: v for k, v in levers.items() if v is not None}}
    if resolved["register"] not in REGISTERS:
        raise LeverError(
            f"unknown register '{resolved['register']}' (one of {', '.join(REGISTERS)})"
        )
    if resolved["inference_depth"] not in INFERENCE_DEPTHS:
        raise LeverError(
            f"unknown inference_depth '{resolved['inference_depth']}' "
            f"(one of {', '.join(INFERENCE_DEPTHS)})"
        )
    if not isinstance(resolved.get("domain_notes", ""), str):
        raise LeverError("domain_notes must be a string")
    return resolved


def _header(levers: dict) -> str:
    return (
        "## Run directives\n\n"
        "Auto-selected for this run in step 1; binding wherever they adjust "
        "a default in your prompt. Absent instructions here leave your "
        "prompt's defaults untouched.\n\n"
        f"- register: {levers['register']}\n"
        f"- inference depth: {levers['inference_depth']}\n"
    )


def _domain_block(levers: dict) -> str:
    notes = (levers.get("domain_notes") or "").strip()
    if not notes:
        return ""
    return f"\n### Domain notes\n\n{notes}\n"


def compose_shims(levers: dict) -> dict[str, str]:
    """Compose the four role shims. Additive: register + domain + depth."""
    lv = validate_levers(levers)
    reg, depth = lv["register"], lv["inference_depth"]

    research = (
        _header(lv)
        + _domain_block(lv)
        + f"\n### Inference depth\n\n{_INFERENCE_RESEARCH[depth]}\n"
    )
    drafting = (
        _header(lv)
        + f"\n### Register posture\n\n{_REGISTER_DRAFTING[reg]}\n"
        + _domain_block(lv)
        + f"\n### Inference depth\n\n{_INFERENCE_DRAFTING[depth]}\n"
    )
    critics = (
        _header(lv)
        + f"\n### Register posture\n\n{_REGISTER_CRITICS[reg]}\n"
        + f"\n### Inference depth\n\n{_INFERENCE_CRITICS[depth]}\n"
    )
    polish = _header(lv) + f"\n### Register posture\n\n{_REGISTER_POLISH[reg]}\n"

    return {"research": research, "drafting": drafting, "critics": critics, "polish": polish}


def _decomposition_path(vault, vault_tag: str):
    return vault.run_dir(vault_tag) / "prompt-decomposition.json"


def read_levers(vault, vault_tag: str) -> dict:
    """Levers block from the run's decomposition; defaults when absent."""
    dpath = _decomposition_path(vault, vault_tag)
    if not dpath.exists():
        raise LeverError(f"no prompt-decomposition.json for run '{vault_tag}' ({dpath})")
    try:
        decomp = json.loads(dpath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise LeverError(f"corrupt prompt-decomposition.json: {e}") from e
    return validate_levers(decomp.get("levers") or {})


def set_levers(vault, vault_tag: str, updates: dict) -> dict:
    """Update the decomposition's levers block in place. Returns resolved levers."""
    dpath = _decomposition_path(vault, vault_tag)
    if not dpath.exists():
        raise LeverError(f"no prompt-decomposition.json for run '{vault_tag}' ({dpath})")
    decomp = json.loads(dpath.read_text(encoding="utf-8"))
    levers = {**(decomp.get("levers") or {}), **updates}
    resolved = validate_levers(levers)  # raises before any write
    decomp["levers"] = levers
    dpath.write_text(json.dumps(decomp, indent=2) + "\n", encoding="utf-8")
    return resolved


def render_shims(vault, vault_tag: str) -> dict:
    """Render the four shim files from the run's decomposition levers.

    Records the resolved levers on the run manifest when one exists (a
    render outside a managed run is legal and simply skips the manifest).
    """
    levers = read_levers(vault, vault_tag)
    shims = compose_shims(levers)

    shims_dir = vault.run_dir(vault_tag) / "shims"
    shims_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for role in ROLES:
        path = shims_dir / f"{role}.md"
        path.write_text(shims[role], encoding="utf-8")
        written.append(str(path))

    from hyperresearch.core.runs import RunError, _save, load_manifest, record_event

    try:
        manifest = load_manifest(vault, vault_tag)
    except RunError:
        manifest = None
    if manifest is not None:
        manifest["levers"] = {
            "register": levers["register"],
            "inference_depth": levers["inference_depth"],
            "domain_notes": levers.get("domain_notes", ""),
        }
        _save(vault, vault_tag, manifest)
        record_event(
            vault,
            vault_tag,
            {
                "type": "levers",
                "register": levers["register"],
                "inference_depth": levers["inference_depth"],
            },
        )

    return {"levers": levers, "files": written}
