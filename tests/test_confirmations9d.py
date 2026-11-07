import pytest
from autojob.forms.confirmations import detect,response_signal

@pytest.mark.parametrize('text',['Your application was successfully submitted.','Application received','Thank you for applying!','Thanks for your application','Su solicitud fue recibida','Postulación recibida'])
def test_visible_receipt_and_http_acceptance(text):
    r=detect(text,'https://portal.invalid/receipt',[response_signal(200)],True);assert r['state']=='ENVIADA CONFIRMADA';assert r['receipt_id'] is None
def test_http200_alone_is_not_confirmation():assert detect('Processing','https://portal.invalid',[response_signal(200)],True)['state']=='ENVÍO NO VERIFICADO'
def test_success_false_overrules_http200():assert detect('Validation error','https://portal.invalid',[response_signal(200,dict(success=False,errors=['private value not stored']))],True)['state']=='RECHAZADA'
def test_server500_is_uncertain():assert detect('Internal server error','https://portal.invalid',[response_signal(500)],True)['state']=='ENVÍO NO VERIFICADO'
def test_unrelated_identifier_without_accepted_response_is_uncertain():assert detect('Details','https://portal.invalid',[response_signal(200)],True,'12345')['state']=='ENVÍO NO VERIFICADO'
def test_accepted_response_and_application_id():assert detect('Details','https://portal.invalid',[response_signal(201,dict(success=True,application_id='APP-12345'))],True)['state']=='ENVIADA CONFIRMADA'
def test_generic_thanks_requires_expected_route_and_json_acceptance():
    args=('Thank you!','https://portal.invalid/receipt',[response_signal(200,dict(success=True))],True)
    assert detect(*args)['state']=='ENVÍO NO VERIFICADO';assert detect(*args,expected_confirmation='https://portal.invalid/receipt')['state']=='ENVIADA CONFIRMADA'
def test_no_transmission_does_not_count_generic_public_receipt():assert detect('Application received','https://portal.invalid',[response_signal(200)],False)['state']=='ENVÍO NO VERIFICADO'
def test_conflicting_signals_are_not_confirmed():assert detect('Application received','https://portal.invalid',[response_signal(200,dict(success=False))],True)['state']=='ENVÍO NO VERIFICADO'
def test_response_body_not_retained():
    r=response_signal(400,dict(error='private@example.invalid',first_name='SECRET'));assert 'SECRET' not in str(r);assert '@' not in str(r);assert r['rejected']
