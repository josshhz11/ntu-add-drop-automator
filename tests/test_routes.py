import pytest
from fastapi.testclient import TestClient
import json

def test_index_route(test_client, override_redis):
    response = test_client.get("/")
    assert response.status_code == 200
    assert "NTU Add-Drop Automator" in response.text

"""def test_input_index_route(test_client):
    data = {
        "username": "test_user",
        "password": "test_pass",
        "num_modules": 2
    }
    response = test_client.post("/input_index", data=data)
    assert response.status_code == 200
    assert "Input Indexes" in response.text"""

def test_swap_status_unauthorized(test_client, override_redis):
    response = test_client.get("/swap_status/test_swap_id")
    assert response.status_code == 200
    assert "You are not logged in" in response.text

def test_privacy_policy_route(test_client):
    response = test_client.get("/privacy_policy")
    assert response.status_code == 200
    assert "Privacy Policy" in response.text