class ConfigurationError(RuntimeError):
    """Raised when application configuration is incomplete or unsafe."""


class AuthenticationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
