"""
Factory for creating the pipeline and related tools
"""

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import requests
from data_pipeline.aisr.actions import SchoolQueryInformation, bulk_query_aisr
from data_pipeline.aisr.authenticate import AISRAuthResponse
from data_pipeline.etl_workflow import run_aisr_workflow, run_etl


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


def create_aisr_actions_for_school_bulk_queries(
    school_query_information_list: list[SchoolQueryInformation],
) -> list[Callable[[requests.Session, AISRAuthResponse, str], None]]:
    """
    Creates a list of bulk query functions for each school in the
    school_query_information_list. The returned functions can be run with
    a requests session and base url.
    """
    function_list = []
    for school_query_information in school_query_information_list:
        function_list.append(
            # pylint: disable-next=line-too-long
            lambda session, auth_response, base_url, query_information=school_query_information, func=bulk_query_aisr: func(
                session,
                auth_response,
                base_url,
                query_information,
            )
        )
    return function_list


def create_aisr_workflow(
    login: Callable[[requests.Session, str, str, str], AISRAuthResponse],
    aisr_function_list: list[Callable[[requests.Session, AISRAuthResponse, str], None]],
    logout: Callable[[requests.Session, str], AISRAuthResponse],
) -> Callable[[str, str, str, str], str]:
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
            lambda session, aisr_login_response, func=bulk_query_function: func(
                session, aisr_login_response, aisr_base_url
            )
            for bulk_query_function in aisr_function_list
        ]
        return run_aisr_workflow(
            login=lambda session: login(session, auth_base_url, username, password),
            aisr_actions=action_list,
            logout=lambda session: logout(session, auth_base_url),
        )

    return aisr_fn
