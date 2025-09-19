"""
Webineer Site Builder — Enhanced single-file PyQt6 app
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
from typing import List, Optional, Dict, Tuple

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
<section class='hero'>
  <p class='eyebrow'>Build in minutes</p>
  <h2 class='hero-title'>Launch something memorable.</h2>
  <p class='hero-lede'>Webineer gives you polished building blocks so you can focus on your story.</p>
  <div class='hero-actions'>
    <a class='btn btn-primary btn-lg' href='#features'>Create my site</a>
    <a class='btn btn-ghost btn-lg' href='#cta'>Explore layout ideas</a>
  </div>
</section>
<section id='features' class='section'>
  <div class='container-narrow stack'>
    <h3 class='text-center'>Handy building blocks</h3>
    <p class='muted text-center'>Use snippets for testimonials, pricing tables, image grids, and more&mdash;skip blank-page syndrome.</p>
  </div>
  <div class='feature-grid'>
    <div class='card stack'>
      <span class='badge'>01</span>
      <h4>Pick a template</h4>
      <p>Start from a curated layout that already respects spacing and typography.</p>
    </div>
    <div class='card stack'>
      <span class='badge'>02</span>
      <h4>Mix in sections</h4>
      <p>Insert ready-made hero, pricing, FAQ, and contact sections right from the menu.</p>
    </div>
    <div class='card stack'>
      <span class='badge'>03</span>
      <h4>Publish anywhere</h4>
      <p>Export a static site and host it on GitHub Pages, Netlify, or any static host.</p>
    </div>
  </div>
</section>
<section class='section-alt'>
  <div class='split'>
    <div class='card stack'>
      <h3>Organize your content</h3>
      <p class='muted'>Use multiple pages with automatic navigation and keep shared styles in one place.</p>
      <ul class='list-check'>
        <li>Preview updates instantly</li>
        <li>Store assets alongside your project</li>
        <li>Export clean HTML + CSS bundles</li>
      </ul>
    </div>
    <div class='card stack'>
      <blockquote class='quote'>&ldquo;Webineer helped us launch a polished microsite in an afternoon.&rdquo;</blockquote>
      <p class='quote-attribution'>&mdash; Taylor, marketing lead</p>
      <p class='muted'>Swap this testimonial with your own customer story.</p>
    </div>
  </div>
</section>
<section id='cta' class='section text-center'>
  <h3>Ready to share your site?</h3>
  <p class='muted'>Tweak the copy, add a few assets, and publish your pages on the web in minutes.</p>
  <div class='hero-actions'>
    <a class='btn btn-primary btn-lg' href='#'>Export sample</a>
    <a class='btn btn-outline btn-lg' href='#'>View publishing tips</a>
  </div>
</section>
"""


# ---------------------- Data Model & Persistence ----------------------



@dataclass
class TemplateSpec:
    name: str
    description: str
    pages: List[Tuple[str, str, str]]
    palette: Optional[Dict[str, str]] = None
    fonts: Optional[Dict[str, str]] = None
    extra_css: str = ""
    include_helpers: bool = True

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
TEMPLATE_EXTRA_SENTINEL = "/* === WEBINEER TEMPLATE EXTRA CSS === */"

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


