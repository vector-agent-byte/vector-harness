"""Application errors translated by entrypoint adapters."""


class ServiceError(Exception):
    def __init__(self, code: str, message: str | None = None, fields: dict | None = None):
        super().__init__(message or code)
        self.code = code
        self.fields = fields
