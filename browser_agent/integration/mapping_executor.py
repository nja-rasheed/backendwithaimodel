"""Safely convert approved field mappings into local browser actions."""

from browser_agent.integration.mapping_adapter import (
    MappingAdapter,
    MappingAdapterError,
)


class MappingExecutionError(Exception):
    """Raised when an approved mapping cannot be executed."""


class MappingExecutor:

    def __init__(self, browser_executor, mapping_adapter=None):
        if browser_executor is None:
            raise MappingExecutionError("Browser executor is required")

        self.browser_executor = browser_executor
        self.mapping_adapter = mapping_adapter or MappingAdapter()

    def execute_mapping(
        self,
        mapping,
        user_approved=False,
    ):
        if not isinstance(mapping, dict):
            raise MappingExecutionError("Invalid mapping")

        if mapping.get("approved") is not True:
            raise MappingExecutionError(
                "Human approval of the mapping is required"
            )

        request_field = mapping.get("request_field")
        visible_field = mapping.get("visible_field")

        if not isinstance(request_field, str):
            raise MappingExecutionError("Invalid request field")

        if not isinstance(visible_field, str):
            raise MappingExecutionError("Invalid visible field")

        value_reference = self.mapping_adapter.FIELD_ALIASES.get(
            request_field
        )

        if value_reference is None:
            raise MappingExecutionError("Unsupported backend field")

        provider = self.browser_executor.value_provider

        if provider is None or not provider.is_approved(value_reference):
            raise MappingExecutionError(
                "Personal data use has not been approved"
            )

        if not user_approved:
            return {
                "status": "awaiting_user_approval",
                "field_ref": visible_field,
                "request_field": request_field,
            }

        action = {
            "action": "fill",
            "target": visible_field,
            "parameters": {"value_ref": value_reference},
            "reason": "Execute an approved field mapping",
        }

        try:
            result = self.browser_executor.execute(
                action,
                user_approved=True,
            )
        except Exception as error:
            raise MappingExecutionError(
                "Approved mapping execution failed"
            ) from error

        return {
            "status": result.get("status"),
            "field_ref": visible_field,
            "request_field": request_field,
            "verified": result.get("verified", False),
        }