PROJECT_TEMPLATES: Dict[str, TemplateSpec] = {
    "starter": TemplateSpec(
        name="Starter landing",
        description="Hero, features, testimonial, and publishing CTA.",
        pages=[
            (
                "index.html",
                "Home",
                "".join([
                    html_section_hero()
                        .replace("Welcome!", "Launch something memorable.")
                        .replace("Build beautiful sites with zero fuss.", "Tweak copy, add assets, and hit publish in minutes.")
                        .replace("Get started", "Preview sections"),
                    html_section_features()
                        .replace("Features", "Handy building blocks"),
                    html_section_two_column()
                        .replace("Headline", "Share social proof")
                        .replace("Explain your value proposition. Keep it short and focused.", "Drop in a customer quote or quick case study to build trust before your CTA."),
                    html_section_cta()
                        .replace("Ready to get started?", "Ready to share your site?")
                        .replace("Create my site", "Export this project"),
                ]),
            ),
        ],
    ),
    "portfolio": TemplateSpec(
        name="Portfolio spotlight",
        description="Introduce yourself, highlight a project, and invite conversations.",
        pages=[
            (
                "index.html",
                "Home",
                "".join([
                    html_section_hero()
                        .replace("Welcome!", "Hi, I'm Riley.")
                        .replace("Build beautiful sites with zero fuss.", "I design onboarding flows that turn users into champions.")
                        .replace("Get started", "View case studies"),
                    html_section_two_column()
                        .replace("Headline", "Case study highlight")
                        .replace("Explain your value proposition. Keep it short and focused.", "Summarize a recent win and link out to a detailed write-up.")
                        .replace("Learn more", "Read the project"),
                    html_section_features()
                        .replace("Features", "What I love to work on")
                        .replace("Speed", "Product strategy")
                        .replace("Simplicity", "End-to-end design")
                        .replace("Portability", "Research & facilitation"),
                    html_section_cta()
                        .replace("Ready to get started?", "Need a design partner?")
                        .replace("Create my site", "Start a conversation"),
                ]),
            ),
        ],
    ),
    "resource": TemplateSpec(
        name="Resource hub",
        description="Organize guides, troubleshooting steps, and FAQs for your audience.",
        pages=[
            (
                "index.html",
                "Overview",
                "".join([
                    html_section_hero()
                        .replace("Welcome!", "Create a helpful resource hub")
                        .replace("Build beautiful sites with zero fuss.", "Collect how-tos, release notes, and quick answers in one place.")
                        .replace("Get started", "Browse guides"),
                    html_section_features()
                        .replace("Features", "Popular resources")
                        .replace("Speed", "Quick start guide")
                        .replace("Simplicity", "Troubleshooting")
                        .replace("Portability", "Release updates"),
                    html_section_faq()
                        .replace("Does this need hosting?", "How do I add a new article?")
                        .replace("Can I use my own CSS?", "Can I embed screenshots?")
                        .replace(
                            "You can host anywhere that serves static files (GitHub Pages, Netlify, S3...).",
                            "Use the Pages panel to add a page, rename it, and drop in content sections.",
                        )
                        .replace(
                            "Yes, edit the Styles tab or paste your stylesheet.",
                            "Absolutely. Upload images in the Assets tab and reference them in your guide.",
                        ),
                    html_section_cta()
                        .replace("Ready to get started?", "Need help fast?")
                        .replace("Create my site", "Email support"),
                ]),
            ),
        ],
    ),
}
DEFAULT_TEMPLATE_KEY = "starter"


STARTER_TEMPLATE_CSS = """/* Template: Starter Landing */
.hero {
  text-align: center;
  background: color-mix(in srgb, var(--color-primary) 8%, var(--color-surface));
  box-shadow: 0 16px 48px rgba(15, 23, 42, .12);
}
.hero-actions .btn {
  min-width: 11rem;
}
.feature-grid .card {
  transition: transform .18s ease, box-shadow .18s ease;
}
.feature-grid .card:hover {
  transform: translateY(-4px);
  box-shadow: 0 22px 45px rgba(15, 23, 42, .18);
}
.split .card {
  background: var(--color-surface);
}
"""

