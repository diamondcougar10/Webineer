"""Site export helpers."""

from __future__ import annotations

import base64
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Project


def _env(templates_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def render_site(project: Project, output_dir: str | Path, templates_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    assets_root = output_dir / "assets"

    # Write CSS
    css_dir = assets_root / "css"
    css_dir.mkdir(parents=True, exist_ok=True)
    (css_dir / "style.css").write_text(project.css, encoding="utf-8")

    # Write binary assets bundled with the project
    for asset in project.assets:
        if not asset.data_base64:
            continue
        dest_subdir = {
            "images": "images",
            "fonts": "fonts",
            "media": "media",
            "js": "js",
        }.get(asset.kind, "files")
        dest_dir = assets_root / dest_subdir
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            data = base64.b64decode(asset.data_base64.encode("ascii"))
        except Exception:
            continue
        (dest_dir / asset.name).write_bytes(data)

    env = _env(templates_dir)
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

