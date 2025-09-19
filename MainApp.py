
"""
Webineer Site Builder — Enhanced single-file PyQt6 app (Pylance-friendly)
Features:
- Pages panel (add/remove)
- Editors: Page HTML + Global CSS
- Design tab: theme presets, color & font pickers (generates CSS)
- Insert menu: HTML sections, icons, SVG graphics, placeholder images
- CSS helpers: buttons, cards, utilities (idempotent append)
- Assets tab: add/remove images, insert <img>, auto-copy on preview/export
- Live preview (Qt WebEngine)
- Save/Open .siteproj (JSON)
- Export a static site with Jinja2 template + copied assets

This version adds precise typing/casts and None-guards to silence Pylance warnings.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional, Dict, Tuple, cast

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
    body { margin: 0; font-family: {{ body_font }}; line-height: 1.6; color: {{ text_color }}; background: {{ surface_color }}; }
    a { text-decoration: none; color: inherit; }
    .container { max-width: 1100px; margin: 0 auto; padding: 1rem; }

    .site-header { border-bottom: 1px solid rgba(0,0,0,.08); background: {{ surface_color }}; position: sticky; top: 0; z-index: 5; backdrop-filter: saturate(180%) blur(8px); }
    .site-name { margin: 0; font-size: 1.15rem; font-family: {{ heading_font }}; letter-spacing: .2px; }
    .site-nav ul { list-style: none; display: flex; gap: .6rem; padding-left: 0; margin: .5rem 0 0; flex-wrap: wrap; }
    .site-nav a { padding: .45rem .7rem; border-radius: .45rem; border: 1px solid transparent; display: inline-block; }
    .site-nav a:hover { background: rgba(0,0,0,.04); }

    .site-footer { border-top: 1px solid rgba(0,0,0,.08); background: {{ surface_color }}; margin-top: 3rem; }
    .hero { padding: 3rem 0; text-align: center; }
    .btn { display: inline-block; padding: .6rem 1rem; border: 1px solid {{ text_color }}; border-radius: .5rem; }
    .grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
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

# Fallback defaults (used for new projects and the Design tab initialization)
DEFAULT_PALETTE = dict(
    primary="#3b82f6",   # blue-500
    surface="#ffffff",
    text="#222222"
)
DEFAULT_FONTS = dict(
    heading="system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, 'Helvetica Neue', Arial",
    body="system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, 'Helvetica Neue', Arial",
)

DEFAULT_INDEX_HTML = """\
<section class="hero">
  <h2>Welcome!</h2>
  <p class="muted">Build beautiful sites with zero fuss.</p>
  <a class="btn btn-primary" href="#">Get started</a>
</section>
<section>
  <h3>Features</h3>
  <div class="grid">
    <div class="card"><h4>Fast</h4><p>Edit and preview instantly.</p></div>
    <div class="card"><h4>Simple</h4><p>HTML in, static site out.</p></div>
    <div class="card"><h4>Portable</h4><p>Publish anywhere.</p></div>
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
    css: str = ""                      # user CSS (generated or edited)
    palette: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PALETTE))
    fonts: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_FONTS))
    images: List[str] = field(default_factory=list)  # absolute file paths on disk
    output_dir: Optional[str] = None
    version: int = 2                   # bump schema

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "css": self.css,
            "palette": self.palette,
            "fonts": self.fonts,
            "images": self.images,
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
            palette=data.get("palette", dict(DEFAULT_PALETTE)),
            fonts=data.get("fonts", dict(DEFAULT_FONTS)),
            images=data.get("images", []),
            output_dir=data.get("output_dir"),
            version=data.get("version", 2),
        )