PORTFOLIO_INDEX_HTML = """<section class="hero portfolio-hero">
  <div class="hero-inner">
    <p class="eyebrow">Product designer</p>
    <h2>Hi, I'm Riley Stone.</h2>
    <p class="hero-lede">I help SaaS teams craft human-centered onboarding and growth experiences.</p>
    <div class="hero-actions">
      <a class="btn btn-primary btn-lg" href="#projects">View projects</a>
      <a class="btn btn-soft btn-lg" href="projects.html">Case studies</a>
    </div>
  </div>
  <div class="hero-image">
    <div class="profile-placeholder">Add your portrait</div>
  </div>
</section>
<section id="projects" class="section">
  <div class="stack text-center max-w-lg">
    <p class="eyebrow">Selected work</p>
    <h3>Showcase impactful projects</h3>
    <p class="text-muted">Swap these cards with your own case studies and highlight outcomes.</p>
  </div>
  <div class="portfolio-grid">
    <article class="project-card stack">
      <h4>Checkout flow redesign</h4>
      <p class="text-muted">Increased conversions 18% for a developer tools platform.</p>
      <a class="btn btn-ghost" href="projects.html#checkout">Read the case study</a>
    </article>
    <article class="project-card stack">
      <h4>Analytics dashboard</h4>
      <p class="text-muted">Delivered an insights hub the whole team can trust.</p>
      <a class="btn btn-ghost" href="projects.html#dashboard">View highlights</a>
    </article>
    <article class="project-card stack">
      <h4>Onboarding refresh</h4>
      <p class="text-muted">Cut time-to-value in half with contextual walkthroughs.</p>
      <a class="btn btn-ghost" href="projects.html#onboarding">See outcomes</a>
    </article>
  </div>
</section>
<section class="section-alt">
  <div class="timeline">
    <article class="timeline-item">
      <h4>Current</h4>
      <p class="text-muted">Design lead at BrightStack, shaping onboarding for 2M users.</p>
    </article>
    <article class="timeline-item">
      <h4>Previously</h4>
      <p class="text-muted">Product designer at Northwind, focused on growth experimentation.</p>
    </article>
    <article class="timeline-item">
      <h4>Tools</h4>
      <p class="text-muted">Figma, FigJam, Maze, Miro, Notion, Webflow, HTML/CSS.</p>
    </article>
  </div>
</section>
<section class="section">
  <div class="contact-card stack text-center">
    <h3>Let's build something great</h3>
    <p class="text-muted">Share a challenge or say hello at <a href="mailto:riley@example.com">riley@example.com</a>.</p>
    <div class="hero-actions">
      <a class="btn btn-primary btn-lg" href="mailto:riley@example.com">Book a call</a>
      <a class="btn btn-outline btn-lg" href="projects.html">See full portfolio</a>
    </div>
  </div>
</section>
"""

PORTFOLIO_PROJECTS_HTML = """<section class="section container-narrow" id="checkout">
  <h2>Selected case studies</h2>
  <article class="case-study stack">
    <h3>Checkout flow redesign</h3>
    <p class="text-muted">A five-week sprint to simplify purchasing for a developer tools platform.</p>
    <div class="stack">
      <h4>Outcome</h4>
      <ul class="list-check">
        <li>18% increase in conversions</li>
        <li>Reduced time-to-purchase by 42 seconds</li>
        <li>Streamlined plan selection for teams</li>
      </ul>
    </div>
  </article>
  <hr class="divider">
  <article class="case-study stack" id="dashboard">
    <h3>Analytics dashboard</h3>
    <p class="text-muted">Turning dense data into actionable insights for customer success teams.</p>
    <p>Introduce saved views, smarter defaults, and contextual glossary tips to keep teams aligned.</p>
  </article>
  <hr class="divider">
  <article class="case-study stack" id="onboarding">
    <h3>Onboarding refresh</h3>
    <p class="text-muted">Contextual in-app education that cut time-to-value in half.</p>
    <p>Add your own screenshots, quotes, and learnings here.</p>
  </article>
</section>
"""

PORTFOLIO_TEMPLATE_CSS = """/* Template: Portfolio Spotlight */
.portfolio-hero {
  display: grid;
  gap: 2.5rem;
  padding-block: 3.5rem;
}
.hero-inner {
  display: grid;
  gap: 1rem;
}
.hero-image {
  display: flex;
  align-items: center;
  justify-content: center;
}
.profile-placeholder {
  width: 220px;
  height: 220px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--color-primary) 18%, var(--color-surface));
  color: var(--color-primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  letter-spacing: .05em;
  text-transform: uppercase;
}
.portfolio-grid {
  margin-top: 2.5rem;
}
.project-card {
  border-radius: var(--radius);
  border: 1px solid rgba(15, 23, 42, .08);
  padding: 1.5rem;
  background: var(--color-surface);
  box-shadow: 0 18px 50px rgba(15, 23, 42, .1);
}
.timeline-item {
  background: var(--color-surface);
  padding: 1.5rem 1.75rem;
  border-radius: var(--radius);
  box-shadow: 0 16px 40px rgba(15, 23, 42, .12);
}
.contact-card {
  padding: 2.5rem;
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--color-primary) 12%, var(--color-surface));
  box-shadow: 0 20px 48px rgba(15, 23, 42, .16);
}
@media (min-width: 840px) {
  .portfolio-hero {
    grid-template-columns: 3fr 2fr;
    align-items: center;
  }
}
"""

