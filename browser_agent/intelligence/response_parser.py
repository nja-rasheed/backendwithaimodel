import json

from browser_agent.security.schema_validator import (
    validate_action,
    SchemaValidationError,
)


class ResponseParsingError(ValueError):
    """Raised when a model response cannot be safely parsed or validated."""


def _reject_constant(value):
    """Reject non-standard JSON values such as NaN and Infinity."""
    raise ValueError(f"Invalid JSON constant: {value}")


def _reject_duplicate_keys(pairs):
    """Reject duplicate keys instead of silently accepting the last value."""
    result = {}

    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value

    return result


def parse_model_response(raw_response: str) -> dict:
    """
    Parse a model response and validate it against the action schema.

    Args:
        raw_response: Raw JSON string returned by the model.

    Returns:
        A schema-validated action dictionary.

    Raises:
        ResponseParsingError: If parsing or validation fails.
    """

    if not isinstance(raw_response, str):
        raise ResponseParsingError("Model response must be a string.")

    if not raw_response.strip():
        raise ResponseParsingError("Model response is empty.")

    try:
        parsed_response = json.loads(
            raw_response,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ResponseParsingError(
            f"Invalid JSON response: {exc}"
        ) from exc

    if not isinstance(parsed_response, dict):
        raise ResponseParsingError(
            "Model response must be a JSON object."
        )

    try:
        validated_action = validate_action(parsed_response)
    except SchemaValidationError as exc:
        raise ResponseParsingError(
            f"Action schema validation failed: {exc}"
        ) from exc

    return validated_action