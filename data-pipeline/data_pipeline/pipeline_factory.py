"""
Factory for creating the pipeline and related tools
"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
from data_pipeline.etl_workflow import run_etl
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.webdriver import WebDriver


def create_file_to_file_etl_pipeline(
    extract: Callable[[Path], pd.DataFrame],
    transform: Callable[[pd.DataFrame], pd.DataFrame],
    load: Callable[[pd.DataFrame, Path, str], None],
) -> Callable[[Path, Path], str]:
    """
    Creates an file to file etl pipeline function by injecting
    the extract, transform, and load functions. The returned
    function can be run with an input file and output folder paths.

    Returns:
        Callable[[Path, Path], str]: A function that runs the full ETL pipeline on a file.
    """

    def etl_fn(input_file: Path, output_folder: Path) -> str:
        """
        Creates etl function for an input file and output folder.
        """
        return run_etl(
            extract=lambda: extract(input_file),
            transform=transform,
            load=lambda df: load(df, output_folder, input_file.name),
        )

    return etl_fn


@contextmanager
def use_web_driver(target_url) -> Generator[WebDriver, None, None]:
    """
    Context manager for a Chrome WebDriver with options set for headless operation.

    Automatically closes the WebDriver when exiting the context.
    """
    options = Options()
    options.headless = True

    driver = webdriver.Chrome(options=options)
    try:
        driver.get(target_url)
        yield driver
    finally:
        driver.quit()
