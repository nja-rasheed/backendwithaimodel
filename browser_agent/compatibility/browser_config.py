import os
from dataclasses import dataclass


@dataclass
class BrowserConfig:

    browser_name: str = "chromium"

    headless: bool = True

    timeout: int = 30000

    def get_launch_options(self):

        return {
            "headless": self.headless
        }


def get_browser_config():

    headless_value = os.getenv(
        "BROWSER_HEADLESS", "true"
    ).lower()

    config = BrowserConfig(
        headless=headless_value == "true"
    )

    return config