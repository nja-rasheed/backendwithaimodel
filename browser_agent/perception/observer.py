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
        Enforce the domain policy for navigation requests
        across the entire browser context.
        """

        request = route.request

        if request.is_navigation_request():

            action = {
                "action": "navigate",
                "target": request.url,
                "parameters": {},
                "reason": "Browser context navigation policy",
            }

            try:
                authorize_action(
                    action,
                    allowed_domains=self.allowed_domains
                )

            except Exception:
                self.blocked_navigation_attempts.append({
                    "reason": "unauthorized_navigation"
                })
                route.abort()
                return

        route.continue_()

    def start(self):

        self.playwright = sync_playwright().start()

        try:
            config = get_browser_config()

            self.browser = self.playwright.chromium.launch(
                **config.get_launch_options()
            )

            # Retain an explicit browser context.
            # Blocking service workers improves route interception
            # consistency for this security-sensitive workflow.
            self.context = self.browser.new_context(
                viewport={
                    "width": 1440,
                    "height": 1000
                },
                screen={
                    "width": 1440,
                    "height": 1000
                },
                service_workers="block",
                ignore_https_errors=getattr(
                    self,
                    "ignore_https_errors",
                    False
                )
            )
            # Install the policy once for this entire context.
            self.context.route(
                "**/*",
                self._navigation_guard
            )

            self.page = self.context.new_page()

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

        return extract_dom(self.page)

    def close(self):

        if self.context:
            self.context.close()
            self.context = None

        if self.browser:
            self.browser.close()
            self.browser = None

        if self.playwright:
            self.playwright.stop()
            self.playwright = None

        self.page = None
        self.navigator = None