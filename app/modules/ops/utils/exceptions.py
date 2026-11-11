from app.common.exceptions import NotFoundError


# LookupError kept so existing callers that catch it still work.
class MeterNotFound(NotFoundError, LookupError):  # noqa: N818 - name fixed by the task contract
    code = "meter_not_found"
    message = "Meter not found"
