import os
from pathlib import Path
import pytest
from playwright.sync_api import expect
from autojob.browser import BraveSession
from autojob.config import Settings
from autojob.profile.store import ProfileStore
from autojob.profile.answers import resolve_question
from autojob.testing.server import local_server

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Abre Brave real solo bajo petición')
def test_local_form_uses_confirmed_profile_and_blocks_unknown(tmp_path):
 settings=Settings(root=tmp_path,headless=True);store=ProfileStore(settings.data_path);state=store.load();values=state['values'];values['full_name']='Persona Ejemplo';values['email']='test@example.invalid';state=store.save(values,state['revision'])
 attachment=tmp_path/'cv-prueba.txt';attachment.write_text('Documento ficticio',encoding='utf-8')
 with local_server() as (url,received),BraveSession(settings) as browser:
  page=browser.new_page(url)
  for question,label in [('Nombre completo','Nombre completo'),('Correo electrónico','Correo electrónico')]:
   answer=resolve_question(question,{'language':'es'},state)
   assert answer.automatic
   page.get_by_label(label).fill(answer.answer)
  page.get_by_label('Documento de prueba').set_input_files(attachment)
  expect(page.get_by_label('Nombre completo')).to_have_value('Persona Ejemplo')
  expect(page.get_by_label('Correo electrónico')).to_have_value('test@example.invalid')
  assert page.get_by_label('Documento de prueba').evaluate('e => e.files[0].name')==attachment.name
  assert not resolve_question('Número de pasaporte',{'language':'es'},state).automatic
  assert received==[]
