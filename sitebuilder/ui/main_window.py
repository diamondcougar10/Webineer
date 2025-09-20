"""Main application window for the site builder."""

from __future__ import annotations

import os
from typing import cast, Literal
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWebEngineWidgets import QWebEngineView

from ..core import generator, storage
from ..core.models import Page, Project
from ..importers import ALLOWED_EXTS_DEFAULT, ImportOptions, ImportResult, import_into_project

APP_TITLE = "PyQt Site Builder"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1240, 800)

        self.project: Optional[Project] = None
        self.project_path: Optional[Path] = None
        self._preview_tmp: Optional[str] = None
        self._debounce = QtCore.QTimer(self)
        self._debounce.setInterval(400)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self.update_preview)

        self._current_page_index: int = 0

        self._build_ui()
        self._build_menu()
        self._bind_events()

        self.new_project_bootstrap()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        splitter = QtWidgets.QSplitter(self)
        splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # Pages panel
        left_panel = QtWidgets.QWidget(self)
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(6)

        self.pages_list = QtWidgets.QListWidget(left_panel)
        self.pages_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)

        btn_row = QtWidgets.QHBoxLayout()
        self.btn_add_page = QtWidgets.QPushButton("Add Page", left_panel)
        self.btn_remove_page = QtWidgets.QPushButton("Remove Page", left_panel)
        btn_row.addWidget(self.btn_add_page)
        btn_row.addWidget(self.btn_remove_page)

        left_layout.addWidget(QtWidgets.QLabel("Pages", left_panel))
        left_layout.addWidget(self.pages_list, 1)
        left_layout.addLayout(btn_row)

        # Editors + assets tabs
        mid_tabs = QtWidgets.QTabWidget(self)
        mid_tabs.setDocumentMode(True)

        self.html_editor = QtWidgets.QPlainTextEdit(mid_tabs)
        self.html_editor.setPlaceholderText("<h2>Hello</h2>\n<p>Edit your page HTML here.</p>")
        self.css_editor = QtWidgets.QPlainTextEdit(mid_tabs)
        self.css_editor.setPlaceholderText("/* Global site CSS lives here */")
        self.assets_view = QtWidgets.QListWidget(mid_tabs)
        self.assets_view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.assets_view.setUniformItemSizes(True)

        mid_tabs.addTab(self.html_editor, "Page HTML")
        mid_tabs.addTab(self.css_editor, "Styles (CSS)")
        mid_tabs.addTab(self.assets_view, "Assets")

        # Preview
        right_panel = QtWidgets.QWidget(self)
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(6)

        self.preview = QWebEngineView(right_panel)
        right_layout.addWidget(QtWidgets.QLabel("Preview", right_panel))
        right_layout.addWidget(self.preview, 1)

        splitter.addWidget(left_panel)
        splitter.addWidget(mid_tabs)
        splitter.addWidget(right_panel)
        splitter.setSizes([240, 560, 520])

        self.status = self.statusBar()

    def _build_menu(self) -> None:
        bar = self.menuBar()
        if bar is None:
            bar = QtWidgets.QMenuBar(self)
            self.setMenuBar(bar)

        file_menu = bar.addMenu("&File")
        act_new = QtGui.QAction("New Project", self)
        act_open = QtGui.QAction("Open Project…", self)
        act_import = QtGui.QAction("Import Site/Project…", self)
        act_save = QtGui.QAction("Save", self)
        act_save_as = QtGui.QAction("Save As…", self)
        act_export = QtGui.QAction("Export Site…", self)
        act_quit = QtGui.QAction("Quit", self)

        if file_menu is not None:
            file_menu.addActions([act_new, act_open, act_import])
        if file_menu is not None:
            file_menu.addSeparator()
        if file_menu is not None:
            file_menu.addActions([act_save, act_save_as])
        if file_menu is not None:
            file_menu.addSeparator()
        if file_menu is not None:
            file_menu.addAction(act_export)
        if file_menu is not None:
            file_menu.addSeparator()
        if file_menu is not None:
            file_menu.addAction(act_quit)

        self.act_new = act_new
        self.act_open = act_open
        self.act_import = act_import
        self.act_save = act_save
        self.act_save_as = act_save_as
        self.act_export = act_export
        self.act_quit = act_quit

        help_menu = bar.addMenu("&Help")
        self.act_about = QtGui.QAction("About", self)
        if help_menu is not None:
            help_menu.addAction(self.act_about)

    def _bind_events(self) -> None:
        self.btn_add_page.clicked.connect(self.add_page)
        self.btn_remove_page.clicked.connect(self.remove_page)
        self.pages_list.currentRowChanged.connect(self._on_page_selection_changed)

        self.html_editor.textChanged.connect(self._on_editor_changed)
        self.css_editor.textChanged.connect(self._on_editor_changed)

        self.act_new.triggered.connect(self.new_project_bootstrap)
        self.act_open.triggered.connect(self.open_project_dialog)
        self.act_import.triggered.connect(self.import_project_dialog)
        self.act_save.triggered.connect(self.save_project)
        self.act_save_as.triggered.connect(self.save_project_as)
        self.act_export.triggered.connect(self.export_site)
        self.act_quit.triggered.connect(self.close)
        self.act_about.triggered.connect(self.show_about)

    # ----------------------------------------------------------- Project Ops --
    def new_project_bootstrap(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "New Project", "Site name:", text="My Site")
        if not ok or not name.strip():
            return
        self.project = Project(
            name=name.strip(),
            pages=[Page(filename="index.html", title="Home", html=self._default_index_html())],
            css=self._default_css(),
            output_dir=None,
        )
        self.project.assets.clear()
        self.project_path = None
        self._current_page_index = 0
        self._refresh_pages_list(select_index=0)
        self._refresh_assets_list()
        self.css_editor.setPlainText(self.project.css)
        self._load_page_into_editor(0)
        self.update_window_title()
        self.update_preview()

    def open_project_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open Project", "", "Site Project (*.siteproj)")
        if not path:
            return
        self.project = storage.load_project(path)
        self.project_path = Path(path)
        self._refresh_pages_list(select_index=0)
        self._refresh_assets_list()
        if self.project.pages:
            self._load_page_into_editor(0)
        self.css_editor.setPlainText(self.project.css)
        self.update_window_title()
        self.update_preview()
        if self.status is not None:
            self.status.showMessage(f"Opened {os.path.basename(path)}", 4000)

    def save_project(self) -> None:
        if self.project is None:
            return
        self._flush_editors_to_model()
        if not self.project_path:
            self.save_project_as()
            return
        storage.save_project(self.project_path, self.project)
        if self.status is not None:
            self.status.showMessage("Project saved", 2500)

    def save_project_as(self) -> None:
        if self.project is None:
            return
        self._flush_editors_to_model()
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Project As", "", "Site Project (*.siteproj)")
        if not path:
            return
        path = path if path.endswith(".siteproj") else f"{path}.siteproj"
        storage.save_project(path, self.project)
        self.project_path = Path(path)
        self.update_window_title()
        if self.status is not None:
            self.status.showMessage(f"Saved {os.path.basename(path)}", 4000)

    def export_site(self) -> None:
        if self.project is None:
            return
        self._flush_editors_to_model()
        out_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Export Site To…")
        if not out_dir:
            return
        templates_dir = Path(__file__).resolve().parent.parent / "core" / "templates"
        generator.render_site(self.project, out_dir, templates_dir)
        if self.status is not None:
            self.status.showMessage(f"Exported site to {out_dir}", 5000)
        QtWidgets.QMessageBox.information(self, "Export complete", f"Your site was exported to:\n{out_dir}")

    def import_project_dialog(self) -> None:
        if self.project is None:
            return
        self._flush_editors_to_model()

        dialog = ImportDialog(self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        selection = dialog.selection()
        if not selection:
            return
        source_type, paths = selection
        options = dialog.options()

        cleanup_dir: Optional[Path] = None
        source_path: Path
        if source_type == "files":
            cleanup_dir = Path(tempfile.mkdtemp(prefix="sitebuilder_import_"))
            for src in paths:
                src_path = Path(src)
                dest = cleanup_dir / src_path.name
                try:
                    shutil.copy2(src_path, dest)
                except Exception as exc:
                    QtWidgets.QMessageBox.warning(self, "Import", f"Failed to include {src_path}: {exc}")
            source_path = cleanup_dir
        else:
            source_path = Path(paths[0])

        target_project = self.project
        new_project_created = False
        if options.create_new_project:
            target_project = Project(name="Imported Site", pages=[], css=self._default_css(), output_dir=None)
            new_project_created = True

        existing_positions = {page.filename: idx for idx, page in enumerate(target_project.pages)}

        progress = QtWidgets.QProgressDialog("Importing content…", None, 0, 1, self)
        progress.setWindowTitle("Importing")
        progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)

        def on_progress(current: int, total: int) -> None:
            progress.setMaximum(total)
            progress.setValue(current)
            QtCore.QCoreApplication.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)

        try:
            result = import_into_project(target_project, source_path, options, progress_callback=on_progress)
        finally:
            progress.close()
            if cleanup_dir:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

        if new_project_created:
            self.project = target_project
            self.project_path = None

        if result.errors:
            if self.status is not None:
                self.status.showMessage("Import completed with errors", 5000)
        else:
            if self.status is not None:
                self.status.showMessage("Import complete", 5000)

        new_index = 0
        for idx, page in enumerate(target_project.pages):
            if page.filename not in existing_positions:
                new_index = idx
                break
        else:
            if existing_positions:
                new_index = min(existing_positions.values())
            elif target_project.pages:
                new_index = 0

        self._refresh_pages_list(select_index=new_index)
        self._refresh_assets_list()
        self.css_editor.setPlainText(target_project.css)
        self.update_preview()
        self.update_window_title()

        _show_import_summary(self, result)

    # --------------------------------------------------------------- Pages --
    def add_page(self) -> None:
        if self.project is None:
            return
        title, ok = QtWidgets.QInputDialog.getText(self, "Add Page", "Page title:", text="About")
        if not ok or not title.strip():
            return
        slug = "-".join(title.lower().split()) or "page"
        filename = f"{slug}.html"
        existing = {p.filename for p in self.project.pages}
        counter = 2
        while filename in existing:
            filename = f"{slug}-{counter}.html"
            counter += 1
        self.project.pages.append(Page(filename=filename, title=title.strip(), html=f"<h2>{title}</h2>\n<p>New page.</p>"))
        self._refresh_pages_list(select_index=len(self.project.pages) - 1)
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
        self._refresh_pages_list(select_index=max(0, row - 1))
        self.update_preview()

    def _refresh_pages_list(self, select_index: int = 0) -> None:
        self.pages_list.blockSignals(True)
        self.pages_list.clear()
        if self.project:
            for page in self.project.pages:
                self.pages_list.addItem(f"{page.title}  ({page.filename})")
        self.pages_list.blockSignals(False)

        count = self.pages_list.count()
        if count == 0:
            return
        select_index = max(0, min(select_index, count - 1))
        self._current_page_index = select_index
        self.pages_list.blockSignals(True)
        self.pages_list.setCurrentRow(select_index)
        self.pages_list.blockSignals(False)
        self._load_page_into_editor(select_index)

    def _refresh_assets_list(self) -> None:
        self.assets_view.clear()
        if not self.project:
            return
        for asset in self.project.assets:
            item = QtWidgets.QListWidgetItem(f"{asset.kind}: {asset.name}")
            self.assets_view.addItem(item)

    def _on_page_selection_changed(self, row: int) -> None:
        if self.project is None or row < 0 or row >= len(self.project.pages):
            return
        self._flush_editors_to_model(self._current_page_index)
        self._current_page_index = row
        self._load_page_into_editor(row)
        self.update_preview()

    # ---------------------------------------------------- Editing & Preview --
    def _on_editor_changed(self) -> None:
        self._debounce.start()

    def _flush_editors_to_model(self, row: Optional[int] = None) -> None:
        if self.project is None:
            return
        if row is None:
            row = self._current_page_index
        if 0 <= row < len(self.project.pages):
            self.project.pages[row].html = self.html_editor.toPlainText()
        self.project.css = self.css_editor.toPlainText()

    def update_preview(self) -> None:
        if self.project is None:
            return
        self._flush_editors_to_model()

        if self._preview_tmp and os.path.isdir(self._preview_tmp):
            shutil.rmtree(self._preview_tmp, ignore_errors=True)
        self._preview_tmp = tempfile.mkdtemp(prefix="sitebuilder_preview_")
        templates_dir = Path(__file__).resolve().parent.parent / "core" / "templates"
        generator.render_site(self.project, self._preview_tmp, templates_dir)

        row = self.pages_list.currentRow()
        if row < 0 and self.project.pages:
            row = 0
        if 0 <= row < len(self.project.pages):
            page = self.project.pages[row]
            path = Path(self._preview_tmp) / page.filename
            self.preview.setUrl(QtCore.QUrl.fromLocalFile(str(path)))

    # ---------------------------------------------------------------- Misc --
    def show_about(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "About",
            f"{APP_TITLE}\n\nA minimal website generator and editor built with PyQt6.",
        )

    def update_window_title(self) -> None:
        name = self.project.name if self.project else "Untitled"
        suffix = f" — {self.project_path.name}" if self.project_path else ""
        self.setWindowTitle(f"{APP_TITLE} — {name}{suffix}")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802 (Qt override)
        if self._preview_tmp and os.path.isdir(self._preview_tmp):
            shutil.rmtree(self._preview_tmp, ignore_errors=True)
        super().closeEvent(event)

    # --------------------------------------------------------------- Defaults --
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

    def _load_page_into_editor(self, index: int) -> None:
        if self.project is None or not (0 <= index < len(self.project.pages)):
            self.html_editor.clear()
            return
        page = self.project.pages[index]
        self.html_editor.blockSignals(True)
        self.html_editor.setPlainText(page.html)
        self.html_editor.blockSignals(False)


