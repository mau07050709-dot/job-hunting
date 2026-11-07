# Validation status

## Naming-only verification — 2026-11-06

- 72 regression tests passed, 0 failed in the targeted naming run.
- Coverage: configuration/storage, GUI startup, person isolation, current application UI, CV/profile handling, salary/date handling, manual completion, local OCR and the real Brave extension against controlled local/fictional forms.
- Python source syntax and extension JavaScript syntax checked.
- A temporary wheel built successfully with distribution name `job-hunting`, version `0.2.1`, and console entry `job-hunting = autojob.cli:main`.
- The GUI was instantiated from this public source copy with empty temporary local storage; title `Job Hunting`, the canonical `job_hunting.ico` resource and all four sections loaded.
- No external application was submitted, no real account was used, and no original Desktop launcher or original project file was modified.
- Temporary runtime data, test CVs, build products and generated package metadata were removed from the public tree after verification.

## Earlier public-export full-suite baseline

Before the naming-only pass, the complete retained suite ran with **800 passed, 27 failed and 67 skipped**. Historical UI tests and other existing failures remain; this repository does not claim a completely green full suite. The naming run is a targeted regression check, not a replacement claim for the entire suite. A subsequent focused export check passed 51 tests, skipped one and found an on-site test still assuming preselected personal localities; that test was adapted to explicitly select a locality, and the defaults/on-site verification then passed all 18 tests.

Opt-in private-CV references, external portal integrations and Windows-vault writes are not normal public validation steps. Passing controlled tests does not guarantee compatibility with every changing employer form or job source.

See [naming compatibility](NAMING.md) for deliberately retained storage, import and extension identifiers.
