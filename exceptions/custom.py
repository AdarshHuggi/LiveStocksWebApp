class BusinessRuleError(Exception):
    def __init__(self, message: str):
        self.message = message


class PermissionDeniedError(Exception):
    def __init__(self, message: str):
        self.message = message
