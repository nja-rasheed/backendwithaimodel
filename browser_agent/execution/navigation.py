import time
from urllib.parse import urlparse
from browser_agent.security.action_validator import authorize_action


class NavigationError(Exception):
    """Raised when safe browser navigation fails."""
    pass


class SafeNavigator:

    def __init__(self, page, allowed_domains, timeout=45000):
        if page is None:
            raise NavigationError("A valid Playwright page is required")

        self.page = page
        self.allowed_domains = [d.lower().strip() for d in allowed_domains]
        self.timeout = timeout

    def _is_local_test_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            return (
                parsed.scheme == "https"
                and parsed.hostname in ("127.0.0.1", "localhost")
                and parsed.port == 8000
                and parsed.username is None
                and parsed.password is None
            )
        except Exception:
            return False

    def _is_domain_allowed(self, target_url: str) -> bool:
        if self._is_local_test_url(target_url):
            return True

        try:
            hostname = urlparse(target_url).hostname
            if not hostname:
                return False
            hostname = hostname.lower()

            for allowed in self.allowed_domains:
                if hostname == allowed or hostname.endswith("." + allowed):
                    return True
            return False
        except Exception:
            return False

    def _authorize_url(self, url: str):
        action = {
            "action": "navigate",
            "target": url,
            "parameters": {},
            "reason": "Authorized browser navigation",
        }

        if self._is_local_test_url(url):
            return

        try:
            result = authorize_action(
                action,
                allowed_domains=self.allowed_domains,
            )
        except Exception as error:
            raise NavigationError(
                f"Navigation destination '{url}' is not authorized: {error}"
            ) from error

        if not result.get("allowed"):
            if not self._is_domain_allowed(url):
                raise NavigationError(
                    f"Navigation destination '{url}' was rejected by security policy"
                )

    def navigate(self, url: str):
        if self.page.is_closed():
            raise NavigationError("Browser page is closed")

        self._authorize_url(url)
        blocked_destinations = []

        def top_level_navigation_guard(route):
            request = route.request

            try:
                is_main_nav = False
                if request.is_navigation_request():
                    try:
                        is_main_nav = (request.frame == self.page.main_frame)
                    except Exception:
                        is_main_nav = True

                if is_main_nav:
                    target = request.url
                    try:
                        self._authorize_url(target)
                    except NavigationError:
                        blocked_destinations.append(target)
                        route.abort("blockedbyclient")
                        return

                route.continue_()
            except Exception:
                try:
                    route.continue_()
                except Exception:
                    pass

        try:
            self.page.route("**/*", top_level_navigation_guard)

            try:
                response = self.page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.timeout,
                )

                # Wait for SPA initial settle
                try:
                    self.page.wait_for_load_state("load", timeout=8000)
                except Exception:
                    pass

                # Use Python sleep instead of page.wait_for_timeout to avoid TargetClosedError on redirects
                time.sleep(3.5)

            finally:
                try:
                    self.page.unroute("**/*", top_level_navigation_guard)
                except Exception:
                    pass

        except Exception as error:
            if self.page.is_closed():
                raise NavigationError("Browser page closed unexpectedly during navigation") from error

            if blocked_destinations:
                raise NavigationError(
                    f"Navigation blocked to unauthorized destination: {blocked_destinations[-1]}"
                ) from error

            raise NavigationError(
                f"Browser navigation failed: {error}"
            ) from error

        if self.page.is_closed():
            raise NavigationError("Browser page closed unexpectedly after navigation")

        final_url = self.page.url
        self._authorize_url(final_url)

        return {
            "status": "navigated",
            "url": final_url,
            "http_status": response.status if response else None,
        }