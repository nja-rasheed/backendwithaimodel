"""
Manages authenticated, temporary Browser Agent sessions.

Security:
- Each session belongs to one authenticated backend user.
- Portal domains are explicitly allowlisted.
- Citizen values remain in the local value provider.
- Gemini receives sanitized browser observations only.
- Browser sessions expire and can be closed.
"""

import secrets
import threading
import time

from urllib.parse import urlparse

from browser_agent.agent import BrowserAgent, BrowserAgentError
from browser_agent.integration.service_request import (
    ServiceRequestAdapter,
    ServiceRequestError,
)
from browser_agent.integration.mapping_adapter import (
    MappingAdapter,
    MappingAdapterError,
)

from app.config import settings


class BrowserSessionError(Exception):
    """Raised when a browser session cannot be managed safely."""


class BrowserSessionManager:

    SESSION_TTL_SECONDS = 30 * 60
    MAX_SESSIONS = 50

    def __init__(self):
        self._sessions = {}
        self._lock = threading.RLock()

    def _get_allowed_domain(self, portal_url):
        """Derive an exact hostname allowlist from the validated portal URL."""

        parsed = urlparse(portal_url)

        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
        ):
            raise BrowserSessionError("Invalid government portal URL")

        return parsed.hostname.lower().rstrip(".")

    def _get_session(self, session_id, user_id):
        """Retrieve a session while enforcing ownership and expiration."""

        session = self._sessions.get(session_id)

        if session is None:
            raise BrowserSessionError("Browser session not found")

        if session["user_id"] != user_id:
            raise BrowserSessionError("Browser session access denied")

        if time.monotonic() - session["last_access"] > self.SESSION_TTL_SECONDS:
            self._close_session_locked(session_id)
            raise BrowserSessionError("Browser session expired")

        session["last_access"] = time.monotonic()

        return session

    def _close_session_locked(self, session_id):
        session = self._sessions.pop(session_id, None)

        if session is None:
            return

        try:
            session["agent"].close()
        except Exception:
            pass

        # Drop references to citizen data.
        session["value_provider"] = None
        session["request_adapter"] = None
        session["mapping_adapter"] = None
        session["safe_request"] = None

    def create_session(self, user_id, manifest):
        """
        Create a browser session from a backend execution manifest.

        The manifest's private form values are retained locally.
        They are never included in the sanitized task sent to Gemini.
        """

        if not isinstance(manifest, dict):
            raise BrowserSessionError("Manifest must be an object")

        # Allow browser observation during pre-validation.
        # Actual application submission must still enforce readiness.

        portal_url = manifest.get("portal_url")

        allowed_domain = self._get_allowed_domain(portal_url)

        request_adapter = ServiceRequestAdapter(
            allowed_domains=[allowed_domain]
        )

        try:
            safe_request = request_adapter.load(manifest)

            mapping_adapter = MappingAdapter()

            provider_result = (
                mapping_adapter.create_value_provider_from_service_request(
                    service_request_adapter=request_adapter,
                    safe_request=safe_request,
                    approved_references=set(),
                )
            )

            value_provider = provider_result["provider"]

        except (ServiceRequestError, MappingAdapterError) as error:
            logger.exception(
                "Private application preparation failed. "
                "Exception type: %s",
                type(error).__name__,
            )
            raise BrowserSessionError(
                "Could not prepare the private application data"
            ) from error

        agent = None

        try:
            agent = BrowserAgent(
                allowed_domains=[allowed_domain],
                value_provider=value_provider,
                api_key=(
                    settings.GEMINI_API_KEYS.split(",")[0].strip()
                    if settings.GEMINI_API_KEYS
                    else settings.GEMINI_API_KEY or None
                ),
            )

            agent.start()
            agent.navigate(portal_url)

            observation = agent.observer.observe()

            if not isinstance(observation, dict):
                raise BrowserSessionError(
                    "Browser returned an invalid observation"
                )

            session_id = secrets.token_urlsafe(32)

            with self._lock:

                self.cleanup_expired_sessions()

                if len(self._sessions) >= self.MAX_SESSIONS:
                    raise BrowserSessionError(
                        "Maximum active browser sessions reached"
                    )

                self._sessions[session_id] = {
                    "user_id": user_id,
                    "agent": agent,
                    "request_adapter": request_adapter,
                    "mapping_adapter": mapping_adapter,
                    "value_provider": value_provider,
                    "safe_request": safe_request,
                    "created_at": time.monotonic(),
                    "last_access": time.monotonic(),
                    "status": "active",
                    "unsupported_fields": provider_result[
                        "unsupported_fields"
                    ],
                }

            return {
                "session_id": session_id,
                "status": "active",
                "service_name": safe_request["service_name"],
                "portal_url": safe_request["portal_url"],
                "observation": observation,
                "unsupported_fields": provider_result[
                    "unsupported_fields"
                ],
                "llm_task": request_adapter.build_llm_task(safe_request),
            }

        except Exception as error:

            if agent is not None:
                try:
                    agent.close()
                except Exception:
                    pass

            if isinstance(error, BrowserSessionError):
                raise

            raise BrowserSessionError(
                "Could not start the government portal browser session"
            ) from error

    def observe(self, session_id, user_id):

        with self._lock:
            session = self._get_session(session_id, user_id)

            try:
                observation = session["agent"].observer.observe()

                return {
                    "status": "success",
                    "observation": observation,
                }

            except Exception as error:
                raise BrowserSessionError(
                    "Could not observe the browser page"
                ) from error

    def get_session_task(self, session_id, user_id):

        with self._lock:
            session = self._get_session(session_id, user_id)

            return session["request_adapter"].build_llm_task(
                session["safe_request"]
            )

    def close_session(self, session_id, user_id):

        with self._lock:
            self._get_session(session_id, user_id)
            self._close_session_locked(session_id)

        return {
            "session_id": session_id,
            "status": "closed",
        }

    def cleanup_expired_sessions(self):

        now = time.monotonic()

        with self._lock:

            expired = [
                session_id
                for session_id, session in self._sessions.items()
                if now - session["last_access"] > self.SESSION_TTL_SECONDS
            ]

            for session_id in expired:
                self._close_session_locked(session_id)

        return len(expired)

    def analyze_session(self, session_id, user_id):
        with self._lock:
            session = self._get_session(session_id, user_id)

            agent = session["agent"]
            observation = agent.observer.observe()

            task = session["request_adapter"].build_llm_task(
                session["safe_request"]
            )

            proposal = agent.decision_engine.decide(
                task=task,
                observation=observation
            )

            return {
                "status": "success",
                "proposal": proposal,
                "execution_status": "not_executed",
                "requires_user_approval": True
            }

    def close_all(self):

        with self._lock:

            session_ids = list(self._sessions.keys())

            for session_id in session_ids:
                self._close_session_locked(session_id)


browser_session_manager = BrowserSessionManager()
