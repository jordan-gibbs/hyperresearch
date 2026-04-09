"""Built-in note templates."""

from __future__ import annotations

from datetime import UTC

BUILTIN_TEMPLATES: dict[str, str] = {
    "note": """\
---
title: "{{ title }}"
id: "{{ id }}"
tags: [{{ tags }}]
status: draft
type: note
created: {{ created }}
---

# {{ title }}

""",
    "concept": """\
---
title: "{{ title }}"
id: "{{ id }}"
tags: [{{ tags }}]
status: draft
type: note
summary: ""
created: {{ created }}
---

# {{ title }}

## Definition

_What is this concept?_

## Key Properties

-

## Examples

-

## Related

- [[]]
""",
    "reference": """\
---
title: "{{ title }}"
id: "{{ id }}"
tags: [{{ tags }}]
status: draft
type: raw
source: ""
summary: ""
confidence: 0.7
created: {{ created }}
---

# {{ title }}

## Citation

_Author, Title, Year. URL._

## Key Points

-

## Quotes

>

## My Notes

""",
    "guide": """\
---
title: "{{ title }}"
id: "{{ id }}"
tags: [{{ tags }}]
status: draft
type: note
summary: ""
created: {{ created }}
---

# {{ title }}

## Prerequisites

- [[]]

## Steps

### 1.

### 2.

### 3.

## Pitfalls

-

## See Also

- [[]]
""",
    "comparison": """\
---
title: "{{ title }}"
id: "{{ id }}"
tags: [{{ tags }}]
status: draft
type: note
summary: ""
created: {{ created }}
---

# {{ title }}

## Overview

_What are we comparing and why?_

## Comparison

| Criteria | Option A | Option B |
|----------|----------|----------|
|          |          |          |
|          |          |          |

## Verdict

## Related

- [[]]
""",
    "moc": """\
---
title: "{{ title }}"
id: "{{ id }}"
tags: [{{ tags }}]
status: draft
type: moc
summary: "Map of content for {{ title }}"
created: {{ created }}
---

# {{ title }}

## Core Concepts

- [[]]

## Guides

- [[]]

## References

- [[]]

## Open Questions

-
""",
}


def get_template(name: str, templates_dir=None) -> str | None:
    """Get a template by name. Checks vault templates dir first, then built-ins."""
    if templates_dir:
        custom = templates_dir / f"{name}.md"
        if custom.exists():
            return custom.read_text(encoding="utf-8")
    return BUILTIN_TEMPLATES.get(name)


def list_templates(templates_dir=None) -> list[dict]:
    """List available templates."""
    templates = []
    for name in BUILTIN_TEMPLATES:
        templates.append({"name": name, "source": "builtin"})

    if templates_dir and templates_dir.exists():
        for f in sorted(templates_dir.glob("*.md")):
            name = f.stem
            if name not in BUILTIN_TEMPLATES:
                templates.append({"name": name, "source": "custom"})
    return templates


def render_template(template_str: str, title: str, note_id: str, tags: list[str]) -> str:
    """Render a template with Jinja2-like variable substitution."""
    from datetime import datetime

    now = datetime.now(UTC).isoformat()
    tags_str = ", ".join(tags) if tags else ""

    result = template_str
    result = result.replace("{{ title }}", title)
    result = result.replace("{{ id }}", note_id)
    result = result.replace("{{ tags }}", tags_str)
    result = result.replace("{{ created }}", now)
    return result
