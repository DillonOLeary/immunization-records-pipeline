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

    # username_input = web_driver.find_element(By.ID, "username")
    # username_input.clear()
    # username_input.send_keys(username)

    # password_input = web_driver.find_element(By.ID, "password")
    # password_input.clear()
    # password_input.send_keys(password)

    # login_button = web_driver.find_element(By.ID, "kc-login")
    # login_button.click()

    return AISRResponse(is_successful=False, message="Failed")
