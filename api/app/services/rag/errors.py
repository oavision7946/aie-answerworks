"""A RAG failure with a user-safe message and the HTTP status the API should return."""


class RagError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
