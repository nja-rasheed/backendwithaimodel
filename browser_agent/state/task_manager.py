import uuid
from datetime import datetime, timezone


class TaskManagerError(Exception):
    pass


class TaskManager:

    def __init__(self):
        self.current_task = None
        self.history = []

    def mark_step_limit_reached(self):
        if self.current_task is None:
            raise TaskManagerError("No active task")

        self.current_task["status"] = "step_limit_reached"

    def start_task(self, description):

        if not isinstance(description, str) or not description.strip():
            raise TaskManagerError("Task description is required")

        task = {
            "task_id": str(uuid.uuid4()),
            "description": description.strip(),
            "status": "running",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "actions": [],
        }

        self.current_task = task
        self.history.append(task)

        return task["task_id"]

    def record_action(self, action, execution, verification=None):

        if self.current_task is None:
            raise TaskManagerError("No active task")

        record = {
            "action": action,
            "execution": execution,
            "verification": verification,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self.current_task["actions"].append(record)

    def complete_task(self):

        if self.current_task is None:
            raise TaskManagerError("No active task")

        self.current_task["status"] = "completed"

    def fail_task(self):

        if self.current_task is None:
            raise TaskManagerError("No active task")

        self.current_task["status"] = "failed"

    def get_current_task(self):

        return self.current_task

    def clear_current_task(self):

        self.current_task = None