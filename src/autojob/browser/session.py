import logging
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from autojob.browser.discovery import find_brave
from autojob.browser.lock import ProfileLock
from autojob.config import Settings
from autojob.errors import BrowserError

logger = logging.getLogger(__name__)


def validate_local_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    try:
        valid = parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port and parsed.path in {"", "/"}
    except ValueError:
        valid = False
    if not valid or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise BrowserError("CDP solo admite http://127.0.0.1:PUERTO, sin credenciales ni redirecciones configuradas.")
    return endpoint


class BraveSession:
    """Sesión propietaria de Brave con perfil exclusivo y cierre determinista.

    El transporte CDP inicia SU PROPIA instancia; nunca adjunta un perfil personal.
    Las instancias no se comparten entre hilos. Usar una por worker.
    """

    def __init__(self, settings: Settings, isolated_key=None):
        self.settings = settings
        from hashlib import sha256
        folder = settings.data_path / 'form-sessions' / sha256(str(isolated_key).encode()).hexdigest() if isolated_key is not None else settings.data_path
        self.profile_path = folder / 'brave-profile'
        self.context = None
        self._playwright = None
        self._browser = None
        self._process = None
        self._lock = ProfileLock(folder / "browser.lock")
        self._owned_pages = []

    def start(self):
        if self.context is not None:
            return self
        executable = find_brave(self.settings.brave_path)
        self._lock.acquire()
        try:
            self.profile_path.mkdir(parents=True, exist_ok=True)
            self._playwright = sync_playwright().start()
            if self.settings.browser_transport == "cdp":
                self._start_cdp(executable)
            else:
                # Reemplazar los argumentos de automatización predeterminados:
                # incluyen cambios de seguridad, extensiones y password-store.
                # Este conjunto conserva las protecciones normales de Brave.
                args = ["--remote-debugging-pipe", f"--user-data-dir={self.profile_path}",
                        "--no-first-run", "--no-default-browser-check", "about:blank"]
                if self.settings.headless:
                    args.insert(0, "--headless=new")
                self.context = self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_path),
                    executable_path=str(executable),
                    headless=self.settings.headless,
                    chromium_sandbox=True,
                    ignore_default_args=True,
                    args=args,
                    timeout=self.settings.timeout_ms,
                )
            self.context.set_default_timeout(self.settings.timeout_ms)
            self.context.set_default_navigation_timeout(self.settings.timeout_ms)
            logger.info("Brave iniciado: transporte=%s", self.settings.browser_transport)
            return self
        except Exception as exc:
            self.close()
            raise BrowserError("No se pudo iniciar Brave. Revisa instalación, perfil ocupado y data/logs/job-hunting.log. " + str(exc)) from exc

    def _start_cdp(self, executable: Path):
        port_file = self.profile_path / "DevToolsActivePort"
        port_file.unlink(missing_ok=True)
        args = [str(executable), f"--user-data-dir={self.profile_path}",
                "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
                "--no-first-run", "--no-default-browser-check", "about:blank"]
        if self.settings.headless:
            args.append("--headless=new")
        self._process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + self.settings.timeout_ms / 1000
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise BrowserError("Brave terminó antes de habilitar CDP")
            if port_file.exists():
                try:
                    port = int(port_file.read_text(encoding="utf-8").splitlines()[0])
                    endpoint = validate_local_endpoint(f"http://127.0.0.1:{port}")
                    self._browser = self._playwright.chromium.connect_over_cdp(endpoint, timeout=self.settings.timeout_ms)
                    self.context = self._browser.contexts[0]
                    return
                except (ValueError, IndexError, OSError):
                    pass
            time.sleep(0.1)
        raise BrowserError("Se agotó el tiempo de conexión CDP")

    def new_page(self, url: str | None = None):
        if self.context is None:
            raise BrowserError("La sesión de Brave no está iniciada")
        page = None
        try:
            page = self.context.new_page()
            self._owned_pages.append(page)
            if url:
                response = page.goto(url, wait_until="domcontentloaded")
                if response and response.status >= 400:
                    raise BrowserError(f"La página respondió HTTP {response.status}")
        except (PlaywrightError, BrowserError) as exc:
            if page is not None:
                try:
                    if not page.is_closed():
                        page.close()
                except PlaywrightError:
                    pass
                if page in self._owned_pages:
                    self._owned_pages.remove(page)
            raise BrowserError("No se pudo abrir la página: " + str(exc)) from exc
        return page

    def switch_to(self, page):
        if page not in self._owned_pages or page.is_closed():
            raise BrowserError("La pestaña no pertenece a esta sesión o ya está cerrada")
        page.bring_to_front()
        return page

    def close(self):
        try:
            if self.context is not None:
                try:
                    self.context.close()
                except PlaywrightError:
                    logger.warning("Brave ya estaba cerrado o desconectado")
            if self._browser is not None:
                try:
                    # browser.close() sobre CDP desconecta; Browser.close cierra
                    # la instancia propia de forma ordenada, incluido su perfil.
                    self._browser.new_browser_cdp_session().send("Browser.close")
                except PlaywrightError:
                    pass
                try:
                    self._browser.close()
                except PlaywrightError:
                    pass
        finally:
            self.context = None
            self._browser = None
            self._owned_pages.clear()
            try:
                if self._playwright is not None:
                    self._playwright.stop()
            finally:
                self._playwright = None
                try:
                    if self._process is not None and self._process.poll() is None:
                        try:
                            self._process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            self._process.terminate()
                            self._process.wait(timeout=5)
                finally:
                    self._process = None
                    self._lock.release()

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()
