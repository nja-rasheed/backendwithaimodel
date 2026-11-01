"""Validate service requests and keep citizen data outside LLM prompts."""

from copy import deepcopy
from urllib.parse import urlparse
import re


class ServiceRequestError(ValueError):
    """Raised when a service request is invalid."""


class ServiceRequestAdapter:
    REQUIRED_TOP_LEVEL = {
        "service_id",
        "service_name",
        "service_code",
        "portal_url",
        "form_payload",
        "file_attachments",
    }

    FORBIDDEN_TASK_VALUE = re.compile(
        r"(password|passwd|otp|one.time.password|secret|token|"
        r"api.key|cvv|card.number)",
        re.IGNORECASE,
    )

    def __init__(self, allowed_domains):
        if not isinstance(allowed_domains, (list, tuple, set)):
            raise ServiceRequestError("An explicit domain allowlist is required")
        if not allowed_domains:
            raise ServiceRequestError("The domain allowlist cannot be empty")

        self.allowed_domains = {
            domain.lower().strip().rstrip(".")
            for domain in allowed_domains
            if isinstance(domain, str) and domain.strip()
        }
        if not self.allowed_domains:
            raise ServiceRequestError("No valid allowlisted domains supplied")

        self._private_form_payload = {}
        self._private_attachments = []

    def _validate_portal_url(self, url):
        if not isinstance(url, str):
            raise ServiceRequestError("portal_url must be a string")

        try:
            parsed = urlparse(url)
            port = parsed.port
        except ValueError as error:
            raise ServiceRequestError("Invalid portal URL") from error

        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
        ):
            raise ServiceRequestError("Portal URL must be a standard HTTPS URL")

        hostname = parsed.hostname.lower().rstrip(".")
        if not any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in self.allowed_domains
        ):
            raise ServiceRequestError("Portal domain is not allowlisted")

        return url

    def load(self, request):
        """Validate request and retain sensitive values locally."""
        if not isinstance(request, dict):
            raise ServiceRequestError("Service request must be a JSON object")

        missing = self.REQUIRED_TOP_LEVEL - request.keys()
        if missing:
            raise ServiceRequestError(
                "Missing required request keys: " + ", ".join(sorted(missing))
            )

        if not isinstance(request["service_id"], (str, int)):
            raise ServiceRequestError("service_id must be a string or integer")

        for key in ("service_name", "service_code"):
            if not isinstance(request[key], str) or not request[key].strip():
                raise ServiceRequestError(f"{key} must be a non-empty string")

        portal_url = self._validate_portal_url(request["portal_url"])

        form_payload = request["form_payload"]
        attachments = request["file_attachments"]

        if not isinstance(form_payload, dict):
            raise ServiceRequestError("form_payload must be an object")
        if not isinstance(attachments, list):
            raise ServiceRequestError("file_attachments must be a list")

        for name, value in form_payload.items():
            if not isinstance(name, str) or not name.strip():
                raise ServiceRequestError("Form field names must be non-empty strings")
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise ServiceRequestError(f"Invalid value type for field {name}")

        safe_attachments = []
        for item in attachments:
            if not isinstance(item, dict):
                raise ServiceRequestError("Each attachment must be an object")
            if not isinstance(item.get("requirement"), str):
                raise ServiceRequestError("Attachment requirement is missing")
            if not isinstance(item.get("filename"), str):
                raise ServiceRequestError("Attachment filename is missing")

            # Keep signed URLs/local paths in private state only.
            source = item.get("download_url") or item.get("local_path")
            if source is not None and not isinstance(source, str):
                raise ServiceRequestError("Attachment source must be a string")

            safe_attachments.append({
                "requirement": item["requirement"],
                "filename": item["filename"],
                "source_available": bool(source),
            })

        self._private_form_payload = deepcopy(form_payload)
        self._private_attachments = deepcopy(attachments)

        return {
            "service_id": request["service_id"],
            "service_name": request["service_name"],
            "service_code": request["service_code"],
            "portal_url": portal_url,
            "governance_tier": request.get("governance_tier"),
            "ready_for_dispatch": request.get("ready_for_dispatch") is True,
            "missing_form_fields": list(request.get("missing_form_fields", [])),
            "missing_documents": list(request.get("missing_documents", [])),
            "form_field_names": list(form_payload.keys()),
            "attachments": safe_attachments,
            "form_payload": {},
            "application_submitted": False,
        }

    def get_local_value(self, value_ref):
        """Retrieve a value locally; never include it in an LLM prompt."""
        if not isinstance(value_ref, str):
            raise ServiceRequestError("value_ref must be a string")
        if value_ref not in self._private_form_payload:
            raise ServiceRequestError("Unknown local value reference")
        return self._private_form_payload[value_ref]

    def get_local_attachments(self):
        """Return attachment metadata and sources for local processing only."""
        return deepcopy(self._private_attachments)

    def build_llm_task(self, safe_request):
        """Build a task containing service metadata, never applicant values."""
        if not isinstance(safe_request, dict):
            raise ServiceRequestError("Load a request before building an LLM task")

        fields = safe_request.get("form_field_names", [])
        documents = [
            item["requirement"] for item in safe_request.get("attachments", [])
        ]

        return (
            f"Inspect the service portal for: {safe_request['service_name']}. "
            f"Identify the relevant application form and map its visible fields "
            f"to these field names: {', '.join(fields)}. "
            f"Required document categories: {', '.join(documents)}. "
            "Do not enter values, upload documents, submit forms, or make payments. "
            "Return a structured mapping proposal only."
        )