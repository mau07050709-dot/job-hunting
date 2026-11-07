import pytest
from autojob.search.geography import classify

@pytest.mark.parametrize('place',['Cartago','Paraíso','Oreamuno','El Guarco','La Unión','Turrialba','Jiménez','Alvarado'])
def test_cartago(place):assert classify(place+', Costa Rica','','onsite')['status']=='CONFIRMADO'
def test_cartago_not_colombia():assert classify('Cartago, Colombia','','hybrid')['status']=='INCOMPATIBLE'
def test_town_needs_country():assert classify('La Unión','','onsite')['status']=='DESCONOCIDO'
def test_excluded_country():assert classify('Worldwide','Remote worldwide excluding Costa Rica')['status']=='INCOMPATIBLE'
def test_residence():assert classify('Remote','Applicants must reside in United States')['status']=='INCOMPATIBLE'
def test_company_hq_not_candidate_eligibility():assert classify('Remote','Our headquarters are in Costa Rica')['status']=='POSIBLE'
def test_candidate_country():assert classify('Remote','We are hiring in Costa Rica')['status']=='CONFIRMADO'
def test_timezone_review():assert classify('Worldwide','Required UTC time zone overlap')['status']=='POSIBLE'
def test_disabled_town():assert classify('Turrialba, Costa Rica','','hybrid',enabled=['Cartago'])['status']=='INCOMPATIBLE'
