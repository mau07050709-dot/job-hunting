class AutoJobError(RuntimeError):
    """Error operativo con mensaje apto para mostrar al usuario."""


class BrowserError(AutoJobError):
    pass


class ProfileInUse(BrowserError):
    pass
