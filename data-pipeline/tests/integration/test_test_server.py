"""
Simple test to see if I can get 
A server set ip
"""

import requests


def test_fastapi_server_responds(fastapi_server):
    """
    Test that the FastAPI server responds correctly with the expected HTML.
    """
    response = requests.get(fastapi_server, timeout=10)

    assert response.status_code == 200

    expected_content = "<h1>Hello Minnesota!</h1>"
    assert expected_content in response.text
