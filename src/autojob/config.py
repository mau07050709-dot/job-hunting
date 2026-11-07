from dataclasses import asdict, dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root: Path
    brave_path: str | None = None
    data_dir: str = "data"
    browser_transport: str = "persistent"
    timeout_ms: int = 15000
    headless: bool = False
    country: str = "Costa Rica"
    onsite_city: str = "Cartago"
    mode: str = "test"
    installation_data_dir: str | None = None

    def __post_init__(self):
        if self.browser_transport not in {"persistent", "cdp"}:
            raise ValueError("browser_transport debe ser persistent o cdp")
        if self.mode != "test":
            raise ValueError("El envío real todavía no está implementado. mode debe ser test.")
        if not isinstance(self.timeout_ms, int) or isinstance(self.timeout_ms, bool) or not 1000 <= self.timeout_ms <= 120000:
            raise ValueError("timeout_ms debe estar entre 1000 y 120000")
        if type(self.headless) is not bool:
            raise ValueError("headless debe ser un booleano")
        if not isinstance(self.data_dir, str) or not self.data_dir.strip():
            raise ValueError("data_dir debe ser un directorio relativo dentro del proyecto")
        if Path(self.data_dir).is_absolute() or not self.data_path.is_relative_to(self.root.resolve()) or self.data_path == self.root.resolve():
            raise ValueError("data_dir debe ser una subcarpeta del proyecto")

        if self.installation_data_dir is not None:
            base=self.installation_data_dir
            if not isinstance(base,str) or not base.strip():
                raise ValueError("Directorio de instalación inválido.")
            path=(self.root/base).resolve()
            if Path(base).is_absolute() or not path.is_relative_to(self.root.resolve()) or path==self.root.resolve():
                raise ValueError("Directorio de instalación fuera del proyecto.")

    @property
    def data_path(self) -> Path:
        return (self.root / self.data_dir).resolve()

    @property
    def profile_path(self) -> Path:
        return self.data_path / "brave-profile"

    @classmethod
    def load(cls, root: Path):
        path = root / "config.json"
        values = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        if not isinstance(values, dict) or "root" in values:
            raise ValueError("Configuración inválida")
        return cls(root=root.resolve(), **values)

    def save(self):
        values = asdict(self)
        del values["root"]
        base=values.pop("installation_data_dir")
        if base is not None:
            values["data_dir"]=base
        path = self.root / "config.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
