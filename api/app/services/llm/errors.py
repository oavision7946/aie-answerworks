"""User-safe messages and the exception types shared by the provider layer."""

NOT_CONFIGURED = "The AI service is not configured. Please contact support."
UNAVAILABLE = "The AI service is temporarily unavailable. Please try again shortly."
FAILED = "The AI service could not complete your request. Please try again."
INCOMPLETE = "The AI service returned an incomplete response. Please try again."
UNUSABLE = "The AI service returned an unusable response. Please try again."
INVALID_REQUEST = "Invalid request. Check the question and selected model, then try again."


class ProviderError(Exception):
    """A provider call failed. Adapters raise this (never SDK exceptions) to the service layer."""


class TransientProviderError(ProviderError):
    """Worth retrying: timeouts, connection errors, rate limits, 5xx."""


class IncompleteResponseError(ProviderError):
    """The provider answered but the payload lacked text or usage."""


class LLMServiceError(Exception):
    """A failure with a user-safe message and the HTTP status the API should return."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