def _show_import_summary(parent: QtWidgets.QWidget, result: ImportResult) -> None:
    summary_lines = [
        f"Files scanned: {result.files_scanned}",
        f"Pages imported: {result.pages_imported}",
        f"CSS files merged: {result.css_files_merged}",
        f"Assets copied: {result.assets_copied}",
    ]

    message = QtWidgets.QMessageBox(parent)
    message.setWindowTitle("Import summary")
    message.setIcon(QtWidgets.QMessageBox.Icon.Warning if result.errors else QtWidgets.QMessageBox.Icon.Information)
    message.setText("\n".join(summary_lines))

    inline: list[str] = []
    if result.errors:
        inline.extend(result.errors[:3])
    if result.warnings:
        inline.extend(result.warnings[:7])
        if len(result.warnings) > 7:
            inline.append("…")
    if inline:
        message.setInformativeText("\n".join(inline))

    details: list[str] = []
    if result.errors:
        details.append("Errors:\n" + "\n".join(result.errors))
    if result.warnings:
        details.append("Warnings:\n" + "\n".join(result.warnings))
    if details:
        message.setDetailedText("\n\n".join(details))

    message.exec()


# ---------------------------------------------------------------------------
# Import dialog
# ---------------------------------------------------------------------------


@dataclass
class _ExtensionItem:
    label: str
    enabled: bool
    tooltip: str = ""


