"""Aviso legible con video opcional, cargado solo cuando se muestra."""
from PySide6.QtCore import QUrl,Qt
from PySide6.QtWidgets import QDialog,QWidget,QStackedLayout,QVBoxLayout
from autojob.notice_media import video_id


class NoticeDialog(QDialog):
    def __init__(self,parent,media,bridge):
        super().__init__(parent);self.media=media;self.bridge=bridge;self.video_view=None;self._url=None
        self.stack=QStackedLayout(self);self.stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.overlay=QWidget();self.overlay.setObjectName('noticeOverlay');self.stack.addWidget(self.overlay)
        self.content=QVBoxLayout(self.overlay)
    def showEvent(self,event):
        super().showEvent(event)
        settings=self.media.load()
        if not settings['enabled']:return
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineSettings
            if self.video_view is None:
                self.video_view=QWebEngineView(self)
                self.video_view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                self.video_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                self.profile=QWebEngineProfile(self)
                self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
                page=QWebEnginePage(self.profile,self.video_view);self.video_view.setPage(page)
                page.setAudioMuted(not settings['sound'])
                page.settings().setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture,False)
                page.settings().setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled,False)
                self.stack.insertWidget(0,self.video_view);self.stack.setCurrentWidget(self.overlay)
                self.overlay.setStyleSheet('#noticeOverlay {background:rgba(15,15,15,155);} #noticeOverlay QLabel {background:transparent;color:white;} #noticeOverlay QPushButton {background:#303030;color:white;}')
            self.video_view.page().setAudioMuted(not settings['sound'])
            self.bridge.start()
            self._url=QUrl(f'http://127.0.0.1:{self.bridge.server.server_port}/notice-video/'+video_id(settings['url']))
            self.video_view.setUrl(self._url)
        except (ImportError,RuntimeError,OSError,ValueError):
            self.overlay.setStyleSheet('background:#212121;')
    def hideEvent(self,event):
        if self.video_view:self.video_view.setUrl(QUrl('about:blank'))
        super().hideEvent(event)
