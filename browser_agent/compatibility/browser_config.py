import os
from dataclasses import dataclass, field
from typing import Dict, Any, List


@dataclass
class BrowserConfig:
    headless: bool = False
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
                "--start-maximized",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        }

    def get_context_options(self) -> Dict[str, Any]:
        return {
            "user_agent": self.user_agent,
            "viewport": None,
            "extra_http_headers": self.extra_headers,
            "locale": "en-US",
            "timezone_id": "Asia/Kolkata",
            "ignore_https_errors": True,
        }


def get_browser_config() -> BrowserConfig:
    """Factory function to provide the browser configuration instance."""
    is_headless = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
    return BrowserConfig(headless=is_headless)