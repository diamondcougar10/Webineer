from __future__ import annotations

import os
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWebEngineWidgets import QWebEngineView

from ..core.models import Project, Page
from ..core import storage, generator

APP_TITLE = "PyQt Site Builder"

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1220, 780)

        # State
        self.project: Optional[Project] = None
        self.project_path: Optional[Path] = None
        self._preview_tmp: Optional[str] = None
        self._debounce = QtCore.QTimer(self)
        self._debounce.setInterval(400)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self.update_preview)

        # UI
        self._build_ui()
        self._build_menu()
        self._bind_events()

        # Start with an empty project
        self.new_project_bootstrap()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        splitter = QtWidgets.QSplitter(self)
        splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # Left: pages list + buttons
        left = QtWidgets.QWidget(self)
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(6,6,6,6)
        left_layout.setSpacing(6)

        self.pages_list = QtWidgets.QListWidget(left)
        self.pages_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)

        btn_bar = QtWidgets.QHBoxLayout()
        self.btn_add_page = QtWidgets.QPushButton("Add Page")
        self.btn_remove_page = QtWidgets.QPushButton("Remove Page")
        btn_bar.addWidget(self.btn_add_page)
        btn_bar.addWidget(self.btn_remove_page)

        left_layout.addWidget(QtWidgets.QLabel("Pages"))
        left_layout.addWidget(self.pages_list, 1)
        left_layout.addLayout(btn_bar)

        # Middle: editors (HTML + CSS)
        mid = QtWidgets.QTabWidget(self)
        mid.setDocumentMode(True)
        self.html_editor = QtWidgets.QPlainTextEdit(mid)
        self.html_editor.setPlaceholderText("<h2>Hello</h2>\n<p>Edit your page HTML here.</p>")
        self.css_editor = QtWidgets.QPlainTextEdit(mid)
        self.css_editor.setPlaceholderText("/* Global site CSS lives here */")
        mid.addTab(self.html_editor, "Page HTML")
        mid.addTab(self.css_editor, "Styles (CSS)")

        # Right: preview
        right = QtWidgets.QWidget(self)
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(6,6,6,6)
        right_layout.setSpacing(6)

        self.preview = QWebEngineView(right)
        right_layout.addWidget(QtWidgets.QLabel("Preview"))
        right_layout.addWidget(self.preview, 1)

        splitter.addWidget(left)
        splitter.addWidget(mid)
        splitter.addWidget(right)
        splitter.setSizes([220, 520, 480])

        self.status = self.statusBar()

    def _build_menu(self) -> None:
        bar = self.menuBar()
        if bar is None:
            bar = QtWidgets.QMenuBar(self)
            self.setMenuBar(bar)

        # File
        m_file = bar.addMenu("&File")
        act_new = QtGui.QAction("New Project", self)
        act_open = QtGui.QAction("Open Projectâ€¦", self)
        act_save = QtGui.QAction("Save", self)
        act_save_as = QtGui.QAction("Save Asâ€¦", self)
        act_export = QtGui.QAction("Export Siteâ€¦", self)
        act_quit = QtGui.QAction("Quit", self)
        if m_file is not None:
            m_file.addActions([act_new, act_open])
            m_file.addSeparator()
            m_file.addActions([act_save, act_save_as])
            m_file.addSeparator()
            m_file.addAction(act_export)
            m_file.addSeparator()
            m_file.addAction(act_quit)

        self.act_new, self.act_open, self.act_save, self.act_save_as, self.act_export, self.act_quit = \
            act_new, act_open, act_save, act_save_as, act_export, act_quit

        # Help
        m_help = bar.addMenu("&Help")
        act_about = QtGui.QAction("About", self)
        if m_help is not None:
            m_help.addAction(act_about)
        self.act_about = act_about

    def _bind_events(self) -> None:
        self.btn_add_page.clicked.connect(self.add_page)
        self.btn_remove_page.clicked.connect(self.remove_page)
        self.pages_list.currentRowChanged.connect(self._on_page_selection_changed)

        self.html_editor.textChanged.connect(self._on_editor_changed)
        self.css_editor.textChanged.connect(self._on_editor_changed)

        self.act_new.triggered.connect(self.new_project_bootstrap)
        self.act_open.triggered.connect(self.open_project_dialog)
        self.act_save.triggered.connect(self.save_project)
        self.act_save_as.triggered.connect(self.save_project_as)
        self.act_export.triggered.connect(self.export_site)
        self.act_quit.triggered.connect(self.close)
        self.act_about.triggered.connect(self.show_about)

    # ---------- Project Ops ----------
    def new_project_bootstrap(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "New Project", "Site name:", text="My Site")
        if not ok or not name.strip():
            return
        self.project = Project(
            name=name.strip(),
            pages=[
                Page(filename="index.html", title="Home", html=self._default_index_html())
            ],
            css=self._default_css(),
            output_dir=None,
        )
        self.project_path = None
        self._refresh_pages_list(select_index=0)
        self.css_editor.setPlainText(self.project.css)
        self.html_editor.setPlainText(self.project.pages[0].html)
        self.update_window_title()
        self.update_preview()

    def open_project_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open Project", "", "Site Project (*.siteproj)")
        if not path:
            return
        self.project = storage.load_project(path)
        self.project_path = Path(path)
        self._refresh_pages_list(select_index=0)
        self.css_editor.setPlainText(self.project.css)
        self.html_editor.setPlainText(self.project.pages[0].html)
        self.update_window_title()
        self.update_preview()
        if self.status is not None:
            self.status.showMessage(f"Opened {os.path.basename(path)}", 3000)

    def save_project(self) -> None:
        if self.project is None:
            return
        self._flush_editors_to_model()
        if not self.project_path:
            return self.save_project_as()
        storage.save_project(self.project_path, self.project)
        if self.status is not None:
            self.status.showMessage("Project saved", 2000)

    def save_project_as(self) -> None:
        if self.project is None:
            return
        self._flush_editors_to_model()
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Project As", "", "Site Project (*.siteproj)")
        if not path:
            return
        if not path.endswith(".siteproj"):
            path += ".siteproj"
        storage.save_project(path, self.project)
        self.project_path = Path(path)
        self.update_window_title()
        if self.status is not None:
            self.status.showMessage(f"Saved {os.path.basename(path)}", 3000)

    def export_site(self) -> None:
        if self.project is None:
            return
        self._flush_editors_to_model()
        out_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Export Site Toâ€¦")
        if not out_dir:
            return
        templates_dir = Path(__file__).resolve().parent.parent / "core" / "templates"
        generator.render_site(self.project, out_dir, templates_dir)
        if self.status is not None:
            self.status.showMessage(f"Exported site to {out_dir}", 5000)
        QtWidgets.QMessageBox.information(self, "Export complete", f"Your site was exported to:\n{out_dir}")

    # ---------- Pages ----------
    def add_page(self) -> None:
        if self.project is None:
            return
        title, ok = QtWidgets.QInputDialog.getText(self, "Add Page", "Page title:", text="About")
        if not ok or not title.strip():
            return
        slug = "-".join(title.lower().split())
        filename = f"{slug}.html" if slug != "index" else "index.html"
        # Avoid duplicates
        existing = {p.filename for p in self.project.pages}
        n = 1
        base_filename = filename
        while filename in existing:
            filename = f"{slug}-{n}.html"
            n += 1
        self.project.pages.append(Page(filename=filename, title=title.strip(), html=f"<h2>{title.strip()}</h2>\n<p>Write something awesome.</p>"))
        self._refresh_pages_list(select_index=len(self.project.pages)-1)
        self.update_preview()

    def remove_page(self) -> None:
        if self.project is None:
            return
        row = self.pages_list.currentRow()
        if row < 0 or row >= len(self.project.pages):
            return
        page = self.project.pages[row]
        if page.filename == "index.html":
            QtWidgets.QMessageBox.warning(self, "Not allowed", "You cannot remove the home page (index.html).")
            return
        del self.project.pages[row]
        self._refresh_pages_list(select_index=max(0, row-1))
        self.update_preview()

    def _refresh_pages_list(self, select_index: int = 0) -> None:
     """Refresh the left-hand Pages list and select a row."""
     self.pages_list.blockSignals(True)
     self.pages_list.clear()
     if self.project:
        for p in self.project.pages:
            self.pages_list.addItem(f"{p.title}  ({p.filename})")
     self.pages_list.blockSignals(False)

     count = self.pages_list.count()
     if count == 0:
        return
    # Clamp the selection index to [0, count-1]
     if select_index < 0:
        select_index = 0
     elif select_index >= count:
        select_index = count - 1
     self.pages_list.setCurrentRow(select_index)

    def _on_page_selection_changed(self, row: int) -> None:
        if self.project is None or row < 0 or row >= len(self.project.pages):
            return
        # Save current edits back to previously selected page
        self._flush_editors_to_model()
        # Load selected page into editor
        page = self.project.pages[row]
        self.html_editor.blockSignals(True)
        self.html_editor.setPlainText(page.html)
        self.html_editor.blockSignals(False)
        self.update_preview()

    # ---------- Editing & Preview ----------
    def _on_editor_changed(self) -> None:
        self._debounce.start()

    def _flush_editors_to_model(self) -> None:
        if self.project is None:
            return
        row = self.pages_list.currentRow()
        if row < 0 or row >= len(self.project.pages):
            return
        self.project.css = self.css_editor.toPlainText()
        self.project.pages[row].html = self.html_editor.toPlainText()

    def update_preview(self) -> None:
        if self.project is None:
            return
        # Make sure model reflects editors
        self._flush_editors_to_model()

        # Build to a temp directory
        if self._preview_tmp and os.path.isdir(self._preview_tmp):
            shutil.rmtree(self._preview_tmp, ignore_errors=True)
        self._preview_tmp = tempfile.mkdtemp(prefix="sitebuilder_preview_")
        templates_dir = Path(__file__).resolve().parent.parent / "core" / "templates"
        generator.render_site(self.project, self._preview_tmp, templates_dir)

        # Load current page into preview
        row = self.pages_list.currentRow()
        if row < 0:
            row = 0
        curr = self.project.pages[row]
        path = Path(self._preview_tmp) / curr.filename
        self.preview.setUrl(QtCore.QUrl.fromLocalFile(str(path)))

    # ---------- Misc ----------
    def show_about(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "About",
            f"{APP_TITLE}\n\nA minimal website generator and editor built with PyQt6."
        )

    def update_window_title(self) -> None:
        name = self.project.name if self.project else "Untitled"
        suffix = f" â€” {self.project_path.name}" if self.project_path else ""
        self.setWindowTitle(f"{APP_TITLE} â€” {name}{suffix}")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        # Clean preview tmp
        if self._preview_tmp and os.path.isdir(self._preview_tmp):
            shutil.rmtree(self._preview_tmp, ignore_errors=True)
        event.accept()

    # ---------- Defaults ----------
    def _default_css(self) -> str:
        return (
            "/* Global site styles */\n"
            "body { background: white; }\n"
            ".hero { background: #f5f5f5; border: 1px solid #e5e5e5; border-radius: .6rem; }\n"
            ".btn { background: #fff; }\n"
        )

    def _default_index_html(self) -> str:
        return (
            "<section class=\"hero\">\n"
            "  <h2>Welcome!</h2>\n"
            "  <p>Your new site is ready. Edit this content and export.</p>\n"
            "  <a class=\"btn\" href=\"#\">Get started</a>\n"
            "</section>\n"
            "<section>\n"
            "  <h3>Features</h3>\n"
            "  <div class=\"grid\">\n"
            "    <div><h4>Fast</h4><p>Edit and preview instantly.</p></div>\n"
            "    <div><h4>Simple</h4><p>HTML in, static site out.</p></div>\n"
            "    <div><h4>Portable</h4><p>Publish anywhere.</p></div>\n"
            "  </div>\n"
            "</section>\n"
        )

def find_templates_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "core" / "templates"
