# Security and privacy

Do not commit CVs, contact details, identities, passwords, pairing tokens, receipts, logs, screenshots, HAR files, local configuration, browser profiles or databases. `.gitignore` is a secondary safeguard, not a sanitizer. Run `python scripts/audit_public.py` before sharing a source snapshot and inspect the resulting files yourself.

CVs, profile corrections, per-person job history and optional appearance/video settings are created locally under `data/`. Credentials and protected identity use Windows-backed storage through the retained security modules; public sources contain no account records or secrets. Do not enable vault integration tests without understanding that they create a fictional Windows credential temporarily.

The extension requests broad HTTPS host access to support different employers, but its task logic is scoped to the selected person and verified application identity. Pairing authenticates loopback requests; it is not an Internet API. Do not expose port 18746 or share the pairing code. Desktop capture is limited to the focused, recently linked application window and is paused for detected CAPTCHA; images used by the OCR monitor stay in memory.

Filling a page or attaching a CV may transmit data before a final click. Review the employer and destination first. Unknown answers, unsupported controls, CAPTCHA, MFA, legal consent and final submission remain human tasks. The public submission engine refuses external final delivery; controlled local POST tests remain available.

Optional videos contact YouTube only when explicitly configured locally. No video, personal image or account is bundled. A fresh installation starts with no background/video and no applicant data.

If you discover a security issue, do not post credentials, CVs, identity documents or exploit details containing private information in a public issue. Contact the repository maintainer privately through a channel they provide. No unverified security-contact address is embedded in this project.
