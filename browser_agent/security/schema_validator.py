class SchemaValidationError(Exception):
    """Raised when an LLM action violates the action schema."""
    pass


ALLOWED_ACTIONS = {
    "navigate",
    "click",
    "fill",
    "wait",
    "request_user_input",
    "request_approval",
    "stop",
}

MAX_TARGET_LENGTH = 500
MAX_REASON_LENGTH = 500
MAX_REFERENCE_LENGTH = 150
MAX_TIMEOUT_MS = 60000


def _validate_string(value, field_name, max_length):
    if not isinstance(value, str):
        raise SchemaValidationError(
            f"{field_name} must be a string"
        )

    value = value.strip()

    if not value:
        raise SchemaValidationError(
            f"{field_name} cannot be empty"
        )

    if len(value) > max_length:
        raise SchemaValidationError(
            f"{field_name} exceeds maximum length"
        )

    return value


def validate_action(action_data):
    """
    Validate and normalize an LLM-generated action.

    This function validates structure and permitted parameters.
    It does not authorize or execute the action.
    """

    if not isinstance(action_data, dict):
        raise SchemaValidationError("Action must be a dictionary")

    expected_keys = {
        "action",
        "target",
        "parameters",
        "reason",
    }

    if set(action_data.keys()) != expected_keys:
        raise SchemaValidationError(
            "Unexpected or missing action fields"
        )

    # 1. Validate action name
    action = action_data["action"]

    if not isinstance(action, str):
        raise SchemaValidationError(
            "Action name must be a string"
        )

    action = action.strip().lower()

    if action not in ALLOWED_ACTIONS:
        raise SchemaValidationError(
            f"Unsupported action: {action}"
        )

    # 2. Validate target
    raw_target = action_data["target"]

    if not isinstance(raw_target, str):
        raise SchemaValidationError(
            "target must be a string"
        )

    if action == "stop":
        if raw_target != "":
            raise SchemaValidationError(
                "stop action must have an empty target"
            )
        target = ""
    else:
        target = _validate_string(
            raw_target,
            "target",
            MAX_TARGET_LENGTH
        )

    # 3. Validate reason
    reason = _validate_string(
        action_data["reason"],
        "reason",
        MAX_REASON_LENGTH
    )

    # 4. Validate parameters
    parameters = action_data["parameters"]

    if not isinstance(parameters, dict):
        raise SchemaValidationError(
            "Parameters must be a dictionary"
        )

    # 5. Action-specific parameter validation
    if action in {
        "navigate",
        "click",
        "request_user_input",
        "request_approval",
        "stop",
    }:

        if parameters:
            raise SchemaValidationError(
                f"{action} does not accept parameters"
            )

        safe_parameters = {}

    elif action == "fill":

        if set(parameters.keys()) != {"value_ref"}:
            raise SchemaValidationError(
                "Fill requires exactly one value_ref parameter"
            )

        value_ref = _validate_string(
            parameters["value_ref"],
            "value_ref",
            MAX_REFERENCE_LENGTH
        )

        import re

        if not re.fullmatch(
            r"[a-zA-Z_][a-zA-Z0-9_.]*",
            value_ref
        ):
            raise SchemaValidationError(
                "Invalid value reference"
            )

        safe_parameters = {
            "value_ref": value_ref
        }

    elif action == "wait":

        if set(parameters.keys()) != {"timeout_ms"}:
            raise SchemaValidationError(
                "Wait requires exactly timeout_ms"
            )

        timeout_ms = parameters["timeout_ms"]

        if isinstance(timeout_ms, bool) or not isinstance(
            timeout_ms, int
        ):
            raise SchemaValidationError(
                "timeout_ms must be an integer"
            )

        if not 0 < timeout_ms <= MAX_TIMEOUT_MS:
            raise SchemaValidationError(
                "timeout_ms is outside the permitted range"
            )

        safe_parameters = {
            "timeout_ms": timeout_ms
        }

    return {
        "action": action,
        "target": target,
        "parameters": safe_parameters,
        "reason": reason,
    }