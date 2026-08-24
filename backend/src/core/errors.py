class ConfigurationError(RuntimeError):
    """Raised when application configuration is incomplete or unsafe."""


class AuthenticationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ApplicationError(RuntimeError):
    """공개 계약의 code와 HTTP 상태로 변환되는 application 오류."""

    status_code = 400

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NotFoundError(ApplicationError):
    status_code = 404

    def __init__(self, message: str = "resource is not found") -> None:
        super().__init__("NOT_FOUND", message)


class RowVersionConflictError(ApplicationError):
    status_code = 409

    def __init__(self, message: str = "row_version does not match the stored value") -> None:
        super().__init__("ROW_VERSION_CONFLICT", message)


class ValidationError(ApplicationError):
    status_code = 422

    def __init__(self, message: str, code: str = "VALIDATION_FAILED") -> None:
        super().__init__(code, message)


class PrivacyConsentRequiredError(ValidationError):
    def __init__(self, message: str = "privacy consent is required") -> None:
        super().__init__(message, code="PRIVACY_CONSENT_REQUIRED")


class F2UnavailableError(ApplicationError):
    status_code = 503

    def __init__(self, message: str = "voice analysis is temporarily unavailable") -> None:
        super().__init__("F2_UNAVAILABLE", message)


class F2ProcessingError(ApplicationError):
    status_code = 502

    def __init__(self, message: str = "voice analysis failed") -> None:
        super().__init__("F2_PROCESSING_FAILED", message)
