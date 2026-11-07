# Third-party dependencies and distribution notes

The MIT license in this repository applies to original Job Hunting application code and its neutral project icon. It does not relicense dependencies, public job-board content, browser software, trademarks or user-supplied media. Dependencies are installed from their upstream packages; their binaries and license files are not vendored here.

| Component | License / upstream reference |
| --- | --- |
| PySide6 / Qt for Python | LGPLv3/GPLv3 or commercial, with module-specific and third-party notices: [Qt for Python](https://doc.qt.io/qtforpython-6/commercial/index.html), [Qt licensing](https://doc.qt.io/qt-6/licensing.html), [LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations) |
| Playwright for Python | Apache-2.0: [upstream](https://github.com/microsoft/playwright-python) |
| pypdf | BSD-3-Clause: [upstream](https://github.com/py-pdf/pypdf) |
| python-docx | MIT: [upstream](https://github.com/python-openxml/python-docx) |
| pdfplumber | MIT: [license](https://github.com/jsvine/pdfplumber/blob/stable/LICENSE.txt) |
| phonenumbers | Apache-2.0: [upstream](https://github.com/daviddrysdale/python-phonenumbers) |
| openpyxl | MIT: [upstream](https://foss.heptapod.net/openpyxl/openpyxl) |
| reportlab | BSD-style license: [upstream](https://hg.reportlab.com/hg-public/reportlab/) |
| lxml | BSD-style Python code plus bundled library notices: [licensing](https://lxml.de/FAQ.html#what-is-the-license) |
| tzdata | Apache-2.0 package / public-domain IANA data: [upstream](https://github.com/python/tzdata) |
| PyWinRT bindings and runtime | MIT: [upstream](https://github.com/pywinrt/pywinrt) |
| pytest (development) | MIT: [upstream](https://github.com/pytest-dev/pytest) |

`requirements-lock.txt` records versions used for validation, not a copy of their artifacts. Transitive packages retain their own license notices. For example, Qt WebEngine includes Chromium components with additional notices; PDFium, cryptography/OpenSSL, Pillow and font resources also have their own terms. Consult the license metadata and installed upstream package notices before producing a binary installer. A source-only export is not a certification that any future bundled executable meets redistribution requirements.

## Assets, services and platform components

- No Brave/Python/Qt executable, Stockfish, Tetrarch, chess ONNX model, EDUS component or third-party browser extension is bundled.
- Windows OCR is accessed through platform APIs; no Windows OCR language/model files are redistributed.
- No anime imagery, YouTube video, song, screenshot, CV, job description archive or original user's appearance settings are distributed. Optional media is supplied by a user as a link and remains subject to the host's embedding and copyright rules.
- Public connector endpoints and limited field-name/schema matching are interoperability code. Job-board and employer terms, API limits, access controls and branding still apply. The repository does not grant permission to scrape restricted sources or bypass paywalls.
- No actual credentials, session data, employer receipt or applicant information is included in test fixtures. Unused job-posting prose was removed from the structural fixture.

Do not remove upstream copyright/license notices when redistributing dependencies separately. A future executable/installer needs its own complete dependency and license review; none is supplied by this repository.
