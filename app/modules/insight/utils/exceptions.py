from decimal import Decimal


class WatchError(ValueError):
    """A watch request that cannot be stored; `code` tells the assistant why."""

    def __init__(self, code: str, message: str, value: Decimal | None = None) -> None:
        super().__init__(message)
        self.code, self.value = code, value
