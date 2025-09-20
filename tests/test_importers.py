from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sitebuilder.importers import (
    extract_html_title_and_body,
    rewrite_css_urls,
    rewrite_html_links,
    slugify_filename,
    detect_likely_html_strings_in_py,
)


def test_extract_html_title_and_body_prefers_main_section() -> None:
    html = """<html><head><title>Sample</title></head><body><main><h1>Heading</h1><p>Body</p></main></body></html>"""
    title, body = extract_html_title_and_body(html)
    assert title == "Sample"
    assert "<h1>Heading</h1>" in body


def test_slugify_filename_generates_safe_names() -> None:
    assert slugify_filename("My Test Page!") == "my-test-page"
    assert slugify_filename("   ") == "page"


def test_rewrite_html_links_updates_targets() -> None:
    html = "<a href='about.html'>About</a><img src=\"images/logo.png\"/>"
    mapping = {
        "about.html": "about-us.html",
        "images/logo.png": "assets/images/logo.png",
    }
    rewritten = rewrite_html_links(html, mapping)
    assert "about-us.html" in rewritten
    assert "assets/images/logo.png" in rewritten


def test_rewrite_css_urls_invokes_rewriter() -> None:
    css = "body{background:url('img/bg.png');}"

    def rewriter(value: str) -> str:
        return "assets/images/bg.png" if value == "img/bg.png" else value

    rewritten = rewrite_css_urls(css, rewriter)
    assert "assets/images/bg.png" in rewritten


def test_detect_likely_html_strings_in_py_finds_triple_quotes() -> None:
    source = 'PAGE = """<div><p>Hello</p></div>"""\nother = """plain"""'
    matches = detect_likely_html_strings_in_py(source)
    assert matches
    score, snippet = matches[0]
    assert score > 0
    assert "<p>Hello</p>" in snippet

