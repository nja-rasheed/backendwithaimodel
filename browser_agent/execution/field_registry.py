import hashlib
import json
import re


class FieldRegistryError(Exception):
    """Raised when a field reference cannot be safely resolved."""
    pass


class FieldRegistry:

    def __init__(self, page):
        if page is None:
            raise FieldRegistryError("A valid Playwright page is required")

        self.page = page
        self._fields = {}
        self._observation_id = None

    @staticmethod
    def _metadata_signature(field):
        metadata = {
            "tag": field.get("tag"),
            "type": field.get("type"),
            "name": field.get("name"),
            "id": field.get("id"),
            "label": field.get("label"),
            "autocomplete": field.get("autocomplete"),
        }

        serialized = json.dumps(
            metadata,
            sort_keys=True,
            ensure_ascii=True
        )

        return hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest()

    def register(self, observation):

        if not isinstance(observation, dict):
            raise FieldRegistryError("Invalid observation")

        fields = observation.get("input_fields")

        if not isinstance(fields, list):
            raise FieldRegistryError("Invalid input field collection")

        registry = {}

        for index, field in enumerate(fields):

            if not isinstance(field, dict):
                raise FieldRegistryError("Invalid field metadata")

            reference = field.get("field_ref")

            if not isinstance(reference, str):
                raise FieldRegistryError("Invalid field reference")

            if not re.fullmatch(r"field_\d{4}", reference):
                raise FieldRegistryError("Malformed field reference")

            if reference in registry:
                raise FieldRegistryError("Duplicate field reference")

            if not isinstance(field.get("tag"), str):
                raise FieldRegistryError("Missing field tag")

            if not isinstance(field.get("type"), str):
                raise FieldRegistryError("Missing field type")

            registry[reference] = {
                "index": index,
                "signature": self._metadata_signature(field),
                "metadata": field.copy(),
            }

        self._fields = registry
        self._observation_id = id(registry)

    def resolve(self, reference):

        if not isinstance(reference, str):
            raise FieldRegistryError("Reference must be a string")

        entry = self._fields.get(reference)

        if entry is None:
            raise FieldRegistryError("Unknown or stale field reference")

        elements = self.page.locator("input, textarea, select")

        index = entry["index"]

        if index >= elements.count():
            raise FieldRegistryError("Field no longer exists")

        element = elements.nth(index)

        try:
            if not element.is_visible():
                raise FieldRegistryError("Field is not visible")

            if not element.is_enabled():
                raise FieldRegistryError("Field is disabled")

            actual_metadata = element.evaluate("""
                element => ({
                    tag: element.tagName.toLowerCase(),
                    type: element.getAttribute("type") || "text",
                    name: element.getAttribute("name"),
                    id: element.id,
                    label: (
                        Array.from(element.labels || [])
                            .map(label => label.innerText.trim())
                            .filter(Boolean)
                            .join(" ")
                        || element.getAttribute("aria-label")
                        || ""
                    ),
                    autocomplete: element.getAttribute("autocomplete")
                })
            """)

        except FieldRegistryError:
            raise

        except Exception as error:
            raise FieldRegistryError(
                "Field is no longer available"
            ) from error

        actual_signature = self._metadata_signature(actual_metadata)

        if actual_signature != entry["signature"]:
            raise FieldRegistryError(
                "Field identity changed since observation"
            )

        return element