import os
import platform
import sys
from dataclasses import dataclass, field
from typing import Any, Dict


def is_display_available() -> bool:
    """Checks whether a graphical display server exists to render a window."""
    if sys.platform.startswith("win"):
        return True
    if sys.platform == "darwin":
        return True
    return bool(os.getenv("DISPLAY"))


def get_default_user_agent() -> str:
    system = platform.system().lower()
    if "linux" in system:
        return (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )


@dataclass
class BrowserConfig:
    headless: bool = True
    user_agent: str = field(default_factory=get_default_user_agent)
    extra_headers: Dict[str, str] = field(
        default_factory=lambda: {
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    def get_launch_options(self) -> Dict[str, Any]:
        """Provides Chromium launch kwargs for Playwright."""
        return {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        }

    def get_context_options(self) -> Dict[str, Any]:
        """Provides browser context initialization options."""
        return {
            "user_agent": self.user_agent,
            "viewport": {"width": 1920, "height": 1080},
            "extra_http_headers": self.extra_headers,
            "locale": "en-US",
            "timezone_id": "Asia/Kolkata",
            "ignore_https_errors": True,
        }


def get_browser_config() -> BrowserConfig:
    """Factory function returning the configured BrowserConfig instance."""
    if not is_display_available():
        headless = True
    else:
        headless = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"

    return BrowserConfig(headless=headless)