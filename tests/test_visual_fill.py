import asyncio,time
import pytest
from autojob.extension_fill import ExtensionFill,allow_entry,allowed_page
from autojob.config import Settings
from autojob.ui.visual_fill import form_labels,VisualWorker,VisualFill

@pytest.mark.parametrize('text,expected',[('First Name Last Name Email',True),('Nombre Apellidos Correo electrÃ³nico',True),('Buscar empleos por email',False),('Verify you are human',False)])
def test_visual_labels(text,expected):assert form_labels(text)==expected


def test_bamboo_scoped_to_company_and_job():
 t=dict(url='https://himalayas.app/companies/leap-event-technology/jobs/part-time-customer-care-agent',job=dict(company='Leap Event Technology'))
 assert allow_entry(t,'https://leapeventtech.bamboohr.com/careers/59?source=himalayas')
 assert allowed_page(t,'https://leapeventtech.bamboohr.com/careers/59/application')
 assert not allowed_page(t,'https://leapeventtech.bamboohr.com/careers/590')
 assert not allow_entry(t,'https://another.bamboohr.com/careers/59')
 assert not allow_entry(t,'https://leapeventtech.bamboohr.com.evil.example/careers/59')


def test_visual_reinspection_is_scoped_and_not_an_answer(tmp_path):
 s=Settings(tmp_path);s.data_path.mkdir();b=ExtensionFill(s)
 b.tasks['t']=dict(id='t',url='https://example.invalid/job',state='DONE',job={})
 b.handle('/visual',dict(id='t',url='https://example.invalid/job',title='Application',height=900,captcha=False))
 assert b.visual_target()['id']=='t'
 assert not b.visual_detected('t','https://other.invalid/job')
 assert b.visual_detected('t','https://example.invalid/job')
 assert b.handle('/visual-next',{})==[dict(id='t',url='https://example.invalid/job')]
 assert b.handle('/visual-next',{})==[]
 b.handle('/visual',dict(id='t',url='https://example.invalid/job',title='Application',height=900,captcha=True))
 assert b.visual_target() is None
 b.visual['seen']=time.monotonic()-6
 assert b.visual_target() is None


def test_actual_windows_ocr_in_worker(tmp_path,qt_application_lifetime,await_ui):
 from PySide6.QtGui import QImage,QPainter,QFont,QFontDatabase
 from PySide6.QtCore import QBuffer,QIODevice
 assert QFontDatabase.addApplicationFont('C:/Windows/Fonts/arial.ttf')>=0
 image=QImage(800,220,QImage.Format.Format_RGB32);image.fill('white')
 painter=QPainter(image);painter.setPen('black');painter.setFont(QFont('Arial',28))
 painter.drawText(30,70,'First Name    Last Name');painter.drawText(30,150,'Email');painter.end()
 buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buffer,'PNG')
 result=[];worker=VisualWorker(dict(id='test',url='https://example.invalid'),bytes(buffer.data()))
 worker.result.connect(lambda *r:result.append(r));worker.start()
 await_ui(lambda:bool(result),20000)
 await_ui(lambda:not worker.isRunning(),10000)
 assert result==[('test','https://example.invalid',True,'')]
 worker.deleteLater()
