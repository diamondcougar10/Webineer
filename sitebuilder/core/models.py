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
