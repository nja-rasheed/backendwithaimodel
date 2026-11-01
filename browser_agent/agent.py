from browser_agent.perception.observer import BrowserObserver
from browser_agent.execution.executor import BrowserExecutor

from browser_agent.intelligence.decision_engine import DecisionEngine

from browser_agent.verification.verifier import ActionVerifier
from browser_agent.verification.error_recovery import (
    ErrorRecovery,
    RecoveryDecision,
)

from browser_agent.state.task_manager import TaskManager

from browser_agent.integration.mapping_executor import (
    MappingExecutor,
    MappingExecutionError,
)


class BrowserAgentError(Exception):
    pass


class BrowserAgent:

    def __init__(
        self,
        allowed_domains,
        model="gemini-flash-lite-latest",
        value_provider=None,
        allow_local_test_server=False,
        api_key=None
    ):

        self.observer = BrowserObserver(allowed_domains)
        self.decision_engine = DecisionEngine(
            model=model,
            api_key=api_key
        )

        self.executor = None

        self.verifier = ActionVerifier()
        self.recovery = ErrorRecovery(max_retries=2)
        self.task_manager = TaskManager()
        self.value_provider = value_provider
        self.mapping_executor = None
        self.pending_action = None
        self.pending_observation = None
        self.pending_url = None
        self.allow_local_test_server = allow_local_test_server

    def start(self):

        page = self.observer.start()

        self.executor = BrowserExecutor(
            page=page,
            allowed_domains=self.observer.allowed_domains,
            value_provider=self.value_provider,
            allow_local_test_server=self.allow_local_test_server
        )

        # MappingExecutor only prepares trusted local fill actions.
        # Final execution still goes through approve_pending_action().
        self.mapping_executor = (
            MappingExecutor(self.executor)
            if self.value_provider is not None
            else None
        )

    def navigate(self, url):

        return self.observer.navigate(url)

    def start_task(self, description):

        if self.task_manager.current_task is not None:
            raise BrowserAgentError("A task is already active")

        self.recovery.reset()

        return self.task_manager.start_task(description)

    def approve_pending_action(self):

        if self.executor is None:
            raise BrowserAgentError("Agent has not started")

        if self.pending_action is None:
            raise BrowserAgentError("No action is awaiting approval")

        action = self.pending_action
        previous_observation = self.pending_observation
        previous_url = self.pending_url

        # Prevent approval if the browser navigated elsewhere.
        if self.executor.page.url != previous_url:
            self.reject_pending_action()
            raise BrowserAgentError(
                "Browser URL changed. Action approval cancelled."
            )

        # Refresh the observation before executing.
        current_observation = self.observer.observe()

        # For filling, ensure the observed fields have not changed.
        if action["action"] == "fill":
            if (
                current_observation.get("input_fields")
                != previous_observation.get("input_fields")
            ):
                self.reject_pending_action()
                raise BrowserAgentError(
                    "Form fields changed. Request a new action."
                )

        self.executor.register_observation(current_observation)

        # Clear pending state before execution to prevent replay.
        self.pending_action = None
        self.pending_observation = None
        self.pending_url = None

        try:
            result = self.executor.execute(
                action,
                user_approved=True
            )
        except Exception:
            self.task_manager.fail_task()
            raise

        if result.get("status") != "executed":
            return {
                "status": result.get("status"),
                "action": action["action"],
                "result": result
            }

        verification = None

        if action["action"] == "click":
            after_observation = self.observer.observe()

            verification = self.verifier.verify_click(
                before_observation=current_observation,
                after_observation=after_observation,
                target=action["target"],
                execution_result=result
            )

        elif action["action"] == "fill":
            verification = {
                "status": (
                    "success"
                    if result.get("verified") is True
                    else "failure"
                )
            }

        self.task_manager.record_action(
            action={"type": action["action"]},
            execution={"status": result.get("status")},
            verification=verification
        )

        return {
            "status": "executed",
            "action": action["action"],
            "result": result,
            "verification": verification
        }

    def reject_pending_action(self):

        if self.pending_action is None:
            raise BrowserAgentError("No action is awaiting rejection")

        action_name = self.pending_action["action"]

        # Discard the proposal permanently.
        self.pending_action = None
        self.pending_observation = None
        self.pending_url = None

        self.task_manager.record_action(
            action={"type": action_name},
            execution={"status": "rejected"},
            verification=None
        )

        self.task_manager.fail_task()

        return {
            "status": "rejected",
            "action": action_name
        }

    def run_step(self, task):

        if self.executor is None:
            raise BrowserAgentError("Agent has not started")

        # Start task tracking if necessary.
        if self.task_manager.current_task is None:
            self.start_task(task)

        task_id = self.task_manager.current_task["task_id"]

        # 1. Observe the current browser state.
        before_observation = self.observer.observe()
        self.executor.register_observation(before_observation)

        # 2. Ask the model to select one action.
        action = self.decision_engine.decide(
            task=task,
            observation=before_observation
        )

        action_name = action["action"]

        # 3. Execute the authorized action.
        try:

            execution_result = self.executor.execute(action)

        except Exception as error:

            import traceback
            traceback.print_exc()

            execution_result = {
                "status": "failed",
                "reason": f"{type(error).__name__}: {error}"
            }

            recovery_decision = self.recovery.decide(
                action_key=action_name,
                verification_status="failure"
            )

            self.task_manager.record_action(
                action={"type": action_name},
                execution=execution_result,
                verification=None
            )

            return {
                "task_id": task_id,
                "action": action_name,
                "result": execution_result,
                "recovery": recovery_decision.value
            }

        # 4. Handle explicit stop.
        if execution_result.get("status") == "stopped":

            self.task_manager.record_action(
                action={"type": action_name},
                execution={"status": "stopped"},
                verification=None
            )

            self.task_manager.complete_task()

            return {
                "task_id": task_id,
                "action": action_name,
                "result": execution_result,
                "task_status": "completed"
            }

        # 5. Handle actions requiring user interaction.
        if execution_result.get("status") == "user_interaction_required":

            # Store only actions explicitly blocked pending approval.
            if execution_result.get("reason") == "explicit_user_approval_required":

                if self.pending_action is not None:
                    raise BrowserAgentError(
                        "Another action is already awaiting approval"
                    )

                self.pending_action = action.copy()
                self.pending_observation = before_observation
                self.pending_url = self.observer.page.url if hasattr(
                    self.observer, "page"
                ) else self.executor.page.url

            self.task_manager.record_action(
                action={"type": action_name},
                execution={"status": "user_interaction_required"},
                verification=None
            )

            return {
                "task_id": task_id,
                "action": action_name,
                "result": execution_result,
                "task_status": "awaiting_user"
            }

        # 6. Verify successful click execution.
        verification_result = None
        recovery_decision = None

        if action_name == "click":

            after_observation = self.observer.observe()

            verification_result = self.verifier.verify_click(
                before_observation=before_observation,
                after_observation=after_observation,
                target=action["target"],
                execution_result=execution_result
            )

            verification_status = verification_result["status"]

            if verification_status == "uncertain":

                recovery_decision = self.recovery.decide(
                    action_key=action_name,
                    verification_status="uncertain"
                )

            elif verification_status == "failure":

                recovery_decision = self.recovery.decide(
                    action_key=action_name,
                    verification_status="failure"
                )

        # 7. Record only minimal action metadata.
        # Never store actual form values or webpage contents here.
        self.task_manager.record_action(
            action={"type": action_name},
            execution={"status": execution_result.get("status")},
            verification=verification_result
        )

        # 8. Return the complete step result.
        return {
            "task_id": task_id,
            "action": action_name,
            "result": execution_result,
            "verification": verification_result,
            "recovery": (
                recovery_decision.value
                if recovery_decision is not None
                else None
            ),
            "task_status": self.task_manager.current_task["status"]
        }

    def run_task(self, task, max_steps=10):

        if self.executor is None:
            raise BrowserAgentError("Agent has not started")

        if not isinstance(max_steps, int) or isinstance(max_steps, bool):
            raise BrowserAgentError("max_steps must be an integer")

        if not 1 <= max_steps <= 20:
            raise BrowserAgentError("max_steps must be between 1 and 20")

        if not isinstance(task, str) or not task.strip():
            raise BrowserAgentError("Task description is required")

        if self.task_manager.current_task is not None:
            raise BrowserAgentError("Another task is already active")

        self.start_task(task)

        task_id = self.task_manager.current_task["task_id"]
        step_results = []

        for step_number in range(1, max_steps + 1):

            try:
                result = self.run_step(task)
            except Exception:
                self.task_manager.fail_task()

                return {
                    "task_id": task_id,
                    "status": "failed",
                    "reason": "An unexpected agent error occurred",
                    "steps_completed": len(step_results),
                }

            step_results.append(result)

            # Stop if the model explicitly ends the task.
            if result.get("task_status") == "completed":
                return {
                    "task_id": task_id,
                    "status": "completed",
                    "steps_completed": step_number,
                    "results": step_results,
                }

            # Stop when human intervention is needed.
            if result.get("task_status") == "awaiting_user":
                return {
                    "task_id": task_id,
                    "status": "awaiting_user",
                    "steps_completed": step_number,
                    "results": step_results,
                }

            # Stop when execution fails.
            if result.get("result", {}).get("status") == "failed":
                self.task_manager.fail_task()

                return {
                    "task_id": task_id,
                    "status": "failed",
                    "steps_completed": step_number,
                    "results": step_results,
                }

            # Do not continue when verification is uncertain.
            verification = result.get("verification")

            if verification and verification.get("status") == "uncertain":
                return {
                    "task_id": task_id,
                    "status": "awaiting_user",
                    "reason": "Action outcome could not be verified",
                    "steps_completed": step_number,
                    "results": step_results,
                }

        self.task_manager.mark_step_limit_reached()

        return {
            "task_id": task_id,
            "status": "step_limit_reached",
            "steps_completed": len(step_results),
            "results": step_results,
        }

    def resume_task(self, max_steps=10):
        """Continue an existing task after an approved action."""

        if self.executor is None:
            raise BrowserAgentError("Agent has not started")

        if self.task_manager.current_task is None:
            raise BrowserAgentError("No active task to resume")

        if not isinstance(max_steps, int) or isinstance(max_steps, bool):
            raise BrowserAgentError("max_steps must be an integer")

        if not 1 <= max_steps <= 20:
            raise BrowserAgentError("max_steps must be between 1 and 20")

        if self.pending_action is not None:
            raise BrowserAgentError(
                "An action is still awaiting approval"
            )

        task = self.task_manager.current_task

        if task["status"] != "running":
            raise BrowserAgentError("Task is not in a resumable state")

        # Do not continue if the last interaction still needs user input.
        actions = task.get("actions", [])

        if actions and actions[-1]["execution"].get("status") == \
                "user_interaction_required":
            raise BrowserAgentError(
                "Resolve the pending user interaction before resuming"
            )

        task_description = task["description"]
        task_id = task["task_id"]
        step_results = []

        for step_number in range(1, max_steps + 1):

            try:
                result = self.run_step(task_description)

            except Exception:
                self.task_manager.fail_task()

                return {
                    "task_id": task_id,
                    "status": "failed",
                    "reason": "An unexpected agent error occurred",
                    "steps_completed": len(step_results),
                }

            step_results.append(result)

            if result.get("task_status") == "completed":
                return {
                    "task_id": task_id,
                    "status": "completed",
                    "steps_completed": step_number,
                    "results": step_results,
                }

            if result.get("task_status") == "awaiting_user":
                return {
                    "task_id": task_id,
                    "status": "awaiting_user",
                    "steps_completed": step_number,
                    "results": step_results,
                }

            if result.get("result", {}).get("status") == "failed":
                self.task_manager.fail_task()

                return {
                    "task_id": task_id,
                    "status": "failed",
                    "steps_completed": step_number,
                    "results": step_results,
                }

            verification = result.get("verification")

            if verification and verification.get("status") == "uncertain":
                return {
                    "task_id": task_id,
                    "status": "awaiting_user",
                    "reason": "Action outcome could not be verified",
                    "steps_completed": step_number,
                    "results": step_results,
                }

        self.task_manager.mark_step_limit_reached()

        return {
            "task_id": task_id,
            "status": "step_limit_reached",
            "steps_completed": len(step_results),
            "results": step_results,
        }

    def prepare_approved_mapping(self, mapping):
        """
        Validate an approved field mapping and stage its fill action.

        This method does not fill the field. The caller must obtain the
        user's browser-action approval by calling approve_pending_action().
        """

        if self.executor is None:
            raise BrowserAgentError("Agent has not started")

        if self.mapping_executor is None:
            raise BrowserAgentError(
                "Local value provider is not configured"
            )

        if self.pending_action is not None:
            raise BrowserAgentError(
                "Another browser action is already awaiting approval"
            )

        if not isinstance(mapping, dict):
            raise BrowserAgentError("Invalid field mapping")

        # MappingExecutor checks mapping approval and the provider's own
        # approved-reference state. user_approved=False prevents execution.
        try:
            preparation = self.mapping_executor.execute_mapping(
                mapping=mapping,
                user_approved=False,
            )

        except MappingExecutionError as error:
            raise BrowserAgentError(
                "Field mapping could not be prepared"
            ) from error

        if preparation.get("status") != "awaiting_user_approval":
            raise BrowserAgentError(
                "Mapping did not enter the approval state"
            )

        request_field = mapping.get("request_field")
        visible_field = mapping.get("visible_field")

        # Build the value reference in trusted Python.
        # Never accept it from the model-generated mapping.
        value_reference = (
            self.mapping_executor.mapping_adapter.FIELD_ALIASES.get(
                request_field
            )
        )

        if value_reference is None:
            raise BrowserAgentError("Unsupported request field")

        observation = self.observer.observe()

        if not isinstance(observation, dict):
            raise BrowserAgentError(
                "Could not obtain a valid browser observation"
            )

        observed_fields = observation.get("input_fields", [])

        if not isinstance(observed_fields, list):
            raise BrowserAgentError(
                "Invalid input fields in browser observation"
            )

        current_url = self.executor.page.url

        if not current_url:
            raise BrowserAgentError(
                "Browser has no active page URL"
            )

        if not any(
            isinstance(field, dict)
            and field.get("field_ref") == visible_field
            for field in observed_fields
        ):
            raise BrowserAgentError(
                "Mapped browser field is not present in the current observation"
            )

        self.executor.register_observation(observation)

        # Ensure the existing approval/audit lifecycle has an active task.
        if self.task_manager.current_task is None:
            self.start_task("Fill approved application form fields")

        elif self.task_manager.current_task.get("status") != "running":
            raise BrowserAgentError(
                "Current task is not in a resumable state"
            )

        action = {
            "action": "fill",
            "target": visible_field,
            "parameters": {
                "value_ref": value_reference,
            },
            "reason": "Execute an approved field mapping",
        }

        self.pending_action = action
        self.pending_observation = observation
        self.pending_url = current_url

        return {
            "status": "awaiting_user_approval",
            "action": "fill",
            "request_field": request_field,
            "field_ref": visible_field,
        }

    def close(self):

        self.observer.close()
        self.executor = None
        self.mapping_executor = None