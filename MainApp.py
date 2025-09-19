"""
Webineer Site Builder — single-file PyQt6 app
- Pages panel (add/remove)
- Editors: Page HTML + Global CSS
- Live preview (Qt WebEngine)
- Save/Open .siteproj (JSON)
- Export a static site with Jinja2 template
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict, Tuple, cast
from pathlib import Path
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWebEngineWidgets import QWebEngineView
from jinja2 import Environment, DictLoader, select_autoescape

APP_TITLE = "Webineer Site Builder"

# ---------------------- Jinja2 Template & Defaults ----------------------

BASE_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }} — {{ site_name }}</title>
  <link rel="stylesheet" href="{{ stylesheet_path }}">
  <style>
    /* Basic reset */
    *, *::before, *::after { box-sizing: border-box; }
    body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, "Helvetica Neue", Arial, "Noto Sans", "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"; line-height: 1.6; color: #222; }
    a { text-decoration: none; color: inherit; }
    .container { max-width: 1000px; margin: 0 auto; padding: 1rem; }

    .site-header { border-bottom: 1px solid #e5e5e5; background: #fafafa; position: sticky; top: 0; z-index: 5; }
    .site-name { margin: 0; font-size: 1.25rem; }
    .site-nav ul { list-style: none; display: flex; gap: .75rem; padding-left: 0; margin: .5rem 0 0; flex-wrap: wrap; }
    .site-nav a { padding: .4rem .6rem; border-radius: .4rem; border: 1px solid transparent; display: inline-block; }
    .site-nav a:hover { background: #f0f0f0; }

    .site-footer { border-top: 1px solid #e5e5e5; background: #fafafa; margin-top: 3rem; }
    .hero { padding: 3rem 0; text-align: center; }
    .btn { display: inline-block; padding: .6rem 1rem; border: 1px solid #222; border-radius: .4rem; }
    .grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
    img { max-width: 100%; height: auto; display: block; }
    code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
  </style>
</head>
<body>
  <header class="site-header">
    <div class="container">
      <h1 class="site-name">{{ site_name }}</h1>
      <nav class="site-nav">
        <ul>
          {% for p in pages %}
            <li><a href="{{ p.filename }}">{{ p.title }}</a></li>
          {% endfor %}
        </ul>
      </nav>
    </div>
  </header>

  <main class="container">
    {{ content | safe }}
  </main>

  <footer class="site-footer">
    <div class="container">
      <small>© {{ site_name }} — Built with Webineer</small>
    </div>
  </footer>
</body>
</html>
"""

DEFAULT_CSS = """\
/* Global site styles */
body { background: white; }
.hero { background: #f5f5f5; border: 1px solid #e5e5e5; border-radius: .6rem; }
.btn { background: #fff; }
"""

DEFAULT_INDEX_HTML = """\
<section class="hero">
  <h2>Welcome!</h2>
  <p>Your new site is ready. Edit this content and export.</p>
  <a class="btn" href="#">Get started</a>
</section>
<section>
  <h3>Features</h3>
  <div class="grid">
    <div><h4>Fast</h4><p>Edit and preview instantly.</p></div>
    <div><h4>Simple</h4><p>HTML in, static site out.</p></div>
    <div><h4>Portable</h4><p>Publish anywhere.</p></div>
  </div>
</section>
"""

# ---------------------- Data Model & Persistence ----------------------

@dataclass
class Page:
    filename: str
    title: str
    html: str

@dataclass
class Project:
    name: str = "My Site"
    pages: List[Page] = field(default_factory=list)
    css: str = DEFAULT_CSS
    output_dir: Optional[str] = None
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "css": self.css,
            "output_dir": self.output_dir,
            "version": self.version,
            "pages": [asdict(p) for p in self.pages],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        pages = [Page(**p) for p in data.get("pages", [])]
        return cls(
            name=data.get("name", "My Site"),
            pages=pages,
            css=data.get("css", DEFAULT_CSS),
            output_dir=data.get("output_dir"),
            version=data.get("version", 1),
        )

