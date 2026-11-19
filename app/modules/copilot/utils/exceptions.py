from app.common.exceptions import AppError, NotFoundError, ServiceUnavailableError


class CopilotUnavailableError(ServiceUnavailableError):
    code = "copilot_unavailable"
    message = "The assistant cannot answer right now"


class VoiceUnavailableError(ServiceUnavailableError):
    code = "voice_unavailable"
    message = "Voice is not available right now"


class ConversationNotFoundError(NotFoundError):
    code = "conversation_not_found"
    message = "No such conversation"


class MessageNotFoundError(NotFoundError):
    code = "message_not_found"
    message = "No such answer"


class PlanNotFoundError(NotFoundError):
    code = "plan_not_found"
    message = "No such plan"


class RateLimitedError(AppError):
    status_code = 429
    code = "copilot_rate_limited"
    message = "Too many questions in a minute; try again shortly"
