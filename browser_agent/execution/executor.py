import time
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

    def _find_unique_element(self, target: str):
        # Use self.page directly (avoid self.observer.page attribute error)
        page = self.page
        if not page or page.is_closed():
            raise ExecutionError("Browser page is closed")

        clean_target = target.strip()

        # Build candidate locator queries ordered by specificity
        locators_to_try = [
            page.get_by_role("button", name=clean_target, exact=False),
            page.get_by_role("link", name=clean_target, exact=False),
            page.locator(f"button:has-text('{clean_target}')"),
            page.locator(f"a:has-text('{clean_target}')"),
            page.locator(f"[role='button']:has-text('{clean_target}')"),
            page.locator(f".card:has-text('{clean_target}')"),
            page.locator(f"div:has-text('{clean_target}')"),
            page.get_by_text(clean_target, exact=False),
        ]

        for locator in locators_to_try:
            try:
                count = locator.count()
                if count > 0:
                    for i in range(count):
                        cand = locator.nth(i)
                        # Ensure the candidate is rendered and attached
                        if cand.is_visible():
                            return cand
            except Exception:
                continue

        # XPath fallback for deeply nested text nodes in Angular/React cards
        try:
            xpath_cand = page.locator(f"//*[contains(normalize-space(text()), '{clean_target}')]")
            count = xpath_cand.count()
            for i in range(count):
                cand = xpath_cand.nth(i)
                if cand.is_visible():
                    return cand
        except Exception:
            pass

        raise ExecutionError(f"No button or link found with name: {target}")

    def execute(self, action_data, user_approved=False):
        if self.page.is_closed():
            raise ExecutionError("Browser page is closed")

        # Validate action
        try:
            action = validate_action(action_data)
        except Exception as error:
            raise ExecutionError(
                "Action schema validation failed"
            ) from error

        # Authorize action
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

        if action_name in {"request_user_input", "request_approval"}:
            return {
                "status": "user_interaction_required",
                "action": action_name,
                "target": action["target"]
            }

        if action_name == "fill":
            if self.form_filler is None:
                raise ExecutionError("Local form filling is not configured")

            try:
                result = self.form_filler.fill(
                    field_ref=action["target"],
                    value_ref=action["parameters"]["value_ref"]
                )
            except FormFillerError as error:
                raise ExecutionError("Form filling failed") from error

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

        # Locate and click the target element
        element = self._find_unique_element(action["target"])

        try:
            # Scroll into viewport to avoid click interception from sticky headers
            element.scroll_into_view_if_needed()
            element.click(timeout=8000)
            # Give the portal SPA 2 seconds to initiate page or modal transition
            time.sleep(2.0)
        except Exception as error:
            raise ExecutionError(
                f"Browser click failed: {error}"
            ) from error

        return {
            "status": "executed",
            "action": "click",
            "target": action["target"]
        }