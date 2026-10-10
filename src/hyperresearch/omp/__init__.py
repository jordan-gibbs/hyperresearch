"""Non-Python install resources for the OMP target.

`extension_template.ts` is the stop-gate extension the OMP installer writes to
`.omp/extensions/hyperresearch.ts`. It lives here (rather than as a Python
string literal) so editors highlight it as TypeScript and so the shipped file
is the one that runs.
"""
