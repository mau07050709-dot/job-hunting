import json
from autojob.search.availability import inspect_page,Availability
from autojob.search.jobs import JobStore

JOB=dict(id='1',title='Developer',url='https://example.invalid/job')
def test_plain_200_is_not_open():assert inspect_page(JOB,200,JOB['url'],'Developer')['state']=='NO VERIFICADA'
def test_deleted_and_redirect():
 assert inspect_page(JOB,404,JOB['url'],'')['state']=='CERRADA'
 assert inspect_page(JOB,200,'https://example.invalid/home','Welcome')['state']=='NO VERIFICADA'
def test_captcha_and_disabled():
 assert inspect_page(JOB,200,JOB['url'],'Developer CAPTCHA')['state']=='NO VERIFICADA'
 assert inspect_page(JOB,200,JOB['url'],'Developer <button disabled>Apply</button>')['state']=='CERRADA'
def test_explicit_jobposting():
 body='Developer <a href="/apply">Apply now</a><script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'Developer','validThrough':'2099-01-01'})+'</script>'
 assert inspect_page(JOB,200,JOB['url'],body)['state']=='ABIERTA'
 assert inspect_page(JOB,200,JOB['url'],body.replace('2099','2000'))['state']=='CERRADA'
def test_persistence_cache_cancel(tmp_path):
 store=JobStore(tmp_path);job=dict(JOB,source='Test',source_id='1',company='Example',location='Remote',description='Python');store.add(job);job=store.list()[0];service=Availability(store)
 result=service.check(job,lambda url:(404,url,''));assert result['state']=='CERRADA';assert service.check(job)['cached'];assert len(service.history(job['id']))==1
 assert service.batch([job],cancel=lambda:True)==[]