class ImportDialog(QtWidgets.QDialog):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Content")
        self.resize(620, 520)

        self._selected_files: list[str] = []
        self._selected_path: str = ""

        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(QtWidgets.QLabel("Source"))

        src_box = QtWidgets.QGroupBox("Source type", self)
        src_layout = QtWidgets.QHBoxLayout(src_box)
        self.radio_folder = QtWidgets.QRadioButton("Folder", src_box)
        self.radio_zip = QtWidgets.QRadioButton("Zip", src_box)
        self.radio_files = QtWidgets.QRadioButton("Files", src_box)
        self.radio_folder.setChecked(True)
        src_layout.addWidget(self.radio_folder)
        src_layout.addWidget(self.radio_zip)
        src_layout.addWidget(self.radio_files)

        layout.addWidget(src_box)

        path_layout = QtWidgets.QHBoxLayout()
        self.path_edit = QtWidgets.QLineEdit(self)
        self.path_edit.setReadOnly(True)
        self.browse_btn = QtWidgets.QPushButton("Browse…", self)
        path_layout.addWidget(self.path_edit, 1)
        path_layout.addWidget(self.browse_btn)
        layout.addLayout(path_layout)

        behavior_box = QtWidgets.QGroupBox("Behavior", self)
        behavior_layout = QtWidgets.QGridLayout(behavior_box)

        self.merge_current_radio = QtWidgets.QRadioButton("Merge into current project", behavior_box)
        self.create_new_radio = QtWidgets.QRadioButton("Create new project from import", behavior_box)
        self.merge_current_radio.setChecked(True)

        behavior_layout.addWidget(self.merge_current_radio, 0, 0, 1, 2)
        behavior_layout.addWidget(self.create_new_radio, 1, 0, 1, 2)

        behavior_layout.addWidget(QtWidgets.QLabel("Conflict handling:"), 2, 0)
        self.conflict_combo = QtWidgets.QComboBox(behavior_box)
        self.conflict_combo.addItems(["Keep both", "Overwrite", "Skip"])
        behavior_layout.addWidget(self.conflict_combo, 2, 1)

        behavior_layout.addWidget(QtWidgets.QLabel("CSS merge:"), 3, 0)
        self.css_combo = QtWidgets.QComboBox(behavior_box)
        self.css_combo.addItems(["Append", "Prepend", "Replace"])
        behavior_layout.addWidget(self.css_combo, 3, 1)

        self.rewrite_links_check = QtWidgets.QCheckBox("Rewrite page links", behavior_box)
        self.rewrite_links_check.setChecked(True)
        self.rewrite_assets_check = QtWidgets.QCheckBox("Rewrite asset URLs", behavior_box)
        self.rewrite_assets_check.setChecked(True)
        behavior_layout.addWidget(self.rewrite_links_check, 4, 0, 1, 2)
        behavior_layout.addWidget(self.rewrite_assets_check, 5, 0, 1, 2)

        layout.addWidget(behavior_box)

        self.advanced_button = QtWidgets.QToolButton(self)
        self.advanced_button.setText("Show advanced ▸")
        self.advanced_button.setCheckable(True)
        self.advanced_button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        layout.addWidget(self.advanced_button)

        self.advanced_widget = QtWidgets.QWidget(self)
        advanced_layout = QtWidgets.QFormLayout(self.advanced_widget)
        self.page_filename_combo = QtWidgets.QComboBox(self.advanced_widget)
        self.page_filename_combo.addItems(["Slugify", "Keep original", "Prefix on collision"])
        self.markdown_combo = QtWidgets.QComboBox(self.advanced_widget)
        self.markdown_combo.addItems(["GitHub Flavored", "CommonMark"])
        self.wrap_text_check = QtWidgets.QCheckBox("Wrap plain text paragraphs", self.advanced_widget)
        self.wrap_text_check.setChecked(True)
        self.home_index_check = QtWidgets.QCheckBox("Set home page to index.html when present", self.advanced_widget)
        self.home_index_check.setChecked(True)
        self.ignore_hidden_check = QtWidgets.QCheckBox("Ignore hidden files", self.advanced_widget)
        self.ignore_hidden_check.setChecked(True)
        self.include_js_check = QtWidgets.QCheckBox("Include JavaScript files", self.advanced_widget)
        self.include_js_check.setChecked(True)

        advanced_layout.addRow("Filename strategy", self.page_filename_combo)
        advanced_layout.addRow("Markdown flavor", self.markdown_combo)
        advanced_layout.addRow(self.wrap_text_check)
        advanced_layout.addRow(self.home_index_check)
        advanced_layout.addRow(self.ignore_hidden_check)
        advanced_layout.addRow(self.include_js_check)

        self.ext_list = QtWidgets.QListWidget(self.advanced_widget)
        self.ext_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
        advanced_layout.addRow("Allowed extensions", self.ext_list)

        layout.addWidget(self.advanced_widget)
        self.advanced_widget.setVisible(False)

        self.advanced_button.toggled.connect(self._toggle_advanced)
        self.browse_btn.clicked.connect(self._on_browse)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        ok_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText("Import")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate_extensions()

    def _toggle_advanced(self, checked: bool) -> None:
        self.advanced_button.setText("Hide advanced ◂" if checked else "Show advanced ▸")
        self.advanced_widget.setVisible(checked)

    def _populate_extensions(self) -> None:
        ext_items = self._build_extension_items()
        for entry in ext_items:
            item = QtWidgets.QListWidgetItem(entry.label, self.ext_list)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            if not entry.enabled:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(QtCore.Qt.CheckState.Checked if entry.enabled else QtCore.Qt.CheckState.Unchecked)
            if entry.tooltip:
                item.setToolTip(entry.tooltip)

    def _build_extension_items(self) -> list[_ExtensionItem]:
        items: list[_ExtensionItem] = []
        optional_tips: Dict[str, str] = {
            ".docx": "Requires the 'mammoth' package",
            ".rst": "Requires the 'docutils' package",
            ".ipynb": "Requires nbconvert and nbformat",
        }
        from .. import importers

        for ext in sorted(ALLOWED_EXTS_DEFAULT):
            enabled = True
            tip = ""
            if ext == ".docx" and getattr(importers, "mammoth", None) is None:
                enabled = False
                tip = optional_tips[ext]
            elif ext == ".rst" and getattr(importers, "publish_parts", None) is None:
                enabled = False
                tip = optional_tips[ext]
            elif ext == ".ipynb" and (getattr(importers, "nbformat", None) is None or getattr(importers, "HTMLExporter", None) is None):
                enabled = False
                tip = optional_tips[ext]
            items.append(_ExtensionItem(label=ext, enabled=enabled, tooltip=tip))
        return items

    def _on_browse(self) -> None:
        if self.radio_folder.isChecked():
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select folder")
            if path:
                self._selected_path = path
                self._selected_files = []
                self.path_edit.setText(path)
        elif self.radio_zip.isChecked():
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select zip", "", "Zip Archives (*.zip)")
            if path:
                self._selected_path = path
                self._selected_files = []
                self.path_edit.setText(path)
        else:
            files, _ = QtWidgets.QFileDialog.getOpenFileNames(
                self,
                "Select files",
                "",
                "Content files (*.html *.htm *.md *.markdown *.txt *.ipynb *.rst *.css *.js);;All files (*)",
            )
            if files:
                self._selected_files = files
                self._selected_path = ""
                self.path_edit.setText(f"{len(files)} file(s) selected")

    def selection(self) -> tuple[str, list[str]] | None:
        if self.radio_files.isChecked():
            if not self._selected_files:
                QtWidgets.QMessageBox.warning(self, "Import", "Select at least one file to import.")
                return None
            return "files", self._selected_files
        path = self._selected_path
        if not path:
            QtWidgets.QMessageBox.warning(self, "Import", "Select a source to import.")
            return None
        if self.radio_folder.isChecked():
            return "folder", [path]
        return "zip", [path]

    def options(self) -> ImportOptions:
        allowed_exts = set()
        for i in range(self.ext_list.count()):
            item = self.ext_list.item(i)
            if item is not None:
                if item.checkState() == QtCore.Qt.CheckState.Checked:
                    allowed_exts.add(item.text())
        conflict_map = {
            "Keep both": "keep-both",
            "Overwrite": "overwrite",
            "Skip": "skip",
        }
        css_map = {
            "Append": "append",
            "Prepend": "prepend",
            "Replace": "replace",
        }
        filename_map = {
            "Slugify": "slugify",
            "Keep original": "keep",
            "Prefix on collision": "prefix-collisions",
        }
        md_map = {
            "GitHub Flavored": "gfm",
            "CommonMark": "commonmark",
        }
        return ImportOptions(
            create_new_project=self.create_new_radio.isChecked(),
            page_filename_strategy=cast(Literal["keep", "slugify", "prefix-collisions"], filename_map[self.page_filename_combo.currentText()]),
            conflict_policy=cast(Literal["overwrite", "keep-both", "skip"], conflict_map[self.conflict_combo.currentText()]),
            merge_css=cast(Literal["append", "prepend", "replace"], css_map[self.css_combo.currentText()]),
            rewrite_links=self.rewrite_links_check.isChecked(),
            rewrite_asset_urls=self.rewrite_assets_check.isChecked(),
            md_flavor=cast(Literal["gfm", "commonmark"], md_map[self.markdown_combo.currentText()]),
            text_wrap_paragraphs=self.wrap_text_check.isChecked(),
            set_home_to_index_if_present=self.home_index_check.isChecked(),
            ignore_hidden=self.ignore_hidden_check.isChecked(),
            include_js_files=self.include_js_check.isChecked(),
            allowed_extensions=allowed_exts or set(ALLOWED_EXTS_DEFAULT),
        )

