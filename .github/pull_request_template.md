<!-- Keep this short. Delete anything that doesn't apply. -->

## What this changes

<!-- One or two sentences. If it fixes an issue, write "Fixes #NNN" so it closes on merge — note that GitHub only auto-closes the FIRST issue in a list, so give each one its own keyword. -->

## Why

<!-- The behavior that was wrong, or the gap being filled. Link the issue if there is one. -->

## How it was verified

<!-- `pytest tests/` and `ruff check src/ tests/` at minimum. Say which tests fail without the change. -->

---

**Scope check** — the review is much faster when the diff contains only the change being proposed:

- [ ] No unrelated reformatting, whitespace, or prose rewriting outside the lines this change needs
- [ ] `CHANGELOG.md` touched only to add an entry under `[Unreleased]`
- [ ] No edits to user-facing output strings, docstrings, or test fixtures unrelated to this fix
- [ ] If you ran a formatter or an automated cleanup pass, its results are in a separate PR

<!-- If you're adding a third-party service or provider, please say up front whether you're affiliated with it. It doesn't disqualify the PR; it just saves a round trip. -->
