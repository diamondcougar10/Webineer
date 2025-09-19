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
