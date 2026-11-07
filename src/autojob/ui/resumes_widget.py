import json
import os
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget

from autojob.resumes.models import DuplicateResume, FIELD_LABELS, LANGUAGES, ResumeError, SCALAR_FIELDS, SPECIALTIES
from autojob.resumes.selection import ResumeSelector
from autojob.resumes.service import ResumeLibrary


class ImportWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    duplicate = Signal(str)

    def __init__(self, data_path, source, replace_id=None, revision=None):
        super().__init__()
        self.data_path, self.source, self.replace_id, self.revision = data_path, source, replace_id, revision

    def run(self):
        try:
            library = ResumeLibrary(self.data_path)
            self.completed.emit(library.import_document(self.source, self.replace_id, self.revision))
        except DuplicateResume as exc:
            self.duplicate.emit(exc.resume_id)
        except ResumeError as exc:
            self.failed.emit(str(exc))
        except Exception:
            # No registrar excepciones ni documentos de usuario.
            self.failed.emit("No se pudo importar el documento. Comprueba permisos y espacio disponible.")


class ReprocessWorker(ImportWorker):
    def run(self):
        try:
            library = ResumeLibrary(self.data_path)
            self.completed.emit(library.reprocess(self.replace_id, self.revision))
        except ResumeError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("No se pudo reprocesar. Se conservaron los datos anteriores.")


def combo(values, auto=False):
    widget = QComboBox()
    if auto:
        widget.addItem("Detectar por el texto", "auto")
    for key, label in values.items():
        widget.addItem(label, key)
    return widget


