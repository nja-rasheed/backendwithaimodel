import os
import sys
from dataclasses import dataclass, field
from typing import Dict, Any


def is_display_available() -> bool:
    """Checks whether a graphical display server exists to render a window."""
    if sys.platform.startswith("win"):
        return True
    if sys.platform == "darwin":
        return True
    # Linux / Docker containers
    return bool(os.getenv("DISPLAY"))


@dataclass
class BrowserConfig:
    headless: bool = True
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    extra_headers: Dict[str, str] = field(default_factory=lambda: {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })

    def get_launch_options(self) -> Dict[str, Any]:
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
        return {
            "user_agent": self.user_agent,
            "viewport": {"width": 1920, "height": 1080},
            "extra_http_headers": self.extra_headers,
            "locale": "en-US",
            "timezone_id": "Asia/Kolkata",
            "ignore_https_errors": True,
        }


def get_browser_config() -> BrowserConfig:
    """Factory function providing the appropriate browser configuration."""
    # Force headless if no display exists, otherwise respect BROWSER_HEADLESS env var
    if not is_display_available():
        headless = True
    else:
        headless = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"

    return BrowserConfig(headless=headless)