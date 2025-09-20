"""Webineer Site Builder — enhanced single-file PyQt6 app."""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWebEngineWidgets import QWebEngineView
from jinja2 import DictLoader, Environment, select_autoescape

APP_TITLE = "Webineer Site Builder"
APP_ICON_PATH = "icon.ico"
SITE_VERSION = 2


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def ensure_app_icon(widget: QtWidgets.QWidget) -> None:
    """Attempt to set the app icon on a widget."""
    icon_path = Path(APP_ICON_PATH)
    if icon_path.exists():
        widget.setWindowIcon(QtGui.QIcon(str(icon_path)))


def app_data_dir() -> Path:
    """Return the platform-specific application data directory."""
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA", Path.home()))
    else:
        base = Path.home() / ".local" / "share"
    target = base / "Webineer"
    target.mkdir(parents=True, exist_ok=True)
    return target


RECENTS_PATH = app_data_dir() / "recents.json"
SETTINGS_PATH = app_data_dir() / "settings.json"
PREVIEWS_DIR = app_data_dir() / "Previews"
PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)


class SettingsManager:
    """Very small settings helper storing JSON data."""

    def __init__(self) -> None:
        self._settings: Dict[str, str] = {}
        self.load()

    def load(self) -> None:
        if SETTINGS_PATH.exists():
            try:
                self._settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            except Exception:
                self._settings = {}

    def save(self) -> None:
        SETTINGS_PATH.write_text(json.dumps(self._settings, indent=2), encoding="utf-8")

    def get(self, key: str, default: str = "") -> str:
        return self._settings.get(key, default)

    def set(self, key: str, value: str) -> None:
        self._settings[key] = value
        self.save()

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Page:
    filename: str
    title: str
    html: str


@dataclass
class AssetImage:
    name: str
    data_base64: str
    width: int
    height: int
    mime: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "data_base64": self.data_base64,
            "width": self.width,
            "height": self.height,
            "mime": self.mime,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "AssetImage":
            def safe_int(val, default=0):
                try:
                    return int(val)
                except (TypeError, ValueError):
                    return default

            return cls(
                name=str(data.get("name", "image.png")),
                data_base64=str(data.get("data_base64", "")),
                width=safe_int(data.get("width", 0)),
                height=safe_int(data.get("height", 0)),
                mime=str(data.get("mime", "image/png")),
            )


DEFAULT_PALETTE = {
    "primary": "#2563eb",
    "surface": "#f8fafc",
    "text": "#0f172a",
}

DEFAULT_FONTS = {
    "heading": "'Poppins', 'Segoe UI', sans-serif",
    "body": "'Inter', 'Segoe UI', sans-serif",
}


@dataclass
class Project:
    name: str = "My Site"
    pages: List[Page] = field(default_factory=list)
    css: str = ""
    palette: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PALETTE))
    fonts: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_FONTS))
    images: List[AssetImage] = field(default_factory=list)
    template_key: str = "starter"
    theme_preset: str = "Calm Sky"
    use_main_js: bool = False
    output_dir: Optional[str] = None
    version: int = SITE_VERSION

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "pages": [asdict(p) for p in self.pages],
            "css": self.css,
            "palette": self.palette,
            "fonts": self.fonts,
            "images": [img.to_dict() for img in self.images],
            "template_key": self.template_key,
            "theme_preset": self.theme_preset,
            "use_main_js": self.use_main_js,
            "output_dir": self.output_dir,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Project":
            def safe_int(val, default=1):
                try:
                    return int(val)
                except (TypeError, ValueError):
                    return default

            def safe_list(val):
                return val if isinstance(val, list) else []

            def safe_dict(val, default):
                if isinstance(val, dict):
                    return {str(k): str(v) for k, v in val.items()}
                return dict(default)

            version = safe_int(data.get("version", 1))
            if version == 1:
                data = migrate_project_v1_to_v2(data)
            pages = [Page(**p) for p in safe_list(data.get("pages", []))]
            images = [AssetImage.from_dict(img) for img in safe_list(data.get("images", []))]
            palette = safe_dict(data.get("palette", DEFAULT_PALETTE), DEFAULT_PALETTE)
            fonts = safe_dict(data.get("fonts", DEFAULT_FONTS), DEFAULT_FONTS)
            output_dir = data.get("output_dir")
            if output_dir is not None and not isinstance(output_dir, str):
                output_dir = str(output_dir)
            return cls(
                name=str(data.get("name", "My Site")),
                pages=pages,
                css=str(data.get("css", "")),
                palette=palette,
                fonts=fonts,
                images=images,
                template_key=str(data.get("template_key", "starter")),
                theme_preset=str(data.get("theme_preset", "Calm Sky")),
                use_main_js=bool(data.get("use_main_js", False)),
                output_dir=output_dir,
                version=version,
            )

# ---------------------------------------------------------------------------
# Templates & presets
# ---------------------------------------------------------------------------


@dataclass
class TemplateDefinition:
    key: str
    title: str
    description: str
    default_pages: List[Tuple[str, str]]


TEMPLATES: Dict[str, TemplateDefinition] = {
    "starter": TemplateDefinition(
        key="starter",
        title="Starter",
        description="A clean one-page layout with a hero, features, and footer.",
        default_pages=[
            (
                "index.html",
                """
<section class=\"hero stack center\">
  <h1>Welcome to {{site_name}}</h1>
  <p class=\"lead\">A friendly place to share what you do.</p>
  <div class=\"stack-inline\">
    <a class=\"btn btn-primary\" href=\"#\">Get Started</a>
    <a class=\"btn btn-ghost\" href=\"#\">Learn more</a>
  </div>
</section>
<section class=\"section\">
  <h2 class=\"eyebrow\">Highlights</h2>
  <div class=\"grid split-3\">
    <article class=\"card\">
      <h3>Fast setup</h3>
      <p>Point, click, publish. Everything stays simple.</p>
    </article>
    <article class=\"card\">
      <h3>Polished</h3>
      <p>Beautiful defaults with room to customize.</p>
    </article>
    <article class=\"card\">
      <h3>Ready to grow</h3>
      <p>Add pages and content blocks as you need them.</p>
    </article>
  </div>
</section>
<section class=\"section\">
  <h2>Next steps</h2>
  <div class=\"callout\">
    <h3>Let's build something great.</h3>
    <p>Use the Insert menu to drop in sections, galleries, contact forms, and more.</p>
  </div>
</section>
                """,
            )
        ],
    ),
    "portfolio": TemplateDefinition(
        key="portfolio",
        title="Portfolio",
        description="Showcase projects with case studies, testimonials, and contact.",
        default_pages=[
            (
                "index.html",
                """
<section class=\"hero hero-split\">
  <div class=\"stack\">
    <p class=\"eyebrow\">Showcase your work</p>
    <h1>Hi, I'm {{site_name}}</h1>
    <p class=\"lead\">I help teams design thoughtful, accessible web experiences.</p>
    <div class=\"stack-inline\">
      <a class=\"btn btn-primary\" href=\"projects.html\">See projects</a>
      <a class=\"btn btn-soft\" href=\"contact.html\">Work together</a>
    </div>
  </div>
  <figure class=\"card media\">
    <img src=\"assets/images/placeholder-portrait.png\" alt=\"Portrait\">
  </figure>
</section>
<section class=\"section\">
  <h2>Featured work</h2>
  <div class=\"grid split-2\">
    <article class=\"card\">
      <h3>Case Study One</h3>
      <p>Results-driven redesign for a SaaS platform.</p>
      <a class=\"btn btn-link\" href=\"projects.html\">Read case study</a>
    </article>
    <article class=\"card\">
      <h3>Case Study Two</h3>
      <p>Growth-focused marketing site for a startup.</p>
      <a class=\"btn btn-link\" href=\"projects.html\">Read case study</a>
    </article>
  </div>
</section>
<section class=\"section section-alt\">
  <h2>What clients say</h2>
  <div class=\"testimonials\">
    <figure>
      <blockquote>
        <p>“They went above and beyond. We shipped in record time.”</p>
      </blockquote>
      <figcaption>Alex Morgan · Product Lead</figcaption>
    </figure>
  </div>
</section>
                """,
            ),
            (
                "projects.html",
                """
<section class=\"section\">
  <h1>Projects</h1>
  <div class=\"grid split-2\">
    <article class=\"card\">
      <h2>Project Alpha</h2>
      <p>Short description of a flagship project outcome.</p>
      <ul class=\"list-check\">
        <li>Insightful research</li>
        <li>Accessible design system</li>
        <li>Launch support</li>
      </ul>
    </article>
    <article class=\"card\">
      <h2>Project Beta</h2>
      <p>A compact case study for a secondary engagement.</p>
    </article>
  </div>
</section>
                """,
            ),
            (
                "contact.html",
                """
<section class=\"section\">
  <h1>Let's connect</h1>
  <p>Ready to collaborate? Tell me about the project and timing.</p>
  <form class=\"stack form\">
    <label>Name<input type=\"text\" placeholder=\"Your name\" required></label>
    <label>Email<input type=\"email\" placeholder=\"you@example.com\" required></label>
    <label>How can I help?<textarea rows=\"4\"></textarea></label>
    <button class=\"btn btn-primary\" type=\"submit\">Send message</button>
  </form>
</section>
                """,
            ),
        ],
    ),
    "resource": TemplateDefinition(
        key="resource",
        title="Resource",
        description="Organize documentation, tutorials, or knowledge bases.",
        default_pages=[
            (
                "index.html",
                """
<section class=\"hero\">
  <h1>{{site_name}} Resource Hub</h1>
  <p class=\"lead\">Find guides, FAQs, and quick tips to get the most out of your product.</p>
  <form class=\"stack-inline\" role=\"search\">
    <input class=\"input\" type=\"search\" placeholder=\"Search articles\">
    <button class=\"btn btn-primary\" type=\"submit\">Search</button>
  </form>
</section>
<section class=\"section\">
  <h2>Popular guides</h2>
  <div class=\"grid split-3\">
    <article class=\"card\">
      <h3>Getting started</h3>
      <p>Set up and launch in under ten minutes.</p>
      <a class=\"btn btn-link\" href=\"docs.html\">Read guide</a>
    </article>
    <article class=\"card\">
      <h3>Team workflows</h3>
      <p>Collaborate smoothly across your organization.</p>
      <a class=\"btn btn-link\" href=\"docs.html\">Read guide</a>
    </article>
    <article class=\"card\">
      <h3>Troubleshooting</h3>
      <p>Quick answers for common questions.</p>
      <a class=\"btn btn-link\" href=\"docs.html\">Read guide</a>
    </article>
  </div>
</section>
<section class=\"section section-alt\">
  <h2>Recently updated</h2>
  <div class=\"timeline\">
    <div class=\"timeline-item\">
      <span class=\"badge\">Apr</span>
      <div>
        <h3>Version 2.1 release notes</h3>
        <p>Improved navigation, accessibility, and performance tweaks.</p>
      </div>
    </div>
    <div class=\"timeline-item\">
      <span class=\"badge\">Mar</span>
      <div>
        <h3>New onboarding lessons</h3>
        <p>Three quick videos to help new teammates succeed.</p>
      </div>
    </div>
  </div>
</section>
                """,
            ),
            (
                "docs.html",
                """
<section class=\"section\">
  <h1>Documentation</h1>
  <div class=\"tabs\">
    <input checked id=\"tab-intro\" name=\"docs-tabs\" type=\"radio\">
    <label for=\"tab-intro\">Introduction</label>
    <div class=\"tab-content\">
      <p>Explain the basics of your product or service here.</p>
    </div>
    <input id=\"tab-guides\" name=\"docs-tabs\" type=\"radio\">
    <label for=\"tab-guides\">Guides</label>
    <div class=\"tab-content\">
      <p>Break down tasks into clear, step-by-step instructions.</p>
    </div>
    <input id=\"tab-faq\" name=\"docs-tabs\" type=\"radio\">
    <label for=\"tab-faq\">FAQ</label>
    <div class=\"tab-content\">
      <p>Answer common questions with short, conversational copy.</p>
    </div>
  </div>
</section>
                """,
            ),
        ],
    ),
}


THEME_PRESETS: Dict[str, Dict[str, str]] = {
    "Calm Sky": {"primary": "#2563eb", "surface": "#f8fafc", "text": "#0f172a"},
    "Sunset": {"primary": "#f97316", "surface": "#fff7ed", "text": "#431407"},
    "Forest": {"primary": "#15803d", "surface": "#f0fdf4", "text": "#052e16"},
    "Midnight": {"primary": "#6366f1", "surface": "#111827", "text": "#f9fafb"},
    "Rose": {"primary": "#ec4899", "surface": "#fdf2f8", "text": "#831843"},
}


