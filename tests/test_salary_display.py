from autojob.extension_fill import salary_display

def test_monthly_range_in_whole_dollars():
    assert salary_display('877.12–1754.23','Salary expectation (In USD per month)')=='877–1754'
    assert salary_display('877.50–1754.51','Salario mensual USD')=='878–1755'

def test_annual_single_value_and_hourly_precision():
    assert salary_display('10525.39','Annual salary USD')=='10525'
    assert salary_display('6.92','Hourly salary USD')=='6.92'
    assert salary_display('Negotiable','Monthly salary')=='Negotiable'