RESOURCE_INDEX_HTML = """<section class="hero docs-hero">
  <h2>Create a helpful resource hub</h2>
  <p class="hero-lede">Share product guides, onboarding steps, and FAQs with a clean, readable layout.</p>
  <div class="hero-actions">
    <a class="btn btn-primary btn-lg" href="#articles">Browse guides</a>
    <a class="btn btn-soft btn-lg" href="guide.html">Read the quick start</a>
  </div>
</section>
<section id="articles" class="section">
  <div class="docs-grid">
    <article class="doc-card stack">
      <h3>Getting started</h3>
      <p class="text-muted">Introduce your product and explain what to expect.</p>
      <a class="btn btn-outline" href="guide.html#basics">View outline</a>
    </article>
    <article class="doc-card stack">
      <h3>Troubleshooting</h3>
      <p class="text-muted">List common issues with quick fixes your users can try.</p>
      <a class="btn btn-outline" href="guide.html#faq">Jump to FAQs</a>
    </article>
    <article class="doc-card stack">
      <h3>Release notes</h3>
      <p class="text-muted">Keep your audience updated with the latest improvements.</p>
      <a class="btn btn-outline" href="#">Add a changelog</a>
    </article>
  </div>
</section>
<section class="section-alt">
  <div class="split">
    <div class="card stack">
      <h3>Keep things organized</h3>
      <p class="text-muted">Group related pages, surface next steps, and cross-link key resources.</p>
      <ul class="list-inline">
        <li>Callout tips</li>
        <li>Step-by-step tasks</li>
        <li>Release updates</li>
      </ul>
    </div>
    <div class="card stack">
      <h3>Share quick answers</h3>
      <details class="faq">
        <summary>How do I add a new page?</summary>
        <p>Use the Pages panel to add one, rename it, and start editing the HTML.</p>
      </details>
      <details class="faq">
        <summary>Can I paste my own CSS?</summary>
        <p>Yes&mdash;drop it into the Styles tab or use the Design tab to generate a theme first.</p>
      </details>
    </div>
  </div>
</section>
"""

RESOURCE_GUIDE_HTML = """<section class="section container-narrow" id="basics">
  <h2>Quick start guide</h2>
  <p class="text-muted">Use this outline to document a process or product quickly.</p>
  <ol class="stepper">
    <li>
      <h3>Explain the goal</h3>
      <p>Start with a short description of what someone will achieve and why it matters.</p>
    </li>
    <li>
      <h3>List the steps</h3>
      <p>Break the process into clear, numbered steps. Screenshots help readers stay oriented.</p>
    </li>
    <li>
      <h3>Highlight best practices</h3>
      <p>Call out gotchas, shortcuts, or recommended tools to stay on track.</p>
    </li>
  </ol>
  <aside class="callout"><strong>Tip:</strong> Link to supporting docs or video tutorials so readers can dive deeper.</p>
  <section class="section-tight" id="faq">
    <h3>FAQs</h3>
    <ul class="list-check">
      <li>How do I share this page? &mdash; Export and upload it to your static host.</li>
      <li>Can I add more sections? &mdash; Duplicate the markup and tailor it to your product.</li>
      <li>Where do I edit styles? &mdash; Use the Styles tab or the Design tab for theme tweaks.</li>
    </ul>
  </section>
</section>
"""

RESOURCE_TEMPLATE_CSS = """/* Template: Resource Hub */
.docs-hero {
  text-align: center;
  padding-block: 3rem;
  background: color-mix(in srgb, var(--color-primary) 6%, var(--color-surface));
  box-shadow: 0 18px 40px rgba(15, 23, 42, .12);
}
.docs-grid {
  margin-top: 2.5rem;
}
.doc-card {
  border-radius: var(--radius);
  border: 1px solid rgba(15, 23, 42, .08);
  padding: 1.5rem;
  background: var(--color-surface);
  box-shadow: 0 16px 45px rgba(15, 23, 42, .1);
}
.callout {
  margin-top: 2.5rem;
}
.faq summary {
  font-weight: 600;
}
"""