FONT_STACKS = [
    "'Inter', 'Segoe UI', sans-serif",
    "'Poppins', 'Segoe UI', sans-serif",
    "'Merriweather', Georgia, serif",
    "'Source Sans Pro', 'Helvetica Neue', Arial, sans-serif",
    "'Fira Sans', 'Segoe UI', sans-serif",
    "'Nunito', 'Segoe UI', sans-serif",
]

# ---------------------------------------------------------------------------
# CSS Helpers & Snippets
# ---------------------------------------------------------------------------


CSS_HELPERS_SENTINEL = "/* === Webineer helper styles v2 === */"
CSS_HELPERS_BLOCK = f"""{CSS_HELPERS_SENTINEL}
:root {{
  --space-0: 0;
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-5: 1.5rem;
  --space-6: 2rem;
  --space-7: 3rem;
  --radius-sm: 0.5rem;
  --radius-md: 0.75rem;
  --radius-lg: 1.5rem;
  --shadow-sm: 0 2px 12px rgba(15, 23, 42, 0.08);
  --shadow-lg: 0 20px 60px rgba(15, 23, 42, 0.12);
  --max-width: 1100px;
}}
body {{
  background: var(--color-surface, #f8fafc);
  color: var(--color-text, #0f172a);
}}
.container {{
  max-width: var(--max-width);
  margin: 0 auto;
  padding: var(--space-6) var(--space-4);
}}
.section {{
  padding: var(--space-7) 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}}
.section-alt {{
  background: rgba(148, 163, 184, 0.1);
  padding: var(--space-7) 0;
}}
.stack {{
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}}
.stack-inline {{
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: center;
}}
.center {{
  text-align: center;
  align-items: center;
}}
.grid {{
  display: grid;
  gap: var(--space-4);
}}
.split-2 {{
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}}
.split-3 {{
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
}}
.hero {{
  padding: var(--space-7) var(--space-4);
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, rgba(59,130,246,.12), rgba(59,130,246,.03));
  box-shadow: var(--shadow-sm);
  display: grid;
  gap: var(--space-5);
}}
.hero-split {{
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  align-items: center;
}}
.lead {{
  font-size: 1.125rem;
  color: rgba(15, 23, 42, 0.75);
}}
.eyebrow {{
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 0.75rem;
  color: rgba(15, 23, 42, 0.6);
}}
.btn {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  padding: 0.6rem 1.4rem;
  border-radius: 999px;
  font-weight: 600;
  transition: all .2s ease;
  border: 1px solid transparent;
}}
.btn-primary {{
  background: var(--color-primary, #2563eb);
  color: #fff;
  box-shadow: var(--shadow-sm);
}}
.btn-soft {{
  background: rgba(37, 99, 235, 0.12);
  color: var(--color-primary, #2563eb);
}}
.btn-outline {{
  border-color: rgba(15, 23, 42, 0.12);
  color: var(--color-text, #0f172a);
  background: transparent;
}}
.btn-ghost {{
  background: transparent;
  color: var(--color-text, #0f172a);
}}
.btn-pill {{
  border-radius: 999px;
}}
.btn-gradient {{
  background: linear-gradient(135deg, var(--color-primary, #2563eb), #a855f7);
  color: white;
  box-shadow: var(--shadow-lg);
}}
.btn-link {{
  padding: 0;
  border: none;
  background: none;
  color: var(--color-primary, #2563eb);
}}
.card {{
  background: white;
  border-radius: var(--radius-md);
  padding: var(--space-5);
  box-shadow: var(--shadow-sm);
}}
.card.media {{
  padding: var(--space-3);
  background: rgba(255,255,255,.72);
  border: 1px solid rgba(148,163,184,.25);
}}
.callout {{
  border-radius: var(--radius-md);
  background: rgba(37, 99, 235, 0.08);
  padding: var(--space-5);
  border: 1px solid rgba(37, 99, 235, 0.25);
}}
.alert {{
  border-radius: var(--radius-md);
  padding: var(--space-4);
  border: 1px solid rgba(148,163,184,.4);
  background: rgba(148,163,184,.12);
}}
.badge {{
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.6rem;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.12);
  color: var(--color-primary, #2563eb);
  font-weight: 600;
  font-size: 0.75rem;
}}
.divider {{
  height: 1px;
  background: rgba(148, 163, 184, 0.3);
  margin: var(--space-5) 0;
}}
.tabs {{
  display: grid;
  gap: 0.5rem;
}}
.tabs > input {{
  display: none;
}}
.tabs > label {{
  padding: 0.6rem 1rem;
  border-radius: var(--radius-sm);
  background: rgba(148,163,184,.14);
  cursor: pointer;
}}
.tabs > input:checked + label {{
  background: var(--color-primary, #2563eb);
  color: white;
}}
.tabs > input:checked + label + .tab-content {{
  display: block;
}}
.tab-content {{
  display: none;
  padding: 1rem;
  background: white;
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-sm);
}}
.timeline {{
  display: grid;
  gap: var(--space-4);
}}
.timeline-item {{
  display: grid;
  gap: var(--space-2);
  grid-template-columns: auto 1fr;
  align-items: start;
}}
.list-check {{
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: var(--space-2);
}}
.list-check li::before {{
  content: "✔";
  color: var(--color-primary, #2563eb);
  margin-right: .5rem;
}}
.inline-tags {{
  display: inline-flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}}
.inline-tags span {{
  padding: 0.25rem 0.75rem;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.14);
}}
.gallery {{
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}}
.gallery figure {{
  background: white;
  border-radius: var(--radius-sm);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}}
.testimonials {{
  display: grid;
  gap: var(--space-4);
}}
.testimonials blockquote {{
  font-size: 1.1rem;
  line-height: 1.6;
  margin: 0;
}}
.steps {{
  display: grid;
  gap: var(--space-4);
}}
.steps article {{
  display: grid;
  gap: var(--space-2);
  padding: var(--space-4);
  border-radius: var(--radius-sm);
  background: rgba(37, 99, 235, 0.06);
}}
.faq {{
  border-radius: var(--radius-sm);
  border: 1px solid rgba(148,163,184,0.35);
  background: white;
  padding: var(--space-3);
}}
.faq summary {{
  cursor: pointer;
  font-weight: 600;
}}
.max-w-sm {{ max-width: 420px; margin: 0 auto; }}
.max-w-md {{ max-width: 640px; margin: 0 auto; }}
.max-w-lg {{ max-width: 960px; margin: 0 auto; }}
.main-container {{ max-width: var(--max-width); margin: 0 auto; padding: 0 var(--space-4); }}
.form input, .form textarea {{
  padding: 0.65rem 0.85rem;
  border-radius: var(--radius-sm);
  border: 1px solid rgba(148,163,184,0.5);
}}
.alert-info {{ background: rgba(37, 99, 235, 0.12); border-color: rgba(37, 99, 235, 0.3); }}
.alert-success {{ background: rgba(16, 185, 129, 0.15); border-color: rgba(16, 185, 129, 0.32); }}
.alert-warning {{ background: rgba(234, 179, 8, 0.2); border-color: rgba(234, 179, 8, 0.42); }}
.alert-danger {{ background: rgba(239, 68, 68, 0.16); border-color: rgba(239, 68, 68, 0.36); }}
"""

MAIN_JS_SNIPPET = """// Lightweight helpers for Webineer components
(function(){
  const navToggle = document.querySelector('[data-toggle="mobile-nav"]');
  const navMenu = document.querySelector('[data-mobile-nav]');
  if(navToggle && navMenu){
    navToggle.addEventListener('click', () => {
      const expanded = navToggle.getAttribute('aria-expanded') === 'true';
      navToggle.setAttribute('aria-expanded', (!expanded).toString());
      navMenu.classList.toggle('is-open');
    });
  }
  document.querySelectorAll('details').forEach((detail) => {
    detail.addEventListener('toggle', () => {
      if(detail.open){
        detail.scrollIntoView({behavior: 'smooth', block: 'nearest'});
      }
    });
  });
})();
"""


@dataclass
class Snippet:
    label: str
    html: str
    requires_js: bool = False


SECTIONS_SNIPPETS: Dict[str, Snippet] = {
    "hero": Snippet("Hero spotlight", """
<section class=\"hero\">
  <h1>Headline that inspires confidence</h1>
  <p class=\"lead\">Explain what you offer and the value in a friendly tone.</p>
  <div class=\"stack-inline\">
    <a class=\"btn btn-primary\" href=\"#\">Primary call to action</a>
    <a class=\"btn btn-ghost\" href=\"#\">Secondary link</a>
  </div>
</section>
"""),
    "hero-split": Snippet("Hero with image", """
<section class=\"hero hero-split\">
  <div class=\"stack\">
    <p class=\"eyebrow\">New announcement</p>
    <h1>Highlight the benefit</h1>
    <p class=\"lead\">Share how you solve the problem, not the feature list.</p>
    <div class=\"stack-inline\">
      <a class=\"btn btn-primary\" href=\"#\">Get started</a>
      <a class=\"btn btn-soft\" href=\"#\">Talk to us</a>
    </div>
  </div>
  <figure class=\"card media\">
    <img src=\"assets/images/placeholder-wide.png\" alt=\"Illustration\">
  </figure>
</section>
"""),
    "header": Snippet("Header with navigation", """
<header class=\"site-header\">
  <div class=\"main-container stack-inline\">
    <a class=\"site-logo\" href=\"index.html\">Brand</a>
    <button class=\"btn btn-ghost\" data-toggle=\"mobile-nav\" aria-expanded=\"false\">Menu</button>
    <nav class=\"site-nav\" data-mobile-nav>
      <ul class=\"stack-inline\">
        <li><a href=\"index.html\">Home</a></li>
        <li><a href=\"#services\">Services</a></li>
        <li><a href=\"#about\">About</a></li>
        <li><a class=\"btn btn-primary btn-pill\" href=\"#contact\">Contact</a></li>
      </ul>
    </nav>
  </div>
</header>
""", requires_js=True),
    "footer": Snippet("Footer", """
<footer class=\"section\">
  <div class=\"grid split-3\">
    <div>
      <h2>About</h2>
      <p>Brief description about your organization or project.</p>
    </div>
    <div>
      <h2>Links</h2>
      <ul class=\"stack\" style=\"list-style:none;padding:0;\">
        <li><a href=\"#\">Pricing</a></li>
        <li><a href=\"#\">Support</a></li>
        <li><a href=\"#\">Blog</a></li>
      </ul>
    </div>
    <div>
      <h2>Stay in touch</h2>
      <p>Share your email to receive updates.</p>
      <form class=\"stack-inline\">
        <input class=\"input\" type=\"email\" placeholder=\"email@domain.com\">
        <button class=\"btn btn-primary\" type=\"submit\">Notify me</button>
      </form>
    </div>
  </div>
  <p>© {{site_name}} — Built with love.</p>
</footer>
"""),
    "gallery": Snippet("Gallery", """
<section class=\"section\">
  <h2>Gallery</h2>
  <div class=\"gallery\">
    <figure><img src=\"assets/images/placeholder-wide.png\" alt=\"Item one\"></figure>
    <figure><img src=\"assets/images/placeholder-wide.png\" alt=\"Item two\"></figure>
    <figure><img src=\"assets/images/placeholder-wide.png\" alt=\"Item three\"></figure>
  </div>
</section>
"""),
    "testimonials": Snippet("Testimonials", """
<section class=\"section section-alt\">
  <h2>Testimonials</h2>
  <div class=\"testimonials\">
    <figure class=\"card\">
      <blockquote>
        <p>“This changed the way we work together.”</p>
      </blockquote>
      <figcaption>Jordan, Customer Success Lead</figcaption>
    </figure>
    <figure class=\"card\">
      <blockquote>
        <p>“A beautiful experience from start to finish.”</p>
      </blockquote>
      <figcaption>Priya, Marketing Director</figcaption>
    </figure>
  </div>
</section>
"""),
    "contact": Snippet("Contact form", """
<section class=\"section max-w-md\">
  <h2>Contact us</h2>
  <form class=\"stack form\">
    <label>Full name<input type=\"text\" placeholder=\"Your name\" required></label>
    <label>Email<input type=\"email\" placeholder=\"you@example.com\" required></label>
    <label>How can we help?<textarea rows=\"4\"></textarea></label>
    <button class=\"btn btn-primary\" type=\"submit\">Send message</button>
  </form>
</section>
"""),
    "blog": Snippet("Blog list", """
<section class=\"section\">
  <h2>Latest stories</h2>
  <div class=\"grid split-3\">
    <article class=\"card\">
      <span class=\"badge\">Jul 14</span>
      <h3>Headline for a new update</h3>
      <p>Keep it short and helpful. Tell the reader what they'll learn.</p>
      <a class=\"btn btn-link\" href=\"#\">Read more</a>
    </article>
    <article class=\"card\">
      <span class=\"badge\">Jul 03</span>
      <h3>Another quick story</h3>
      <p>Share progress, showcase customers, or explain a concept.</p>
      <a class=\"btn btn-link\" href=\"#\">Read more</a>
    </article>
  </div>
</section>
"""),
    "features": Snippet("Feature comparison", """
<section class=\"section\">
  <h2>Compare plans</h2>
  <div class=\"grid split-3\">
    <article class=\"card\">
      <h3>Starter</h3>
      <ul class=\"list-check\">
        <li>Core features</li>
        <li>Email support</li>
        <li>Community access</li>
      </ul>
      <a class=\"btn btn-outline\" href=\"#\">Choose plan</a>
    </article>
    <article class=\"card\">
      <h3>Growth</h3>
      <ul class=\"list-check\">
        <li>Everything in Starter</li>
        <li>Advanced analytics</li>
        <li>Priority help</li>
      </ul>
      <a class=\"btn btn-primary\" href=\"#\">Best for teams</a>
    </article>
    <article class=\"card\">
      <h3>Scale</h3>
      <ul class=\"list-check\">
        <li>Unlimited projects</li>
        <li>Dedicated support</li>
        <li>Custom integrations</li>
      </ul>
      <a class=\"btn btn-outline\" href=\"#\">Talk to sales</a>
    </article>
  </div>
</section>
"""),
    "steps": Snippet("Steps / How-to", """
<section class=\"section\">
  <h2>How it works</h2>
  <div class=\"steps\">
    <article>
      <h3>1. Share your goals</h3>
      <p>Tell us what success looks like for you.</p>
    </article>
    <article>
      <h3>2. We craft a plan</h3>
      <p>Collaborate on a roadmap that fits your team.</p>
    </article>
    <article>
      <h3>3. Launch and celebrate</h3>
      <p>We provide the support you need to keep growing.</p>
    </article>
  </div>
</section>
"""),
    "timeline": Snippet("Timeline", """
<section class=\"section section-alt\">
  <h2>Roadmap</h2>
  <div class=\"timeline\">
    <div class=\"timeline-item\">
      <span class=\"badge\">Phase 1</span>
      <div>
        <h3>Discovery</h3>
        <p>Understand needs, audience, and goals.</p>
      </div>
    </div>
    <div class=\"timeline-item\">
      <span class=\"badge\">Phase 2</span>
      <div>
        <h3>Design</h3>
        <p>Prototype and iterate with feedback.</p>
      </div>
    </div>
    <div class=\"timeline-item\">
      <span class=\"badge\">Phase 3</span>
      <div>
        <h3>Launch</h3>
        <p>Ship with confidence and celebrate wins.</p>
      </div>
    </div>
  </div>
</section>
"""),
}


