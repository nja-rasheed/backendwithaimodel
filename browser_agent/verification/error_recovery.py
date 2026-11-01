from enum import Enum


class RecoveryDecision(str, Enum):
    RETRY = "retry"
    REPLAN = "replan"
    ASK_USER = "ask_user"
    STOP = "stop"


class ErrorRecovery:
    def __init__(self, max_retries=2):
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")

        self.max_retries = max_retries
        self.retry_counts = {}

    def decide(self, action_key, verification_status):
        if not isinstance(action_key, str) or not action_key.strip():
            raise ValueError("action_key is required")

        if verification_status == "success":
            self.retry_counts.pop(action_key, None)
            return RecoveryDecision.STOP

        if verification_status == "uncertain":
            return RecoveryDecision.ASK_USER

        if verification_status != "failure":
            raise ValueError("Unknown verification status")

        retries = self.retry_counts.get(action_key, 0)

        if retries < self.max_retries:
            self.retry_counts[action_key] = retries + 1
            return RecoveryDecision.RETRY

        return RecoveryDecision.REPLAN

    def reset(self):
        self.retry_counts.clear()