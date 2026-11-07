"""Validación cerrada de la cola usando únicamente identidad y archivos ficticios."""
from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
from autojob.forms.controlled import controlled_site
from autojob.forms.queue import PreparationQueue
from autojob.forms.runner import process
from autojob.config import Settings

def run_lab(settings,confirm_unknown=True):
 from docx import Document
 with TemporaryDirectory(prefix='autojob-7b-lab-') as folder,controlled_site() as fixture:
  root=Path(folder);q=PreparationQueue(root);data=q.preparation.data
  values={'first_name':'Test','last_name':'Candidate','birth_date':'2000-02-03','own_computer':True,'main_min':'1000','main_max':'1500','main_expected':'1200','main_currency':'USD','main_period':'month','main_hours':'40'};data.save(values,confirmed=values)
  profile=data.profile.load();profile['values']['full_name']='Test Candidate';profile['values']['email']='candidate@example.invalid';data.profile.save(profile['values'],profile['revision'])
  if confirm_unknown:data.faq_save('','Unknown mandatory project code','FICTIONAL-123',True)
  data.faq_save('','Accepted shifts Day','Yes',True);data.faq_save('','Accepted shifts Night','No',True);data.faq_save('','Preferred mode Remote','Remote',True);data.faq_save('','Preferred mode Onsite','Remote',True)
  files={}
  for kind in ('cv','letter'):
   path=root/('fictional-'+kind+'.docx');doc=Document();doc.add_paragraph('FICTIONAL '+kind+' — Test Candidate, no real personal data.');doc.save(path);files[kind]=dict(path=str(path),sha256=sha256(path.read_bytes()).hexdigest())
  fixture['artifact_root']=str(root);fixture['next_urls']={fixture['origin']+'/autojob-test/step1':fixture['origin']+'/autojob-test/step2'}
  for suffix in ['one','two']:
   q.preparation.compatibility.jobs.add(dict(source='CONTROLLED LAB',source_id=suffix,url=fixture['origin']+'/autojob-test/step1?job='+suffix,title='Fictional Customer Support',company='Fictional Company',description='Fictitious local form used only for verification.',location='Worldwide',modality='remote',geography='CONFIRMADO',availability='ABIERTA'))
  jobs=q.preparation.compatibility.jobs.list();q.add([j['id'] for j in jobs])
  # La URL de inspección se controla en la cola; el identificador de vacante sigue siendo distinto.
  from contextlib import closing
  with closing(q.db.connect()) as db,db:db.execute('UPDATE preparation_queue SET url=?',(fixture['origin']+'/autojob-test/step1',))
  result=q.run(settings,processor=lambda queue,row,s,p,c,r:process(queue,row,s,p,c,r,fixture,files));rows=q.list()
  assert result['processed']==2 and all(r['state']==('PREPARADA' if confirm_unknown else 'PENDIENTE') for r in rows)
  assert all(r['stage']==2 for r in rows) and all(len(r['payload']['filled'])>=(11 if confirm_unknown else 10) for r in rows)
  assert all(req['method']=='GET' for req in fixture['requests'])
  # Probar parada/reanudación por separado sin volver a usar acciones externas.
  q.requeue([r['job_id'] for r in rows]);flag=[False]
  def partial(queue,row,*args):flag[0]=True;return dict(row['payload'],interrupted=True)
  paused=q.run(settings,pause=lambda:flag[0],processor=partial);assert paused['paused']
  persisted=PreparationQueue(root);assert len(persisted.list())==2
  return dict(processed=result['processed'],prepared=sum(r['state']=='PREPARADA' for r in rows),states=[r['state'] for r in rows],stages_per_form=2,verified_fields=[len(r['payload']['filled']) for r in rows],attachments_fictional=True,submitted=False,requests=fixture['requests'],pause_verified=paused['paused'],persistence_verified=True)
