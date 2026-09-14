from core.errors import ApplicationError


class ChatConflict(ApplicationError):
    status_code = 409

    def __init__(
        self, code="CHATBOT_CONFLICT", message="다른 요청이 처리 중이거나 검색 조건이 바뀌었어요."
    ):
        super().__init__(code, message)


class ChatUnavailable(ApplicationError):
    status_code = 503

    def __init__(self):
        super().__init__(
            "CHATBOT_UNAVAILABLE", "챗봇을 사용할 수 없어요. 잠시 후 다시 시도해 주세요."
        )


class ChatBusy(ApplicationError):
    status_code = 429

    def __init__(self):
        super().__init__("CHATBOT_BUSY", "다른 질문을 처리하고 있어요. 잠시 후 다시 시도해 주세요.")
