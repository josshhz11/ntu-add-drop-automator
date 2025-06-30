import pytest
from app import validate_login, login_to_portal
from unittest.mock import MagicMock

def test_validate_login():
    assert validate_login("user", "pass") == True
    assert validate_login("", "pass") == False
    assert validate_login("user", "") == False
    assert validate_login("", "") == False

@pytest.mark.asyncio
async def test_login_to_portal(mocker):
    mock_driver = MagicMock()
    mock_redis = MagicMock()

    # Mock Selenium interactions
    mock_driver.get.return_value = None
    mock_driver.find_element.return_value = MagicMock()

    result = login_to_portal(
        driver=mock_driver,
        username="test_user",
        password="test_pass",
        swap_id="test_swap",
        redis_db=mock_redis
    )

    # Verify login attempt was made
    mock_driver.get.assert_called_once()
    assert mock_driver.find_element.call_count > 0