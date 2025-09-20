"""Import pipeline for bringing external content into a project."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, Iterator, Literal, Optional
from urllib.parse import urlparse, urlunparse
from zipfile import ZipFile

from .core.models import Asset, Page, Project

try:  # pragma: no cover - optional dependency
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover - graceful fallback
    BeautifulSoup = None  # type: ignore

try:  # pragma: no cover - optional dependency
    import markdown as markdown_lib  # type: ignore
except Exception:  # pragma: no cover
    markdown_lib = None  # type: ignore

try:  # pragma: no cover - optional dependency
    import nbformat  # type: ignore
    from nbconvert import HTMLExporter  # type: ignore
except Exception:  # pragma: no cover
    nbformat = None  # type: ignore
    HTMLExporter = None  # type: ignore

try:  # pragma: no cover - optional dependency
    import mammoth  # type: ignore
except Exception:  # pragma: no cover
    mammoth = None  # type: ignore

try:  # pragma: no cover - optional dependency
    from docutils.core import publish_parts  # type: ignore
except Exception:  # pragma: no cover
    publish_parts = None  # type: ignore


SourceType = Literal["folder", "zip", "file"]


ALLOWED_EXTS_DEFAULT: set[str] = {
    ".html",
    ".htm",
    ".md",
    ".markdown",
    ".txt",
    ".ipynb",
    ".rst",
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".mp4",
    ".webm",
    ".mp3",
    ".js",
    ".docx",
}


MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MiB safety cap


@dataclass(slots=True)
class ImportOptions:
    create_new_project: bool = False
    page_filename_strategy: Literal["keep", "slugify", "prefix-collisions"] = "slugify"
    conflict_policy: Literal["overwrite", "keep-both", "skip"] = "keep-both"
    merge_css: Literal["append", "prepend", "replace"] = "append"
    rewrite_links: bool = True
    rewrite_asset_urls: bool = True
    md_flavor: Literal["gfm", "commonmark"] = "gfm"
    text_wrap_paragraphs: bool = True
    set_home_to_index_if_present: bool = True
    ignore_hidden: bool = True
    include_js_files: bool = True
    allowed_extensions: set[str] | None = None


@dataclass(slots=True)
class ImportResult:
    files_scanned: int = 0
    pages_imported: int = 0
    css_files_merged: int = 0
    assets_copied: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PageCandidate:
    source_path: Path
    rel_path: str
    ext: str
    title: str = ""
    body_html: str = ""
    new_filename: str = ""
    replace_existing: bool = False
    skip: bool = False


@dataclass(slots=True)
class AssetCandidate:
    source_path: Path
    rel_path: str
    ext: str
    kind: str
    new_name: str = ""
    content_hash: str = ""


def sniff_source_type(path: Path) -> SourceType:
    path = Path(path)
    if path.is_dir():
        return "folder"
    if path.is_file() and path.suffix.lower() == ".zip":
        return "zip"
    return "file"


def import_into_project(
    target_project: Project,
    source: str | Path,
    options: ImportOptions,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ImportResult:
    source_path = Path(source)
    result = ImportResult()
    allowed_exts = {ext.lower() for ext in (options.allowed_extensions or ALLOWED_EXTS_DEFAULT)}

    cleanup_dirs: list[Path] = []
    try:
        source_type = sniff_source_type(source_path)
        if source_type == "zip":
            extracted = _extract_zip(source_path, result)
            if extracted is None:
                return result
            cleanup_dirs.append(extracted)
            base_iter: Iterable[tuple[Path, str]] = _iter_folder(extracted, options, result)
        elif source_type == "folder":
            base_iter = _iter_folder(source_path, options, result)
        else:
            base_iter = _iter_single(source_path, result)

        files_to_process = [(path, rel) for path, rel in base_iter if path.is_file()]
        total = len(files_to_process) or 1

        page_candidates: list[PageCandidate] = []
        css_candidates: list[Path] = []
        asset_candidates: list[AssetCandidate] = []

        for index, (abs_path, rel_path) in enumerate(files_to_process, start=1):
            result.files_scanned += 1
            ext = abs_path.suffix.lower()
            if allowed_exts and ext not in allowed_exts:
                result.warnings.append(f"Skipped unsupported file: {rel_path}")
                if progress_callback:
                    progress_callback(index, total)
                continue
            if ext in {".html", ".htm", ".md", ".markdown", ".txt", ".ipynb", ".rst", ".docx", ".py"}:
                page_candidates.append(PageCandidate(source_path=abs_path, rel_path=rel_path, ext=ext))
            elif ext == ".css":
                css_candidates.append(abs_path)
            elif ext == ".js":
                if options.include_js_files:
                    asset_candidates.append(
                        AssetCandidate(source_path=abs_path, rel_path=rel_path, ext=ext, kind="js")
                    )
            elif ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico"}:
                asset_candidates.append(
                    AssetCandidate(source_path=abs_path, rel_path=rel_path, ext=ext, kind="images")
                )
            elif ext in {".woff", ".woff2", ".ttf", ".otf"}:
                asset_candidates.append(
                    AssetCandidate(source_path=abs_path, rel_path=rel_path, ext=ext, kind="fonts")
                )
            elif ext in {".mp4", ".webm", ".mp3"}:
                asset_candidates.append(
                    AssetCandidate(source_path=abs_path, rel_path=rel_path, ext=ext, kind="media")
                )
            else:
                result.warnings.append(f"Ignored file: {rel_path}")

            if progress_callback:
                progress_callback(index, total)

        asset_map = _process_assets(target_project, asset_candidates, result)

        imported_css = _merge_css_files(target_project, css_candidates, asset_map, options, result)
        if imported_css is not None:
            target_project.css = imported_css

        page_map = _process_pages(target_project, page_candidates, asset_map, options, result)

        combined_map: Dict[str, str] = {}
        if options.rewrite_asset_urls:
            combined_map.update(asset_map)
        if options.rewrite_links:
            combined_map.update(page_map)

        _finalize_pages(target_project, page_candidates, combined_map, options, result)

        if progress_callback:
            progress_callback(total, total)

        return result
    finally:
        for tmp in cleanup_dirs:
            shutil.rmtree(tmp, ignore_errors=True)


def _iter_folder(base: Path, options: ImportOptions, result: ImportResult) -> Iterator[tuple[Path, str]]:
    base = Path(base)
    for path in base.rglob("*"):
        try:
            if options.ignore_hidden and _is_hidden(path.relative_to(base)):
                continue
        except Exception:
            continue
        if path.is_symlink():
            try:
                resolved = path.resolve()
            except Exception:
                result.warnings.append(f"Skipped unreadable symlink: {path}")
                continue
            if base not in resolved.parents and resolved != base:
                result.warnings.append(f"Skipped symlink outside root: {path}")
                continue
        rel = path.relative_to(base).as_posix()
        yield path, rel


def _iter_single(path: Path, result: ImportResult) -> Iterator[tuple[Path, str]]:
    if not path.exists():
        result.errors.append(f"File not found: {path}")
        return iter(())
    return iter([(path, path.name)])


def _extract_zip(path: Path, result: ImportResult) -> Path | None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="sitebuilder_zip_"))
    try:
        with ZipFile(path) as zf:
            for member in zf.infolist():
                name = member.filename
                if member.is_dir():
                    continue
                normalized = PurePosixPath(name)
                if ".." in normalized.parts:
                    result.warnings.append(f"Skipping unsafe zip entry: {name}")
                    continue
                dest = tmp_dir.joinpath(*normalized.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, dest.open("wb") as fh:
                    shutil.copyfileobj(src, fh)
        return tmp_dir
    except Exception as exc:  # pragma: no cover - rare
        result.errors.append(f"Failed to extract zip: {exc}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None


def _process_assets(
    project: Project,
    candidates: list[AssetCandidate],
    result: ImportResult,
) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    existing_hashes: Dict[str, Asset] = {}
    for asset in project.assets:
        try:
            digest = hashlib.sha1(base64.b64decode(asset.data_base64.encode("ascii"))).hexdigest()
        except Exception:
            continue
        existing_hashes[digest] = asset

    taken_names = {asset.name for asset in project.assets}

    for candidate in candidates:
        path = candidate.source_path
        try:
            size = path.stat().st_size
        except OSError:
            result.warnings.append(f"Unable to stat asset: {candidate.rel_path}")
            continue
        if size > MAX_FILE_SIZE:
            result.warnings.append(f"Skipped large asset (>10MB): {candidate.rel_path}")
            continue

        digest = _hash_file(path)
        candidate.content_hash = digest
        if digest in existing_hashes:
            asset = existing_hashes[digest]
            export_path = _asset_export_path(asset)
            normalized = _normalize_rel(candidate.rel_path)
            mapping[normalized] = export_path
            mapping.setdefault(Path(candidate.rel_path).name, export_path)
            continue

        data_base64 = _read_file_base64(path)
        if data_base64 is None:
            result.warnings.append(f"Failed to read asset: {candidate.rel_path}")
            continue

        new_name = _unique_asset_name(path.name, taken_names)
        taken_names.add(new_name)
        asset = Asset(name=new_name, data_base64=data_base64, kind=candidate.kind)
        project.assets.append(asset)
        existing_hashes[digest] = asset
        result.assets_copied += 1
        export_path = _asset_export_path(asset)
        normalized = _normalize_rel(candidate.rel_path)
        mapping[normalized] = export_path
        name_only = Path(candidate.rel_path).name
        mapping.setdefault(name_only, export_path)

    return mapping


def _asset_export_path(asset: Asset) -> str:
    dest_subdir = {
        "images": "images",
        "fonts": "fonts",
        "media": "media",
        "js": "js",
    }.get(asset.kind, "files")
    return f"assets/{dest_subdir}/{asset.name}"


def _merge_css_files(
    project: Project,
    candidates: list[Path],
    asset_map: Dict[str, str],
    options: ImportOptions,
    result: ImportResult,
) -> str | None:
    if not candidates:
        return None
    rewritten_blocks: list[str] = []
    for css_path in candidates:
        try:
            text = css_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            result.warnings.append(f"Unable to read CSS file: {css_path}")
            continue
        if options.rewrite_asset_urls and asset_map:
            text = rewrite_css_urls(text, lambda value: _rewrite_asset(value, asset_map))
        rel = css_path.name
        rewritten_blocks.append(f"/* --- imported: {rel} --- */\n{text.strip()}\n")
        result.css_files_merged += 1

    if not rewritten_blocks:
        return None

    merged = "\n\n".join(rewritten_blocks)
    current = project.css or ""
    if options.merge_css == "replace":
        return merged
    if options.merge_css == "prepend":
        return f"{merged}\n\n{current}" if current else merged
    # append
    return f"{current}\n\n{merged}" if current else merged


def _rewrite_asset(value: str, mapping: Dict[str, str]) -> str:
    normalized = _normalize_rel(value)
    if normalized in mapping:
        return mapping[normalized]
    alt = normalized.lstrip("./")
    return mapping.get(alt, value)


def _process_pages(
    project: Project,
    candidates: list[PageCandidate],
    asset_map: Dict[str, str],
    options: ImportOptions,
    result: ImportResult,
) -> Dict[str, str]:
    if not candidates:
        return {}

    page_map: Dict[str, str] = {}
    for candidate in candidates:
        try:
            body_html, title = _convert_page(candidate, options, result)
        except Exception as exc:  # pragma: no cover - defensive
            result.warnings.append(f"Failed to convert {candidate.rel_path}: {exc}")
            candidate.skip = True
            continue
        candidate.body_html = body_html
        candidate.title = title or Path(candidate.rel_path).stem

    # Determine home page preference
    home_candidate: PageCandidate | None = None
    if options.set_home_to_index_if_present and candidates:
        for candidate in candidates:
            stem = Path(candidate.rel_path).stem.lower()
            if stem == "index":
                home_candidate = candidate
                break
        if home_candidate is None:
            home_candidate = candidates[0]

    existing_names = {page.filename for page in project.pages}
    assigned: set[str] = set()

    for candidate in candidates:
        if candidate.skip:
            continue
        base_name = _determine_base_name(candidate, options)
        if home_candidate is candidate:
            base_name = "index"
        filename = f"{base_name}.html"
        normalized_rel = _normalize_rel(candidate.rel_path)

        final_name = _resolve_page_conflict(
            filename, candidate, existing_names, assigned, options, result
        )
        if final_name is None:
            candidate.skip = True
            continue

        candidate.new_filename = final_name
        assigned.add(final_name)
        page_map[normalized_rel] = final_name
        if normalized_rel != Path(candidate.rel_path).name:
            page_map[Path(candidate.rel_path).name] = final_name

    return page_map


def _determine_base_name(candidate: PageCandidate, options: ImportOptions) -> str:
    stem = Path(candidate.rel_path).stem
    if options.page_filename_strategy == "keep":
        base = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-") or "page"
        return base.lower()
    if options.page_filename_strategy == "prefix-collisions":
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-") or "page"
        return slug.lower()
    # slugify using title
    title = candidate.title or stem
    slug = slugify_filename(title)
    return slug or "page"


def _resolve_page_conflict(
    filename: str,
    candidate: PageCandidate,
    existing: set[str],
    assigned: set[str],
    options: ImportOptions,
    result: ImportResult,
) -> str | None:
    target = filename
    if target in assigned:
        target = _increment_filename(target, assigned)

    if target in existing:
        if options.conflict_policy == "overwrite":
            candidate.replace_existing = True
            return target
        if options.conflict_policy == "skip":
            result.warnings.append(f"Skipped page (conflict): {candidate.rel_path}")
            return None
        if options.page_filename_strategy == "prefix-collisions":
            prefix = hashlib.sha1(candidate.rel_path.encode("utf-8")).hexdigest()[:6]
            target = f"{prefix}-{target}"
        target = _increment_filename(target, existing | assigned)
    return target


def _increment_filename(filename: str, taken: set[str]) -> str:
    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".html"
    counter = 2
    candidate = f"{stem}-{counter}{suffix}"
    while candidate in taken:
        counter += 1
        candidate = f"{stem}-{counter}{suffix}"
    return candidate


def _finalize_pages(
    project: Project,
    candidates: list[PageCandidate],
    mapping: Dict[str, str],
    options: ImportOptions,
    result: ImportResult,
) -> None:
    for candidate in candidates:
        if candidate.skip or not candidate.new_filename:
            continue
        html = candidate.body_html
        if mapping and (options.rewrite_links or options.rewrite_asset_urls):
            html = rewrite_html_links(html, mapping)

        page = Page(filename=candidate.new_filename, title=candidate.title, html=html)

        if candidate.replace_existing:
            for idx, existing in enumerate(project.pages):
                if existing.filename == candidate.new_filename:
                    project.pages[idx] = page
                    break
        else:
            project.pages.append(page)
        result.pages_imported += 1


def _convert_page(
    candidate: PageCandidate,
    options: ImportOptions,
    result: ImportResult,
) -> tuple[str, str]:
    path = candidate.source_path
    ext = candidate.ext
    if ext in {".html", ".htm"}:
        html = path.read_text(encoding="utf-8", errors="ignore")
        title, body = extract_html_title_and_body(html)
        return body, title
    if ext in {".md", ".markdown"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
        html = _convert_markdown(text, options, result)
        title = _first_heading(text) or Path(candidate.rel_path).stem
        return html, title
    if ext == ".txt":
        text = path.read_text(encoding="utf-8", errors="ignore")
        html = _convert_text(text, options)
        title = _first_non_empty_line(text) or Path(candidate.rel_path).stem
        return html, title
    if ext == ".ipynb":
        return _convert_ipynb(path, candidate, result)
    if ext == ".rst":
        text = path.read_text(encoding="utf-8", errors="ignore")
        html = _convert_rst(text, result)
        title = _first_heading(text) or Path(candidate.rel_path).stem
        return html, title
    if ext == ".docx":
        return _convert_docx(path, candidate, result)
    if ext == ".py":
        text = path.read_text(encoding="utf-8", errors="ignore")
        snippets = detect_likely_html_strings_in_py(text)
        if not snippets:
            raise ValueError("No embeddable HTML found")
        html = snippets[0][1]
        title, body = extract_html_title_and_body(html)
        return body, title
    raise ValueError(f"Unsupported page type: {ext}")


def _convert_markdown(text: str, options: ImportOptions, result: ImportResult) -> str:
    if markdown_lib is None:
        result.warnings.append("markdown library not available; returning plain text")
        return f"<pre>{_escape_html(text)}</pre>"
    extensions: list[str] = ["extra"]
    if options.md_flavor == "gfm":
        extra_exts: list[str] = []
        for module_name in ("pymdownx.github", "mdx_gfm"):
            try:  # pragma: no cover - optional
                importlib.import_module(module_name)
            except Exception:
                continue
            extra_exts.append(module_name)
            break
        if not extra_exts:
            result.warnings.append("GFM extensions not available; using basic markdown")
        extensions.extend(extra_exts or ["toc"])
    return markdown_lib.markdown(text, extensions=extensions)


def _convert_text(text: str, options: ImportOptions) -> str:
    if not options.text_wrap_paragraphs:
        return f"<pre>{_escape_html(text)}</pre>"
    paragraphs = [p.strip() for p in text.splitlines()]
    blocks: list[str] = []
    buf: list[str] = []
    for line in paragraphs:
        if not line:
            if buf:
                blocks.append(" ".join(buf))
                buf = []
            continue
        buf.append(line)
    if buf:
        blocks.append(" ".join(buf))
    return "\n".join(f"<p>{_escape_html(block)}</p>" for block in blocks)


def _convert_ipynb(path: Path, candidate: PageCandidate, result: ImportResult) -> tuple[str, str]:
    if nbformat is None or HTMLExporter is None:
        raise ValueError("nbconvert not available")
    notebook = nbformat.read(path, as_version=4)
    exporter = HTMLExporter()
    body, _ = exporter.from_notebook_node(notebook)
    title, content = extract_html_title_and_body(body)
    if not title:
        title = Path(candidate.rel_path).stem
    return content, title


def _convert_rst(text: str, result: ImportResult) -> str:
    if publish_parts is None:
        result.warnings.append("docutils not available; treating as plain text")
        return f"<pre>{_escape_html(text)}</pre>"
    parts = publish_parts(text, writer_name="html")
    return parts.get("body", "")


def _convert_docx(path: Path, candidate: PageCandidate, result: ImportResult) -> tuple[str, str]:
    if mammoth is None:
        raise ValueError("mammoth not available")
    with path.open("rb") as fh:
        converted = mammoth.convert_to_html(fh)
    html = converted.value
    title, body = extract_html_title_and_body(html)
    if not title:
        title = Path(candidate.rel_path).stem
    return body, title


def extract_html_title_and_body(html: str) -> tuple[str, str]:
    if BeautifulSoup is None:
        title = _simple_match(r"<title>(.*?)</title>", html)
        body = _simple_match(r"<body[^>]*>(.*)</body>", html, flags=re.DOTALL) or html
        return (title or "", body.strip())

    soup = BeautifulSoup(html, "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            title = h1.get_text(strip=True)
    if not title:
        title = ""

    body_container = soup.find("main") or soup.body or soup
    if body_container is None:
        return title, html
    if body_container.name in {"html", "body"}:
        contents = body_container.decode_contents()
    else:
        contents = body_container.decode()
    return title, contents.strip()


def rewrite_html_links(html: str, mapping: Dict[str, str]) -> str:
    if BeautifulSoup is None:
        return _rewrite_html_fallback(html, mapping)

    soup = BeautifulSoup(html, "html.parser")

    attrs_map = {
        "a": ["href"],
        "img": ["src", "srcset"],
        "link": ["href"],
        "script": ["src"],
        "video": ["src", "poster"],
        "source": ["src", "srcset"],
        "audio": ["src"],
    }

    for tag_name, attrs in attrs_map.items():
        for tag in soup.find_all(tag_name):
            for attr in attrs:
                value = tag.get(attr)
                if not value:
                    continue
                if attr == "srcset":
                    new_value = _rewrite_srcset(value, mapping)
                else:
                    new_value = _rewrite_url_value(value, mapping)
                if new_value != value:
                    tag[attr] = new_value

    return str(soup)


def _rewrite_html_fallback(html: str, mapping: Dict[str, str]) -> str:
    from html.parser import HTMLParser
    import html as html_lib

    class _Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=False)
            self.out: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
            self.out.append("<" + tag)
            self._write_attrs(tag, attrs)
            self.out.append(">")

        def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
            self.out.append("<" + tag)
            self._write_attrs(tag, attrs)
            self.out.append("/>")

        def handle_endtag(self, tag: str) -> None:
            self.out.append(f"</{tag}>")

        def handle_data(self, data: str) -> None:
            self.out.append(data)

        def handle_comment(self, data: str) -> None:
            self.out.append(f"<!--{data}-->")

        def handle_decl(self, decl: str) -> None:
            self.out.append(f"<!{decl}>")

        def handle_entityref(self, name: str) -> None:
            self.out.append(f"&{name};")

        def handle_charref(self, name: str) -> None:
            self.out.append(f"&#{name};")

        def _write_attrs(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
            for key, value in attrs:
                val = value
                if value:
                    if key == "srcset":
                        val = _rewrite_srcset(value, mapping)
                    else:
                        val = _rewrite_url_value(value, mapping)
                if val is None:
                    self.out.append(f" {key}")
                else:
                    escaped = html_lib.escape(val, quote=True)
                    self.out.append(f" {key}=\"{escaped}\"")

    parser = _Parser()
    parser.feed(html)
    parser.close()
    return "".join(parser.out)


def rewrite_css_urls(css: str, rewriter: Callable[[str], str]) -> str:
    pattern = re.compile(r"url\(\s*(['\"]?)([^'\"]+?)\1\s*\)")

    def repl(match: re.Match[str]) -> str:
        quote = match.group(1)
        value = match.group(2)
        new_value = rewriter(value)
        return f"url({quote}{new_value}{quote})"

    return pattern.sub(repl, css)


def detect_likely_html_strings_in_py(source: str) -> list[tuple[int, str]]:
    triple_re = re.compile(r"([\"\']{3})(.+?)\1", re.DOTALL)
    results: list[tuple[int, str]] = []
    for match in triple_re.finditer(source):
        snippet = match.group(2)
        score = len(re.findall(r"<([a-zA-Z][a-zA-Z0-9]*)", snippet))
        if score > 0:
            results.append((score, snippet.strip()))
    results.sort(key=lambda item: item[0], reverse=True)
    return results


def slugify_filename(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", name).strip("-").lower()
    return slug or "page"


def _rewrite_url_value(value: str, mapping: Dict[str, str]) -> str:
    value = value.strip()
    if value.startswith("data:"):
        return value
    if value.startswith("#"):
        return value
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return value
    normalized = _normalize_rel(parsed.path)
    if normalized in mapping:
        new_path = mapping[normalized]
    else:
        alt = normalized.lstrip("./")
        new_path = mapping.get(alt)
    if not new_path:
        return value
    rebuilt = urlunparse(parsed._replace(path=new_path))
    return rebuilt


def _normalize_rel(value: str) -> str:
    cleaned = value.replace("\\", "/")
    return str(PurePosixPath(cleaned))


def _hash_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_file_base64(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except Exception:
        return None
    return base64.b64encode(data).decode("ascii")


def _unique_asset_name(name: str, taken: set[str]) -> str:
    base = Path(name).stem
    suffix = Path(name).suffix
    sanitized = slugify_filename(base)
    candidate = f"{sanitized}{suffix}" if sanitized else name
    if candidate not in taken:
        return candidate
    counter = 2
    while True:
        next_name = f"{sanitized}-{counter}{suffix}"
        if next_name not in taken:
            return next_name
        counter += 1


def _is_hidden(relative: Path) -> bool:
    return any(part.startswith(".") for part in relative.parts)


def _simple_match(pattern: str, text: str, flags: int = 0) -> str | None:
    match = re.search(pattern, text, flags | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _escape_html(text: str) -> str:
    import html

    return html.escape(text, quote=False)


def _first_heading(text: str) -> str:
    heading = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    if heading:
        return heading.group(1).strip()
    return ""


def _first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:80]
    return ""


def _rewrite_srcset(value: str, mapping: Dict[str, str]) -> str:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    rewritten_parts: list[str] = []
    for part in parts:
        if " " in part:
            url_part, descriptor = part.split(" ", 1)
            new_url = _rewrite_url_value(url_part, mapping)
            rewritten_parts.append(f"{new_url} {descriptor.strip()}")
        else:
            rewritten_parts.append(_rewrite_url_value(part, mapping))
    return ", ".join(rewritten_parts)

