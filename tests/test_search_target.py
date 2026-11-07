from copy import deepcopy
import pytest
from autojob.config import Settings
from autojob.manual_search import ManualSearch,ResultsStore,application_rows,identity_keys,matching_job,location_priority

def setup(root,count=5):
    from test_batch_https import seed
    store,cv=seed(root);p=store.prep.compatibility.profile;s=p.load();v=s['values'];v['work_authorization']=True;p.save(v,s['revision'],confirmed=['work_authorization'])
    engine=ManualSearch(Settings(root));original=engine.jobs.list()[0]
    engine.results.save(dict(results=[dict(job=original,url=original['application_url'])],review=[]))
    for i in range(count):
        j=dict(original,source_id='new-'+str(i),url=f'https://employer.example/jobs/{i}',application_url=f'https://employer.example/jobs/{i}',company='Fictional '+str(i))
        engine.jobs.add(j)
    return engine

def run(engine,n=3,**kw):
    return engine.run(dict(target=n,queries=['Python'],sources=[]),services=dict(search=lambda *a:dict(errors=[]),check=lambda j:None),**kw)

def test_target_counts_only_new_distinct_jobs_and_accumulates_after_restart(tmp_path):
    e=setup(tmp_path);first=run(e)
    assert first['new_count']==3 and len(application_rows(first))==4
    second=run(e)
    assert second['new_count']==2 and len(application_rows(second))==6
    assert 'no se completó el objetivo' in second['reason']
    restarted=ManualSearch(Settings(tmp_path))
    assert len(application_rows(restarted.results.latest()))==6
    assert restarted.results.target()==3
    assert run(restarted)['new_count']==0

@pytest.mark.parametrize('value',[0,51,True,1.5])
def test_reject_invalid_target_without_losing_existing_rows(tmp_path,value):
    e=setup(tmp_path,0)
    with pytest.raises(ValueError):run(e,value)
    assert len(application_rows(e.results.latest()))==1

def test_cancel_preserves_prior_applications(tmp_path):
    e=setup(tmp_path)
    r=run(e,pause=lambda:True)
    assert r['state']=='PAUSADO' and r['new_count']==0
    assert len(application_rows(r))==1

def test_canonical_employer_apply_url_is_one_logical_job(tmp_path):
    e=setup(tmp_path,0);row=application_rows(e.results.latest())[0]
    other=deepcopy(row);other['job']['id']='another-source';other['job']['url']='https://other-source.example/job/1';other['url']=row['url']+'?utm_source=other'
    assert not e.results.add(other)
    assert len(application_rows(e.results.latest()))==1

def test_confirmed_geo_legal_restrictions_and_rank():
    j=dict(title='Customer Support',geography='CONFIRMADO',modality='remote',location='Costa Rica')
    ev=dict(eligibility='REQUIERE REVISIÓN',score=75,geography='CONFIRMADO',assessments=[])
    assert matching_job(j,ev,{'customer_service'})
    assert not matching_job(dict(j,title='Customer Service Representative (Mexico)'),ev,{'customer_service'})
    assert not matching_job(dict(j,geography='DESCONOCIDO'),ev,{'customer_service'})
    restricted=dict(ev,assessments=[dict(kind='authorization',importance='OBLIGATORIO',state='POR VERIFICAR')])
    assert not matching_job(j,restricted,{'customer_service'})
    assert location_priority(j)<location_priority(dict(j,location='LATAM'))<location_priority(dict(j,modality='onsite'))

def test_targeted_pagination_uses_cr_filter_and_stops_exhausted(tmp_path):
    from autojob.search.targeted import TargetedPages
    from autojob.search.jobs import JobStore,Connector
    from urllib.parse import urlsplit,parse_qs
    seen=[]
    def fetch(url):
        q=parse_qs(urlsplit(url).query);seen.append(q)
        assert q['country']==['CR']
        return dict(jobs=[])
    pages=TargetedPages(JobStore(tmp_path),['python'],lambda:False,lambda s:None,fetch=fetch)
    assert len(list(pages))==2
    assert all(q['page']==['1'] for q in seen)
    # Una búsqueda repetida usa la caché diaria, sin repetir HTTP.
    list(TargetedPages(JobStore(tmp_path),['python'],lambda:False,lambda s:None,fetch=lambda u:pytest.fail('No usar caché')))
    row=dict(title='Junior Python Developer',companyName='Example',guid='https://himalayas.app/companies/example/jobs/junior',description='Python',locationRestrictions=[],timezoneRestrictions=['-6'],applicationLink='https://employer.example/job/1')
    job=list(Connector('Himalayas').search_jobs([],payload=dict(jobs=[row],_country_filter='CR')))[0]
    assert job['geography']=='CONFIRMADO' and job['structured_discovery_at']
