from autojob.search.availability import inspect_page
from autojob.search.geography import classify
from autojob.search.jobs import Connector,JobStore
from autojob.autonomous import verified_jobs

JOB=dict(id='j',title='Customer Support',url='https://example.invalid/job/123')

def test_application_without_expiry_is_not_rejected():
    body='<h1>Customer Support</h1><a href="https://jobs.example.invalid/job/123/apply">Apply now</a>'
    r=inspect_page(JOB,200,JOB['url'],body)
    assert r['state']=='ABIERTA' and r['application_access']=='ACCESIBLE'
    assert r['application_url'].endswith('/123/apply')

def test_general_search_link_does_not_validate_application():
    assert inspect_page(JOB,200,JOB['url'],'<h1>Customer Support</h1><a href="/jobs">Apply now</a>')['state']=='NO VERIFICADA'

def test_redirect_with_wrong_title_and_explicit_closed():
    assert inspect_page(JOB,200,'https://example.invalid/jobs','Other role <a href="/apply">Apply</a>')['state']=='NO VERIFICADA'
    assert inspect_page(JOB,200,JOB['url'],'Customer Support This job is not available')['state']=='CERRADA'

def test_worldwide_and_empty_country_list_are_not_confirmations():
    assert classify('Worldwide','Customer Support')['status']=='POSIBLE'
    row=dict(id='a',title='Customer Support',companyName='Example',url=JOB['url'],description='Support customers',locationRestrictions=[])
    assert next(Connector('Himalayas').search_jobs([],payload={'jobs':[row]}))['geography']=='POSIBLE'

def test_all_sources_and_more_than_ten_results_persist(tmp_path,monkeypatch):
    rows=[dict(id=n,title='Customer Support',company_name='Example '+str(n),url='https://example.invalid/job/'+str(n),description='Help customers') for n in range(36)]
    calls=[]
    def fetch(self,url):calls.append(self.name);return rows
    monkeypatch.setattr(Connector,'_fetch',fetch)
    store=JobStore(tmp_path);r=store.search(['Support'],['Remotive','Remote OK'],None)
    assert r['found']==36 and r['duplicates']==36 and len(calls)==2
    assert len(JobStore(tmp_path).list())==36

def test_bounded_verification_continues_after_failure_and_cancels():
    jobs=[dict(id=str(n),company='Example',title='Support') for n in range(40)];seen=[]
    def check(j):
        seen.append(j['id'])
        if j['id']=='2':raise TimeoutError()
    assert len(list(verified_jobs(jobs,check,lambda:False,lambda s:None)))==40
    assert len(set(seen))==40
    assert list(verified_jobs(jobs,check,lambda:True,lambda s:None))==[]


def test_actual_apply_destination_404_does_not_enter_active_queue(tmp_path):
    from autojob.search.availability import Availability
    store=JobStore(tmp_path)
    store.add(dict(JOB,company='Example',source='Test',source_id='x',description='Support'))
    job=store.list()[0];calls=[]
    def fetch(url):
        calls.append(url)
        if len(calls)==1:return 200,url,'<h1>Customer Support</h1><a href="/job/123/apply">Apply now</a>'
        return 404,url,''
    result=Availability(store).check(job,fetch)
    assert result['state']=='CERRADA' and len(calls)==2
    assert store.list()[0]['availability']=='CERRADA'


def test_reserved_brave_keeps_all_jobs_without_blocking_worker(tmp_path,monkeypatch):
    from test_redesign import seed
    from autojob.config import Settings
    from autojob.autonomous import AutomaticCoordinator
    from autojob.forms import execution
    store,cv=seed(tmp_path);engine=AutomaticCoordinator(Settings(tmp_path))
    base=engine.jobs.list()[0]
    for n in range(12):engine.jobs.add(dict(base,source_id='defer-'+str(n),company='Local '+str(n),url='https://jobs.lever.co/defer-'+str(n),application_url='https://jobs.lever.co/defer-'+str(n)+'/apply'))
    engine.delivery_authorization=execution.begin(store,30)
    monkeypatch.setattr(engine.sessions,'preparing_count',lambda:3)
    monkeypatch.setattr(engine.sessions,'park_idle',lambda:False)
    result=engine.run(dict(queries=[],sources=[],limit=None),services=dict(search=lambda *a:dict(found=0),geography=lambda *a:None,availability=lambda *a:None))
    assert result['browser_deferred']==13 and len(engine.queue.list())==13
    assert not result['deliveries'] and result['state']!='ERROR'


def test_stop_is_persisted_without_turning_into_error(tmp_path):
    from test_redesign import seed
    from autojob.config import Settings
    from autojob.autonomous import AutomaticCoordinator
    from autojob.forms import execution
    store,cv=seed(tmp_path);engine=AutomaticCoordinator(Settings(tmp_path))
    engine.delivery_authorization=execution.begin(store,30)
    result=engine.run(dict(queries=[],sources=[]),stop=lambda:True)
    assert result['state']=='DETENIDO' and engine.store.latest()['state']=='DETENIDO'
