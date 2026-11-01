from browser_agent.security.sanitizer import SENSITIVE_PATTERNS


ALLOWED_KEYS = {
    "title",
    "headings",
    "buttons",
    "links",
    "input_fields",
    "security",
    "text",
    "visible",
    "disabled",
    "type",
    "required",
    "field_ref",
    "category",
    "personal_values_included",
    "confidential_values_included",
    "authentication_values_included"
}

class PrivacyViolation(Exception):
    pass


def validate_llm_payload(payload):
    """
    Validate sanitized data before an external LLM request.
    Reject unexpected fields and recognizable sensitive identifiers.
    """

    def inspect(value):

        if isinstance(value, dict):

            for key, item in value.items():

                if key not in ALLOWED_KEYS:
                    raise PrivacyViolation(
                        f"Unexpected payload key: {key}"
                    )

                inspect(item)

        elif isinstance(value, list):

            for item in value:
                inspect(item)

        elif isinstance(value, str):

            for pattern in SENSITIVE_PATTERNS:

                if pattern.search(value):
                    raise PrivacyViolation(
                        "Potential sensitive information detected"
                    )

        elif not isinstance(value, (bool, int, float, type(None))):

            raise PrivacyViolation(
                "Unsupported payload data type"
            )

    inspect(payload)

    security = payload.get("security", {})

    if security.get("personal_values_included") is not False:
        raise PrivacyViolation("Personal data must not be included")

    if security.get("confidential_values_included") is not False:
        raise PrivacyViolation("Confidential data must not be included")

    if security.get("authentication_values_included") is not False:
        raise PrivacyViolation("Authentication data must not be included")

    return True