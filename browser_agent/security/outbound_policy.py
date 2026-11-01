from browser_agent.security.privacy_guard import (
    validate_llm_payload,
    PrivacyViolation
)
import re

class OutboundPolicyError(Exception):
    """Raised when webpage data violates outbound security rules."""
    pass


# Strict limits on information sent to Gemini.
MAX_TITLE_LENGTH = 200
MAX_TEXT_LENGTH = 500
MAX_HEADINGS = 30
MAX_BUTTONS = 50
MAX_LINKS = 50
MAX_INPUT_FIELDS = 50

# Input types that must never be forwarded to the LLM.
FORBIDDEN_INPUT_TYPES = {
    "password",
    "file",
    "hidden",
}
FIELD_REF_PATTERN = re.compile(r"field_\d{4}")

ALLOWED_FIELD_CATEGORIES = {
    "PUBLIC",
    "PERSONAL"
}


def _validate_string(value, field_name, max_length=MAX_TEXT_LENGTH):
    """Validate string type and maximum length."""

    if not isinstance(value, str):
        raise OutboundPolicyError(
            f"{field_name} must be a string"
        )

    if len(value) > max_length:
        raise OutboundPolicyError(
            f"{field_name} exceeds maximum length"
        )

    return value


def build_outbound_payload(sanitized_observation):
    """
    Construct a strictly allowlisted payload for Gemini.

    Only approved webpage metadata is included.
    Unknown fields and sensitive input types are rejected.
    """

    if not isinstance(sanitized_observation, dict):
        raise OutboundPolicyError(
            "Observation must be a dictionary"
        )

    # First validate the existing privacy guard.
    try:
        validate_llm_payload(sanitized_observation)

    except PrivacyViolation as error:
        raise OutboundPolicyError(
            "Privacy validation failed"
        ) from error

    expected_keys = {
        "title",
        "headings",
        "buttons",
        "links",
        "input_fields",
        "security"
    }

    if set(sanitized_observation.keys()) != expected_keys:
        raise OutboundPolicyError(
            "Unexpected or missing observation fields"
        )

    title = _validate_string(
        sanitized_observation["title"],
        "title",
        MAX_TITLE_LENGTH
    )

    headings = sanitized_observation["headings"]
    buttons = sanitized_observation["buttons"]
    links = sanitized_observation["links"]
    input_fields = sanitized_observation["input_fields"]

    # Validate collection types.
    if not isinstance(headings, list):
        raise OutboundPolicyError(
            "Headings must be a list"
        )

    if not isinstance(buttons, list):
        raise OutboundPolicyError(
            "Buttons must be a list"
        )

    if not isinstance(links, list):
        raise OutboundPolicyError(
            "Links must be a list"
        )

    if not isinstance(input_fields, list):
        raise OutboundPolicyError(
            "Input fields must be a list"
        )

    # Enforce collection limits.
    if len(headings) > MAX_HEADINGS:
        raise OutboundPolicyError(
            "Too many headings"
        )

    if len(buttons) > MAX_BUTTONS:
        raise OutboundPolicyError(
            "Too many buttons"
        )

    if len(links) > MAX_LINKS:
        raise OutboundPolicyError(
            "Too many links"
        )

    if len(input_fields) > MAX_INPUT_FIELDS:
        raise OutboundPolicyError(
            "Too many input fields"
        )

    # Validate headings.
    safe_headings = []

    for heading in headings:
        safe_headings.append(
            _validate_string(
                heading,
                "heading"
            )
        )

    # Validate buttons.
    safe_buttons = []

    for button in buttons:

        if not isinstance(button, dict):
            raise OutboundPolicyError(
                "Invalid button structure"
            )

        if set(button.keys()) != {"text", "disabled"}:
            raise OutboundPolicyError(
                "Unexpected button metadata"
            )

        if not isinstance(button["disabled"], bool):
            raise OutboundPolicyError(
                "Invalid button state"
            )

        safe_buttons.append({
            "text": _validate_string(
                button["text"],
                "button text"
            ),
            "disabled": button["disabled"]
        })

    # Validate links.
    safe_links = []

    for link in links:

        if not isinstance(link, dict):
            raise OutboundPolicyError(
                "Invalid link structure"
            )

        if set(link.keys()) != {"text", "visible"}:
            raise OutboundPolicyError(
                "Unexpected link metadata"
            )

        if not isinstance(link["visible"], bool):
            raise OutboundPolicyError(
                "Invalid link visibility"
            )

        safe_links.append({
            "text": _validate_string(
                link["text"],
                "link text"
            ),
            "visible": link["visible"]
        })

    # Validate input fields.
    # Validate input fields.
    safe_fields = []
    seen_references = set()

    for field in input_fields:

        if not isinstance(field, dict):
            raise OutboundPolicyError(
                "Invalid input field"
            )

        expected_field_keys = {
            "field_ref",
            "category",
            "type",
            "required",
            "disabled"
        }

        if set(field.keys()) != expected_field_keys:
            raise OutboundPolicyError(
                "Unexpected input field metadata"
            )

        field_ref = field["field_ref"]

        if (
            not isinstance(field_ref, str)
            or not FIELD_REF_PATTERN.fullmatch(field_ref)
        ):
            raise OutboundPolicyError(
                "Invalid field reference"
            )

        if field_ref in seen_references:
            raise OutboundPolicyError(
                "Duplicate field reference"
            )

        seen_references.add(field_ref)

        category = field["category"]

        if category not in ALLOWED_FIELD_CATEGORIES:
            raise OutboundPolicyError(
                "Invalid field category"
            )

        input_type = _validate_string(
            field["type"],
            "input type",
            30
        ).strip().lower()

        if input_type in FORBIDDEN_INPUT_TYPES:
            raise OutboundPolicyError(
                "Sensitive input type is not allowed"
            )

        if not isinstance(field["required"], bool):
            raise OutboundPolicyError(
                "Invalid required state"
            )

        if not isinstance(field["disabled"], bool):
            raise OutboundPolicyError(
                "Invalid disabled state"
            )

        safe_fields.append({
            "field_ref": field_ref,
            "category": category,
            "type": input_type,
            "required": field["required"],
            "disabled": field["disabled"]
        })

    # Construct a completely new object.
    # Never forward the original observation directly.
    # Security metadata is deliberately excluded.
    return {
        "title": title,
        "headings": safe_headings,
        "buttons": safe_buttons,
        "links": safe_links,
        "input_fields": safe_fields
    }