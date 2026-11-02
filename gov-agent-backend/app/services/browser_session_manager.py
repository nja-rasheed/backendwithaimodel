"""
Manages authenticated, temporary Browser Agent sessions.

Security:
- Each session belongs to one authenticated backend user.
- Portal domains are explicitly allowlisted.
- Citizen values remain in the local value provider.
- Gemini receives sanitized browser observations only.
- Browser sessions expire and can be closed.
"""

import sys
from pathlib import Path

# Ensure root folder (backendwithaimodel) is in sys.path
_CURRENT_DIR = Path(__file__).resolve()
_REPO_ROOT = _CURRENT_DIR.parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import logging
import queue
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

logger = logging.getLogger(__name__)


class BrowserSessionError(Exception):
    """Raised when a browser session cannot be managed safely."""


import asyncio
import logging
import queue
import secrets
import threading
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor

class _PlaywrightEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    """Event loop policy that guarantees worker threads report no running loop."""
    def get_event_loop(self):
        raise RuntimeError("No running event loop on Playwright worker thread")


def _init_playwright_thread():
    """Executed once when the background worker thread is spawned."""
    # Reset thread-local loop and override policy for this thread
    try:
        asyncio.set_event_loop(None)
    except Exception:
        pass


class PlaywrightWorkerThread:
    """Dedicated background OS thread running Playwright operations."""

    def __init__(self):
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="PlaywrightWorker",
            initializer=_init_playwright_thread,
        )

    def execute(self, func, *args, **kwargs):
        def _wrapper():
            # Guarantee no event loop is registered on this thread during the call
            try:
                asyncio.set_event_loop(None)
            except Exception:
                pass
            return func(*args, **kwargs)

        future = self._executor.submit(_wrapper)
        return future.result()


_playwright_worker = PlaywrightWorkerThread()


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

        agent = session.get("agent")
        if agent is not None:
            try:
                _playwright_worker.execute(agent.close)
            except Exception:
                pass

        # Drop references to citizen data
        session["value_provider"] = None
        session["request_adapter"] = None
        session["mapping_adapter"] = None
        session["safe_request"] = None

    def _start_and_observe_portal(self, agent, portal_url):
        """Initializes, navigates, and waits for SPA dynamic elements before extraction."""
        agent.start()
        agent.navigate(portal_url)

        page = agent.observer.page
        if page and not page.is_closed():
            # Wait for either form cards or general text content to mount in the DOM
            try:
                page.wait_for_selector(
                    "div.card, div.form-card, .dashboard-container, a, button, h1, h2, h3, h4, h5",
                    state="visible",
                    timeout=12000
                )
            except Exception:
                pass

            # Safe diagnostics
            try:
                print("DEBUG: Active URL:", page.url)
                print("DEBUG: Active Title:", page.title())
                # Log actual rendered text snippet to verify content exists
                body_text = page.locator("body").inner_text()
                print("DEBUG: Body snippet:", repr(body_text[:200]))
            except Exception as e:
                print("DEBUG: Diagnostic read failed:", e)

        return agent.observer.observe()
    def create_session(self, user_id, manifest):
        """
        Create a browser session from a backend execution manifest.
        The manifest's private form values are retained locally.
        """
        if not isinstance(manifest, dict):
            raise BrowserSessionError("Manifest must be an object")

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
                "Private application preparation failed: %s",
                type(error).__name__,
            )
            raise BrowserSessionError(
                "Could not prepare the private application data"
            ) from error

        agent = None

        try:
            gemini_key = (
                settings.GEMINI_API_KEYS.split(",")[0].strip()
                if getattr(settings, "GEMINI_API_KEYS", None)
                else getattr(settings, "GEMINI_API_KEY", None) or None
            )

            agent = BrowserAgent(
                allowed_domains=[allowed_domain],
                value_provider=value_provider,
                api_key=gemini_key,
            )

            # Start and navigate entirely on the dedicated Playwright worker thread
            observation = _playwright_worker.execute(
                self._start_and_observe_portal,
                agent,
                portal_url
            )

            if not isinstance(observation, dict):
                raise BrowserSessionError("Browser returned an invalid observation")

            session_id = secrets.token_urlsafe(32)

            with self._lock:
                self.cleanup_expired_sessions()

                if len(self._sessions) >= self.MAX_SESSIONS:
                    raise BrowserSessionError("Maximum active browser sessions reached")

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
                    "unsupported_fields": provider_result["unsupported_fields"],
                }

            return {
                "session_id": session_id,
                "status": "active",
                "service_name": safe_request["service_name"],
                "portal_url": safe_request["portal_url"],
                "observation": observation,
                "unsupported_fields": provider_result["unsupported_fields"],
                "llm_task": request_adapter.build_llm_task(safe_request),
            }

        except Exception as error:
            import traceback
            traceback.print_exc()

            if agent is not None:
                try:
                    _playwright_worker.execute(agent.close)
                except Exception:
                    pass

            if isinstance(error, BrowserSessionError):
                raise

            raise BrowserSessionError(
                f"Could not start browser session: {type(error).__name__}: {error}"
            ) from error

    def observe(self, session_id, user_id):
        with self._lock:
            session = self._get_session(session_id, user_id)

            try:
                agent = session["agent"]
                observation = _playwright_worker.execute(agent.observer.observe)

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

    def _execute_analysis(self, agent, task):
        observation = agent.observer.observe()
        proposal = agent.decision_engine.decide(
            task=task,
            observation=observation
        )
        return proposal

    def analyze_session(self, session_id, user_id):
        with self._lock:
            session = self._get_session(session_id, user_id)

            agent = session["agent"]
            task = session["request_adapter"].build_llm_task(
                session["safe_request"]
            )

            proposal = _playwright_worker.execute(
                self._execute_analysis,
                agent,
                task
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
    def _execute_agent_action(self, agent, action=None):
        """Executes an action directly via the BrowserAgent on the worker thread."""
        # 1. If an explicit action is provided from the request
        if action:
            normalized_action = {
                "action": str(action.get("action", "")).strip().lower(),
                "target": str(action.get("target", "")).strip(),
                "parameters": action.get("parameters") if isinstance(action.get("parameters"), dict) else {},
                "reason": str(action.get("reason") or "Approved execution by user").strip()
            }

            if agent.executor:
                agent.executor.register_observation(agent.observer.observe())
                result = agent.executor.execute(normalized_action, user_approved=True)
                return {
                    "status": "executed",
                    "action": normalized_action["action"],
                    "result": result,
                }

        # 2. If the agent already has a staged pending action, approve it
        if agent.pending_action is not None:
            return agent.approve_pending_action()

        raise BrowserSessionError("No pending or specified action to execute")

    def execute_session_action(self, session_id, user_id, action=None):
        with self._lock:
            session = self._get_session(session_id, user_id)
            agent = session["agent"]

            try:
                result = _playwright_worker.execute(
                    self._execute_agent_action,
                    agent,
                    action,
                )
            except Exception as error:
                logger.exception("Failed to execute browser action: %s", error)
                raise BrowserSessionError(f"Action execution failed: {error}") from error

            try:
                session["observation"] = _playwright_worker.execute(agent.observer.observe)
            except Exception:
                pass

            return {
                "status": "success",
                "execution": result,
                "observation": session.get("observation"),
            }


browser_session_manager = BrowserSessionManager()