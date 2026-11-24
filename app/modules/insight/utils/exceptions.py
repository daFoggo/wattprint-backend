from decimal import Decimal


class WatchError(ValueError):
    """A watch request that cannot be stored; `code` tells the assistant why."""

    def __init__(self, code: str, message: str, value: Decimal | None = None) -> None:
        super().__init__(message)
        self.code, self.value = code, value


class PlanError(ValueError):
    """A savings plan request that cannot be stored; `code` tells the client why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
