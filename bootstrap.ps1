# --- Configure your project root ---
$root = "C:\Users\curph\OneDrive\Documents\GitHub\Webineer"

# --- Create directories ---
$dirs = @(
  "$root\sitebuilder",
  "$root\sitebuilder\ui",
  "$root\sitebuilder\core",
  "$root\sitebuilder\core\templates",
  "$root\sitebuilder\core\static",
  "$root\.vscode"
)
foreach ($d in $dirs) { New-Item -ItemType Directory -Force -Path $d | Out-Null }

# --- requirements.txt ---
@'
PyQt6>=6.6
PyQt6-WebEngine>=6.6
Jinja2>=3.1
'@ | Set-Content -Encoding UTF8 "$root\requirements.txt"

# --- .gitignore ---
@'
.venv/
__pycache__/
*.pyc
*.pyo
*.pyd
build/
dist/
*.spec
*.siteproj
.DS_Store
'@ | Set-Content -Encoding UTF8 "$root\.gitignore"

# --- VS Code settings ---
@'
{
  "python.defaultInterpreterPath": "${workspaceFolder}\\.venv\\Scripts\\python.exe",
  "python.analysis.typeCheckingMode": "basic",
  "editor.formatOnSave": true
}
'@ | Set-Content -Encoding UTF8 "$root\.vscode\settings.json"

@'
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Run PyQt Site Builder",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}\\MainApp.py",
      "console": "integratedTerminal",
      "justMyCode": true
    }
  ]
}
'@ | Set-Content -Encoding UTF8 "$root\.vscode\launch.json"

@'
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Install requirements",
      "type": "shell",
      "command": "pip install -r requirements.txt",
      "group": "build",
      "problemMatcher": []
    }
  ]
}
'@ | Set-Content -Encoding UTF8 "$root\.vscode\tasks.json"

# --- Python package: sitebuilder ---

# __init__.py files
"" | Set-Content -Encoding UTF8 "$root\sitebuilder\__init__.py"
"" | Set-Content -Encoding UTF8 "$root\sitebuilder\ui\__init__.py"
"" | Set-Content -Encoding UTF8 "$root\sitebuilder\core\__init__.py"

# sitebuilder\main.py
@'
import sys
from PyQt6 import QtWidgets
from .ui.main_window import MainWindow

def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
'@ | Set-Content -Encoding UTF8 "$root\sitebuilder\main.py"

# sitebuilder\core\models.py
@'
from dataclasses import dataclass, asdict
from typing import List, Optional

@dataclass
class Page:
    filename: str
    title: str
    html: str

@dataclass
class Project:
    name: str
    pages: List[Page]
    css: str
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
            css=data.get("css", ""),
            output_dir=data.get("output_dir"),
            version=data.get("version", 1),
        )
'@ | Set-Content -Encoding UTF8 "$root\sitebuilder\core\models.py"

# sitebuilder\core\storage.py
@'
import json
from pathlib import Path
from .models import Project

def save_project(path: str | Path, project: Project) -> None:
    path = Path(path)
    path.write_text(json.dumps(project.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

def load_project(path: str | Path) -> Project:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return Project.from_dict(data)
'@ | Set-Content -Encoding UTF8 "$root\sitebuilder\core\storage.py"

# sitebuilder\core\generator.py
@'
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from .models import Project

def _env(templates_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"])
    )

def render_site(project: Project, output_dir: str | Path, templates_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write CSS
    css_dir = output_dir / "assets" / "css"
    css_dir.mkdir(parents=True, exist_ok=True)
    (css_dir / "style.css").write_text(project.css, encoding="utf-8")

    env = _env(templates_dir)
    tpl = env.get_template("base.html.j2")

    nav = [{"filename": p.filename, "title": p.title} for p in project.pages]

    for page in project.pages:
        html = tpl.render(
            site_name=project.name,
            title=page.title,
            pages=nav,
            content=page.html,
            stylesheet_path="assets/css/style.css"
        )
        (output_dir / page.filename).write_text(html, encoding="utf-8")
'@ | Set-Content -Encoding UTF8 "$root\sitebuilder\core\generator.py"

# sitebuilder\core\templates\base.html.j2
@'
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
    a { text-decoration: none; }
    .container { max-width: 1000px; margin: 0 auto; padding: 1rem; }

    .site-header { border-bottom: 1px solid #e5e5e5; background: #fafafa; position: sticky; top: 0; }
    .site-name { margin: 0; font-size: 1.25rem; }
    .site-nav ul { list-style: none; display: flex; gap: .75rem; padding-left: 0; margin: .5rem 0 0; flex-wrap: wrap; }
    .site-nav a { padding: .4rem .6rem; border-radius: .4rem; border: 1px solid transparent; }
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
      <small>© {{ site_name }} — Built with PyQt SiteBuilder</small>
    </div>
  </footer>
</body>
</html>
'@ | Set-Content -Encoding UTF8 "$root\sitebuilder\core\templates\base.html.j2"

# sitebuilder\core\static\base.css
@'
/* Starter theme overrides go here.
   This file is NOT used directly at runtime; it's here as a reference.
   The running app writes your current CSS as `assets/css/style.css` in the export. */
body { background: white; }
'@ | Set-Content -Encoding UTF8 "$root\sitebuilder\core\static\base.css"

# sitebuilder\ui\main_window.py
@'
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

        # File
        m_file = bar.addMenu("&File")
        act_new = QtGui.QAction("New Project", self)
        act_open = QtGui.QAction("Open Project…", self)
        act_save = QtGui.QAction("Save", self)
        act_save_as = QtGui.QAction("Save As…", self)
        act_export = QtGui.QAction("Export Site…", self)
        act_quit = QtGui.QAction("Quit", self)
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
        self.status.showMessage(f"Opened {os.path.basename(path)}", 3000)

    def save_project(self) -> None:
        if self.project is None:
            return
        self._flush_editors_to_model()
        if not self.project_path:
            return self.save_project_as()
        storage.save_project(self.project_path, self.project)
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
        self.status.showMessage(f"Saved {os.path.basename(path)}", 3000)

    def export_site(self) -> None:
        if self.project is None:
            return
        self._flush_editors_to_model()
        out_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Export Site To…")
        if not out_dir:
            return
        templates_dir = Path(__file__).resolve().parent.parent / "core" / "templates"
        generator.render_site(self.project, out_dir, templates_dir)
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
        suffix = f" — {self.project_path.name}" if self.project_path else ""
        self.setWindowTitle(f"{APP_TITLE} — {name}{suffix}")

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
'@ | Set-Content -Encoding UTF8 "$root\sitebuilder\ui\main_window.py"

# --- Your existing MainApp.py (overwrite with entry point) ---
@'
from sitebuilder.main import main

if __name__ == "__main__":
    raise SystemExit(main())
'@ | Set-Content -Encoding UTF8 "$root\MainApp.py"

# --- Create & populate virtual environment ---
& py -3.12 -m venv "$root\.venv"
& "$root\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$root\.venv\Scripts\python.exe" -m pip install -r "$root\requirements.txt"

Write-Host "`nSetup complete. Next steps:"
Write-Host "1) Open the folder in VS Code."
Write-Host "2) Press F5 to run, or:"
Write-Host "   `"$root\.venv\Scripts\Activate`"; python MainApp.py"
