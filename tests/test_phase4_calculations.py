from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
import pytest
from autojob.profile.calculations import age, salary, convert_time

def test_age_before_birthday():
    assert age(date(2000, 11, 1), date(2026, 10, 30)) == 25
    with pytest.raises(ValueError): age(date(2030, 1, 1), date(2026, 1, 1))

def test_salary_conversion():
    assert salary(1200, "month", "year", 40) == Decimal(14400)
    assert salary(20, "hour", "week", 40) == Decimal(800)
    with pytest.raises(ValueError): salary(1, "month", "hour", 0)

def test_dst_conversion():
    winter = datetime(2026, 1, 15, 9, tzinfo=ZoneInfo("America/Los_Angeles"))
    summer = datetime(2026, 7, 15, 9, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert convert_time(winter, "America/Los_Angeles", "America/Costa_Rica").hour == 11
    assert convert_time(summer, "America/Los_Angeles", "America/Costa_Rica").hour == 10
