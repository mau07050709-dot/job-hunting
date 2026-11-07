"""OCR local, en memoria, únicamente de la candidatura visible y vinculada."""
import asyncio
import re
import sys
from hashlib import sha256
from PySide6.QtCore import QObject,QThread,QTimer,Signal,QBuffer,QIODevice
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication


def form_labels(text):
    text=text.casefold()
    name=bool(re.search(r"first name|full name|nombre|apellido",text))
    email=bool(re.search(r"e.?mail|correo",text))
    return name and email


async def recognize_png(png):
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapDecoder,SoftwareBitmap,BitmapPixelFormat,BitmapAlphaMode
    from winrt.windows.storage.streams import InMemoryRandomAccessStream,DataWriter
    stream=InMemoryRandomAccessStream()
    writer=DataWriter(stream.get_output_stream_at(0))
    try:
        writer.write_bytes(png)
        await writer.store_async()
        await writer.flush_async()
        stream.seek(0)
        decoder=await BitmapDecoder.create_async(stream)
        source=await decoder.get_software_bitmap_async()
        bitmap=SoftwareBitmap.convert(source,BitmapPixelFormat.BGRA8,BitmapAlphaMode.PREMULTIPLIED)
        try:
            for tag in ('en-US','es-ES'):
                engine=OcrEngine.try_create_from_language(Language(tag))
                if engine:
                    result=await engine.recognize_async(bitmap)
                    if form_labels(result.text):return True
            return False
        finally:bitmap.close();source.close()
    finally:writer.close();stream.close()


def capture_candidate(target):
    """No capturar otras apps, ventanas no enfocadas, barra de pestañas ni CAPTCHA."""
    if sys.platform!='win32' or not target.get('title') or target.get('captcha'):return None
    import ctypes as C
    from ctypes import wintypes as W
    user=C.WinDLL('user32',use_last_error=True);kernel=C.WinDLL('kernel32',use_last_error=True)
    user.GetForegroundWindow.restype=W.HWND
    user.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
    user.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
    user.GetClientRect.argtypes=[W.HWND,C.POINTER(W.RECT)]
    kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)]
    kernel.CloseHandle.argtypes=[W.HANDLE]
    hwnd=user.GetForegroundWindow();title=C.create_unicode_buffer(600)
    user.GetWindowTextW(hwnd,title,600)
    if title.value not in (target['title']+' - Brave',target['title']+' – Brave'):return None
    pid=W.DWORD();user.GetWindowThreadProcessId(hwnd,C.byref(pid))
    handle=kernel.OpenProcess(0x1000,False,pid.value)
    if not handle:return None
    try:
        path=C.create_unicode_buffer(2048);size=W.DWORD(2048)
        if not kernel.QueryFullProcessImageNameW(handle,0,path,C.byref(size)) or not path.value.lower().endswith('\\brave.exe'):return None
    finally:kernel.CloseHandle(handle)
    screen=QGuiApplication.primaryScreen()
    if not screen:return None
    image=screen.grabWindow(int(hwnd)).toImage()
    if image.isNull():return None
    # innerHeight pertenece solo al documento; excluir las barras del navegador.
    height=int(target.get('height',0)*image.devicePixelRatio())
    if height<100 or height>image.height():return None
    image=image.copy(0,image.height()-height,image.width(),height)
    if image.width()>1600:image=image.scaledToWidth(1600)
    buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buffer,'PNG')
    return bytes(buffer.data())


class VisualWorker(QThread):
    result=Signal(str,str,bool,str)
    def __init__(self,target,png):
        super().__init__(QApplication.instance());self.target=target;self.png=png
    def run(self):
        import winrt.runtime as runtime
        runtime.init_apartment(runtime.ApartmentType.MULTI_THREADED)
        try:
            async def limited():
                async with asyncio.timeout(8):return await recognize_png(self.png)
            found=asyncio.run(limited())
            self.result.emit(self.target['id'],self.target['url'],found,'')
        except Exception:
            self.result.emit(self.target['id'],self.target['url'],False,'OCR local no disponible; el lector de campos de la extensión sigue activo.')
        finally:self.png=b'';runtime.uninit_apartment()


class VisualFill(QObject):
    status=Signal(str)
    def __init__(self,bridge,parent=None):
        super().__init__(parent);self.bridge=bridge;self.worker=None;self.last=None;self.closed=False;self.error_shown=False
        self.timer=QTimer(self);self.timer.setInterval(2000);self.timer.timeout.connect(self.tick);self.timer.start()
    def tick(self):
        if self.closed or self.worker:return
        target=self.bridge.visual_target()
        if not target:return
        png=capture_candidate(target)
        if not png:return
        signature=(target['id'],target['url'],sha256(png).digest())
        if signature==self.last:return
        self.last=signature
        worker=VisualWorker(target,png);self.worker=worker
        worker.result.connect(self.result)
        worker.finished.connect(self.finished)
        worker.start()
    def result(self,task,url,found,error):
        if self.closed:return
        if error and not self.error_shown:self.error_shown=True;self.status.emit(error)
        current=self.bridge.visual_target()
        if found and current and current['id']==task and current['url']==url:
            self.bridge.visual_detected(task,url)
    def finished(self):
        worker=self.worker;self.worker=None
        if worker:worker.deleteLater()
    def close(self):
        self.closed=True;self.timer.stop()
        if self.worker:
            try:self.worker.result.disconnect(self.result);self.worker.finished.disconnect(self.finished)
            except RuntimeError:pass
            self.worker.finished.connect(self.worker.deleteLater)
            self.worker=None
