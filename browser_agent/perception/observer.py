from playwright.sync_api import sync_playwright

from browser_agent.compatibility.browser_config import (
    get_browser_config
)

from browser_agent.execution.navigation import (
    SafeNavigator
)

from browser_agent.security.action_validator import (
    authorize_action
)

from browser_agent.perception.dom_extractor import (
    extract_dom
)


class BrowserObserver:

    def __init__(self, allowed_domains):
        if not isinstance(allowed_domains, (list, tuple, set)):
            raise ValueError("An explicit domain allowlist is required")

        if not allowed_domains:
            raise ValueError("The domain allowlist cannot be empty")

        self.allowed_domains = allowed_domains

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.navigator = None
        self.blocked_navigation_attempts = []

    def _navigation_guard(self, route):
        """
        Enforce the domain policy strictly for top-level frame navigation
        requests across the browser context without blocking essential subresources.
        """
        request = route.request

        # Only restrict top-level document navigation, allow subresources (fonts, scripts, css)
        if request.is_navigation_request() and request.frame == self.page.main_frame:
            action = {
                "action": "navigate",
                "target": request.url,
                "parameters": {},
                "reason": "Browser context navigation policy",
            }

            try:
                result = authorize_action(
                    action,
                    allowed_domains=self.allowed_domains
                )
                if not result.get("allowed"):
                    raise ValueError("Domain not allowed")
            except Exception:
                self.blocked_navigation_attempts.append({
                    "url": request.url,
                    "reason": "unauthorized_navigation"
                })
                route.abort()
                return

        route.continue_()

    def start(self):
        from playwright.sync_api import sync_playwright

        self.playwright = sync_playwright().start()

        try:
            config = get_browser_config()

            self.browser = self.playwright.chromium.launch(
                **config.get_launch_options()
            )

            context_opts = config.get_context_options()
            self.context = self.browser.new_context(**context_opts)

            self.page = self.context.new_page()

            self.page.on("console", lambda msg: print(f"BROWSER CONSOLE [{msg.type}]: {msg.text}"))
            self.page.on("requestfailed", lambda req: print(f"REQUEST FAILED: {req.url} - {req.failure}"))

            self.navigator = SafeNavigator(
                page=self.page,
                allowed_domains=self.allowed_domains
            )

            return self.page

        except Exception:
            self.close()
            raise

    def navigate(self, url):
        if self.navigator is None:
            raise RuntimeError("Browser has not been started")

        return self.navigator.navigate(url)

    def observe(self):
        if self.page is None or self.page.is_closed():
            raise RuntimeError("Browser page is unavailable")

        # Give Angular/React SPA 500ms to settle rendering if DOM is completely blank
        return extract_dom(self.page)

    def close(self):
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
            self.context = None

        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
            self.browser = None

        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
            self.playwright = None

        self.page = None
        self.navigator = None