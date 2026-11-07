from copy import deepcopy
from autojob.profile.answers import AnswerBank,resolve_question
from autojob.profile.store import ProfileStore,empty
from autojob.profile.soft_skills import extract_soft_skills

def test_equivalent_questions_and_unknown(tmp_path):
 p=ProfileStore(tmp_path).load();v=deepcopy(p['values']);v['full_name']='Example Person';p=ProfileStore(tmp_path).save(v,p['revision'])
 for q in ('What is your full name?','Nombre completo'):
  result=resolve_question(q,{},p);assert result.answer=='Example Person' and result.automatic and result.category=='CONFIRMADA'
 result=resolve_question('What is your favorite planet?',{},p);assert result.category=='DESCONOCIDA' and not result.automatic

def test_legal_question_never_automatic(tmp_path):
 p=ProfileStore(tmp_path).load();assert resolve_question('Are you legally authorized to work in Costa Rica?',{},p).category=='SENSIBLE'

def test_bank_persistence_and_stale_profile(tmp_path):
 store=ProfileStore(tmp_path);p=store.load();bank=AnswerBank(tmp_path)
 bank.save('Información personal','en',['What is your full name?'],'Example Person',True,p)
 assert resolve_question('Full name',{'language':'en'},p,AnswerBank(tmp_path)).answer=='Example Person'
 v=deepcopy(p['values']);v['city']='Cartago';p=store.save(v,p['revision'])
 assert not resolve_question('Full name',{'language':'en'},p,bank).automatic

def test_soft_skills_found_only_in_cv():
 result=extract_soft_skills([{'text':'Teamwork and communication, teamwork. Fast learning.'}])
 assert len(result)==3 and not any('adapt' in x.casefold() for x in result)
