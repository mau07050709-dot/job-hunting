"""Interfaz cotidiana de tres secciones sobre los servicios conservados."""
from contextlib import closing
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QObject
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QPushButton,QLabel,QTableWidget,QTableWidgetItem,QDialog,QTabWidget,QFormLayout,QLineEdit,QPlainTextEdit,QSpinBox,QFileDialog,QMessageBox,QCheckBox,QInputDialog,QDialogButtonBox,QComboBox
from autojob.ui.control_shell import Shell,Interventions,ControlWorker
from autojob.forms.submissions import SubmissionStore
from autojob.forms import execution
from autojob.ui.background import submit
from autojob.manual_search import application_rows

class StartPage(QWidget):
    def __init__(self,shell):
        super().__init__();self.shell=shell;layout=QVBoxLayout(self)
        self.attach=QPushButton('ADJUNTAR CV');self.start=QPushButton('INICIAR Job Hunting');self.pause=QPushButton('PAUSAR')
        self.start.setObjectName('primaryAction')
        for b in (self.attach,self.start):b.setMinimumHeight(50)
        self.attach.clicked.connect(shell.import_cvs);self.start.clicked.connect(lambda:shell.start(user_initiated=True));self.pause.clicked.connect(shell.pause)
        self.start.setEnabled(False)
        layout.addWidget(self.attach)
        target_row=QHBoxLayout();target_row.addWidget(QLabel('Vacantes nuevas a buscar (máximo 50)'))
        self.search_target=QSpinBox();self.search_target.setObjectName('new_vacancy_target');self.search_target.setRange(1,50);self.search_target.setValue(shell.engine.results.target());self.search_target.valueChanged.connect(shell.engine.results.set_target);target_row.addWidget(self.search_target);target_row.addStretch();layout.addLayout(target_row)
        priority=QLabel('Prioridad: trabajo remoto desde Costa Rica. Cada búsqueda añade ofertas nuevas y conserva las anteriores.');priority.setWordWrap(True);layout.addWidget(priority)
        layout.addWidget(self.start);layout.addWidget(self.pause);self.pause.hide()
        self.active=QLabel('No hay una candidatura activa.');self.active.setWordWrap(True);layout.addWidget(self.active)
        self.skip=QPushButton('SALTAR Y CONTINUAR');self.skip.setObjectName('skip_current_application');self.skip.setMinimumHeight(42);self.skip.clicked.connect(shell.skip_current);self.skip.setEnabled(False);layout.addWidget(self.skip)
        self.status=QLabel('Adjunta tus CV, completa tu información y pulsa INICIAR. Al terminar encontrarás todas las ofertas en POSTULACIONES.');self.status.setWordWrap(True);self.status.setObjectName('statusPanel');layout.addWidget(self.status)
        self.skip.hide()
        self.cards={};grid=QGridLayout()
        for n,(key,title) in enumerate([('found','Vacantes encontradas'),('compatible','Compatibles'),('pending','Pendientes'),('sent','Enviadas confirmadas'),('interventions','Intervenciones necesarias')]):
            label=QLabel(title+'\n0')
            label.setObjectName('summaryCard');self.cards[key]=label
            if key=='pending':label.setParent(self);label.hide()
            else:
                visible=n-(1 if n>2 else 0);grid.addWidget(label,visible//3,visible%3)
        layout.addLayout(grid);layout.addStretch()
        # Interfaces conservadas requieren estas referencias, sin controles extra visibles.
        self.mode=QLabel();self.authorization_status=QLabel();self.goal=QLabel();self.browser_state=QLabel();self.stop=QPushButton();self.note=QLabel()
        for w in (self.mode,self.authorization_status,self.goal,self.browser_state,self.stop,self.note):w.setParent(self);w.hide()
    def update_authorization(self):return bool(self.shell.delivery_authorization)
    def refresh(self):self.shell.request_refresh()

class ResumePage(QWidget):
    def __init__(self,shell):
        super().__init__();self.shell=shell;layout=QVBoxLayout(self);row=QHBoxLayout()
        people_row=QHBoxLayout()
        people_row.addWidget(QLabel('Persona activa'))
        self.person_selector=QComboBox()
        self.person_selector.setObjectName('person_selector')
        self.new_person_button=QPushButton('AÑADIR PERSONA')
        self.rename_person_button=QPushButton('CAMBIAR ALIAS')
        self.reload_people()
        self.person_selector.currentIndexChanged.connect(self.select_person)
        self.new_person_button.clicked.connect(self.new_person)
        self.rename_person_button.clicked.connect(self.rename_person)
        people_row.addWidget(self.person_selector,1)
        people_row.addWidget(self.new_person_button)
        people_row.addWidget(self.rename_person_button)
        layout.addLayout(people_row)
        layout.addWidget(QLabel("Los CV que importes y los datos que guardes pertenecen a la persona seleccionada."))
        for text,fn in [('IMPORTAR CV',shell.import_cvs),('ELIMINAR CV',self.remove),('REVISAR Y CORREGIR',self.review),('INFORMACIÓN ADICIONAL',shell.additional)]:
            b=QPushButton(text);b.clicked.connect(fn);row.addWidget(b)
        layout.addLayout(row)
        done=QPushButton('POSTULACIONES HECHAS');done.setObjectName('completed_applications');done.clicked.connect(shell.show_completed);layout.addWidget(done)
        self.locality_button=QPushButton('ELEGIR LOCALIDAD PARA PUESTOS PRESENCIALES')
        self.locality_button.clicked.connect(shell.choose_localities)
        layout.addWidget(self.locality_button)
        self.locality_summary=QLabel()
        self.locality_summary.setWordWrap(True)
        layout.addWidget(self.locality_summary)
        self.update_localities()
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Nombre','Idioma','Especialidad','Estado']);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);layout.addWidget(self.table);self.rows=[]
    def reload_people(self):
        self.person_selector.blockSignals(True)
        self.person_selector.clear()
        for person in self.shell.window.people.rows():
            self.person_selector.addItem(person['alias'],person['id'])
        self.person_selector.setCurrentIndex(self.person_selector.findData(self.shell.window.person['id']))
        self.person_selector.blockSignals(False)

    def select_person(self,index):
        person_id=self.person_selector.itemData(index)
        if person_id and not self.shell.window.switch_person(person_id):
            self.reload_people()

    def new_person(self):
        alias,accepted=QInputDialog.getText(self,'Añadir persona','Alias de la persona')
        if not accepted:return
        try:
            person=self.shell.window.people.create(alias)
        except ValueError as exc:
            self.shell.home.status.setText(str(exc))
            return
        self.reload_people()
        self.shell.window.switch_person(person['id'])

    def rename_person(self):
        window=self.shell.window
        alias,accepted=QInputDialog.getText(self,'Cambiar alias','Alias de la persona',text=window.person['alias'])
        if not accepted:return
        try:
            window.person=window.people.rename(window.person['id'],alias)
        except ValueError as exc:
            self.shell.home.status.setText(str(exc))
            return
        self.reload_people()
        self.shell.home.active.setText('Persona activa: '+window.person['alias']+' · Búsqueda según sus CV y preferencias')
        self.shell.posts.person_label.setText('Postulaciones de '+window.person['alias'])

    def update_localities(self):
        from autojob.search.onsite import OnsitePreferences
        places=OnsitePreferences(self.shell.settings.data_path).load()['localities']
        self.locality_summary.setText('Presencial en Costa Rica: '+(', '.join(places) if places else 'desactivado')+
                                      '. Remoto desde Costa Rica: empresas de cualquier país. Se buscan también puestos nocturnos y atención en tiendas.')
    def selected(self):
        n=self.table.currentRow();return self.rows[n] if 0<=n<len(self.rows) else None
    def refresh(self):
        self.render(self.shell.engine.compatibility.library.list())
    def render(self,rows):
        if rows==self.rows:return
        selected=self.selected();id=selected['id'] if selected else None;self.rows=rows;self.table.setRowCount(len(self.rows))
        for n,r in enumerate(self.rows):
            for c,v in enumerate([r['title'],r['language'],r['specialty'],'Revisado' if r['reviewed'] else 'Por revisar']):self.table.setItem(n,c,QTableWidgetItem(v))
            if r['id']==id:self.table.selectRow(n)
        self.table.horizontalHeader().setStretchLastSection(True);self.table.setColumnWidth(0,380)
    def review(self):
        r=self.selected();w=self.shell.window.resumes_widget;w.refresh(r['id'] if r else None);self.shell.dialog_widget('REVISAR Y CORREGIR',w)
    def remove(self):
        r=self.selected()
        if not r:return
        if QMessageBox.question(self,'Eliminar CV','¿Eliminar «'+r['title']+'» de Job Hunting? Se conserva el documento externo original.')!=QMessageBox.StandardButton.Yes:return
        try:self.shell.engine.compatibility.library.delete(r['id'],r['revision']);self.refresh();self.shell.request_refresh()
        except Exception as e:self.shell.home.status.setText(str(e))

class Questions(QWidget):
    def __init__(self,path):
        super().__init__();from autojob.profile.semantic import SemanticAnswers
        self.store=SemanticAnswers(path);layout=QVBoxLayout(self);form=QFormLayout();self.fields={}
        for key,label in [('question','Pregunta'),('answer','Respuesta'),('language','Idioma (opcional)'),('category','Categoría (opcional)'),('company','Empresa (solo si la respuesta depende de ella)')]:
            w=QLineEdit();self.fields[key]=w;form.addRow(label,w)
        layout.addLayout(form);b=QPushButton('AÑADIR PREGUNTA');b.clicked.connect(self.save);layout.addWidget(b);self.message=QLabel();layout.addWidget(self.message);self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Pregunta','Respuesta','Idioma','Categoría']);layout.addWidget(self.table);self.refresh()
    def save(self):
        try:
            self.store.save(**{k:w.text() for k,w in self.fields.items()});self.message.setText('Respuesta guardada. Se reutilizará cuando coincidan la intención y el contexto.');self.refresh()
        except ValueError as exc:self.message.setText(str(exc))
    def refresh(self):
        rows=self.store.rows();self.table.setRowCount(len(rows))
        for n,r in enumerate(rows):
            for c,k in enumerate(['question','answer','language','category']):self.table.setItem(n,c,QTableWidgetItem(r[k] or ''))

class SelectedApplications(QWidget):
    def __init__(self,shell):
        super().__init__();self.shell=shell;layout=QVBoxLayout(self);self.person_label=QLabel('Postulaciones de '+shell.window.person['alias']);layout.addWidget(self.person_label);self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['Empresa','Puesto','Compatibilidad','Estado','Última actualización']);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);layout.addWidget(self.table);source_note=QLabel('Fuentes públicas: <a href="https://himalayas.app">Himalayas</a>, <a href="https://saplic.com">Saplic</a> y portales indicados en los enlaces.');source_note.setOpenExternalLinks(True);layout.addWidget(source_note);self.message=QLabel();self.message.setWordWrap(True);layout.addWidget(self.message);self.action=QPushButton('RESOLVER AHORA');self.action.clicked.connect(self.resolve);layout.addWidget(self.action);self.table.itemSelectionChanged.connect(self.selection);self.rows=[]
        self.remove_button=QPushButton('ELIMINAR DE MI LISTA');self.remove_button.setObjectName('archive_selected_application');self.remove_button.clicked.connect(self.remove_selected);layout.addWidget(self.remove_button);self.remove_button.setEnabled(False)
        self.done_button=QPushButton('HECHO');self.done_button.setObjectName('mark_application_done');self.done_button.setEnabled(False);self.done_button.clicked.connect(shell.mark_completed);layout.addWidget(self.done_button)
        self.fill_button=QPushButton('RELLENAR AUTOMÁTICAMENTE EN MI BRAVE');self.fill_button.clicked.connect(lambda:shell.fill_selected(self.selected()));layout.addWidget(self.fill_button)
        info=QPushButton('MI INFORMACIÓN Y PREFERENCIAS');info.clicked.connect(shell.additional);layout.addWidget(info)
        links=QPushButton('ACTUALIZAR LISTA');links.clicked.connect(lambda:shell.request_refresh(True));layout.addWidget(links)
        self.message.setTextFormat(Qt.TextFormat.PlainText);self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);self.message.setObjectName('statusPanel')
    def read_rows(self):
        engine=self.shell.engine
        rows=application_rows(engine.results.latest())
        excluded=engine.store.excluded_ids(r['job'] for r in rows)
        from autojob.completed import CompletedApplications
        from autojob.manual_search import identity_keys
        completed=CompletedApplications(self.shell.settings.data_path).keys()
        rows=[r for r in rows if not identity_keys(r['job'],r.get('url')) & completed]
        return [dict(r,confirmed=False,attempt={},queue={},evaluation={},excluded=False,disposition=None) for r in rows if r['job']['id'] not in excluded]
    def refresh_manual(self):
        self.render_manual(self.read_rows())
    def render_manual(self,rows):
        if rows==self.rows:return
        selected=self.selected();id=selected['job']['id'] if selected else None
        self.rows=rows
        self.table.setColumnCount(7);self.table.setHorizontalHeaderLabels(['Empresa','Puesto','Afinidad orientativa','Geografía','Ubicación','Horario','Enlace']);self.table.setRowCount(len(self.rows))
        for n,r in enumerate(self.rows):
            for c,v in enumerate([r['job']['company'],r['job']['title'],r.get('score'),r.get('geography'),r['job'].get('location'),r.get('night_status') or r['job'].get('night_status') or 'No publicado',r['url']]):self.table.setItem(n,c,QTableWidgetItem(str(v if v is not None else 'Desconocido')))
            if r['job']['id']==id:self.table.selectRow(n)
        self.table.setColumnWidth(0,145);self.table.setColumnWidth(1,310);self.table.setColumnWidth(2,150);self.table.setColumnWidth(3,120);self.table.horizontalHeader().setStretchLastSection(True);self.selection()
    def selected(self):
        n=self.table.currentRow();return self.rows[n] if 0<=n<len(self.rows) else None
    def refresh(self,*a,**kw):
        if getattr(self.shell,'manual_mode',False):return self.refresh_manual()
        e=self.shell.engine;queue={r['job_id']:r for r in e.queue.list()};attempts={r['job_id']:r for r in reversed(SubmissionStore(self.shell.settings.data_path).rows())};evaluations=e.compatibility.latest();selected=self.selected();id=selected['job']['id'] if selected else None
        self.rows=[];confirmed_urls=e.store.confirmed_urls();excluded=e.store.excluded()
        for j in e.jobs.list():
            if j['id'] not in queue and j['id'] not in attempts:continue
            disposition=e.store.dispositions.get(j)
            if disposition and disposition['hidden']:continue
            delivery=attempts.get(j['id'],{});q=queue.get(j['id'],{});confirmed=delivery.get('state')=='ENVIADA CONFIRMADA' and delivery.get('evidence',{}).get('verified') is True and (delivery.get('mode')=='local' or j['url'] in confirmed_urls)
            self.rows.append(dict(job=j,confirmed=confirmed,attempt=delivery,queue=q,evaluation=evaluations.get(j['id'],{}),excluded=e.store.is_excluded(j),disposition=disposition))
        self.table.setRowCount(len(self.rows))
        for n,r in enumerate(self.rows):
            j=r['job'];q=r['queue'];state='ENVIADA' if r['confirmed'] else r['attempt'].get('state') if r['attempt'].get('state') in {'ENVÍO NO VERIFICADO','RECHAZADA','ENVIANDO'} else 'DESCARTADA POR EL USUARIO' if r['disposition'] else 'DESCARTADA' if r['excluded'] else 'EN COLA' if q.get('state')=='POR PREPARAR' else 'EN PROCESO' if q.get('state') in {'ANALIZANDO','RELLENANDO'} else 'PENDIENTE';values=[j['company'],j['title'],str(r['evaluation'].get('score','—')),state,r['attempt'].get('updated_at') or r['queue'].get('updated_at') or j.get('discovered_at','')]
            for c,v in enumerate(values):self.table.setItem(n,c,QTableWidgetItem(str(v)))
            if j['id']==id:self.table.selectRow(n)
        self.table.setColumnWidth(0,200);self.table.setColumnWidth(1,350);self.table.horizontalHeader().setStretchLastSection(True);self.selection()
    def selection(self):
        if hasattr(self,'done_button'):self.done_button.setEnabled(bool(self.selected()))
        if getattr(self.shell,'manual_mode',False):
            self.fill_button.setEnabled(bool(self.selected()) and not getattr(self.shell,'_fill_request',False));self.action.setText('ABRIR EN BRAVE PARA POSTULARME');self.action.setEnabled(bool(self.selected()));self.remove_button.setEnabled(bool(self.selected()));return
        if hasattr(self,'remove_button'):self.remove_button.setEnabled(bool(self.selected()))
        r=self.selected();self.action.setEnabled(bool(r));self.action.setText('ABRIR OFERTA DESCARTADA' if r and r.get('excluded') else 'ABRIR POSTULACIÓN' if r and r['confirmed'] else 'REVISAR ENVÍO INCIERTO' if r and r['attempt'].get('state')=='ENVÍO NO VERIFICADO' else 'REVISAR RESULTADO' if r and r['attempt'].get('state')=='RECHAZADA' else 'RESOLVER AHORA')
    def resolve(self):
        if getattr(self.shell,'manual_mode',False):
            r=self.selected()
            if r:
                self.message.setText('Abriendo oferta en tu Brave principal…')
                self.shell.manual_browser.open(r['url'])
            return
        r=self.selected()
        if not r:return
        self.shell.center.feedback('Abriendo '+r['job']['company']+' · '+r['job']['title']+'…')
        if r.get('excluded'):self.shell.view_sent(dict(r,notice='Descartada por indicación del usuario; se abre únicamente para consulta.'));return
        if r['confirmed']:self.shell.view_sent(r);return
        if r['attempt'].get('state') in {'ENVÍO NO VERIFICADO','RECHAZADA'}:
            self.shell.view_sent(r);return
        e=self.shell.engine;j=r['job'];rows=[x for x in e.store.interventions() if x['job_id']==j['id'] and x['state'] in {'PENDIENTE','POSPUESTA'}]
        rows.sort(key=lambda r:0 if r['kind'] in {'INFORMACIÓN FALTANTE','DATO OBLIGATORIO PENDIENTE'} else 1)
        row=rows[0] if rows else dict(job_id=j['id'],company=j['company'],title=j['title'],url=j.get('application_url') or j['url'],kind='REVISIÓN NECESARIA',verification_id=None)
        self.shell.center.resolve(row)

    def remove_selected(self):
        row=self.selected()
        if not row:return
        job=row['job']
        if QMessageBox.question(self,'Eliminar de mi lista','¿Quitar «'+job['company']+' · '+job['title']+'» de tu lista? Se conservará el historial y no volverá a seleccionarse.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.shell.discard_job(job,hide=True)

class SimpleInterventions(Interventions):
    def feedback(self,message):
        self.status.setText(message);self.shell.posts.message.setText(message);self.shell.home.status.setText(message)

    def resolve(self,row=None):
        super().resolve(row)
        self.feedback(self.status.text())

    def later(self,row=None):
        selected=row if isinstance(row,dict) else self.selected()
        super().later(selected)
        task=self.shell.engine.sessions.tasks.get((selected or {}).get('job_id'))
        if task and task.get('readonly'):task['cancel'].set()
        self.feedback(self.status.text())

    def show_problem(self,row,config=None):
        if getattr(self.shell,'manual_mode',False):return
        if row['id'] in self.notified_ids:return
        self.notified_ids.add(row['id'])
        with closing(self.shell.engine.store.db.connect()) as db,db:db.execute('UPDATE control_interventions SET alerted=1 WHERE id=?',(row['id'],))
        d=QDialog(self.window());d.setWindowTitle('Job Hunting');d.setModal(False);d.resize(560,210);box=QVBoxLayout(d)
        detail='Es necesario completar una verificación CAPTCHA en Brave.' if 'CAPTCHA' in row['kind'] else row['message']
        message=QLabel(row['company']+' · '+row['title']+'\n\n'+detail);message.setTextFormat(Qt.TextFormat.PlainText);message.setWordWrap(True);box.addWidget(message);buttons=QHBoxLayout()
        for text,fn in [('RESOLVER AHORA',lambda:self.resolve(row)),('RESOLVER MÁS TARDE',lambda:self.later(row))]:
            b=QPushButton(text);b.clicked.connect(lambda checked=False,fn=fn:(d.close(),fn()));buttons.addWidget(b)
        box.addLayout(buttons);self.popup=d;d.show();d.raise_()
        if (config if config is not None else self.shell.engine.store.config()).get('notifications'):self.tray.showMessage('Job Hunting',row['company']+' · '+row['kind'])
    def resolve_selected(self,row=None):
        row=row if isinstance(row,dict) else self.selected()
        if not row:self.status.setText('Selecciona una intervención de la tabla y pulsa RESOLVER AHORA.');return
        if row.get('kind')=='REVISAR CURRÍCULUMS':self.shell.data_view.review();return
        from autojob.live import historical,command
        from autojob.auth.verifications import VerificationStore
        sender=SubmissionStore(self.shell.settings.data_path)
        if not row.get('job_id') and row.get('verification_id'):
            v=next((v for v in VerificationStore(self.shell.settings.data_path).list() if v['id']==row['verification_id']),None)
            if v:row=dict(row,job_id=v['job_id'],url=v['url'])
        if not row.get('job_id'):self.status.setText('Falta identificar la candidatura.');return
        previous=historical(sender,row['job_id'])
        retained=command(row['job_id'],'FOCUS')
        reserved=[v for v in VerificationStore(self.shell.settings.data_path).list() if v['job_id']==row['job_id'] and v['reserved'] and 'CAPTCHA' in v['kind']]
        for v in reserved:VerificationStore(self.shell.settings.data_path).update(v['id'],command='RESOLVER')
        if retained or self.shell.engine.sessions.contains(row['job_id']):
            if not retained:self.shell.engine.sessions.launch(row['job_id'],self.shell.delivery_authorization,human=True)
            from autojob.live import status
            task=self.shell.engine.sessions.tasks.get(row['job_id'],{})
            self.status.setText(status(row['job_id']) or task.get('message') or 'Abriendo la candidatura seleccionada en Brave…');return
        job=next((j for j in self.shell.engine.jobs.list() if j['id']==row['job_id']),None)
        if not job:
            self.status.setText('La intervención no contiene una referencia válida a una vacante.');self.shell.home.status.setText(self.status.text());return
        if previous:
            attempt=next((a for a in sender.rows() if a['job_id']==job['id']),{})
            self.shell.view_sent(dict(job=job,attempt=attempt));return
        if not self.shell.delivery_authorization:
            try:ticket=execution.preparation_ticket(sender,job)
            except ValueError as exc:
                self.shell.view_sent(dict(job=job,attempt={},notice='La preparación automática está pendiente: '+str(exc)));return
            self.open_direct(dict(row,url=job.get('application_url') or job['url'],preparation_authorization=ticket));return
        from autojob.forms import fiveca
        if job and fiveca.accepts(job.get('application_url') or job['url']) and not historical(SubmissionStore(self.shell.settings.data_path),job['id']):
            d=QDialog(self.window());d.setWindowTitle('Avisos extraordinarios de 5CA');d.resize(700,650);box=QVBoxLayout(d);text=QPlainTextEdit(fiveca.ASSESSMENT+'\n\n'+fiveca.PROCESSING);text.setReadOnly(True);box.addWidget(text)
            a=QCheckBox('Autorizo el tratamiento de los resultados de las evaluaciones');b=QCheckBox('He revisado el aviso y autorizo el tratamiento de esta candidatura');box.addWidget(a);box.addWidget(b);save=QPushButton('GUARDAR Y CONTINUAR');box.addWidget(save)
            def approve():
                if not a.isChecked() or not b.isChecked():return
                execution.approve_extra(SubmissionStore(self.shell.settings.data_path),self.shell.delivery_authorization,job,fiveca.consents());d.close();self.open_direct(row)
            save.clicked.connect(approve);self.popup=d;d.show();return
        try:sender.permission(self.shell.delivery_authorization,job)
        except ValueError as exc:
            self.shell.view_sent(dict(job=job,attempt={},notice='La preparación automática está pendiente: '+str(exc)));return
        # La pregunta pendiente se responde en el propio portal, sin formulario paralelo.
        self.open_direct(dict(row,url=job.get('application_url') or job['url'],company=job['company'],title=job['title']))
    def open_direct(self,row,readonly=False):
        if readonly:return
        sessions=self.shell.engine.sessions
        task=sessions.launch(row['job_id'],row.get('preparation_authorization') or self.shell.delivery_authorization,human=True,preparation_only=bool(row.get('preparation_authorization')))
        message='Recuperando y rellenando la candidatura; se enfocará el campo pendiente en Brave.' if task else 'Hay tres formularios preparados abiertos. Cierra uno para recuperar esta candidatura; sigue guardada en POSTULACIONES.'
        self.feedback(message)
    def direct_finished(self,result):
        if (result.get('result') or {}).get('authorization_required'):
            if getattr(self,'operation_popup',None):self.operation_popup.close()
            self.shell.home.status.setText(result['result']['reason']+' Pulsa INICIAR para incorporar los datos actuales.');self.shell.main.setCurrentIndex(0);self.shell.request_refresh();return
        if not result.get('ok'):
            message=result.get('error','No se pudo recuperar la página. La candidatura sigue pendiente.');self.status.setText(message);self.shell.home.status.setText(message)
            if getattr(self,'operation_popup',None):self.operation_popup.close()
            self.shell.request_refresh();return
        super().direct_finished(result)
    def show_error(self,message,code='I9I_ACTION'):
        self.status.setText(message+' · '+code);self.shell.home.status.setText(self.status.text())

class SimpleShell(Shell):
    def __init__(self,window,engine=None):
        QObject.__init__(self,window)
        self.window=window
        self.settings=window.settings
        self.worker=None
        self.delivery_authorization=None
        self.original_widgets=[]
        self._dialogs=[]
        self._identity_widget=None
        self._center=None
        self.main=QTabWidget()
        self.main.tabBar().setObjectName('main-navigation')
        self.main.setStyleSheet('QTabBar#main-navigation::tab{padding:13px 22px;font-size:15px;font-weight:600} QTabBar#main-navigation::tab:selected{background:#383838;color:white}')
        window.main_tabs=self.main
        window.setCentralWidget(self.main)
        window.setMinimumSize(760,600)
        window.tabs.router=self
        self.schedule_timer=QTimer(window)
        from autojob.manual_search import ManualSearch
        from autojob.ui.manual_results import ManualBrowser
        from autojob.extension_fill import ExtensionFill
        self.manual_mode=True
        self.manual_browser=ManualBrowser(self.settings)
        self.extension_fill=ExtensionFill(self.settings,pair_data_path=window.installation_settings.data_path)
        self.engine=engine or ManualSearch(self.settings)
        self.engine.delivery_authorization=None
        self.home=StartPage(self)
        self.data_view=ResumePage(self)
        self.posts=SelectedApplications(self)
        self.posts.selection()
        for w,title in [(self.home,'INICIO'),(self.data_view,'MIS DATOS'),(self.posts,'POSTULACIONES')]:self.main.addTab(w,title)
        self.empty_configuration=QWidget();self.main.addTab(self.empty_configuration,'CONFIGURACIÓN')
        config_layout=QVBoxLayout(self.empty_configuration);self.change_background_button=QPushButton('CAMBIAR FONDO');self.change_background_button.clicked.connect(self.change_background);config_layout.addWidget(self.change_background_button)
        reset_button=QPushButton('RESTABLECER FONDO PREDETERMINADO')
        reset_button.clicked.connect(lambda:self.change_background(reset=True))
        config_layout.addWidget(reset_button)
        panel_button=QPushButton('ESTILO DE PANELES')
        panel_button.setObjectName('panel_style_button')
        panel_button.clicked.connect(self.choose_panel_style)
        config_layout.addWidget(panel_button)
        from autojob.ui.appearance import MODES
        self.panel_style_status=QLabel('Paneles: '+MODES[window.panel_mode])
        config_layout.addWidget(self.panel_style_status)
        video_button=QPushButton('VIDEO DE LOS AVISOS');video_button.setObjectName('notice_video_settings');video_button.clicked.connect(self.configure_notice_video);config_layout.addWidget(video_button)
        extension_button=QPushButton('VINCULAR EXTENSIÓN DE RELLENADO');extension_button.clicked.connect(self.extension_setup);config_layout.addWidget(extension_button)
        self.background_status=QLabel('Elige una imagen para cualquiera de las pestañas.');self.background_status.setWordWrap(True);config_layout.addWidget(self.background_status);config_layout.addStretch()
        from autojob.ui.background_images import BackgroundImages
        self.background_images=BackgroundImages(window.installation_settings.data_path)
        window.section_backgrounds=self.background_images.load((None,) * 4);window.set_section_background(0)
        self.feed_timer=QTimer(window);self.feed_timer.setSingleShot(True);self.feed_timer.timeout.connect(lambda:self.start(user_initiated=False))
        self.session_timer=QTimer(window);self.session_timer.setInterval(250);self.session_timer.timeout.connect(self.session_tick);self.session_timer.start()
        self.home.active.setText('Persona activa: '+window.person['alias']+' · Búsqueda según sus CV y preferencias')
        self.main.currentChanged.connect(window.set_section_background)
        self.main.setCurrentIndex(0)
        window.setWindowTitle('Job Hunting')
        self.timer=QTimer(window)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self.request_refresh)
        self.timer.start()
        self.refresh_task=None
        self.refresh_pending=False
        self._recovered=False
        self._fill_request=False
        self._show_posts=False
        self._fill_notices={}
        self.request_refresh()
        self.update_people_controls()

    def can_change_person(self):
        if self.busy() or self._fill_request or self.extension_fill.busy():
            return False
        if self.window.worker and self.window.worker.isRunning():
            return False
        if any(t.isRunning() for t in getattr(self.window,'_ui_tasks',())):
            return False
        direct=getattr(self._center,'direct_worker',None)
        if direct and direct.isRunning():
            return False
        if self.engine.sessions.count():
            return False
        from autojob.live import active
        if active():
            return False
        return not any(getattr(widget,key,None) and getattr(widget,key).isRunning()
                       for widget in self.original_widgets for key in ('worker','offer'))

    def update_people_controls(self):
        enabled=self.can_change_person()
        self.data_view.person_selector.setEnabled(enabled)
        self.data_view.new_person_button.setEnabled(enabled)
        self.data_view.rename_person_button.setEnabled(enabled)

    @property
    def center(self):
        if self._center is None:
            self._center=SimpleInterventions(self)
            self._center.setParent(self.window)
            self._center.hide()
            self._center.tray.hide()
        return self._center

    @property
    def post_tabs(self):
        if not hasattr(self,'_legacy_post_tabs'):
            self._legacy_post_tabs=QTabWidget(self.window)
            self._legacy_post_tabs.addTab(self.center,'Centro de intervenciones')
            self._legacy_post_tabs.hide()
        return self._legacy_post_tabs

    @property
    def identity_widget(self):
        if self._identity_widget is None:
            from autojob.ui.identity_widget import IdentityWidget
            self._identity_widget=IdentityWidget(self.settings)
            self._identity_widget.setParent(self.window)
            self._identity_widget.hide()
        return self._identity_widget

    def refresh(self):
        self.request_refresh()

    def request_refresh(self,include_posts=False):
        if getattr(self,'close_requested',False):
            return
        if self.refresh_task is not None:
            self.refresh_pending=True
            return
        def read():
            if not self._recovered:
                self.engine.store.recover()
                sender=SubmissionStore(self.settings.data_path)
                sender.recover()
                execution.recover(sender)
                if self.extension_fill.paired:
                    try:self.extension_fill.start()
                    except OSError:pass
                self._recovered=True
            library=self.engine.compatibility.library
            resumes=library.list()
            return dict(resumes=resumes,rows=self.posts.read_rows(),
                        valid=any(self.engine.compatibility.available(r['id']) for r in resumes),
                        found=self.engine.jobs.count(),sent=self.engine.store.confirmed())
        task=submit(self.window,read,self.apply_snapshot,self.home.status.setText)
        self.refresh_task=task
        def finished():
            self.refresh_task=None
            self.update_people_controls()
            if self.refresh_pending:
                self.refresh_pending=False
                self.request_refresh()
        task.completed.connect(finished)

    def apply_snapshot(self,data):
        self.data_view.render(data['resumes'])
        self.posts.render_manual(data['rows'])
        if self._show_posts:
            self._show_posts=False
            self.main.setCurrentIndex(2)
        self.home.cards['found'].setText('Vacantes encontradas\n'+str(data['found']))
        self.home.cards['compatible'].setText('Ofertas en POSTULACIONES\n'+str(len(data['rows'])))
        self.home.cards['sent'].setText('Enviadas confirmadas\n'+str(data['sent']))
        self.home.cards['interventions'].setText('Postulación manual\nTú completas las solicitudes')
        self.home.search_target.setEnabled(not self.busy())
        self.home.start.setEnabled(data['valid'] and not self.busy())
        self.home.pause.setVisible(self.busy() or self.feed_timer.isActive())
        self.home.attach.setEnabled(not self.busy())
    def options_snapshot(self,target=None):
        from autojob.search.jobs import ENDPOINTS
        if target is None:target=self.home.search_target.value()
        saved=self.engine.store.config().get('search')
        extra=self.engine.compatibility.profile.load()['values']
        profile_terms=[x for key in ('positions','skills') for x in (extra.get(key) or []) if isinstance(x,str) and 3<=len(x)<=70]
        broad=profile_terms+['Night shift customer support','Overnight support','Nocturno','Gasolinera','Cajero','Dependiente de tienda','AMPM','Developer','Python','Support','Customer Service','Help Desk','Service Desk','QA','Electronics','Intern','Virtual Assistant','Administrative Assistant','Bilingual Support','Call Center','Customer Experience','Reservations Agent','Hospitality Support','Back Office','Data Entry']
        if saved and saved.get('queries') and saved.get('sources'):return dict(saved,queries=list(dict.fromkeys(saved['queries']+broad)),sources=[s for s in dict.fromkeys(saved['sources']+list(ENDPOINTS)) if s in ENDPOINTS],limit=None,hours=0,target=target)
        positions=list(extra.get('positions') or [])
        for r in self.engine.compatibility.library.list():positions.extend(self.engine.compatibility.library.get(r['id'])['fields'].get('positions') or [])
        queries=list(dict.fromkeys([p.strip() for p in positions if isinstance(p,str) and 3<=len(p.strip())<=80]+['Junior Python Developer','IT Support','Technical Support','Customer Service','Customer Support','Electronics Technician']))[:16]
        return dict(queries=list(dict.fromkeys(queries+broad)),sources=list(ENDPOINTS),limit=None,hours=0,target=target)
    def start(self,*args,ids=None,user_initiated=False):
        if self.busy() or not user_initiated:return
        if not self.home.start.isEnabled():self.home.status.setText('Adjunta al menos un CV para orientar la búsqueda.');return
        self.advance_on_discard=False;self.delivery_authorization=None;self.feed_timer.stop()
        target=self.home.search_target.value()
        self.home.status.setText(f'Preparando búsqueda de {target} vacantes nuevas…')
        self.worker=ControlWorker(self.engine,lambda:self.options_snapshot(target));self.worker.progress.connect(self.home.status.setText);self.worker.done.connect(self.finished,Qt.ConnectionType.QueuedConnection);self.home.start.setEnabled(False);self.home.search_target.setEnabled(False);self.home.attach.setEnabled(False);self.home.pause.show();self.main.setCurrentIndex(0);self.worker.start();self.update_people_controls()
    def finished(self,result):
        self.home.status.setText(result.get('reason') or 'No se pudo terminar la búsqueda. Los resultados anteriores se conservan.');self.home.pause.hide()
        if getattr(self,'close_requested',False):
            QTimer.singleShot(0,self.window.close)
        elif result.get('state')!='ERROR':
            self.show_links(result)
        else:
            self.request_refresh()
    def extension_setup(self):
        import os
        try:self.extension_fill.start()
        except OSError:self.home.status.setText('El puente local está ocupado. Cierra otras instancias de Job Hunting y vuelve a intentarlo.');return
        d=QDialog(self.window);d.setWindowTitle('Vincular extensión con tu Brave principal');d.resize(680,420);layout=QVBoxLayout(d)
        text=QLabel('Instala una sola vez la extensión local en tu Brave principal:\n1. Abre brave://extensions y activa Modo de desarrollador.\n2. Pulsa Cargar extensión sin empaquetar y elige la carpeta brave-extension del proyecto.\n3. Abre la extensión Job Hunting y pega el código de abajo; pulsa VINCULAR.\n4. Vuelve a pulsar RELLENAR sobre la oferta que quieras completar.\n\nBrave solicita permiso de lectura y modificación de páginas HTTPS. La extensión solo actúa sobre la candidatura seleccionada en Job Hunting, sin enviar solicitudes.');text.setWordWrap(True);layout.addWidget(text)
        code=QLineEdit(self.extension_fill.token);code.setReadOnly(True);code.setEchoMode(QLineEdit.EchoMode.Password);layout.addWidget(code)
        copy=QPushButton('COPIAR CÓDIGO DE VINCULACIÓN');copy.clicked.connect(lambda:__import__('PySide6.QtWidgets',fromlist=['QApplication']).QApplication.clipboard().setText(self.extension_fill.token));layout.addWidget(copy)
        folder=QPushButton('ABRIR CARPETA DE LA EXTENSIÓN');folder.clicked.connect(lambda:os.startfile(str(self.settings.root/'brave-extension')));layout.addWidget(folder)
        self._dialogs.append(d);d.show()
    def ensure_visual_fill(self):
        if not hasattr(self,'visual_fill'):
            from autojob.ui.visual_fill import VisualFill
            self.visual_fill=VisualFill(self.extension_fill,self.window)
            self.visual_fill.status.connect(self.fill_status)

    def fill_selected(self,row):
        if not row or self._fill_request:return
        bridge=self.extension_fill
        self.ensure_visual_fill()
        self._fill_request=True
        self.posts.selection()
        self.update_people_controls()
        self.fill_status('Preparando el autorrelleno para tu Brave principal…')
        def enqueue():
            bridge.start()
            task_id=bridge.enqueue(row)
            if not self.manual_browser.launch(row['url'],announce=False):
                bridge.abort(task_id)
                raise ValueError('No se pudo abrir Brave. Revisa su ruta en la configuración.')
            if bridge.paired and bridge.fast_wake:
                from autojob.extension_fill import WAKE_PATH
                self.manual_browser.launch(f'http://127.0.0.1:{bridge.server.server_port}{WAKE_PATH}',announce=False)
            return dict(id=task_id,paired=bridge.paired,fast=bridge.fast_wake)
        def finished(result):
            self._fill_request=False
            self.posts.selection()
            self.update_people_controls()
            if not result['paired']:
                self.fill_status('Oferta abierta en tu Brave personal. Vincula la extensión para completar los datos en esa pestaña.')
                self.extension_setup()
            else:
                self.fill_status('Oferta abierta en tu Brave personal. Esperando a que la extensión analice y rellene los campos. Si no empieza, recárgala en brave://extensions.')
        def failed(message):
            self._fill_request=False
            self.posts.selection()
            self.update_people_controls()
            self.fill_status(message)
        submit(self.window,enqueue,finished,failed)

    def mark_completed(self):
        row=self.posts.selected()
        if not row:return
        from autojob.completed import CompletedApplications
        try:CompletedApplications(self.settings.data_path).mark(row)
        except (ValueError,OSError) as exc:self.fill_status(str(exc));return
        for task_id in self.extension_fill.finish_manual(row['job']['id']):
            if task_id in self._fill_notices:self._fill_notices[task_id]['dialog'].close()
        self.posts.refresh_manual();self.request_refresh(True)
        self.fill_status('Guardada en MIS DATOS → POSTULACIONES HECHAS. Es una marca manual; no modifica los comprobantes de envío.')
    def show_completed(self):
        from autojob.completed import CompletedApplications
        dialog=QDialog(self.window);dialog.setWindowTitle('Postulaciones hechas · '+self.window.person['alias']);dialog.resize(1000,520);layout=QVBoxLayout(dialog)
        label=QLabel('Marcadas como hechas por ti. Se conservan los datos de la oferta y la fecha; este registro no es una confirmación del portal.');label.setWordWrap(True);layout.addWidget(label)
        rows=CompletedApplications(self.settings.data_path).rows();table=QTableWidget(len(rows),4);table.setHorizontalHeaderLabels(['Empresa','Puesto','Fecha marcada como hecha','Enlace']);table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for n,row in enumerate(rows):
            for c,value in enumerate([row['job']['company'],row['job']['title'],row['completed_at'],row['url']]):table.setItem(n,c,QTableWidgetItem(str(value)))
        table.horizontalHeader().setStretchLastSection(True);table.setColumnWidth(1,300);layout.addWidget(table)
        button=QPushButton('ABRIR EN BRAVE');layout.addWidget(button)
        def open_row(*args):
            n=table.currentRow()
            if 0<=n<len(rows):self.manual_browser.open(rows[n]['url'])
        button.clicked.connect(open_row);table.doubleClicked.connect(open_row)
        table.itemSelectionChanged.connect(lambda:button.setEnabled(table.currentRow()>=0));button.setEnabled(False)
        close=QPushButton('CERRAR');close.clicked.connect(dialog.close);layout.addWidget(close)
        self._dialogs.append(dialog);dialog.show()

    def configure_notice_video(self):
        from autojob.notice_media import NoticeMedia
        from PySide6.QtWidgets import QCheckBox
        store=NoticeMedia(self.window.installation_settings.data_path);settings=store.load()
        dialog=QDialog(self.window);dialog.setWindowTitle('Video de los avisos');dialog.resize(620,220);layout=QVBoxLayout(dialog)
        enabled=QCheckBox('Mostrar video de fondo en los avisos');enabled.setChecked(settings['enabled']);layout.addWidget(enabled)
        sound=QCheckBox('Reproducir sonido del video');sound.setChecked(settings['sound']);layout.addWidget(sound)
        url=QLineEdit(settings['url']);url.setPlaceholderText('https://www.youtube.com/watch?v=...');layout.addWidget(url)
        message=QLabel('El video requiere Internet y que YouTube permita insertarlo. Puedes desactivarlo sin cambiar el aviso.');message.setWordWrap(True);layout.addWidget(message)
        save=QPushButton('GUARDAR');layout.addWidget(save)
        def apply():
            try:store.save(url.text(),enabled.isChecked(),sound.isChecked())
            except ValueError as exc:message.setText(str(exc));return
            for item in self._fill_notices.values():item['dialog'].close()
            dialog.accept()
        save.clicked.connect(apply);self._dialogs.append(dialog);dialog.show()

    def show_fill_notice(self,notice):
        task_id=notice['id']
        pending=notice['pending']
        previous=self._fill_notices.get(task_id)
        if not pending:
            if previous:previous['dialog'].close()
            return
        if previous:
            previous['label'].setText(notice['message'])
            if set(pending)-set(previous['pending']):
                previous['dialog'].show()
            previous['pending']=pending
            return
        from autojob.notice_media import NoticeMedia
        from autojob.ui.notice_dialog import NoticeDialog
        dialog=NoticeDialog(self.window,NoticeMedia(self.window.installation_settings.data_path),self.extension_fill)
        dialog.setWindowTitle('Completar pasos pendientes — Job Hunting')
        dialog.setModal(False)
        dialog.resize(620,330)
        layout=dialog.content
        heading=QLabel(self.window.person['alias']+' · '+notice['job']['company']+' · '+notice['job']['title'])
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        label=QLabel(notice['message'])
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(label)
        row=QHBoxLayout()
        open_button=QPushButton('CONTINUAR EN BRAVE')
        close_button=QPushButton('CERRAR AVISO')
        row.addWidget(open_button);row.addWidget(close_button)
        layout.addLayout(row)
        def check():
            try:
                self.extension_fill.retry(task_id)
                from autojob.extension_fill import WAKE_PATH
                from threading import Thread
                if self.extension_fill.fast_wake:
                    url=f'http://127.0.0.1:{self.extension_fill.server.server_port}{WAKE_PATH}'
                    Thread(target=self.manual_browser.launch,args=(url,False),daemon=True).start()
                self.fill_status('Comprobando el formulario que permanece en Brave…')
                dialog.close()
            except (ValueError,OSError) as exc:
                label.setText(str(exc))
        open_button.clicked.connect(check)
        close_button.clicked.connect(dialog.close)
        self._fill_notices[task_id]=dict(dialog=dialog,label=label,pending=pending)
        self._dialogs.append(dialog)
        dialog.show()

    def fill_status(self,message):
        self.home.status.setText(message)
        self.posts.message.setText(message)
    def show_links(self,result=None,review_only=False):
        # Una sola lista cotidiana para todas las ofertas encontradas.
        self._show_posts=True;self.request_refresh(True)
    def pause(self):
        self.advance_on_discard=False;self.continue_after_discard=None
        if hasattr(self,'feed_timer'):self.feed_timer.stop()
        if hasattr(self.engine,'sessions'):self.engine.sessions.cancel_all()
        if self.busy():super().pause()
        elif self.delivery_authorization:
            execution.state(SubmissionStore(self.settings.data_path),self.delivery_authorization,'PAUSADO');self.home.status.setText('Pausado. Pulsa INICIAR para continuar.');self.home.pause.hide()
    def import_cvs(self):
        files,_=QFileDialog.getOpenFileNames(self.window,'Adjuntar currículums','','Currículums (*.pdf *.docx)')
        if not files:return
        self.home.status.setText('Importando y analizando CV…');path=self.settings.data_path
        def work():
            from autojob.resumes.service import ResumeLibrary
            from autojob.resumes.models import DuplicateResume,ResumeError
            library=ResumeLibrary(path);messages=[]
            for file in files:
                try:library.import_document(Path(file));messages.append(Path(file).name+': importado')
                except DuplicateResume:messages.append(Path(file).name+': ya importado')
                except ResumeError as exc:messages.append(Path(file).name+': '+str(exc))
            return '\n'.join(messages)
        submit(self.window,work,lambda result:(self.home.status.setText(result),self.request_refresh()),self.home.status.setText)
    def dialog_widget(self,title,widget):
        d=QDialog(self.window);d.setWindowTitle('Job Hunting · '+title);d.resize(1000,780);box=QVBoxLayout(d);box.addWidget(widget);widget.show();self._dialogs.append(d);d.finished.connect(lambda _:self.request_refresh());d.show();return d
    def view_sent(self,row):
        from hashlib import sha256
        url=(row['attempt'].get('evidence') or {}).get('url') or row['job'].get('application_url') or row['job']['url'];mode=row['attempt'].get('mode','real');id=row['job'].get('id') or sha256(url.encode()).hexdigest()
        from autojob.application_status import review_reason
        previous=row['attempt'].get('state')
        evaluated=dict(row,evaluation=row.get('evaluation') or self.engine.compatibility.latest().get(id) or {})
        notice='Existe un intento anterior en estado '+previous+'. Se conserva su resultado y no se vuelve a enviar.' if previous in {'ENVIANDO','ENVIADA CONFIRMADA','ENVÍO NO VERIFICADO','RECHAZADA'} else review_reason(evaluated,row.get('notice',''))
        if row.get('notice') and not previous:notice=row['notice']+' '+notice
        self.center.feedback('ABRIENDO SOLO PARA CONSULTA\n'+notice+'\nTodavía no se ha preparado un formulario en esta ventana.')
        self.engine.sessions.launch(id,None,human=True,readonly=True,url=url,mode=mode,notice=notice)
    def session_tick(self):
        if getattr(self,'manual_mode',False):
            self.update_people_controls()
            from queue import Empty
            self.extension_fill.expire()
            try:
                while True:
                    message=self.extension_fill.events.get_nowait();self.fill_status(message);self.request_refresh()
            except Empty:pass
            try:
                while True:self.show_fill_notice(self.extension_fill.notices.get_nowait())
            except Empty:pass
            try:
                while True:
                    message=self.manual_browser.events.get_nowait();self.home.status.setText(message);self.posts.message.setText(message)
            except Empty:pass
            if getattr(self,'close_requested',False) and not self.busy():self.window.close()
            return
        updates=self.engine.sessions.tick();selected=self.posts.selected();selected=selected['job']['id'] if selected else None
        for job,message in updates:
            if job==selected or self.main.currentIndex()!=2:self.center.feedback(message)
        id=self.engine.active_job()
        if id!=getattr(self,'_active_display_id',None):
            self._active_display_id=id;self._active_display_job=next((j for j in self.engine.jobs.list() if j['id']==id),None) if id else None
        job=getattr(self,'_active_display_job',None)
        self.home.skip.setEnabled(bool(job) and not getattr(self,'discard_busy',False))
        self.home.skip.setToolTip('Descarta únicamente la candidatura activa y continúa la cola.' if job else 'Se habilita cuando Job Hunting procesa o abre una candidatura.')
        readonly=bool(job and (self.engine.sessions.tasks.get(id) or {}).get('readonly'))
        task=(self.engine.sessions.tasks.get(id) or {})
        label='Solo consulta: ' if readonly else 'Pendiente de ti en Brave: ' if task.get('message','').startswith('NECESITO TU AYUDA') else 'Postulación en curso: ' if task else 'Verificando oportunidad: '
        self.home.active.setText(label+job['company']+' · '+job['title'] if job else 'No hay una candidatura activa.')
        pending=getattr(self,'continue_after_discard',None)
        if pending and not self.engine.sessions.contains(pending) and not self.busy():
            self.continue_after_discard=None
            if self.delivery_authorization and getattr(self,'advance_on_discard',False) and not getattr(self,'close_requested',False):
                with closing(SubmissionStore(self.settings.data_path).db.connect()) as db:
                    maximum=db.execute('SELECT target FROM autonomous_executions WHERE authorization_id=?',(self.delivery_authorization,)).fetchone()
                    used=db.execute("SELECT COUNT(*) FROM submission_attempts WHERE authorization_id=? AND state IN ('ENVIANDO','ENVIADA CONFIRMADA','ENVÍO NO VERIFICADO')",(self.delivery_authorization,)).fetchone()[0]
                if maximum and used>=maximum['target']:
                    self.center.feedback('Objetivo de la ejecución alcanzado. El historial y las tareas restantes se conservan.');return
                from autojob.forms.submissions import eligible_row
                ids=[r['job']['id'] for r in self.engine.compatibility.rows() if eligible_row(r) and not self.engine.store.is_excluded(r['job']) and not SubmissionStore(self.settings.data_path).duplicate(r['job']) and not self.engine.sessions.contains(r['job']['id'])]
                self.start(ids=ids or None,user_initiated=False)
        if getattr(self,'browser_deferred_ids',[]) and not self.busy() and self.engine.sessions.preparing_count()<self.engine.sessions.limit and getattr(self,'advance_on_discard',False) and not getattr(self,'close_requested',False):
            ids=self.browser_deferred_ids;self.browser_deferred_ids=[];self.start(ids=ids,user_initiated=False)
        if getattr(self,'close_requested',False) and not self.engine.sessions.count():self.window.close()

    def skip_current(self):
        id=self.engine.active_job()
        job=next((j for j in self.engine.jobs.list() if j['id']==id),None)
        if job:self.discard_job(job)
        else:self.home.skip.setEnabled(False);self.home.active.setText('No hay una candidatura activa para saltar.')

    def discard_job(self,job,hide=False):
        if getattr(self,'discard_busy',False):return
        self.discard_busy=True;self.home.skip.setEnabled(False);self.posts.remove_button.setEnabled(False)
        self.center.feedback('Deteniendo '+job['company']+' · '+job['title']+' de forma segura…')
        def done(result):
            self.discard_busy=False
            other_preparations=any(t['thread'].is_alive() and not t.get('discarded') and not t.get('readonly') for t in self.engine.sessions.tasks.values())
            self.continue_after_discard=None if self.busy() or other_preparations else job['id']
            if self.continue_after_discard:self.feed_timer.stop()
            message='Ocultada de tu lista; se conserva el historial.' if hide else 'DESCARTADA POR EL USUARIO. Continuando con otra candidatura…'
            if result['previous_submission']=='ENVIANDO':message+=' Se está comprobando el envío en curso; no se cancelará su evidencia ni se repetirá.'
            self.center.feedback(message);self.request_refresh()
            popup=self.center.popup
            if popup and popup.isVisible():popup.close()
        def failed(message):self.discard_busy=False;self.center.feedback(message);self.posts.selection()
        submit(self.window,lambda:self.engine.discard(job['id'],hide),done,failed)
    def allow_close(self):
        from autojob.live import cancel_all,active
        cancel_all()
        self.engine.sessions.cancel_all()
        direct=getattr(self._center,'direct_worker',None)
        if direct and direct.isRunning():
            direct.cancelled.set()
        if self.busy():
            self.worker.stopped.set()
        if active() or self.engine.sessions.count() or self.busy() or (direct and direct.isRunning()) or any(
            t.isRunning() for t in getattr(self.window,'_ui_tasks',())
        ):
            self.close_requested=True
            self.timer.stop()
            self.home.status.setText('Cerrando las operaciones en curso y conservando los datos…')
            return False
        return True

    def finish_close(self):
        if hasattr(self,'visual_fill'):self.visual_fill.close()
        self.close_requested=True
        self.timer.stop()
        self.session_timer.stop()
        self.feed_timer.stop()
        self.manual_browser.stop.set()
        if self._center:
            self._center.tray.hide()
        self.extension_fill.close()
    def choose_localities(self):
        from autojob.search.onsite import OnsitePreferences,LOCALITIES
        store=OnsitePreferences(self.settings.data_path)
        saved=store.load()
        dialog=QDialog(self.window)
        dialog.setWindowTitle('Elegir localidad para puestos presenciales')
        dialog.resize(560,500)
        layout=QVBoxLayout(dialog)
        note=QLabel('Elige las ciudades o cantones de Costa Rica donde aceptarías trabajo presencial. Cartago se refiere al cantón, no a toda la provincia. Los remotos pueden ser de empresas de cualquier país que admitan trabajar desde Costa Rica.')
        note.setWordWrap(True)
        layout.addWidget(note)
        choices={}
        for place in LOCALITIES:
            box=QCheckBox(place)
            box.setChecked(place in saved['localities'])
            layout.addWidget(box)
            choices[place]=box
        layout.addWidget(QLabel('Otras localidades de Costa Rica, separadas por coma'))
        extra=QLineEdit(', '.join(p for p in saved['localities'] if p not in LOCALITIES))
        layout.addWidget(extra)
        info=QLabel('Se incluyen gasolineras, tiendas de conveniencia, recepción y atención al cliente. Se excluye comida rápida. Cada oferta indicará si la noche está publicada o debe confirmarse.')
        info.setWordWrap(True)
        layout.addWidget(info)
        message=QLabel()
        message.setWordWrap(True)
        layout.addWidget(message)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)
        buttons.rejected.connect(dialog.reject)
        def save():
            try:
                places=[p for p,b in choices.items() if b.isChecked()]
                places.extend(p.strip() for p in extra.text().split(',') if p.strip())
                store.save(places,saved['night_search'])
            except ValueError as exc:
                message.setText(str(exc))
                return
            self.data_view.update_localities()
            self.home.status.setText('Localidades presenciales guardadas. Se usarán en la próxima búsqueda.')
            dialog.accept()
        buttons.accepted.connect(save)
        self._dialogs.append(dialog)
        dialog.show()
        return dialog

    def additional(self):
        tabs=QTabWidget()
        for widget,title in [(self.window.profile_widget,'Perfil y preferencias'),(self.window.application_data_widget,'Disponibilidad y equipo'),(Questions(self.settings.data_path),'Preguntas personalizadas'),(self.window.accounts_widget,'Cuentas'),(self.identity_widget,'Identificación protegida')]:widget.show();tabs.addTab(widget,title)
        target=QSpinBox();target.setRange(1,10000);target.setValue(self.engine.store.config()['target']);target.valueChanged.connect(lambda v:self.engine.store.configure(target=v));target_page=QWidget();form=QFormLayout(target_page);form.addRow('Objetivo de postulaciones por ejecución',target);tabs.addTab(target_page,'Objetivo');self.dialog_widget('INFORMACIÓN ADICIONAL',tabs)
    def choose_panel_style(self):
        from autojob.ui.appearance import MODES
        keys=list(MODES)
        labels=list(MODES.values())
        selected,accepted=QInputDialog.getItem(
            self.window,'Estilo de paneles','Aspecto de tablas y paneles',labels,
            keys.index(self.window.panel_mode),False)
        if not accepted:return
        try:
            self.window.set_panel_mode(keys[labels.index(selected)])
            self.panel_style_status.setText('Paneles: '+selected)
        except (OSError,ValueError):
            self.panel_style_status.setText('No se pudo guardar el estilo de paneles.')

    def change_background(self,reset=False):
        titles=[self.main.tabText(i) for i in range(self.main.count())]
        title,accepted=QInputDialog.getItem(self.window,'Elegir pestaña','¿A qué pestaña quieres cambiarle el fondo?',titles,self.main.currentIndex(),False)
        if not accepted:return
        index=titles.index(title)
        try:
            if reset:
                self.background_images.reset(index)
                message='Tema oscuro restablecido en '+title+'.'
            else:
                image,_=QFileDialog.getOpenFileName(self.window,'Elegir imagen de fondo','',self.background_images.file_filter())
                if not image:return
                self.background_images.save(index,image)
                message='Fondo de '+title+' guardado en este equipo.'
            self.window.section_backgrounds=self.background_images.load((None,) * 4)
            self.window.set_section_background(self.main.currentIndex())
            self.background_status.setText(message)
        except (OSError,ValueError):
            self.background_status.setText('No se pudo cambiar el fondo. El fondo anterior se conserva.')
    def save_search(self):
        self.engine.store.configure(search=Shell.options_snapshot(self));self.home.status.setText('Preferencias de búsqueda guardadas.')
    def open(self,widget):self.dialog_widget('REVISAR Y CORREGIR',widget)
    def open_advanced(self,widget):self.open(widget)
    def authorize(self):self.home.status.setText('Pulsa INICIAR Job Hunting para comenzar.')
    def test_mode(self):self.pause()