def save_project(path: str | Path, project: Project) -> None:
    path = Path(path)
    path.write_text(json.dumps(project.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

def load_project(path: str | Path) -> Project:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return Project.from_dict(data)

# ---------------------- Rendering ----------------------

def _env_from_memory() -> Environment:
    """Jinja2 env that loads template from in-memory dict."""
    return Environment(
        loader=DictLoader({"base.html.j2": BASE_TEMPLATE}),
        autoescape=select_autoescape(["html", "xml"]),
    )

def render_site(project: Project, output_dir: str | Path) -> None:
    """Render the project to a static site at output_dir."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write CSS
    css_dir = output_dir / "assets" / "css"
    css_dir.mkdir(parents=True, exist_ok=True)
    (css_dir / "style.css").write_text(project.css, encoding="utf-8")

    env = _env_from_memory()
    tpl = env.get_template("base.html.j2")
    nav = [{"filename": p.filename, "title": p.title} for p in project.pages]

    for page in project.pages:
        html = tpl.render(
            site_name=project.name,
            title=page.title,
            pages=nav,
            content=page.html,
            stylesheet_path="assets/css/style.css",
        )
        (output_dir / page.filename).write_text(html, encoding="utf-8")

# ---------------------- UI ----------------------

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1220, 780)

        # State
        self.project: Optional[Project] = None
        self.project_path: Optional[Path] = None
        self._preview_tmp: Optional[str] = None

        # Debounce typing for preview
        self._debounce = QtCore.QTimer(self)
        self._debounce.setInterval(400)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self.update_preview)

        # UI
        self._build_ui()
        self._build_menu()
        self._bind_events()

        # Start with a new project
        self.new_project_bootstrap()

    # ---------- UI construction ----------
    def _build_ui(self) -> None:
        splitter = QtWidgets.QSplitter(self)
        splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # Left: Pages list + buttons
        left = QtWidgets.QWidget(self)
        lyt_left = QtWidgets.QVBoxLayout(left)
        lyt_left.setContentsMargins(6, 6, 6, 6)
        lyt_left.setSpacing(6)

        self.pages_list = QtWidgets.QListWidget(left)
        self.pages_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)

        bar = QtWidgets.QHBoxLayout()
        self.btn_add = QtWidgets.QPushButton("Add Page")
        self.btn_remove = QtWidgets.QPushButton("Remove Page")
        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_remove)

        lyt_left.addWidget(QtWidgets.QLabel("Pages"))
        lyt_left.addWidget(self.pages_list, 1)
        lyt_left.addLayout(bar)

        # Middle: Editors (HTML + CSS)
        mid = QtWidgets.QTabWidget(self)
        mid.setDocumentMode(True)

        self.html_editor = QtWidgets.QPlainTextEdit(mid)
        self.html_editor.setPlaceholderText("<h2>Hello</h2>\n<p>Edit your page HTML here.</p>")

        self.css_editor = QtWidgets.QPlainTextEdit(mid)
        self.css_editor.setPlaceholderText("/* Global site CSS */")

        mid.addTab(self.html_editor, "Page HTML")
        mid.addTab(self.css_editor, "Styles (CSS)")

        # Right: Preview
        right = QtWidgets.QWidget(self)
        lyt_right = QtWidgets.QVBoxLayout(right)
        lyt_right.setContentsMargins(6, 6, 6, 6)
        lyt_right.setSpacing(6)

        self.preview = QWebEngineView(right)
        lyt_right.addWidget(QtWidgets.QLabel("Preview"))
        lyt_right.addWidget(self.preview, 1)

        splitter.addWidget(left)
        splitter.addWidget(mid)
        splitter.addWidget(right)
        splitter.setSizes([240, 560, 420])

        # Ensure a typed, non-None status bar
        if self.statusBar() is None:
            self.setStatusBar(QtWidgets.QStatusBar(self))
        self.status: QtWidgets.QStatusBar = cast(QtWidgets.QStatusBar, self.statusBar())

    def _build_menu(self) -> None:
        # Always ensure we have a menubar object, then create menus/actions unconditionally
        bar = self.menuBar()
        if bar is None:
            bar = QtWidgets.QMenuBar(self)
            self.setMenuBar(bar)
        bar = cast(QtWidgets.QMenuBar, bar)

        # File menu
        m_file = cast(QtWidgets.QMenu, bar.addMenu("&File"))
        self.act_new = QtGui.QAction("New Project", self)
        self.act_open = QtGui.QAction("Open Project…", self)
        self.act_save = QtGui.QAction("Save", self)
        self.act_save_as = QtGui.QAction("Save As…", self)
        self.act_export = QtGui.QAction("Export Site…", self)
        self.act_quit = QtGui.QAction("Quit", self)

        m_file.addActions([self.act_new, self.act_open])
        m_file.addSeparator()
        m_file.addActions([self.act_save, self.act_save_as])
        m_file.addSeparator()
        m_file.addAction(self.act_export)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)

        # Help menu
        m_help = cast(QtWidgets.QMenu, bar.addMenu("&Help"))
        self.act_about = QtGui.QAction("About", self)
        m_help.addAction(self.act_about)

    def _bind_events(self) -> None:
        self.btn_add.clicked.connect(self.add_page)
        self.btn_remove.clicked.connect(self.remove_page)
        self.pages_list.currentRowChanged.connect(self._on_page_selected)

        self.html_editor.textChanged.connect(self._on_editor_changed)
        self.css_editor.textChanged.connect(self._on_editor_changed)

        self.act_new.triggered.connect(self.new_project_bootstrap)
        self.act_open.triggered.connect(self.open_project_dialog)
        self.act_save.triggered.connect(self.save_project)
        self.act_save_as.triggered.connect(self.save_project_as)
        self.act_export.triggered.connect(self.export_site)
        self.act_quit.triggered.connect(self.close)
        self.act_about.triggered.connect(self.show_about)

    # ---------- Project ops ----------
    def new_project_bootstrap(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "New Project", "Site name:", text="My Site")
        if not ok or not name.strip():
            return
        self.project = Project(
            name=name.strip(),
            pages=[Page(filename="index.html", title="Home", html=DEFAULT_INDEX_HTML)],
            css=DEFAULT_CSS,
            output_dir=None,
        )
        self.project_path = None
        self._refresh_pages_list(select_index=0)
        self.css_editor.setPlainText(self.project.css)
        self.html_editor.setPlainText(self.project.pages[0].html)
        self.update_window_title()
        self.update_preview()

    def open_project_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open Project", "", "Site Project (*.siteproj)"
        )
        if not path:
            return
        try:
            self.project = load_project(path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to open project:\n{e}")
            return
        self.project_path = Path(path)
        self._refresh_pages_list(select_index=0)
        if self.project.pages:
            self.html_editor.setPlainText(self.project.pages[0].html)
        self.css_editor.setPlainText(self.project.css)
        self.update_window_title()
        self.update_preview()
        self.status.showMessage(f"Opened {os.path.basename(path)}", 3000)

    def save_project(self) -> None:
        if not self.project:
            return
        self._flush_editors_to_model()
        if not self.project_path:
            self.save_project_as()
            return
        try:
            save_project(self.project_path, self.project)
            self.status.showMessage("Project saved", 2000)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to save:\n{e}")

    def save_project_as(self) -> None:
        if not self.project:
            return
        self._flush_editors_to_model()
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Project As", "", "Site Project (*.siteproj)"
        )
        if not path:
            return
        if not path.endswith(".siteproj"):
            path += ".siteproj"
        try:
            save_project(path, self.project)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to save:\n{e}")
            return
        self.project_path = Path(path)
        self.update_window_title()
        self.status.showMessage(f"Saved {os.path.basename(path)}", 3000)

    def export_site(self) -> None:
        if not self.project:
            return
        self._flush_editors_to_model()
        out_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Export Site To…")
        if not out_dir:
            return
        try:
            render_site(self.project, out_dir)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Export failed:\n{e}")
            return
        self.status.showMessage(f"Exported site to {out_dir}", 5000)
        QtWidgets.QMessageBox.information(
            self, "Export complete", f"Your site was exported to:\n{out_dir}"
        )

    # ---------- Pages ----------
    def add_page(self) -> None:
        if not self.project:
            return
        title, ok = QtWidgets.QInputDialog.getText(self, "Add Page", "Page title:", text="About")
        if not ok or not title.strip():
            return
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        filename = "index.html" if slug == "index" else f"{slug or 'page'}.html"
        existing = {p.filename for p in self.project.pages}
        if filename in existing:
            n = 1
            base = filename[:-5] if filename.endswith(".html") else filename
            while filename in existing:
                filename = f"{base}-{n}.html"
                n += 1
        self.project.pages.append(Page(filename=filename, title=title.strip(),
                                       html=f"<h2>{title.strip()}</h2>\n<p>Write something awesome.</p>"))
        self._refresh_pages_list(select_index=len(self.project.pages) - 1)
        self.update_preview()

    def remove_page(self) -> None:
        if not self.project:
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
            for p in self.project.pages:
                self.pages_list.addItem(f"{p.title}  ({p.filename})")
        self.pages_list.blockSignals(False)
        self.pages_list.setCurrentRow(select_index)

    def _on_page_selected(self, row: int) -> None:
        if not self.project or row < 0 or row >= len(self.project.pages):
            return
        # Save previous page edits
        self._flush_editors_to_model()
        # Load selected page
        page = self.project.pages[row]
        self.html_editor.blockSignals(True)
        self.html_editor.setPlainText(page.html)
        self.html_editor.blockSignals(False)
        self.update_preview()

    # ---------- Editing & Preview ----------
    def _on_editor_changed(self) -> None:
        self._debounce.start()

    def _flush_editors_to_model(self) -> None:
        if not self.project:
            return
        row = self.pages_list.currentRow()
        if 0 <= row < len(self.project.pages):
            self.project.pages[row].html = self.html_editor.toPlainText()
        self.project.css = self.css_editor.toPlainText()

    def update_preview(self) -> None:
        if not self.project:
            return
        self._flush_editors_to_model()

        # Rebuild preview in a temp directory
        if self._preview_tmp and os.path.isdir(self._preview_tmp):
            shutil.rmtree(self._preview_tmp, ignore_errors=True)
        self._preview_tmp = tempfile.mkdtemp(prefix="webineer_preview_")
        render_site(self.project, self._preview_tmp)

        # Show current page
        row = self.pages_list.currentRow()
        if row < 0:
            row = 0
        if not self.project.pages:
            return
        curr = self.project.pages[row]
        page_path = Path(self._preview_tmp) / curr.filename
        self.preview.setUrl(QtCore.QUrl.fromLocalFile(str(page_path)))

    # ---------- Misc ----------
    def show_about(self) -> None:
        QtWidgets.QMessageBox.information(
            self, "About",
            f"{APP_TITLE}\n\nA minimal static site builder and editor built with PyQt6."
        )

    def update_window_title(self) -> None:
        name = self.project.name if self.project else "Untitled"
        suffix = f" — {self.project_path.name}" if self.project_path else ""
        self.setWindowTitle(f"{APP_TITLE} — {name}{suffix}")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._preview_tmp and os.path.isdir(self._preview_tmp):
            shutil.rmtree(self._preview_tmp, ignore_errors=True)
        event.accept()

# ---------------------- Entry Point ----------------------

def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
