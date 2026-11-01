from browser_agent.security.schema_validator import validate_action
from browser_agent.security.action_validator import (
    authorize_action,
    ApprovalRequiredError,
)
from browser_agent.execution.field_registry import (
    FieldRegistry,
    FieldRegistryError,
)

from browser_agent.execution.form_filler import (
    FormFiller,
    FormFillerError,
)

from browser_agent.execution.value_provider import LocalValueProvider

class ExecutionError(Exception):
    """Raised when a browser action cannot be safely executed."""
    pass


class BrowserExecutor:

    def __init__(
        self,
        page,
        allowed_domains,
        value_provider=None,
        allow_local_test_server=False
    ):
        if page is None:
            raise ExecutionError("A valid Playwright page is required")

        if value_provider is not None and not isinstance(
            value_provider, LocalValueProvider
        ):
            raise ExecutionError("Invalid local value provider")

        self.page = page
        self.allowed_domains = allowed_domains
        self.allow_local_test_server = allow_local_test_server
        self.field_registry = FieldRegistry(page)
        self.value_provider = value_provider

        self.form_filler = (
            FormFiller(self.field_registry, value_provider)
            if value_provider is not None
            else None
        )

    def register_observation(self, observation):

        try:
            self.field_registry.register(observation)

        except FieldRegistryError as error:
            raise ExecutionError(
                "Could not register observed form fields"
            ) from error

    def _find_unique_element(self, target):
        """
        Find exactly one button or link using its accessible name.

        Arbitrary CSS selectors and XPath are not accepted.
        """

        buttons = self.page.get_by_role(
            "button",
            name=target,
            exact=True
        )

        links = self.page.get_by_role(
            "link",
            name=target,
            exact=True
        )

        button_count = buttons.count()
        link_count = links.count()

        total_matches = button_count + link_count

        if total_matches == 0:
            raise ExecutionError(
                f"No button or link found with name: {target}"
            )

        if total_matches > 1:
            raise ExecutionError(
                f"Ambiguous target: {target}. "
                "Multiple elements matched."
            )

        element = buttons if button_count == 1 else links

        if not element.is_visible():
            raise ExecutionError(
                "Target element is not visible"
            )

        if not element.is_enabled():
            raise ExecutionError(
                "Target element is disabled"
            )

        return element

    def execute(self, action_data, user_approved=False):
        """
        Execute a schema-validated and authorized browser action.

        Currently supports:
        - click

        Other actions will be implemented separately.
        """

        if self.page.is_closed():
            raise ExecutionError("Browser page is closed")

        # Validate the model-generated action.
        try:
            action = validate_action(action_data)
        except Exception as error:
            raise ExecutionError(
                "Action schema validation failed"
            ) from error

        # Authorize the action against the current browser URL.
        try:
            authorization = authorize_action(
                action,
                allowed_domains=self.allowed_domains,
                current_url=self.page.url,
                user_approved=user_approved,
                allow_local_test_server=self.allow_local_test_server
            )

        except ApprovalRequiredError:
            return {
                "status": "user_interaction_required",
                "action": action["action"],
                "target": action["target"],
                "reason": "explicit_user_approval_required"
            }

        except Exception as error:
            raise ExecutionError(
                "Action authorization failed"
            ) from error

        if not authorization.get("allowed"):
            raise ExecutionError("Action was not authorized")

        action_name = action["action"]

        if action_name == "stop":
            return {
                "status": "stopped",
                "action": action_name
            }

        if action_name in {
            "request_user_input",
            "request_approval"
        }:
            return {
                "status": "user_interaction_required",
                "action": action_name,
                "target": action["target"]
            }

        if action_name == "fill":

            if self.form_filler is None:
                raise ExecutionError(
                    "Local form filling is not configured"
                )

            try:
                result = self.form_filler.fill(
                    field_ref=action["target"],
                    value_ref=action["parameters"]["value_ref"]
                )

            except FormFillerError as error:
                raise ExecutionError(
                    "Form filling failed"
                ) from error

            return {
                "status": "executed",
                "action": "fill",
                "field_ref": result["field_ref"],
                "verified": result["verified"],
            }

        if action_name != "click":
            raise ExecutionError(
                f"Execution not implemented for: {action_name}"
            )

        # Locate the target without accepting arbitrary selectors.
        element = self._find_unique_element(
            action["target"]
        )

        try:
            element.click(timeout=5000)
        except Exception as error:
            raise ExecutionError(
                "Browser click failed"
            ) from error

        return {
            "status": "executed",
            "action": "click",
            "target": action["target"]
        }