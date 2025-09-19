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
