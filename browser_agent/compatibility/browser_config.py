import os
from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class BrowserConfig:

    browser_name: str = "chromium"
    headless: bool = True
    timeout: int = 45000

    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def get_launch_options(self) -> Dict[str, Any]:
        return {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--window-size=1920,1080",
                "--start-maximized",
            ],
        }

    def get_context_options(self) -> Dict[str, Any]:
        return {
            "user_agent": self.user_agent,
            "viewport": {"width": 1920, "height": 1080},
            "locale": "en-US",
            "timezone_id": "Asia/Kolkata",
            "has_touch": False,
            "is_mobile": False,
            "java_script_enabled": True,
            "ignore_https_errors": True,
            # Leave extra_http_headers empty or omit completely so Chromium generates valid subresource headers
        }


def get_browser_config() -> BrowserConfig:
    headless_value = os.getenv("BROWSER_HEADLESS", "true").lower()
    return BrowserConfig(
        headless=headless_value == "true"
    )