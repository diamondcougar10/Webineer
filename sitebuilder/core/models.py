"""Data models for the site builder application."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import List, Optional


@dataclass
class Page:
    filename: str
    title: str
    html: str


@dataclass
class Asset:
    """A binary asset bundled with the project."""

    name: str
    data_base64: str
    kind: str  # images, fonts, media, js, other

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "data_base64": self.data_base64,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Asset":
        return cls(
            name=data.get("name", "asset"),
            data_base64=data.get("data_base64", ""),
            kind=data.get("kind", "other"),
        )


@dataclass
class Project:
    name: str
    pages: List[Page]
    css: str
    output_dir: Optional[str] = None
    version: int = 1
    assets: List[Asset] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "css": self.css,
            "output_dir": self.output_dir,
            "version": self.version,
            "pages": [asdict(p) for p in self.pages],
            "assets": [asset.to_dict() for asset in self.assets],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        pages = [Page(**p) for p in data.get("pages", [])]
        assets_data = data.get("assets", [])
        assets: List[Asset] = []
        for asset_data in assets_data:
            if isinstance(asset_data, dict):
                assets.append(Asset.from_dict(asset_data))
        return cls(
            name=data.get("name", "My Site"),
            pages=pages,
            css=data.get("css", ""),
            output_dir=data.get("output_dir"),
            version=data.get("version", 1),
            assets=assets,
        )

