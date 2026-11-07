"""Formularios reservados en hilos y perfiles propios, sin bloquear la cola."""
from threading import Event, RLock, Thread
from autojob.forms.submissions import SubmissionEngine


class FormSessions:
    def __init__(self, settings, limit=3):
        self.settings = settings
        self.limit = limit
        self.lock = RLock()
        self.tasks = {}
        self.active_id=None

    def active_job(self):
        with self.lock:
            candidates=[job for job,t in self.tasks.items() if not t.get('discarded') and (t['thread'].is_alive() or (t.get('result') or {}).get('state')=='PENDIENTE')]
            return self.active_id if self.active_id in candidates else next(iter(reversed(candidates)),None)

    def stop_job(self,job):
        # Solo una señal; Playwright y su cierre pertenecen al hilo de la sesión.
        with self.lock:
            task=self.tasks.get(job)
            if task:
                task['discarded']=True;task['cancel'].set()
                task['message']='Deteniendo esta candidatura de forma segura; se conserva cualquier resultado final.'
            if self.active_id==job:self.active_id=None

    def count(self):
        with self.lock:
            return sum(t['thread'].is_alive() for t in self.tasks.values())

    def preparing_count(self):
        with self.lock:
            return sum(t['thread'].is_alive() and not t.get('readonly') for t in self.tasks.values())

    def park_idle(self):
        """Liberar solo preparaciones sin intervención humana para avanzar la cola."""
        from autojob.live import command
        with self.lock:
            for job,task in self.tasks.items():
                if task['thread'].is_alive() and not task.get('readonly') and not task['focus'] and task['ready'].is_set() and command(job,'PARK'):
                    task['parked']=True
                    task['message']='Preparación guardada para continuar con otra candidatura. Resolver ahora recuperará los campos y el CV autorizados.'
                    return True
        return False

    def contains(self, job):
        with self.lock:
            task = self.tasks.get(job)
            return bool(task and task['thread'].is_alive())

    def launch(self, job, authorization, human=False, preparation_only=False, readonly=False, url=None, mode='real', notice=''):
        from autojob.live import command
        with self.lock:
            if self.contains(job):
                if human:
                    self.active_id=job
                    self.tasks[job]['focus'] = True
                    command(job, 'FOCUS')
                return self.tasks[job]
            if not readonly and self.preparing_count() >= self.limit:
                return None
            task = dict(ready=Event(), cancel=Event(), focus=human, result=None, preparation_only=preparation_only or readonly, readonly=readonly, message='Abriendo la candidatura seleccionada en Brave…', reported=None)

            def run():
                try:
                    if readonly:
                        task['result']=self.consult(job,url,mode,notice,task)
                    else:
                        task['result'] = SubmissionEngine(self.settings).run(
                            job, authorization, stop=task['cancel'].is_set,
                            retain=True, isolated=True, prepared=task['ready'])
                except Exception as exc:
                    # No registrar valores, respuestas, URLs con tokens ni credenciales.
                    task['result'] = dict(state='PENDIENTE', reason='No se pudo abrir o preparar el portal. I9I_NAVIGATION_'+type(exc).__name__+'. La candidatura sigue guardada.')
                    from autojob.control import ControlStore
                    from autojob.forms.queue import PreparationQueue
                    queue = PreparationQueue(self.settings.data_path)
                    record = next((j for j in queue.preparation.compatibility.jobs.list() if j['id'] == job), None)
                    if record and not task.get('discarded'):
                        ControlStore(self.settings.data_path).add_intervention(job, record['company'], record['title'], 'PORTAL NO DISPONIBLE', task['result']['reason'], record.get('application_url') or record['url'])
                finally:
                    if not task.get('parked'):task['message']=(task['result'] or {}).get('reason') or (task['result'] or {}).get('state','Operación terminada.')
                    task['ready'].set()

            task['thread'] = Thread(target=run, name='job-hunting-form-'+job[:8], daemon=True)
            self.tasks[job] = task
            self.active_id=job
            task['thread'].start()
            return task

    def consult(self,job,url,mode,notice,task):
        """Consulta explícita de una fila: no reclama intentos ni transmite adjuntos."""
        from autojob.browser import BraveSession
        from autojob.forms.guard import PreparationGuard
        from autojob.forms.execution import public_destination
        import re
        public_destination(url,mode)
        from autojob.forms.navigation import category_url,open_page,save
        if category_url(url):return dict(state='ENLACE INVÁLIDO',reason='Categoría general sin candidatura identificada; continuar con otra oferta.')
        with BraveSession(self.settings,isolated_key=job) as browser:
            guard=PreparationGuard(browser);page=browser.new_page()
            cdp=browser.context.new_cdp_session(page);cdp.send('Network.enable');cdp.send('Network.setBypassServiceWorker',{'bypass':True})
            http=None
            try:
                record=next((j for j in __import__('autojob.search.jobs',fromlist=['JobStore']).JobStore(self.settings.data_path).list() if j['id']==job),None)
                diagnostic=open_page(guard,page,url,record);save(self.settings.data_path,job,diagnostic)
            except ValueError as exc:
                match=re.fullmatch(r'HTTP (\d{3})',str(exc))
                if not match:raise
                http=int(match[1])
            page.bring_to_front();task['focus']=False
            closed=http in {404,410} or bool(re.search(r'this job is not available|no longer available|no longer accepting|job not found',page.locator('body').inner_text(),re.I))
            from autojob.application_status import consultation_message
            task['message']=(diagnostic['state']+' — '+diagnostic['title']+'\n' if http is None else '')+consultation_message(notice,closed,http)
            task['ready'].set()
            while not task['cancel'].is_set() and not page.is_closed():
                if task['focus']:page.bring_to_front();task['focus']=False
                page.wait_for_timeout(200)
        return dict(state='CONSULTADA',reason='Consulta cerrada. La candidatura y su historial se conservan.')

    def prepare(self, job, authorization, cancelled):
        # INICIAR sustituye un permiso de recuperación que solo podía rellenar.
        # Primero termina su propietario; nunca dos trabajadores sobre la misma página.
        with self.lock:
            old=self.tasks.get(job)
            if old and old.get('preparation_only'):old['cancel'].set()
            else:old=None
        if old:
            while old['thread'].is_alive():
                old['thread'].join(.1)
                if cancelled():return dict(state='PENDIENTE',reason='Continuación pausada.')
        task = self.launch(job, authorization)
        if task is None:
            return dict(state='EN COLA', reason='Tres formularios conservados; esperando una sesión libre.')
        while not task['ready'].wait(.1):
            if cancelled():
                task['cancel'].set()
                return dict(state='PENDIENTE', reason='Preparación pausada; se conserva en la cola.')
        return task['result'] or dict(state='PENDIENTE', reason='Formulario preparado y reservado; la búsqueda continúa.')

    def tick(self):
        from autojob.live import command,status
        updates=[]
        with self.lock:
            for job, task in self.tasks.items():
                observed=status(job) if not task.get('readonly') and not task.get('discarded') else None
                if observed:task['message']=observed
                if not task.get('readonly') and task['focus'] and command(job, 'FOCUS'):
                    task['focus'] = False
                if task.get('message')!=task.get('reported'):
                    task['reported']=task.get('message');updates.append((job,task['reported']))
        return updates

    def cancel_all(self):
        with self.lock:
            for task in self.tasks.values():
                task['cancel'].set()

