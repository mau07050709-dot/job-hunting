from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget

from autojob.resumes.semantics import REQUIRED, STRUCTURE_KEYS

LABELS = {"company": "Empresa", "position": "Puesto", "start_date": "Fecha de inicio", "end_date": "Fecha de finalización",
    "responsibilities": "Responsabilidades (una por línea)", "description": "Descripción", "institution": "Institución",
    "degree": "Carrera o titulación", "academic_status": "Estado académico", "name": "Nombre del proyecto",
    "technologies": "Tecnologías (una por línea)"}
CATEGORIES = {"experience": "Experiencia laboral", "education": "Educación", "academic_projects": "Proyectos"}


class RecordEditor(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.structure = {key: [] for key in CATEGORIES}
        self.loading = False
        self.current_row = None
        layout = QVBoxLayout(self)
        self.legend = QLabel("Azul: extracción automática · Verde: corrección manual · Incompleto: faltan datos explícitos")
        self.legend.setWordWrap(True)
        layout.addWidget(self.legend)
        row = QHBoxLayout()
        self.category = QComboBox()
        for key, label in CATEGORIES.items(): self.category.addItem(label, key)
        self.category.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.category)
        add = QPushButton("Añadir registro")
        add.clicked.connect(self.add_record)
        remove = QPushButton("Eliminar registro")
        remove.clicked.connect(self.remove_record)
        row.addWidget(add)
        row.addWidget(remove)
        layout.addLayout(row)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Registro", "Estado", "Origen"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumWidth(260)
        self.table.setWordWrap(False)
        self.table.itemSelectionChanged.connect(self.load_selected)
        splitter.addWidget(self.table)
        self.record_tabs = QTabWidget()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.form_body = QWidget()
        self.form = QFormLayout(self.form_body)
        self.scroll.setWidget(self.form_body)
        self.scroll.setMinimumHeight(240)
        self.record_tabs.addTab(self.scroll, "Datos del registro")
        self.sources = QPlainTextEdit()
        self.sources.setReadOnly(True)
        self.sources.setPlaceholderText("La fuente y el texto original del registro aparecen aquí.")
        self.record_tabs.addTab(self.sources, "Fuente original")
        self.legacy = QPlainTextEdit()
        self.legacy.setReadOnly(True)
        self.record_tabs.addTab(self.legacy, "Correcciones anteriores")
        self.record_tabs.setTabVisible(2, False)
        splitter.addWidget(self.record_tabs)
        splitter.setSizes([340, 700])
        layout.addWidget(splitter)
        self.widgets = {}

    def load(self, item):
        self.structure = deepcopy(item["structure"])
        previous = []
        for key, label in CATEGORIES.items():
            if key in item["manual_fields"]:
                previous.append(label + " — TEXTO CORREGIDO ANTERIORMENTE, CONSERVADO:\n" + "\n".join(item["fields"][key]))
        self.legacy.setPlainText("\n\n".join(previous))
        self.record_tabs.setTabVisible(2, bool(previous))
        self.refresh()

    def clear(self):
        self.structure = {key: [] for key in CATEGORIES}
        self.legacy.clear()
        self.record_tabs.setTabVisible(2, False)
        self.refresh()

    def value(self):
        return deepcopy(self.structure)

    def refresh(self, *_):
        self.loading = True
        category = self.category.currentData()
        rows = self.structure[category]
        self.table.setRowCount(len(rows))
        for index, record in enumerate(rows):
            name = record.get("position") or record.get("degree") or record.get("name") or "Registro sin identificar"
            if record.get("company"): name += " · " + record["company"]
            values = [name, "Incompleto" if record.get("incomplete") else "Datos principales presentes", "Manual" if record.get("origin") == "manual" else "Automático"]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.table.setItem(index, column, cell)
        self.table.setColumnWidth(0, 170)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 85)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.loading = False
        if rows:
            self.table.selectRow(0)
        self.load_selected()

    def load_selected(self):
        if self.loading:
            return
        self.loading = True
        self.widgets = {}
        while self.form.rowCount(): self.form.removeRow(0)
        row_index = self.table.currentRow()
        rows = self.structure[self.category.currentData()]
        self.current_row = row_index if 0 <= row_index < len(rows) else None
        if self.current_row is None:
            self.sources.clear()
            self.loading = False
            return
        record = rows[row_index]
        for key in STRUCTURE_KEYS[self.category.currentData()]:
            multiline = key in {"responsibilities", "description", "technologies"}
            widget = QPlainTextEdit() if multiline else QLineEdit()
            value = record.get(key)
            text = "\n".join(value) if isinstance(value, list) else value or ""
            if multiline:
                widget.setMaximumHeight(85)
                widget.setPlainText(text)
            else:
                widget.setText(text)
            widget.setPlaceholderText("Desconocido")
            manual = key in record.get("manual_fields", [])
            widget.setStyleSheet("border-left:3px solid " + ("#67dfad" if manual else "#80aaff") + ";padding:5px")
            widget.setToolTip("Corrección manual" if manual else "Extraído automáticamente: contrasta con la fuente")
            widget.textChanged.connect(lambda *_, key=key: self.edit(key))
            self.form.addRow(LABELS[key] + (" · Manual" if manual else " · Auto"), widget)
            self.widgets[key] = widget
        missing = record.get("incomplete_fields", [])
        text = "Faltan: " + ", ".join(LABELS[key] for key in missing) + "\n\n" if missing else ""
        text += "FUENTE ORIGINAL\n" + record.get("raw_text", "")
        text += "\n\n" + "\n".join(f"{entry['location']}: {entry['text']}" for entry in record.get("sources", []))
        self.sources.setPlainText(text)
        self.loading = False

    def edit(self, key):
        if self.loading or self.current_row is None:
            return
        category = self.category.currentData()
        record = self.structure[category][self.current_row]
        widget = self.widgets[key]
        text = widget.toPlainText() if isinstance(widget, QPlainTextEdit) else widget.text()
        record[key] = [line.strip() for line in text.splitlines() if line.strip()] if key in {"responsibilities", "technologies"} else text.strip() or None
        record["manual_fields"] = sorted(set(record.get("manual_fields", [])) | {key})
        record["origin"] = "manual"
        record["incomplete_fields"] = [field for field in REQUIRED[category] if not record.get(field)]
        record["incomplete"] = bool(record["incomplete_fields"])
        widget.setStyleSheet("border-left:3px solid #67dfad;padding:5px")
        widget.setToolTip("Corrección manual")
        self.table.item(self.current_row, 2).setText("Manual")
        self.table.item(self.current_row, 1).setText("Incompleto" if record["incomplete"] else "Datos principales presentes")
        self.changed.emit()

    def add_record(self):
        category = self.category.currentData()
        item = {key: [] if key in {"technologies", "responsibilities"} else None for key in STRUCTURE_KEYS[category]}
        item.update(id=str(uuid4()), raw_text="", sources=[], origin="manual", manual_fields=list(STRUCTURE_KEYS[category]), incomplete=True, incomplete_fields=list(REQUIRED[category]))
        self.structure[category].append(item)
        self.refresh()
        self.table.selectRow(len(self.structure[category])-1)
        self.changed.emit()

    def remove_record(self):
        if self.current_row is not None:
            del self.structure[self.category.currentData()][self.current_row]
            self.refresh()
            self.changed.emit()
