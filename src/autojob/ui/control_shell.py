from pathlib import Path
from threading import Event
from contextlib import closing
import json
from PySide6.QtCore import Qt,QTimer,QThread,Signal,QObject,Slot
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QFormLayout,QLabel,QPushButton,QSpinBox,QCheckBox,QTabWidget,QStackedWidget,QComboBox,QScrollArea,QTableWidget,QTableWidgetItem,QPlainTextEdit,QFrame,QDialog,QDialogButtonBox,QSystemTrayIcon,QStyle,QFileDialog
from autojob.control import Coordinator,ControlStore
from autojob.interventions import InterventionService
from autojob.auth.verifications import bus,VerificationStore

def from_auto_sender_recover(settings):
    from autojob.forms.submissions import SubmissionStore
    SubmissionStore(settings.data_path).recover()

class RoutedTabs(QTabWidget):
    router=None
    def setCurrentWidget(self,widget):
        if self.router and widget in self.router.original_widgets:self.router.open(widget)
        else:super().setCurrentWidget(widget)

class Host(QScrollArea):
    def __init__(self):
        super().__init__();self.setWidgetResizable(True);body=QWidget();self.body=QVBoxLayout(body);self.setWidget(body);self.setMinimumSize(200,130);self.setFrameShape(QFrame.Shape.NoFrame)
    def mount(self,widget):
        self.body.addWidget(widget);widget.show();self.body.activate();widget.updateGeometry()

class ControlWorker(QThread):
    progress=Signal(str);done=Signal(object)
    def __init__(self,engine,options,ids=None):super().__init__();self.engine=engine;self.options=options;self.ids=ids;self.paused=Event();self.stopped=Event()
    def run(self):
        try:self.done.emit(self.engine.run(self.options() if callable(self.options) else self.options,self.paused.is_set,self.stopped.is_set,self.progress.emit,self.ids))
        except Exception as e:self.done.emit(dict(state='ERROR',error=type(e).__name__))