class ResumeWidget(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.library = ResumeLibrary(settings.data_path)
        self.selector = ResumeSelector(self.library)
        self.worker = None
        self.current = None
        self._loading = False
        self._dirty = False
        layout = QVBoxLayout(self)
        heading = QLabel("Mis currículums")
        heading.setStyleSheet("font-size:25px;font-weight:700;padding:8px 0")
        layout.addWidget(heading)
        subtitle = QLabel("PDF y DOCX · Extracción local · Revisa los datos antes de habilitar la selección automática")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        actions = QHBoxLayout()
        self.import_button = QPushButton("Importar CV")
        self.import_button.clicked.connect(self.choose_import)
        self.replace_button = QPushButton("Sustituir documento")
        self.replace_button.clicked.connect(self.choose_replace)
        self.delete_button = QPushButton("Eliminar")
        self.delete_button.clicked.connect(self.confirm_delete)
        self.default_button = QPushButton("Hacer predeterminado")
        self.default_button.clicked.connect(self.set_default)
        self.open_button = QPushButton("Abrir original")
        self.open_button.clicked.connect(self.open_original)
        self.refresh_button = QPushButton("Actualizar")
        self.refresh_button.clicked.connect(self.refresh_requested)
        for button in (self.import_button, self.replace_button, self.delete_button, self.default_button, self.open_button, self.refresh_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        reprocess_row = QHBoxLayout()
        self.reprocess_button = QPushButton("Reprocesar sin perder correcciones")
        self.reprocess_button.clicked.connect(self.start_reprocess)
        reprocess_row.addWidget(self.reprocess_button)
        reprocess_note = QLabel("Nuevo análisis por posiciones y bloques. Los datos manuales se conservan.")
        reprocess_note.setWordWrap(True)
        reprocess_row.addWidget(reprocess_note)
        layout.addLayout(reprocess_row)
        self.message = QLabel("Importa tus CV. Los datos no identificados se muestran como Desconocido.")
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.message)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Currículum", "Idioma", "Especialidad", "Revisión", "Preferido", "Versiones"])
        self.table.setMaximumHeight(140)
        self.table.setMinimumHeight(85)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        splitter.addWidget(self.table)
        self.detail_tabs = QTabWidget()
        self._build_editor()
        self.source = QPlainTextEdit()
        self.source.setReadOnly(True)
        self.detail_tabs.addTab(self.source, "Texto y fuentes")
        self.audit = QPlainTextEdit()
        self.audit.setReadOnly(True)
        self.detail_tabs.addTab(self.audit, "Extracción y versiones")
        self._build_selection()
        from autojob.ui.resume_records import RecordEditor
        self.record_editor = RecordEditor()
        self.record_editor.changed.connect(self.mark_dirty)
        records_page = QWidget()
        records_layout = QVBoxLayout(records_page)
        records_layout.addWidget(self.record_editor)
        records_save = QPushButton("Guardar correcciones y registros")
        records_save.clicked.connect(self.save_current)
        records_layout.addWidget(records_save)
        self.detail_tabs.addTab(records_page, "Registros estructurados")
        splitter.addWidget(self.detail_tabs)
        splitter.setSizes([180, 420])
        layout.addWidget(splitter)
        self.refresh()

    def _build_editor(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        self.title = QLineEdit()
        self.title.setMaxLength(200)
        self.language = combo(LANGUAGES)
        self.specialty = combo(SPECIALTIES)
        form.addRow("Nombre de esta versión", self.title)
        form.addRow("Idioma del documento", self.language)
        form.addRow("Especialidad", self.specialty)
        note = QLabel("Vacío = Desconocido. En las listas, escribe una entrada por línea.\nLas correcciones se conservan separadas de la extracción original.")
        note.setWordWrap(True)
        form.addRow(note)
        self.fields = {}
        self.field_labels = {}
        for key, label in FIELD_LABELS.items():
            if key in SCALAR_FIELDS:
                widget = QLineEdit()
                widget.setMaxLength(1000)
            else:
                widget = QPlainTextEdit()
                widget.setFixedHeight(74)
            widget.setPlaceholderText("Desconocido")
            widget.textChanged.connect(lambda *_, key=key: self.field_changed(key))
            self.fields[key] = widget
            if key in {"experience", "education", "academic_projects"}:
                widget.setParent(body)
                widget.hide()
            else:
                self.field_labels[key] = QLabel(label)
                form.addRow(self.field_labels[key], widget)
        structured_note = QLabel("Experiencia, educación y proyectos se editan por registro en la pestaña Registros estructurados. El texto corregido previamente se conserva allí como referencia.")
        structured_note.setWordWrap(True)
        form.addRow(structured_note)
        self.reviewed = QCheckBox("He revisado los datos, el idioma y la especialidad de este CV")
        form.addRow(self.reviewed)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        self.save_button = QPushButton("Guardar correcciones")
        self.save_button.clicked.connect(self.save_current)
        layout.addWidget(self.save_button)
        for widget in (self.title,):
            widget.textChanged.connect(self.mark_dirty)
        self.language.currentIndexChanged.connect(self.mark_dirty)
        self.specialty.currentIndexChanged.connect(self.mark_dirty)
        self.reviewed.toggled.connect(self.mark_dirty)
        self.editor_page = page
        self.detail_tabs.addTab(page, "Revisar y corregir")

    def _build_selection(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Prueba local de selección. No busca vacantes ni envía postulaciones."))
        self.vacancy = QPlainTextEdit()
        self.vacancy.setPlaceholderText("Pega el título y la descripción de una vacante o escribe Junior Python Developer…")
        self.vacancy.setMaximumHeight(130)
        layout.addWidget(self.vacancy)
        form = QFormLayout()
        self.job_language = combo({"es": "Español", "en": "Inglés"}, auto=True)
        self.job_specialty = combo({"technical": "Técnico", "customer_service": "Customer Service"}, auto=True)
        form.addRow("Idioma del CV solicitado", self.job_language)
        form.addRow("Tipo de vacante", self.job_specialty)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.select_button = QPushButton("Probar selección")
        self.select_button.clicked.connect(self.test_selection)
        rules_button = QPushButton("Configurar reglas")
        rules_button.clicked.connect(self.edit_rules)
        row.addWidget(self.select_button)
        row.addWidget(rules_button)
        layout.addLayout(row)
        self.selection_result = QPlainTextEdit()
        self.selection_result.setReadOnly(True)
        layout.addWidget(self.selection_result)
        self.detail_tabs.addTab(page, "Probar selección automática")

    def mark_dirty(self, *_):
        if not self._loading:
            self._dirty = True

    def field_changed(self, key):
        if not self._loading:
            self.mark_dirty()
            if key in self.field_labels:
                self.field_labels[key].setText(FIELD_LABELS[key] + " · Manual")
                self.fields[key].setStyleSheet("border-left:3px solid #67dfad;padding:4px")

    def allow_discard(self):
        if not self._dirty:
            return True
        answer = QMessageBox.question(self, "Cambios sin guardar", "Hay correcciones sin guardar. ¿Quieres descartarlas?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def refresh_requested(self):
        if self.allow_discard():
            self._dirty = False
            self.refresh(self.current["id"] if self.current else None)

    def refresh(self, selected_id=None):
        self.table.blockSignals(True)
        rows = self.library.list()
        self.table.setRowCount(len(rows))
        selected_row = None
        for index, item in enumerate(rows):
            values = [item["title"], LANGUAGES[item["language"]], SPECIALTIES[item["specialty"]], "Revisado" if item["reviewed"] else "Por revisar", "Sí" if item["is_default"] else "", str(item["version_count"])]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.ItemDataRole.UserRole, item["id"])
                self.table.setItem(index, column, cell)
            if item["id"] == selected_id:
                selected_row = index
        self.table.resizeColumnsToContents()
        for column, width in [(1, 95), (2, 145), (3, 110), (4, 85), (5, 85)]:
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.blockSignals(False)
        if selected_row is None and rows:
            selected_row = 0
        if selected_row is not None:
            self.table.selectRow(selected_row)
            self.load_record(rows[selected_row]["id"])
        else:
            self.current = None
            self.clear_editor()
        self._dirty = False
        self.update_buttons()

    def clear_editor(self):
        self._loading = True
        self.title.clear()
        for widget in self.fields.values():
            widget.clear()
        self.source.clear()
        self.audit.clear()
        self.reviewed.setChecked(False)
        self.record_editor.clear()
        self._loading = False

    def selection_changed(self):
        selected = self.table.selectedItems()
        if not selected:
            return
        resume_id = selected[0].data(Qt.ItemDataRole.UserRole)
        if self.current and self.current["id"] == resume_id:
            return
        if not self.allow_discard():
            self.table.blockSignals(True)
            for row in range(self.table.rowCount()):
                if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == self.current["id"]:
                    self.table.selectRow(row)
                    break
            self.table.blockSignals(False)
            return
        self.load_record(resume_id)

    def load_record(self, resume_id):
        try:
            item = self.library.get(resume_id)
        except ResumeError as exc:
            self.message.setText(str(exc))
            return
        self._loading = True
        self.current = item
        self.title.setText(item["title"])
        self.language.setCurrentIndex(self.language.findData(item["language"]))
        self.specialty.setCurrentIndex(self.specialty.findData(item["specialty"]))
        self.reviewed.setChecked(bool(item["reviewed"]))
        for key, widget in self.fields.items():
            value = item["fields"][key]
            if key in SCALAR_FIELDS:
                widget.setText(value or "")
            else:
                widget.setPlainText("\n".join(value))
            manual = item["provenance"][key] == "manual"
            widget.setStyleSheet("border-left:3px solid " + ("#67dfad" if manual else "#80aaff") + ";padding:4px")
            if key in self.field_labels:
                self.field_labels[key].setText(FIELD_LABELS[key] + (" · Manual" if manual else " · Automático"))
            citations = item["latest_analysis"].get("evidence", {}).get(key, [])
            widget.setToolTip("\n".join(f"{e['location']}: {e['text']}" for e in citations) or "Sin fuente automática; comprueba el documento.")
        self.record_editor.load(item)
        self.source.setPlainText("\n\n".join(f"[{unit['location']}]\n{unit['text']}" for unit in item["source_units"]) or "Sin texto extraíble. Completa los datos manualmente si puedes verificarlos.")
        analysis = item["latest_analysis"]
        lines = ["ANÁLISIS AUTOMÁTICO ACTUAL", "Las correcciones se guardan por separado. La primera extracción sigue conservada en el historial.", ""]
        for key, label in FIELD_LABELS.items():
            value = analysis["fields"].get(key)
            text = ("; ".join(value) if isinstance(value, list) else value) or "Desconocido"
            lines.append(f"{label}: {text}")
            locations = list(dict.fromkeys(entry["location"] for entry in analysis["evidence"].get(key, [])))
            if locations:
                lines.append("  Fuentes: " + "; ".join(locations))
        lines.extend(["", "VERSIONES CONSERVADAS", "Al sustituir un documento, vuelve a revisar los datos extraídos."])
        for version in self.library.versions(resume_id):
            active = " · Documento activo" if version["id"] == item["current_version"] else " · Versión anterior"
            lines.append(f"{version['filename']} · {version['created_at']}{active}")
        self.audit.setPlainText("\n".join(lines))
        warnings = item["latest_analysis"]["warnings"]
        if item["manual_fields"]:
            warnings = ["Correcciones manuales conservadas: " + ", ".join(FIELD_LABELS[key] for key in item["manual_fields"])] + warnings
        self.message.setText(" · ".join(warnings) if warnings else "Documento importado. Revisa los datos extraídos y guarda tu revisión.")
        self._loading = False
        self._dirty = False
        self.update_buttons()

    def update_buttons(self):
        busy = self.worker is not None and self.worker.isRunning()
        self.import_button.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        for button in (self.replace_button, self.delete_button, self.default_button, self.open_button, self.save_button, self.reprocess_button):
            button.setEnabled(self.current is not None and not busy)
        self.editor_page.setEnabled(self.current is not None and not busy)
        self.table.setEnabled(not busy)
        self.record_editor.setEnabled(self.current is not None and not busy)

    def start_reprocess(self):
        if not self.current or (self.worker and self.worker.isRunning()):
            return
        # Guardar primero las correcciones en edición; si hay conflicto no continuar.
        if self._dirty:
            self.save_current()
            if self._dirty:
                return
        self.worker = ReprocessWorker(self.settings.data_path, None, self.current["id"], self.current["revision"])
        self.worker.completed.connect(self.reprocess_completed)
        self.worker.failed.connect(self.import_failed)
        self.worker.finished.connect(self.update_buttons)
        self.message.setText("Reprocesando el original. Se conservarán las correcciones manuales…")
        self.worker.start()
        self.update_buttons()

    def reprocess_completed(self, item):
        self.refresh(item["id"])
        self.message.setText("Reprocesamiento completado. Correcciones conservadas; revisa los nuevos registros y sus advertencias.")

    def choose_import(self):
        if not self.allow_discard():
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Importar currículum", "", "Currículums (*.pdf *.docx)")
        if filename:
            self.start_import(Path(filename))

    def choose_replace(self):
        if not self.current or not self.allow_discard():
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Sustituir documento (se conservará la versión anterior)", "", "Currículums (*.pdf *.docx)")
        if filename:
            self.start_import(Path(filename), self.current["id"], self.current["revision"])

    def start_import(self, source, replace_id=None, revision=None):
        if self.worker and self.worker.isRunning():
            return
        self._dirty = False
        self.worker = ImportWorker(self.settings.data_path, source, replace_id, revision)
        self.worker.completed.connect(self.import_completed)
        self.worker.failed.connect(self.import_failed)
        self.worker.duplicate.connect(self.import_duplicate)
        self.worker.finished.connect(self.update_buttons)
        self.message.setText("Importando y analizando el documento localmente…")
        self.worker.start()
        self.update_buttons()

    def import_completed(self, item):
        self.refresh(item["id"])
        self.message.setText("CV importado. Revisa los campos, el idioma y la especialidad. " + " · ".join(item["original_analysis"]["warnings"]))

    def import_failed(self, message):
        self.message.setText(message)

    def import_duplicate(self, resume_id):
        self.refresh(resume_id)
        self.message.setText("Documento duplicado: ya existe en esta biblioteca o en su historial de versiones.")

    def save_current(self):
        if not self.current:
            return
        fields = {}
        for key, widget in self.fields.items():
            if key in SCALAR_FIELDS:
                fields[key] = widget.text().strip() or None
            else:
                fields[key] = [line.strip() for line in widget.toPlainText().splitlines() if line.strip()]
        try:
            item = self.library.update(self.current["id"], title=self.title.text(), language=self.language.currentData(), specialty=self.specialty.currentData(), fields=fields, reviewed=self.reviewed.isChecked(), expected_revision=self.current["revision"], structure=self.record_editor.value())
            self._dirty = False
            self.refresh(item["id"])
            self.message.setText("Correcciones guardadas. " + ("CV habilitado para selección." if item["reviewed"] else "CV pendiente de revisión."))
        except ResumeError as exc:
            self.message.setText(str(exc))

    def set_default(self):
        if self.current:
            try:
                self.library.set_default(self.current["id"])
                # No recargar el editor: podría contener correcciones sin guardar.
                self.message.setText("Predeterminado guardado. Solo se usará si está revisado y es compatible.")
                for row in range(self.table.rowCount()):
                    selected = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == self.current["id"]
                    self.table.item(row, 4).setText("Sí" if selected else "")
            except ResumeError as exc:
                self.message.setText(str(exc))

    def confirm_delete(self):
        if not self.current:
            return
        answer = QMessageBox.question(self, "Eliminar currículum", "¿Eliminar este CV, sus datos y todas sus versiones de Job Hunting? El archivo externo que importaste se conserva.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            pending = self.library.delete(self.current["id"], self.current["revision"])
            self._dirty = False
            self.current = None
            self.refresh()
            self.message.setText("Currículum eliminado." if not pending else "Datos eliminados. Algunas copias siguen bloqueadas por otro programa; ciérralo para poder retirarlas de data/resumes.")
        except ResumeError as exc:
            self.message.setText(str(exc))

    def open_original(self):
        if self.current:
            try:
                os.startfile(str(self.library.original_path(self.current["id"])))
            except (ResumeError, OSError):
                self.message.setText("No se pudo abrir la copia original. Revisa su disponibilidad y la aplicación asociada.")

    def test_selection(self):
        try:
            result = self.selector.select(self.vacancy.toPlainText(), self.job_language.currentData(), self.job_specialty.currentData())
            title = self.library.get(result.resume_id)["title"] if result.resume_id else "Pendiente de selección"
            self.selection_result.setPlainText(f"{title}\n\n{result.reason}\nIdioma: {LANGUAGES[result.language]}\nEspecialidad: {SPECIALTIES[result.specialty]}")
        except ResumeError as exc:
            self.selection_result.setPlainText(str(exc))

    def edit_rules(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Reglas locales de selección")
        dialog.resize(650, 480)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Una palabra o frase por línea. Se comparan términos completos, sin distinguir mayúsculas."))
        editors = {}
        try:
            rules = self.selector.load_rules()
        except ResumeError:
            from autojob.resumes.analysis import DEFAULT_RULES
            rules = DEFAULT_RULES
        form = QFormLayout()
        for key, label in [("technical", "Técnico"), ("customer_service", "Customer Service")]:
            editor = QPlainTextEdit("\n".join(rules[key]))
            editors[key] = editor
            form.addRow(label, editor)
        layout.addLayout(form)
        error = QLabel()
        error.setWordWrap(True)
        layout.addWidget(error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(dialog.reject)

        def save():
            try:
                self.selector.save_rules({key: [line.strip() for line in editor.toPlainText().splitlines() if line.strip()] for key, editor in editors.items()})
                dialog.accept()
            except (ResumeError, OSError) as exc:
                error.setText(str(exc) if isinstance(exc, ResumeError) else "No se pudieron guardar las reglas.")

        buttons.accepted.connect(save)
        layout.addWidget(buttons)
        dialog.exec()
