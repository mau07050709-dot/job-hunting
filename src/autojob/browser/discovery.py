import os
from pathlib import Path
import shutil

from autojob.errors import BrowserError


def find_brave(configured: str | None = None) -> Path:
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file() and candidate.name.lower() == "brave.exe":
            return candidate.resolve()
        raise BrowserError("brave_path no apunta a un brave.exe existente")
    candidates = []
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "BraveSoftware/Brave-Browser/Application/brave.exe")
    found = shutil.which("brave.exe")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise BrowserError("No se encontró Brave. Instálalo o configura brave_path en config.json.")