COMPONENT_SNIPPETS: Dict[str, Snippet] = {
    "button-primary": Snippet("Button — primary", "<a class=\"btn btn-primary\" href=\"#\">Primary action</a>"),
    "button-soft": Snippet("Button — soft", "<a class=\"btn btn-soft\" href=\"#\">Soft button</a>"),
    "button-outline": Snippet("Button — outline", "<a class=\"btn btn-outline\" href=\"#\">Outline button</a>"),
    "button-ghost": Snippet("Button — ghost", "<a class=\"btn btn-ghost\" href=\"#\">Ghost button</a>"),
    "button-pill": Snippet("Button — pill", "<a class=\"btn btn-primary btn-pill\" href=\"#\">Pill button</a>"),
    "button-gradient": Snippet("Button — gradient", "<a class=\"btn btn-gradient\" href=\"#\">Gradient button</a>"),
    "alert": Snippet("Alert / Callout", "<aside class=\"alert alert-info\">Friendly reminder or info.</aside>"),
    "alert-success": Snippet("Alert — success", "<aside class=\"alert alert-success\">Great news!</aside>"),
    "card": Snippet("Card", """
<article class=\"card\">
  <h3>Card title</h3>
  <p>Use cards to highlight features or short blurbs.</p>
  <a class=\"btn btn-link\" href=\"#\">Read more</a>
</article>
"""),
    "tabs": Snippet("Tabs (CSS only)", """
<div class=\"tabs\">
  <input checked id=\"tab-one\" name=\"example-tabs\" type=\"radio\">
  <label for=\"tab-one\">Tab one</label>
  <div class=\"tab-content\">
    <p>Content for the first tab.</p>
  </div>
  <input id=\"tab-two\" name=\"example-tabs\" type=\"radio\">
  <label for=\"tab-two\">Tab two</label>
  <div class=\"tab-content\">
    <p>Content for the second tab.</p>
  </div>
</div>
"""),
    "accordion": Snippet("Accordion", """
<details class=\"faq\">
  <summary>Frequently asked question</summary>
  <p>Provide a clear, concise answer.</p>
</details>
"""),
    "badge": Snippet("Badge", "<span class=\"badge\">New</span>"),
    "divider": Snippet("Divider", "<div class=\"divider\"></div>"),
    "icon-list": Snippet("Icon list", """
<ul class=\"list-check\">
  <li>First highlight</li>
  <li>Second highlight</li>
  <li>Third highlight</li>
</ul>
"""),
    "inline-tags": Snippet("Inline tags", """
<div class=\"inline-tags\">
  <span>Design</span>
  <span>Research</span>
  <span>Strategy</span>
</div>
"""),
}

# ---------------------------------------------------------------------------
# Rendering utilities
# ---------------------------------------------------------------------------


BASE_TEMPLATE = """\
<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{{ title }} — {{ site_name }}</title>
  <link rel=\"stylesheet\" href=\"assets/css/style.css\">
</head>
<body class=\"main-container\">
  {{ content | safe }}
  <script src=\"assets/js/main.js\"{% if not include_js %} defer hidden{% endif %}></script>
</body>
</html>
"""


def build_base_css(palette: Dict[str, str], fonts: Dict[str, str]) -> str:
    primary = palette.get("primary", DEFAULT_PALETTE["primary"])
    surface = palette.get("surface", DEFAULT_PALETTE["surface"])
    text = palette.get("text", DEFAULT_PALETTE["text"])
    heading_font = fonts.get("heading", DEFAULT_FONTS["heading"])
    body_font = fonts.get("body", DEFAULT_FONTS["body"])
    return f""":root {{
  --color-primary: {primary};
  --color-surface: {surface};
  --color-text: {text};
}}
body {{
  font-family: {body_font};
  background: var(--color-surface);
  color: var(--color-text);
  margin: 0;
  line-height: 1.6;
}}
h1, h2, h3, h4, h5 {{
  font-family: {heading_font};
  color: var(--color-text);
  line-height: 1.2;
}}
a {{
  color: var(--color-primary);
}}
.site-header {{
  position: sticky;
  top: 0;
  background: rgba(255,255,255,0.92);
  backdrop-filter: blur(10px);
  z-index: 10;
  padding: 0.75rem 1rem;
}}
.site-header .site-logo {{
  font-weight: 700;
  font-size: 1.25rem;
}}
.site-nav ul {{
  list-style: none;
  margin: 0;
  padding: 0;
}}
.site-nav li {{ display: inline-flex; }}
.site-nav a {{
  padding: 0.5rem 0.75rem;
  border-radius: 999px;
}}
.site-nav.is-open {{
  display: grid;
}}
@media (max-width: 640px) {{
  .site-nav {{ display: none; }}
  .site-nav.is-open {{ display: grid; gap: 0.5rem; padding-top: 0.75rem; }}
}}
"""


def _jinja_env() -> Environment:
    return Environment(
        loader=DictLoader({"base.html.j2": BASE_TEMPLATE}),
        autoescape=select_autoescape(["html", "xml"]),
    )


@dataclass
class MigrationResult:
    project: Project
    migrated: bool


def migrate_project_v1_to_v2(data: Dict[str, object]) -> Dict[str, object]:
    pages_data = data.get("pages", [])
    if not isinstance(pages_data, list):
        pages_data = []
    pages = [Page(**p) for p in pages_data]
    project = Project(
        name=str(data.get("name", "My Site")),
        pages=pages,
        css=str(data.get("css", "")),
    output_dir=str(data.get("output_dir")) if data.get("output_dir") is not None else None,
        palette=dict(DEFAULT_PALETTE),
        fonts=dict(DEFAULT_FONTS),
        images=[],
    )
    return project.to_dict()


def load_project(path: Path) -> MigrationResult:
    raw = json.loads(path.read_text(encoding="utf-8"))
    migrated = False
    version = int(raw.get("version", 1))
    if version == 1:
        raw = migrate_project_v1_to_v2(raw)
        migrated = True
    project = Project.from_dict(raw)
    project.version = SITE_VERSION
    return MigrationResult(project=project, migrated=migrated)


def save_project(path: Path, project: Project) -> None:
    payload = project.to_dict()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def render_project(project: Project, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    css_dir = assets_dir / "css"
    img_dir = assets_dir / "images"
    js_dir = assets_dir / "js"
    css_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)
    if project.use_main_js:
        js_dir.mkdir(parents=True, exist_ok=True)
        (js_dir / "main.js").write_text(MAIN_JS_SNIPPET, encoding="utf-8")
    else:
        if js_dir.exists():
            shutil.rmtree(js_dir)
    css = project.css
    if CSS_HELPERS_SENTINEL not in css:
        css = css.rstrip() + "\n\n" + CSS_HELPERS_BLOCK
    (css_dir / "style.css").write_text(css, encoding="utf-8")
    for asset in project.images:
        data = base64.b64decode(asset.data_base64.encode("ascii"))
        (img_dir / asset.name).write_bytes(data)
    env = _jinja_env()
    template = env.get_template("base.html.j2")
    nav = [{"filename": p.filename, "title": p.title} for p in project.pages]
    for page in project.pages:
        html = template.render(
            site_name=project.name,
            title=page.title,
            pages=nav,
            content=page.html,
            include_js=project.use_main_js,
        )
        (output_dir / page.filename).write_text(html, encoding="utf-8")

# ---------------------------------------------------------------------------
# Recent projects manager and thumbnails
# ---------------------------------------------------------------------------


@dataclass
class RecentItem:
    path: str
    name: str
    last_opened: str
    pinned: bool = False
    thumbnail: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "name": self.name,
            "last_opened": self.last_opened,
            "pinned": self.pinned,
            "thumbnail": self.thumbnail,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "RecentItem":
        return cls(
            path=str(data.get("path", "")),
            name=str(data.get("name", "Untitled")),
            last_opened=str(data.get("last_opened", datetime.utcnow().isoformat())),
            pinned=bool(data.get("pinned", False)),
            thumbnail=(str(data["thumbnail"]) if data.get("thumbnail") else None),
        )


class RecentProjectsManager:
    """Persistent recent-project list with pinning and thumbnails."""

    def __init__(self) -> None:
        self._items: List[RecentItem] = []
        self.load()

    def load(self) -> None:
        if not RECENTS_PATH.exists():
            self._items = []
            return
        try:
            data = json.loads(RECENTS_PATH.read_text(encoding="utf-8"))
            self._items = [RecentItem.from_dict(item) for item in data]
        except Exception:
            self._items = []

    def save(self) -> None:
        RECENTS_PATH.write_text(
            json.dumps([item.to_dict() for item in self._items], indent=2),
            encoding="utf-8",
        )

    def add_or_bump(self, path: Path, project: Project) -> None:
        path_str = str(path)
        now = datetime.utcnow().isoformat()
        for item in self._items:
            if item.path == path_str:
                item.name = project.name
                item.last_opened = now
                self.save()
                return
        self._items.append(RecentItem(path=path_str, name=project.name, last_opened=now))
        self.save()

    def remove(self, path: str) -> None:
        self._items = [item for item in self._items if item.path != path]
        self.save()

    def set_pinned(self, path: str, pinned: bool) -> None:
        for item in self._items:
            if item.path == path:
                item.pinned = pinned
        self.save()

    def list(self) -> List[RecentItem]:
        def sort_key(item: RecentItem) -> Tuple[int, str]:
            return (-1 if item.pinned else 0, item.last_opened)

        return sorted(self._items, key=sort_key, reverse=True)

    def purge_missing(self) -> None:
        changed = False
        existing: List[RecentItem] = []
        for item in self._items:
            if Path(item.path).exists():
                existing.append(item)
            else:
                changed = True
        if changed:
            self._items = existing
            self.save()

    def set_thumbnail(self, path: Path, image_path: Path) -> None:
        for item in self._items:
            if item.path == str(path):
                item.thumbnail = str(image_path)
                break
        self.save()


