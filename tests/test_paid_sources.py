from autojob.search.access_policy import excluded_job,paywall_page,paywall_url
from autojob.manual_search import useful_url
from autojob.search.jobs import ENDPOINTS,JobStore
from autojob.search.availability import inspect_page,Availability

PAY='https://weworkremotely.com/job-seekers/onboarding/step_3?context=paywall&from_listing_id=47993&payment_plan=top_access'
JOB=dict(id='test',source='We Work Remotely',source_id='test',company='Example',title='Support',url='https://weworkremotely.com/remote-jobs/example-support',description='Public role',location='Worldwide',geography='POSIBLE',modality='remote')

def test_remote_ok_disabled_even_if_saved_source():
    assert 'Remote OK' not in ENDPOINTS
    assert not useful_url('https://remoteok.com/remote-jobs/example-123')
    assert excluded_job(dict(source='Remote OK',url='https://employer.example/role'))

def test_paid_link_and_redirect_are_excluded():
    assert paywall_url(PAY) and not useful_url(PAY)
    assert inspect_page(JOB,200,PAY,'Choose your plan')['application_access']=='PAGO'
    assert paywall_page(JOB['url'],f'<a href="{PAY.replace("&","&amp;")}">Apply now</a>')

def test_free_listing_not_excluded_by_generic_premium_ad():
    # La detección de pago no debe confundir anuncios genéricos; aun así
    # WWR completo está excluido por la nueva preferencia del usuario.
    assert excluded_job(JOB)
    assert not useful_url(JOB['url'])
    assert not paywall_page(JOB['url'],'<h1>Support</h1><aside>Premium subscription available</aside><a href="https://employer.example/apply">Apply now</a>')

def test_paywall_persistence_and_saved_results(tmp_path):
    from autojob.manual_search import ResultsStore
    jobs=JobStore(tmp_path);jobs.add(dict(JOB,source='Official',url='https://employer.example/job/support'));job=jobs.list()[0];results=ResultsStore(jobs.db)
    results.save(dict(results=[dict(job=job,url=job['url'])],review=[]))
    assert results.latest()['results']
    Availability(jobs).check(job,fetch=lambda u:(200,PAY,'Select your payment plan'),force=True)
    assert excluded_job(jobs.list()[0])
    assert not ResultsStore(jobs.db).latest()['results']

def test_old_saved_remoteok_not_displayed(tmp_path):
    from autojob.manual_search import ResultsStore
    store=ResultsStore(JobStore(tmp_path).db)
    store.save(dict(results=[dict(job=dict(JOB,source='Remote OK'),url='https://remoteok.com/job/123')],review=[]))
    assert not store.latest()['results']


def test_wwr_fully_excluded_including_unverified_and_old_settings(tmp_path):
    from autojob.manual_search import ResultsStore
    assert 'We Work Remotely' not in ENDPOINTS
    store=ResultsStore(JobStore(tmp_path).db)
    row=dict(job=JOB,url=JOB['url'])
    store.save(dict(results=[row],review=[row]))
    assert not store.latest()['results'] and not store.latest()['review']
    result=JobStore(tmp_path).search(['Support'],['We Work Remotely','Remote OK'])
    assert result['found']==0 and not result['errors']
