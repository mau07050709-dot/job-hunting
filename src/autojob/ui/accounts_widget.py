import json
from PySide6.QtCore import QThread,Signal,Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QComboBox,QPlainTextEdit,QCheckBox,QPushButton,QTableWidget,QTableWidgetItem,QSpinBox,QScrollArea,QLabel,QMessageBox,QFileDialog,QInputDialog
from autojob.auth.service import Accounts,STATES,check_session
from autojob.auth.vault import Secret

class AuthWorker(QThread):
    done=Signal(object)
    def __init__(self,fn):super().__init__();self.fn=fn
    def run(self):
        try:self.done.emit(dict(ok=True,result=self.fn()))
        except Exception:self.done.emit(dict(ok=False,error='No se completó la operación. Revisa el dominio, el perfil de Brave y el estado de Windows Credential Manager.'))

class AccountsWidget(QWidget):
    def __init__(self,settings):
        super().__init__();self.settings=settings;self.store=Accounts(settings.data_path);self.worker=None;self.selected_id=None
        layout=QVBoxLayout(self);heading=QLabel('Mis cuentas laborales · Fase 8B · Acciones reales solo con permiso explícito del dominio y la acción');heading.setWordWrap(True);layout.addWidget(heading)
        self.table=QTableWidget(0,10);self.table.setHorizontalHeaderLabels(['Plataforma','Sitio web','Correo','Usuario','Estado','Incorporada','Última autenticación','Verificación','Método','Observaciones']);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.itemSelectionChanged.connect(self.select);layout.addWidget(self.table,2)
        body=QWidget();form=QFormLayout(body);self.platform=QLineEdit();self.site=QLineEdit();self.email=QLineEdit();self.username=QLineEdit();self.state=QComboBox();self.state.addItems(STATES);self.method=QComboBox();self.method.addItems(['Correo y contraseña','SSO externo','Sin contraseña','Desconocido']);self.notes=QLineEdit();self.domain=QCheckBox('He comprobado que es el dominio oficial de esta plataforma');self.email_confirmed=QCheckBox('Confirmo que este es el correo de mi cuenta');self.existing=QCheckBox('Esta cuenta ya existe en la plataforma (preparar login)')
        for label,control in [('Plataforma',self.platform),('Sitio HTTPS oficial',self.site),('Correo utilizado',self.email),('Usuario opcional',self.username),('Estado declarado',self.state),('Método de acceso',self.method),('Observaciones (sin secretos)',self.notes),('Validación del dominio',self.domain),('Confirmación del correo',self.email_confirmed),('Cuenta existente',self.existing)]:form.addRow(label,control)
        self.password=QLineEdit();self.password.setEchoMode(QLineEdit.EchoMode.Password);self.password.setPlaceholderText('Solo en memoria; se limpia después de guardar');form.addRow('Contraseña',self.password)
        row=QHBoxLayout();self.length=QSpinBox();self.length.setRange(16,128);self.length.setValue(24);self.symbols=QCheckBox('El portal admite símbolos');self.symbols.setChecked(True);row.addWidget(self.length);row.addWidget(self.symbols);form.addRow('Política de contraseña',row)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(body);layout.addWidget(scroll,2)
        for actions in [[('Nueva entrada',self.clear),('Añadir cuenta',lambda:self.save(True)),('Guardar metadatos',self.save),('Preparar registro',self.prepare),('Generar contraseña',self.generate)], [('Guardar credenciales',self.save_secret),('Ver estado',self.details),('Comprobar sesión',self.check),('Eliminar cuenta del registro',self.remove),('Eliminar credencial guardada',self.delete_secret)], [('Consultar bloqueos',self.blocks),('Exportar historial seguro',self.export),('Prueba local ficticia',self.local),('Actualizar',self.refresh)]]:
            buttons=QHBoxLayout()
            for label,fn in actions:b=QPushButton(label);b.clicked.connect(fn);buttons.addWidget(b)
            layout.addLayout(buttons)
        extra=QHBoxLayout()
        for title,fn in [('Autorizar dominio / acción',self.authorize_domain),('Registrar cuenta — acción real',lambda:self.real_auth('REGISTRO')),('Iniciar sesión — acción real',lambda:self.real_auth('LOGIN')),('Ver verificaciones pendientes',self.blocks),('Revocar autorizaciones del dominio',self.revoke_domain)]:
            b=QPushButton(title);b.clicked.connect(fn);extra.addWidget(b)
        layout.addLayout(extra)
        demo=QPushButton('Prueba local 8B — CAPTCHA manual');demo.clicked.connect(self.manual_demo);layout.addWidget(demo)
        self.status=QLabel('Los secretos se guardan únicamente en Windows. No se leen credenciales de tu navegador personal.');self.status.setWordWrap(True);layout.addWidget(self.status);self.output=QPlainTextEdit();self.output.setReadOnly(True);layout.addWidget(self.output,2);self.refresh()
    def refresh(self):
        selected=self.selected_id;self.rows=self.store.list();self.table.blockSignals(True);self.table.setRowCount(len(self.rows))
        keys=['platform','origin','email','username','state','incorporated_at','last_auth_at','verification','method','notes']
        for n,r in enumerate(self.rows):
            for c,k in enumerate(keys):
                item=QTableWidgetItem(str(r[k] or 'Desconocido'));item.setData(256,r['id']);item.setToolTip(item.text());self.table.setItem(n,c,item)
            if r['id']==selected:self.table.selectRow(n)
        self.table.blockSignals(False)
        for c,width in enumerate([170,230,230,140,210,190,190,190,180,260]):self.table.setColumnWidth(c,width)
    def select(self):
        items=self.table.selectedItems()
        if not items:return
        self.selected_id=items[0].data(256);r=self.store.get(self.selected_id)
        if not r:return
        for control,key in [(self.platform,'platform'),(self.site,'origin'),(self.email,'email'),(self.username,'username'),(self.notes,'notes')]:control.setText(r[key])
        self.state.setCurrentText(r['state']);self.method.setCurrentText(r['method']);self.domain.setChecked(bool(r['domain_verified']));self.email_confirmed.setChecked(bool(r['email_confirmed']));self.existing.setChecked(bool(r['exists_remotely']));self.password.clear();self.details()
    def clear(self):
        self.selected_id=None;self.table.clearSelection()
        for e in [self.platform,self.site,self.email,self.username,self.notes,self.password]:e.clear()
        self.domain.setChecked(False);self.email_confirmed.setChecked(False);self.existing.setChecked(False);self.state.setCurrentIndex(0);self.output.clear()
    def save(self,new=False):
        try:
            self.selected_id=self.store.add(self.platform.text(),self.site.text(),self.email.text(),self.username.text(),self.state.currentText(),self.method.currentText(),self.notes.text(),self.domain.isChecked(),self.email_confirmed.isChecked(),None if new else self.selected_id,exists_remotely=self.existing.isChecked() or self.state.currentText() in {'ACTIVA','SESIÓN EXPIRADA','CREDENCIALES INCORRECTAS','VERIFICACIÓN PENDIENTE','BLOQUEADA'})
            self.refresh();self.status.setText('Metadatos guardados. No se creó ni inició una cuenta externa.')
        except Exception as e:self.status.setText(str(e) if isinstance(e,ValueError) else 'No se pudieron guardar los metadatos.')
    def generate(self):
        try:
            secret=self.store.generate(self.selected_id,length=self.length.value(),symbols=self.symbols.isChecked())
            try:self.password.setText(secret.reveal())
            finally:secret.clear()
            self.status.setText('Contraseña nueva generada y oculta. Pulsa Guardar credenciales para guardarla en Windows.')
        except Exception:self.status.setText('No se pudo generar o comprobar la contraseña; no se guardó en archivos.')
    def save_secret(self):
        secret=None
        try:
            secret=Secret(self.password.text());self.store.save_secret(self.selected_id,secret);self.status.setText('Credencial guardada en Windows; ningún secreto se guardó en SQLite.');self.refresh()
        except Exception:self.status.setText('No se guardó la credencial. Selecciona una cuenta y utiliza una contraseña distinta, de al menos 12 caracteres.')
        finally:
            self.password.clear()
            if secret:secret.clear()
    def prepare(self):
        try:
            preview=self.store.prepare(self.selected_id);self.output.setPlainText(json.dumps(preview,ensure_ascii=False,indent=2));self.refresh();self.status.setText('Preparación local guardada. Campos desconocidos pendientes; acuerdos sin aceptar. Registro real requiere permiso específico del dominio y acción.')
        except Exception:self.status.setText('No se pudo preparar. Selecciona una cuenta y revisa sus datos y el almacén de Windows.')
    def details(self):
        r=self.store.get(self.selected_id)
        if not r:return
        text=f"{r['platform']}\nSitio: {r['origin']}\nEstado: {r['state']}\nVerificación: {r['verification']}\nCredencial en Windows: {'Sí' if r['credential_ref'] else 'No'}\nDominio revisado: {'Sí' if r['domain_verified'] else 'No'}\n"
        text+='\nHistorial:\n'+'\n'.join(e['at']+' · '+e['event']+' · '+e['state'] for e in self.store.history(r['id']))
        self.output.setPlainText(text)
    def blocks(self):
        tasks=self.store.tasks();selected=self.store.get(self.selected_id);lines=[]
        if selected:lines.append('Verificación de la cuenta: '+selected['verification'])
        for t in tasks:
            if not selected or t['origin']==selected['origin']:lines.append(f"{t['origin']} · {t['kind']} · {t['state']} · {t['url']} · {', '.join(json.loads(t['observation']).get('blocks',[]))}")
        self.output.setPlainText('\n'.join(lines) or 'No hay tareas de autenticación pendientes registradas.')
    def launch_worker(self,fn):
        if self.worker and self.worker.isRunning():self.status.setText('Espera a que termine la comprobación en curso.');return
        self.worker=AuthWorker(fn);self.worker.done.connect(self.finished);self.worker.start();self.status.setText('Comprobación en Brave en curso; la interfaz sigue disponible.')
    def finished(self,result):
        self.refresh();self.output.setPlainText(json.dumps(result,ensure_ascii=False,indent=2));self.status.setText('Operación terminada. Revisa el resultado. El envío de postulaciones permanece deshabilitado.' if result['ok'] else result['error'])
    def check(self):
        r=self.store.get(self.selected_id)
        if not r:self.status.setText('Selecciona una cuenta.');return
        url,ok=QInputDialog.getText(self,'Comprobar sesión sin iniciar sesión','URL del panel o página protegida del mismo origen (sin tokens):',text=r['origin'])
        from autojob.auth.permissions import Permissions,scope
        if ok and not Permissions(self.settings.data_path).allowed(r['origin'],'INSPECCIONAR',scope(self.store,r,'INSPECCIONAR')):self.status.setText('Autoriza INSPECCIONAR para este dominio antes de comprobar la sesión.');return
        if ok:self.launch_worker(lambda:check_session(self.settings,self.store,r['id'],url))
    def local(self):
        from autojob.auth.local import run_local
        self.launch_worker(lambda:run_local(self.settings))
    def delete_secret(self):
        if not self.selected_id:return
        if QMessageBox.question(self,'Eliminar credencial','¿Eliminar de Windows la credencial de esta cuenta?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        try:self.store.delete_secret(self.selected_id);self.refresh();self.details();self.status.setText('Credencial eliminada de Windows; se conserva el registro de cuenta.')
        except Exception:self.status.setText('No se pudo eliminar; la referencia se conserva para volver a intentarlo.')
    def remove(self):
        if not self.selected_id:return
        if QMessageBox.question(self,'Eliminar registro local','¿Eliminar el registro local y su credencial guardada? Esta acción no elimina la cuenta del portal.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        try:self.store.remove(self.selected_id);self.clear();self.refresh()
        except Exception:self.status.setText('No se pudo eliminar la credencial; se conservó la cuenta local.')
    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'Exportar metadatos sin secretos','cuentas-historial.json','JSON (*.json)')
        if path:
            from pathlib import Path
            try:self.store.export(Path(path));self.status.setText('Historial exportado sin contraseñas, referencias secretas ni observaciones libres.')
            except Exception:self.status.setText('No se pudo exportar el historial.')
    def allow_close(self):
        demo=getattr(self,'demo',None)
        if demo and demo.isVisible():
            if demo.worker and demo.worker.isRunning():self.status.setText('Omite o termina primero la prueba local manual.');return False
            demo.close()
        if self.worker and self.worker.isRunning():self.status.setText('Espera a que termine la prueba; se cerrará Brave y eliminará la credencial ficticia.');return False
        self.password.clear();return True

    def authorize_domain(self):
        from autojob.auth.permissions import Permissions,scope
        row=self.store.get(self.selected_id)
        if not row or not row['domain_verified']:self.status.setText('Revisa primero el dominio oficial de la cuenta.');return
        action,ok=QInputDialog.getItem(self,'Permiso independiente','Acción concreta para '+row['origin'],['INSPECCIONAR','RELLENAR','LOGIN','REGISTRO','IDENTIDAD'],0,False)
        if not ok:return
        detail=scope(self.store,row,action);description='Acción: '+action
        if action=='IDENTIDAD':
            from autojob.auth.identity import IdentityStore
            identity=IdentityStore(self.settings.data_path).summary()
            if not identity or not identity['confirmed']:self.status.setText('Confirma primero una identificación protegida.');return
            field,ok=QInputDialog.getItem(self,'Dato concreto','Campo autorizado a este origen',['number','kind','country'],0,False)
            if not ok:return
            detail=identity['revision']+':'+field;description='Identidad: '+field+' · '+identity['kind']+' · '+identity['masked']
        if QMessageBox.question(self,'Autorizar acción real',f"Dominio: {row['origin']}\n{description}\nCuenta: {row['email']}\nPermiso específico y revocable. No autoriza contratos, adjuntos ni postulaciones. Los datos autorizados podrán ser leídos por los scripts de ese sitio. ¿Concederlo?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        Permissions(self.settings.data_path).set(row['origin'],action,detail,True)
        if action=='RELLENAR':
            from autojob.forms.queue import PreparationQueue
            PreparationQueue(self.settings.data_path).allow_site(row['origin'],True)
        self.status.setText('Permiso guardado solo para '+row['origin']+' · '+action)
    def revoke_domain(self):
        from autojob.auth.permissions import Permissions
        row=self.store.get(self.selected_id)
        if row:
            Permissions(self.settings.data_path).revoke(row['origin'])
            from autojob.forms.queue import PreparationQueue
            PreparationQueue(self.settings.data_path).allow_site(row['origin'],False)
            self.status.setText('Permisos revocados. Los trabajadores comprueban el permiso antes de transmitir.')
    def real_auth(self,action):
        row=self.store.get(self.selected_id)
        if not row:self.status.setText('Selecciona una cuenta.');return
        url,ok=QInputDialog.getText(self,'Acción real: '+action,'URL del formulario oficial del mismo origen:',text=row['origin'])
        if not ok:return
        from autojob.auth.external import ExternalAuth
        self.launch_worker(lambda:ExternalAuth(self.settings.data_path).run(self.settings,row['id'],action,url,title=row['platform']))

    def manual_demo(self):
        from autojob.ui.auth_demo import ManualDemo
        demo=getattr(self,'demo',None)
        if demo and demo.isVisible():demo.raise_();return
        self.demo=ManualDemo(self.settings,self.window());self.demo.destroyed.connect(lambda:setattr(self,'demo',None));self.demo.show()