def write_project_thumbnail(project: Project, project_path: Optional[Path]) -> Optional[Path]:
    if project_path is None:
        return None
    pixmap = QtGui.QPixmap(420, 260)
    pixmap.fill(QtGui.QColor(project.palette.get("surface", "#f8fafc")))
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setPen(QtGui.QPen(QtGui.QColor(project.palette.get("primary", "#2563eb")), 6))
    painter.drawRoundedRect(12, 12, 396, 236, 18, 18)
    painter.setPen(QtGui.QPen(QtGui.QColor(project.palette.get("text", "#0f172a"))))
    font = QtGui.QFont()
    font.setPointSize(18)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(
        pixmap.rect().adjusted(24, 24, -24, -24),
        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
        project.name,
    )
    font.setPointSize(11)
    font.setBold(False)
    painter.setFont(font)
    summary = "\n".join(page.title for page in project.pages[:3])
    painter.drawText(
        pixmap.rect().adjusted(24, 80, -24, -24),
        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
        summary,
    )
    painter.end()
    hash_name = f"{abs(hash(project_path))}.png"
    output = PREVIEWS_DIR / hash_name
    pixmap.save(str(output), "PNG")
    return output

# ---------------------------------------------------------------------------
# Automatic recommendations
# ---------------------------------------------------------------------------


AUTO_MAP = {
    ("Landing", "Customers", "Get signups"): {
        "template": "starter",
        "theme": "Calm Sky",
        "pages": ["About", "Pricing"],
        "cta": "Start free trial",
    },
    ("Portfolio", "Hiring managers", "Showcase work"): {
        "template": "portfolio",
        "theme": "Forest",
        "pages": ["Projects", "About", "Contact"],
        "cta": "View my work",
    },
    ("Resource", "Internal users", "Provide help docs"): {
        "template": "resource",
        "theme": "Midnight",
        "pages": ["Docs", "FAQ", "Updates"],
        "cta": "Explore resources",
    },
    ("Other", "Community", "Share news"): {
        "template": "resource",
        "theme": "Rose",
        "pages": ["Blog", "About"],
        "cta": "Read the latest",
    },
}

# ---------------------------------------------------------------------------
# Qt helper widgets
# ---------------------------------------------------------------------------


class LargeToolButton(QtWidgets.QToolButton):
    def __init__(self, text: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setMinimumHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        font = self.font()
        font.setPointSize(12)
        self.setFont(font)


class TemplateCard(QtWidgets.QFrame):
    clicked = QtCore.pyqtSignal(str)

    def __init__(self, template: TemplateDefinition, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.template = template
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Raised)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        thumb = QtWidgets.QLabel(self)
        thumb.setFixedHeight(120)
        pix = QtGui.QPixmap(320, 120)
        pix.fill(QtGui.QColor("#dbeafe"))
        painter = QtGui.QPainter(pix)
        painter.setPen(QtGui.QPen(QtGui.QColor("#1d4ed8")))
        painter.drawRoundedRect(6, 6, 308, 108, 12, 12)
        painter.setPen(QtGui.QColor("#1e293b"))
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, template.title)
        painter.end()
        thumb.setPixmap(pix)
        thumb.setScaledContents(True)
        layout.addWidget(thumb)
        title = QtWidgets.QLabel(f"<b>{template.title}</b>")
        desc = QtWidgets.QLabel(template.description)
        desc.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addStretch()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.template.key)
        super().mouseReleaseEvent(event)


class AssetListWidget(QtWidgets.QListWidget):
    filesDropped = QtCore.pyqtSignal(list)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime is not None and mime.hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        mime = event.mimeData()
        if mime is not None and mime.hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        mime = event.mimeData()
        if mime is not None and mime.hasUrls():
            paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
            if paths:
                self.filesDropped.emit(paths)
        else:
            super().dropEvent(event)

# ---------------------------------------------------------------------------
# Guided plan dialog
# ---------------------------------------------------------------------------