class Home(QWidget):
    def __init__(self,shell):
        super().__init__();self.shell=shell;layout=QVBoxLayout(self);title=QLabel('Job Hunting');title.setStyleSheet('font-size:32px;font-weight:700');layout.addWidget(title);layout.addWidget(QLabel('Tus currículums y preferencias. Un único punto para iniciar el trabajo.'))
        self.mode=mode=QLabel('MODO PREPARACIÓN — ENVÍOS REALES DESACTIVADOS');mode.setStyleSheet('color:#f8d486;font-weight:700;padding:10px;background:rgba(40,51,72,205);border-radius:6px');mode.setWordWrap(True);layout.addWidget(mode)
        self.authorization_status=QLabel('Lote no autorizado en esta sesión · Los envíos reales están desactivados.');self.authorization_status.setWordWrap(True);self.authorization_status.setObjectName('batch_authorization_status');layout.addWidget(self.authorization_status)
        self.goal=QLabel();self.goal.setStyleSheet('font-size:27px;font-weight:700;padding:12px 0');layout.addWidget(self.goal);row=QHBoxLayout();row.addWidget(QLabel('Objetivo de postulaciones confirmadas'));self.target=QSpinBox();self.target.setRange(1,10000);self.target.setValue(shell.engine.store.config()['target']);self.target.valueChanged.connect(self.change_goal);row.addWidget(self.target);row.addStretch();layout.addLayout(row)
        row=QHBoxLayout();self.start=QPushButton('INICIAR Job Hunting');self.start.setStyleSheet('background:rgba(37,99,180,220);font-size:18px;font-weight:700;padding:17px');self.pause=QPushButton('PAUSAR');self.stop=QPushButton('DETENER')
        for b,fn in [(self.start,shell.start),(self.pause,shell.pause),(self.stop,shell.stop)]:b.clicked.connect(fn);row.addWidget(b)
        layout.addLayout(row);mode_row=QHBoxLayout();self.authorize=QPushButton('MODO AUTOMÁTICO · revisar y autorizar');self.authorize.clicked.connect(shell.authorize);mode_row.addWidget(self.authorize);test=QPushButton('MODO PRUEBA · revocar envíos');test.clicked.connect(shell.test_mode);mode_row.addWidget(test);layout.addLayout(mode_row);self.status=QLabel('Listo para iniciar.');self.status.setWordWrap(True);layout.addWidget(self.status);self.browser_state=QLabel('Brave: disponible · perfil independiente');layout.addWidget(self.browser_state);grid=QGridLayout();self.cards={}
        for n,(key,label) in enumerate([('found','Vacantes encontradas'),('compatible','Compatibles'),('prepared','Preparadas'),('sent','Enviadas confirmadas'),('pending','Pendientes'),('errors','Errores'),('interventions','Intervenciones requeridas')]):
            frame=QFrame();frame.setStyleSheet('QFrame{background:rgba(29,41,57,195);border-radius:8px}');box=QVBoxLayout(frame);box.addWidget(QLabel(label));value=QLabel('0');value.setStyleSheet('font-size:26px;font-weight:700');box.addWidget(value);self.cards[key]=value;grid.addWidget(frame,n//3,n%3)
        layout.addLayout(grid);row=QHBoxLayout()
        for text,fn in [('MIS DATOS',lambda:shell.main.setCurrentIndex(1)),('VER POSTULACIONES',lambda:shell.main.setCurrentIndex(2)),('RESOLVER PENDIENTES',shell.center.resolve_all)]:b=QPushButton(text);b.clicked.connect(fn);row.addWidget(b)
        layout.addLayout(row);self.note=QLabel('Las preparadas no son enviadas. Brave utiliza un perfil independiente; las intervenciones se conservan para reanudarlas.');self.note.setWordWrap(True);layout.addWidget(self.note);layout.addStretch()
    def change_goal(self,value):self.shell.engine.store.configure(target=value);self.shell.refresh()
    def refresh(self):
        counts=self.shell.engine.store.counts(self.shell.engine.queue)
        for key,label in self.cards.items():label.setText(str(counts[key]))
        self.goal.setText(f"POSTULACIONES CONFIRMADAS: {counts['sent']}/{counts['target']}")
        from autojob.browser.lock import ProfileLock
        lock=ProfileLock(self.shell.settings.data_path/'browser.lock')
        try:lock.acquire();self.browser_state.setText('Brave: disponible · perfil independiente')
        except Exception:self.browser_state.setText('Brave: sesión ocupada o reservada para intervención; otras tareas locales pueden continuar')
        finally:lock.release()
        self.update_authorization();run=self.shell.engine.store.latest();self.status.setText((run['state']+' · '+run['operation']) if run else 'Listo para iniciar. No se ha ejecutado el coordinador.');running=bool(self.shell.worker and self.shell.worker.isRunning());self.start.setEnabled(not running);self.pause.setEnabled(running);self.stop.setEnabled(running)
    def update_authorization(self):
        token=self.shell.delivery_authorization
        if not token:
            self.authorization_status.setText('Lote no autorizado en esta sesión · Los envíos reales están desactivados.');return False
        try:
            from contextlib import closing
            from autojob.forms.submissions import SubmissionStore,UNSAFE
            store=SubmissionStore(self.shell.settings.data_path)
            with closing(store.db.connect()) as db:row=db.execute('SELECT expires_at,revoked,max_count,profile_hash,scope FROM submission_authorizations WHERE id=?',(token,)).fetchone()
            if not row or row['revoked'] or row['expires_at']<__import__('autojob.storage.database',fromlist=['utc_now']).utc_now() or row['profile_hash']!=store.prep.inputs_hash():
                self.mode.setText('MODO PREPARACIÓN — ENVÍOS REALES DESACTIVADOS');self.authorization_status.setText('Lote inactivo: no existe, venció, fue revocado o los datos cambiaron. Revisa MODO AUTOMÁTICO para activar otro.');return False
            with closing(store.db.connect()) as db:used=db.execute('SELECT COUNT(*) FROM submission_attempts WHERE authorization_id=? AND state IN ('+','.join('?' for _ in UNSAFE)+')',(token,*UNSAFE)).fetchone()[0]
            from datetime import datetime,timezone
            remaining=max(0,int((datetime.fromisoformat(row['expires_at'])-datetime.now(timezone.utc)).total_seconds()//60))
            scope=json.loads(row['scope']);batch=scope.get('_batch',{});ids=batch.get('cv_ids') or list(dict.fromkeys(rule['cv_id'] for rule in scope.values() if isinstance(rule,dict) and rule.get('cv_id')));titles=[store.prep.compatibility.library.get(id)['title'] for id in ids]
            self.authorization_status.setText(f'Lote AUTORIZADO en esta sesión · Máximo {row["max_count"]} transmisiones · {max(0,row["max_count"]-used)} restantes · Vence en {remaining} min. CV autorizados: '+', '.join(titles)+'. Solo se procesan vacantes dentro del alcance revisado.')
            if used>=row['max_count']:
                self.mode.setText('MODO PREPARACIÓN — ENVÍOS REALES DESACTIVADOS');self.authorization_status.setText('Lote agotado · '+self.authorization_status.text());return False
            self.mode.setText('MODO AUTOMÁTICO ACTIVADO · Alcance revisado · Pulsa INICIAR')
            return True
        except Exception:
            self.mode.setText('MODO PREPARACIÓN — ENVÍOS REALES DESACTIVADOS');self.authorization_status.setText('No se pudo verificar el lote; los envíos permanecen bloqueados hasta revisar MODO AUTOMÁTICO.')
            return False

class Applications(QWidget):
    def __init__(self,shell):
        super().__init__();self.shell=shell;layout=QVBoxLayout(self);row=QHBoxLayout();self.filter=QComboBox();self.filter.addItems(['Envío no verificado','Rechazadas','Descartadas','Todas','Encontradas','Recomendadas','En cola','Preparadas','Pendientes','Bloqueadas','Enviadas confirmadas','Omitidas']);self.filter.setCurrentText('Todas');self.filter.currentTextChanged.connect(self.refresh);row.addWidget(self.filter)
        for text,fn in [('Actualizar',lambda:self.shell.request_refresh(True)),('Abrir detalle',self.detail),('Incorporar comprobante',self.receipt),('Continuar preparación',self.resume),('Abrir en Brave',self.open),('Exportar Excel',self.export)]:b=QPushButton(text);b.clicked.connect(fn);row.addWidget(b)
        layout.addLayout(row);self.counter=QLabel();layout.addWidget(self.counter);self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['Empresa','Puesto','Modalidad / ubicación','Compatibilidad','Estado']);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.itemSelectionChanged.connect(self.detail);layout.addWidget(self.table,3);self.details=QPlainTextEdit();self.details.setReadOnly(True);layout.addWidget(self.details,2);self.rows=[]
    def refresh(self,*args,data=None):
        if data is not None:self._snapshot=data
        elif hasattr(self,'_snapshot'):data=self._snapshot
        if data is None:self.shell.request_refresh(True);return
        deliveries=data['deliveries']
        rows=data['rows'];queue=data['queue'];current_hash=data['current_hash'];confirmed_urls=data['confirmed_urls'];omitted=data['omitted'];selected=self.selected();selected=selected['job']['id'] if selected else None;self.rows=[];self.table.blockSignals(True)
        for r in rows:
            q=queue.get(r['job']['id']);e=r['evaluation'] or {};state='OMITIDA' if r['job']['id'] in omitted else q['state'] if q else 'ENCONTRADA';r=dict(r,queue=q,state=state)
            if state=='PREPARADA' and (q['payload'].get('preview') or {}).get('inputs_hash')!=current_hash:state='REQUIERE ACTUALIZACIÓN';r['state']=state
            if r['job']['url'] in confirmed_urls:state='ENVIADA CONFIRMADA';r['state']=state
            delivery=deliveries.get(r['job']['id'])
            if delivery and delivery['state'] in {'ENVIANDO','ENVIADA CONFIRMADA','ENVÍO NO VERIFICADO','RECHAZADA'}:state=delivery['state'];r['state']=state
            f=self.filter.currentText()
            if f=='Rechazadas' and state!='RECHAZADA':continue
            if f=='Envío no verificado' and state!='ENVÍO NO VERIFICADO':continue
            if f=='Descartadas' and state!='OMITIDA':continue
            if f=='Encontradas' and state!='ENCONTRADA':continue
            if f=='Recomendadas' and (r['stale'] or e.get('eligibility')!='COMPATIBLE' or state=='OMITIDA'):continue
            if f=='En cola' and not q:continue
            if f=='Preparadas' and state!='PREPARADA':continue
            if f=='Pendientes' and state not in {'PENDIENTE','POR PREPARAR','REQUIERE REVISIÓN','REQUIERE ACTUALIZACIÓN'}:continue
            if f=='Bloqueadas' and state not in {'BLOQUEADA','ERROR'}:continue
            if f=='Omitidas' and state!='OMITIDA':continue
            if f=='Enviadas confirmadas' and state!='ENVIADA CONFIRMADA':continue
            self.rows.append(r)
        token=(self.filter.currentText(),tuple((r['job']['id'],r['job']['company'],r['job']['title'],r['job'].get('modality'),r['job'].get('location'),(r['evaluation'] or {}).get('score'),r['stale'],r['state']) for r in self.rows))
        if token==getattr(self,'_render_token',None):self.table.blockSignals(False);self.detail();return
        self._render_token=token
        self.table.setRowCount(len(self.rows))
        for n,r in enumerate(self.rows):
            j=r['job'];e=r['evaluation'] or {};values=[j['company'],j['title'],(j.get('modality') or 'Desconocida')+' · '+(j.get('location') or 'Ubicación desconocida'),str(e.get('score','Sin evaluar'))+(' · actualizar' if r['stale'] else ''),r['state']]
            for c,v in enumerate(values):item=QTableWidgetItem(str(v));item.setData(256,j['id']);self.table.setItem(n,c,item)
            if j['id']==selected:self.table.selectRow(n)
        self.table.blockSignals(False)
        for c,w in enumerate([180,300,230,140,200]):self.table.setColumnWidth(c,w)
        self.counter.setText(str(len(self.rows))+' vacantes · La cola de preparación no acredita envíos.');self.detail()
    def selected(self):
        items=self.table.selectedItems();return next((r for r in self.rows if items and r['job']['id']==items[0].data(256)),None)
    def detail(self):
        r=self.selected()
        if not r:return
        j=r['job'];e=r['evaluation'] or {};q=r['queue'] or {};p=q.get('payload') or {};cv=e.get('resume_selection') or {};text=f"{j['company']}\n{j['title']}\n\nModalidad: {j.get('modality') or 'Desconocida'}\nUbicación: {j.get('location') or 'Desconocida'}\nSalario publicado: {j.get('salary') or 'No publicado'} {j.get('currency') or ''}\nCompatibilidad: {e.get('score','Sin evaluar')}\nElegibilidad: {e.get('eligibility','Sin evaluar')}\nGeografía: {e.get('geography',j.get('geography','Desconocida'))}\nVigencia: {e.get('availability',j.get('availability','No verificada'))}\nCV: {cv.get('title') or 'Sin selección confirmada'}\nEstado: {r['state']}\nEnlace: {j['url']}\nÚltima acción: {q.get('last_action') or 'Descubrimiento guardado'}\n\nObstáculos:\n"+'\n'.join(b.get('type','Revisión')+' · '+b.get('evidence','') for b in p.get('blocks',[]))+'\n\n'+(j.get('description') or '')
        if self.details.toPlainText()!=text:self.details.setPlainText(text)
    def receipt(self):
        r=self.selected()
        if not r:return
        from autojob.ui.receipt_review import ReceiptReview
        dialog=ReceiptReview(self.shell,r['job']['id']);dialog.exec();self.refresh()
    def resume(self):
        r=self.selected()
        if not r:return
        id=r['job']['id']
        if id in self.shell.engine.store.excluded():self.details.setPlainText('Esta vacante fue omitida. Revisa la decisión antes de reactivarla desde las herramientas avanzadas.');return
        self.shell.engine.queue.add([id]);self.shell.engine.queue.requeue([id]);self.shell.start(ids=[id])
    def open(self):
        r=self.selected()
        if not r:return
        self.shell.window.queue_widget.add_ids([r['job']['id']]);self.shell.window.queue_widget.refresh()
        for n,row in enumerate(self.shell.window.queue_widget.rows):
            if row['job_id']==r['job']['id']:self.shell.window.queue_widget.table.selectRow(n);break
        self.shell.window.queue_widget.open_form()
    def export(self):
        name,_=QFileDialog.getSaveFileName(self,'Exportar vacantes visibles','postulaciones.xlsx','Excel (*.xlsx)')
        if name:
            from autojob.matching.service import export
            export(self.rows,name)

class Interventions(QWidget):
    def __init__(self,shell):
        super().__init__();self.shell=shell;self.service=InterventionService(shell.engine);self.popup=None;self.notified_ids=set();self.notification_cutoff=__import__('autojob.control',fromlist=['now']).now();self.all_mode=False;self.cycle_seen=set();self.resume_ids=set();self.resume_all=False;self.pending_manual=None;layout=QVBoxLayout(self);layout.addWidget(QLabel('Centro de intervenciones · Las tareas pendientes se conservan sin detener la interfaz.'));self.status=QLabel('Solo se reanuda cuando hay una solución verificable.');self.status.setWordWrap(True);layout.addWidget(self.status);self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Empresa / puesto','Problema','Estado','Qué se necesita']);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);layout.addWidget(self.table)
        row=QHBoxLayout()
        for text,fn in [('RESOLVER AHORA',self.resolve),('RESOLVER DESPUÉS',self.later),('OMITIR ESTA POSTULACIÓN',self.omit),('Comprobar solución',self.check),('RESOLVER PENDIENTES',self.resolve_all)]:
            b=QPushButton(text);b.clicked.connect(fn);row.addWidget(b)
            if text=='RESOLVER AHORA':b.setObjectName('resolve_intervention_button');b.setShortcut('Alt+R');b.setToolTip('Resolver la intervención seleccionada (Alt+R)')
        layout.addLayout(row);self.quiet=QCheckBox('Posponer ventanas emergentes durante esta sesión');layout.addWidget(self.quiet);self.rows=[];self.tray=QSystemTrayIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning),self);self.tray.setToolTip('Job Hunting · Centro de intervenciones');self.tray.show();self.tray.messageClicked.connect(self.resolve_all);bus().notice.connect(self.notice,Qt.ConnectionType.QueuedConnection)
    @Slot(str,str,str)
    def notice(self,*args):self.shell.request_refresh()
    def selected(self):
        items=self.table.selectedItems();return next((r for r in self.rows if items and r['id']==items[0].data(256)),None)
    def refresh(self):
        self.shell.engine.store.sync(self.shell.engine.queue);self.rows=[r for r in self.shell.engine.store.interventions() if r['state'] in {'PENDIENTE','POSPUESTA'}];selected=self.selected();selected=selected['id'] if selected else None;self.table.setRowCount(len(self.rows))
        for n,r in enumerate(self.rows):
            from autojob.ui.intervention_feedback import display
            kind,message=display(r)
            for c,v in enumerate([r['company']+' · '+r['title'],kind,r['state'],message]):item=QTableWidgetItem(v);item.setData(256,r['id']);self.table.setItem(n,c,item)
            if r['id']==selected:self.table.selectRow(n)
        for c,w in enumerate([320,220,130,500]):self.table.setColumnWidth(c,w)
        latest=self.shell.engine.store.latest()
        ready=self.service.ready() if latest and latest['state'] not in {'DETENIDO','PAUSADO','ERROR'} else []
        for id in ready:
            from autojob.live import active
            if id and active(id):continue
            if id:self.resume_ids.add(id)
            else:self.resume_all=True
        if ready and self.all_mode:QTimer.singleShot(0,self.next_problem)
        if self.pending_manual and not self.shell.occupied():
            row=self.pending_manual;self.pending_manual=None;self.resolve(row)
        if (self.resume_ids or self.resume_all) and not self.shell.occupied():
            ids=list(self.resume_ids) if not self.resume_all else [];self.resume_ids.clear();self.resume_all=False;self.shell.start(ids=ids)
        config=self.shell.engine.store.config();active=self.shell.occupied()
        if not self.quiet.isChecked():
            row=next((r for r in self.rows if r['state']=='PENDIENTE' and not r['alerted'] and r['id'] not in self.notified_ids and r['created_at']>=self.notification_cutoff),None)
            if row and not (self.popup and self.popup.isVisible()):self.show_problem(row,config)
    def apply_snapshot(self,data):
        selected=self.selected();selected=selected['id'] if selected else None;self.rows=data['interventions'];self.table.setRowCount(len(self.rows))
        for n,r in enumerate(self.rows):
            from autojob.ui.intervention_feedback import display
            kind,message=display(r)
            for c,v in enumerate([r['company']+' · '+r['title'],kind,r['state'],message]):item=QTableWidgetItem(v);item.setData(256,r['id']);self.table.setItem(n,c,item)
            if r['id']==selected:self.table.selectRow(n)
        for c,w in enumerate([320,220,130,500]):self.table.setColumnWidth(c,w)
        ready=data['ready']
        for id in ready:
            from autojob.live import active
            if id and active(id):continue
            if id:self.resume_ids.add(id)
            else:self.resume_all=True
        if ready and self.all_mode:QTimer.singleShot(0,self.next_problem)
        if self.pending_manual and not self.shell.occupied():
            row=self.pending_manual;self.pending_manual=None;self.resolve(row)
        if (self.resume_ids or self.resume_all) and not self.shell.occupied():
            ids=list(self.resume_ids) if not self.resume_all else [];self.resume_ids.clear();self.resume_all=False;self.shell.start(ids=ids)
        config=data['config'];active=self.shell.occupied()
        if not self.quiet.isChecked():
            row=next((r for r in self.rows if r['state']=='PENDIENTE' and not r['alerted'] and r['id'] not in self.notified_ids and r['created_at']>=self.notification_cutoff),None)
            if row and not (self.popup and self.popup.isVisible()):self.show_problem(row,config)
    def show_problem(self,row,config=None):
        config=config or self.shell.engine.store.config()
        self.notified_ids.add(row['id'])
        with closing(self.shell.engine.store.db.connect()) as db,db:db.execute('UPDATE control_interventions SET alerted=1 WHERE id=?',(row['id'],))
        if config['notifications']:self.tray.showMessage('Job Hunting necesita intervención',row['company']+' · '+row['title']+' · '+row['kind'],QSystemTrayIcon.MessageIcon.Warning,10000)
        if not config['popups']:return
        from autojob.ui.intervention_feedback import display,plan,ActionRequired,diagnostic
        if display(row)[0]=='AUTORIZACIÓN CV':
            try:
                decision=plan(self.shell.settings,row,self.shell.delivery_authorization)
                if decision.get('authorization_required'):
                    self.popup=ActionRequired(self,row,decision['message'],decision.get('cv_title'));self.popup.show();self.popup.raise_();self.popup.activateWindow();self.status.setText(decision['message']);return
            except Exception as exc:self.show_error('No se pudo recuperar el permiso del CV; la tarea sigue pendiente.',diagnostic(exc));return
        if row['kind']=='CARTA DE PRESENTACIÓN':
            from autojob.ui.submission_ui import LetterReview
            self.popup=LetterReview(self,row);self.popup.show();self.popup.raise_();self.popup.activateWindow();return
        if row['kind'] in {'INFORMACIÓN FALTANTE','DATO OBLIGATORIO PENDIENTE'}:
            from autojob.ui.submission_ui import MissingInformation
            self.popup=MissingInformation(self,row);self.popup.show();self.popup.raise_();self.popup.activateWindow();return
        dialog=QDialog(self.window());dialog.setWindowTitle('Job Hunting · Intervención necesaria');dialog.setModal(False);dialog.resize(620,300);box=QVBoxLayout(dialog)
        label=QLabel(f"{row['company']} · {row['title']}\n\n{row['kind']}\n{row['message']}\n\nFormulario: {row['url'] or 'Datos de Job Hunting'}\nEstado: {row['state']}");label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True);box.addWidget(label);buttons=QHBoxLayout()
        for text,fn in [('RESOLVER AHORA',lambda:self.resolve(row)),('RESOLVER DESPUÉS',lambda:self.later(row)),('OMITIR ESTA POSTULACIÓN',lambda:self.omit(row))]:b=QPushButton(text);b.clicked.connect(lambda checked=False,fn=fn:(fn(),dialog.close()));buttons.addWidget(b)
        box.addLayout(buttons);self.popup=dialog;dialog.show();dialog.raise_();dialog.activateWindow()
    def show_error(self,message,code='I9I_ACTION'):
        self.status.setText(message+' · '+code);self.shell.home.status.setText(message)
        dialog=QDialog(self.window());dialog.setWindowTitle('Job Hunting · No se pudo resolver');dialog.setModal(False);box=QVBoxLayout(dialog);label=QLabel(message+'\nCódigo: '+code);label.setWordWrap(True);label.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(label);button=QPushButton('CERRAR');button.clicked.connect(dialog.close);box.addWidget(button);self.popup=dialog;dialog.show();dialog.raise_();dialog.activateWindow()
    def resolve(self,row=None):
        try:self.resolve_selected(row)
        except Exception as exc:
            from autojob.ui.intervention_feedback import diagnostic
            self.show_error('No se pudo recuperar la intervención. La tarea se conserva y no se abrirá otra candidatura por error.',diagnostic(exc))
    def resolve_selected(self,row=None):
        row=row if isinstance(row,dict) else self.selected()
        if not row:self.status.setText('Selecciona una intervención de la tabla y pulsa RESOLVER AHORA.');return
        from autojob.live import command,historical
        from autojob.forms.submissions import SubmissionStore
        if not row.get('job_id') and row.get('verification_id'):
            verification=next((v for v in VerificationStore(self.shell.settings.data_path).list() if v['id']==row['verification_id']),None)
            if verification:row=dict(row,job_id=verification['job_id'],url=verification['url'])
        if not row.get('job_id'):self.status.setText('Falta identificar la candidatura; no se abre un formulario sin contexto.');return
        previous=historical(SubmissionStore(self.shell.settings.data_path),row['job_id'])
        if previous=='INFLIGHT':
            # ENVIANDO puede estar esperando CAPTCHA antes de liberar el primer POST.
            # Solo enfocar el propietario actual; jamás reconstruir otro formulario.
            command(row['job_id'],'FOCUS')
            verification=next((v for v in VerificationStore(self.shell.settings.data_path).list() if v['job_id']==row['job_id'] and v['reserved'] and v['kind']=='CAPTCHA PENDIENTE'),None)
            if verification:VerificationStore(self.shell.settings.data_path).update(verification['id'],command='RESOLVER')
            self.status.setText('Intento en curso: se conserva su sesión. No se abre ni se envía otro formulario.');return
        if previous:
            from autojob.ui.receipt_review import ReceiptReview
            self.popup=ReceiptReview(self.shell,row['job_id']);self.popup.setModal(False);self.popup.show();self.status.setText('Resultado final existente: solo revisión de comprobante. No se reabre el formulario.');return
        retained=command(row['job_id'],'FOCUS')
        if retained and row['kind'] not in {'INFORMACIÓN FALTANTE','DATO OBLIGATORIO PENDIENTE'}:self.status.setText('INTERVENCIÓN HUMANA ACTIVA: se conserva la pestaña preparada hasta que termines, pospongas o cierres.');return
        if row.get('id') and not any(k in row['kind'] for k in ['LOGIN','AUTENTICACIÓN','REGISTRO','MFA','CORREO','SMS']) and row['kind'] not in {'CARTA DE PRESENTACIÓN','REVISAR CURRÍCULUMS'}:
            from autojob.ui.intervention_feedback import plan,ActionRequired
            decision=plan(self.shell.settings,row,self.shell.delivery_authorization)
            if decision.get('error'):self.show_error(decision['error'],'I9I_CONTEXT');return
            if decision.get('authorization_required'):
                if isinstance(self.popup,ActionRequired) and self.popup.isVisible() and self.popup.row.get('id')==row.get('id'):
                    self.popup.raise_();self.popup.activateWindow();self.status.setText(decision['message']);return
                self.popup=ActionRequired(self,row,decision['message'],decision.get('cv_title'));self.popup.show();self.status.setText(decision['message']);return
        self.shell.main.setCurrentIndex(2);self.shell.post_tabs.setCurrentWidget(self)
        if row.get('verification_id') and 'CAPTCHA' in row['kind']:
            verification=next((v for v in VerificationStore(self.shell.settings.data_path).list() if v['id']==row['verification_id']),None)
            if verification and verification['reserved']:
                VerificationStore(self.shell.settings.data_path).update(verification['id'],command='RESOLVER');self.status.setText('Resuelve el CAPTCHA en la misma sesión reservada de Brave; el trabajador espera tu intervención.');return
            if self.shell.occupied():self.pending_manual=row;self.status.setText('La intervención se abrirá al liberar el trabajo actual. El perfil único de Brave no permite modificar dos formularios a la vez.');return
            self.open_direct(row)
        elif row['kind']=='CARTA DE PRESENTACIÓN':
            from autojob.ui.submission_ui import LetterReview
            self.popup=LetterReview(self,row);self.popup.show()
        elif row['kind']=='REVISAR CURRÍCULUMS':self.shell.open(self.shell.window.resumes_widget)
        elif row['kind'] in {'INFORMACIÓN FALTANTE','DATO OBLIGATORIO PENDIENTE'}:
            if not retained and not self.shell.occupied():
                with closing(self.shell.engine.store.db.connect()) as db:exists=db.execute('SELECT 1 FROM discovered_jobs WHERE id=?',(row['job_id'],)).fetchone()
                if exists:self.open_direct(row)
            from autojob.ui.submission_ui import MissingInformation
            self.popup=MissingInformation(self,row);self.popup.show()
        else:
            self.open_direct(row)
        self.status.setText('Completa la acción necesaria y usa Comprobar solución. Se revalidarán los datos y el formulario.')
    def open_direct(self,row,readonly=False):
        if self.shell.occupied():self.pending_manual=row;self.status.setText('La etapa se abrirá al liberar Brave; la cola y el bloqueo quedan conservados.');return
        if not row.get('url'):self.status.setText('No existe un enlace verificable para esta intervención.');return
        from autojob.ui.intervention_feedback import InterventionWorker,OperationFeedback
        settings=self.shell.settings;store=self.shell.engine.store;queue=self.shell.engine.queue;authorization=self.shell.delivery_authorization
        def run(progress,cancelled):
            if readonly:
                from autojob.ui.intervention_feedback import open_readonly
                return open_readonly(settings,row,progress,cancelled)
            progress('Recuperando la vacante y los permisos vigentes…')
            if not any(k in row['kind'] for k in ['LOGIN','AUTENTICACIÓN','REGISTRO','MFA','CORREO','SMS']):
                from autojob.ui.intervention_feedback import open_prepared
                return open_prepared(settings,row,authorization,progress,lambda:cancelled() or getattr(self.shell,'close_requested',False))
            from autojob.intervention_context import capture,focus
            from autojob.browser import BraveSession
            from autojob.forms.guard import PreparationGuard
            context=capture(store,row,queue)
            if cancelled():return dict(cancelled=True)
            progress('Abriendo Brave con su perfil independiente…')
            with BraveSession(settings) as browser:
                if any(k in row['kind'] for k in ['LOGIN','AUTENTICACIÓN','REGISTRO','MFA','CORREO','SMS']):
                    from autojob.manual_stage import open_stage
                    return open_stage(browser,settings,row,context,stop=lambda:cancelled() or getattr(self.shell,'close_requested',False))
        self.direct_worker=InterventionWorker(run);self.navigation_job=row['job_id'];self.navigation_row=dict(row);self.shell.window.notifications_widget.worker=self.direct_worker
        self.operation_popup=OperationFeedback(self,row,self.direct_worker);self.popup=self.operation_popup;self.operation_popup.show()
        self.direct_worker.progress.connect(self.navigation_progress,Qt.ConnectionType.QueuedConnection);self.direct_worker.done.connect(self.direct_finished,Qt.ConnectionType.QueuedConnection);self.direct_worker.start()
        self.status.setText('Recuperando el formulario: se reponen los campos conocidos y el CV únicamente con permiso vigente. Se conserva la sesión preparada; los contratos e identidad requieren permisos específicos.')
    @Slot(str)
    def navigation_progress(self,message):
        self.status.setText(message)
        if getattr(self,'operation_popup',None):self.operation_popup.message.setText(message)
    @Slot(object)
    def direct_finished(self,result):
        if getattr(self.shell,'close_requested',False):QTimer.singleShot(0,self.shell.window.close);return
        self.shell.request_refresh()
        if not result.get('ok'):
            message=result.get('error','No se pudo abrir la etapa. La candidatura sigue pendiente.');self.status.setText(message)
            if getattr(self,'operation_popup',None):self.operation_popup.message.setText(message);self.operation_popup.cancel.setText('CERRAR');self.operation_popup.cancel.setEnabled(True);self.operation_popup.cancel.clicked.disconnect();self.operation_popup.cancel.clicked.connect(self.operation_popup.close)
        elif (result.get('result') or {}).get('authorization_required'):
            from autojob.ui.intervention_feedback import ActionRequired
            row=getattr(self,'navigation_row',None)
            if getattr(self,'operation_popup',None):self.operation_popup.close()
            if row:self.popup=ActionRequired(self,row,result['result']['reason']);self.popup.show()
            self.status.setText(result['result']['reason'])
        elif getattr(self,'operation_popup',None):self.operation_popup.close()
    def later(self,row=None):
        row=row if isinstance(row,dict) else self.selected()
        if row:
            from autojob.live import command
            command(row['job_id'],'LATER')
            if getattr(self,'navigation_job',None)==row['job_id'] and getattr(self,'direct_worker',None):self.direct_worker.cancelled.set()
            if row.get('verification_id'):VerificationStore(self.shell.settings.data_path).update(row['verification_id'],command='OMITIR')
            self.shell.engine.store.intervention_state(row['id'],'POSPUESTA');self.status.setText('Intervención conservada. No se repetirá esta ventana.');self.refresh()
            if self.all_mode:QTimer.singleShot(0,self.next_problem)
    def omit(self,row=None):
        row=row if isinstance(row,dict) else self.selected()
        if row:
            from autojob.live import command
            command(row['job_id'],'CANCEL')
            if getattr(self,'navigation_job',None)==row['job_id'] and getattr(self,'direct_worker',None):self.direct_worker.cancelled.set()
            if row.get('verification_id'):VerificationStore(self.shell.settings.data_path).update(row['verification_id'],command='OMITIR')
            self.shell.engine.store.omit(row['id']);self.refresh()
            if self.all_mode:QTimer.singleShot(0,self.next_problem)
    def check(self):
        row=self.selected()
        if not row:return
        from autojob.live import command
        if command(row['job_id'],'CHECK'):self.status.setText('Comprobando el formulario actual en su sesión; un clic no declara resuelto el bloqueo.');return
        from autojob.ui.background import submit
        def done(result):
            ok,value=result;self.status.setText('Solución comprobada; se prioriza su continuación.' if ok else value)
            if ok and value:self.resume_ids.add(value)
            self.shell.request_refresh()
            if ok and self.all_mode:QTimer.singleShot(0,self.next_problem)
        submit(self.window(),lambda:self.service.resume(row['id']),done,self.status.setText)
    def resolve_all(self,*args):
        self.all_mode=True;self.cycle_seen=set();self.next_problem()
    def next_problem(self):
        self.shell.main.setCurrentIndex(2);self.shell.post_tabs.setCurrentWidget(self);self.refresh()
        row=next((r for r in self.rows if r['id'] not in self.cycle_seen),None)
        if row:self.cycle_seen.add(row['id']);self.show_problem(row,dict(popups=True,notifications=False))
        else:self.status.setText('No quedan más intervenciones en este recorrido. Las pospuestas siguen guardadas.');self.all_mode=False

