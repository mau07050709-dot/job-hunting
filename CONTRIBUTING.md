# Contributing

Use a separate local environment and fictional applicants for development. Never attach private CVs, browser profiles, real credentials, medical information or employer receipts to issues or pull requests.

Install `.[dev]` from the repository root. Run the complete suite with `python -m pytest -q` and consult `docs/TESTING.md` for historical tests and optional integrations. Browser integration tests use temporary profiles and controlled fixtures. Do not turn on real-portal, private-CV or Windows-vault flags during routine development.

Preserve person isolation, manual corrections, duplicate prevention, uncertain-result handling and the manual-final-submission policy. New adapters must not bypass CAPTCHA, login/access restrictions or paywalls. Describe unsupported controls accurately rather than reporting successful preparation or submission without evidence.

Before exporting source, remove generated runtime/build files and run `python scripts/audit_public.py`. Review newly added binary assets and their licenses. The audit is heuristic; a clean result does not replace manual review. Do not add badges, benchmark claims, screenshots or compatibility claims that have not been verified.
