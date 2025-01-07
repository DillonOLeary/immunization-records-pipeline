"""
Query MIIC for school immunization data
"""

import logging
from dataclasses import dataclass

from selenium.webdriver.chrome.webdriver import WebDriver

logger = logging.getLogger(__name__)


@dataclass
class AISRResponse:
    """
    Dataclass to hold the response from interactions with AISR.
    """

    is_successful: bool
    message: str


def login(web_driver: WebDriver, username: str, password: str) -> AISRResponse:
    """
    Use Selenium to log into MIIC.
    """
    logger.info("Logging into MIIC")

    return AISRResponse(is_successful=False, message="Failed")
