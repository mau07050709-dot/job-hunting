import os
from pathlib import Path

from autojob.errors import ProfileInUse


class ProfileLock:
    """Bloqueo del sistema operativo: se libera incluso si el proceso termina."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def acquire(self):
        if self.handle is not None:
            raise ProfileInUse("Esta instancia ya tiene el bloqueo del perfil")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0)
            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise ProfileInUse("El perfil de Job Hunting está en uso. Cierra la otra ejecución.") from exc
        self.handle = handle

    def release(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None