class GuidedPlanDialog(QtWidgets.QDialog):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Make it for me")
        ensure_app_icon(self)
        self.setModal(True)
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel("Answer a few quick questions and we'll pick a template, theme, and starter pages.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.purpose = self._create_group("What are you making?", ["Landing", "Portfolio", "Resource", "Other"], layout)
        self.audience = self._create_group(
            "Who is it for?", ["Customers", "Hiring managers", "Internal users", "Community"], layout
        )
        self.goal = self._create_group(
            "What's the goal?", ["Get signups", "Showcase work", "Provide help docs", "Share news"], layout
        )
        layout.addWidget(QtWidgets.QLabel("Short blurb (optional):"))
        self.blurb = QtWidgets.QPlainTextEdit(self)
        self.blurb.setPlaceholderText("I need a simple site for my lawn service…")
        self.blurb.setFixedHeight(80)
        layout.addWidget(self.blurb)
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        self.setMinimumWidth(420)

    def _create_group(
        self,
        title: str,
        options: Iterable[str],
        parent_layout: QtWidgets.QVBoxLayout,
    ) -> QtWidgets.QButtonGroup:
        parent_layout.addWidget(QtWidgets.QLabel(f"<b>{title}</b>"))
        container = QtWidgets.QWidget(self)
        lay = QtWidgets.QHBoxLayout(container)
        lay.setSpacing(8)
        lay.setContentsMargins(0, 0, 0, 0)
        group = QtWidgets.QButtonGroup(self)
        for opt in options:
            btn = QtWidgets.QRadioButton(opt, container)
            btn.setMinimumHeight(32)
            lay.addWidget(btn)
            group.addButton(btn)
        lay.addStretch()
        parent_layout.addWidget(container)
        buttons = group.buttons()
        if buttons:
            buttons[0].setChecked(True)
        return group

    def result(self) -> Optional[Dict[str, str]]:
        if self.result() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        purpose = self._checked_text(self.purpose)
        audience = self._checked_text(self.audience)
        goal = self._checked_text(self.goal)
        if not purpose or not audience or not goal:
            return None
        mapping = AUTO_MAP.get((purpose, audience, goal))
        if not mapping:
            mapping = next(iter(AUTO_MAP.values()))
        result = dict(mapping)
        result["blurb"] = self.blurb.toPlainText().strip()
        return result

    def _checked_text(self, group: QtWidgets.QButtonGroup) -> Optional[str]:
        btn = group.checkedButton()
        return btn.text() if btn else None

# ---------------------------------------------------------------------------
# New Project Wizard
# ---------------------------------------------------------------------------


class NewProjectWizard(QtWidgets.QDialog):
    def __init__(
        self,
        recents: RecentProjectsManager,
        settings: SettingsManager,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Project Wizard")
        ensure_app_icon(self)
        self.recents = recents
        self.settings = settings
        self.resize(720, 520)
        self._project_result: Optional[Project] = None
        self._path_result: Optional[Path] = None

        self.stack = QtWidgets.QStackedWidget(self)
        self.steps: List[QtWidgets.QWidget] = []
        self._build_steps()

        nav_layout = QtWidgets.QHBoxLayout()
        self.btn_back = QtWidgets.QPushButton("Back")
        self.btn_next = QtWidgets.QPushButton("Next")
        self.btn_finish = QtWidgets.QPushButton("Create project")
        for btn in (self.btn_back, self.btn_next, self.btn_finish):
            btn.setMinimumHeight(40)
        nav_layout.addWidget(self.btn_back)
        nav_layout.addStretch()
        nav_layout.addWidget(self.btn_next)
        nav_layout.addWidget(self.btn_finish)
        self.btn_finish.hide()

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.stack)
        layout.addLayout(nav_layout)

        self.btn_back.clicked.connect(self._back)
        self.btn_next.clicked.connect(self._next)
        self.btn_finish.clicked.connect(self._finish)
        self.stack.currentChanged.connect(self._update_buttons)
        self._update_buttons()

    def _build_steps(self) -> None:
        self.steps.append(self._build_describe())
        self.steps.append(self._build_template())
        self.steps.append(self._build_pages())
        self.steps.append(self._build_style())
        self.steps.append(self._build_review())
        for step in self.steps:
            self.stack.addWidget(step)

    # Step widgets ------------------------------------------------------
    def _build_describe(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(page)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.describe_purpose = QtWidgets.QComboBox(page)
        self.describe_purpose.addItems(["Landing", "Portfolio", "Resource", "Other"])
        self.describe_audience = QtWidgets.QComboBox(page)
        self.describe_audience.addItems(["Customers", "Hiring managers", "Internal users", "Community"])
        self.describe_goal = QtWidgets.QComboBox(page)
        self.describe_goal.addItems(["Get signups", "Showcase work", "Provide help docs", "Share news"])
        self.describe_blurb = QtWidgets.QPlainTextEdit(page)
        self.describe_blurb.setPlaceholderText("Short description or tagline")
        self.describe_blurb.setFixedHeight(80)
        self.describe_name = QtWidgets.QLineEdit(page)
        self.describe_name.setText("My Site")
        self.describe_location = QtWidgets.QLineEdit(page)
        browse = QtWidgets.QPushButton("Browse…", page)
        browse.clicked.connect(self._choose_location)
        location_layout = QtWidgets.QHBoxLayout()
        location_layout.addWidget(self.describe_location)
        location_layout.addWidget(browse)
        layout.addRow("What are you making?", self.describe_purpose)
        layout.addRow("Who is it for?", self.describe_audience)
        layout.addRow("Goal", self.describe_goal)
        layout.addRow("Project name", self.describe_name)
        layout.addRow("Save location", location_layout)
        layout.addRow("Tagline / blurb", self.describe_blurb)
        helper = QtWidgets.QLabel("Tip: the location should be an empty folder where we'll keep exports and previews.")
        helper.setWordWrap(True)
        layout.addRow(helper)
        last = self.settings.get("last_save_dir", str(Path.home()))
        self.describe_location.setText(last)
        return page

    def _build_template(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(QtWidgets.QLabel("Choose a template"))
        self.template_buttons = QtWidgets.QButtonGroup(self)
        for tmpl in TEMPLATES.values():
            radio = QtWidgets.QRadioButton(f"{tmpl.title} — {tmpl.description}")
            radio.setProperty("template_key", tmpl.key)
            self.template_buttons.addButton(radio)
            layout.addWidget(radio)
        if self.template_buttons.buttons():
            self.template_buttons.buttons()[0].setChecked(True)
        helper = QtWidgets.QLabel("Each template comes with pages and starter sections you can customize later.")
        helper.setWordWrap(True)
        layout.addWidget(helper)
        layout.addStretch()
        return page

    def _build_pages(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(QtWidgets.QLabel("Select pages"))
        self.page_checks: List[Tuple[QtWidgets.QCheckBox, QtWidgets.QLineEdit]] = []
        for title in ["Home", "About", "Projects", "Docs", "Contact", "Blog"]:
            box = QtWidgets.QCheckBox(title, page)
            edit = QtWidgets.QLineEdit(title, page)
            edit.setEnabled(title != "Home")
            if title == "Home":
                box.setChecked(True)
                box.setEnabled(False)
            else:
                box.setChecked(title in ("About", "Contact"))
            row = QtWidgets.QHBoxLayout()
            row.addWidget(box)
            row.addWidget(edit)
            layout.addLayout(row)
            self.page_checks.append((box, edit))
        layout.addStretch()
        helper = QtWidgets.QLabel("Home is required. Rename other pages to match your voice.")
        helper.setWordWrap(True)
        layout.addWidget(helper)
        return page

    def _build_style(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(page)
        layout.addRow(QtWidgets.QLabel("Choose a theme"))
        self.theme_combo = QtWidgets.QComboBox(page)
        self.theme_combo.addItems(list(THEME_PRESETS.keys()))
        self.heading_combo = QtWidgets.QComboBox(page)
        self.heading_combo.addItems(FONT_STACKS)
        self.body_combo = QtWidgets.QComboBox(page)
        self.body_combo.addItems(FONT_STACKS)
        layout.addRow("Theme preset", self.theme_combo)
        layout.addRow("Heading font", self.heading_combo)
        layout.addRow("Body font", self.body_combo)
        helper = QtWidgets.QLabel("You can tweak colors later in the builder.")
        helper.setWordWrap(True)
        layout.addRow(helper)
        return page

    def _build_review(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(QtWidgets.QLabel("Review"))
        self.review_text = QtWidgets.QTextEdit(page)
        self.review_text.setReadOnly(True)
        layout.addWidget(self.review_text, 1)
        layout.addWidget(QtWidgets.QLabel("Click Create project to open the editor."))
        return page

    # Navigation --------------------------------------------------------
    def _update_buttons(self) -> None:
        index = self.stack.currentIndex()
        self.btn_back.setEnabled(index > 0)
        if index == len(self.steps) - 1:
            self.btn_next.hide()
            self.btn_finish.show()
            self._refresh_review()
        else:
            self.btn_next.show()
            self.btn_finish.hide()

    def _next(self) -> None:
        if self.stack.currentIndex() < len(self.steps) - 1:
            self.stack.setCurrentIndex(self.stack.currentIndex() + 1)

    def _back(self) -> None:
        if self.stack.currentIndex() > 0:
            self.stack.setCurrentIndex(self.stack.currentIndex() - 1)

    def _finish(self) -> None:
        project, path = self._build_project_from_inputs()
        if project is None:
            return
        self._project_result = project
        self._path_result = path
        self.accept()

    def _choose_location(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose save location",
            self.settings.get("last_save_dir", str(Path.home())),
        )
        if directory:
            self.describe_location.setText(directory)
            self.settings.set("last_save_dir", directory)

    def _refresh_review(self) -> None:
        project, path = self._build_project_from_inputs(validate=False)
        if project is None:
            self.review_text.setPlainText("Please complete earlier steps.")
            return
        lines = [
            f"Name: {project.name}",
            f"Template: {project.template_key}",
            f"Theme: {project.theme_preset}",
            f"Heading font: {project.fonts['heading']}",
            f"Body font: {project.fonts['body']}",
            f"Pages: {', '.join(page.title for page in project.pages)}",
            f"Save to: {path}",
        ]
        self.review_text.setPlainText("\n".join(lines))

    def _build_project_from_inputs(
        self,
        validate: bool = True,
    ) -> Tuple[Optional[Project], Optional[Path]]:
        name = self.describe_name.text().strip()
        if not name:
            if validate:
                QtWidgets.QMessageBox.warning(self, "Missing name", "Please provide a project name.")
            return None, None
        location = self.describe_location.text().strip()
        if not location:
            if validate:
                QtWidgets.QMessageBox.warning(self, "Missing location", "Choose where to save the project.")
            return None, None
        template_key = "starter"
        for btn in self.template_buttons.buttons():
            if btn.isChecked():
                template_key = str(btn.property("template_key"))
        selected_pages: List[str] = []
        page_titles: Dict[str, str] = {}
        for box, edit in self.page_checks:
            title = edit.text().strip() or box.text()
            if box.text() == "Home":
                selected_pages.append("Home")
                page_titles["Home"] = title
                continue
            if box.isChecked():
                selected_pages.append(box.text())
                page_titles[box.text()] = title
        theme = self.theme_combo.currentText()
        fonts = {
            "heading": self.heading_combo.currentText(),
            "body": self.body_combo.currentText(),
        }
        palette = dict(THEME_PRESETS.get(theme, DEFAULT_PALETTE))
        project = create_project_from_template(
            name=name,
            template_key=template_key,
            selected_pages=selected_pages,
            page_titles=page_titles,
            palette=palette,
            fonts=fonts,
            blurb=self.describe_blurb.toPlainText().strip(),
        )
        project.theme_preset = theme
        project.output_dir = location
        path = Path(location) / f"{re.sub(r'[^a-zA-Z0-9_-]+', '-', name.lower()).strip('-') or 'site'}.siteproj"
        return project, path

    def project_result(self) -> Tuple[Optional[Project], Optional[Path]]:
        return self._project_result, self._path_result

def create_project_from_template(
    name: str,
    template_key: str,
    selected_pages: List[str],
    page_titles: Dict[str, str],
    palette: Dict[str, str],
    fonts: Dict[str, str],
    blurb: str = "",
) -> Project:
    template = TEMPLATES.get(template_key, TEMPLATES["starter"])
    pages: List[Page] = []
    page_map: Dict[str, str] = {"Home": "index.html"}
    for filename, html in template.default_pages:
        title = "Home" if filename == "index.html" else Path(filename).stem.capitalize()
        page_map[title] = filename
        if title in selected_pages or filename == "index.html":
            content = html.replace("{{site_name}}", name)
            if blurb and "lead" in content and title == "Home":
                content = re.sub(r"<p class=\"lead\">.*?</p>", f"<p class=\"lead\">{blurb}</p>", content, count=1)
            pages.append(Page(filename=filename, title=page_titles.get(title, title), html=content))
    for title in selected_pages:
        if title not in page_map:
            filename = f"{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-') or 'page'}.html"
            body = f"<section class=\"section\">\n  <h1>{title}</h1>\n  <p>Write something helpful here.</p>\n</section>"
            pages.append(Page(filename=filename, title=page_titles.get(title, title), html=body))
    base_css = build_base_css(palette, fonts)
    css = base_css.rstrip() + "\n\n" + CSS_HELPERS_BLOCK
    project = Project(
        name=name,
        pages=pages,
        css=css,
        palette=palette,
        fonts=fonts,
        template_key=template_key,
        theme_preset="",
        images=placeholder_images(),
    )
    project.theme_preset = next((key for key, val in THEME_PRESETS.items() if val == palette), "Custom")
    return project


def placeholder_images() -> List[AssetImage]:
    images: List[AssetImage] = []
    for name, width, height in [
        ("placeholder-wide.png", 1200, 720),
        ("placeholder-portrait.png", 600, 800),
    ]:
        pix = QtGui.QPixmap(width // 6, height // 6)
        pix.fill(QtGui.QColor("#e2e8f0"))
        painter = QtGui.QPainter(pix)
        painter.setPen(QtGui.QPen(QtGui.QColor("#94a3b8"), 4))
        painter.drawRect(6, 6, pix.width() - 12, pix.height() - 12)
        painter.end()
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        pix.save(buffer, "PNG")
        data = base64.b64encode(buffer.data().data()).decode("ascii")
        images.append(
            AssetImage(name=name, data_base64=data, width=pix.width(), height=pix.height(), mime="image/png")
        )
    return images

# ---------------------------------------------------------------------------
# Start window (launch hub)
# ---------------------------------------------------------------------------


class StartWindow(QtWidgets.QMainWindow):
    project_opened = QtCore.pyqtSignal(object, object)

    def __init__(
        self,
        controller: "AppController",
        recents: RecentProjectsManager,
        settings: SettingsManager,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.recents = recents
        self.settings = settings
        self.template_cards = {}
        self.status_bar = QtWidgets.QStatusBar(self)
        self.setStatusBar(self.status_bar)
        ensure_app_icon(self)
        self.setWindowTitle("Webineer — Start")
        self.resize(1200, 820)
        self._selected_template = "starter"
        self._page_checks = {}
        self._page_edits = {}
        self._recent_widgets = {}

        central = QtWidgets.QWidget(self)
        outer = QtWidgets.QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(central)

        self.nav_list = QtWidgets.QListWidget(central)
        self.nav_list.setFixedWidth(220)
        self.nav_list.setSpacing(4)
        self.nav_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        for label in ["Create New", "Open", "Import", "Recent", "Learn"]:
            item = QtWidgets.QListWidgetItem(label)
            font = item.font()
            font.setPointSize(12)
            item.setFont(font)
            self.nav_list.addItem(item)
        self.nav_list.setCurrentRow(0)

        self.stack = QtWidgets.QStackedWidget(central)
        outer.addWidget(self.nav_list)
        outer.addWidget(self.stack, 1)

        self.pages: Dict[str, QtWidgets.QWidget] = {}
        self.pages["Create New"] = self._build_create_page()
        self.pages["Open"] = self._build_open_page()
        self.pages["Import"] = self._build_import_page()
        self.pages["Recent"] = self._build_recent_page()
        self.pages["Learn"] = self._build_learn_page()
        for key in ["Create New", "Open", "Import", "Recent", "Learn"]:
            self.stack.addWidget(self.pages[key])

        self.status_bar = QtWidgets.QStatusBar(self)
        self.setStatusBar(self.status_bar)

        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav_list.currentTextChanged.connect(self._on_nav_changed)
        self._on_nav_changed("Create New")
        self.refresh_recents()

    # UI builders -------------------------------------------------------
    def _wrap_scroll(self, widget: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
        area = QtWidgets.QScrollArea(self)
        area.setWidget(widget)
        area.setWidgetResizable(True)
        area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        return area

    def _build_create_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(40, 32, 40, 32)
        title = QtWidgets.QLabel("<h1>Welcome! Let's make something new.</h1>")
        subtitle = QtWidgets.QLabel("Choose a look, add pages, and jump in. You can always change things later.")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        layout.addWidget(QtWidgets.QLabel("What are you making?"))
        self.quick_purpose = QtWidgets.QButtonGroup(self)
        purpose_row = QtWidgets.QHBoxLayout()
        radio_buttons = []
        for option in ["Landing", "Portfolio", "Resource", "Other"]:
            btn = QtWidgets.QRadioButton(option, page)
            btn.setMinimumHeight(36)
            self.quick_purpose.addButton(btn)
            radio_buttons.append((btn, option))
            purpose_row.addWidget(btn)
        self.quick_purpose.buttons()[0].setChecked(True)
        purpose_row.addStretch()
        layout.addLayout(purpose_row)
        # ...existing code for form, template, pages, theme, etc...
        # Connect signals after all UI elements are initialized
        for btn, option in radio_buttons:
            btn.toggled.connect(lambda checked, text=option: self._quick_purpose_changed(text, checked))

        form = QtWidgets.QFormLayout()
        self.create_name = QtWidgets.QLineEdit(page)
        self.create_name.setPlaceholderText("Project name")
        self.create_name.setText("My Site")
        self.create_location = QtWidgets.QLineEdit(page)
        self.create_location.setPlaceholderText("Where to save the .siteproj file")
        self.create_location.setText(self.settings.get("last_save_dir", str(Path.home())))
        browse = QtWidgets.QPushButton("Browse…", page)
        browse.clicked.connect(self._browse_save_location)
        location_layout = QtWidgets.QHBoxLayout()
        location_layout.addWidget(self.create_location)
        location_layout.addWidget(browse)
        form.addRow("Project name", self.create_name)
        form.addRow("Save location", location_layout)
        layout.addLayout(form)

        layout.addWidget(QtWidgets.QLabel("Template"))
        template_grid = QtWidgets.QGridLayout()
        template_grid.setSpacing(16)
        row = col = 0
        self.template_cards: Dict[str, TemplateCard] = {}
        for tmpl in TEMPLATES.values():
            card = TemplateCard(tmpl, page)
            card.clicked.connect(self._on_template_selected)
            template_grid.addWidget(card, row, col)
            self.template_cards[tmpl.key] = card
            col += 1
            if col == 2:
                col = 0
                row += 1
        layout.addLayout(template_grid)

        layout.addWidget(QtWidgets.QLabel("Add pages"))
        page_options = QtWidgets.QHBoxLayout()
        for label in ["About", "Projects", "Docs", "Contact", "Blog", "Pricing", "FAQ", "Updates"]:
            check = QtWidgets.QCheckBox(label, page)
            if label in ("About", "Contact"):
                check.setChecked(True)
            self._page_checks[label] = check
            edit = QtWidgets.QLineEdit(label, page)
            edit.setPlaceholderText(f"{label} title")
            edit.setMaximumWidth(160)
            self._page_edits[label] = edit
            column = QtWidgets.QVBoxLayout()
            column.addWidget(check)
            column.addWidget(edit)
            page_options.addLayout(column)
        page_options.addStretch()
        layout.addLayout(page_options)

        layout.addWidget(QtWidgets.QLabel("Theme & fonts"))
        theme_layout = QtWidgets.QHBoxLayout()
        self.create_theme = QtWidgets.QComboBox(page)
        self.create_theme.addItems(list(THEME_PRESETS.keys()))
        self.create_theme.setCurrentText("Calm Sky")
        self.heading_font_combo = QtWidgets.QComboBox(page)
        self.heading_font_combo.addItems(FONT_STACKS)
        self.body_font_combo = QtWidgets.QComboBox(page)
        self.body_font_combo.addItems(FONT_STACKS)
        theme_layout.addWidget(QtWidgets.QLabel("Theme"))
        theme_layout.addWidget(self.create_theme)
        theme_layout.addWidget(QtWidgets.QLabel("Heading font"))
        theme_layout.addWidget(self.heading_font_combo)
        theme_layout.addWidget(QtWidgets.QLabel("Body font"))
        theme_layout.addWidget(self.body_font_combo)
        layout.addLayout(theme_layout)

        button_row = QtWidgets.QHBoxLayout()
        self.btn_make_plan = QtWidgets.QPushButton("Make it for me")
        self.btn_make_plan.setMinimumHeight(44)
        self.btn_make_plan.clicked.connect(self._run_make_it_for_me)
        self.btn_open_wizard = QtWidgets.QPushButton("Wizard…")
        self.btn_open_wizard.setMinimumHeight(44)
        self.btn_open_wizard.clicked.connect(self._launch_wizard)
        self.btn_create_project = QtWidgets.QPushButton("Create")
        self.btn_create_project.setMinimumHeight(48)
        self.btn_create_project.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.btn_create_project.clicked.connect(self._create_project)
        button_row.addWidget(self.btn_make_plan)
        button_row.addWidget(self.btn_open_wizard)
        button_row.addStretch()
        button_row.addWidget(self.btn_create_project)
        layout.addLayout(button_row)
        layout.addStretch()

        self._on_template_selected(self._selected_template)
        return self._wrap_scroll(page)

    def _build_open_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.addWidget(QtWidgets.QLabel("<h2>Open a project</h2>"))
        self.open_path = QtWidgets.QLineEdit(page)
        self.open_path.setPlaceholderText("Select a .siteproj file")
        browse = QtWidgets.QPushButton("Browse…", page)
        browse.clicked.connect(self._browse_open_file)
        path_row = QtWidgets.QHBoxLayout()
        path_row.addWidget(self.open_path)
        path_row.addWidget(browse)
        layout.addLayout(path_row)
        self.btn_open_confirm = QtWidgets.QPushButton("Open")
        self.btn_open_confirm.setMinimumHeight(44)
        self.btn_open_confirm.clicked.connect(self._open_selected_file)
        layout.addWidget(self.btn_open_confirm)
        layout.addStretch()
        return self._wrap_scroll(page)

    def _build_import_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.addWidget(QtWidgets.QLabel("<h2>Import an older project</h2>"))
        info = QtWidgets.QLabel("Import Webineer v1 projects. We'll upgrade them safely to the new format.")
        info.setWordWrap(True)
        layout.addWidget(info)
        self.import_path = QtWidgets.QLineEdit(page)
        browse = QtWidgets.QPushButton("Choose file…", page)
        browse.clicked.connect(self._browse_import_file)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.import_path)
        row.addWidget(browse)
        layout.addLayout(row)
        self.btn_import = QtWidgets.QPushButton("Import & open")
        self.btn_import.setMinimumHeight(44)
        self.btn_import.clicked.connect(self._import_project)
        layout.addWidget(self.btn_import)
        self.import_summary = QtWidgets.QTextEdit(page)
        self.import_summary.setReadOnly(True)
        self.import_summary.setPlaceholderText("Migration summary will appear here.")
        layout.addWidget(self.import_summary, 1)
        return self._wrap_scroll(page)

    def _build_recent_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        header = QtWidgets.QLabel("<h2>Recent projects</h2>")
        layout.addWidget(header)
        self.recent_list = QtWidgets.QListWidget(page)
        self.recent_list.setIconSize(QtCore.QSize(120, 74))
        self.recent_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.recent_list.itemDoubleClicked.connect(self._open_recent_item)
        self.recent_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.recent_list.customContextMenuRequested.connect(self._recent_context_menu)
        layout.addWidget(self.recent_list, 1)
        purge_btn = QtWidgets.QPushButton("Clean up missing")
        purge_btn.clicked.connect(self._purge_missing)
        layout.addWidget(purge_btn)
        return self._wrap_scroll(page)

    def _build_learn_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.addWidget(QtWidgets.QLabel("<h2>Learn the basics</h2>"))
        copy = QtWidgets.QLabel(
            "Start by creating a project, then use the Insert menu to drop in sections and components."
            " The preview updates live, and exporting creates a ready-to-publish folder."
        )
        copy.setWordWrap(True)
        layout.addWidget(copy)
        link = QtWidgets.QLabel(
            "<a href=\"https://example.com/webineer-tips\">Read getting started tips (opens in preview)</a>"
        )
        link.setOpenExternalLinks(True)
        layout.addWidget(link)
        layout.addStretch()
        return self._wrap_scroll(page)

    # Handlers ----------------------------------------------------------
    def _on_nav_changed(self, text: str) -> None:
        self.status_bar.showMessage("Ready")
        if text == "Recent":
            self.refresh_recents()

    def _on_template_selected(self, key: str) -> None:
        self._selected_template = key
        for tmpl_key, card in self.template_cards.items():
            if tmpl_key == key:
                card.setStyleSheet("border: 2px solid #2563eb; border-radius: 12px;")
            else:
                card.setStyleSheet("")
        self.status_bar.showMessage(f"Template set to {TEMPLATES[key].title}", 4000)

    def _browse_save_location(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose where to save",
            self.settings.get("last_save_dir", str(Path.home())),
        )
        if directory:
            self.create_location.setText(directory)
            self.settings.set("last_save_dir", directory)

    def _run_make_it_for_me(self) -> None:
        dialog = GuidedPlanDialog(self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            result = dialog.result()
            if not result:
                return
            self._apply_plan_result(result)
            self.status_bar.showMessage("Plan applied!", 5000)

    def _quick_purpose_changed(self, purpose: str, checked: bool) -> None:
        if not checked:
            return
        mapping = {
            "Landing": ("starter", "Calm Sky"),
            "Portfolio": ("portfolio", "Forest"),
            "Resource": ("resource", "Midnight"),
        }
        if purpose in mapping:
            template, theme = mapping[purpose]
            self._on_template_selected(template)
            self.create_theme.setCurrentText(theme)

    def _apply_plan_result(self, data: Dict[str, str]) -> None:
        template_key = data.get("template", "starter")
        theme = data.get("theme", "Calm Sky")
        pages = data.get("pages", [])
        self._on_template_selected(template_key)
        self.create_theme.setCurrentText(theme)
        for label, checkbox in self._page_checks.items():
            checked = label in pages
            checkbox.setChecked(checked)
            if checked and label in self._page_edits:
                self._page_edits[label].setText(label)
        blurb = data.get("blurb", "")
        if blurb:
            self.create_name.setText(blurb.split()[0].capitalize() + " Site")
        if data.get("cta"):
            self.status_bar.showMessage(f"Suggested CTA: {data['cta']}", 6000)

    def _launch_wizard(self) -> None:
        wizard = NewProjectWizard(self.recents, self.settings, self)
        if wizard.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            project, path = wizard.project_result()
            if project is None or path is None:
                return
            self.project_opened.emit(project, path)
            self.close()

    def _collect_pages(self) -> Tuple[List[str], Dict[str, str]]:
        selected: List[str] = ["Home"]
        titles: Dict[str, str] = {"Home": "Home"}
        for label, checkbox in self._page_checks.items():
            if checkbox.isChecked():
                selected.append(label)
                titles[label] = self._page_edits[label].text().strip() or label
        return selected, titles

    def _create_project(self) -> None:
        name = self.create_name.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Name required", "Please enter a project name.")
            return
        location = self.create_location.text().strip()
        if not location:
            QtWidgets.QMessageBox.warning(self, "Choose location", "Select where to save the project file.")
            return
        selected, titles = self._collect_pages()
        palette = dict(THEME_PRESETS.get(self.create_theme.currentText(), DEFAULT_PALETTE))
        fonts = {
            "heading": self.heading_font_combo.currentText(),
            "body": self.body_font_combo.currentText(),
        }
        project = create_project_from_template(
            name=name,
            template_key=self._selected_template,
            selected_pages=selected,
            page_titles=titles,
            palette=palette,
            fonts=fonts,
        )
        project.output_dir = location
        save_dir = Path(location)
        save_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.lower()).strip("-") or "site"
        project_path = save_dir / f"{slug}.siteproj"
        if project_path.exists():
            if QtWidgets.QMessageBox.question(self, "Overwrite?", f"{project_path.name} already exists. Replace it?") != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        try:
            save_project(project_path, project)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Error", f"Could not save project:\n{exc}")
            return
        self.recents.add_or_bump(project_path, project)
        thumb = write_project_thumbnail(project, project_path)
        if thumb:
            self.recents.set_thumbnail(project_path, thumb)
        self.project_opened.emit(project, project_path)
        self.close()

    def _browse_open_file(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open project",
            self.settings.get("last_open_dir", str(Path.home())),
            "Webineer Project (*.siteproj)",
        )
        if path:
            self.open_path.setText(path)
            self.settings.set("last_open_dir", str(Path(path).parent))

    def _open_selected_file(self) -> None:
        path = self.open_path.text().strip()
        if not path:
            return
        self._open_project_from_path(Path(path))

    def _browse_import_file(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Import project",
            self.settings.get("last_open_dir", str(Path.home())),
            "Webineer Project (*.siteproj)",
        )
        if path:
            self.import_path.setText(path)
            self.settings.set("last_open_dir", str(Path(path).parent))

    def _import_project(self) -> None:
        path = self.import_path.text().strip()
        if not path:
            return
        project_path = Path(path)
        try:
            result = load_project(project_path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Import failed", str(exc))
            return
        if result.migrated:
            self.import_summary.setPlainText("Upgraded to Webineer v2. You're all set!")
            try:
                save_project(project_path, result.project)
            except Exception:
                pass
        else:
            self.import_summary.setPlainText("Project opened.")
        self.project_opened.emit(result.project, project_path)
        self.close()

    def _open_project_from_path(self, path: Path) -> None:
        if not path.exists():
            QtWidgets.QMessageBox.warning(self, "Not found", "That project file no longer exists.")
            return
        try:
            result = load_project(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Error", f"Couldn't open project:\n{exc}")
            return
        self.settings.set("last_open_dir", str(path.parent))
        if result.migrated:
            QtWidgets.QMessageBox.information(self, "Upgraded", "We upgraded this project to the latest format.")
            try:
                save_project(path, result.project)
            except Exception:
                pass
        self.project_opened.emit(result.project, path)
        self.close()

    def refresh_recents(self) -> None:
        self.recents.load()
        if not hasattr(self, 'recent_list'):
            return
        self.recent_list.clear()
        for item in self.recents.list():
            list_item = QtWidgets.QListWidgetItem(item.name)
            list_item.setData(Qt.ItemDataRole.UserRole, item.path)
            subtitle = f"{item.path}\nLast opened: {item.last_opened}"
            if item.pinned:
                subtitle = "📌 " + subtitle
            list_item.setToolTip(subtitle)
            if item.thumbnail and Path(item.thumbnail).exists():
                list_item.setIcon(QtGui.QIcon(item.thumbnail))
            self.recent_list.addItem(list_item)

    def _open_recent_item(self, item: QtWidgets.QListWidgetItem) -> None:
        path = Path(str(item.data(Qt.ItemDataRole.UserRole)))
        if not path.exists():
            QtWidgets.QMessageBox.warning(self, "Missing", "This project file is missing. Removing from list.")
            self.recents.remove(str(path))
            self.refresh_recents()
            return
        self._open_project_from_path(path)

    def _recent_context_menu(self, pos: QtCore.QPoint) -> None:
        item = self.recent_list.itemAt(pos)
        if item is None:
            return
        path_str = str(item.data(Qt.ItemDataRole.UserRole))
        menu = QtWidgets.QMenu(self)
        act_open = menu.addAction("Open")
        act_folder = menu.addAction("Open folder")
        act_pin = menu.addAction("Unpin" if "📌" in item.toolTip() else "Pin")
        act_remove = menu.addAction("Remove from list")
        action = menu.exec(self.recent_list.mapToGlobal(pos))
        if action == act_open:
            self._open_project_from_path(Path(path_str))
        elif action == act_folder:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(Path(path_str).parent)))
        elif action == act_pin:
            currently_pinned = "📌" in item.toolTip()
            self.recents.set_pinned(path_str, not currently_pinned)
            self.refresh_recents()
        elif action == act_remove:
            self.recents.remove(path_str)
            self.refresh_recents()

    def _purge_missing(self) -> None:
        self.recents.purge_missing()
        self.refresh_recents()
        self.status_bar.showMessage("Cleaned up missing entries", 3000)

# ---------------------------------------------------------------------------
# Main builder window
# ---------------------------------------------------------------------------


class MainWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        controller: "AppController",
        project: Project,
        project_path: Optional[Path],
        recents: RecentProjectsManager,
        settings: SettingsManager,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        ensure_app_icon(self)
        self.controller = controller
        self.project = project
        self.project_path = project_path
        self.recents = recents
        self.settings = settings
        self.setWindowTitle(f"{APP_TITLE} — {project.name}")
        self.resize(1280, 820)

        self._preview_tmp: Optional[str] = None
        self._debounce = QtCore.QTimer(self)
        self._debounce.setInterval(400)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self.update_preview)

        self._build_ui()
        self._build_menu()
        self._bind_events()
        self._load_project_into_ui()
        self.update_preview()

    # UI setup ----------------------------------------------------------
    def _build_ui(self) -> None:
        splitter = QtWidgets.QSplitter(self)
        splitter.setOrientation(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # Left panel
        left = QtWidgets.QWidget(self)
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)
        header = QtWidgets.QHBoxLayout()
        header.addWidget(QtWidgets.QLabel("Pages"))
        header.addStretch()
        self.btn_add_page = QtWidgets.QPushButton("Add")
        self.btn_remove_page = QtWidgets.QPushButton("Remove")
        header.addWidget(self.btn_add_page)
        header.addWidget(self.btn_remove_page)
        left_layout.addLayout(header)

        self.pages_list = QtWidgets.QListWidget(left)
        self.pages_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        left_layout.addWidget(self.pages_list, 1)

        # Center tabs
        self.tab_editors = QtWidgets.QTabWidget(self)
        self.tab_editors.setDocumentMode(True)
        self.html_editor = QtWidgets.QPlainTextEdit(self.tab_editors)
        self.html_editor.setPlaceholderText("Write HTML for the current page.")
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(11)
        self.html_editor.setFont(font)
        self.css_editor = QtWidgets.QPlainTextEdit(self.tab_editors)
        self.css_editor.setPlaceholderText("Global CSS")
        self.css_editor.setFont(font)
        self.tab_editors.addTab(self.html_editor, "Page HTML")
        self.tab_editors.addTab(self.css_editor, "Global CSS")
        self.design_tab = self._build_design_tab()
        self.assets_tab = self._build_assets_tab()
        self.tab_editors.addTab(self.design_tab, "Design")
        self.tab_editors.addTab(self.assets_tab, "Assets")

        # Preview
        right = QtWidgets.QWidget(self)
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(4)
        right_layout.addWidget(QtWidgets.QLabel("Preview"))
        self.preview = QWebEngineView(right)
        right_layout.addWidget(self.preview, 1)

        splitter.addWidget(left)
        splitter.addWidget(self.tab_editors)
        splitter.addWidget(right)
        splitter.setSizes([260, 620, 400])

        status = QtWidgets.QStatusBar(self)
        self.setStatusBar(status)
        self.status_bar = status

    def _build_design_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(tab)
        self.design_theme_combo = QtWidgets.QComboBox(tab)
        self.design_theme_combo.addItems(list(THEME_PRESETS.keys()) + ["Custom"])
        self.design_primary = QtWidgets.QLineEdit(tab)
        self.design_surface = QtWidgets.QLineEdit(tab)
        self.design_text = QtWidgets.QLineEdit(tab)
        self.design_heading_font = QtWidgets.QComboBox(tab)
        self.design_heading_font.addItems(FONT_STACKS)
        self.design_body_font = QtWidgets.QComboBox(tab)
        self.design_body_font.addItems(FONT_STACKS)
        layout.addRow("Theme preset", self.design_theme_combo)
        layout.addRow("Primary color", self.design_primary)
        layout.addRow("Surface color", self.design_surface)
        layout.addRow("Text color", self.design_text)
        layout.addRow("Heading font", self.design_heading_font)
        layout.addRow("Body font", self.design_body_font)
        btn_row = QtWidgets.QHBoxLayout()
        self.btn_apply_theme = QtWidgets.QPushButton("Apply theme")
        self.btn_apply_theme.setMinimumHeight(40)
        self.btn_add_helpers = QtWidgets.QPushButton("Add CSS helpers")
        self.btn_add_helpers.setMinimumHeight(40)
        btn_row.addWidget(self.btn_apply_theme)
        btn_row.addWidget(self.btn_add_helpers)
        layout.addRow(btn_row)
        note = QtWidgets.QLabel(
            "Helper tip: theme updates refresh the base CSS. Helpers add spacing, buttons, and layout utilities."
        )
        note.setWordWrap(True)
        layout.addRow(note)
        return tab

    def _build_assets_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        button_row = QtWidgets.QHBoxLayout()
        self.btn_add_asset = QtWidgets.QPushButton("Add images…")
        self.btn_rename_asset = QtWidgets.QPushButton("Rename")
        self.btn_remove_asset = QtWidgets.QPushButton("Remove")
        button_row.addWidget(self.btn_add_asset)
        button_row.addWidget(self.btn_rename_asset)
        button_row.addWidget(self.btn_remove_asset)
        button_row.addStretch()
        layout.addLayout(button_row)
        self.asset_list = AssetListWidget(tab)
        self.asset_list.filesDropped.connect(self._import_assets)
        self.asset_list.currentRowChanged.connect(self._show_asset_preview)
        layout.addWidget(self.asset_list, 1)
        self.asset_preview = QtWidgets.QLabel("Drop images here or click Add.")
        self.asset_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.asset_preview.setMinimumHeight(160)
        layout.addWidget(self.asset_preview)
        self.btn_insert_image = QtWidgets.QPushButton("Insert responsive image")
        layout.addWidget(self.btn_insert_image)
        return tab

    def _build_menu(self) -> None:
        bar = self.menuBar()
        if bar is None:
            bar = QtWidgets.QMenuBar(self)
            self.setMenuBar(bar)
        file_menu = bar.addMenu("&File")
        self.act_new = QtGui.QAction("New…", self)
        self.act_open = QtGui.QAction("Open…", self)
        self.act_save = QtGui.QAction("Save", self)
        self.act_save_as = QtGui.QAction("Save As…", self)
        self.act_export = QtGui.QAction("Export…", self)
        self.act_start = QtGui.QAction("Start Page", self)
        self.act_quit = QtGui.QAction("Quit", self)
        self.act_new.setShortcut("Ctrl+N")
        self.act_open.setShortcut("Ctrl+O")
        self.act_save.setShortcut("Ctrl+S")
        self.act_save_as.setShortcut("Ctrl+Shift+S")
        self.act_export.setShortcut("Ctrl+E")
        self.act_start.setShortcut("Ctrl+R")
        if file_menu is not None:
            file_menu.addActions([self.act_new, self.act_open])
            file_menu.addSeparator()
            file_menu.addActions([self.act_save, self.act_save_as])
            file_menu.addSeparator()
            file_menu.addAction(self.act_export)
            file_menu.addSeparator()
            file_menu.addAction(self.act_start)
            file_menu.addSeparator()
            file_menu.addAction(self.act_quit)

        insert_menu = bar.addMenu("&Insert")
        if insert_menu is not None:
            self.menu_sections = insert_menu.addMenu("Sections")
            if self.menu_sections is not None:
                for key, snippet in SECTIONS_SNIPPETS.items():
                    action = QtGui.QAction(snippet.label, self)
                    action.triggered.connect(lambda checked=False, k=key: self.insert_snippet(k, section=True))
                    self.menu_sections.addAction(action)
            self.menu_components = insert_menu.addMenu("Components")
            if self.menu_components is not None:
                for key, snippet in COMPONENT_SNIPPETS.items():
                    action = QtGui.QAction(snippet.label, self)
                    action.triggered.connect(lambda checked=False, k=key: self.insert_snippet(k, section=False))
                    self.menu_components.addAction(action)

        help_menu = bar.addMenu("&Help")
        self.act_about = QtGui.QAction("About", self)
        self.act_get_started = QtGui.QAction("Get Started", self)
        self.act_about.setShortcut("F1")
        if help_menu is not None:
            help_menu.addAction(self.act_about)
            help_menu.addAction(self.act_get_started)

    def _bind_events(self) -> None:
        self.pages_list.currentRowChanged.connect(self._on_page_selected)
        self.html_editor.textChanged.connect(self._on_editor_changed)
        self.css_editor.textChanged.connect(self._on_editor_changed)
        self.btn_add_page.clicked.connect(self.add_page)
        self.btn_remove_page.clicked.connect(self.remove_page)
        self.btn_apply_theme.clicked.connect(self.apply_theme)
        self.btn_add_helpers.clicked.connect(self.add_css_helpers)
        self.btn_add_asset.clicked.connect(self._browse_assets)
        self.btn_rename_asset.clicked.connect(self._rename_asset)
        self.btn_remove_asset.clicked.connect(self._remove_asset)
        self.btn_insert_image.clicked.connect(self._insert_image_dialog)
        self.act_new.triggered.connect(lambda: self.controller.show_start_from_main("Create New"))
        self.act_open.triggered.connect(self.open_project_dialog)
        self.act_save.triggered.connect(self.save_project)
        self.act_save_as.triggered.connect(self.save_project_as)
        self.act_export.triggered.connect(self.export_project)
        self.act_quit.triggered.connect(self.close)
        self.act_start.triggered.connect(lambda: self.controller.show_start_from_main("Recent"))
        self.act_about.triggered.connect(self.show_about)
        self.act_get_started.triggered.connect(self._open_help_page)

    def _load_project_into_ui(self) -> None:
        self._refresh_pages_list()
        if self.project.pages:
            self.pages_list.setCurrentRow(0)
            self.html_editor.setPlainText(self.project.pages[0].html)
        self.css_editor.setPlainText(self.project.css)
        self.design_primary.setText(self.project.palette.get("primary", "#2563eb"))
        self.design_surface.setText(self.project.palette.get("surface", "#f8fafc"))
        self.design_text.setText(self.project.palette.get("text", "#0f172a"))
        self.design_heading_font.setCurrentText(self.project.fonts.get("heading", FONT_STACKS[0]))
        self.design_body_font.setCurrentText(self.project.fonts.get("body", FONT_STACKS[0]))
        self._refresh_assets()

    # Page management ---------------------------------------------------
    def _refresh_pages_list(self) -> None:
        self.pages_list.blockSignals(True)
        self.pages_list.clear()
        for page in self.project.pages:
            self.pages_list.addItem(f"{page.title} ({page.filename})")
        self.pages_list.blockSignals(False)

    def add_page(self) -> None:
        title, ok = QtWidgets.QInputDialog.getText(self, "Add page", "Title")
        if not ok or not title.strip():
            return
        title = title.strip()
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "page"
        filename = f"{slug}.html"
        existing = {p.filename for p in self.project.pages}
        counter = 1
        while filename in existing:
            filename = f"{slug}-{counter}.html"
            counter += 1
        self.project.pages.append(Page(filename=filename, title=title, html=f"<section class=\"section\">\n  <h1>{title}</h1>\n  <p>Start writing here.</p>\n</section>"))
        self._refresh_pages_list()
        self.pages_list.setCurrentRow(len(self.project.pages) - 1)
        self.update_preview()

    def remove_page(self) -> None:
        row = self.pages_list.currentRow()
        if row < 0 or row >= len(self.project.pages):
            return
        page = self.project.pages[row]
        if page.filename == "index.html":
            QtWidgets.QMessageBox.warning(self, "Not allowed", "Home cannot be removed.")
            return
        if QtWidgets.QMessageBox.question(
            self,
            "Remove page",
            f"Delete {page.title}?",
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        del self.project.pages[row]
        self._refresh_pages_list()
        self.pages_list.setCurrentRow(max(0, row - 1))
        self.update_preview()

    def _on_page_selected(self, index: int) -> None:
        if index < 0 or index >= len(self.project.pages):
            return
        self._flush_editors_to_model()
        page = self.project.pages[index]
        self.html_editor.blockSignals(True)
        self.html_editor.setPlainText(page.html)
        self.html_editor.blockSignals(False)
        self.update_preview()

    # Editing & preview -------------------------------------------------
    def _on_editor_changed(self) -> None:
        self._debounce.start()

    def _flush_editors_to_model(self) -> None:
        index = self.pages_list.currentRow()
        if 0 <= index < len(self.project.pages):
            self.project.pages[index].html = self.html_editor.toPlainText()
        self.project.css = self.css_editor.toPlainText()

    def update_preview(self) -> None:
        self._flush_editors_to_model()
        if self._preview_tmp and os.path.isdir(self._preview_tmp):
            shutil.rmtree(self._preview_tmp, ignore_errors=True)
        self._preview_tmp = tempfile.mkdtemp(prefix="webineer_preview_")
        render_project(self.project, Path(self._preview_tmp))
        index = self.pages_list.currentRow()
        if index < 0 and self.project.pages:
            index = 0
        if 0 <= index < len(self.project.pages):
            page = self.project.pages[index]
            file_path = Path(self._preview_tmp) / page.filename
            self.preview.setUrl(QtCore.QUrl.fromLocalFile(str(file_path)))
        self.status_bar.showMessage("Preview updated", 1500)

    def insert_snippet(self, key: str, section: bool) -> None:
        snippet = SECTIONS_SNIPPETS[key] if section else COMPONENT_SNIPPETS[key]
        cursor = self.html_editor.textCursor()
        if not cursor.hasSelection():
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        html = "\n\n" + snippet.html.strip() + "\n\n"
        cursor.insertText(html)
        self.html_editor.setTextCursor(cursor)
        if snippet.requires_js:
            self.project.use_main_js = True
        self.update_preview()

    # Theme helpers -----------------------------------------------------
    def apply_theme(self) -> None:
        palette = {
            "primary": self.design_primary.text().strip() or "#2563eb",
            "surface": self.design_surface.text().strip() or "#f8fafc",
            "text": self.design_text.text().strip() or "#0f172a",
        }
        fonts = {
            "heading": self.design_heading_font.currentText(),
            "body": self.design_body_font.currentText(),
        }
        theme = self.design_theme_combo.currentText()
        if theme in THEME_PRESETS:
            palette = dict(THEME_PRESETS[theme])
            self.design_primary.setText(palette["primary"])
            self.design_surface.setText(palette["surface"])
            self.design_text.setText(palette["text"])
        base_css = build_base_css(palette, fonts)
        current_css = self.css_editor.toPlainText()
        helpers_index = current_css.find(CSS_HELPERS_SENTINEL)
        remainder = ""
        if helpers_index != -1:
            remainder = current_css[helpers_index:]
        else:
            remainder = "\n\n" + CSS_HELPERS_BLOCK
        new_css = base_css.rstrip() + "\n\n" + remainder.strip() + "\n"
        self.css_editor.setPlainText(new_css)
        self.project.css = new_css
        self.project.palette = palette
        self.project.fonts = fonts
        self.project.theme_preset = theme
        self.update_preview()
        self.status_bar.showMessage("Theme applied", 4000)

    def add_css_helpers(self) -> None:
        css = self.css_editor.toPlainText()
        if CSS_HELPERS_SENTINEL in css:
            QtWidgets.QMessageBox.information(self, "Already added", "CSS helpers are already in your stylesheet.")
            return
        self.css_editor.appendPlainText("\n\n" + CSS_HELPERS_BLOCK)
        self.project.css = self.css_editor.toPlainText()
        self.update_preview()

    # Asset management --------------------------------------------------
    def _refresh_assets(self) -> None:
        self.asset_list.clear()
        for asset in self.project.images:
            item = QtWidgets.QListWidgetItem(f"{asset.name} ({asset.width}×{asset.height})")
            item.setData(Qt.ItemDataRole.UserRole, asset)
            self.asset_list.addItem(item)

    def _browse_assets(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Add images",
            self.settings.get("last_asset_dir", str(Path.home())),
            "Images (*.png *.jpg *.jpeg *.gif *.svg)",
        )
        if paths:
            self.settings.set("last_asset_dir", str(Path(paths[0]).parent))
            self._import_assets(paths)

    def _import_assets(self, paths: List[str]) -> None:
        added = 0
        for path_str in paths:
            path = Path(path_str)
            asset = self._asset_from_file(path)
            if asset:
                asset.name = self._unique_asset_name(asset.name)
                self.project.images.append(asset)
                added += 1
        if added:
            self._refresh_assets()
            self.status_bar.showMessage(f"Added {added} asset(s)", 3000)
            self.update_preview()

    def _asset_from_file(self, path: Path) -> Optional[AssetImage]:
        if not path.exists():
            return None
        image = QtGui.QImage(str(path))
        if image.isNull():
            QtWidgets.QMessageBox.warning(self, "Unsupported", f"Could not load {path.name}.")
            return None
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, Path(path).suffix.replace(".", "").upper() or "PNG")
        data = base64.b64encode(buffer.data().data()).decode("ascii")
        mime = "image/png"
        if path.suffix.lower() in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        elif path.suffix.lower() == ".gif":
            mime = "image/gif"
        elif path.suffix.lower() == ".svg":
            mime = "image/svg+xml"
        return AssetImage(name=path.name, data_base64=data, width=image.width(), height=image.height(), mime=mime)

    def _unique_asset_name(self, name: str, exclude: Optional[str] = None) -> str:
        existing = {asset.name for asset in self.project.images if asset.name != exclude}
        if name not in existing:
            return name
        base = Path(name).stem
        ext = Path(name).suffix or ".png"
        counter = 1
        candidate = f"{base}-{counter}{ext}"
        while candidate in existing:
            counter += 1
            candidate = f"{base}-{counter}{ext}"
        return candidate

    def _show_asset_preview(self, row: int) -> None:
        if row < 0 or row >= len(self.project.images):
            self.asset_preview.setText("Drop images here or click Add.")
            self.asset_preview.setPixmap(QtGui.QPixmap())
            return
        asset = self.project.images[row]
        data = base64.b64decode(asset.data_base64.encode("ascii"))
        pixmap = QtGui.QPixmap()
        pixmap.loadFromData(data)
        scaled = pixmap.scaled(240, 160, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.asset_preview.setPixmap(scaled)

    def _rename_asset(self) -> None:
        row = self.asset_list.currentRow()
        if row < 0 or row >= len(self.project.images):
            return
        asset = self.project.images[row]
        new_name, ok = QtWidgets.QInputDialog.getText(self, "Rename asset", "File name", text=asset.name)
        if not ok or not new_name.strip():
            return
        new_name = self._unique_asset_name(new_name.strip(), exclude=asset.name)
        asset.name = new_name
        self._refresh_assets()

    def _remove_asset(self) -> None:
        row = self.asset_list.currentRow()
        if row < 0 or row >= len(self.project.images):
            return
        if QtWidgets.QMessageBox.question(self, "Remove asset", "Remove this image from the project?") != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        del self.project.images[row]
        self._refresh_assets()
        self.asset_preview.setPixmap(QtGui.QPixmap())
        self.update_preview()

    def _insert_image_dialog(self) -> None:
        row = self.asset_list.currentRow()
        if row < 0 or row >= len(self.project.images):
            QtWidgets.QMessageBox.information(self, "Select image", "Choose an image first.")
            return
        asset = self.project.images[row]
        alt, ok = QtWidgets.QInputDialog.getText(self, "Alt text", "Describe the image", text="")
        if not ok:
            return
        width, ok_w = QtWidgets.QInputDialog.getInt(self, "Width", "Width (px)", value=max(1, asset.width), min=1)
        if not ok_w:
            return
        height, ok_h = QtWidgets.QInputDialog.getInt(self, "Height", "Height (px)", value=max(1, asset.height), min=1)
        if not ok_h:
            return
        html = (
            f"<figure class=\"max-w-md\">\n  <img src=\"assets/images/{asset.name}\" alt=\"{alt}\" width=\"{width}\" height=\"{height}\">\n"
            "  <figcaption>Optional caption</figcaption>\n</figure>\n"
        )
        cursor = self.html_editor.textCursor()
        cursor.insertText(html)
        self.html_editor.setTextCursor(cursor)
        self.update_preview()

    # File operations ---------------------------------------------------
    def open_project_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open project",
            self.settings.get("last_open_dir", str(Path.home())),
            "Webineer Project (*.siteproj)",
        )
        if not path:
            return
        self.settings.set("last_open_dir", str(Path(path).parent))
        try:
            result = load_project(Path(path))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Error", f"Could not open project:\n{exc}")
            return
        self.project = result.project
        self.project_path = Path(path)
        self.project.output_dir = str(self.project_path.parent)
        if result.migrated:
            QtWidgets.QMessageBox.information(self, "Upgraded", "Project upgraded to the latest format.")
        self._load_project_into_ui()
        self.update_preview()
        self.recents.add_or_bump(self.project_path, self.project)
        thumb = write_project_thumbnail(self.project, self.project_path)
        if thumb:
            self.recents.set_thumbnail(self.project_path, thumb)

    def save_project(self) -> None:
        if self.project_path is None:
            self.save_project_as()
            return
        self._flush_editors_to_model()
        try:
            save_project(self.project_path, self.project)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Error", f"Could not save:\n{exc}")
            return
        self.status_bar.showMessage("Project saved", 2000)
        self.recents.add_or_bump(self.project_path, self.project)
        thumb = write_project_thumbnail(self.project, self.project_path)
        if thumb:
            self.recents.set_thumbnail(self.project_path, thumb)

    def save_project_as(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save project as",
            str(self.project_path or Path.home() / "MySite.siteproj"),
            "Webineer Project (*.siteproj)",
        )
        if not path:
            return
        path_obj = Path(path)
        if path_obj.suffix != ".siteproj":
            path_obj = path_obj.with_suffix(".siteproj")
        self.project_path = path_obj
        self.project.output_dir = str(path_obj.parent)
        self.save_project()

    def export_project(self) -> None:
        self._flush_editors_to_model()
        out_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Export site",
            self.project.output_dir or str(Path.home()),
        )
        if not out_dir:
            return
        try:
            render_project(self.project, Path(out_dir))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.status_bar.showMessage(f"Exported to {out_dir}", 4000)
        QtWidgets.QMessageBox.information(self, "Export complete", f"Your site was exported to:\n{out_dir}")

    # Misc --------------------------------------------------------------
    def show_about(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "About Webineer",
            "Webineer Site Builder\nCreate polished static websites in minutes.",
        )

    def _open_help_page(self) -> None:
        html = """
<!doctype html>
<html><body style=\"font-family: system-ui; padding: 2rem; max-width: 720px; margin: auto;\">
<h1>Welcome to Webineer</h1>
<p>Use the Start Page to spin up a project with templates, themes, and ready-made sections.</p>
<ol>
  <li>Pick a template and theme.</li>
  <li>Add sections from the Insert menu.</li>
  <li>Drop in images from the Assets tab and export when ready.</li>
</ol>
<p>Need inspiration? Try the "Make it for me" button on the start page.</p>
</body></html>
"""
        self.preview.setHtml(html)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._preview_tmp and os.path.isdir(self._preview_tmp):
            shutil.rmtree(self._preview_tmp, ignore_errors=True)
        super().closeEvent(event)

    def show_tab(self, name: str) -> None:
        # MainWindow does not have nav_list; this method is a no-op or should be removed.
        pass

# ---------------------------------------------------------------------------
# Application controller
# ---------------------------------------------------------------------------


class AppController(QtCore.QObject):
    def __init__(self, app: QtWidgets.QApplication) -> None:
        super().__init__()
        self.app = app
        self.settings = SettingsManager()
        self.recents = RecentProjectsManager()
        self.start_window: Optional[StartWindow] = None
        self.main_windows: List[MainWindow] = []

    def show_start(self, tab: Optional[str] = None) -> None:
        if self.start_window is None:
            self.start_window = StartWindow(self, self.recents, self.settings)
            self.start_window.project_opened.connect(self.open_project_from_start)
        # if tab:
        #     self.start_window.show_tab(tab)
        self.start_window.show()
        self.start_window.raise_()
        self.start_window.activateWindow()

    def show_start_from_main(self, tab: str = "Create New") -> None:
        self.show_start(tab)

    def open_project_from_start(self, project: Project, path_obj: object) -> None:
        path: Optional[Path]
        if isinstance(path_obj, Path):
            path = path_obj
        elif isinstance(path_obj, str):
            path = Path(path_obj)
        else:
            path = None
        window = MainWindow(self, project, path, self.recents, self.settings)
        window.destroyed.connect(lambda: self._remove_main_window(window))
        self.main_windows.append(window)
        window.show()
        if path is not None:
            self.recents.add_or_bump(path, project)
            thumb = write_project_thumbnail(project, path)
            if thumb:
                self.recents.set_thumbnail(path, thumb)
        if self.start_window is not None:
            self.start_window.close()
            self.start_window = None

    def _remove_main_window(self, window: MainWindow) -> None:
        self.main_windows = [w for w in self.main_windows if w is not window]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Webineer")
    controller = AppController(app)
    controller.show_start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
