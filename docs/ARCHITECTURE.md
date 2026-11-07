# Architecture

The Python package retains its internal `autojob` name. `ui/main_window.py` and `ui/simple_shell.py` compose the four-section PySide6 desktop interface; existing advanced widgets remain in the package. `people.py` selects separate local stores per alias. `storage/database.py` maintains SQLite and migrations. `resumes/`, `profile/` and `matching/` handle extraction, corrections, confirmed answers and compatibility rules. `search/` and `manual_search.py` manage public connectors, result targets and logical deduplication.

`extension_fill.py` exposes a paired loopback bridge. The Manifest V3 extension reads field metadata, verifies task scope, fills confirmed values and uploads a reviewed role-matched CV when requested. It preserves manual values and does not click final submission. `forms/detection.py` recognizes application structures and validates company/role across new destinations. Accessible embedded documents are processed using their document IDs.

`ui/visual_fill.py` runs a Qt timer and bounded worker-thread Windows OCR. It observes only the linked foreground application document; the OCR signal requests a new DOM inspection rather than clicking arbitrary screen coordinates. This is text recognition, not the chess-piece ONNX model.

`forms/`, `auth/`, `form_sessions.py` and `interventions.py` retain preparation, authorization, account isolation, session and historical receipt machinery. The public engine blocks external final submission while keeping controlled local simulators. `completed.py` separately stores manually marked applications and does not treat them as verified employer receipts.

All runtime state is created locally. The source tree has no dependency on a private installation, another desktop project or a previously authenticated browser profile. User data is not bundled into the source ZIP.