def css_helpers_block() -> str:
    css = """\n:root {
  --sp-1: .25rem;
  --sp-2: .5rem;
  --sp-3: 1rem;
  --sp-4: 1.5rem;
  --sp-5: 2rem;
  --sp-6: 3rem;
}
.section {
  padding-block: var(--sp-6);
}
.section-tight {
  padding-block: var(--sp-5);
}
.section-alt {
  padding-block: var(--sp-6);
  background: color-mix(in srgb, var(--color-primary) 10%, var(--color-surface));
}
.stack {
  display: grid;
  gap: var(--sp-3);
}
.stack-lg {
  display: grid;
  gap: var(--sp-4);
}
.split {
  display: grid;
  gap: var(--sp-4);
}
@media (min-width: 768px) {
  .split {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: center;
  }
}
.hero-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: var(--sp-3);
}
.feature-grid {
  display: grid;
  gap: var(--sp-4);
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  margin-top: var(--sp-5);
}
.docs-grid {
  display: grid;
  gap: var(--sp-4);
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}
.portfolio-grid {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}
.timeline {
  display: grid;
  gap: var(--sp-3);
}
.timeline-item {
  border-left: 3px solid var(--color-primary);
  padding-left: calc(var(--sp-3) + .35rem);
}
.case-study {
  display: grid;
  gap: var(--sp-3);
}
.grid-auto {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
}
.stepper {
  list-style: none;
  padding-left: 0;
  display: grid;
  gap: var(--sp-3);
  counter-reset: step;
}
.stepper li {
  border-left: 3px solid var(--color-primary);
  padding-left: calc(var(--sp-3) + .35rem);
  position: relative;
}
.stepper li::before {
  counter-increment: step;
  content: counter(step, decimal-leading-zero);
  position: absolute;
  left: calc(-1 * var(--sp-5));
  top: 0;
  font-weight: 600;
  color: var(--color-primary);
}
.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-primary) 18%, var(--color-surface));
  color: var(--color-primary);
  font-weight: 600;
  letter-spacing: .06em;
}
.list-check {
  list-style: none;
  padding-left: 0;
  display: grid;
  gap: var(--sp-2);
}
.list-check li::before {
  content: "\2713";
  margin-right: .5rem;
  color: var(--color-primary);
  font-weight: 600;
}
.list-inline {
  list-style: none;
  padding-left: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}
.list-inline li {
  background: color-mix(in srgb, var(--color-primary) 15%, var(--color-surface));
  padding: .35rem .85rem;
  border-radius: 999px;
  font-size: .9rem;
}
.eyebrow {
  text-transform: uppercase;
  letter-spacing: .18em;
  font-size: .75rem;
  margin-bottom: var(--sp-2);
  display: inline-block;
  opacity: .75;
}
.text-muted {
  color: rgba(15, 23, 42, .68);
}
.btn-soft {
  background: color-mix(in srgb, var(--color-primary) 12%, var(--color-surface));
  border-color: transparent;
  color: var(--color-primary);
}
.btn-pill {
  border-radius: 999px;
}
.shadow-sm {
  box-shadow: 0 16px 32px rgba(15, 23, 42, .08);
}
.shadow-md {
  box-shadow: 0 30px 60px rgba(15, 23, 42, .16);
}
.max-w-md {
  max-width: 40rem;
  margin-inline: auto;
}
.max-w-lg {
  max-width: 56rem;
  margin-inline: auto;
}
.container-narrow {
  max-width: 780px;
  margin-inline: auto;
  padding: 0 1rem;
}
.callout {
  border-left: 4px solid var(--color-primary);
  background: color-mix(in srgb, var(--color-primary) 8%, var(--color-surface));
  padding: var(--sp-3);
  border-radius: var(--radius);
}
.divider {
  border: 0;
  border-top: 1px solid rgba(15, 23, 42, .12);
  margin: var(--sp-5) 0;
}
details.faq {
  border: 1px solid rgba(15, 23, 42, .12);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--color-primary) 6%, var(--color-surface));
  padding: var(--sp-3);
}
details.faq summary {
  cursor: pointer;
  font-weight: 600;
}
.text-center {
  text-align: center;
}
.text-left {
  text-align: left;
}
.text-right {
  text-align: right;
}
.gap-sm {
  gap: var(--sp-2);
}
.gap-lg {
  gap: var(--sp-5);
}
.mt-1 {
  margin-top: var(--sp-2);
}
.mt-2 {
  margin-top: var(--sp-3);
}
.mt-3 {
  margin-top: var(--sp-4);
}
.mt-4 {
  margin-top: var(--sp-5);
}
.mb-1 {
  margin-bottom: var(--sp-2);
}
.mb-2 {
  margin-bottom: var(--sp-3);
}
.mb-3 {
  margin-bottom: var(--sp-4);
}
.mb-4 {
  margin-bottom: var(--sp-5);
}
.bg-tint {
  background: color-mix(in srgb, var(--color-primary) 10%, var(--color-surface));
}
.w-full {
  width: 100%;
}
"""
    return f"{CSS_HELPERS_SENTINEL}\n{css.strip()}"

