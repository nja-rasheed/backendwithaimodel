from browser_agent.execution.field_registry import (
    FieldRegistry,
    FieldRegistryError,
)
from browser_agent.execution.value_provider import (
    LocalValueProvider,
    ValueProviderError,
)


class FormFillerError(Exception):
    """Raised when a form field cannot be safely filled."""
    pass


class FormFiller:

    ALLOWED_INPUT_TYPES = {
        "text",
        "date",
        "email",
        "tel",
    }

    def __init__(self, registry, value_provider):

        if not isinstance(registry, FieldRegistry):
            raise FormFillerError("Invalid field registry")

        if not isinstance(value_provider, LocalValueProvider):
            raise FormFillerError("Invalid value provider")

        self.registry = registry
        self.value_provider = value_provider

    def fill(self, field_ref, value_ref):

        # Resolve the live browser element.
        try:
            element = self.registry.resolve(field_ref)
        except FieldRegistryError as error:
            raise FormFillerError(
                "Field could not be safely resolved"
            ) from error

        # Read only field metadata, never its existing value.
        tag = element.evaluate(
            "element => element.tagName.toLowerCase()"
        )

        input_type = element.get_attribute("type") or "text"

        if tag == "input" and input_type not in self.ALLOWED_INPUT_TYPES:
            raise FormFillerError("Unsupported input type")

        if tag not in {"input", "textarea", "select"}:
            raise FormFillerError("Unsupported form element")

        # Resolve the actual value locally.
        try:
            value = self.value_provider.resolve(value_ref)
        except ValueProviderError as error:
            raise FormFillerError(
                "Local value resolution failed"
            ) from error

        # Fill only supported controls.
        try:
            if tag == "select":
                element.select_option(
                    value=value,
                    timeout=5000
                )
            else:
                element.fill(
                    value,
                    timeout=5000
                )

            # Verify locally without returning or logging the value.
            if tag == "select":
                actual_value = element.input_value()
            else:
                actual_value = element.input_value()

            if actual_value != value:
                raise FormFillerError(
                    "Form filling verification failed"
                )

        except FormFillerError:
            raise

        except Exception as error:
            raise FormFillerError(
                "Browser form filling failed"
            ) from error

        return {
            "status": "filled",
            "field_ref": field_ref,
            "verified": True,
        }