"""Trabajos locales sin widgets; entrega explícita al hilo gráfico por señales Qt."""
import time
from PySide6.QtCore import QThread,Signal,QTimer,QCoreApplication,QObject,Slot,Qt
from shiboken6 import isValid

class UiTask(QThread):
    result=Signal(object)
    failed=Signal(str)
    completed=Signal()
    def __init__(self,owner,operation):super().__init__(owner);self.operation=operation;self.elapsed_ms=None;self.delivery_discarded=None
    def run(self):
        start=time.perf_counter()
        try:self.result.emit(self.operation())
        except Exception as exc:self.failed.emit(str(exc) if isinstance(exc,ValueError) else 'No se pudo completar la operación local ('+type(exc).__name__+').')
        finally:self.elapsed_ms=(time.perf_counter()-start)*1000

class Completion(QObject):
    def __init__(self,owner,task,done,error):super().__init__(QCoreApplication.instance());self.owner=owner;self.task=task;self.done=done;self.error=error
    def active(self):
        valid=isValid(self.owner) and not getattr(getattr(self.owner,'shell',None),'close_requested',False)
        if not valid:self.task.delivery_discarded='VENTANA CERRADA'
        return valid
    @Slot(object)
    def success(self,value):
        if self.active():self.done(value)
    @Slot(str)
    def failure(self,message):
        if self.active():self.error(message)
    @Slot()
    def finish(self):
        owner=self.owner;task=self.task;owner._ui_tasks.discard(task);QCoreApplication.instance()._background_tasks.discard(task);task.completed.emit()
        if isValid(owner) and getattr(getattr(owner,'shell',None),'close_requested',False):QTimer.singleShot(0,lambda:owner.close() if isValid(owner) else None)
        task.deleteLater();self.deleteLater()

def submit(owner,operation,done,error):
    app=QCoreApplication.instance();task=UiTask(app,operation)
    if not hasattr(owner,'_ui_tasks'):owner._ui_tasks=set()
    if not hasattr(app,'_background_tasks'):app._background_tasks=set()
    owner._ui_tasks.add(task);app._background_tasks.add(task);receiver=Completion(owner,task,done,error);task._completion=receiver
    task.result.connect(receiver.success,Qt.ConnectionType.QueuedConnection);task.failed.connect(receiver.failure,Qt.ConnectionType.QueuedConnection);task.finished.connect(receiver.finish,Qt.ConnectionType.QueuedConnection);task.start();return task

def snapshot(settings,include_posts=False):
    from contextlib import closing
    from autojob.control import Coordinator
    from autojob.interventions import InterventionService
    from autojob.forms.submissions import SubmissionStore
    from autojob.browser.lock import ProfileLock
    engine=Coordinator(settings);store=engine.store;queue=engine.queue
    counts=store.counts(queue);store.sync(queue);latest=store.latest()
    ready=InterventionService(engine).ready() if latest and latest['state'] not in {'DETENIDO','PAUSADO','ERROR'} else []
    lock=ProfileLock(settings.data_path/'browser.lock');available=False
    try:lock.acquire();available=True
    except Exception:pass
    finally:lock.release()
    if latest and latest['state']=='ESPERANDO INTERVENCIÓN':
        from autojob.control import completion_text
        pending=sum(r['state'] in {'PENDIENTE','POSPUESTA'} for r in store.interventions());queued=sum(r['state']=='POR PREPARAR' for r in queue.list())
        latest=dict(latest,operation=completion_text(latest['state'],pending,latest.get('checkpoint',{}).get('eligible',counts['compatible']),queued,available,bool((store.config().get('search') or {}).get('hours'))))
    result=dict(counts=counts,latest=latest,ready=ready,interventions=[r for r in store.interventions() if r['state'] in {'PENDIENTE','POSPUESTA'}],config=store.config(),browser_available=available)
    if include_posts:
        result['posts']=dict(deliveries={r['job_id']:r for r in reversed(SubmissionStore(settings.data_path).rows()) if r['mode']=='real'},rows=engine.compatibility.rows(),queue={r['job_id']:r for r in queue.list()},current_hash=queue.preparation.inputs_hash(),confirmed_urls=store.confirmed_urls(),omitted=store.excluded())
        with closing(store.db.connect()) as db:
            result['events']=[dict(r) for r in db.execute('SELECT at,phase,code FROM control_events ORDER BY id DESC LIMIT 100')];result['runs']=[dict(r) for r in db.execute('SELECT started_at,state,operation FROM control_runs ORDER BY started_at DESC LIMIT 30')]
    return result
