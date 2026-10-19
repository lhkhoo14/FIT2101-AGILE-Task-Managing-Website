import pytest
from datetime import date, timedelta
from server.logic.sprint_logic import validate_sprint_dates, is_sprint_active

@pytest.mark.unit
def test_sprint_logic_valid_dates():
    """Test valid sprint date range validation."""
    start = date(2026, 1, 1)
    end = date(2026, 1, 14)
    assert validate_sprint_dates(start, end) is True

@pytest.mark.unit
def test_sprint_logic_invalid_dates():
    """Test sprint date validation failure when end is before start."""
    start = date(2026, 1, 14)
    end = date(2026, 1, 1)
    assert validate_sprint_dates(start, end) is False