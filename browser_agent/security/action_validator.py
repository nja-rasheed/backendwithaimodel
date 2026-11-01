import re
from urllib.parse import urlparse

from browser_agent.security.schema_validator import (
    validate_action,
    SchemaValidationError,
)


class ActionAuthorizationError(Exception):
    """Raised when an action is not authorized."""
    pass


class ApprovalRequiredError(ActionAuthorizationError):
    """Raised when an action requires explicit user approval."""
    pass


# These references must never be filled through an LLM-proposed action.
FORBIDDEN_REFERENCE_TERMS = {
    "password",
    "passcode",
    "otp",
    "token",
    "secret",
    "aadhaar",
    "pan",
    "bank",
    "account_number",
    "card_number",
    "cvv",
    "pin",
}

# Actions whose targets indicate a consequential operation.
CONSEQUENTIAL_TARGET_PATTERN = re.compile(
    r"\b(submit|finalize|pay|payment|confirm|"
    r"place order|send application|file application)\b",
    re.IGNORECASE,
)


def _host_is_allowed(hostname, allowed_domains):
    """Check whether a hostname belongs to the configured allowlist."""

    if not hostname or not isinstance(allowed_domains, (list, tuple, set)):
        return False

    hostname = hostname.lower().rstrip(".")

    for domain in allowed_domains:

        if not isinstance(domain, str):
            continue

        domain = domain.lower().strip().rstrip(".")

        if not domain:
            continue

        # Do not accept URLs or paths as allowlist entries.
        if "/" in domain or ":" in domain or "@" in domain:
            continue

        if hostname == domain or hostname.endswith("." + domain):
            return True

    return False


def _validate_https_url(
    url,
    allowed_domains,
    allow_local_test_server=False
):
    """Validate HTTPS URLs and enforce the configured domain allowlist."""

    if not isinstance(url, str):
        raise ActionAuthorizationError("URL must be a string")

    try:
        parsed = urlparse(url)
    except ValueError as error:
        raise ActionAuthorizationError("Invalid URL") from error

    if parsed.scheme.lower() != "https":
        raise ActionAuthorizationError(
            "Only HTTPS navigation is permitted"
        )

    if not parsed.hostname:
        raise ActionAuthorizationError(
            "URL must contain a hostname"
        )

    if parsed.username is not None or parsed.password is not None:
        raise ActionAuthorizationError(
            "URLs containing embedded credentials are forbidden"
        )

    try:
        port = parsed.port
    except ValueError as error:
        raise ActionAuthorizationError(
            "Invalid URL port"
        ) from error

    hostname = parsed.hostname.lower().rstrip(".")

    local_test_url = (
        allow_local_test_server is True
        and hostname == "127.0.0.1"
        and port == 8000
    )

    if port not in (None, 443) and not local_test_url:
        raise ActionAuthorizationError(
            "Non-standard HTTPS ports are forbidden"
        )

    if not local_test_url and not _host_is_allowed(
        hostname,
        allowed_domains
    ):
        raise ActionAuthorizationError(
            "Domain is not in the approved allowlist"
        )

    return hostname

def _validate_fill_reference(value_ref):
    """Reject references that point to sensitive information."""

    parts = re.split(r"[._]", value_ref.lower())

    if any(part in FORBIDDEN_REFERENCE_TERMS for part in parts):
        raise ActionAuthorizationError(
            "Sensitive data references cannot be filled through an LLM action"
        )


def authorize_action(
    action_data,
    allowed_domains,
    current_url=None,
    user_approved=False,
    allow_local_test_server=False,
):
    """
    Authorize a schema-validated action.

    This function does not execute browser actions.

    user_approved must come from a trusted application approval
    mechanism, never from the LLM response.
    """

    if not isinstance(user_approved, bool):
        raise ActionAuthorizationError(
            "User approval state must be a boolean"
        )

    try:
        action = validate_action(action_data)
    except SchemaValidationError as error:
        raise ActionAuthorizationError(
            "Action failed schema validation"
        ) from error

    action_name = action["action"]
    target = action["target"]

    # These actions do not directly interact with the browser.
    if action_name in {
        "stop",
        "request_user_input",
        "request_approval",
    }:
        return {
            "allowed": True,
            "action": action_name,
            "requires_approval": False,
        }

    
    # Navigation must validate the destination URL, not the current page.
    if action_name == "navigate":
        _validate_https_url(
            target,
            allowed_domains,
            allow_local_test_server=allow_local_test_server
        )

    else:
        # Browser interactions must occur on an approved HTTPS page.
        if current_url is None:
            raise ActionAuthorizationError(
                "Current page URL is required"
            )

        _validate_https_url(
            current_url,
            allowed_domains,
            allow_local_test_server=allow_local_test_server
        )

    # Sensitive local data references are prohibited.
    if action_name == "fill":

        _validate_fill_reference(
            action["parameters"]["value_ref"]
        )

    
    # Require explicit approval for all form filling and clicks.
    # A button's visible label alone cannot establish whether
    # clicking it has consequential effects.
    requires_approval = action_name in {"fill", "click"}

    if requires_approval and not user_approved:
        raise ApprovalRequiredError(
            "Explicit user approval is required for this action"
        )

    return {
        "allowed": True,
        "action": action_name,
        "requires_approval": requires_approval,
    }