import pytest
from datetime import date, timedelta
from server.logic.sprint_logic import validate_sprint_dates

@pytest.mark.unit
def test_sprint_logic_valid_dates():
    """Test valid sprint date range validation against today's date."""
    today = date.today()
    start_str = (today + timedelta(days=1)).isoformat()
    end_str = (today + timedelta(days=14)).isoformat()
    
    start, end = validate_sprint_dates(start_str, end_str, today_date=today)
    assert start <= end

@pytest.mark.unit
def test_sprint_logic_invalid_dates():
    """Test sprint date validation failure when end is before start."""
    today = date.today()
    start_str = (today + timedelta(days=14)).isoformat()
    end_str = (today + timedelta(days=1)).isoformat()
    
    with pytest.raises(ValueError):
        validate_sprint_dates(start_str, end_str, today_date=today)