class Shell(QObject):
    def __init__(self,window):
        super().__init__(window)
        self.window=window;self.settings=window.settings;self.engine=Coordinator(self.settings);self.engine.store.recover();from_auto_sender_recover(self.settings);self.worker=None;self.delivery_authorization=None;self.original_widgets=[];self.normal_hosts={};self.advanced_hosts={};self.main=QTabWidget();self.main.tabBar().setObjectName('main-navigation');self.main.setStyleSheet('QTabBar#main-navigation::tab{padding:13px 22px;font-size:15px;font-weight:600} QTabBar#main-navigation::tab:selected{background:rgba(40,94,153,225);color:white}');window.main_tabs=self.main
        old=window.takeCentralWidget();window.setCentralWidget(self.main);self.old=old;original=[(old.widget(i),old.tabText(i)) for i in range(old.count())];self.original_widgets=[w for w,t in original];old.blockSignals(True)
        while old.count():old.removeTab(0)
        for widget,title in original:
            host=Host();self.advanced_hosts[widget]=host;old.addTab(host,title)
        old.blockSignals(False);old.router=self
        self.post_tabs=QTabWidget();self.center=Interventions(self);self.home=Home(self);self.posts=Applications(self);self.post_tabs.addTab(self.posts,'Postulaciones');self.post_tabs.addTab(self.center,'Centro de intervenciones');self.history=QPlainTextEdit();self.history.setReadOnly(True);self.post_tabs.addTab(self.history,'Historial')
        self.data_tabs=QTabWidget()
        for widget,title in [(window.resumes_widget,'Currículums'),(window.profile_widget,'Perfil personal'),(window.application_data_widget,'Información adicional y disponibilidad')]:
            host=Host();self.normal_hosts[widget]=host;self.data_tabs.addTab(host,title)
        self.preference_host=Host();self.data_tabs.insertTab(2,self.preference_host,'Preferencias laborales')
        from autojob.ui.identity_widget import IdentityWidget
        self.identity_widget=IdentityWidget(self.settings);self.identity_host=Host();self.identity_host.mount(self.identity_widget);self.data_tabs.addTab(self.identity_host,'Identificación personal')
        from autojob.ui.submission_ui import ApprovedAnswersPanel
        self.approved_answers=ApprovedAnswersPanel(self.settings.data_path);self.answers_host=Host();self.answers_host.mount(self.approved_answers);self.data_tabs.addTab(self.answers_host,'Respuestas aprobadas')
        self.config_widget=QWidget();self.config_area=QScrollArea();self.config_area.setWidgetResizable(True);self.config_area.setWidget(self.config_widget);layout=QVBoxLayout(self.config_widget);layout.setAlignment(Qt.AlignmentFlag.AlignTop);layout.addWidget(QLabel('Configuración · Conserva aquí las herramientas de búsqueda, cuentas y funciones avanzadas.'));links=QGridLayout()
        for n,(text,widget) in enumerate([('Fuentes, palabras clave y filtros',window.jobs_widget),('Brave y navegación',original[0][0]),('Cuentas, credenciales y permisos',window.accounts_widget),('Pesos y equivalencias',window.compatibility_widget),('Plantillas',window.template_widget),('Banco de respuestas',window.answers_widget),('Cartas',window.letters_widget),('Simulador',window.simulator_widget),('Historial de preparación',window.preparation_widget),('Gestor técnico de verificaciones',window.notifications_widget)]):b=QPushButton(text);b.clicked.connect(lambda checked=False,w=widget:self.open_advanced(w));links.addWidget(b,n//2,n%2)
        layout.addLayout(links);form=QFormLayout();self.options={}
        for key,label,maxval in [('max_verify','Máximo de verificaciones por ejecución',10),('max_evaluate','Máximo de evaluaciones por ejecución',300),('max_prepare','Máximo de preparaciones por ejecución',20)]:s=QSpinBox();s.setRange(0,maxval);s.setValue(self.engine.store.config()[key]);s.valueChanged.connect(lambda value,k=key:self.engine.store.configure(**{k:value}));form.addRow(label,s);self.options[key]=s
        for key,label in [('popups','Ventanas de intervención'),('notifications','Notificaciones de Windows')]:c=QCheckBox(label);c.setChecked(self.engine.store.config()[key]);c.toggled.connect(lambda value,k=key:self.engine.store.configure(**{k:value}));form.addRow(c)
        layout.addLayout(form);advanced=QPushButton('Herramientas avanzadas · interfaces originales');advanced.clicked.connect(self.show_advanced);layout.addWidget(advanced);self.advanced_area=QScrollArea();self.advanced_area.setWidgetResizable(True);self.advanced_area.setWidget(old);self.advanced_area.hide();layout.addWidget(self.advanced_area,1)
        save_search=QPushButton('Guardar configuración de búsqueda');save_search.clicked.connect(self.save_search);layout.addWidget(save_search)
        logs=QPushButton('Abrir logs locales');logs.clicked.connect(self.open_logs);layout.addWidget(logs)
        evidence=QPushButton('Abrir evidencias e historial técnico');evidence.clicked.connect(window.open_evidence);layout.addWidget(evidence)
        for widget,title in [(self.home,'INICIO'),(self.data_tabs,'MIS DATOS'),(self.post_tabs,'POSTULACIONES'),(self.config_area,'CONFIGURACIÓN')]:self.main.addTab(widget,title)
        self.main.currentChanged.connect(window.set_section_background);self.main.currentChanged.connect(self.enter);self.data_tabs.currentChanged.connect(self.enter_data);old.currentChanged.connect(self.enter_advanced);self.main.setCurrentIndex(0);window.set_section_background(0);window.setMinimumSize(760,600);window.setWindowTitle('Job Hunting · Centro de control')
        window.notifications_widget.silent_mode=True;window.notifications_widget.coordinated=True;window.notifications_widget.tray.hide();window.jobs_widget.timer.stop()
        try:window.jobs_widget.frequency.valueChanged.disconnect(window.jobs_widget.schedule)
        except RuntimeError:pass
        self.schedule_timer=QTimer(self.main);self.schedule_timer.timeout.connect(lambda:self.start() if not self.occupied() or self.manual_intervention_only() else None);window.jobs_widget.frequency.valueChanged.connect(self.schedule)
        saved=self.engine.store.config().get('search')
        if saved:
            window.jobs_widget.keywords.setPlainText('\n'.join(saved['queries']));window.jobs_widget.limit.setValue(saved['limit']);window.jobs_widget.frequency.setValue(saved.get('hours',window.jobs_widget.frequency.value()))
            for name,box in window.jobs_widget.sources.items():box.setChecked(name in saved['sources'])
        self.schedule()
        project_button=QPushButton('Revisar proyectos y estudios documentados en mis currículums');project_button.clicked.connect(self.open_projects);self.normal_hosts[window.profile_widget].body.insertWidget(0,project_button)
        self.timer=QTimer(self.main);self.timer.timeout.connect(self.request_refresh);self.timer.start(2500);self.enter_data();self.refresh_task=None;self.refresh_pending=False;self.request_refresh()
    def authorize(self):
        if self.occupied():self.home.status.setText('Termina o pausa el trabajo actual antes de autorizar envíos.');return
        from autojob.ui.batch_ui import BatchAuthorization
        dialog=BatchAuthorization(self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.delivery_authorization=dialog.authorization;self.engine.delivery_authorization=dialog.authorization;self.home.mode.setText('MODO AUTOMÁTICO AUTORIZADO · Alcance revisado · Pulsa INICIAR');self.home.status.setText('Lote limitado por duración, dominios, geografía, CV y criterios revisados. No incluye identidad ni acuerdos especiales.');self.home.refresh()
    def test_mode(self):
        if self.delivery_authorization:
            from autojob.forms.submissions import SubmissionStore
            SubmissionStore(self.settings.data_path).revoke(self.delivery_authorization)
        self.delivery_authorization=None;self.engine.delivery_authorization=None;self.home.mode.setText('MODO PRUEBA — ENVÍOS REALES DESACTIVADOS');self.home.refresh()
    def open_projects(self):
        self.open(self.window.resumes_widget);self.window.resumes_widget.detail_tabs.setCurrentIndex(2)
    def busy(self):return bool(self.worker and self.worker.isRunning())
    def occupied(self):
        if self.busy():return True
        if self.window.worker and self.window.worker.isRunning():return True
        for widget in self.original_widgets:
            for key in ['worker','offer']:
                worker=getattr(widget,key,None)
                if worker and worker.isRunning():return True
        return False
    def manual_intervention_only(self):
        if self.busy() or self.window.worker and self.window.worker.isRunning():return False
        active=[widget for widget in self.original_widgets for key in ['worker','offer'] if getattr(widget,key,None) and getattr(widget,key).isRunning()]
        return bool(active) and all(widget==self.window.notifications_widget for widget in active)
    def schedule(self,*args):
        self.schedule_timer.stop();hours=self.window.jobs_widget.frequency.value()
        if hours:self.schedule_timer.start(max(6,hours)*3600000)
    def save_search(self):
        self.engine.store.configure(search=self.options_snapshot());self.home.status.setText('Configuración de búsqueda guardada para el próximo inicio.')
    def open_logs(self):
        import os
        path=self.settings.data_path/'logs';path.mkdir(exist_ok=True);os.startfile(str(path))
    def options_snapshot(self):
        w=self.window.jobs_widget
        return dict(queries=[line.strip() for line in w.keywords.toPlainText().splitlines() if line.strip()],sources=[name for name,b in w.sources.items() if b.isChecked()],limit=w.limit.value(),hours=w.frequency.value())
    def start(self,*args,ids=None):
        if self.busy():self.home.status.setText('Ya hay una ejecución activa.');return
        if self.occupied() and not self.manual_intervention_only():self.home.status.setText('Espera a que termine la herramienta avanzada o la sesión de intervención.');return
        if self.delivery_authorization and not self.home.update_authorization():
            self.delivery_authorization=None;self.engine.delivery_authorization=None;self.home.mode.setText('MODO PREPARACIÓN — ENVÍOS REALES DESACTIVADOS');self.home.status.setText('El lote ya no está vigente para estos datos. Revisa y autoriza otro lote antes de iniciar envíos.');self.home.refresh();return
        self.center.notification_cutoff=__import__('autojob.control',fromlist=['now']).now()
        options=self.options_snapshot()
        if not options['queries'] or not options['sources']:self.home.status.setText('Configura al menos una fuente y una palabra clave.');return
        self.engine.store.configure(search=options)
        self.engine.delivery_authorization=self.delivery_authorization;self.worker=ControlWorker(self.engine,options,ids);self.worker.progress.connect(self.home.status.setText);self.worker.done.connect(self.finished,Qt.ConnectionType.QueuedConnection);self.worker.start();self.main.setCurrentIndex(0);self.home.start.setEnabled(False);self.home.pause.setEnabled(True);self.home.stop.setEnabled(True)
    def pause(self):
        if self.worker:self.worker.paused.set();self.home.status.setText('Pausa solicitada. Se termina la operación actual y se conserva un punto recuperable.')
    def stop(self):
        if self.worker:self.worker.stopped.set();self.home.status.setText('Detención solicitada. Se conservan los resultados guardados; no se inicia otra vacante.')
    @Slot(object)
    def finished(self,result):
        self.home.start.setEnabled(True);self.home.pause.setEnabled(False);self.home.stop.setEnabled(False)
        self.home.status.setText(result.get('state','Finalizado')+(' · Ejecución autorizada conservada.' if self.delivery_authorization else ' · Envíos reales desactivados.'));self.request_refresh()
        if getattr(self,'close_requested',False):QTimer.singleShot(100,self.window.close)
    def request_refresh(self,include_posts=False):
        if getattr(self,'close_requested',False):return
        self.refresh_pending=bool(include_posts) or self.main.currentIndex()==2 or getattr(self,'refresh_pending',False)
        if getattr(self,'refresh_task',None) is not None:return
        from autojob.ui.background import submit,snapshot
        settings=self.settings;include=self.refresh_pending;self.refresh_pending=False
        def done(data):self.apply_snapshot(data)
        def error(message):self.home.status.setText(message)
        task=submit(self.window,lambda:snapshot(settings,include),done,error);self.refresh_task=task
        def finished():
            self.refresh_task=None
            from shiboken6 import isValid
            if isValid(self.window) and self.refresh_pending:QTimer.singleShot(0,lambda:self.request_refresh(True) if isValid(self.window) else None)
        task.completed.connect(finished)
    def apply_snapshot(self,data):
        counts=data['counts']
        for key,label in self.home.cards.items():label.setText(str(counts[key]))
        self.home.goal.setText(f"POSTULACIONES CONFIRMADAS: {counts['sent']}/{counts['target']}")
        self.home.update_authorization()
        self.home.browser_state.setText('Brave: disponible · perfil independiente' if data['browser_available'] else 'Brave: sesión ocupada o reservada para intervención; otras tareas locales pueden continuar')
        run=data['latest'];self.home.status.setText((run['state']+' · '+run['operation']) if run else 'Listo para iniciar. No se ha ejecutado el coordinador.')
        running=self.busy();self.home.start.setEnabled(not running);self.home.pause.setEnabled(running);self.home.stop.setEnabled(running)
        self.center.apply_snapshot(data)
        if 'posts' in data:
            self.posts.refresh(data=data['posts']);events=data['events'];runs=data['runs'];self.history.setPlainText('EJECUCIONES\n'+'\n'.join(r['started_at']+' · '+r['state']+' · '+r['operation'] for r in runs)+'\n\nOPERACIONES\n'+'\n'.join(r['at']+' · '+r['phase']+' · '+r['code'] for r in events))
    def refresh(self):
        self.home.refresh();self.center.refresh()
        if self.main.currentIndex()==2:
            self.posts.refresh()
            with closing(self.engine.store.db.connect()) as db:events=[dict(r) for r in db.execute('SELECT at,phase,code FROM control_events ORDER BY id DESC LIMIT 100')];runs=[dict(r) for r in db.execute('SELECT started_at,state,operation FROM control_runs ORDER BY started_at DESC LIMIT 30')]
            self.history.setPlainText('EJECUCIONES\n'+'\n'.join(r['started_at']+' · '+r['state']+' · '+r['operation'] for r in runs)+'\n\nOPERACIONES\n'+'\n'.join(r['at']+' · '+r['phase']+' · '+r['code'] for r in events))
    def enter(self,index):
        if index==1:self.enter_data()
        elif index==2:self.request_refresh(True)
    def enter_data(self,*args):
        host=self.data_tabs.currentWidget()
        if host==self.identity_host:self.identity_widget.refresh();return
        if host==self.answers_host:self.approved_answers.refresh();return
        self.identity_widget.hide_number()
        if host==self.preference_host:
            host.mount(self.window.profile_widget);tabs=self.window.profile_widget.findChild(QTabWidget)
            for n in range(tabs.count()):
                if tabs.tabText(n)=='Preferencias laborales':tabs.setCurrentIndex(n);break
            return
        for widget,h in self.normal_hosts.items():
            if h==host:h.mount(widget)
    def open(self,widget):
        if widget in self.normal_hosts:self.main.setCurrentIndex(1);self.data_tabs.setCurrentWidget(self.normal_hosts[widget]);self.normal_hosts[widget].mount(widget)
        elif widget in {self.window.queue_widget,self.window.jobs_widget,self.window.recommendations_widget,self.window.compatibility_widget}:self.main.setCurrentIndex(2);self.post_tabs.setCurrentWidget(self.posts);self.posts.refresh()
        elif widget==self.window.notifications_widget:self.main.setCurrentIndex(2);self.post_tabs.setCurrentWidget(self.center)
        else:self.open_advanced(widget)
    def open_advanced(self,widget):
        self.main.setCurrentIndex(3);self.advanced_area.show();host=self.advanced_hosts[widget];self.advanced_hosts[widget].mount(widget);QTabWidget.setCurrentWidget(self.old,host)
    def show_advanced(self):
        self.advanced_area.show();self.enter_advanced(self.old.currentIndex())
    def enter_advanced(self,index):
        if self.advanced_area.isVisible():
            host=self.old.widget(index)
            for widget,h in self.advanced_hosts.items():
                if h==host:h.mount(widget)
    def allow_close(self):
        from autojob.live import cancel_all,active
        if active():self.close_requested=True
        cancel_all()
        if getattr(self.center,'direct_worker',None) and self.center.direct_worker.isRunning():
            self.center.direct_worker.cancelled.set();self.close_requested=True;return False
        if any(t.isRunning() for t in getattr(self.window,'_ui_tasks',set())):
            self.close_requested=True;self.timer.stop();return False
        if self.busy():self.close_requested=True;self.stop();return False
        if self.center.popup:self.center.popup.close()
        return True

def install(window,engine=None):
    from autojob.ui.simple_shell import SimpleShell
    window.shell=SimpleShell(window,engine)

