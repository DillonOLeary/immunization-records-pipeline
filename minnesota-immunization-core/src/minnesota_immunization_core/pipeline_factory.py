"""
Factory for creating the pipeline and related tools
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from minnesota_immunization_core.aisr.actions import (
    SchoolQueryInformation,
    bulk_query_aisr,
    get_and_download_vaccination_records,
)
from minnesota_immunization_core.aisr.authenticate import AISRAuthResponse
from minnesota_immunization_core.etl_workflow import run_aisr_workflow, run_etl


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
        Callable[[Path, Path], str]: A function
        that runs the full ETL pipeline on a file.
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


def create_aisr_actions_for_school_bulk_queries(
    school_query_information_list: list[SchoolQueryInformation],
) -> list[Callable[..., None]]:  # Using ... to accept any callable
    """
    Creates a list of bulk query functions for each school in the
    school_query_information_list. The returned functions can be run with
    a requests session and base url.
    """
    function_list = []
    for school_query_information in school_query_information_list:
        function_list.append(
            # pylint: disable-next=line-too-long
            lambda session,
            access_token,
            base_url,
            query_information=school_query_information,
            func=bulk_query_aisr: func(
                session,
                access_token,
                base_url,
                query_information,
            )
        )
    return function_list


def create_aisr_workflow(
    login: Callable[[requests.Session, str, str, str], AISRAuthResponse],
    aisr_function_list: list[Callable[..., None]],
    logout: Callable[[requests.Session, str], None],
) -> Callable[[str, str, str, str], None]:
    """
    Create a query function that can be run with a base url, username, and password
    """

    def aisr_fn(
        auth_base_url: str,
        aisr_base_url: str,
        username: str,
        password: str,
    ):
        action_list = [
            lambda session, access_token, func=bulk_query_function: func(
                session, access_token, aisr_base_url
            )
            for bulk_query_function in aisr_function_list
        ]
        return run_aisr_workflow(
            login=lambda session: login(session, auth_base_url, username, password),
            aisr_actions=action_list,
            logout=lambda session: logout(session, auth_base_url),
        )

    return aisr_fn


def generate_vaccination_record_filename(school_name: str) -> str:
    """
    Generate a filename for downloaded vaccination records.

    Args:
        school_name: Name of the school

    Returns:
        A filename string with the format
        'vaccinations_SchoolName_YYYYMMDD_HHMMSS_uniqueID.csv'
    """
    # Clean up school name for filename (replace spaces with underscores)
    clean_school_name = school_name.replace(" ", "_")

    # Add timestamp and unique ID
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]  # Shortened UUID for brevity

    return f"vaccinations_{clean_school_name}_{timestamp}_{unique_id}.csv"


def create_aisr_download_actions(
    school_info_list: list[SchoolQueryInformation],
    output_folder: Path,
) -> list[Callable[..., None]]:
    """
    Creates a list of download functions for each school in the provided list.
    Each function will download vaccination records for a
    school to a file in the output folder.

    Args:
        school_info_list: List of SchoolQueryInformation objects
        output_folder: Folder where downloaded files will be saved

    Returns:
        List of functions that can be used to download vaccination records
    """
    import logging
    logger = logging.getLogger(__name__)

    function_list = []
    for school_info in school_info_list:
        # Create a specific output file for this school with a unique filename
        output_filename = generate_vaccination_record_filename(school_info.school_name)
        output_file = output_folder / output_filename

        # Create a download function for this school -
        # binding both the function and parameters
        def create_download_func(school_name, school_id, output_path):
            def download_func(session, access_token, base_url):
                logger.info(
                    f"Downloading vaccination records for {school_name} "
                    f"(ID: {school_id})"
                )
                try:
                    result = get_and_download_vaccination_records(
                        session=session,
                        access_token=access_token,
                        base_url=base_url,
                        school_id=school_id,
                        output_path=output_path,
                    )
                    logger.info(
                        f"Successfully downloaded vaccination records for "
                        f"{school_name}"
                    )
                    return result
                except Exception as e:
                    logger.error(
                        f"Failed to download vaccination records for "
                        f"{school_name}: {e}"
                    )
                    raise
            return download_func

        function_list.append(
            create_download_func(
                school_info.school_name,
                school_info.school_id,
                output_file
            )
        )

    return function_list
