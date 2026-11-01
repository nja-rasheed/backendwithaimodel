import json
import os
import re
import uuid

from datetime import datetime, timezone
from pathlib import Path


class AuditLoggerError(Exception):
    """Raised when an audit event cannot be safely recorded."""
    pass


# Only predefined event types are accepted.
ALLOWED_EVENT_TYPES = {
    "action_proposed",
    "action_approved",
    "action_rejected",
    "execution_started",
    "execution_succeeded",
    "execution_failed",
    "verification_succeeded",
    "verification_failed",
    "task_started",
    "task_completed",
    "task_failed",
}

ALLOWED_OUTCOMES = {
    "success",
    "failure",
    "pending",
    "rejected",
}

ALLOWED_COMPONENTS = {
    "agent",
    "intelligence",
    "security",
    "execution",
    "verification",
    "state",
}

ALLOWED_ACTIONS = {
    "navigate",
    "click",
    "fill",
    "wait",
    "request_user_input",
    "request_approval",
    "stop",
    "none",
}

ALLOWED_REASON_CODES = {
    "none",
    "schema_invalid",
    "privacy_violation",
    "domain_not_allowed",
    "approval_required",
    "approval_granted",
    "approval_denied",
    "execution_error",
    "verification_failed",
    "user_cancelled",
}


class AuditLogger:

    def __init__(self, log_path="data/audit.jsonl"):
        """
        Initialize the audit logger.

        Each event is stored as one JSON object per line.
        """

        self.log_path = Path(log_path)

        try:
            self.log_path.parent.mkdir(
                parents=True,
                exist_ok=True
            )
        except OSError as error:
            raise AuditLoggerError(
                "Unable to initialize audit directory"
            ) from error

    @staticmethod
    def _validate_task_id(task_id):
        """
        Accept only UUID-based task identifiers.

        This prevents arbitrary user information from being
        inserted into the task identifier field.
        """

        if not isinstance(task_id, str):
            raise AuditLoggerError(
                "Task ID must be a string"
            )

        try:
            return str(uuid.UUID(task_id))
        except ValueError as error:
            raise AuditLoggerError(
                "Task ID must be a valid UUID"
            ) from error

    def log_event(
        self,
        event_type,
        outcome,
        component,
        action="none",
        reason_code="none",
        task_id=None,
    ):
        """
        Record a structured security event.

        Arbitrary text, webpage content, URLs, credentials,
        and user-provided values are deliberately not accepted.
        """

        if event_type not in ALLOWED_EVENT_TYPES:
            raise AuditLoggerError(
                "Unsupported event type"
            )

        if outcome not in ALLOWED_OUTCOMES:
            raise AuditLoggerError(
                "Unsupported event outcome"
            )

        if component not in ALLOWED_COMPONENTS:
            raise AuditLoggerError(
                "Unsupported component"
            )

        if action not in ALLOWED_ACTIONS:
            raise AuditLoggerError(
                "Unsupported action"
            )

        if reason_code not in ALLOWED_REASON_CODES:
            raise AuditLoggerError(
                "Unsupported reason code"
            )

        if task_id is not None:
            task_id = self._validate_task_id(task_id)

        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "task_id": task_id,
            "event_type": event_type,
            "outcome": outcome,
            "component": component,
            "action": action,
            "reason_code": reason_code,
        }

        try:
            serialized = (
                json.dumps(event, separators=(",", ":")) + "\n"
            ).encode("utf-8")

            # Open with restrictive permissions on POSIX systems.
            flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY

            fd = os.open(
                self.log_path,
                flags,
                0o600
            )

            try:
                if os.name == "posix":
                    os.fchmod(fd, 0o600)

                with os.fdopen(fd, "ab") as log_file:
                    fd = -1
                    log_file.write(serialized)
                    log_file.flush()
                    os.fsync(log_file.fileno())

            finally:
                if fd != -1:
                    os.close(fd)

        except OSError as error:
            raise AuditLoggerError(
                "Unable to write audit event"
            ) from error

        return event["event_id"]