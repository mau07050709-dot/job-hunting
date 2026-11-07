from dataclasses import replace
import ctypes
import json
import os

from PySide6.QtCore import QThread, Signal, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget

from autojob.config import Settings
from autojob.storage.database import Database


class SmokeWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings

    def run(self):
        from autojob.testing.smoke import run_smoke
        try:
            self.completed.emit(json.dumps(run_smoke(self.settings), ensure_ascii=False, indent=2))
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        from autojob.people import People
        self.people=People(settings)
        self.installation_settings=self.people.settings
        from autojob.ui.appearance import Appearance
        self.appearance=Appearance(self.installation_settings.data_path)
        self.panel_mode=self.appearance.load()
        self.person=self.people.active()
        settings=self.people.settings_for(self.person["id"])
        self.settings = settings
        self.worker = None
        self.database = Database(settings.data_path / "autojob.sqlite3")
        self.setWindowTitle("Job Hunting · Currículums y navegación")
        icon_path=settings.root / "job_hunting.ico"
        if icon_path.is_file():self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1120, 840)
        self.setObjectName("job-maxxing-window")
        self.section_backgrounds = (None,) * 4
        self._background_cache = {}
        self._background = QPixmap()
        self._previous_background = QPixmap()
        self._background_path = None
        self._background_opacity = 1.0
        self._background_transition = QVariantAnimation(self)
        self._background_transition.setDuration(150)
        self._background_transition.setStartValue(0.0)
        self._background_transition.setEndValue(1.0)
        self._background_transition.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._background_transition.valueChanged.connect(self._blend_background)
        self._background_transition.finished.connect(self._finish_background)
        self.setStyleSheet(self._background_stylesheet())
        self._create_workspace()

    def _create_workspace(self,engine=None):
        self._tools = {}
        from autojob.ui.control_shell import RoutedTabs, install
        self.tabs = RoutedTabs(self)
        self.tabs.hide()
        self.tabs.addTab(QWidget(), "Navegación Brave")
        for _, _, title in self.TOOLS.values():
            self.tabs.addTab(QWidget(), title)
        install(self,engine)

    TOOLS = {
        "resumes_widget": ("resumes_widget", "ResumeWidget", "Mis currículums"),
        "profile_widget": ("profile_widget", "ProfileWidget", "Mi perfil"),
        "answers_widget": ("answers_widget", "AnswersWidget", "Respuestas frecuentes"),
        "template_widget": ("template_widget", "TemplateWidget", "Plantillas profesionales"),
        "letters_widget": ("ui_4c", "LettersWidget", "Cartas de presentación"),
        "simulator_widget": ("ui_4c", "SimulatorWidget", "Simulador de postulaciones"),
        "jobs_widget": ("jobs_widget", "JobsWidget", "Buscar empleos"),
        "compatibility_widget": ("compatibility_widget", "CompatibilityWidget", "Compatibilidad laboral"),
        "review_widget": ("review_widget", "ReviewWidget", "Revisar mi perfil"),
        "recommendations_widget": ("compatibility_widget", "CompatibilityWidget", "Vacantes recomendadas"),
        "application_data_widget": ("application_widgets", "ApplicationDataWidget", "Datos para postulaciones"),
        "preparation_widget": ("application_widgets", "PreparationWidget", "Preparar postulación"),
        "queue_widget": ("queue_widget", "QueueWidget", "Cola de postulaciones"),
        "accounts_widget": ("accounts_widget", "AccountsWidget", "Mis cuentas laborales"),
        "notifications_widget": ("notifications_widget", "NotificationsWidget", "Gestor de CAPTCHA y notificaciones"),
    }
    SMOKE_CONTROLS = {"transport", "headless", "run_button", "table", "output", "status"}

    def __getattr__(self, name):
        if name in self.TOOLS:
            return self.tool(name)
        if name in self.SMOKE_CONTROLS:
            self._create_smoke_panel()
            return getattr(self, name)
        raise AttributeError(name)

    def tool(self, name):
        from importlib import import_module
        if name in self._tools:
            return self._tools[name]
        module, factory, _ = self.TOOLS[name]
        args = (self.settings, self.queue_widget) if name == "notifications_widget" else (self.settings,)
        widget = getattr(import_module("autojob.ui." + module), factory)(*args)
        widget.setParent(self.tabs)
        self._tools[name] = widget
        self.shell.original_widgets.append(widget)
        if name == "jobs_widget":
            widget.timer.stop()
            saved = self.shell.engine.store.config().get("search")
            if saved:
                widget.keywords.setPlainText("\n".join(saved["queries"]))
                if saved["limit"] is not None:
                    widget.limit.setValue(saved["limit"])
                widget.frequency.setValue(saved.get("hours", 0))
                for source, box in widget.sources.items():
                    box.setChecked(source in saved["sources"])
                widget.timer.stop()
            widget.frequency.valueChanged.disconnect(widget.schedule)
        if name == "notifications_widget":
            widget.silent_mode = widget.coordinated = True
            widget.tray.hide()
        if name in {"jobs_widget", "compatibility_widget", "recommendations_widget", "preparation_widget"}:
            from autojob.ui.queue_widget import connect_source
            connect_source(self, widget, preparation=name == "preparation_widget")
        if name == "review_widget":
            widget.changed.connect(self._refresh_recommendations)
        return widget

    def switch_person(self,person_id):
        if person_id==self.person["id"]:
            return True
        if not self.shell.can_change_person():
            self.shell.home.status.setText("Termina o pausa el trabajo y espera a que finalice el autorrelleno antes de cambiar de persona.")
            return False
        for widget in self._tools.values():
            check=getattr(widget,"allow_close",None) or getattr(widget,"allow_discard",None)
            if check and not check():
                return False
        from autojob.manual_search import ManualSearch
        try:
            person=self.people.get(person_id)
            settings=self.people.settings_for(person_id)
            engine=ManualSearch(settings)
            self.shell.extension_fill.retire()
            self.people.select(person_id)
        except Exception as exc:
            self.shell.extension_fill.retired=False
            self.shell.home.status.setText(str(exc) if isinstance(exc,ValueError) else "No se pudo abrir el espacio de esa persona.")
            return False

        old_shell=self.shell
        old_tabs=self.tabs
        old_tools=self._tools
        old_person=self.person
        old_settings=self.settings
        old_page=old_shell.main.currentIndex()
        old_central=self.takeCentralWidget()
        old_shell.finish_close()
        try:
            self.settings=settings
            self.person=person
            self.database=engine.jobs.db
            for name in self.SMOKE_CONTROLS:
                self.__dict__.pop(name,None)
            self._create_workspace(engine)
            self.shell.main.setCurrentIndex(old_page)
        except Exception:
            # Recuperar el espacio anterior si falla la creación de la nueva interfaz.
            failed=self.takeCentralWidget()
            if failed:failed.deleteLater()
            self.people.select(old_person["id"])
            self.settings=old_settings
            self.person=old_person
            self.database=old_shell.engine.jobs.db
            self.shell=old_shell
            self._tools=old_tools
            self.tabs=old_tabs
            self.main_tabs=old_shell.main
            self.setCentralWidget(old_central)
            old_shell.close_requested=False
            old_shell.manual_browser.stop.clear()
            old_shell.extension_fill.retired=False
            if old_shell.extension_fill.paired:
                try:old_shell.extension_fill.start()
                except OSError:pass
            self.set_section_background(old_page)
            old_shell.timer.start()
            old_shell.session_timer.start()
            old_shell.request_refresh()
            old_shell.home.status.setText("No se pudo cambiar de persona. Tu selección anterior sigue activa.")
            return False

        for dialog in old_shell._dialogs:
            dialog.reject()
            dialog.deleteLater()
        if old_shell._center:old_shell._center.deleteLater()
        if old_shell._identity_widget:old_shell._identity_widget.deleteLater()
        old_central.deleteLater()
        old_tabs.deleteLater()
        old_shell.deleteLater()
        return True

    def _refresh_recommendations(self):
        for name in ("compatibility_widget", "recommendations_widget"):
            if name in self._tools:
                self._tools[name].refresh()

    def _create_smoke_panel(self):
        settings = self.settings
        container = QWidget(self.tabs)
        self.shell.original_widgets.append(container)
        layout = QVBoxLayout(container)
        heading = QLabel("Job Hunting  /  Laboratorio de navegación")
        heading.setStyleSheet("font-size:26px;font-weight:700;padding:12px 0")
        layout.addWidget(heading)
        layout.addWidget(QLabel("Modo prueba · Perfil exclusivo de Brave · Sin postulaciones reales"))
        self.status = QLabel("Listo para comprobar Brave con un formulario local.")
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.transport = QComboBox()
        self.transport.addItems(["persistent", "cdp"])
        self.transport.setCurrentText(settings.browser_transport)
        row.addWidget(QLabel("Conexión:"))
        row.addWidget(self.transport)
        self.headless = QCheckBox("Ejecutar sin ventana de Brave")
        self.headless.setChecked(settings.headless)
        row.addWidget(self.headless)
        self.run_button = QPushButton("Probar Brave")
        self.run_button.clicked.connect(self.start_smoke)
        row.addWidget(self.run_button)
        layout.addLayout(row)
        actions = QHBoxLayout()
        save = QPushButton("Guardar configuración")
        save.clicked.connect(self.save_settings)
        actions.addWidget(save)
        folder = QPushButton("Abrir evidencias")
        folder.clicked.connect(self.open_evidence)
        actions.addWidget(folder)
        refresh = QPushButton("Actualizar historial")
        refresh.clicked.connect(self.refresh)
        actions.addWidget(refresh)
        layout.addLayout(actions)
        layout.addWidget(QLabel("Historial de pruebas locales — no son postulaciones"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Inicio (UTC)", "Prueba", "Estado", "ID"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Aquí aparecerá el resultado y la ruta de las evidencias.")
        layout.addWidget(self.output)
        layout.addWidget(QLabel("Gestión de CV disponible en Mis currículums. Búsqueda y envío automático aún no implementados."))
        self.refresh()
    def _background_stylesheet(self, _image_path=None):
        stylesheet = """
            QWidget { color: #f0f0f0; font: 14px 'Segoe UI'; }
            QDialog, QMessageBox, QMenu { background: #212121; }
            QTabBar::tab { background: #242424; padding: 9px 16px; color: #d4d4d4; }
            QTabBar::tab:selected { background: #383838; color: #ffffff; }
            QTabBar::tab:hover:!selected { background: #303030; }
            QPushButton, QComboBox, QSpinBox, QLineEdit, QPlainTextEdit, QTextEdit, QTableWidget {
                background: #2b2b2b; padding: 8px; border: 1px solid #484848; border-radius: 6px;
            }
            QPushButton:hover { background: #383838; }
            QPushButton:pressed { background: #464646; }
            QPushButton:disabled { color: #999999; background: #252525; }
            QPushButton#primaryAction { background: #e6e6e6; color: #181818; font-size: 16px; font-weight: 700; }
            QPushButton#primaryAction:hover { background: #ffffff; }
            QPushButton#primaryAction:pressed { background: #bfbfbf; }
            QPushButton#primaryAction:disabled { background: #363636; color: #a3a3a3; }
            QFrame#summaryCard { background: #252525; border: 1px solid #383838; border-radius: 10px; }
            QLabel#summaryCard, QLabel#statusPanel { background: rgba(37,37,37,235); padding: 14px; border-radius: 8px; }
            QHeaderView::section { background: #363636; color: #eeeeee; padding: 8px; border: 0; }
            QTableWidget { gridline-color: #383838; selection-background-color: #4a4a4a; }
            QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget, QTabWidget::pane {
                background: transparent; border: 0;
            }
        """

        mode=self.panel_mode
        if mode=="opaque":
            return stylesheet
        fill="transparent" if mode=="background" else "rgba(38,38,38,125)"
        header="transparent" if mode=="background" else "rgba(45,45,45,150)"
        return stylesheet + """
            QTableView, QTreeView, QListView, QTextEdit, QPlainTextEdit,
            QLabel#summaryCard, QLabel#statusPanel, QFrame#summaryCard {
                background: PANEL_FILL;
            }
            QTableView::item, QTreeView::item, QListView::item { background: transparent; }
            QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {
                background: rgba(90,105,125,160); color: white;
            }
            QHeaderView, QHeaderView::section { background: HEADER_FILL; }
            QAbstractScrollArea::corner { background: HEADER_FILL; }
        """.replace("PANEL_FILL",fill).replace("HEADER_FILL",header)

    def set_panel_mode(self,mode):
        self.appearance.save(mode)
        self.panel_mode=mode
        self.setStyleSheet(self._background_stylesheet())
        self.update()

    def set_section_background(self, index):
        if not 0 <= index < len(self.section_backgrounds):
            return
        path = self.section_backgrounds[index]
        if path == self._background_path:
            return
        self._background_cache = {p: pixmap for p, pixmap in self._background_cache.items() if p in self.section_backgrounds}
        if path not in self._background_cache:
            self._background_cache[path] = QPixmap(str(path)) if path else QPixmap()
        self._background_transition.stop()
        self._previous_background = self._background
        self._background = self._background_cache[path]
        self._background_path = path
        if self.isVisible() and not self._previous_background.isNull():
            self._background_transition.start()
        else:
            self._finish_background()

    def _blend_background(self, opacity):
        self._background_opacity = opacity
        self.update()

    def _finish_background(self):
        self._previous_background = QPixmap()
        self._blend_background(1.0)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#191919"))
        if not self._previous_background.isNull():
            painter.drawPixmap(self.rect(), self._previous_background)
        painter.setOpacity(self._background_opacity)
        if not self._background.isNull():
            painter.drawPixmap(self.rect(), self._background)

    def selected_settings(self):
        return replace(self.settings, browser_transport=self.transport.currentText(), headless=self.headless.isChecked())

    def save_settings(self):
        try:
            self.settings = self.selected_settings()
            self.settings.save()
            self.people.settings=replace(self.settings,data_dir=self.settings.installation_data_dir or self.settings.data_dir,installation_data_dir=None)
            self.installation_settings=self.people.settings
            self.status.setText("Configuración guardada.")
        except Exception as exc:
            QMessageBox.critical(self, "Configuración", str(exc))

    def start_smoke(self):
        if self.worker and self.worker.isRunning():
            return
        self.run_button.setEnabled(False)
        self.status.setText("Probando Brave; espera al cierre y reapertura del perfil…")
        self.worker = SmokeWorker(self.selected_settings())
        self.worker.completed.connect(self.on_completed)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_completed(self, result):
        self.output.setPlainText(result)
        self.status.setText("Prueba completada: recepción local y reapertura verificadas.")

    def on_failed(self, message):
        self.output.setPlainText(message)
        self.status.setText("La prueba falló. Consulta el resultado y data/logs/job-hunting.log.")

    def on_finished(self):
        self.run_button.setEnabled(True)
        self.refresh()

    def refresh(self):
        rows = self.database.recent_runs()
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, key in enumerate(("started_at", "kind", "status", "id")):
                self.table.setItem(index, column, QTableWidgetItem(str(row[key])))
        self.table.resizeColumnsToContents()

    def open_evidence(self):
        path = self.settings.data_path / "evidence"
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))

    def closeEvent(self, event):
        resume = self._tools.get("resumes_widget")
        if (self.worker and self.worker.isRunning()) or (resume and resume.worker and resume.worker.isRunning()):
            self.shell.home.status.setText("Espera a que termine la operación antes de cerrar la ventana.")
            event.ignore()
            return
        if not self.shell.allow_close():
            event.ignore()
            return
        for widget in self._tools.values():
            check = getattr(widget, "allow_close", None) or getattr(widget, "allow_discard", None)
            if check and not check():
                self.shell.close_requested = False
                self.shell.timer.start()
                event.ignore()
                return
        if self.shell.delivery_authorization:
            from autojob.forms.execution import close_execution
            from autojob.forms.submissions import SubmissionStore
            close_execution(SubmissionStore(self.settings.data_path), self.shell.delivery_authorization)
        self.shell.finish_close()
        event.accept()


def launch(settings):
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("com.jobhunting.desktop")
        except (AttributeError, OSError):
            pass
    app = QApplication.instance() or QApplication([])
    app.setApplicationDisplayName("Job Hunting")
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in {
        "Window": "#212121", "WindowText": "#f0f0f0", "Base": "#242424",
        "AlternateBase": "#2e2e2e", "Text": "#f0f0f0", "Button": "#303030",
        "ButtonText": "#f0f0f0", "Highlight": "#4a4a4a", "HighlightedText": "#ffffff",
        "PlaceholderText": "#a5a5a5", "Link": "#b8d1f5",
    }.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#999999"))
    app.setPalette(palette)
    icon_path = settings.root / "job_hunting.ico"
    app_icon = QIcon(str(icon_path)) if icon_path.is_file() else QIcon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    window = MainWindow(settings)
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.show()
    return app.exec()
