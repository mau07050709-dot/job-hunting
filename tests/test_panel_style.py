import json
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor,QImage
from PySide6.QtWidgets import QInputDialog,QPushButton
from autojob.config import Settings
from autojob.ui.appearance import Appearance
from autojob.ui.main_window import MainWindow


def test_preference_validated_and_safe_default(tmp_path):
    store=Appearance(tmp_path)
    assert store.load()=="opaque"
    store.save("translucent")
    assert Appearance(tmp_path).load()=="translucent"
    with pytest.raises(ValueError):store.save("other")
    assert store.load()=="translucent"
    for content in ["broken",'{"panels": []}',"[]"]:
        store.path.write_text(content)
        assert store.load()=="opaque"


def test_table_pixels_show_background_and_buttons_stay_opaque(tmp_path,qt_application_lifetime,await_ui):
    window=MainWindow(Settings(tmp_path))
    window.show()
    await_ui(lambda:not window._ui_tasks)
    image=QImage(100,100,QImage.Format.Format_RGB32)
    image.fill(QColor(35,125,210))
    source=tmp_path/"blue.png"
    image.save(str(source))
    store=window.shell.background_images
    store.save(1,source)
    store.save(2,source)
    window.section_backgrounds=store.load((None,)*4)
    window.main_tabs.setCurrentIndex(1)
    window._background_transition.stop()
    window._finish_background()
    viewport=window.shell.data_view.table.viewport()
    def sample():
        qt_application_lifetime.processEvents()
        center=viewport.mapTo(window,viewport.rect().center())
        return window.grab().toImage().pixelColor(center)
    colors={}
    button_colors={}
    button=window.shell.data_view.locality_button
    for mode in ["opaque","translucent","background"]:
        window.set_panel_mode(mode)
        colors[mode]=sample()
        corner=button.mapTo(window,QPoint(15,button.height()//2))
        button_colors[mode]=window.grab().toImage().pixelColor(corner)
    assert colors["opaque"].blue()<colors["translucent"].blue()<colors["background"].blue(),colors
    assert colors["background"].blue()>190
    assert button_colors["opaque"]==button_colors["background"]==button_colors["translucent"]
    assert window.close()
    again=MainWindow(Settings(tmp_path))
    await_ui(lambda:not again._ui_tasks)
    assert again.panel_mode=="background"
    assert again.close()


def test_config_button_and_person_switch_preserve_local_preference(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    window=MainWindow(Settings(tmp_path))
    await_ui(lambda:not window._ui_tasks)
    assert window.shell.empty_configuration.findChild(QPushButton,"panel_style_button")
    monkeypatch.setattr(QInputDialog,"getItem",lambda *a:("Gris transparente",True))
    window.shell.choose_panel_style()
    assert window.panel_mode=="translucent"
    other=window.people.create("Otra")
    assert window.switch_person(other["id"])
    await_ui(lambda:not window._ui_tasks)
    assert window.panel_mode=="translucent"
    assert "Gris transparente" in window.shell.panel_style_status.text()
    assert window.close()