def template_extra_css_block(extra_css: str) -> str:
    extra_css = extra_css.strip()
    if not extra_css:
        return ""
    if not extra_css.endswith(""):
        extra_css += ""
    return f"{TEMPLATE_EXTRA_SENTINEL}{extra_css}"

def extract_css_block(css: str, sentinel: str) -> Tuple[str, str]:
    before, marker, after = css.partition(sentinel)
    if not marker:
        return css, ""
    block = (marker + after).strip()
    base = before.rstrip()
    return base, block

PROJECT_TEMPLATES = {
    "starter": TemplateSpec(
        name="Starter landing",
        description="Versatile marketing layout with hero, features, and testimonial.",
        pages=[
            ("index.html", "Home", DEFAULT_INDEX_HTML),
        ],
        extra_css=STARTER_TEMPLATE_CSS,
        include_helpers=True,
    ),
    "portfolio": TemplateSpec(
        name="Portfolio spotlight",
        description="Introduce yourself, showcase projects, and invite conversations.",
        pages=[
            ("index.html", "Home", PORTFOLIO_INDEX_HTML),
            ("projects.html", "Projects", PORTFOLIO_PROJECTS_HTML),
        ],
        palette=dict(primary="#7c3aed", surface="#fcfbff", text="#1f2933"),
        fonts=dict(
            heading="Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Arial",
            body="Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Arial",
        ),
        extra_css=PORTFOLIO_TEMPLATE_CSS,
        include_helpers=True,
    ),
    "resource": TemplateSpec(
        name="Resource hub",
        description="Organize guides, troubleshooting steps, and FAQs with ease.",
        pages=[
            ("index.html", "Overview", RESOURCE_INDEX_HTML),
            ("guide.html", "Quick start guide", RESOURCE_GUIDE_HTML),
        ],
        palette=dict(primary="#0ea5e9", surface="#f5faff", text="#0f172a"),
        fonts=dict(
            heading="Segoe UI, system-ui, -apple-system, Roboto, Ubuntu, 'Helvetica Neue', Arial",
            body="Segoe UI, system-ui, -apple-system, Roboto, Ubuntu, 'Helvetica Neue', Arial",
        ),
        extra_css=RESOURCE_TEMPLATE_CSS,
        include_helpers=True,
    ),
}
DEFAULT_TEMPLATE_KEY = "starter"


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

        self.status = self.statusBar()

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
        m_file = bar.addMenu("&File")
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
        m_insert = bar.addMenu("&Insert")
        sec = m_insert.addMenu("Section")
        self._add_action(sec, "Hero", lambda: self.insert_html(html_section_hero()))
        self._add_action(sec, "Features grid", lambda: self.insert_html(html_section_features()))
        self._add_action(sec, "Two‑column (image + text)", lambda: self.insert_html(html_section_two_column()))
        self._add_action(sec, "Call‑to‑Action", lambda: self.insert_html(html_section_cta()))
        self._add_action(sec, "FAQ", lambda: self.insert_html(html_section_faq()))
        self._add_action(sec, "Pricing", lambda: self.insert_html(html_section_pricing()))

        gfx = m_insert.addMenu("Graphics")
        self._add_action(gfx, "Wave divider (top)", lambda: self.insert_html(svg_wave(self.project.palette["surface"], False)))
        self._add_action(gfx, "Wave divider (bottom)", lambda: self.insert_html(svg_wave(self.project.palette["surface"], True)))
        self._add_action(gfx, "Placeholder image…", self.insert_placeholder_dialog)

        icons = m_insert.addMenu("Icon (inline SVG)")
        for name in sorted(ICONS.keys()):
            self._add_action(icons, name, lambda n=name: self.insert_html(ICONS[n]))

        # CSS menu
        m_css = bar.addMenu("&CSS")
        self._add_action(m_css, "Append CSS helpers", self.append_css_helpers)
        self._add_action(m_css, "Reset CSS to Design", self.apply_design_to_css)

        # Help
        m_help = bar.addMenu("&Help")
        self.act_about = QtGui.QAction("About", self)
        m_help.addAction(self.act_about)

    def _add_action(self, menu: QtWidgets.QMenu, title: str, slot) -> None:
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
