# Job Hunting

A Windows desktop application for CV-based job discovery, application preparation and human-assisted form filling in Brave.

Job Hunting combines local resume parsing, an editable professional profile, rules-based matching, a persistent job catalog and a companion browser extension. It is designed around a reviewable workflow: discover opportunities, inspect the employer's application form, fill confirmed information, and let the user complete unknown answers and the final submission.

## Features

- Four main sections: Home, My Data, Applications and Settings (the current interface is in Spanish).
- Independent person aliases with separate CVs, profiles, preferences and application lists.
- PDF/DOCX import, structured extraction, manual corrections and CV selection by role/language.
- Public job-source connectors, deduplication, configurable result targets, geographical checks and local persistence.
- Confirmed profile answers, salary conversions and configurable availability. No applicant information is preloaded.
- Personal-Brave autofill through a locally paired Manifest V3 extension; selected applications only.
- Form detection across matching redirects, new tabs and accessible embedded documents. Existing manual entries are preserved.
- Optional on-device Windows OCR with periodic Qt captures and worker-thread processing. Captures are not stored by the OCR monitor.
- Human intervention notices; optional user-configured YouTube background video/audio.
- A manually completed applications archive per person, distinct from verified submission receipts.
- Local letter templates, response tools, controlled form simulators, account/identity protection and retained advanced modules.

**The public edition does not perform automated final submissions to external employers.** Complete final submission yourself in Brave. CAPTCHA, MFA, authentication, legal declarations and unsupported controls require human input. Autofill and attaching a CV can transmit personal data to the selected employer before submission; use them only after reviewing the destination.

## Requirements

- Windows 10/11, 64-bit; validation is performed on Windows 11 with Python 3.13.
- Python 3.11+ (Python 3.13 recommended) and Brave installed separately.
- Internet for job sources and optional video. CV parsing, profile storage, rules and OCR run locally.
- An installed English or Spanish Windows OCR language for optional visual recognition. DOM-based autofill still works without OCR.

## Install from source (PowerShell)

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\job-hunting.exe init
.\.venv\Scripts\job-hunting.exe gui
```

Run these commands from the repository root. Alternatively, double-click **Instalar Job Hunting.cmd**, then **Iniciar Job Hunting.cmd**. No VS Code is required. These launchers operate in this copy's directory and do not alter another installation or create Desktop shortcuts.

`config.example.json` documents supported configuration keys. `init` creates a local `config.json` and SQLite storage under `data/`. Both are excluded from the repository. Configure Brave's executable only if automatic discovery fails. Do not reuse a private installation's database or browser profile in a public repository.

For a fresh setup, clone the repository into a new folder and run the Windows launchers from that folder. Add a person alias and import the CV from **Mis datos**. The imported files and preferences stay in the local installation.

## First-run workflow

1. Open **MIS DATOS** and create/select a person alias.
2. Import your own CVs, review extraction and confirm your profile, salary currency/period, availability and work authorization.
3. Choose accepted localities for on-site jobs. Remote eligibility must be checked for the applicant's actual country.
4. Select a target of 1–50 new opportunities and start discovery. Results appear in **POSTULACIONES**.
5. Open a result in your normal Brave or request autofill after configuring the extension below.
6. Review unknown answers, attachments, employer geography and terms yourself. Submit manually.
7. Use **HECHO** to archive an application you consider completed. This does not manufacture a verified receipt.

The geographic engine currently focuses on Costa Rica and remote eligibility from Costa Rica. Source limits, public availability and regional rules still apply; this is not a worldwide eligibility verifier. Localities and salaries are editable. Unknown data stays unknown. The optional next-day start rule is off until you confirm it for your own profile.

## Brave extension

Open `brave://extensions` in your personal Brave, enable Developer mode, choose **Load unpacked**, and select `brave-extension/`. In Job Hunting, open **CONFIGURACIÓN → VINCULAR EXTENSIÓN DE RELLENADO**, copy the local pairing code and link it in the extension. Do not publish this code. Pairing is local and normally needed only once per installation/profile.

See [extension guide](brave-extension/README.md) and [security notes](SECURITY.md). The app uses loopback port 18746 for the paired bridge. Do not run two copies using this port at the same time. The personal browser is not owned or closed by the extension; automated search uses a separate browser profile.

## Development and tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Local browser integration tests are opt-in and use fictional applicants and temporary profiles:

```powershell
$env:JOB_HUNTING_TEST_EXTENSION = "1"
.\.venv\Scripts\python.exe -m pytest -q tests/test_generic_forms.py tests/test_extension_fill.py
```

Tests involving private CV references, real websites or the Windows credential vault must not be enabled in a normal test run. No private references are included. See [testing status](docs/TESTING.md) for executed results, inherited historical-test failures and unverified integrations. Passing local tests is not proof that every employer portal works.

## Repository layout

```text
src/autojob/      Desktop UI, profile/CV services, storage, search and browser engines
brave-extension/ Companion extension and DOM scanner
scripts/         Installation, safe packaging and public-source audit
tests/          Unit/regression tests and controlled fixtures
docs/           Architecture, privacy and validation notes
```

## Distribution and limitations

This repository is a source distribution. It does not include Python, Brave, browser profiles, databases, CVs, credentials, an executable, personal backgrounds or videos. `scripts/package_windows.py` creates a source ZIP from an explicit allowlist. Users install dependencies themselves; no installer or executable is claimed to be tested on every Windows version.

Job boards and forms change, may restrict automation, require login/payment, use inaccessible frames or block automated access. Job Hunting does not bypass paywalls, CAPTCHA or access restrictions. No search or autofill implementation can guarantee support for every page. Never infer employment authorization, credentials, experience or legal consent from incomplete data.

## License

Application code is provided under the [MIT License](LICENSE). Dependencies, services and trademarks remain under their own licenses and terms; see [third-party notices](THIRD_PARTY_NOTICES.md). No third-party browser, ML model, engine binary or media asset is redistributed here.

Internal compatibility identifiers are documented in [project naming](docs/NAMING.md). They do not change the product name.
