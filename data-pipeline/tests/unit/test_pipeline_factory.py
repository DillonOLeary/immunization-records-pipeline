"""
Tests for the construction of the pipeline and tools
"""

# pylint: disable=missing-function-docstring

from unittest.mock import MagicMock, patch

from data_pipeline.pipeline_factory import use_web_driver


def test_web_driver_closes_out_of_context():
    """
    Test that the WebDriver's quit method is called when exiting the context.
    """
    target_url = "https://example.com"

    with patch("selenium.webdriver.Chrome") as mock_web_driver:
        mock_driver = MagicMock()
        mock_web_driver.return_value = mock_driver

        with use_web_driver(target_url):
            mock_web_driver.assert_called_once()
            mock_driver.get.assert_called_once_with(target_url)

        mock_driver.quit.assert_called_once()