def save_project(path: str | Path, project: Project) -> None:
    path = Path(path)
    path.write_text(json.dumps(project.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

def load_project(path: str | Path) -> Project:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return Project.from_dict(data)

# ---------------------- CSS Generation & Helpers ----------------------

CSS_HELPERS_SENTINEL = "/* === WEBINEER CSS HELPERS (DO NOT DUPLICATE) === */"

THEME_PRESETS = {
    "Classic (Blue)": dict(primary="#3b82f6", surface="#ffffff", text="#222222"),
    "Midnight":       dict(primary="#60a5fa", surface="#0b1020", text="#e5e7eb"),
    "Emerald":        dict(primary="#10b981", surface="#ffffff", text="#1f2937"),
    "Rose":           dict(primary="#f43f5e", surface="#ffffff", text="#1f2937"),
    "Slate":          dict(primary="#64748b", surface="#f8fafc", text="#0f172a"),
    "Contrast":       dict(primary="#111111", surface="#ffffff", text="#111111"),
}

FONT_STACKS = {
    "System UI": "system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, 'Helvetica Neue', Arial",
    "Serif (Georgia)": "Georgia, 'Times New Roman', Times, serif",
    "Humanist (Segoe UI)": "Segoe UI, system-ui, -apple-system, Roboto, Ubuntu, 'Helvetica Neue', Arial",
    "Grotesk (Inter-like)": "Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Arial",
    "Mono (for headings)": "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace",
}

def generate_base_css(palette: Dict[str, str], fonts: Dict[str, str]) -> str:
    primary = palette["primary"]
    surface = palette["surface"]
    text = palette["text"]
    body_font = fonts["body"]
    heading_font = fonts["heading"]
    return f"""/* Generated by Webineer Design tab */
:root {{
  --color-primary: {primary};
  --color-surface: {surface};
  --color-text: {text};
  --radius: .6rem;
}}

html, body {{
  background: var(--color-surface);
  color: var(--color-text);
  font-family: {body_font};
  line-height: 1.6;
}}

h1, h2, h3, h4, h5 {{
  font-family: {heading_font};
  line-height: 1.25;
}}

a {{ color: inherit; }}

.container {{ max-width: 1100px; margin-inline: auto; padding: 1rem; }}
.grid {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}

.hero {{ padding: 3rem 0; text-align: center; background: color-mix(in oklab, var(--color-primary) 8%, var(--color-surface)); border: 1px solid rgba(0,0,0,.06); border-radius: var(--radius); }}

.btn {{
  display: inline-block; padding: .6rem 1rem; border-radius: var(--radius); border: 1px solid var(--color-text);
  background: transparent;
}}
.btn-primary {{ border-color: var(--color-primary); background: var(--color-primary); color: white; }}
.btn-secondary {{ border-color: color-mix(in oklab, var(--color-primary) 40%, white); background: color-mix(in oklab, var(--color-primary) 12%, white); }}
.btn-ghost {{ border-color: transparent; background: transparent; }}

.card {{ border: 1px solid rgba(0,0,0,.08); border-radius: var(--radius); padding: 1rem; background: white; }}
.navbar a.active {{ background: color-mix(in oklab, var(--color-primary) 10%, white); border-radius: .45rem; }}

img {{ max-width: 100%; height: auto; display: block; }}
pre, code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace; }}
"""

def css_helpers_block() -> str:
    return f"""{CSS_HELPERS_SENTINEL}
:root {{
  --sp-1: .25rem; --sp-2: .5rem; --sp-3: 1rem; --sp-4: 1.5rem; --sp-5: 2rem;
}}
/* Utilities */
.mt-1 {{ margin-top: var(--sp-2); }} .mt-2 {{ margin-top: var(--sp-3); }} .mt-3 {{ margin-top: var(--sp-4); }}
.mb-1 {{ margin-bottom: var(--sp-2); }} .mb-2 {{ margin-bottom: var(--sp-3); }} .mb-3 {{ margin-bottom: var(--sp-4); }}
.text-center {{ text-align: center; }}
.container-narrow {{ max-width: 800px; margin-inline: auto; padding: 1rem; }}

/* Buttons */
.btn-lg {{ padding: .8rem 1.25rem; font-weight: 600; }}
.btn-outline {{ background: transparent; border: 1px solid var(--color-primary); color: var(--color-primary); }}

/* Cards */
.card:hover {{ transform: translateY(-1px); transition: transform .15s ease; }}
.card .muted {{ color: rgba(0,0,0,.65); }}

/* Nav */
.navbar ul {{ list-style: none; display: flex; gap: .6rem; padding-left: 0; }}
.navbar a {{ padding: .45rem .7rem; border-radius: .45rem; display: inline-block; }}
"""

# ---------------------- HTML Snippets & SVG Icons ----------------------

ICONS: Dict[str, str] = {
    "home": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            '<path d="M3 11l9-8 9 8"></path><path d="M9 22V12h6v10"></path></svg>',
    "star": '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
            '<path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"/></svg>',
    "check": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
    "x": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
          'stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
    "mail": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16v16H4z"/><path d="M22 6l-10 7L2 6"/></svg>',
    "phone": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2A19.86 '
             '19.86 0 0 1 3.11 7.18 2 2 0 0 1 5.1 5h3a2 2 0 0 1 2 1.72 12.44 12.44 0 0 0 .7 2.81 '
             '2 2 0 0 1-.45 2L9 13a16 16 0 0 0 6 6l1.47-1.35a2 2 0 0 1 2-.45 12.44 12.44 0 0 0 2.81.7 '
             '2 2 0 0 1 1.72 2z"/></svg>',
    "arrow-right": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                   'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                   '<path d="M5 12h14"/><path d="M12 5l7 7-7 7"/></svg>',
    "github": '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
              '<path d="M12 .5C5.73.5.77 5.46.77 11.73c0 4.9 3.18 9.06 7.6 10.53.56.1.77-.24.77-.54 '
              'v-1.87c-3.09.67-3.74-1.33-3.74-1.33-.5-1.26-1.22-1.6-1.22-1.6-.99-.68.07-.66.07-.66 '
              '1.1.08 1.68 1.13 1.68 1.13.98 1.67 2.58 1.19 3.21.9.1-.71.38-1.19.69-1.46-2.47-.28-5.07-1.23-5.07-5.46 '
              '0-1.21.43-2.2 1.13-2.98-.11-.28-.49-1.42.11-2.96 0 0 .93-.3 3.04 1.14a10.64 10.64 0 0 1 5.54 0 '
              'c2.11-1.44 3.04-1.14 3.04-1.14.6 1.54.22 2.68.11 2.96.7.78 1.13 1.77 1.13 2.98 0 4.24-2.61 5.17-5.1 5.45 '
              '.4.35.74 1.05.74 2.12v3.14c0 .3.21.64.77.54 4.42-1.47 7.6-5.63 7.6-10.53C23.23 5.46 18.27.5 12 .5z"/></svg>',
    "twitter": '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
               '<path d="M22 5.8c-.7.3-1.4.5-2.1.6.8-.5 1.3-1.2 1.6-2.1-.7.5-1.6.8-2.4 1-1.4-1.5-3.9-1.5-5.3 0-1.1 '
               '1.1-1.4 2.7-.8 4.1-3.1-.1-5.9-1.6-7.8-3.9-1 1.7-.5 3.8 1.1 4.9-.6 0-1.2-.2-1.7-.5 0 1.9 1.4 3.6 3.2 '
               '4-.6.2-1.3.2-1.9.1.6 1.6 2.1 2.8 3.9 2.8-1.5 1.2-3.4 1.9-5.4 1.9h-.7c2 1.3 4.3 2.1 6.8 2.1 '
               '8.2 0 12.7-6.9 12.4-13.1.8-.6 1.4-1.2 1.9-1.9z"/></svg>',
}

def html_section_hero() -> str:
    return """<section class="hero">
  <h2>Welcome!</h2>
  <p class="muted">Build beautiful sites with zero fuss.</p>
  <a class="btn btn-primary" href="#">Get started</a>
</section>
"""

def html_section_two_column() -> str:
    return """<section class="mt-3">
  <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); align-items: center;">
    <div>
      <h3>Headline</h3>
      <p>Explain your value proposition. Keep it short and focused.</p>
      <a class="btn btn-outline" href="#">Learn more</a>
    </div>
    <div><img src="assets/images/example.jpg" alt="Example image"></div>
  </div>
</section>
"""

def html_section_features() -> str:
    return """<section class="mt-3">
  <h3 class="text-center">Features</h3>
  <div class="grid">
    <div class="card"><h4>Speed</h4><p>Edit and preview instantly.</p></div>
    <div class="card"><h4>Simplicity</h4><p>HTML in, static site out.</p></div>
    <div class="card"><h4>Portability</h4><p>Publish anywhere.</p></div>
  </div>
</section>
"""

def html_section_cta() -> str:
    return """<section class="mt-3 text-center container-narrow">
  <h3>Ready to get started?</h3>
  <p class="muted">No build chain, no servers. Just publish the folder.</p>
  <a class="btn btn-lg btn-primary" href="#">Create my site</a>
</section>
"""

def html_section_faq() -> str:
    return """<section class="mt-3 container-narrow">
  <h3>FAQ</h3>
  <details><summary>Does this need hosting?</summary><p>You can host anywhere that serves static files (GitHub Pages, Netlify, S3...).</p></details>
  <details><summary>Can I use my own CSS?</summary><p>Yes, edit the Styles tab or paste your stylesheet.</p></details>
</section>
"""

def html_section_pricing() -> str:
    return """<section class="mt-3">
  <h3 class="text-center">Pricing</h3>
  <div class="grid">
    <div class="card"><h4>Starter</h4><p class="muted">$0</p><p>Basic features</p><a class="btn btn-primary" href="#">Choose</a></div>
    <div class="card"><h4>Pro</h4><p class="muted">$19</p><p>Everything you need</p><a class="btn btn-primary" href="#">Choose</a></div>
    <div class="card"><h4>Team</h4><p class="muted">$49</p><p>For small teams</p><a class="btn btn-primary" href="#">Choose</a></div>
  </div>
</section>
"""

def svg_wave(divider_color="#ffffff", flip=False) -> str:
    transform = ' transform="scale(1,-1)"' if flip else ""
    return f"""<svg width="100%" height="80" viewBox="0 0 1200 120" preserveAspectRatio="none"
  xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><g{transform}><path d="M0,0 C300,100 900,0 1200,80 L1200,120 L0,120 Z" fill="{divider_color}"/></g></svg>
"""

def svg_placeholder(width=800, height=400, bg="#e5e7eb", fg="#6b7280", label=None) -> str:
    label = label or f"{width}×{height}"
    # encode minimally for inline SVG as data URI
    svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'>
  <rect width='100%' height='100%' fill='{bg}'/>
  <text x='50%' y='50%' dominant-baseline='middle' text-anchor='middle'
        font-family='system-ui, -apple-system, Segoe UI, Roboto' font-size='24' fill='{fg}'>{label}</text>
</svg>"""
    import urllib.parse
    data = urllib.parse.quote(svg)
    return f"<img src='data:image/svg+xml;utf8,{data}' alt='{label}' width='{width}' height='{height}'>"

# ---------------------- Rendering (copies images) ----------------------

def _env_from_memory() -> Environment:
    return Environment(
        loader=DictLoader({"base.html.j2": BASE_TEMPLATE}),
        autoescape=select_autoescape(["html", "xml"]),
    )

def _copy_images(images: List[str], out_root: Path) -> None:
    if not images:
        return
    img_dir = out_root / "assets" / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    for src in images:
        try:
            src_path = Path(src)
            if src_path.exists():
                shutil.copy2(src_path, img_dir / src_path.name)
        except Exception:
            # best-effort; skip problematic files
            pass

def render_site(project: Project, output_dir: str | Path) -> None:
    """Render the project to a static site at output_dir (HTML+CSS+assets)."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write CSS
    css_dir = output_dir / "assets" / "css"
    css_dir.mkdir(parents=True, exist_ok=True)
    (css_dir / "style.css").write_text(project.css, encoding="utf-8")

    # Copy images
    _copy_images(project.images, output_dir)

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
            body_font=project.fonts["body"],
            heading_font=project.fonts["heading"],
            text_color=project.palette["text"],
            surface_color=project.palette["surface"],
        )
        (output_dir / page.filename).write_text(html, encoding="utf-8")

# ---------------------- UI ----------------------

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 820)

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

        # Middle/Right: Tabs + Preview
        mid = QtWidgets.QTabWidget(self)
        mid.setDocumentMode(True)

        # Editors tab
        self.html_editor = QtWidgets.QPlainTextEdit(mid)
        self.html_editor.setPlaceholderText("<h2>Hello</h2>\n<p>Edit your page HTML here.</p>")

        self.css_editor = QtWidgets.QPlainTextEdit(mid)
        self.css_editor.setPlaceholderText("/* Global site CSS */")

        mid.addTab(self.html_editor, "Page HTML")
        mid.addTab(self.css_editor, "Styles (CSS)")

        # Design tab
        self.design_tab = self._build_design_tab()
        mid.addTab(self.design_tab, "Design")

        # Assets tab
        self.assets_tab = self._build_assets_tab()
        mid.addTab(self.assets_tab, "Assets")

        # Right: preview
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
        splitter.setSizes([240, 640, 420])

        # Ensure a non-None status bar and keep a typed handle for Pylance
        if self.statusBar() is None:
            self.setStatusBar(QtWidgets.QStatusBar(self))
        self.status: QtWidgets.QStatusBar = cast(QtWidgets.QStatusBar, self.statusBar())

    def _build_design_tab(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget(self)
        l = QtWidgets.QFormLayout(w)
        l.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

        self.cmb_theme = QtWidgets.QComboBox(w)
        self.cmb_theme.addItems(list(THEME_PRESETS.keys()))

        # Color pickers
        def mk_color_row(label: str) -> Tuple[QtWidgets.QLineEdit, QtWidgets.QPushButton]:
            line = QtWidgets.QLineEdit(w); line.setMaxLength(9)
            btn = QtWidgets.QPushButton("Pick", w)
            hl = QtWidgets.QHBoxLayout(); hl.addWidget(line); hl.addWidget(btn)
            box = QtWidgets.QWidget(w); box.setLayout(hl)
            l.addRow(label, box)
            return line, btn

        self.txt_primary, btn_primary = mk_color_row("Primary")
        self.txt_surface, btn_surface = mk_color_row("Surface")
        self.txt_text, btn_text = mk_color_row("Text")

        # Fonts
        self.cmb_heading = QtWidgets.QComboBox(w); self.cmb_heading.addItems(list(FONT_STACKS.keys()))
        self.cmb_body = QtWidgets.QComboBox(w);    self.cmb_body.addItems(list(FONT_STACKS.keys()))
        l.addRow("Headings font", self.cmb_heading)
        l.addRow("Body font", self.cmb_body)

        # Buttons
        hb = QtWidgets.QHBoxLayout()
        self.btn_apply_design = QtWidgets.QPushButton("Apply (Replace CSS)", w)
        self.btn_append_helpers = QtWidgets.QPushButton("Append CSS Helpers", w)
        hb.addWidget(self.btn_apply_design); hb.addWidget(self.btn_append_helpers)
        l.addRow("", hb)

        # Wire pickers
        def pick_color(edit: QtWidgets.QLineEdit):
            start = QtGui.QColor(edit.text() or "#ffffff")
            c = QtWidgets.QColorDialog.getColor(start, w, "Pick Color")
            if c.isValid():
                edit.setText(c.name())

        btn_primary.clicked.connect(lambda: pick_color(self.txt_primary))
        btn_surface.clicked.connect(lambda: pick_color(self.txt_surface))
        btn_text.clicked.connect(lambda: pick_color(self.txt_text))

        self.btn_apply_design.clicked.connect(self.apply_design_to_css)
        self.btn_append_helpers.clicked.connect(self.append_css_helpers)

        return w

    def _build_assets_tab(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget(self)
        v = QtWidgets.QVBoxLayout(w)
        self.assets_list = QtWidgets.QListWidget(w)
        hb = QtWidgets.QHBoxLayout()
        self.btn_add_asset = QtWidgets.QPushButton("Add Images…", w)
        self.btn_remove_asset = QtWidgets.QPushButton("Remove", w)
        self.btn_insert_img = QtWidgets.QPushButton("Insert <img>", w)
        hb.addWidget(self.btn_add_asset); hb.addWidget(self.btn_remove_asset); hb.addWidget(self.btn_insert_img)
        v.addWidget(self.assets_list, 1); v.addLayout(hb)

        self.btn_add_asset.clicked.connect(self.add_assets)
        self.btn_remove_asset.clicked.connect(self.remove_selected_asset)
        self.btn_insert_img.clicked.connect(self.insert_selected_img_tag)

        return w

    def _build_menu(self) -> None:
        bar = self.menuBar()

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

        # Insert menu (HTML helpers, icons, graphics)
        m_insert = cast(QtWidgets.QMenu, bar.addMenu("&Insert"))
        sec   = cast(QtWidgets.QMenu, m_insert.addMenu("Section"))
        gfx   = cast(QtWidgets.QMenu, m_insert.addMenu("Graphics"))
        icons = cast(QtWidgets.QMenu, m_insert.addMenu("Icon (inline SVG)"))

        self._add_action(sec, "Hero",                      lambda: self.insert_html(html_section_hero()))
        self._add_action(sec, "Features grid",             lambda: self.insert_html(html_section_features()))
        self._add_action(sec, "Two‑column (image + text)", lambda: self.insert_html(html_section_two_column()))
        self._add_action(sec, "Call‑to‑Action",            lambda: self.insert_html(html_section_cta()))
        self._add_action(sec, "FAQ",                       lambda: self.insert_html(html_section_faq()))
        self._add_action(sec, "Pricing",                   lambda: self.insert_html(html_section_pricing()))

        self._add_action(gfx, "Wave divider (top)",    self._insert_wave_top)
        self._add_action(gfx, "Wave divider (bottom)", self._insert_wave_bottom)
        self._add_action(gfx, "Placeholder image…",    self.insert_placeholder_dialog)

        for name in sorted(ICONS.keys()):
            self._add_action(icons, name, lambda n=name: self.insert_html(ICONS[n]))

        # CSS menu
        m_css = cast(QtWidgets.QMenu, bar.addMenu("&CSS"))
        self._add_action(m_css, "Append CSS helpers", self.append_css_helpers)
        self._add_action(m_css, "Reset CSS to Design", self.apply_design_to_css)

        # Help
        m_help = cast(QtWidgets.QMenu, bar.addMenu("&Help"))
        self.act_about = QtGui.QAction("About", self)
        m_help.addAction(self.act_about)

    def _add_action(self, menu: Optional[QtWidgets.QMenu], title: str, slot) -> None:
        assert menu is not None, "Menu unexpectedly None"
        act = QtGui.QAction(title, self)
        act.triggered.connect(slot)
        menu.addAction(act)

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
        # Initialize design
        palette = dict(DEFAULT_PALETTE)
        fonts = dict(DEFAULT_FONTS)
        self.project = Project(
            name=name.strip(),
            pages=[Page(filename="index.html", title="Home", html=DEFAULT_INDEX_HTML)],
            css=generate_base_css(palette, fonts),
            palette=palette,
            fonts=fonts,
            images=[],
            output_dir=None,
        )
        self.project_path = None
        self._refresh_pages_list(select_index=0)
        self._sync_design_tab_from_project()
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
        self._sync_design_tab_from_project()
        self._refresh_assets_list()
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

    # ---------- Design tab logic ----------
    def _sync_design_tab_from_project(self) -> None:
        if not self.project:
            return
        pal = self.project.palette
        fonts = self.project.fonts
        self.txt_primary.setText(pal["primary"])
        self.txt_surface.setText(pal["surface"])
        self.txt_text.setText(pal["text"])
        # set combo defaults (fallback to System UI if unknown)
        def key_for_stack(stack: str) -> str:
            for k, v in FONT_STACKS.items():
                if v == stack:
                    return k
            return "System UI"
        self.cmb_heading.setCurrentText(key_for_stack(fonts["heading"]))
        self.cmb_body.setCurrentText(key_for_stack(fonts["body"]))
        # theme combo is purely preset; not auto-detected

    def apply_design_to_css(self) -> None:
        if not self.project:
            return
        # If a preset is chosen, use it; otherwise use custom fields
        preset = THEME_PRESETS.get(self.cmb_theme.currentText())
        pal = dict(preset) if preset else {}
        # override with explicit fields
        pal["primary"] = self.txt_primary.text() or pal.get("primary", DEFAULT_PALETTE["primary"])
        pal["surface"] = self.txt_surface.text() or pal.get("surface", DEFAULT_PALETTE["surface"])
        pal["text"]    = self.txt_text.text() or pal.get("text", DEFAULT_PALETTE["text"])

        fonts = {
            "heading": FONT_STACKS.get(self.cmb_heading.currentText(), FONT_STACKS["System UI"]),
            "body":    FONT_STACKS.get(self.cmb_body.currentText(), FONT_STACKS["System UI"]),
        }

        # Update project + CSS editor
        self.project.palette = pal
        self.project.fonts = fonts
        base_css = generate_base_css(pal, fonts)
        # Preserve helpers block if present
        helpers = ""
        if CSS_HELPERS_SENTINEL in self.project.css:
            helpers = "\n\n" + self.project.css.split(CSS_HELPERS_SENTINEL, 1)[1]
            helpers = CSS_HELPERS_SENTINEL + helpers
        self.project.css = base_css + ("\n\n" + helpers if helpers else "")
        self.css_editor.blockSignals(True)
        self.css_editor.setPlainText(self.project.css)
        self.css_editor.blockSignals(False)
        self.update_preview()

    def append_css_helpers(self) -> None:
        if not self.project:
            return
        if CSS_HELPERS_SENTINEL in self.project.css:
            QtWidgets.QMessageBox.information(self, "Already added", "CSS helpers are already present.")
            return
        self.project.css += ("\n\n" if self.project.css else "") + css_helpers_block()
        self.css_editor.blockSignals(True)
        self.css_editor.setPlainText(self.project.css)
        self.css_editor.blockSignals(False)
        self.update_preview()

    # ---------- Insert helpers ----------
    def insert_html(self, snippet: str) -> None:
        cursor = self.html_editor.textCursor()
        cursor.insertText("\n" + snippet + "\n")
        self.html_editor.setTextCursor(cursor)
        self.update_preview()

    def insert_placeholder_dialog(self) -> None:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Insert placeholder image")
        layout = QtWidgets.QFormLayout(dlg)
        w = QtWidgets.QLineEdit("800"); h = QtWidgets.QLineEdit("400")
        bg = QtWidgets.QLineEdit("#e5e7eb"); fg = QtWidgets.QLineEdit("#6b7280")
        label = QtWidgets.QLineEdit("")
        layout.addRow("Width", w); layout.addRow("Height", h)
        layout.addRow("Background", bg); layout.addRow("Foreground", fg)
        layout.addRow("Label (optional)", label)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                        QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        layout.addRow(bb)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            try:
                img = svg_placeholder(int(w.text()), int(h.text()), bg.text() or "#e5e7eb", fg.text() or "#6b7280", label.text() or None)
                self.insert_html(img)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Could not create placeholder:\n{e}")

    # ---------- Assets ----------
    def _refresh_assets_list(self) -> None:
        self.assets_list.clear()
        if not self.project:
            return
        for p in self.project.images:
            self.assets_list.addItem(Path(p).name)

    def add_assets(self) -> None:
        if not self.project:
            return
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Add images", "", "Images (*.png *.jpg *.jpeg *.gif *.svg *.webp)")
        if not files:
            return
        # keep unique
        existing = set(self.project.images)
        for f in files:
            if f not in existing:
                self.project.images.append(f)
        self._refresh_assets_list()
        self.update_preview()  # so preview copy includes them

    def remove_selected_asset(self) -> None:
        if not self.project:
            return
        row = self.assets_list.currentRow()
        if row < 0 or row >= len(self.project.images):
            return
        del self.project.images[row]
        self._refresh_assets_list()
        self.update_preview()

    def insert_selected_img_tag(self) -> None:
        if not self.project:
            return
        row = self.assets_list.currentRow()
        if row < 0 or row >= len(self.project.images):
            return
        fname = Path(self.project.images[row]).name
        tag = f'<img src="assets/images/{fname}" alt="{Path(fname).stem}">'
        self.insert_html(tag)

    # ---------- Misc ----------
    def _pal(self) -> Dict[str, str]:
        # Safe palette accessor for type checker
        return self.project.palette if self.project else dict(DEFAULT_PALETTE)

    def _insert_wave_top(self) -> None:
        self.insert_html(svg_wave(self._pal()["surface"], False))

    def _insert_wave_bottom(self) -> None:
        self.insert_html(svg_wave(self._pal()["surface"], True))

    def show_about(self) -> None:
        QtWidgets.QMessageBox.information(
            self, "About",
            f"{APP_TITLE}\n\nA friendly static site builder with themes, helpers, and graphics."
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
