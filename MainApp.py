# Restore svg_wave function above its first usage
from __future__ import annotations
from jinja2 import DictLoader, Environment, select_autoescape
import base64
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple, cast
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QObject, QThread, Qt, QUrl, pyqtSignal, QTimer, QPropertyAnimation
from PyQt6.QtGui import QCloseEvent, QDesktopServices, QPixmap
# Try multimedia; allow graceful fallback
try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

    _WEBINEER_AUDIO_OK = True
except Exception:
    _WEBINEER_AUDIO_OK = False
from PyQt6.QtWebEngineWidgets import QWebEngineView


def svg_wave(fill: str = "#e2e8f0") -> str:

    path = (
        "M0,96L60,90C120,85,240,74,360,72C480,70,600,78,720,90C840,102,960,118,1080,114C1200,110,1320,86,1380,74L1440,64L1440,120L1380,120C1320,120,1200,120,1080,120C960,120,840,120,720,120C600,120,480,120,360,120C240,120,120,120,60,120L0,120Z"
    )
    return (
        "<svg class=\"wave\" aria-hidden=\"true\" viewBox=\"0 0 1440 120\" preserveAspectRatio=\"none\">"
        f"<path fill=\"{fill}\" d=\"{path}\"></path></svg>"
    )


"""Webineer Site Builder — enhanced single-file PyQt6 app."""
# ---------------------------------------------------------------------------

openai_api_key = os.getenv("OPENAI_API_KEY")

APP_TITLE = "Webineer Site Builder"
APP_ICON_PATH = "icon.ico"
SITE_VERSION = 3
# ---- UI spacing defaults (comfortable, consistent) ----
UI_MARGIN_PX = 14        # was ~6 in several places
UI_SPACING_PX = 12
FORM_HSPACE_PX = 12
FORM_VSPACE_PX = 10


def _tune_design_layouts(root_widget: QtWidgets.QWidget) -> None:
    # Make all input fields and combos expand horizontally
    for widget_type in (QtWidgets.QLineEdit, QtWidgets.QComboBox):
        for w in root_widget.findChildren(widget_type):
            w.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                            QtWidgets.QSizePolicy.Policy.Preferred)

    # For buttons, set both expanding horizontal policy and a comfortable minimum height
    for btn in root_widget.findChildren(QtWidgets.QPushButton):
        btn.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                          QtWidgets.QSizePolicy.Policy.Preferred)
        btn.setMinimumHeight(32)

    # Make all child layouts of QGroupBox and QFormLayout expand horizontally
    for gb in root_widget.findChildren(QtWidgets.QGroupBox):
        l = gb.layout()
        if l is not None:
            l.setAlignment(Qt.AlignmentFlag.AlignTop)
            # For QHBoxLayout and QVBoxLayout, set stretch factors
            if isinstance(l, (QtWidgets.QHBoxLayout, QtWidgets.QVBoxLayout)):
                for i in range(l.count()):
                    item = l.itemAt(i)
                    if item is not None and hasattr(item, 'widget') and callable(getattr(item, 'widget', None)):
                        w = item.widget()
                        if w:
                            w.setSizePolicy(
                                QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
    # Limit the maximum width of the main Design tab content to prevent stretching in fullscreen
    if isinstance(root_widget, QtWidgets.QWidget):
        # 900px is a comfortable max width for forms
        root_widget.setMaximumWidth(900)
        # Optionally, center the content if the parent is much wider
        parent = root_widget.parentWidget()
        if parent and parent.width() > 1000:
            root_widget.setContentsMargins(
                (parent.width() - 900) // 2, UI_MARGIN_PX, (parent.width() - 900) // 2, UI_MARGIN_PX)
    """
    Loosen margins/spacing and make fields grow inside the Design tab.
    Safe: only changes layout properties; no logic or signal behaviour.
    """
    # Apply to all descendant layouts
    for lay in root_widget.findChildren((QtWidgets.QVBoxLayout,
                                         QtWidgets.QHBoxLayout,
                                         QtWidgets.QGridLayout,
                                         QtWidgets.QFormLayout)):
        # margins + generic spacing
        try:
            lay.setContentsMargins(
                UI_MARGIN_PX, UI_MARGIN_PX, UI_MARGIN_PX, UI_MARGIN_PX)
        except Exception:
            pass
        try:
            lay.setSpacing(UI_SPACING_PX)
        except Exception:
            pass

        # form-specific tweaks for better readability
        if isinstance(lay, QtWidgets.QFormLayout):
            try:
                lay.setHorizontalSpacing(FORM_HSPACE_PX)
                lay.setVerticalSpacing(FORM_VSPACE_PX)
                lay.setFieldGrowthPolicy(
                    QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
                lay.setRowWrapPolicy(
                    QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
                lay.setFormAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            except Exception:
                pass

    # Give every group a little “breathing room” below
    for gb in root_widget.findChildren(QtWidgets.QGroupBox):
        try:
            gb.setMinimumWidth(340)
            gb.setMaximumWidth(700)
            gb.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                             QtWidgets.QSizePolicy.Policy.Preferred)
            l = gb.layout()
            if l is not None:
                l.setAlignment(Qt.AlignmentFlag.AlignTop)
                # Add vertical spacing below each group
                spacer = QtWidgets.QSpacerItem(
                    0, UI_SPACING_PX // 2, QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Minimum)
                l.addItem(spacer)
        except Exception:
            pass

    # Last touch: if the Background panel has a stacked “options” area,
    # make sure it has a sensible minimum height so it doesn’t collapse.
    for stk in root_widget.findChildren(QtWidgets.QStackedWidget):
        # Only nudge if it’s currently very small
        if stk.minimumHeight() < 140:
            stk.setMinimumHeight(180)
        # Ensure it can expand to fill available space
        sp = stk.sizePolicy()
        sp.setHorizontalPolicy(QtWidgets.QSizePolicy.Policy.Expanding)
        sp.setVerticalPolicy(QtWidgets.QSizePolicy.Policy.Preferred)
        stk.setSizePolicy(sp)

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def ensure_app_icon(widget: QtWidgets.QWidget) -> None:
    """Attempt to set the app icon on a widget."""
    icon_path = Path(APP_ICON_PATH)
    if icon_path.exists():
        widget.setWindowIcon(QtGui.QIcon(str(icon_path)))


def open_url(url: str) -> None:
    """Open a URL using the desktop services with a webbrowser fallback."""
    try:
        qurl = QUrl(url)
        if qurl.isValid() and QDesktopServices.openUrl(qurl):
            return
    except Exception:
        pass
    webbrowser.open(url)


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""

    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"


def app_base_dir() -> Path:
    """Return the base directory for assets."""

    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(__file__).resolve().parent


def asset_path(*parts: str) -> Path:
    """Build an absolute path to an asset bundled with the app."""

    return app_base_dir().joinpath(*parts)


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
COVERS_DIR = PREVIEWS_DIR / "Covers"
COVERS_DIR.mkdir(parents=True, exist_ok=True)
COVER_FULL_SIZE = QtCore.QSize(1280, 800)
COVER_TILE_SIZE = QtCore.QSize(420, 260)

# Application build/version marker used to decide when to reset app data on upgrade
BUILD_VERSION = "1.0.0"
INSTALL_MARK = app_data_dir() / ".installed_version"


def clear_app_data() -> None:
    """Remove app data safely: settings, recents, caches. Never touches user projects.

    This removes only files and folders under the app data directory (LOCALAPPDATA\\Webineer).
    It intentionally does not touch user-created projects or any files outside that folder.
    """
    to_delete_files = [RECENTS_PATH, SETTINGS_PATH]
    to_delete_dirs = [PREVIEWS_DIR, COVERS_DIR, app_data_dir() / "logs"]

    for p in to_delete_files:
        try:
            if p.exists():
                p.unlink(missing_ok=True)
        except Exception:
            pass

    for d in to_delete_dirs:
        try:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass

    # Recreate empty folders expected by the app
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    COVERS_DIR.mkdir(parents=True, exist_ok=True)


def reset_if_new_install_or_version() -> None:
    """Clear app data if this is a new install or a version change.

    Compares the stored INSTALL_MARK (if present) to the current BUILD_VERSION.
    If they differ, perform a one-shot clear and write the current version.
    """
    try:
        previous = INSTALL_MARK.read_text(
            encoding="utf-8").strip() if INSTALL_MARK.exists() else ""
    except Exception:
        previous = ""
    if previous != BUILD_VERSION:
        clear_app_data()
        try:
            INSTALL_MARK.write_text(BUILD_VERSION, encoding="utf-8")
        except Exception:
            pass


SPLASH_IMAGE = Path(
    r"C:\Users\curph\OneDrive\Documents\GitHub\Webineer\Assets\SplashScreen.png")
INTRO_SOUND = Path(
    r"C:\Users\curph\OneDrive\Documents\GitHub\Webineer\Assets\intro-sound-2-269294.mp3")


class _AudioOnce:
    """Holds player references so they don't get GC'ed."""

    def __init__(self) -> None:
        self.player: Optional["QMediaPlayer"] = None
        self.output: Optional["QAudioOutput"] = None


INTRO_AUDIO = _AudioOnce()


def play_intro_sound(volume_pct: int = 70, source: Optional[Path] = None) -> None:
    """Play intro sound once if multimedia is available."""

    if not _WEBINEER_AUDIO_OK:
        return

    src = source if source and source.exists() else INTRO_SOUND
    if not src.exists():
        bundled = asset_path("Assets", "intro-sound-2-269294.mp3")
        if bundled.exists():
            src = bundled
        else:
            return

    app = QtWidgets.QApplication.instance()
    if app is None:
        return

    INTRO_AUDIO.player = QMediaPlayer()
    INTRO_AUDIO.output = QAudioOutput()
    INTRO_AUDIO.player.setAudioOutput(INTRO_AUDIO.output)
    INTRO_AUDIO.output.setVolume(max(0.0, min(1.0, volume_pct / 100.0)))
    INTRO_AUDIO.player.setSource(QtCore.QUrl.fromLocalFile(str(src)))
    INTRO_AUDIO.player.play()


def show_splash_and_fade(app: QtWidgets.QApplication) -> Optional[QtWidgets.QSplashScreen]:
    """Show splash screen if enabled and asset exists."""

    try:
        sm = SettingsManager()
        show = sm.get("show_splash", "1") == "1"
    except Exception:
        show = True

    img = SPLASH_IMAGE if SPLASH_IMAGE.exists(
    ) else asset_path("Assets", "SplashScreen.png")
    if not show or not img.exists():
        return None

    pm = QPixmap(str(img))
    if pm.isNull():
        return None

    splash = QtWidgets.QSplashScreen(pm)
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    splash.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    splash.setEnabled(False)
    splash.setWindowOpacity(0.0)
    splash.show()
    app.processEvents()

    fade_in = QPropertyAnimation(splash, b"windowOpacity")
    fade_in.setDuration(250)
    fade_in.setStartValue(0.0)
    fade_in.setEndValue(1.0)
    fade_in.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    setattr(splash, "_fade_in_anim", fade_in)

    splash.showMessage(
        "Starting Webineer…",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QtGui.QColor("white"),
    )
    app.processEvents()
    return splash


def hide_splash_with_fade(
    splash: Optional[QtWidgets.QSplashScreen],
    target: Optional[QtWidgets.QWidget] = None,
) -> None:
    """Fade out and close the splash screen."""

    if splash is None:
        return

    anim = QPropertyAnimation(splash, b"windowOpacity")
    anim.setDuration(180)
    anim.setStartValue(splash.windowOpacity())
    anim.setEndValue(0.0)

    def _finish() -> None:
        try:
            if target is not None:
                splash.finish(target)
            else:
                splash.close()
        except Exception:
            try:
                splash.close()
            except Exception:
                pass

    anim.finished.connect(_finish)
    anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    setattr(splash, "_fade_out_anim", anim)


class SettingsManager:
    """Very small settings helper storing JSON data."""

    def __init__(self) -> None:
        self._settings: Dict[str, str] = {}
        self.load()

    def load(self) -> None:
        changed = False
        if SETTINGS_PATH.exists():
            try:
                self._settings = json.loads(
                    SETTINGS_PATH.read_text(
                        encoding="utf-8"))
            except Exception:
                self._settings = {}
        else:
            self._settings = {}

        if self._settings.get("show_splash", "") == "":
            self._settings["show_splash"] = "1"
            changed = True
        if self._settings.get("play_intro_sound", "") == "":
            self._settings["play_intro_sound"] = "1"
            changed = True
        if self._settings.get("intro_volume", "") == "":
            self._settings["intro_volume"] = "70"
            changed = True

        if changed:
            try:
                self.save()
            except Exception:
                pass

    def save(self) -> None:
        SETTINGS_PATH.write_text(
            json.dumps(
                self._settings,
                indent=2),
            encoding="utf-8")

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
        """Return a dictionary representation of the AssetImage."""
        return {
            "name": self.name,
            "data_base64": self.data_base64,
            "width": self.width,
            "height": self.height,
            "mime": self.mime,
        }

    @staticmethod
    def from_dict(data: Dict[str, object]) -> "AssetImage":
        def safe_int(val, default=0):
            try:
                return int(val)
            except (TypeError, ValueError):
                return default
        return AssetImage(
            name=str(data.get("name", "")),
            data_base64=str(data.get("data_base64", "")),
            width=safe_int(data.get("width", 0)),
            height=safe_int(data.get("height", 0)),
            mime=str(data.get("mime", "")),
        )


@dataclass
class ExternalAsset:
    kind: str
    mode: str
    href: str
    sri: Optional[str] = None
    original_url: Optional[str] = None
    data_base64: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "kind": self.kind,
            "mode": self.mode,
            "href": self.href,
        }
        if self.sri:
            payload["sri"] = self.sri
        if self.original_url:
            payload["original_url"] = self.original_url
        if self.data_base64:
            payload["data_base64"] = self.data_base64
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "ExternalAsset":
        href_raw = data.get("href", "")
        href = str(href_raw) if isinstance(href_raw, (str, bytes)) else ""
        sri_val = data.get("sri")
        original = data.get("original_url")
        encoded = data.get("data_base64")
        return cls(
            kind=str(data.get("kind", "css")),
            mode=str(data.get("mode", "cdn")),
            href=href,
            sri=str(sri_val) if isinstance(sri_val, str) and sri_val else None,
            original_url=str(original) if isinstance(
                original, str) and original else None,
            data_base64=str(encoded) if isinstance(
                encoded, str) and encoded else None,
        )


@dataclass
class BackgroundSpec:
    scope: str
    kind: str
    value: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "scope": self.scope,
            "kind": self.kind,
            "value": dict(
                self.value)}

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "BackgroundSpec":
        raw_value = data.get("value")
        value: Dict[str, str]
        if isinstance(raw_value, dict):
            value = {str(k): str(v) for k, v in raw_value.items()}
        else:
            value = {}
        return cls(
            scope=str(
                data.get(
                    "scope", "site")), kind=str(
                data.get(
                    "kind", "solid")), value=value)


DEFAULT_PALETTE = {
    "primary": "#2563eb",
    "surface": "#f8fafc",
    "text": "#0f172a",
}

DEFAULT_FONTS = {
    "heading": "'Poppins', 'Segoe UI', sans-serif",
    "body": "'Inter', 'Segoe UI', sans-serif",
}

DEFAULT_GRADIENT = {"from": "#3b82f6", "to": "#60a5fa", "angle": "135deg"}

SHADOW_LEVELS = ["none", "sm", "md", "lg"]
MOTION_EFFECTS = ["none", "fade", "zoom", "blur"]
MOTION_EASINGS: Dict[str, str] = {
    "Gentle ease": "cubic-bezier(.2,.65,.2,1)",
    "Smooth ease-out": "cubic-bezier(.22,.7,.36,1)",
    "Playful bounce": "cubic-bezier(.68,-0.55,.27,1.55)",
    "Linear": "linear",
    "Ease-in-out": "ease-in-out",
}
GRADIENT_ANGLES = ["45deg", "90deg", "135deg", "180deg"]
MOTION_PREF_OPTIONS: Dict[str, str] = {
    "Respect visitor setting": "respect",
    "Force on": "force_on",
    "Force off": "force_off",
}


@dataclass
class Project:
    name: str = "My Site"
    pages: List[Page] = field(default_factory=list)
    css: str = ""
    palette: Dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_PALETTE))
    fonts: Dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_FONTS))
    images: List[AssetImage] = field(default_factory=list)
    external: List[ExternalAsset] = field(default_factory=list)
    backgrounds: List[BackgroundSpec] = field(default_factory=list)
    template_key: str = "starter"
    theme_preset: str = "Calm Sky"
    use_main_js: bool = False
    output_dir: Optional[str] = None
    version: int = SITE_VERSION
    use_scroll_animations: bool = False
    gradients: Dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_GRADIENT))
    radius_scale: float = 1.0
    shadow_level: str = "md"
    motion_pref: str = "respect"
    motion_default_effect: str = "none"
    motion_default_easing: str = "cubic-bezier(.2,.65,.2,1)"
    motion_default_duration: int = 600
    motion_default_delay: int = 0
    cover_path: Optional[str] = None
    cover_updated_utc: Optional[str] = None
    cover_asset_name: Optional[str] = None
    cover_tile_path: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "pages": [asdict(p) for p in self.pages],
            "css": self.css,
            "palette": self.palette,
            "fonts": self.fonts,
            "images": [img.to_dict() for img in self.images],
            "external": [asset.to_dict() for asset in self.external],
            "backgrounds": [bg.to_dict() for bg in self.backgrounds],
            "template_key": self.template_key,
            "theme_preset": self.theme_preset,
            "use_main_js": self.use_main_js,
            "output_dir": self.output_dir,
            "version": self.version,
            "use_scroll_animations": self.use_scroll_animations,
            "gradients": dict(self.gradients),
            "radius_scale": self.radius_scale,
            "shadow_level": self.shadow_level,
            "motion_pref": self.motion_pref,
            "motion_default_effect": self.motion_default_effect,
            "motion_default_easing": self.motion_default_easing,
            "motion_default_duration": self.motion_default_duration,
            "motion_default_delay": self.motion_default_delay,
            "cover_path": self.cover_path,
            "cover_updated_utc": self.cover_updated_utc,
            "cover_asset_name": self.cover_asset_name,
            "cover_tile_path": self.cover_tile_path,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Project":
        def safe_int(val, default=1):
            try:
                return int(val)
            except (TypeError, ValueError):
                return default

        def safe_float(val, default=1.0):
            try:
                return float(val)
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
        images = [
            AssetImage.from_dict(img) for img in safe_list(
                data.get(
                    "images",
                    [])) if isinstance(
                img,
                dict)]
        external_items: List[ExternalAsset] = []
        for entry in safe_list(data.get("external", [])):
            if isinstance(entry, dict):
                external_items.append(ExternalAsset.from_dict(entry))
        backgrounds_data = data.get("backgrounds", [])
        background_items: List[BackgroundSpec] = []
        if isinstance(backgrounds_data, list):
            for entry in backgrounds_data:
                if isinstance(entry, dict):
                    background_items.append(
                        BackgroundSpec.from_dict(entry))
        elif isinstance(backgrounds_data, dict):
            for key, entry in backgrounds_data.items():
                if isinstance(entry, dict):
                    value = dict(entry)
                    value.setdefault("page", str(key))
                    background_items.append(
                        BackgroundSpec(
                            scope=str(entry.get("scope", "page")),
                            kind=str(entry.get("kind", "solid")),
                            value={str(k): str(v)
                                   for k, v in value.items()},
                        )
                    )
        palette = safe_dict(
            data.get(
                "palette",
                DEFAULT_PALETTE),
            DEFAULT_PALETTE)
        fonts = safe_dict(data.get("fonts", DEFAULT_FONTS), DEFAULT_FONTS)
        output_dir = data.get("output_dir")
        if output_dir is not None and not isinstance(output_dir, str):
            output_dir = str(output_dir)
        gradients_raw = data.get("gradients")
        gradients = dict(DEFAULT_GRADIENT)
        if isinstance(gradients_raw, dict):
            gradients = {
                "from": str(gradients_raw.get("from", gradients["from"])),
                "to": str(gradients_raw.get("to", gradients["to"])),
                "angle": str(gradients_raw.get("angle", gradients["angle"])),
            }
        radius_scale = safe_float(data.get("radius_scale", 1.0), 1.0)
        if radius_scale <= 0:
            radius_scale = 1.0
        shadow_level = str(data.get("shadow_level", "md"))
        if shadow_level not in {"none", "sm", "md", "lg"}:
            shadow_level = "md"
        motion_pref = str(data.get("motion_pref", "respect"))
        if motion_pref not in {"respect", "force_on", "force_off"}:
            motion_pref = "respect"
        motion_default_effect = str(
            data.get("motion_default_effect", "none"))
        if motion_default_effect not in {"none", "fade", "zoom", "blur"}:
            motion_default_effect = "none"
        motion_default_easing = str(
            data.get("motion_default_easing", "cubic-bezier(.2,.65,.2,1)")
        )
        motion_default_duration = safe_int(
            data.get("motion_default_duration", 600), 600)
        if motion_default_duration < 0:
            motion_default_duration = 600
        motion_default_delay = safe_int(
            data.get("motion_default_delay", 0), 0)
        if motion_default_delay < 0:
            motion_default_delay = 0
        cover_path_raw = data.get("cover_path")
        cover_path = str(cover_path_raw) if isinstance(
            cover_path_raw, str) or cover_path_raw is None else str(cover_path_raw)
        cover_updated = data.get("cover_updated_utc")
        cover_asset_name = data.get("cover_asset_name")
        cover_tile_raw = data.get("cover_tile_path")
        cover_tile = (
            str(cover_tile_raw)
            if isinstance(cover_tile_raw, str) or cover_tile_raw is None
            else str(cover_tile_raw)
        )
        return cls(
            name=str(data.get("name", "My Site")),
            pages=pages,
            css=str(data.get("css", "")),
            palette=palette,
            fonts=fonts,
            images=images,
            external=external_items,
            backgrounds=background_items,
            template_key=str(data.get("template_key", "starter")),
            theme_preset=str(data.get("theme_preset", "Calm Sky")),
            use_main_js=bool(data.get("use_main_js", False)),
            output_dir=output_dir,
            version=version,
            use_scroll_animations=bool(
                data.get("use_scroll_animations", False)),
            gradients=gradients,
            radius_scale=radius_scale,
            shadow_level=shadow_level,
            motion_pref=motion_pref,
            motion_default_effect=motion_default_effect,
            motion_default_easing=motion_default_easing,
            motion_default_duration=motion_default_duration,
            motion_default_delay=motion_default_delay,
            cover_path=cover_path,
            cover_updated_utc=str(
                cover_updated) if cover_updated else None,
            cover_asset_name=str(
                cover_asset_name) if cover_asset_name else None,
            cover_tile_path=cover_tile,
        )

# ---------------------------------------------------------------------------
# Templates & presets
# ---------------------------------------------------------------------------


THEME_PRESETS: Dict[str, Dict[str, str]] = {
    "Calm Sky": {"primary": "#2563eb", "surface": "#f8fafc", "text": "#0f172a"},
    "Sunset": {"primary": "#f97316", "surface": "#fff7ed", "text": "#431407"},
    "Forest": {"primary": "#15803d", "surface": "#f0fdf4", "text": "#052e16"},
    "Midnight": {"primary": "#6366f1", "surface": "#111827", "text": "#f9fafb"},
    "Rose": {"primary": "#ec4899", "surface": "#fdf2f8", "text": "#831843"},
    "Glassmorphism": {"primary": "#60a5fa", "surface": "#0f172a", "text": "#f8fafc"},
    "Neumorphism": {"primary": "#4f46e5", "surface": "#e2e8f0", "text": "#1f2937"},
    "Warm Sunset": {"primary": "#fb7185", "surface": "#fff1e6", "text": "#7c2d12"},
    "Mint Fresh": {"primary": "#10b981", "surface": "#ecfdf5", "text": "#064e3b"},
}

THEME_STYLE_PRESETS: Dict[str, Dict[str, object]] = {
    "Glassmorphism": {
        "fonts": {"heading": "'Poppins', 'Segoe UI', sans-serif", "body": "'Inter', 'Segoe UI', sans-serif"},
        "gradients": {"from": "#60a5fa", "to": "#a855f7", "angle": "120deg"},
        "radius_scale": 1.2,
        "shadow_level": "lg",
        "extra_css": """/* theme: Glassmorphism */
body { background: radial-gradient(circle at 15% 20%, rgba(96,165,250,0.25), transparent 55%), #0f172a; color: #e2e8f0; }
.card { background: rgba(15,23,42,0.55); border: 1px solid rgba(148,163,184,0.35); backdrop-filter: blur(18px); color: #f8fafc; }
.btn-primary { box-shadow: 0 24px 48px rgba(37,99,235,0.35); }
""",
    },
    "Neumorphism": {
        "fonts": {"heading": "'Nunito', 'Segoe UI', sans-serif", "body": "'Nunito', 'Segoe UI', sans-serif"},
        "gradients": {"from": "#dbeafe", "to": "#e2e8f0", "angle": "135deg"},
        "radius_scale": 1.1,
        "shadow_level": "sm",
        "extra_css": """/* theme: Neumorphism */
body { background: #e2e8f0; }
.card { border: none; background: #e2e8f0; box-shadow: 12px 12px 30px rgba(148,163,184,0.35), -12px -12px 30px rgba(255,255,255,0.9); }
.btn { box-shadow: inset 4px 4px 12px rgba(148,163,184,0.35), inset -4px -4px 12px rgba(255,255,255,0.85); }
""",
    },
    "Warm Sunset": {
        "fonts": {"heading": "'Source Sans Pro', 'Helvetica Neue', Arial, sans-serif", "body": "'Inter', 'Segoe UI', sans-serif"},
        "gradients": {"from": "#fb7185", "to": "#f97316", "angle": "125deg"},
        "radius_scale": 1.0,
        "shadow_level": "md",
        "extra_css": """/* theme: Warm Sunset */
.hero { background: linear-gradient(135deg, rgba(251,113,133,0.92), rgba(249,115,22,0.85)); color: #fff; padding: calc(var(--space-7) * 1.15) 0; }
.section-alt { background: rgba(251,146,60,0.12); }
.btn-primary { background: linear-gradient(135deg, #fb7185, #f97316); }
""",
    },
    "Mint Fresh": {
        "fonts": {"heading": "'Fira Sans', 'Segoe UI', sans-serif", "body": "'Inter', 'Segoe UI', sans-serif"},
        "gradients": {"from": "#34d399", "to": "#22d3ee", "angle": "135deg"},
        "radius_scale": 1.05,
        "shadow_level": "md",
        "extra_css": """/* theme: Mint Fresh */
.section-alt { background: rgba(45,212,191,0.12); }
.card { border: 1px solid rgba(16,185,129,0.25); }
.btn-primary { box-shadow: 0 24px 50px rgba(16,185,129,0.35); }
""",
    },
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

CSS_HELPERS_SENTINEL = "/* === WEBINEER CSS HELPERS (DO NOT DUPLICATE) === */"
ANIM_HELPERS_SENTINEL = "/* === WEBINEER ANIMATION HELPERS === */"
GRADIENT_HELPERS_SENTINEL = "/* === WEBINEER GRADIENT HELPERS === */"
BG_HELPERS_SENTINEL = "/* === WEBINEER BG HELPERS (DO NOT DUPLICATE) === */"
TEMPLATE_EXTRA_SENTINEL = "/* === WEBINEER TEMPLATE EXTRA CSS === */"
BACKGROUND_BLOCK_START = "/* === WEBINEER BACKGROUNDS START === */"
BACKGROUND_BLOCK_END = "/* === WEBINEER BACKGROUNDS END === */"
BACKGROUND_COMMENT_PREFIX = "/* Webineer Background"

CSS_HELPERS_BLOCK = """:root {
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
  --shadow-none: none;
  --shadow-sm: 0 16px 32px rgba(15, 23, 42, 0.08);
  --shadow-md: 0 30px 60px rgba(15, 23, 42, 0.16);
  --shadow-lg: 0 40px 80px rgba(15, 23, 42, 0.22);
  --max-width: 1100px;
}
body {
  background: var(--color-surface, #f8fafc);
  color: var(--color-text, #0f172a);
}
.container {
  max-width: var(--max-width);
  margin: 0 auto;
  padding: var(--space-6) var(--space-4);
}
.section {
  padding: var(--space-7) 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.section-alt {
  background: rgba(148, 163, 184, 0.1);
  padding: var(--space-7) 0;
}
.stack {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.stack-inline {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: center;
}
.center {
  text-align: center;
  align-items: center;
}
.grid {
  display: grid;
  gap: var(--space-4);
}
.split-2 {
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}
.split-3 {
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}
.hero {
  padding: var(--space-7) 0;
  display: grid;
  gap: var(--space-5);
  justify-items: start;
}
.hero-split {
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  align-items: center;
}
.hero .lead {
  font-size: 1.2rem;
  max-width: 540px;
}
.hero .btn {
  padding: 0.85rem 1.35rem;
  font-weight: 600;
}
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.75rem 1.25rem;
  border-radius: 999px;
  border: none;
  cursor: pointer;
  font-weight: 600;
  text-decoration: none;
}
.btn-primary {
  background: var(--color-primary, #2563eb);
  color: white;
  box-shadow: var(--shadow-sm);
}
.btn-outline {
  border: 2px solid rgba(37, 99, 235, 0.35);
  color: var(--color-primary, #2563eb);
  background: transparent;
}
.btn-ghost {
  background: transparent;
  color: var(--color-primary, #2563eb);
}
.btn-soft {
  background: rgba(37, 99, 235, 0.12);
  color: var(--color-primary, #2563eb);
}
.btn-pill {
  border-radius: 999px;
}
.btn-gradient {
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  color: white;
  box-shadow: var(--shadow-lg);
}
.hero figure {
  margin: 0;
}
.card {
  padding: var(--space-5);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  background: white;
}
.card.media {
  padding: 0;
  overflow: hidden;
}
.card.media img {
  width: 100%;
  height: auto;
  display: block;
}
.lead {
  font-size: 1.125rem;
  color: rgba(15, 23, 42, 0.85);
}
.eyebrow {
  font-size: 0.85rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(37, 99, 235, 0.9);
}
.list-check {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 0.35rem;
}
.list-check li::before {
  content: "✔";
  margin-right: .5rem;
}
.inline-tags {
  display: inline-flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.inline-tags span {
  padding: 0.25rem 0.75rem;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.14);
}
.gallery {
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}
.gallery figure {
  background: white;
  border-radius: var(--radius-sm);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.testimonials {
  display: grid;
  gap: var(--space-4);
}
.testimonials blockquote {
  font-size: 1.1rem;
  line-height: 1.6;
  margin: 0;
}
.steps {
  display: grid;
  gap: var(--space-4);
}
.steps article {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-4);
  border-radius: var(--radius-sm);
  background: rgba(37, 99, 235, 0.06);
}
.faq {
  border-radius: var(--radius-sm);
  border: 1px solid rgba(148,163,184,0.35);
  background: white;
  padding: var(--space-3);
}
.faq summary {
  cursor: pointer;
  font-weight: 600;
}
.max-w-sm { max-width: 420px; margin: 0 auto; }
.max-w-md { max-width: 640px; margin: 0 auto; }
.max-w-lg { max-width: 960px; margin: 0 auto; }
.main-container { max-width: var(--max-width); margin: 0 auto; padding: 0 var(--space-4); }
.form input, .form textarea {
  padding: 0.65rem 0.85rem;
  border-radius: var(--radius-sm);
  border: 1px solid rgba(148,163,184,0.5);
}
.alert-info { background: rgba(37, 99, 235, 0.12); border-color: rgba(37, 99, 235, 0.3); }
.alert-success { background: rgba(16, 185, 129, 0.15); border-color: rgba(16, 185, 129, 0.32); }
.alert-warning { background: rgba(234, 179, 8, 0.2); border-color: rgba(234, 179, 8, 0.42); }
.alert-danger { background: rgba(239, 68, 68, 0.16); border-color: rgba(239, 68, 68, 0.36); }
.muted { color: rgba(15, 23, 42, 0.68); }
.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.25rem 0.75rem;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.12);
  font-weight: 600;
}
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
  font-size: 0.95rem;
}
.breadcrumb a {
  color: inherit;
  text-decoration: none;
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
}
.breadcrumb span[aria-current="page"] {
  font-weight: 600;
}
.pill-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.pill-nav a {
  text-decoration: none;
  padding: 0.5rem 0.85rem;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.14);
  color: inherit;
}
.pill-nav a.is-active {
  background: var(--color-primary, #2563eb);
  color: #fff;
}
.shimmer {
  position: relative;
  overflow: hidden;
  background: rgba(148, 163, 184, 0.18);
}
.shimmer::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.45), transparent);
  transform: translateX(-100%);
  animation: shimmer-move 1.4s infinite;
}
@keyframes shimmer-move {
  100% { transform: translateX(100%); }
}
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
"""

BG_HELPERS_BLOCK = """{BG_HELPERS_SENTINEL}
.bg-cover   {{ background-repeat:no-repeat; background-position:center; background-size:cover; }}
.bg-fixed   {{ background-attachment: fixed; }}
.bg-soft    {{ background: color-mix(in oklab, var(--color-primary) 6%, var(--color-surface)); }}
.glass      {{ backdrop-filter: blur(10px) saturate(120%); background: rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.18); border-radius: .8rem; }}
.tile-grid  {{ display:grid; gap:1rem; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); }}
.tile       {{ border-radius:.8rem; padding:1rem; background: rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.1); box-shadow: 0 10px 30px rgba(0,0,0,.18); }}
.neon-btn   {{ color:#fff; text-shadow:0 0 8px var(--color-primary); box-shadow:0 0 12px var(--color-primary) inset, 0 0 16px var(--color-primary); }}
"""


def gradient_helpers_block(grad: Dict[str, str]) -> str:
    """Return the gradient helper CSS block."""

    return f"""{GRADIENT_HELPERS_SENTINEL}
:root {{
  --gradient-from: {grad.get('from', '#3b82f6')};
  --gradient-to: {grad.get('to', '#60a5fa')};
  --gradient-angle: {grad.get('angle', '135deg')};
  --gradient-main: linear-gradient(var(--gradient-angle), var(--gradient-from), var(--gradient-to));
}}
.bg-gradient {{ background: var(--gradient-main); }}
.text-on-gradient {{ color: white; }}
.card-gradient {{ background: var(--gradient-main); color: white; }}
.btn-gradient {{ background: var(--gradient-main); border-color: transparent; color: white; }}
"""


def animation_helpers_block(motion_pref: str = "respect") -> str:
    """Return the animation helper CSS block."""

    reduce_block = (
        "@media (prefers-reduced-motion: reduce) {\n  .anim, [data-animate] { animation: none !important; transition: none !important; }\n}\n"
        if motion_pref != "force_on"
        else ""
    )
    force_off_block = (
        ".anim, [data-animate] { animation: none !important; transition: none !important; }\n"
        if motion_pref == "force_off"
        else ""
    )
    return (
        f"""{ANIM_HELPERS_SENTINEL}
:root {{
  --anim-duration: .6s;
  --anim-delay: 0s;
  --anim-ease: cubic-bezier(.2,.65,.2,1);
}}
{reduce_block}{force_off_block}/* Keyframes */
@keyframes fadeInUp {{ from {{ opacity:0; transform: translateY(10px); }} to {{ opacity:1; transform:none; }} }}
@keyframes zoomIn   {{ from {{ opacity:0; transform: scale(.96); }} to {{ opacity:1; transform:scale(1); }} }}
@keyframes blurIn   {{ from {{ opacity:0; filter: blur(8px); }} to {{ opacity:1; filter:none; }} }}
@keyframes float    {{ 0% {{ transform: translateY(0); }} 50% {{ transform: translateY(-6px); }} 100% {{ transform: translateY(0); }} }}
/* Utilities */
.anim {{
  animation-duration: var(--anim-duration, .6s);
  animation-delay: var(--anim-delay, 0s);
  animation-timing-function: var(--anim-ease, cubic-bezier(.2,.65,.2,1));
  animation-fill-mode: both;
}}
.anim-fade {{ animation-name: fadeInUp; }}
.anim-zoom {{ animation-name: zoomIn; }}
.anim-blur {{ animation-name: blurIn; }}
.anim-float {{ animation: float 3.5s ease-in-out infinite; }}
/* Attribute-driven (with small JS): [data-animate="fade|zoom|blur"] */
[data-animate] {{
  opacity: 0;
  --anim-duration: var(--anim-duration, .6s);
  --anim-delay: var(--anim-delay, 0s);
  --anim-ease: var(--anim-ease, cubic-bezier(.2,.65,.2,1));
}}
[data-animate].is-in {{
  opacity: 1;
  animation-duration: var(--anim-duration, .6s);
  animation-delay: var(--anim-delay, 0s);
  animation-timing-function: var(--anim-ease, cubic-bezier(.2,.65,.2,1));
  animation-fill-mode: both;
}}
[data-animate="fade"].is-in {{ animation-name: fadeInUp; }}
[data-animate="zoom"].is-in {{ animation-name: zoomIn; }}
[data-animate="blur"].is-in {{ animation-name: blurIn; }}
.anim-fade-up   {{ opacity:0; transform: translateY(12px); transition:opacity .6s ease, transform .6s ease; }}
.anim-fade-in   {{ opacity:0; transition:opacity .6s ease; }}
.anim-zoom-in   {{ opacity:0; transform: scale(.98); transition:opacity .6s ease, transform .6s ease; }}
.is-visible.anim-fade-up {{ opacity:1; transform:none; }}
.is-visible.anim-fade-in {{ opacity:1; }}
.is-visible.anim-zoom-in {{ opacity:1; transform:scale(1); }}
"""
    )


CSS_SENTINELS = (
    CSS_HELPERS_SENTINEL,
    BG_HELPERS_SENTINEL,
    GRADIENT_HELPERS_SENTINEL,
    ANIM_HELPERS_SENTINEL,
    TEMPLATE_EXTRA_SENTINEL,
)


def ensure_block(css: str, sentinel: str, block: str) -> str:
    """Ensure a sentinel block exists in the CSS, appending if necessary."""

    if sentinel in css:
        return css
    base = css.rstrip()
    block_content = block.strip()
    if block_content.startswith(sentinel):
        block_content = block_content[len(sentinel):].lstrip("\n")
    addition = f"{sentinel}\n{block_content}\n" if block_content else f"{sentinel}\n"
    if base:
        return base + "\n\n" + addition
    return addition


def extract_css_block(css: str, sentinel: str) -> str | None:
    """Return the CSS content for a sentinel without the sentinel line."""

    if sentinel not in css:
        return None
    tail = css.split(sentinel, 1)[1].lstrip('\n')
    end = len(tail)
    for other in CSS_SENTINELS:
        if other == sentinel:
            continue
        pos = tail.find(other)
        if pos != -1 and pos < end:
            end = pos
    block = tail[:end].strip()
    return block or None


THEME_EXTRA_PREFIX = "/* theme:"


def strip_theme_extras(block: Optional[str]) -> str:
    """Remove theme extra CSS markers from a TEMPLATE_EXTRA block."""

    if not block:
        return ""
    pattern = re.compile(r"/\* theme:.*?\*/.*?(?=(/\* theme:)|$)", re.S)
    cleaned = re.sub(pattern, "", block)
    return cleaned.strip()


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
  const reveal = (root = document) => {
    const els = root.querySelectorAll('.anim-fade-up, .anim-fade-in, .anim-zoom-in');
    if (!('IntersectionObserver' in window) || !els.length) {
      els.forEach((el) => el.classList.add('is-visible'));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
        }
      });
    }, { threshold: .12 });
    els.forEach((el) => io.observe(el));
  };
  reveal(document);
})();
"""

SCROLL_JS_SNIPPET = """// Minimal intersection observer for scroll animations
(() => {
  const prefersReduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (prefersReduce) return;
  const els = document.querySelectorAll('[data-animate]');
  const io = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-in');
        io.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  els.forEach((el) => io.observe(el));
})();
"""


@dataclass
class Snippet:
    label: str
    html: str
    requires_js: bool = False


LAYOUT_SNIPPETS: Dict[str, Snippet] = {
    "hero-spotlight": Snippet(
        "Hero spotlight",
        """
<section class="hero">
  <h1>Headline that inspires confidence</h1>
  <p class="lead">Explain what you offer and the value in a friendly tone.</p>
  <div class="stack-inline">
    <a class="btn btn-primary" href="#">Primary call to action</a>
    <a class="btn btn-ghost" href="#">Secondary link</a>
  </div>
</section>
""",
    ),
    "hero-split": Snippet(
        "Hero split",
        """
<section class="hero hero-split">
  <div class="stack">
    <p class="eyebrow">New announcement</p>
    <h1>Pair a bold message with visuals</h1>
    <p class="lead">Balance storytelling and imagery to quickly explain what you do.</p>
    <a class="btn btn-primary" href="#">See how it works</a>
  </div>
  <figure class="card media">
    <img src="assets/images/placeholder-wide.png" alt="Product screenshot">
  </figure>
</section>
""",
    ),
    "sticky-header": Snippet(
        "Sticky header",
        """
<header class="site-header">
  <div class="main-container stack-inline">
    <a class="site-logo" href="index.html">Brand</a>
    <button class="btn btn-ghost" data-toggle="mobile-nav" aria-expanded="false" aria-controls="primary-menu">Menu</button>
    <nav class="site-nav" data-mobile-nav id="primary-menu">
      <ul class="stack-inline">
        <li><a href="index.html">Home</a></li>
        <li><a href="#services">Services</a></li>
        <li><a href="#about">About</a></li>
        <li><a class="btn btn-primary btn-pill" href="#contact">Contact</a></li>
      </ul>
    </nav>
  </div>
</header>
""",
        requires_js=True,
    ),
    "tile-dashboard": Snippet(
        "Tile dashboard",
        """
<section class="section">
  <div class="tile-grid">
    <a class="tile" href="#"><h3>Docs</h3><p class="muted">Guides & tips</p></a>
    <a class="tile" href="#"><h3>Blog</h3><p class="muted">Latest updates</p></a>
    <a class="tile" href="#"><h3>Gallery</h3><p class="muted">Screens & shots</p></a>
    <a class="tile" href="#"><h3>Contact</h3><p class="muted">Get in touch</p></a>
  </div>
</section>
""",
    ),
    "sidebar-layout": Snippet(
        "Sidebar layout",
        """
<section class="section">
  <div class="grid" style="grid-template-columns: minmax(220px, 260px) 1fr; gap: var(--space-5);">
    <aside class="card stack" aria-label="Secondary navigation">
      <h3>Quick links</h3>
      <ul class="stack" style="list-style:none;padding:0;margin:0;">
        <li><a href="#overview">Overview</a></li>
        <li><a href="#features">Features</a></li>
        <li><a href="#pricing">Pricing</a></li>
        <li><a href="#faq">FAQ</a></li>
      </ul>
    </aside>
    <article class="stack">
      <h2 id="overview">Content area</h2>
      <p>Use this split layout to mix navigation with detail content.</p>
      <div class="card">
        <h3>Highlight</h3>
        <p>Share updates, announcements, or notes that need extra attention.</p>
      </div>
    </article>
  </div>
</section>
""",
    ),
    "footer": Snippet(
        "Footer",
        """
<footer class="section">
  <div class="grid split-3">
    <div>
      <h2>About</h2>
      <p>Brief description about your organization or project.</p>
    </div>
    <div>
      <h2>Links</h2>
      <ul class="stack" style="list-style:none;padding:0;">
        <li><a href="#">Pricing</a></li>
        <li><a href="#">Support</a></li>
        <li><a href="#">Blog</a></li>
      </ul>
    </div>
    <div>
      <h2>Stay in touch</h2>
      <p>Share your email to receive updates.</p>
      <form class="stack-inline">
        <label class="visually-hidden" for="footer-email">Email</label>
        <input id="footer-email" class="input" type="email" placeholder="email@domain.com">
        <button class="btn btn-primary" type="submit">Notify me</button>
      </form>
    </div>
  </div>
  <p>© {{site_name}} — Built with love.</p>
</footer>
""",
    ),
}


SECTIONS_SNIPPETS: Dict[str, Snippet] = {
    "pricing": Snippet(
        "Pricing",
        """
<section class="section">
  <h2>Pricing plans</h2>
  <p class="muted">Choose a package that fits where you are today.</p>
  <div class="grid split-3">
    <article class="card">
      <h3 class="eyebrow">Starter</h3>
      <p class="lead">$9<span aria-hidden="true">/mo</span></p>
      <ul class="list-check">
        <li>Launch-ready templates</li>
        <li>Email support</li>
        <li>Up to 3 projects</li>
      </ul>
      <a class="btn btn-outline" href="#">Get started</a>
    </article>
    <article class="card">
      <h3 class="eyebrow">Growth</h3>
      <p class="lead">$29<span aria-hidden="true">/mo</span></p>
      <ul class="list-check">
        <li>Unlimited projects</li>
        <li>Advanced analytics</li>
        <li>Priority chat</li>
      </ul>
      <a class="btn btn-primary" href="#">Most popular</a>
    </article>
    <article class="card">
      <h3 class="eyebrow">Scale</h3>
      <p class="lead">Talk to us</p>
      <ul class="list-check">
        <li>Dedicated partner</li>
        <li>Custom integrations</li>
        <li>Launch support</li>
      </ul>
      <a class="btn btn-outline" href="#">Book a call</a>
    </article>
  </div>
</section>
""",
    ),
    "testimonials": Snippet(
        "Testimonials",
        """
<section class="section section-alt">
  <h2>Testimonials</h2>
  <div class="testimonials">
    <figure class="card">
      <blockquote>
        <p>“This changed the way we work together.”</p>
      </blockquote>
      <figcaption>Jordan, Customer Success Lead</figcaption>
    </figure>
    <figure class="card">
      <blockquote>
        <p>“A beautiful experience from start to finish.”</p>
      </blockquote>
      <figcaption>Priya, Marketing Director</figcaption>
    </figure>
  </div>
</section>
""",
    ),
    "faq": Snippet(
        "FAQ",
        """
<section class="section max-w-lg">
  <h2>Frequently asked questions</h2>
  <details class="faq">
    <summary>What should visitors know first?</summary>
    <p>Answer with a friendly sentence or two. Keep it simple and actionable.</p>
  </details>
  <details class="faq">
    <summary>How long does setup take?</summary>
    <p>Most teams publish in under a day—drag, drop, and refine.</p>
  </details>
  <details class="faq">
    <summary>Can I update content later?</summary>
    <p>Absolutely. Add new sections and tweak copy whenever inspiration strikes.</p>
  </details>
</section>
""",
    ),
    "blog": Snippet(
        "Blog list",
        """
<section class="section">
  <h2>Latest stories</h2>
  <div class="grid split-3">
    <article class="card">
      <span class="badge">Jul 14</span>
      <h3>Headline for a new update</h3>
      <p>Keep it short and helpful. Tell the reader what they'll learn.</p>
      <a class="btn btn-link" href="#">Read more</a>
    </article>
    <article class="card">
      <span class="badge">Jul 03</span>
      <h3>Another quick story</h3>
      <p>Share progress, showcase customers, or explain a concept.</p>
      <a class="btn btn-link" href="#">Read more</a>
    </article>
  </div>
</section>
""",
    ),
    "feature-matrix": Snippet(
        "Feature matrix",
        """
<section class="section">
  <h2>Compare plans</h2>
  <div class="grid split-3">
    <article class="card">
      <h3>Starter</h3>
      <ul class="list-check">
        <li>Core features</li>
        <li>Email support</li>
        <li>Community access</li>
      </ul>
      <a class="btn btn-outline" href="#">Choose plan</a>
    </article>
    <article class="card">
      <h3>Growth</h3>
      <ul class="list-check">
        <li>Everything in Starter</li>
        <li>Advanced analytics</li>
        <li>Priority help</li>
      </ul>
      <a class="btn btn-primary" href="#">Best for teams</a>
    </article>
    <article class="card">
      <h3>Scale</h3>
      <ul class="list-check">
        <li>Unlimited projects</li>
        <li>Dedicated support</li>
        <li>Custom integrations</li>
      </ul>
      <a class="btn btn-outline" href="#">Talk to sales</a>
    </article>
  </div>
</section>
""",
    ),
    "timeline": Snippet(
        "Timeline",
        """
<section class="section section-alt">
  <h2>Roadmap</h2>
  <div class="timeline">
    <div class="timeline-item">
      <span class="badge">Phase 1</span>
      <div>
        <h3>Discovery</h3>
        <p>Understand needs, audience, and goals.</p>
      </div>
    </div>
    <div class="timeline-item">
      <span class="badge">Phase 2</span>
      <div>
        <h3>Design</h3>
        <p>Prototype and iterate with feedback.</p>
      </div>
    </div>
    <div class="timeline-item">
      <span class="badge">Phase 3</span>
      <div>
        <h3>Launch</h3>
        <p>Ship with confidence and celebrate wins.</p>
      </div>
    </div>
  </div>
</section>
""",
    ),
    "steps": Snippet(
        "Steps",
        """
<section class="section">
  <h2>How it works</h2>
  <div class="steps">
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
""",
    ),
    "gallery": Snippet(
        "Gallery",
        """
<section class="section">
  <h2>Gallery</h2>
  <div class="gallery">
    <figure><img src="assets/images/placeholder-wide.png" alt="Item one"></figure>
    <figure><img src="assets/images/placeholder-wide.png" alt="Item two"></figure>
    <figure><img src="assets/images/placeholder-wide.png" alt="Item three"></figure>
  </div>
</section>
""",
    ),
    "contact": Snippet(
        "Contact form",
        """
<section class="section max-w-md">
  <h2>Contact us</h2>
  <form class="stack form">
    <label>Full name<input type="text" placeholder="Your name" required></label>
    <label>Email<input type="email" placeholder="you@example.com" required></label>
    <label>How can we help?<textarea rows="4"></textarea></label>
    <button class="btn btn-primary" type="submit">Send message</button>
  </form>
</section>
""",
    ),
    "glass-card-cta": Snippet(
        "Glass card CTA",
        """
<section class="section text-center">
  <div class="glass" style="padding:2rem; border-radius:.8rem;">
    <h3>Level up your site</h3>
    <p class="muted">Swap themes, drop sections, and publish anywhere.</p>
    <a class="btn neon-btn" href="#">Try a template</a>
  </div>
</section>
""",
    ),
}


COMPONENT_SNIPPETS: Dict[str, Snippet] = {
    "button-primary": Snippet("Button — primary", "<a class=\"btn btn-primary\" href=\"#\">Primary action</a>"),
    "button-soft": Snippet("Button — soft", "<a class=\"btn btn-soft\" href=\"#\">Soft button</a>"),
    "button-outline": Snippet("Button — outline", "<a class=\"btn btn-outline\" href=\"#\">Outline button</a>"),
    "button-ghost": Snippet("Button — ghost", "<a class=\"btn btn-ghost\" href=\"#\">Ghost button</a>"),
    "button-pill": Snippet("Button — pill", "<a class=\"btn btn-primary btn-pill\" href=\"#\">Pill button</a>"),
    "button-gradient": Snippet("Button — gradient", "<a class=\"btn btn-gradient\" href=\"#\">Gradient button</a>"),
    "button-neon": Snippet("Button — neon", "<a class=\"btn neon-btn\" href=\"#\">Glow button</a>"),
    "alert": Snippet("Alert / Callout", "<aside class=\"alert alert-info\">Friendly reminder or info.</aside>"),
    "alert-success": Snippet("Alert — success", "<aside class=\"alert alert-success\">Great news!</aside>"),
    "card": Snippet(
        "Card",
        """
<article class="card">
  <h3>Card title</h3>
  <p>Use cards to highlight features or short blurbs.</p>
  <a class="btn btn-link" href="#">Read more</a>
</article>
""",
    ),
    "glass-card": Snippet(
        "Card — glass",
        """
<article class="glass" style="padding:1.5rem;">
  <h3>Frosted glass</h3>
  <p>Backdrop-filter and subtle borders create a modern feel.</p>
</article>
""",
    ),
    "tabs": Snippet(
        "Tabs (CSS only)",
        """
<div class="tabs">
  <input checked id="tab-one" name="example-tabs" type="radio">
  <label for="tab-one">Tab one</label>
  <div class="tab-content">
    <p>Content for the first tab.</p>
  </div>
  <input id="tab-two" name="example-tabs" type="radio">
  <label for="tab-two">Tab two</label>
  <div class="tab-content">
    <p>Content for the second tab.</p>
  </div>
</div>
""",
    ),
    "accordion": Snippet(
        "Accordion",
        """
<details class="faq">
  <summary>Frequently asked question</summary>
  <p>Provide a clear, concise answer.</p>
</details>
""",
    ),
    "badge": Snippet("Badge", "<span class=\"badge\">New</span>"),
    "chip": Snippet("Chip", "<span class=\"chip\">Beta</span>"),
    "divider": Snippet("Divider", "<div class=\"divider\"></div>"),
    "breadcrumb": Snippet(
        "Breadcrumb",
        """
<nav class="breadcrumb" aria-label="Breadcrumb">
  <a href="#">Home</a>
  <span aria-hidden="true">›</span>
  <a href="#">Library</a>
  <span aria-hidden="true">›</span>
  <span aria-current="page">Current page</span>
</nav>
""",
    ),
    "pill-nav": Snippet(
        "Pill navigation",
        """
<nav class="pill-nav" aria-label="Secondary">
  <a class="is-active" href="#">Overview</a>
  <a href="#">Features</a>
  <a href="#">Pricing</a>
  <a href="#">FAQ</a>
</nav>
""",
    ),
    "icon-list": Snippet(
        "Icon list",
        """
<ul class="list-check">
  <li>First highlight</li>
  <li>Second highlight</li>
  <li>Third highlight</li>
</ul>
""",
    ),
    "inline-tags": Snippet(
        "Inline tags",
        """
<div class="inline-tags">
  <span>Design</span>
  <span>Research</span>
  <span>Strategy</span>
</div>
""",
    ),
}


EFFECT_SNIPPETS: Dict[str, Snippet] = {
    "wave": Snippet("Wave separator", svg_wave()),
    "shimmer": Snippet("Shimmer placeholder", "<div class=\"shimmer\" style=\"height:180px; border-radius:var(--radius-md);\"></div>"),
    "scroll-reveal": Snippet(
        "Scroll reveal demo",
        """
<section class="section">
  <h2 class="anim-fade-in">Delightful animations</h2>
  <p class="anim-fade-up">Add <code>anim-fade-up</code>, <code>anim-fade-in</code>, or <code>anim-zoom-in</code> to any element.</p>
  <div class="tile-grid">
    <article class="tile anim-zoom-in">
      <h3>Ready when visible</h3>
      <p>Elements animate gently as they enter the viewport.</p>
    </article>
    <article class="tile anim-fade-up">
      <h3>Respect preferences</h3>
      <p>Reduced motion visitors see calm, static content.</p>
    </article>
  </div>
</section>
<!-- Turn on Design → Motion → Enable appear-on-scroll (JS) for full effect. -->
""",
        requires_js=True,
    ),
}


class ColorButton(QtWidgets.QPushButton):
    """Small helper button that opens a color dialog and shows the current color."""

    colorChanged = QtCore.pyqtSignal(str)

    def __init__(self, color: str = "#ffffff",
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._color = color or "#ffffff"
        self.setMinimumWidth(80)
        self.clicked.connect(self._choose_color)
        self._update_style()

    def color(self) -> str:
        return self._color

    def setColor(self, color: str) -> None:
        if not color:
            return
        if color == self._color:
            return
        self._color = color
        self._update_style()
        self.colorChanged.emit(color)

    def _choose_color(self) -> None:
        dialog_color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(self._color), self.window())
        if dialog_color.isValid():
            self.setColor(dialog_color.name())

    def _update_style(self) -> None:
        self.setText(self._color.upper())
        self.setStyleSheet(
            f"background:{
                self._color}; border: 1px solid rgba(148,163,184,0.6); border-radius:4px;"
            " padding: 6px;"
        )


# ---------------------------------------------------------------------------
# Section helper utilities
# ---------------------------------------------------------------------------


def html_section_hero() -> str:
    return LAYOUT_SNIPPETS["hero-spotlight"].html.strip()


def html_section_two_column() -> str:
    return """<section class=\"section\">\n  <div class=\"grid split-2\">\n    <article class=\"stack\">\n      <p class=\"eyebrow\">Why choose us</p>\n      <h2>Share a concise benefit</h2>\n      <p>Use this space to explain how you help visitors solve their problem or reach a goal.</p>\n      <div class=\"stack-inline\">\n        <a class=\"btn btn-primary\" href=\"#\">Primary action</a>\n        <a class=\"btn btn-ghost\" href=\"#\">Learn more</a>\n      </div>\n    </article>\n    <article class=\"card media\">\n      <img src=\"assets/images/placeholder-wide.png\" alt=\"Screenshot preview\">\n    </article>\n  </div>\n</section>"""


def html_section_features() -> str:
    return """<section class=\"section\">\n  <h2>Highlights</h2>\n  <div class=\"grid split-3\">\n    <article class=\"card\">\n      <h3>Fast onboarding</h3>\n      <p>Walk newcomers through the essentials in minutes.</p>\n    </article>\n    <article class=\"card\">\n      <h3>Thoughtful design</h3>\n      <p>Clean layouts keep attention on your message.</p>\n    </article>\n    <article class=\"card\">\n      <h3>Built to grow</h3>\n      <p>Swap or add sections as your story evolves.</p>\n    </article>\n  </div>\n</section>"""


def html_section_cta() -> str:
    return """<section class=\"section center\">\n  <div class=\"card stack center\">\n    <h2>Ready to get started?</h2>\n    <p class=\"lead\">Invite visitors to take the next step with a clear promise.</p>\n    <div class=\"stack-inline\">\n      <a class=\"btn btn-primary\" href=\"#\">Start now</a>\n      <a class=\"btn btn-ghost\" href=\"#\">Talk to us</a>\n    </div>\n  </div>\n</section>"""


def html_section_faq() -> str:
    return """<section class=\"section max-w-lg\">\n  <h2>Frequently asked questions</h2>\n  <details class=\"faq\">\n    <summary>What should visitors know first?</summary>\n    <p>Answer with a friendly sentence or two. Keep it simple and actionable.</p>\n  </details>\n  <details class=\"faq\">\n    <summary>How long does setup take?</summary>\n    <p>Most teams publish in under a day—drag, drop, and refine.</p>\n  </details>\n  <details class=\"faq\">\n    <summary>Can I update content later?</summary>\n    <p>Absolutely. Add new sections and tweak copy whenever inspiration strikes.</p>\n  </details>\n</section>"""


def html_section_pricing() -> str:
    return SECTIONS_SNIPPETS["pricing"].html.strip()


def html_section_testimonials() -> str:
    return SECTIONS_SNIPPETS["testimonials"].html.strip()


def html_section_gallery() -> str:
    return SECTIONS_SNIPPETS["gallery"].html.strip()


def html_section_contact_form() -> str:
    return SECTIONS_SNIPPETS["contact"].html.strip()


def html_section_about_header() -> str:
    return """<section class=\"section max-w-lg\">\n  <p class=\"eyebrow\">About</p>\n  <h1>Meet the team behind your next big win</h1>\n  <p class=\"lead\">Share your mission, values, and the milestones that make your story memorable.</p>\n</section>"""


def svg_blob(color: str = "#e5e7eb") -> str:
    return f"""<svg viewBox=\"0 0 600 400\" xmlns=\"http://www.w3.org/2000/svg\" width=\"100%\" height=\"100%\" preserveAspectRatio=\"none\">\n  <path fill=\"{color}\" d=\"M92.4,-111.4C126.6,-86.1,162.9,-64.6,185.5,-31.5C208,1.6,216.9,46.3,199.6,85.9C182.3,125.4,138.9,159.8,93.5,176.8C48.2,193.9,1,193.7,-46.2,188.6C-93.4,183.4,-140.6,173.2,-171.8,141.6C-203,110,-218.3,57.1,-213.4,7.2C-208.5,-42.6,-183.4,-89.6,-148.9,-116.1C-114.5,-142.6,-70.8,-148.7,-31.7,-141.8C7.4,-134.8,14.8,-114.8,92.4,-111.4Z\" transform=\"translate(300 200)\"/>\n</svg>"""


def svg_dots(bg: str = "#ffffff", dot: str = "#e5e7eb") -> str:
    return f"""<svg viewBox=\"0 0 400 200\" xmlns=\"http://www.w3.org/2000/svg\" width=\"100%\" height=\"100%\" preserveAspectRatio=\"none\">\n  <defs>\n    <pattern id=\"dots\" x=\"0\" y=\"0\" width=\"24\" height=\"24\" patternUnits=\"userSpaceOnUse\">\n      <rect width=\"24\" height=\"24\" fill=\"{bg}\"/>\n      <circle cx=\"6\" cy=\"6\" r=\"3\" fill=\"{dot}\"/>\n      <circle cx=\"18\" cy=\"18\" r=\"3\" fill=\"{dot}\"/>\n    </pattern>\n  </defs>\n  <rect width=\"400\" height=\"200\" fill=\"url(#dots)\"/>\n</svg>"""


def svg_diagonal_stripes(bg: str = "#ffffff", stripe: str = "#f1f5f9") -> str:
    return f"""<svg viewBox=\"0 0 400 200\" xmlns=\"http://www.w3.org/2000/svg\" width=\"100%\" height=\"100%\" preserveAspectRatio=\"none\">\n  <defs>\n    <pattern id=\"diagonal\" width=\"20\" height=\"20\" patternUnits=\"userSpaceOnUse\" patternTransform=\"rotate(45)\">\n      <rect width=\"20\" height=\"20\" fill=\"{bg}\"/>\n      <rect width=\"10\" height=\"20\" fill=\"{stripe}\"/>\n    </pattern>\n  </defs>\n  <rect width=\"400\" height=\"200\" fill=\"url(#diagonal)\"/>\n</svg>"""


BACKGROUND_SCOPE_CHOICES = ["Entire site", "Current page"]
BACKGROUND_KIND_CHOICES = ["Solid", "Gradient", "Image", "Pattern"]
BACKGROUND_PATTERN_PRESETS: Dict[str, str] = {
    "Soft waves": svg_wave("#dbeafe"),
    "Diagonal": svg_diagonal_stripes("#ffffff", "#e2e8f0"),
    "Dot grid": svg_dots("#ffffff", "#cbd5f5"),
}
# ---------------------------------------------------------------------------
# Template specifications
# ---------------------------------------------------------------------------


@dataclass
class TemplateSpec:
    name: str
    description: str
    pages: List[Tuple[str, str, str]]
    palette: Optional[Dict[str, str]] = None
    fonts: Optional[Dict[str, str]] = None
    extra_css: str = ""
    include_helpers: bool = True
    gradients: Optional[Dict[str, str]] = None
    radius_scale: Optional[float] = None
    shadow_level: Optional[str] = None
    cover_html: Optional[str] = None
    cover_css: Optional[str] = None


def _starter_spec() -> TemplateSpec:
    hero = html_section_hero()
    hero = hero.replace(
        "Headline that inspires confidence",
        "Welcome to {{SITE_NAME}}")
    hero = hero.replace(
        "Explain what you offer and the value in a friendly tone.",
        "Share a friendly, one-sentence promise that sets the tone.",
    )
    hero = hero.replace("Primary call to action", "Get started")
    hero = hero.replace("Secondary link", "Preview features")
    two_column = html_section_two_column()
    features = html_section_features()
    cta = html_section_cta().replace("Ready to get started?", "Launch in minutes")
    cta = cta.replace(
        "Invite visitors to take the next step with a clear promise.",
        "Publish quickly, iterate often.",
    )
    html = "\n\n".join([hero, two_column, features, cta])
    cover_html = """
<div class=\"cover-root\">
  <section class=\"cover-hero\">
    <div class=\"cover-copy\">
      <span class=\"cover-eyebrow\">Launch-ready landing</span>
      <h1>{{SITE_NAME}}</h1>
      <p class=\"cover-lead\">Craft a polished hero, highlight benefits, and guide visitors to action.</p>
      <div class=\"cover-cta-row\">
        <span class=\"cover-chip primary\">Get started</span>
        <span class=\"cover-chip ghost\">Preview tour</span>
      </div>
    </div>
    <div class=\"cover-hero-art\">
      <div class=\"cover-mockup\">
        <div class=\"cover-mockup-bar\"></div>
        <div class=\"cover-mockup-body\"></div>
      </div>
    </div>
  </section>
  <section class=\"cover-grid\">
    <article class=\"cover-card\">
      <h3>Hero-first</h3>
      <p>Set the tone with a confident headline and supporting copy.</p>
    </article>
    <article class=\"cover-card\">
      <h3>Feature highlights</h3>
      <p>Pair icons and copy to explain how you help.</p>
    </article>
    <article class=\"cover-card\">
      <h3>CTA clarity</h3>
      <p>Keep visitors moving with primary and secondary paths.</p>
    </article>
  </section>
</div>
"""
    cover_css = """
body {
  margin: 0;
  background: var(--color-surface);
  color: var(--color-text);
  font-family: var(--font-body);
}
.cover-root {
  padding: 48px 56px;
  display: flex;
  flex-direction: column;
  gap: 36px;
}
.cover-hero {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 48px;
  background: radial-gradient(circle at top left, rgba(255,255,255,0.92), transparent 60%), var(--color-surface);
  border-radius: 28px;
  padding: 56px;
  box-shadow: 0 36px 90px rgba(15,23,42,0.16);
  border: 1px solid rgba(15,23,42,0.08);
}
.cover-copy h1 {
  font-family: var(--font-heading);
  font-size: 2.8rem;
  margin: 0 0 12px 0;
}
.cover-eyebrow {
  display: inline-flex;
  padding: 6px 14px;
  border-radius: 999px;
  background: rgba(37,99,235,0.12);
  color: rgba(37,99,235,0.9);
  font-weight: 600;
  font-size: 0.85rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.cover-lead {
  font-size: 1.1rem;
  line-height: 1.6;
  margin-bottom: 20px;
  max-width: 440px;
}
.cover-cta-row {
  display: inline-flex;
  gap: 14px;
}
.cover-chip {
  padding: 12px 22px;
  border-radius: 999px;
  font-weight: 600;
  box-shadow: 0 14px 30px rgba(37,99,235,0.18);
}
.cover-chip.primary {
  background: var(--color-primary);
  color: white;
}
.cover-chip.ghost {
  background: rgba(15,23,42,0.06);
}
.cover-hero-art {
  position: relative;
}
.cover-mockup {
  background: linear-gradient(140deg, rgba(37,99,235,0.95), rgba(37,99,235,0.65));
  border-radius: 26px;
  padding: 26px;
  min-height: 280px;
  display: grid;
  grid-template-rows: 36px 1fr;
  gap: 20px;
  box-shadow: 0 40px 70px rgba(37,99,235,0.32);
}
.cover-mockup-bar {
  background: rgba(255,255,255,0.35);
  border-radius: 999px;
}
.cover-mockup-body {
  background: rgba(255,255,255,0.18);
  border-radius: 18px;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.22);
}
.cover-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 24px;
}
.cover-card {
  background: white;
  border-radius: 20px;
  padding: 24px;
  box-shadow: 0 24px 60px rgba(15,23,42,0.12);
  border: 1px solid rgba(15,23,42,0.05);
}
.cover-card h3 {
  margin-top: 0;
  font-family: var(--font-heading);
}
"""
    return TemplateSpec(
        name="Starter landing",
        description="Hero-first landing page with highlights and a call to action.",
        pages=[("index.html", "Home", html)],
        palette=dict(DEFAULT_PALETTE),
        fonts=dict(DEFAULT_FONTS),
        cover_html=cover_html,
        cover_css=cover_css,
    )


def _portfolio_spec() -> TemplateSpec:
    hero = LAYOUT_SNIPPETS["hero-split"].html.strip()
    hero = hero.replace("New announcement", "Case studies")
    hero = hero.replace("Highlight the benefit", "I'm {{SITE_NAME}}")
    hero = hero.replace(
        "Share how you solve the problem, not the feature list.",
        "I help teams design thoughtful, accessible web experiences.",
    )
    hero = hero.replace("Get started", "See projects")
    hero = hero.replace("Talk to us", "Book a call")
    projects = """<section class="section">
  <h2>Featured work</h2>
  <div class="grid split-2">
    <article class="card">
      <h3>Case Study One</h3>
      <p>Results-driven redesign for a SaaS platform.</p>
      <a class="btn btn-link" href="projects.html">View case study</a>
    </article>
    <article class="card">
      <h3>Case Study Two</h3>
      <p>Growth-focused marketing site for a startup.</p>
      <a class="btn btn-link" href="projects.html">View case study</a>
    </article>
  </div>
</section>"""
    testimonials = html_section_testimonials()
    cta = html_section_cta().replace("Ready to get started?", "Let’s collaborate")
    cta = cta.replace(
        "Invite visitors to take the next step with a clear promise.",
        "Share a project brief and we'll schedule a kickoff call.",
    )
    index_html = "\n\n".join([hero, projects, testimonials, cta])
    projects_page = """<section class="section">
  <h1>Projects</h1>
  <div class="grid split-3">
    <article class="card">
      <h2>Product Launch</h2>
      <p>A sprint to craft a cohesive visual identity.</p>
      <ul class="list-check">
        <li>Brand discovery</li>
        <li>Design system</li>
        <li>Launch support</li>
      </ul>
    </article>
    <article class="card">
      <h2>Research Library</h2>
      <p>Turning interviews into a searchable knowledge base.</p>
    </article>
    <article class="card">
      <h2>Marketing Refresh</h2>
      <p>Story-driven pages that convert curious visitors.</p>
    </article>
  </div>
</section>"""
    contact_page = "\n\n".join(
        [html_section_contact_form(), html_section_faq()])
    palette = {"primary": "#15803d", "surface": "#f0fdf4", "text": "#052e16"}
    fonts = {"heading": "'Poppins', 'Segoe UI', sans-serif",
             "body": "'Inter', 'Segoe UI', sans-serif"}
    cover_html = """
<div class=\"portfolio-cover\">
  <section class=\"portfolio-hero\">
    <div class=\"portfolio-avatar\">UX</div>
    <div class=\"portfolio-copy\">
      <span class=\"portfolio-label\">Creative portfolio</span>
      <h1>{{SITE_NAME}}</h1>
      <p>Selected case studies and brand explorations for modern teams.</p>
      <div class=\"portfolio-tags\">
        <span>Product design</span>
        <span>Brand systems</span>
        <span>Accessibility</span>
      </div>
      <div class=\"portfolio-actions\">
        <span class=\"portfolio-chip primary\">View projects</span>
        <span class=\"portfolio-chip ghost\">Book a call</span>
      </div>
    </div>
  </section>
  <section class=\"portfolio-grid\">
    <article>
      <h3>Case study: Motionly</h3>
      <p>Reimagined onboarding to lift activation by 36%.</p>
    </article>
    <article>
      <h3>Identity: Northlake</h3>
      <p>Warm, editorial look for a mission-driven nonprofit.</p>
    </article>
    <article>
      <h3>UX audit: Segment</h3>
      <p>Prioritized fixes with annotated walkthroughs.</p>
    </article>
  </section>
</div>
"""
    cover_css = """
body {
  margin: 0;
  background: var(--color-surface);
  font-family: var(--font-body);
  color: var(--color-text);
}
.portfolio-cover {
  padding: 48px 52px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}
.portfolio-hero {
  display: grid;
  gap: 28px;
  grid-template-columns: auto 1fr;
  align-items: center;
  background: linear-gradient(135deg, rgba(21,128,61,0.16), rgba(21,128,61,0.04));
  border-radius: 32px;
  padding: 48px 52px;
  border: 1px solid rgba(5,46,22,0.08);
  box-shadow: 0 28px 70px rgba(5,46,22,0.16);
}
.portfolio-avatar {
  width: 96px;
  height: 96px;
  border-radius: 28px;
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 1.6rem;
  color: white;
  background: linear-gradient(160deg, var(--color-primary), rgba(21,128,61,0.75));
  box-shadow: 0 22px 45px rgba(21,128,61,0.35);
}
.portfolio-copy h1 {
  font-family: var(--font-heading);
  font-size: 2.6rem;
  margin: 0 0 12px 0;
}
.portfolio-label {
  text-transform: uppercase;
  font-weight: 600;
  font-size: 0.85rem;
  letter-spacing: 0.08em;
  color: rgba(5,46,22,0.68);
}
.portfolio-copy p {
  max-width: 520px;
  line-height: 1.6;
  font-size: 1.05rem;
}
.portfolio-tags {
  display: inline-flex;
  gap: 12px;
  flex-wrap: wrap;
  margin: 16px 0;
}
.portfolio-tags span {
  padding: 6px 14px;
  border-radius: 999px;
  background: rgba(5,46,22,0.08);
  font-weight: 600;
}
.portfolio-actions {
  display: flex;
  gap: 12px;
}
.portfolio-chip {
  padding: 12px 22px;
  border-radius: 999px;
  font-weight: 600;
}
.portfolio-chip.primary {
  background: var(--color-primary);
  color: white;
  box-shadow: 0 16px 40px rgba(21,128,61,0.35);
}
.portfolio-chip.ghost {
  background: rgba(5,46,22,0.08);
}
.portfolio-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 24px;
}
.portfolio-grid article {
  background: white;
  border-radius: 22px;
  padding: 22px;
  border: 1px solid rgba(5,46,22,0.06);
  box-shadow: 0 20px 60px rgba(5,46,22,0.12);
}
.portfolio-grid h3 {
  margin-top: 0;
  font-family: var(--font-heading);
}
"""
    return TemplateSpec(
        name="Portfolio",
        description="Showcase projects with testimonials and a contact path.",
        pages=[
            ("index.html", "Home", index_html),
            ("projects.html", "Projects", projects_page),
            ("contact.html", "Contact", contact_page),
        ],
        palette=palette,
        fonts=fonts,
        cover_html=cover_html,
        cover_css=cover_css,
    )


def _resource_spec() -> TemplateSpec:
    hero = html_section_hero()
    hero = hero.replace(
        "Headline that inspires confidence",
        "{{SITE_NAME}} Resource Hub")
    hero = hero.replace(
        "Explain what you offer and the value in a friendly tone.",
        "Find guides, tutorials, and quick wins for your team.",
    )
    hero = hero.replace("Primary call to action", "Browse guides")
    hero = hero.replace("Secondary link", "Contact support")
    cards = """<section class="section">
  <h2>Popular guides</h2>
  <div class="grid split-3">
    <article class="card">
      <h3>Getting started</h3>
      <p>Set up and launch in under ten minutes.</p>
      <a class="btn btn-link" href="guide.html">Read guide</a>
    </article>
    <article class="card">
      <h3>Team workflows</h3>
      <p>Collaborate smoothly across your organization.</p>
      <a class="btn btn-link" href="guide.html">Read guide</a>
    </article>
    <article class="card">
      <h3>Troubleshooting</h3>
      <p>Quick answers for common questions.</p>
      <a class="btn btn-link" href="guide.html">Read guide</a>
    </article>
  </div>
</section>"""
    updates = """<section class="section section-alt">
  <h2>Recently updated</h2>
  <div class="timeline">
    <div class="timeline-item">
      <span class="badge">Apr</span>
      <div>
        <h3>Version 2.1 release notes</h3>
        <p>Improved navigation, accessibility, and performance tweaks.</p>
      </div>
    </div>
    <div class="timeline-item">
      <span class="badge">Mar</span>
      <div>
        <h3>New onboarding lessons</h3>
        <p>Three quick videos to help new teammates succeed.</p>
      </div>
    </div>
  </div>
</section>"""
    faq = html_section_faq()
    index_html = "\n\n".join([hero, cards, updates, faq])
    guide_html = """<section class="section">
  <h1>Documentation</h1>
  <div class="tabs">
    <input checked id="tab-intro" name="docs-tabs" type="radio">
    <label for="tab-intro">Introduction</label>
    <div class="tab-content">
      <p>Explain the basics, link to quick wins, and define success.</p>
    </div>
    <input id="tab-guides" name="docs-tabs" type="radio">
    <label for="tab-guides">Guides</label>
    <div class="tab-content">
      <p>Break down tasks into clear, step-by-step instructions.</p>
    </div>
    <input id="tab-faq" name="docs-tabs" type="radio">
    <label for="tab-faq">FAQ</label>
    <div class="tab-content">
      <p>Collect helpful answers to unblock your team quickly.</p>
    </div>
  </div>
</section>"""
    palette = {"primary": "#6366f1", "surface": "#111827", "text": "#f9fafb"}
    fonts = {
        "heading": "'Source Sans Pro', 'Helvetica Neue', Arial, sans-serif",
        "body": "'Inter', 'Segoe UI', sans-serif"}
    cover_html = """
<div class=\"resource-cover\">
  <section class=\"resource-hero\">
    <div class=\"resource-meta\">
      <span class=\"resource-label\">Resource hub</span>
      <h1>{{SITE_NAME}}</h1>
      <p>Guides, tutorials, and FAQs to help teams move faster.</p>
      <div class=\"resource-cta\">
        <span class=\"resource-chip\">Browse articles</span>
        <span class=\"resource-chip ghost\">Watch intro</span>
      </div>
    </div>
    <div class=\"resource-panel\">
      <div class=\"resource-panel-row\">
        <span class=\"badge\">New</span>
        <p>Automation playbook</p>
      </div>
      <div class=\"resource-panel-row\">
        <span class=\"badge\">Guide</span>
        <p>Team onboarding checklist</p>
      </div>
      <div class=\"resource-panel-row\">
        <span class=\"badge\">FAQ</span>
        <p>How do I sync content?</p>
      </div>
    </div>
  </section>
  <section class=\"resource-grid\">
    <article>
      <h3>Start here</h3>
      <p>Step-by-step launch plan with embedded video lessons.</p>
    </article>
    <article>
      <h3>Release notes</h3>
      <p>See what's new and why it matters for your workflow.</p>
    </article>
    <article>
      <h3>Community picks</h3>
      <p>Curated insights from power users and partner teams.</p>
    </article>
  </section>
</div>
"""
    cover_css = """
body {
  margin: 0;
  background: var(--color-surface);
  color: var(--color-text);
  font-family: var(--font-body);
}
.resource-cover {
  padding: 52px 56px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}
.resource-hero {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 36px;
  background: radial-gradient(circle at top right, rgba(99,102,241,0.18), transparent 60%), rgba(15,23,42,0.6);
  border-radius: 32px;
  padding: 52px;
  border: 1px solid rgba(148,163,184,0.18);
  box-shadow: 0 36px 80px rgba(15,23,42,0.45);
}
.resource-label {
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 0.85rem;
  font-weight: 600;
  color: rgba(199,210,254,0.85);
}
.resource-meta h1 {
  font-family: var(--font-heading);
  font-size: 2.6rem;
  margin: 12px 0;
}
.resource-meta p {
  max-width: 460px;
  line-height: 1.65;
  color: rgba(226,232,240,0.92);
}
.resource-cta {
  display: inline-flex;
  gap: 14px;
  margin-top: 20px;
}
.resource-chip {
  padding: 12px 22px;
  border-radius: 999px;
  font-weight: 600;
  background: var(--color-primary);
  color: white;
  box-shadow: 0 18px 48px rgba(99,102,241,0.45);
}
.resource-chip.ghost {
  background: rgba(148,163,184,0.18);
  color: var(--color-text);
  box-shadow: none;
}
.resource-panel {
  background: rgba(15,23,42,0.65);
  border-radius: 24px;
  padding: 24px;
  display: grid;
  gap: 16px;
  box-shadow: inset 0 0 0 1px rgba(148,163,184,0.22);
}
.resource-panel-row {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 12px;
  align-items: center;
  color: rgba(226,232,240,0.9);
}
.resource-panel-row .badge {
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(99,102,241,0.35);
  color: white;
  font-weight: 600;
  font-size: 0.78rem;
}
.resource-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 24px;
}
.resource-grid article {
  background: rgba(15,23,42,0.72);
  border-radius: 24px;
  padding: 24px;
  box-shadow: 0 24px 60px rgba(15,23,42,0.45);
  border: 1px solid rgba(148,163,184,0.18);
}
.resource-grid h3 {
  margin-top: 0;
  font-family: var(--font-heading);
  color: white;
}
.resource-grid p {
  color: rgba(226,232,240,0.82);
  line-height: 1.6;
}
"""
    return TemplateSpec(
        name="Resource hub",
        description="Organize documentation, tutorials, and helpful FAQs.",
        pages=[
            ("index.html", "Home", index_html),
            ("guide.html", "Guide", guide_html),
        ],
        palette=palette,
        fonts=fonts,
        extra_css=""".timeline {
  display: grid;
  gap: var(--space-4);
  border-left: 3px solid rgba(99, 102, 241, 0.35);
  padding-left: var(--space-4);
}
.timeline-item {
  display: grid;
  gap: var(--space-2);
  align-items: start;
}
.timeline-item .badge {
  background: rgba(99, 102, 241, 0.15);
  color: rgba(199, 210, 254, 0.95);
  border-radius: 999px;
  padding: 0.25rem 0.75rem;
  font-weight: 600;
}
.tabs {
  display: grid;
  gap: var(--space-3);
  background: rgba(15, 23, 42, 0.35);
  padding: var(--space-4);
  border-radius: var(--radius-md);
}
.tabs > input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.tabs > label {
  font-weight: 600;
  cursor: pointer;
  color: rgba(224, 231, 255, 0.86);
  padding-bottom: 0.35rem;
  border-bottom: 2px solid transparent;
}
.tabs > input:checked + label {
  color: white;
  border-color: rgba(99, 102, 241, 0.85);
}
.tabs .tab-content {
  display: none;
  line-height: 1.65;
  color: rgba(226, 232, 240, 0.92);
}
.tabs > input:checked + label + .tab-content {
  display: block;
}
""",
        cover_html=cover_html,
        cover_css=cover_css,
    )


def _saas_bold_spec() -> TemplateSpec:
    hero = """<section class="hero bg-gradient text-on-gradient">
  <div class="container grid split-2 align-center">
    <div class="stack">
      <p class="eyebrow">Modern SaaS</p>
      <h1>{{SITE_NAME}} helps product teams ship faster</h1>
      <p class="lead">Launch polished marketing, onboarding, and help pages without waiting on design.</p>
      <div class="stack-inline">
        <a class="btn btn-gradient" href="#">Start free trial</a>
        <a class="btn btn-ghost" href="#">See live demo</a>
      </div>
      <div class="stack-inline">
        <span class="badge">No credit card</span>
        <span class="badge">Onboard in 10 minutes</span>
      </div>
    </div>
    <div class="card shadow glass-panel stack">
      <h3>Trusted launch playbook</h3>
      <ul class="list-check">
        <li>Dynamic templates for every funnel stage.</li>
        <li>Reusable brand components.</li>
        <li>Insights to boost trial-to-paid conversion.</li>
      </ul>
    </div>
  </div>
</section>"""
    feature_bands = """<section class="section">
  <div class="grid split-3 feature-band">
    <article class="stack">
      <h3>Guided onboarding</h3>
      <p>Welcome new customers with contextual walkthroughs and smart nudges.</p>
    </article>
    <article class="stack">
      <h3>Dynamic content</h3>
      <p>Personalize messaging with data-aware sections and responsive layouts.</p>
    </article>
    <article class="stack">
      <h3>Actionable insights</h3>
      <p>Track adoption milestones and highlight the moments that matter.</p>
    </article>
  </div>
</section>"""
    metrics = """<section class="section">
  <div class="metrics-grid">
    <div class="metric">
      <strong>4.8★</strong>
      <p>Average satisfaction score from beta customers.</p>
    </div>
    <div class="metric">
      <strong>+36%</strong>
      <p>Increase in trial conversions after two weeks.</p>
    </div>
    <div class="metric">
      <strong>20 hrs</strong>
      <p>Saved every month on marketing upkeep.</p>
    </div>
  </div>
</section>"""
    testimonial = """<section class="section">
  <div class="testimonial-highlight stack">
    <p class="lead">“Webineer let us launch three new pages in a single afternoon. The gradients and animations feel premium out of the box.”</p>
    <p><strong>Avery Martin</strong> · Growth Lead at Skyline</p>
  </div>
</section>"""
    cta = """<section class="section center">
  <div class="card stack center">
    <h2>Start shipping bold experiences</h2>
    <p>Install the toolkit, pick a template, and go live in minutes.</p>
    <div class="stack-inline">
      <a class="btn btn-gradient" href="#">Create my site</a>
      <a class="btn btn-ghost" href="#">Talk with sales</a>
    </div>
  </div>
</section>"""
    index_html = "\n\n".join([hero, feature_bands, metrics, testimonial, cta])
    platform_section = """<section class="section">
  <div class="grid split-2 align-center">
    <article class="stack">
      <p class="eyebrow">Platform</p>
      <h2>Every stage covered</h2>
      <p>Ship onboarding flows, help centers, and launch microsites using one consistent system.</p>
      <ul class="list-check">
        <li>Reusable sections for product updates.</li>
        <li>Motion presets that respect accessibility.</li>
        <li>Design tokens synced to your brand.</li>
      </ul>
    </article>
    <aside class="card shadow">
      <h3>Integrations</h3>
      <ul class="stack">
        <li>Analytics &amp; attribution</li>
        <li>Marketing automation</li>
        <li>Support docs</li>
      </ul>
    </aside>
  </div>
</section>"""
    platform_html = "\n\n".join([platform_section, html_section_faq()])
    pricing_html = "\n\n".join([_pricing_hero(),
                                html_section_pricing(),
                                html_section_testimonials(),
                                html_section_cta()])
    extra_css = """.glass-panel {
  backdrop-filter: blur(18px);
  background: rgba(15, 23, 42, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.12);
}
.feature-band {
  background: rgba(15, 23, 42, 0.08);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
}
.metrics-grid {
  display: grid;
  gap: var(--space-4);
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}
.metric {
  background: rgba(15, 23, 42, 0.65);
  color: rgba(241, 245, 249, 0.92);
  padding: var(--space-4);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
}
.metric strong {
  display: block;
  font-size: 2.5rem;
}
.testimonial-highlight {
  background: rgba(15, 23, 42, 0.55);
  padding: var(--space-5);
  border-radius: var(--radius-lg);
  color: rgba(248, 250, 252, 0.92);
  box-shadow: var(--shadow-lg);
}
@media (max-width: 960px) {
  .glass-panel {
    order: -1;
  }
}
"""
    palette = {"primary": "#38bdf8", "surface": "#0f172a", "text": "#e0f2fe"}
    fonts = {"heading": "'Space Grotesk', 'Segoe UI', sans-serif",
             "body": "'Inter', 'Segoe UI', sans-serif"}
    gradients = {"from": "#22d3ee", "to": "#6366f1", "angle": "118deg"}
    cover_html = """
<div class=\"saas-cover\">
  <section class=\"saas-hero\">
    <div class=\"saas-copy\">
      <span class=\"saas-eyebrow\">Product platform</span>
      <h1>{{SITE_NAME}}</h1>
      <p>Ship onboarding journeys, release notes, and help docs from one polished hub.</p>
      <div class=\"saas-actions\">
        <span class=\"saas-chip primary\">Start free trial</span>
        <span class=\"saas-chip ghost\">Watch demo</span>
      </div>
      <div class=\"saas-metrics\">
        <article><strong>4.8★</strong><p>Customer delight score</p></article>
        <article><strong>+36%</strong><p>Activation lift</p></article>
        <article><strong>24 hrs</strong><p>To launch new pages</p></article>
      </div>
    </div>
    <div class=\"saas-dashboard\">
      <div class=\"saas-window\">
        <header><span></span><span></span><span></span></header>
        <div class=\"saas-chart\"></div>
        <div class=\"saas-pills\">
          <div>Onboarding checklist</div>
          <div>Usage analytics</div>
          <div>Lifecycle playbooks</div>
        </div>
      </div>
    </div>
  </section>
  <section class=\"saas-feature-row\">
    <article>
      <h3>Gradient hero</h3>
      <p>Blend glassmorphic panels with confident typography for instant polish.</p>
    </article>
    <article>
      <h3>Guided tours</h3>
      <p>Lead visitors to the aha moment with progressive onboarding steps.</p>
    </article>
    <article>
      <h3>Conversion ready</h3>
      <p>Pair CTAs and proof to remove friction on the path to signup.</p>
    </article>
  </section>
</div>
"""
    cover_css = """
body {
  margin: 0;
  background: radial-gradient(circle at top right, rgba(34,211,238,0.16), transparent 58%), var(--color-surface);
  color: var(--color-text);
  font-family: var(--font-body);
}
.saas-cover {
  padding: 48px 52px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}
.saas-hero {
  display: grid;
  gap: 36px;
  grid-template-columns: 1.1fr 0.9fr;
  background: linear-gradient(135deg, rgba(34,211,238,0.35), rgba(99,102,241,0.18));
  border-radius: 36px;
  padding: 52px;
  box-shadow: 0 40px 90px rgba(15,23,42,0.45);
  position: relative;
  overflow: hidden;
}
.saas-hero::after {
  content: "";
  position: absolute;
  inset: 18px;
  border: 1px solid rgba(226,232,240,0.18);
  border-radius: 30px;
  pointer-events: none;
}
.saas-copy {
  position: relative;
  z-index: 2;
  display: grid;
  gap: 18px;
}
.saas-eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 0.85rem;
  font-weight: 600;
  color: rgba(226,232,240,0.85);
}
.saas-copy h1 {
  font-family: var(--font-heading);
  font-size: 2.8rem;
  margin: 0;
  color: white;
}
.saas-copy p {
  max-width: 460px;
  line-height: 1.6;
  color: rgba(226,232,240,0.88);
}
.saas-actions {
  display: inline-flex;
  gap: 16px;
}
.saas-chip {
  padding: 12px 22px;
  border-radius: 999px;
  font-weight: 600;
  backdrop-filter: blur(12px);
}
.saas-chip.primary {
  background: var(--color-primary);
  color: #0f172a;
  box-shadow: 0 16px 48px rgba(34,211,238,0.45);
}
.saas-chip.ghost {
  color: rgba(226,232,240,0.92);
  border: 1px solid rgba(226,232,240,0.35);
}
.saas-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(120px, 1fr));
  gap: 16px;
  margin-top: 12px;
}
.saas-metrics article {
  background: rgba(15,23,42,0.35);
  border-radius: 18px;
  padding: 16px 18px;
  color: rgba(226,232,240,0.9);
  text-align: center;
}
.saas-metrics strong {
  display: block;
  font-family: var(--font-heading);
  font-size: 1.6rem;
}
.saas-dashboard {
  position: relative;
  z-index: 2;
  display: flex;
  justify-content: center;
  align-items: center;
}
.saas-window {
  width: 100%;
  max-width: 420px;
  background: rgba(15,23,42,0.65);
  border-radius: 28px;
  padding: 26px;
  box-shadow: 0 30px 60px rgba(15,23,42,0.55);
  color: white;
}
.saas-window header {
  display: inline-flex;
  gap: 8px;
  margin-bottom: 18px;
}
.saas-window header span {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: rgba(255,255,255,0.35);
}
.saas-chart {
  height: 160px;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(34,211,238,0.3), rgba(15,23,42,0.1));
  margin-bottom: 18px;
  position: relative;
  overflow: hidden;
}
.saas-chart::after {
  content: "";
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 20% 80%, rgba(94,234,212,0.4), transparent 55%),
              radial-gradient(circle at 80% 20%, rgba(129,140,248,0.35), transparent 55%);
}
.saas-pills {
  display: grid;
  gap: 10px;
}
.saas-pills div {
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(15,23,42,0.55);
  border: 1px solid rgba(148,163,184,0.25);
  font-weight: 600;
}
.saas-feature-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 24px;
}
.saas-feature-row article {
  background: white;
  padding: 24px;
  border-radius: 22px;
  box-shadow: 0 22px 55px rgba(15,23,42,0.18);
}
.saas-feature-row h3 {
  font-family: var(--font-heading);
  margin-top: 0;
}
.saas-feature-row p {
  margin-bottom: 0;
  color: rgba(15,23,42,0.76);
}
"""
    return TemplateSpec(
        name="Bold SaaS",
        description="Gradient-rich SaaS marketing with metrics, testimonials, and pricing.",
        pages=[
            ("index.html", "Home", index_html),
            ("platform.html", "Platform", platform_html),
            ("pricing.html", "Pricing", pricing_html),
        ],
        palette=palette,
        fonts=fonts,
        extra_css=extra_css,
        gradients=gradients,
        radius_scale=1.15,
        shadow_level="lg",
        cover_html=cover_html,
        cover_css=cover_css,
    )


def _photo_showcase_spec() -> TemplateSpec:
    hero = """<section class="hero">
  <div class="container grid split-2 align-center">
    <div class="stack">
      <p class="eyebrow">Photography portfolio</p>
      <h1>{{SITE_NAME}} captures stories in light</h1>
      <p class="lead">Blend editorial storytelling with immersive galleries that scale across devices.</p>
      <div class="stack-inline">
        <a class="btn btn-primary" href="#portfolio">View collections</a>
        <a class="btn btn-ghost" href="#contact">Book a session</a>
      </div>
    </div>
    <figure class="card shadow">
      <img src="assets/images/placeholder-tall.png" alt="Portrait sample">
      <figcaption class="muted">Lifestyle · Editorial · Brand</figcaption>
    </figure>
  </div>
</section>"""
    gallery = """<section class="section" id="portfolio">
  <h2>Featured collections</h2>
  <div class="gallery-masonry">
    <figure><img src="assets/images/placeholder-tall.png" alt="Gallery shot 1"><figcaption>City light</figcaption></figure>
    <figure><img src="assets/images/placeholder-wide.png" alt="Gallery shot 2"><figcaption>Quiet moments</figcaption></figure>
    <figure><img src="assets/images/placeholder-wide.png" alt="Gallery shot 3"><figcaption>Editorial spread</figcaption></figure>
    <figure><img src="assets/images/placeholder-tall.png" alt="Gallery shot 4"><figcaption>Portrait series</figcaption></figure>
    <figure><img src="assets/images/placeholder-wide.png" alt="Gallery shot 5"><figcaption>Brand atmosphere</figcaption></figure>
    <figure><img src="assets/images/placeholder-tall.png" alt="Gallery shot 6"><figcaption>Behind the scenes</figcaption></figure>
  </div>
  <p class="muted lightbox-hint">Tip: pair with your favorite lightbox script for interactive viewing.</p>
</section>"""
    services = """<section class="section section-alt" id="services">
  <div class="grid split-3">
    <article class="card stack">
      <h3>Brand campaigns</h3>
      <p>Create cohesive visuals for launches, billboards, and social storytelling.</p>
    </article>
    <article class="card stack">
      <h3>Editorial features</h3>
      <p>Collaborate on magazine-ready imagery with thoughtful art direction.</p>
    </article>
    <article class="card stack">
      <h3>Portrait sessions</h3>
      <p>Capture personality-driven portraits for founders and creative teams.</p>
    </article>
  </div>
</section>"""
    contact = """<section class="section" id="contact">
  <div class="card stack">
    <h2>Let's work together</h2>
    <p>Share your project goals, timelines, and inspiration. We'll reply within one day.</p>
    <form class="stack">
      <label>Name<input type="text" placeholder="Your name"></label>
      <label>Email<input type="email" placeholder="you@example.com"></label>
      <label>Project notes<textarea rows="4" placeholder="Tell us about the shoot"></textarea></label>
      <button class="btn btn-primary" type="submit">Request availability</button>
    </form>
  </div>
</section>"""
    index_html = "\n\n".join([hero, gallery, services, contact])
    story_page = """<article class="section container stack">
  <p class="muted">Recent story</p>
  <h1>Golden hour rooftop session</h1>
  <p class="lead">We partnered with the Ember team to showcase their founders in a warm, cinematic light.</p>
  <p>Highlight the creative direction, planning, and post-production workflow. Encourage visitors to explore more stories or inquire about bookings.</p>
  <div class="gallery-inline">
    <img src="assets/images/placeholder-wide.png" alt="Story photo 1">
    <img src="assets/images/placeholder-wide.png" alt="Story photo 2">
  </div>
</article>"""
    pricing_page = """<section class="section">
  <h1>Services &amp; rates</h1>
  <div class="grid split-2">
    <article class="card stack">
      <h2>Editorial day</h2>
      <p>Full-day creative direction with production support.</p>
      <p class="lead">Starting at $3,200</p>
    </article>
    <article class="card stack">
      <h2>Brand library</h2>
      <p>Quarterly shoots to refresh your content pipeline.</p>
      <p class="lead">Starting at $5,500</p>
    </article>
  </div>
</section>"""
    extra_css = """.gallery-masonry {
  column-count: 3;
  column-gap: var(--space-4);
}
.gallery-masonry figure {
  break-inside: avoid;
  margin: 0 0 var(--space-4);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-md);
}
.gallery-masonry img {
  width: 100%;
  display: block;
}
.gallery-inline {
  display: grid;
  gap: var(--space-4);
}
.lightbox-hint {
  text-align: center;
  margin-top: var(--space-3);
}
@media (max-width: 960px) {
  .gallery-masonry {
    column-count: 2;
  }
}
@media (max-width: 640px) {
  .gallery-masonry {
    column-count: 1;
  }
}
"""
    palette = {"primary": "#f59e0b", "surface": "#0f172a", "text": "#f8fafc"}
    fonts = {"heading": "'Playfair Display', 'Times New Roman', serif",
             "body": "'Source Sans Pro', 'Helvetica Neue', sans-serif"}
    gradients = {"from": "#0ea5e9", "to": "#f472b6", "angle": "135deg"}
    cover_html = """
<div class=\"photo-cover\">
  <section class=\"photo-hero\">
    <div class=\"photo-copy\">
      <span class=\"photo-label\">Editorial photography</span>
      <h1>{{SITE_NAME}}</h1>
      <p>Tell immersive stories with layered imagery and quiet typography.</p>
      <div class=\"photo-actions\">
        <span class=\"photo-chip primary\">View portfolio</span>
        <span class=\"photo-chip ghost\">Book a session</span>
      </div>
      <ul class=\"photo-tags\">
        <li>Brand</li>
        <li>Editorial</li>
        <li>Lifestyle</li>
      </ul>
    </div>
    <div class=\"photo-mosaic\">
      <div class=\"photo-frame tall\"></div>
      <div class=\"photo-frame wide\"></div>
      <div class=\"photo-frame square\"></div>
    </div>
  </section>
  <section class=\"photo-grid\">
    <article>
      <h3>Case studies</h3>
      <p>Highlight hero shoots with warm, editorial layouts and captions.</p>
    </article>
    <article>
      <h3>Behind the scenes</h3>
      <p>Blend motion-inspired textures and candid storytelling moments.</p>
    </article>
    <article>
      <h3>Booking details</h3>
      <p>Set expectations with clear timelines, pricing, and deliverables.</p>
    </article>
  </section>
</div>
"""
    cover_css = """
body {
  margin: 0;
  background: var(--color-surface);
  color: var(--color-text);
  font-family: var(--font-body);
}
.photo-cover {
  padding: 52px 56px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}
.photo-hero {
  display: grid;
  gap: 36px;
  grid-template-columns: 1.1fr 1fr;
  background: linear-gradient(135deg, rgba(15,23,42,0.82), rgba(15,23,42,0.55));
  border-radius: 40px;
  padding: 52px;
  box-shadow: 0 36px 90px rgba(15,23,42,0.55);
  position: relative;
  overflow: hidden;
}
.photo-hero::after {
  content: "";
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at top left, rgba(15,118,110,0.35), transparent 55%),
              radial-gradient(circle at bottom right, rgba(244,114,182,0.28), transparent 60%);
  pointer-events: none;
}
.photo-copy {
  position: relative;
  z-index: 2;
  display: grid;
  gap: 20px;
  color: rgba(248,250,252,0.92);
}
.photo-label {
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 600;
  font-size: 0.85rem;
  color: rgba(236,254,255,0.75);
}
.photo-copy h1 {
  margin: 0;
  font-size: 2.9rem;
  font-family: var(--font-heading);
}
.photo-actions {
  display: inline-flex;
  gap: 16px;
}
.photo-chip {
  padding: 12px 22px;
  border-radius: 999px;
  font-weight: 600;
}
.photo-chip.primary {
  background: var(--color-primary);
  color: #0f172a;
  box-shadow: 0 22px 48px rgba(245,158,11,0.45);
}
.photo-chip.ghost {
  border: 1px solid rgba(241,245,249,0.35);
  color: rgba(241,245,249,0.92);
}
.photo-tags {
  list-style: none;
  padding: 0;
  margin: 0;
  display: inline-flex;
  gap: 12px;
}
.photo-tags li {
  padding: 6px 14px;
  border-radius: 999px;
  background: rgba(148,163,184,0.25);
}
.photo-mosaic {
  display: grid;
  grid-template-areas: "tall wide" "tall square";
  gap: 18px;
}
.photo-frame {
  border-radius: 24px;
  background: linear-gradient(160deg, rgba(15,118,110,0.65), rgba(244,114,182,0.65));
  position: relative;
  overflow: hidden;
  box-shadow: 0 28px 70px rgba(15,23,42,0.45);
}
.photo-frame::after {
  content: "";
  position: absolute;
  inset: 18px;
  border: 1px solid rgba(255,255,255,0.25);
  border-radius: 18px;
}
.photo-frame.tall { grid-area: tall; min-height: 260px; }
.photo-frame.wide { grid-area: wide; min-height: 150px; }
.photo-frame.square { grid-area: square; min-height: 150px; }
.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 24px;
}
.photo-grid article {
  background: white;
  padding: 24px;
  border-radius: 24px;
  box-shadow: 0 26px 60px rgba(15,23,42,0.15);
}
.photo-grid h3 {
  margin-top: 0;
  font-family: var(--font-heading);
}
.photo-grid p {
  color: rgba(30,41,59,0.78);
}
"""
    return TemplateSpec(
        name="Photo showcase",
        description="Immersive gallery layout with editorial storytelling and booking form.",
        pages=[
            ("index.html", "Home", index_html),
            ("story.html", "Story", story_page),
            ("services.html", "Services", pricing_page),
        ],
        palette=palette,
        fonts=fonts,
        extra_css=extra_css,
        gradients=gradients,
        radius_scale=1.05,
        shadow_level="md",
        cover_html=cover_html,
        cover_css=cover_css,
    )


def _event_launch_spec() -> TemplateSpec:
    hero = """<section class="hero bg-gradient text-on-gradient">
  <div class="container">
    <p class="eyebrow">Conference launch</p>
    <h1>Join {{SITE_NAME}} — the summit for creative web teams</h1>
    <p class="lead">Three days of workshops, inspiring keynotes, and community meetups in the heart of the city.</p>
    <div class="stack-inline">
      <a class="btn btn-gradient" href="#tickets">Reserve seat</a>
      <a class="btn btn-ghost" href="#schedule">View schedule</a>
    </div>
    <div class="stack stats-ribbon">
      <span><strong>May 24–26</strong> · Harbor Convention Center</span>
      <span><strong>500+</strong> makers · Hybrid sessions</span>
    </div>
  </div>
</section>"""
    highlights = """<section class="section">
  <div class="grid split-3">
    <article class="card stack">
      <h3>Hands-on workshops</h3>
      <p>Prototype live with mentors guiding accessibility, motion, and storytelling.</p>
    </article>
    <article class="card stack">
      <h3>Keynote voices</h3>
      <p>Hear from design systems leads shaping inclusive experiences.</p>
    </article>
    <article class="card stack">
      <h3>Community roundtables</h3>
      <p>Swap ideas with product, marketing, and engineering peers.</p>
    </article>
  </div>
</section>"""
    schedule = """<section class="section" id="schedule">
  <h2>Preview the schedule</h2>
  <div class="schedule-grid">
    <div>
      <h4>Day 1 — Momentum</h4>
      <ul>
        <li>09:00 · Welcome keynote</li>
        <li>11:00 · Building motion systems</li>
        <li>14:00 · Inclusive content sprints</li>
      </ul>
    </div>
    <div>
      <h4>Day 2 — Collaboration</h4>
      <ul>
        <li>09:30 · Designing with tokens</li>
        <li>13:00 · Gradient storytelling lab</li>
        <li>16:00 · Community showcase</li>
      </ul>
    </div>
    <div>
      <h4>Day 3 — Launch</h4>
      <ul>
        <li>10:00 · Product marketing roundtables</li>
        <li>12:30 · Live audits</li>
        <li>15:30 · Closing celebration</li>
      </ul>
    </div>
  </div>
</section>"""
    speakers = """<section class="section section-alt" id="speakers">
  <h2>Meet the speakers</h2>
  <div class="grid split-3">
    <article class="speaker-card">
      <img src="assets/images/placeholder-square.png" alt="Keynote speaker">
      <h3>Jordan Lee</h3>
      <p>Design systems lead at Atlas</p>
    </article>
    <article class="speaker-card">
      <img src="assets/images/placeholder-square.png" alt="Speaker">
      <h3>Amina Cole</h3>
      <p>Creative director at Northwind</p>
    </article>
    <article class="speaker-card">
      <img src="assets/images/placeholder-square.png" alt="Speaker">
      <h3>Sam Rivera</h3>
      <p>Product strategist at Launchpad</p>
    </article>
  </div>
</section>"""
    tickets = """<section class="section center" id="tickets">
  <div class="card stack center">
    <h2>Secure your ticket</h2>
    <p>Early access pricing available until April 30.</p>
    <div class="stack-inline">
      <a class="btn btn-gradient" href="#">General admission — $249</a>
      <a class="btn btn-ghost" href="#">Team bundles</a>
    </div>
  </div>
</section>"""
    index_html = "\n\n".join(
        [hero, highlights, schedule, speakers, tickets, html_section_faq()])
    travel_page = """<section class="section">
  <h1>Plan your visit</h1>
  <div class="grid split-2">
    <article class="stack">
      <h2>Venue</h2>
      <p>Harbor Convention Center · 221 Market Street</p>
      <p>Steps away from downtown hotels, coffee shops, and waterfront walks.</p>
      <div class="map-placeholder">Map placeholder</div>
    </article>
    <article class="stack">
      <h2>Stay &amp; explore</h2>
      <ul class="list-check">
        <li>Partner hotels with attendee rates.</li>
        <li>Local guides for dining and meetups.</li>
        <li>Transit tips for easy travel.</li>
      </ul>
    </article>
  </div>
</section>"""
    faq_page = "\n\n".join([
        """<section class="section">
  <h1>FAQ</h1>
  <p class="lead">Everything you need to know before arriving.</p>
</section>""",
        html_section_faq(),
    ])
    extra_css = """.stats-ribbon {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-top: var(--space-4);
}
.schedule-grid {
  display: grid;
  gap: var(--space-4);
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}
.schedule-grid h4 {
  margin-bottom: var(--space-2);
}
.speaker-card {
  background: rgba(15, 23, 42, 0.85);
  padding: var(--space-4);
  border-radius: var(--radius-lg);
  text-align: center;
  box-shadow: var(--shadow-lg);
}
.speaker-card img {
  border-radius: 999px;
  width: 120px;
  height: 120px;
  object-fit: cover;
  margin-bottom: var(--space-3);
}
.map-placeholder {
  background: rgba(148, 163, 184, 0.2);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  text-align: center;
  font-weight: 600;
}
@media (max-width: 720px) {
  .stats-ribbon {
    flex-direction: column;
    align-items: flex-start;
  }
}
"""
    palette = {"primary": "#fb923c", "surface": "#111827", "text": "#fef3c7"}
    fonts = {"heading": "'Plus Jakarta Sans', 'Segoe UI', sans-serif",
             "body": "'Inter', 'Segoe UI', sans-serif"}
    gradients = {"from": "#fb923c", "to": "#f43f5e", "angle": "120deg"}
    cover_html = """
<div class=\"event-cover\">
  <section class=\"event-hero\">
    <div class=\"event-copy\">
      <span class=\"event-eyebrow\">Three-day summit</span>
      <h1>{{SITE_NAME}}</h1>
      <p>Workshops, keynotes, and community meetups for creative web teams.</p>
      <div class=\"event-meta\">
        <span>May 24–26 · Harbor Convention Center</span>
        <span>500+ makers · Hybrid sessions</span>
      </div>
      <div class=\"event-actions\">
        <span class=\"event-chip primary\">Reserve seat</span>
        <span class=\"event-chip ghost\">View schedule</span>
      </div>
    </div>
    <div class=\"event-schedule\">
      <article>
        <h4>Day 1 · Momentum</h4>
        <ul>
          <li>09:00 · Opening keynote</li>
          <li>11:30 · Building with tokens</li>
          <li>15:00 · Accessibility labs</li>
        </ul>
      </article>
      <article>
        <h4>Day 2 · Collaboration</h4>
        <ul>
          <li>09:30 · Motion storytelling</li>
          <li>13:00 · Inclusive content sprints</li>
          <li>17:00 · Community showcase</li>
        </ul>
      </article>
      <article>
        <h4>Day 3 · Launch</h4>
        <ul>
          <li>10:00 · Product marketing roundtables</li>
          <li>12:30 · Live audits</li>
          <li>16:00 · Closing celebration</li>
        </ul>
      </article>
    </div>
  </section>
  <section class=\"event-speakers\">
    <article>
      <div class=\"avatar\">JL</div>
      <div><h3>Jordan Lee</h3><p>Design systems lead</p></div>
    </article>
    <article>
      <div class=\"avatar\">AC</div>
      <div><h3>Amina Cole</h3><p>Creative director</p></div>
    </article>
    <article>
      <div class=\"avatar\">SR</div>
      <div><h3>Sam Rivera</h3><p>Product strategist</p></div>
    </article>
  </section>
</div>
"""
    cover_css = """
body {
  margin: 0;
  background: radial-gradient(circle at top, rgba(251,146,60,0.25), transparent 60%), var(--color-surface);
  color: var(--color-text);
  font-family: var(--font-body);
}
.event-cover {
  padding: 48px 54px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}
.event-hero {
  display: grid;
  gap: 32px;
  grid-template-columns: 1fr 1fr;
  background: linear-gradient(125deg, rgba(251,146,60,0.28), rgba(244,63,94,0.22));
  border-radius: 36px;
  padding: 48px;
  box-shadow: 0 36px 85px rgba(15,23,42,0.55);
}
.event-copy {
  display: grid;
  gap: 18px;
}
.event-eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 0.82rem;
  font-weight: 600;
  color: rgba(248,250,252,0.8);
}
.event-copy h1 {
  margin: 0;
  font-size: 2.8rem;
  font-family: var(--font-heading);
  color: rgba(248,250,252,0.95);
}
.event-copy p {
  max-width: 420px;
  line-height: 1.6;
  color: rgba(248,250,252,0.85);
}
.event-meta {
  display: grid;
  gap: 8px;
  color: rgba(248,250,252,0.75);
}
.event-actions {
  display: inline-flex;
  gap: 16px;
}
.event-chip {
  padding: 12px 22px;
  border-radius: 999px;
  font-weight: 600;
}
.event-chip.primary {
  background: var(--color-primary);
  color: #111827;
  box-shadow: 0 22px 50px rgba(251,146,60,0.45);
}
.event-chip.ghost {
  border: 1px solid rgba(248,250,252,0.35);
  color: rgba(248,250,252,0.9);
}
.event-schedule {
  display: grid;
  gap: 16px;
}
.event-schedule article {
  background: rgba(15,23,42,0.55);
  border-radius: 20px;
  padding: 18px 20px;
  color: rgba(248,250,252,0.9);
  box-shadow: inset 0 0 0 1px rgba(248,250,252,0.08);
}
.event-schedule h4 {
  margin: 0 0 12px 0;
  font-family: var(--font-heading);
  font-size: 1.05rem;
}
.event-schedule ul {
  margin: 0;
  padding-left: 18px;
  line-height: 1.55;
}
.event-speakers {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 24px;
}
.event-speakers article {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 16px;
  align-items: center;
  background: rgba(15,23,42,0.7);
  padding: 20px 22px;
  border-radius: 22px;
  box-shadow: 0 26px 60px rgba(15,23,42,0.45);
}
.event-speakers h3 {
  margin: 0;
  font-family: var(--font-heading);
  color: rgba(248,250,252,0.95);
}
.event-speakers p {
  margin: 4px 0 0 0;
  color: rgba(248,250,252,0.7);
}
.avatar {
  width: 54px;
  height: 54px;
  border-radius: 18px;
  background: rgba(248,250,252,0.18);
  display: grid;
  place-items: center;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: rgba(248,250,252,0.9);
}
"""
    return TemplateSpec(
        name="Event launch",
        description="Countdown-ready event site with schedule, speakers, and travel info.",
        pages=[
            ("index.html", "Home", index_html),
            ("travel.html", "Travel", travel_page),
            ("faq.html", "FAQ", faq_page),
        ],
        palette=palette,
        fonts=fonts,
        extra_css=extra_css,
        gradients=gradients,
        radius_scale=1.1,
        shadow_level="md",
        cover_html=cover_html,
        cover_css=cover_css,
    )


def _pricing_hero() -> str:
    hero = html_section_hero()
    hero = hero.replace(
        "Headline that inspires confidence",
        "Pricing that scales with you")
    hero = hero.replace(
        "Explain what you offer and the value in a friendly tone.",
        "Pick the plan that matches your stage.")
    hero = hero.replace("Primary call to action", "Choose a plan")
    hero = hero.replace("Secondary link", "Contact sales")
    return hero


def _contact_intro() -> str:
    hero = html_section_hero()
    hero = hero.replace(
        "Headline that inspires confidence",
        "We’d love to hear from you")
    hero = hero.replace(
        "Explain what you offer and the value in a friendly tone.",
        "Reach out with project ideas, support questions, or quick hellos.")
    hero = hero.replace("Primary call to action", "Send a message")
    hero = hero.replace("Secondary link", "Schedule a call")
    return hero


def _docs_outline() -> str:
    return """<section class="section">
  <h2>Guide overview</h2>
  <ol class="list-check">
    <li>Welcome — set expectations for new readers.</li>
    <li>Setup — describe the steps required before they begin.</li>
    <li>Best practices — share tips to stay productive.</li>
  </ol>
</section>"""


def page_basic() -> str:
    return """<section class="section">
  <h2>New page</h2>
  <p>Start with a short introduction, then break content into sections.</p>
</section>"""


def page_pricing() -> str:
    sections = [_pricing_hero(), html_section_pricing(), html_section_faq()]
    return "\n\n".join(sections)


def page_about() -> str:
    sections = [
        html_section_about_header(),
        html_section_two_column(),
        html_section_testimonials()]
    return "\n\n".join(sections)


def page_contact() -> str:
    sections = [
        _contact_intro(),
        html_section_contact_form(),
        html_section_faq()]
    return "\n\n".join(sections)


def page_faq() -> str:
    return html_section_faq()


def page_blog_index() -> str:
    return """<section class="section">
  <h2>Latest stories</h2>
  <div class="grid split-2">
    <article class="card">
      <span class="badge">Feature</span>
      <h3>Announce something exciting</h3>
      <p>Summarize the benefit and link to the full post.</p>
      <a class="btn btn-link" href="#">Read more</a>
    </article>
    <article class="card">
      <span class="badge">Update</span>
      <h3>Share a quick win</h3>
      <p>Keep readers in the loop with short highlights.</p>
      <a class="btn btn-link" href="#">Read more</a>
    </article>
  </div>
</section>"""


def page_blog_post() -> str:
    return """<article class="section container">
  <header class="stack">
    <p class="muted">Published 2025-01-01 · 5 min read</p>
    <h1>Post title</h1>
    <p class="lead">Set up the narrative and explain why it matters.</p>
  </header>
  <p>Use short paragraphs, helpful subheadings, and add visuals to keep readers engaged.</p>
  <p>Wrap up with a summary or clear next step.</p>
</article>"""


def page_portfolio() -> str:
    sections = [
        html_section_gallery(),
        html_section_testimonials(),
        html_section_cta()]
    return "\n\n".join(sections)


def page_docs() -> str:
    return "\n\n".join([_contact_intro(), _docs_outline(), html_section_faq()])


PAGE_TYPES: Dict[str, Callable[[], str]] = {
    "Basic Page": page_basic,
    "Pricing Page": page_pricing,
    "About Page": page_about,
    "Contact Page": page_contact,
    "FAQ Page": page_faq,
    "Blog Index": page_blog_index,
    "Blog Post": page_blog_post,
    "Portfolio Projects": page_portfolio,
    "Docs Guide": page_docs,
}


PAGE_TYPE_SECTIONS: Dict[str, List[Tuple[str, Callable[[], str]]]] = {
    "Pricing Page": [
        ("Hero", _pricing_hero),
        ("Pricing grid", html_section_pricing),
        ("FAQ", html_section_faq),
    ],
    "About Page": [
        ("About header", html_section_about_header),
        ("Two column", html_section_two_column),
        ("Testimonials", html_section_testimonials),
    ],
    "Contact Page": [
        ("Intro", _contact_intro),
        ("Contact form", html_section_contact_form),
        ("FAQ", html_section_faq),
    ],
    "FAQ Page": [("FAQ", html_section_faq)],
    "Portfolio Projects": [
        ("Gallery", html_section_gallery),
        ("Testimonials", html_section_testimonials),
        ("Call to action", html_section_cta),
    ],
    "Docs Guide": [
        ("Intro", _contact_intro),
        ("Outline", _docs_outline),
        ("FAQ", html_section_faq),
    ],
}

PROJECT_TEMPLATES: Dict[str, TemplateSpec] = {
    "starter": _starter_spec(),
    "portfolio": _portfolio_spec(),
    "resource": _resource_spec(),
    "saas_bold": _saas_bold_spec(),
    "photo_showcase": _photo_showcase_spec(),
    "event_launch": _event_launch_spec(),
}


@dataclass
class TemplateDefinition:
    key: str
    title: str
    description: str
    default_pages: List[Tuple[str, str]]
    cover_html: Optional[str] = None
    cover_css: Optional[str] = None


TEMPLATES: Dict[str, TemplateDefinition] = {
    key: TemplateDefinition(
        key=key,
        title=spec.name,
        description=spec.description,
        default_pages=[
            (filename, html.replace("{{SITE_NAME}}", "{{site_name}}"))
            for filename, _, html in spec.pages
        ],
        cover_html=spec.cover_html,
        cover_css=spec.cover_css,
    )
    for key, spec in PROJECT_TEMPLATES.items()
}


# ---------------------------------------------------------------------------
# Cover rendering utilities
# ---------------------------------------------------------------------------


def _normalize_hex(color: str, default: str) -> str:
    if not color or not isinstance(color, str):
        return default
    color = color.strip()
    if not color:
        return default
    if color.startswith("#"):
        hex_part = color[1:]
        if len(hex_part) in {3, 6, 8}:
            return "#" + hex_part
    return default


def _color_from_palette(
        palette: Dict[str, str], key: str, fallback: str) -> QtGui.QColor:
    value = _normalize_hex(palette.get(key, fallback), fallback)
    color = QtGui.QColor(value)
    if not color.isValid():
        color = QtGui.QColor(fallback)
    return color


def _primary_font(font_str: str, fallback: str) -> str:
    if not font_str:
        return fallback
    primary = font_str.split(",", 1)[0].strip().strip("'\"")
    return primary or fallback


def _contrast_text_for(color: QtGui.QColor) -> QtGui.QColor:
    if not color.isValid():
        return QtGui.QColor("#0f172a")
    r, g, b = color.redF(), color.greenF(), color.blueF()
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return QtGui.QColor(
        "#0f172a") if luminance > 0.55 else QtGui.QColor("#f8fafc")


def _extract_tagline(project: Project) -> str:
    if not project.pages:
        return "Design, launch, and iterate with confidence."
    html = project.pages[0].html
    match = re.search(r"<p[^>]*>(.*?)</p>", html, re.IGNORECASE | re.DOTALL)
    if match:
        text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        if text:
            return text[:220]
    spec = PROJECT_TEMPLATES.get(project.template_key)
    if spec and spec.description:
        return spec.description
    return "Craft a polished presence in minutes."


def _collect_card_titles(project: Project) -> List[str]:
    titles = [page.title for page in project.pages[1:4] if page.title]
    if not titles:
        titles = ["Highlights", "What you get", "Next steps"]
    while len(titles) < 3:
        defaults = ["Highlights", "What you get", "Next steps", "Contact"]
        titles.append(defaults[len(titles) % len(defaults)])
    return titles[:3]


def _project_cover_asset(project: Project) -> Optional[QtGui.QPixmap]:
    candidate: Optional[AssetImage] = None
    if project.cover_asset_name:
        candidate = next(
            (img for img in project.images if img.name == project.cover_asset_name), None)
    if candidate is None:
        candidate = next(
            (img for img in project.images if img.mime != "image/svg+xml"), None)
    if candidate is None and project.images:
        candidate = project.images[0]
    if candidate is None or not candidate.data_base64:
        return None
    try:
        data = base64.b64decode(candidate.data_base64.encode("ascii"))
    except Exception:
        return None
    image = QtGui.QImage.fromData(data)
    if image.isNull():
        return None
    return QtGui.QPixmap.fromImage(image)


def render_project_cover(
        project: Project,
        size: QtCore.QSize = COVER_FULL_SIZE) -> QtGui.QPixmap:
    surface = _color_from_palette(
        project.palette,
        "surface",
        DEFAULT_PALETTE["surface"])
    primary = _color_from_palette(
        project.palette,
        "primary",
        DEFAULT_PALETTE["primary"])
    text_color = _color_from_palette(
        project.palette, "text", DEFAULT_PALETTE["text"])
    pixmap = QtGui.QPixmap(size)
    pixmap.fill(surface)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
    margin = int(min(size.width(), size.height()) * 0.06)
    hero_height = int(size.height() * 0.55)
    hero_rect = QtCore.QRectF(
        margin,
        margin,
        size.width() -
        margin *
        2,
        hero_height)
    hero_path = QtGui.QPainterPath()
    radius = min(hero_rect.width(), hero_rect.height()) * 0.06
    hero_path.addRoundedRect(hero_rect, radius, radius)
    gradient = QtGui.QLinearGradient(
        hero_rect.topLeft(),
        hero_rect.bottomRight())
    grad_primary = QtGui.QColor(primary)
    grad_primary.setAlphaF(0.85)
    gradient.setColorAt(0.0, grad_primary)
    mix = QtGui.QColor(surface)
    mix.setAlphaF(0.92)
    gradient.setColorAt(1.0, mix)
    painter.fillPath(hero_path, gradient)
    overlay = QtGui.QColor(primary)
    overlay.setAlpha(35)
    painter.fillPath(hero_path, overlay)
    painter.setPen(QtGui.QPen(QtGui.QColor(primary), 1.2))
    painter.drawPath(hero_path)

    content_margin = 48
    text_width = hero_rect.width() * 0.55
    text_rect = QtCore.QRectF(
        hero_rect.left() + content_margin,
        hero_rect.top() + content_margin,
        text_width - content_margin,
        hero_rect.height() - content_margin * 2,
    )
    heading_font = QtGui.QFont(
        _primary_font(
            project.fonts.get(
                "heading",
                DEFAULT_FONTS["heading"]),
            "Poppins"))
    heading_font.setBold(True)
    heading_font.setPointSizeF(max(28.0, size.width() / 28))
    eyebrow_font = QtGui.QFont(
        _primary_font(
            project.fonts.get(
                "body",
                DEFAULT_FONTS["body"]),
            "Inter"))
    eyebrow_font.setPointSizeF(max(13.0, size.width() / 55))
    eyebrow_font.setLetterSpacing(
        QtGui.QFont.SpacingType.PercentageSpacing, 108)
    eyebrow_font.setCapitalization(QtGui.QFont.Capitalization.AllUppercase)
    body_font = QtGui.QFont(
        _primary_font(
            project.fonts.get(
                "body",
                DEFAULT_FONTS["body"]),
            "Inter"))
    body_font.setPointSizeF(max(14.0, size.width() / 60))

    painter.save()
    painter.setPen(QtGui.QPen(primary))
    painter.setFont(eyebrow_font)
    painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft |
                     Qt.AlignmentFlag.AlignTop, "Launch-ready")

    painter.setPen(QtGui.QPen(text_color))
    painter.setFont(heading_font)
    title_rect = QtCore.QRectF(
        text_rect.left(),
        text_rect.top() + 32,
        text_rect.width(),
        text_rect.height())
    painter.drawText(
        title_rect,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        project.name.strip() or "Untitled")

    tagline = _extract_tagline(project)
    painter.setFont(body_font)
    tagline_rect = QtCore.QRectF(
        text_rect.left(),
        title_rect.top() + heading_font.pointSizeF() * 1.8,
        text_rect.width(),
        text_rect.height() - heading_font.pointSizeF() * 1.8,
    )
    painter.drawText(tagline_rect, Qt.AlignmentFlag.AlignLeft |
                     Qt.TextFlag.TextWordWrap, tagline)

    chip_height = 36
    chip_spacing = 16
    chip_y = tagline_rect.top() + max(tagline_rect.height() * 0.4, 48)
    chip_rect_primary = QtCore.QRectF(
        text_rect.left(), chip_y, 160, chip_height)
    chip_rect_secondary = QtCore.QRectF(
        chip_rect_primary.right() +
        chip_spacing,
        chip_y,
        150,
        chip_height)
    cta_text_color = _contrast_text_for(primary)

    def draw_chip(
            rect: QtCore.QRectF,
            bg: QtGui.QColor,
            fg: QtGui.QColor,
            label: str) -> None:
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, chip_height / 2, chip_height / 2)
        painter.fillPath(path, bg)
        painter.setPen(QtGui.QPen(QtGui.QColor(bg).darker(115)
                       if fg == cta_text_color else fg))
        painter.setFont(QtGui.QFont(body_font.family(),
                        int(max(12.0, size.width() / 70))))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    draw_chip(chip_rect_primary, primary, cta_text_color, "Get started")
    ghost_bg = QtGui.QColor(surface)
    ghost_bg = ghost_bg.darker(110)
    ghost_bg.setAlpha(90)
    ghost_text = QtGui.QColor(text_color)
    ghost_text.setAlpha(230)
    draw_chip(chip_rect_secondary, ghost_bg, ghost_text, "Preview")
    painter.restore()

    painter.save()
    image_pix = _project_cover_asset(project)
    if image_pix is not None:
        art_width = hero_rect.width() - text_width - content_margin
        art_rect = QtCore.QRectF(
            hero_rect.left() + text_width + content_margin * 0.4,
            hero_rect.top() + content_margin,
            art_width - content_margin,
            hero_rect.height() - content_margin * 2,
        )
        art_path = QtGui.QPainterPath()
        art_path.addRoundedRect(art_rect, 28, 28)
        painter.setClipPath(art_path)
        scaled = image_pix.scaled(
            art_rect.size().toSize(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation)
        target = QtCore.QRectF(
            art_rect.center().x() - scaled.width() / 2,
            art_rect.center().y() - scaled.height() / 2,
            scaled.width(),
            scaled.height(),
        )
        painter.drawPixmap(target.toRect(), scaled)
        painter.setClipping(False)
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 25), 2))
        painter.drawPath(art_path)
        painter.restore()

    cards_top = hero_rect.bottom() + margin * 0.6
    card_area_height = size.height() - cards_top - margin
    if card_area_height > 0:
        cards_rect = QtCore.QRectF(
            hero_rect.left(),
            cards_top,
            hero_rect.width(),
            card_area_height)
        card_spacing = 20
        card_width = (cards_rect.width() - card_spacing * 2) / 3
        card_titles = _collect_card_titles(project)
        for idx, title in enumerate(card_titles):
            card_rect = QtCore.QRectF(
                cards_rect.left() + idx * (card_width + card_spacing),
                cards_rect.top(),
                card_width,
                cards_rect.height() * 0.85,
            )
            card_path = QtGui.QPainterPath()
            card_path.addRoundedRect(card_rect, 24, 24)
            card_bg = QtGui.QColor(surface)
            card_bg = card_bg.lighter(103 + idx * 4)
            painter.fillPath(card_path, card_bg)
            painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 18)))
            painter.drawPath(card_path)
            painter.setPen(QtGui.QPen(text_color))
            painter.setFont(QtGui.QFont(heading_font.family(),
                            int(max(14.0, size.width() / 55))))
            heading_rect = QtCore.QRectF(
                card_rect.left() + 20,
                card_rect.top() + 18,
                card_rect.width() - 40,
                40,
            )
            painter.drawText(
                heading_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                title)
            painter.setFont(QtGui.QFont(body_font.family(),
                            int(max(12.0, size.width() / 70))))
            body_rect = QtCore.QRectF(
                heading_rect.left(),
                heading_rect.bottom() + 12,
                heading_rect.width(),
                card_rect.height() - 80,
            )
            sample = [
                "Launch new sections quickly with curated blocks.",
                "Showcase wins and social proof with ease.",
                "Keep visitors moving with confident calls to action.",
            ]
            painter.drawText(
                body_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                sample[idx % len(sample)],
            )

    painter.end()
    return pixmap


def _cover_base_key(project_path_or_temp: Optional[Path]) -> str:
    if project_path_or_temp is None:
        return f"temp-{uuid.uuid4().hex}"
    path = Path(project_path_or_temp)
    if path.suffix.lower() == ".png" and path.parent == COVERS_DIR:
        stem = path.stem
        if stem.endswith("-cover"):
            return stem[:-6]
        return stem
    try:
        resolved = path.resolve()
    except Exception:
        resolved = path
    return f"{abs(hash(str(resolved))):x}"


def save_cover_png(
        pixmap: QtGui.QPixmap,
        project_path_or_temp: Optional[Path]) -> Path:
    base_key = _cover_base_key(project_path_or_temp)
    cover_path = COVERS_DIR / f"{base_key}-cover.png"
    tile_path = PREVIEWS_DIR / f"{base_key}-tile.png"
    pixmap.save(str(cover_path), "PNG")
    tile = pixmap.scaled(COVER_TILE_SIZE,
                         Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                         Qt.TransformationMode.SmoothTransformation)
    tile.save(str(tile_path), "PNG")
    return cover_path


def cover_tile_path_from_cover(cover_path: Path) -> Path:
    base_key = _cover_base_key(cover_path)
    return PREVIEWS_DIR / f"{base_key}-tile.png"


def get_cover_or_thumbnail(
        project: Project,
        project_path: Optional[Path] = None) -> Optional[Path]:
    if project.cover_path and Path(project.cover_path).exists():
        return Path(project.cover_path)
    if project.cover_tile_path and Path(project.cover_tile_path).exists():
        return Path(project.cover_tile_path)
    if project_path:
        key = _cover_base_key(project_path)
        cover_candidate = COVERS_DIR / f"{key}-cover.png"
        if cover_candidate.exists():
            return cover_candidate
        tile_candidate = PREVIEWS_DIR / f"{key}-tile.png"
        if tile_candidate.exists():
            return tile_candidate
    return None


DEFAULT_TEMPLATE_COVER_CSS = """
body {
  margin: 0;
  background: var(--color-surface);
  color: var(--color-text);
  font-family: var(--font-body);
}
.template-cover {
  min-height: 100vh;
  padding: 32px;
  display: flex;
  justify-content: center;
  align-items: center;
}
.template-cover > * {
  width: min(1180px, 100%);
  margin: auto;
}
"""

DEFAULT_TEMPLATE_COVER_HTML = """
<div class=\"cover-root\">
  <section style=\"padding:48px;border-radius:24px;background:rgba(37,99,235,0.12);text-align:center;\">
    <h1 style=\"font-family:var(--font-heading);font-size:3rem;margin-bottom:12px;\">{{SITE_NAME}}</h1>
    <p style=\"font-size:1.1rem;max-width:560px;margin:0 auto 24px;\">Choose a template to see its curated preview.</p>
    <div style=\"display:inline-flex;gap:16px;\">
      <span style=\"padding:12px 22px;border-radius:999px;background:var(--color-primary);color:#fff;font-weight:600;\">Primary action</span>
      <span style=\"padding:12px 22px;border-radius:999px;background:rgba(15,23,42,0.08);font-weight:600;\">Secondary</span>
    </div>
  </section>
</div>
"""


def template_preview_html(
    template_key: str,
    project_name: str,
    palette: Dict[str, str],
    fonts: Dict[str, str],
) -> str:
    spec = PROJECT_TEMPLATES.get(template_key, PROJECT_TEMPLATES["starter"])
    html = (spec.cover_html or DEFAULT_TEMPLATE_COVER_HTML).replace(
        "{{SITE_NAME}}", project_name or spec.name)
    css = DEFAULT_TEMPLATE_COVER_CSS + (spec.cover_css or "")
    primary = palette.get("primary", DEFAULT_PALETTE["primary"])
    surface = palette.get("surface", DEFAULT_PALETTE["surface"])
    text = palette.get("text", DEFAULT_PALETTE["text"])
    heading_font = fonts.get("heading", DEFAULT_FONTS["heading"])
    body_font = fonts.get("body", DEFAULT_FONTS["body"])
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>{
        spec.name} preview</title><style>:root {{ --color-primary: {primary}; --color-surface: {surface}; --color-text: {text}; --font-heading: {heading_font}; --font-body: {body_font}; }} {css}</style></head><body class='template-cover'>{html}</body></html>"""


def preview_project_for_template(
        template_key: str,
        project_name: Optional[str] = None,
        palette: Optional[Dict[str, str]] = None,
        fonts: Optional[Dict[str, str]] = None) -> Project:
    spec = PROJECT_TEMPLATES.get(template_key, PROJECT_TEMPLATES["starter"])
    pages = [
        Page(
            filename=filename,
            title=title,
            html=html.replace(
                "{{SITE_NAME}}",
                project_name or spec.name))
        for filename, title, html in spec.pages[:1]
    ]
    # Prefer wizard's palette/fonts, then template, then global defaults
    palette = dict(palette or spec.palette or DEFAULT_PALETTE)
    fonts = dict(fonts or spec.fonts or DEFAULT_FONTS)
    project = Project(
        name=project_name or spec.name,
        pages=pages,
        css=spec.extra_css or "",
        palette=palette,
        fonts=fonts,
        template_key=template_key,
    )
    return project


_TEMPLATE_COVER_CACHE: Dict[str, QtGui.QPixmap] = {}
_TEMPLATE_COVER_SIZE_CACHE: Dict[Tuple[str, int, int], QtGui.QPixmap] = {}


def template_cover_pixmap(
    key: str,
    size: QtCore.QSize = QtCore.QSize(
        360,
        200)) -> QtGui.QPixmap:
    """Return a cached cover pixmap for template tiles and previews."""

    if size.isValid() is False or size.width() <= 0 or size.height() <= 0:
        size = QtCore.QSize(360, 200)
    dims = (size.width(), size.height())
    cache_key = (key, dims[0], dims[1])
    cached = _TEMPLATE_COVER_SIZE_CACHE.get(cache_key)
    if cached is not None and not cached.isNull():
        return cached.copy()

    base = _TEMPLATE_COVER_CACHE.get(key)
    if base is None or base.isNull():
        definition = TEMPLATES.get(key)
        fallback_name = definition.title if definition else PROJECT_TEMPLATES.get(
            key, PROJECT_TEMPLATES["starter"]).name
        project = preview_project_for_template(key, fallback_name)
        base = render_project_cover(project, COVER_FULL_SIZE)
        _TEMPLATE_COVER_CACHE[key] = base

    if dims == (base.width(), base.height()):
        _TEMPLATE_COVER_SIZE_CACHE[cache_key] = base
        return base.copy()

    scaled = base.scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    _TEMPLATE_COVER_SIZE_CACHE[cache_key] = scaled
    return scaled.copy()


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
  {% for asset in external_css %}
  <link rel=\"stylesheet\" href=\"{{ asset.href | e }}\"{% if asset.sri %} integrity=\"{{ asset.sri | e }}\" crossorigin=\"anonymous\"{% endif %}>
  {% endfor %}
  <link rel=\"stylesheet\" href=\"assets/css/style.css\">
  <style>
    :root {
      --color-primary: {{ color_primary }};
      --color-surface: {{ color_surface }};
      --color-text: {{ color_text }};
      --font-heading: {{ heading_font | safe }};
      --font-body: {{ body_font | safe }};
    }
  </style>
</head>
<body class=\"main-container{% if page_slug %} page-{{ page_slug }}{% endif %}\">
  {{ content | safe }}
  {% for asset in external_js %}
  <script src=\"{{ asset.href | e }}\"{% if asset.sri %} integrity=\"{{ asset.sri | e }}\" crossorigin=\"anonymous\"{% endif %}></script>
  {% endfor %}
  {% if use_scroll_js %}<script src=\"assets/js/site.js\" defer></script>{% endif %}
  <script src=\"assets/js/main.js\"{% if not include_js %} defer hidden{% endif %}></script>
</body>
</html>
"""


def build_base_css(
    palette: Dict[str, str],
    fonts: Dict[str, str],
    radius_scale: float = 1.0,
    shadow_level: str = "md",
) -> str:
    primary = palette.get("primary", DEFAULT_PALETTE["primary"])
    surface = palette.get("surface", DEFAULT_PALETTE["surface"])
    text = palette.get("text", DEFAULT_PALETTE["text"])
    heading_font = fonts.get("heading", DEFAULT_FONTS["heading"])
    body_font = fonts.get("body", DEFAULT_FONTS["body"])
    radius_scale_str = f"{radius_scale:g}" if radius_scale else "1"
    level = shadow_level if shadow_level in {
        "none", "sm", "md", "lg"} else "md"
    return f""":root {{
  --color-primary: {primary};
  --color-surface: {surface};
  --color-text: {text};
  --font-heading: {heading_font};
  --font-body: {body_font};
  --radius: calc(.6rem * {radius_scale_str});
  --shadow-none: none;
  --shadow-sm: 0 16px 32px rgba(15,23,42,.08);
  --shadow-md: 0 30px 60px rgba(15,23,42,.16);
  --shadow-lg: 0 40px 80px rgba(15,23,42,.22);
}}
body {{
  font-family: var(--font-body);
  background: var(--color-surface);
  color: var(--color-text);
  margin: 0;
  line-height: 1.6;
}}
h1, h2, h3, h4, h5 {{
  font-family: var(--font-heading);
  color: var(--color-text);
  line-height: 1.2;
}}
a {{
  color: var(--color-primary);
}}
.shadow {{ box-shadow: var(--shadow-{level}); }}
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


def generate_base_css(
    palette: Dict[str, str],
    fonts: Dict[str, str],
    radius_scale: float = 1.0,
    shadow_level: str = "md",
) -> str:
    """Compatibility wrapper to build the base CSS from palette and fonts."""

    return build_base_css(palette, fonts, radius_scale, shadow_level)


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
        output_dir=str(data.get("output_dir")) if data.get(
            "output_dir") is not None else None,
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
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False),
        encoding="utf-8")


def render_site(project: Project, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    css_dir = assets_dir / "css"
    img_dir = assets_dir / "images"
    js_dir = assets_dir / "js"
    vendor_dir = assets_dir / "vendor"
    css_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)
    if vendor_dir.exists():
        shutil.rmtree(vendor_dir)
    external_css_payload: List[Dict[str, str]] = []
    external_js_payload: List[Dict[str, str]] = []
    css_source = project.css or ""
    css = ensure_block(css_source, CSS_HELPERS_SENTINEL, CSS_HELPERS_BLOCK)
    css = ensure_block(css, BG_HELPERS_SENTINEL, BG_HELPERS_BLOCK)
    css = ensure_block(
        css,
        GRADIENT_HELPERS_SENTINEL,
        gradient_helpers_block(
            project.gradients))
    css = ensure_block(
        css,
        ANIM_HELPERS_SENTINEL,
        animation_helpers_block(
            project.motion_pref))
    extra_block = extract_css_block(css_source, TEMPLATE_EXTRA_SENTINEL)
    if extra_block:
        css = ensure_block(
            css,
            TEMPLATE_EXTRA_SENTINEL,
            f"{TEMPLATE_EXTRA_SENTINEL}\n{extra_block}")
    (css_dir / "style.css").write_text(css, encoding="utf-8")
    for asset in project.images:
        data = base64.b64decode(asset.data_base64.encode("ascii"))
        (img_dir / asset.name).write_bytes(data)
    for asset in project.external:
        href_value = asset.href
        rel_path: Optional[Path] = None
        if asset.mode == "local":
            rel_path = Path(asset.href)
            if rel_path.is_absolute(
            ) or not rel_path.parts or rel_path.parts[0] != "assets":
                rel_path = Path("assets") / "vendor" / rel_path.name
            if not rel_path.name:
                fallback_base = slugify(
                    asset.original_url or asset.href or f"{
                        asset.kind}-asset")
                fallback_name = f"{
                    fallback_base or 'external'}{
                    '.css' if asset.kind == 'css' else '.js'}"
                rel_path = Path("assets") / "vendor" / fallback_name
            href_value = rel_path.as_posix()
            if href_value != asset.href:
                asset.href = href_value
        if asset.kind == "css":
            payload: Dict[str, str] = {"href": href_value}
            if asset.sri:
                payload["sri"] = asset.sri
            external_css_payload.append(payload)
        elif asset.kind == "js":
            payload = {"href": href_value}
            if asset.sri:
                payload["sri"] = asset.sri
            external_js_payload.append(payload)
        if asset.mode == "local" and asset.data_base64 and rel_path is not None:
            target = output_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                blob = base64.b64decode(asset.data_base64.encode("ascii"))
            except Exception:
                blob = b""
            if blob:
                target.write_bytes(blob)
    js_needed = project.use_main_js or project.use_scroll_animations
    if js_needed:
        js_dir.mkdir(parents=True, exist_ok=True)
        main_js_path = js_dir / "main.js"
        site_js_path = js_dir / "site.js"
        if project.use_main_js:
            main_js_path.write_text(MAIN_JS_SNIPPET, encoding="utf-8")
        elif main_js_path.exists():
            main_js_path.unlink()
        if project.use_scroll_animations:
            site_js_path.write_text(SCROLL_JS_SNIPPET, encoding="utf-8")
        elif site_js_path.exists():
            site_js_path.unlink()
    elif js_dir.exists():
        shutil.rmtree(js_dir)
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
            use_scroll_js=project.use_scroll_animations,
            page_slug=slugify(Path(page.filename).stem),
            external_css=external_css_payload,
            external_js=external_js_payload,
            color_primary=project.palette.get(
                "primary", DEFAULT_PALETTE["primary"]),
            color_surface=project.palette.get(
                "surface", DEFAULT_PALETTE["surface"]),
            color_text=project.palette.get("text", DEFAULT_PALETTE["text"]),
            heading_font=project.fonts.get(
                "heading", DEFAULT_FONTS["heading"]),
            body_font=project.fonts.get("body", DEFAULT_FONTS["body"]),
        )
        (output_dir / page.filename).write_text(html, encoding="utf-8")


def render_project(project: Project, output_dir: Path) -> None:
    render_site(project, output_dir)

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
    cover: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "name": self.name,
            "last_opened": self.last_opened,
            "pinned": self.pinned,
            "thumbnail": self.thumbnail,
            "cover": self.cover,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "RecentItem":
        return cls(
            path=str(data.get("path", "")),
            name=str(data.get("name", "Untitled")),
            last_opened=str(
                data.get(
                    "last_opened",
                    datetime.utcnow().isoformat())),
            pinned=bool(data.get("pinned", False)),
            thumbnail=(str(data["thumbnail"])
                       if data.get("thumbnail") else None),
            cover=(str(data["cover"]) if data.get("cover") else None),
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
        self._items.append(
            RecentItem(
                path=path_str,
                name=project.name,
                last_opened=now))
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

    def set_cover(self, path: Path, cover_path: Path, *,
                  tile_path: Optional[Path] = None) -> None:
        for item in self._items:
            if item.path == str(path):
                item.cover = str(cover_path)
                if tile_path is not None:
                    item.thumbnail = str(tile_path)
                break
        self.save()


def write_project_thumbnail(project: Project,
                            project_path: Optional[Path]) -> Optional[Path]:
    base_reference: Optional[Path]
    if project_path is None and project.cover_path:
        base_reference = Path(project.cover_path)
    else:
        base_reference = project_path
    pixmap = render_project_cover(project, COVER_FULL_SIZE)
    cover_path = save_cover_png(pixmap, base_reference)
    tile_path = cover_tile_path_from_cover(cover_path)
    project.cover_path = str(cover_path)
    project.cover_tile_path = str(tile_path)
    project.cover_updated_utc = datetime.utcnow().isoformat()
    return tile_path

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
    def __init__(self, text: str,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setMinimumHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        font = self.font()
        font.setPointSize(12)
        self.setFont(font)


class TemplatePreviewDialog(QtWidgets.QDialog):
    def __init__(self, title: str,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        ensure_app_icon(self)
        self.setWindowTitle(f"{title} preview")
        self.resize(960, 640)
        layout = QtWidgets.QVBoxLayout(self)
        self.view = QWebEngineView(self)
        layout.addWidget(self.view, 1)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def set_preview_html(self, html: str) -> None:
        self.view.setHtml(html)


@dataclass
class TemplateSelectionResult:
    template_key: str
    project_name: str
    palette: Dict[str, str]
    fonts: Dict[str, str]
    theme: str


class TemplateSelectDialog(QtWidgets.QDialog):
    def __init__(self,
                 parent: Optional[QtWidgets.QWidget] = None,
                 templates: Dict[str,
                                 TemplateSpec] | None = None) -> None:
        super().__init__(parent)
        ensure_app_icon(self)
        self.setWindowTitle("Start a new project")
        self.resize(1100, 720)
        self._templates = templates or PROJECT_TEMPLATES
        self._template_order = [
            key for key in self._templates.keys() if key in PROJECT_TEMPLATES]
        if not self._template_order:
            self._template_order = ["starter"]
        self._template_cards: Dict[str, TemplateCard] = {}
        default_key = "starter" if "starter" in self._template_order else self._template_order[
            0]
        self._selected_key = default_key

        layout = QtWidgets.QVBoxLayout(self)
        form_group = QtWidgets.QGroupBox("Project details", self)
        form_layout = QtWidgets.QFormLayout(form_group)
        self.name_edit = QtWidgets.QLineEdit("My Site", form_group)
        form_layout.addRow("Name", self.name_edit)
        self.theme_combo = QtWidgets.QComboBox(form_group)
        self.theme_combo.addItems(list(THEME_PRESETS.keys()))
        form_layout.addRow("Theme", self.theme_combo)
        self.primary_edit = QtWidgets.QLineEdit(form_group)
        self.surface_edit = QtWidgets.QLineEdit(form_group)
        self.text_edit = QtWidgets.QLineEdit(form_group)
        color_row = QtWidgets.QHBoxLayout()
        color_row.addWidget(QtWidgets.QLabel("Primary"))
        color_row.addWidget(self.primary_edit)
        color_row.addWidget(QtWidgets.QLabel("Surface"))
        color_row.addWidget(self.surface_edit)
        color_row.addWidget(QtWidgets.QLabel("Text"))
        color_row.addWidget(self.text_edit)
        form_layout.addRow("Palette", color_row)
        self.heading_combo = QtWidgets.QComboBox(form_group)
        self.heading_combo.addItems(FONT_STACKS)
        self.body_combo = QtWidgets.QComboBox(form_group)
        self.body_combo.addItems(FONT_STACKS)
        font_row = QtWidgets.QHBoxLayout()
        font_row.addWidget(QtWidgets.QLabel("Heading"))
        font_row.addWidget(self.heading_combo)
        font_row.addWidget(QtWidgets.QLabel("Body"))
        font_row.addWidget(self.body_combo)
        form_layout.addRow("Fonts", font_row)
        layout.addWidget(form_group)

        splitter = QtWidgets.QSplitter(Qt.Orientation.Horizontal, self)
        layout.addWidget(splitter, 1)

        tiles_container = QtWidgets.QWidget(splitter)
        tiles_layout = QtWidgets.QVBoxLayout(tiles_container)
        tiles_layout.setContentsMargins(0, 0, 0, 0)
        tiles_layout.setSpacing(12)
        tiles_layout.addWidget(QtWidgets.QLabel("Templates"))
        cards_scroll = QtWidgets.QScrollArea(tiles_container)
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cards_widget = QtWidgets.QWidget(cards_scroll)
        cards_layout = QtWidgets.QVBoxLayout(cards_widget)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(12)
        for key in self._template_order:
            definition = TEMPLATES.get(key)
            if definition is None:
                spec = self._templates.get(key, PROJECT_TEMPLATES["starter"])
                definition = TemplateDefinition(
                    key=key,
                    title=spec.name,
                    description=spec.description,
                    default_pages=[(filename, html)
                                   for filename, _, html in spec.pages],
                    cover_html=spec.cover_html,
                    cover_css=spec.cover_css,
                )
            pix = template_cover_pixmap(key, QtCore.QSize(360, 200))
            card = TemplateCard(definition, cards_widget, preview_pixmap=pix)
            card.clicked.connect(self._select_card)
            card.preview_requested.connect(self._show_preview_dialog)
            cards_layout.addWidget(card)
            self._template_cards[key] = card
        cards_layout.addStretch(1)
        cards_scroll.setWidget(cards_widget)
        tiles_layout.addWidget(cards_scroll, 1)
        splitter.addWidget(tiles_container)

        preview_container = QtWidgets.QWidget(splitter)
        preview_layout = QtWidgets.QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(QtWidgets.QLabel("Live preview"))
        self.preview_view = QWebEngineView(preview_container)
        preview_layout.addWidget(self.preview_view, 1)
        splitter.addWidget(preview_container)
        splitter.setSizes([380, 700])

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.theme_combo.currentTextChanged.connect(self._apply_theme_palette)
        for edit in (self.primary_edit, self.surface_edit, self.text_edit):
            edit.textChanged.connect(self._update_preview)
        self.heading_combo.currentTextChanged.connect(self._update_preview)
        self.body_combo.currentTextChanged.connect(self._update_preview)
        self.name_edit.textChanged.connect(self._update_preview)

        self._apply_theme_palette(self.theme_combo.currentText())
        self._highlight_selected_card()
        self._update_preview()

    def _select_card(self, key: str) -> None:
        if key not in self._template_cards:
            return
        self._selected_key = key
        self._highlight_selected_card()
        self._update_preview()

    def _highlight_selected_card(self) -> None:
        for key, card in self._template_cards.items():
            card.setStyleSheet(
                "border: 2px solid #2563eb; border-radius: 12px;" if key == self._selected_key else "")

    def _apply_theme_palette(self, theme: str) -> None:
        palette = THEME_PRESETS.get(theme, DEFAULT_PALETTE)
        self.primary_edit.setText(
            palette.get(
                "primary",
                DEFAULT_PALETTE["primary"]))
        self.surface_edit.setText(
            palette.get(
                "surface",
                DEFAULT_PALETTE["surface"]))
        self.text_edit.setText(palette.get("text", DEFAULT_PALETTE["text"]))
        self._update_preview()

    def _update_preview(self) -> None:
        palette = {
            "primary": self.primary_edit.text().strip() or DEFAULT_PALETTE["primary"],
            "surface": self.surface_edit.text().strip() or DEFAULT_PALETTE["surface"],
            "text": self.text_edit.text().strip() or DEFAULT_PALETTE["text"],
        }
        fonts = {
            "heading": self.heading_combo.currentText(),
            "body": self.body_combo.currentText()}
        definition = TEMPLATES.get(self._selected_key)
        fallback_title = definition.title if definition else self._templates.get(
            self._selected_key, PROJECT_TEMPLATES["starter"]).name
        name = self.name_edit.text().strip() or fallback_title
        html = template_preview_html(self._selected_key, name, palette, fonts)
        self.preview_view.setHtml(html)

    def _show_preview_dialog(self, key: str) -> None:
        palette = {
            "primary": self.primary_edit.text().strip() or DEFAULT_PALETTE["primary"],
            "surface": self.surface_edit.text().strip() or DEFAULT_PALETTE["surface"],
            "text": self.text_edit.text().strip() or DEFAULT_PALETTE["text"],
        }
        fonts = {
            "heading": self.heading_combo.currentText(),
            "body": self.body_combo.currentText()}
        definition = TEMPLATES.get(key)
        fallback_title = definition.title if definition else self._templates.get(
            key, PROJECT_TEMPLATES["starter"]).name
        name = self.name_edit.text().strip() or fallback_title
        html = template_preview_html(key, name, palette, fonts)
        dialog = TemplatePreviewDialog(fallback_title, self)
        dialog.set_preview_html(html)
        dialog.exec()

    def result(self) -> Optional[TemplateSelectionResult]:
        if self._selected_key not in self._template_cards:
            return None
        palette = {
            "primary": self.primary_edit.text().strip() or DEFAULT_PALETTE["primary"],
            "surface": self.surface_edit.text().strip() or DEFAULT_PALETTE["surface"],
            "text": self.text_edit.text().strip() or DEFAULT_PALETTE["text"],
        }
        fonts = {
            "heading": self.heading_combo.currentText(),
            "body": self.body_combo.currentText()}
        definition = TEMPLATES.get(self._selected_key)
        fallback_title = definition.title if definition else self._templates.get(
            self._selected_key, PROJECT_TEMPLATES["starter"]).name
        project_name = self.name_edit.text().strip() or fallback_title
        return TemplateSelectionResult(
            template_key=self._selected_key,
            project_name=project_name,
            palette=palette,
            fonts=fonts,
            theme=self.theme_combo.currentText(),
        )


class PageTemplateDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        page_types: Dict[str, Callable[[], str]] | None = None,
    ) -> None:
        super().__init__(parent)
        ensure_app_icon(self)
        self.setWindowTitle("Add Page")
        self._types = page_types or {}
        self._section_entries: List[Tuple[QtWidgets.QCheckBox, Callable[[], str]]] = [
        ]
        self._auto_title = ""
        self._title_custom = False
        self._suppress_title_signal = False

        form = QtWidgets.QFormLayout(self)
        self.title_edit = QtWidgets.QLineEdit(self)
        self.title_edit.textEdited.connect(self._on_title_edited)
        self.type_combo = QtWidgets.QComboBox(self)
        self.type_combo.addItems(list(self._types.keys()))
        form.addRow("Title", self.title_edit)
        form.addRow("Page type", self.type_combo)

        self.sections_group = QtWidgets.QGroupBox("Sections", self)
        self.sections_layout = QtWidgets.QVBoxLayout(self.sections_group)
        form.addRow(self.sections_group)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        initial_type = self.type_combo.currentText()
        self._on_type_changed(initial_type)

    def _on_type_changed(self, page_type: str) -> None:
        base_title = page_type.replace("Page", "").strip() or "Page"
        current_text = self.title_edit.text().strip()
        should_update = (
            not self._title_custom) or (
            not current_text) or (
            current_text == self._auto_title)
        self._auto_title = base_title
        if should_update:
            self._suppress_title_signal = True
            self.title_edit.setText(base_title)
            self._suppress_title_signal = False
            self._title_custom = False
        for checkbox, _ in self._section_entries:
            checkbox.deleteLater()
        self._section_entries = []
        while self.sections_layout.count():
            item = self.sections_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        entries = PAGE_TYPE_SECTIONS.get(page_type, [])
        self.sections_group.setVisible(bool(entries))
        for label, builder in entries:
            checkbox = QtWidgets.QCheckBox(label, self.sections_group)
            checkbox.setChecked(True)
            self.sections_layout.addWidget(checkbox)
            self._section_entries.append((checkbox, builder))

    def _on_title_edited(self, _text: str) -> None:
        if not self._suppress_title_signal:
            self._title_custom = True

    def _selected_sections(self) -> List[str]:
        html_parts: List[str] = []
        for checkbox, builder in self._section_entries:
            if checkbox.isChecked():
                html_parts.append(builder())
        return html_parts

    def build_html(self) -> str:
        selected = self._selected_sections()
        if selected:
            return "\n\n".join(selected)
        builder = self._types.get(self.type_combo.currentText())
        return builder() if builder else "<section><h2>New page</h2></section>"

    def result(self) -> Tuple[str, str, str]:
        title = self.title_edit.text().strip() or "Page"
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "page"
        filename = "index.html" if slug == "index" else f"{slug}.html"
        html = self.build_html()
        return title, filename, html


class TemplateCard(QtWidgets.QFrame):
    clicked = QtCore.pyqtSignal(str)
    preview_requested = QtCore.pyqtSignal(str)

    def __init__(
        self,
        template: TemplateDefinition,
        parent: Optional[QtWidgets.QWidget] = None,
        preview_pixmap: Optional[QtGui.QPixmap] = None,
    ) -> None:
        super().__init__(parent)
        self.template = template
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Raised)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"Template {template.title}")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.thumb = QtWidgets.QLabel(self)
        self.thumb.setFixedHeight(160)
        self.thumb.setScaledContents(True)
        layout.addWidget(self.thumb)

        self.preview_button = QtWidgets.QPushButton("Preview template", self)
        self.preview_button.setVisible(False)
        self.preview_button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.preview_button)

        title = QtWidgets.QLabel(f"<b>{template.title}</b>")
        title.setWordWrap(True)
        desc = QtWidgets.QLabel(template.description)
        desc.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addStretch()

        self.preview_button.clicked.connect(
            lambda: self.preview_requested.emit(
                self.template.key))
        self.update_preview_pixmap(preview_pixmap)

    def update_preview_pixmap(self, pixmap: Optional[QtGui.QPixmap]) -> None:
        if pixmap is None or pixmap.isNull():
            placeholder = QtGui.QPixmap(320, 160)
            placeholder.fill(QtGui.QColor("#dbeafe"))
            painter = QtGui.QPainter(placeholder)
            painter.setPen(QtGui.QPen(QtGui.QColor("#1d4ed8")))
            painter.drawRoundedRect(
                6,
                6,
                placeholder.width() -
                12,
                placeholder.height() -
                12,
                14,
                14)
            painter.setPen(QtGui.QColor("#1e293b"))
            painter.drawText(
                placeholder.rect(),
                Qt.AlignmentFlag.AlignCenter,
                self.template.title)
            painter.end()
            self.thumb.setPixmap(placeholder)
        else:
            self.thumb.setPixmap(
                pixmap.scaled(
                    self.thumb.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation))

    def enterEvent(self, event: QtGui.QEnterEvent) -> None:
        self.preview_button.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QtGui.QEnterEvent) -> None:
        self.preview_button.setVisible(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.template.key)
        super().mouseReleaseEvent(event)


class RecentTileList(QtWidgets.QListWidget):
    deleteRequested = QtCore.pyqtSignal(QtWidgets.QListWidgetItem)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.setResizeMode(QtWidgets.QListWidget.ResizeMode.Adjust)
        self.setMovement(QtWidgets.QListView.Movement.Static)
        self.setSpacing(18)
        self.setWordWrap(True)
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setIconSize(COVER_TILE_SIZE)
        self.setUniformItemSizes(False)
        self.setAlternatingRowColors(False)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            item = self.currentItem()
            if item is not None:
                self.deleteRequested.emit(item)
                return
        super().keyPressEvent(event)


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
            paths = [url.toLocalFile()
                     for url in mime.urls() if url.isLocalFile()]
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
        intro = QtWidgets.QLabel(
            "Answer a few quick questions and we'll pick a template, theme, and starter pages.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.purpose = self._create_group(
            "What are you making?", [
                "Landing", "Portfolio", "Resource", "Other"], layout)
        self.audience = self._create_group(
            "Who is it for?", ["Customers", "Hiring managers",
                               "Internal users", "Community"], layout
        )
        self.goal = self._create_group(
            "What's the goal?", [
                "Get signups", "Showcase work", "Provide help docs", "Share news"], layout
        )
        layout.addWidget(QtWidgets.QLabel("Short blurb (optional):"))
        self.blurb = QtWidgets.QPlainTextEdit(self)
        self.blurb.setPlaceholderText(
            "I need a simple site for my lawn service…")
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
        self._selected_template_key = "starter" if "starter" in PROJECT_TEMPLATES else next(
            iter(PROJECT_TEMPLATES))
        self.template_cards: Dict[str, TemplateCard] = {}
        self.template_preview: Optional[QWebEngineView] = None
        self.template_caption: Optional[QtWidgets.QLabel] = None

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
        self._highlight_template_cards()
        self._update_template_preview()

    # Step widgets ------------------------------------------------------
    def _build_describe(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(page)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.describe_purpose = QtWidgets.QComboBox(page)
        self.describe_purpose.addItems(
            ["Landing", "Portfolio", "Resource", "Other"])
        self.describe_audience = QtWidgets.QComboBox(page)
        self.describe_audience.addItems(
            ["Customers", "Hiring managers", "Internal users", "Community"])
        self.describe_goal = QtWidgets.QComboBox(page)
        self.describe_goal.addItems(
            ["Get signups", "Showcase work", "Provide help docs", "Share news"])
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
        helper = QtWidgets.QLabel(
            "Tip: the location should be an empty folder where we'll keep exports and previews.")
        helper.setWordWrap(True)
        layout.addRow(helper)
        last = self.settings.get("last_save_dir", str(Path.home()))
        self.describe_location.setText(last)
        self.describe_name.textChanged.connect(self._update_template_preview)
        return page

    def _build_template(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        list_container = QtWidgets.QWidget(page)
        list_layout = QtWidgets.QVBoxLayout(list_container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(12)
        list_layout.addWidget(QtWidgets.QLabel("Choose a template"))
        cards_scroll = QtWidgets.QScrollArea(list_container)
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cards_widget = QtWidgets.QWidget(cards_scroll)
        cards_layout = QtWidgets.QVBoxLayout(cards_widget)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(12)
        self.template_cards = {}
        for key, tmpl in TEMPLATES.items():
            pixmap = template_cover_pixmap(key, QtCore.QSize(320, 180))
            card = TemplateCard(tmpl, cards_widget, preview_pixmap=pixmap)
            card.clicked.connect(self._on_template_card_clicked)
            card.preview_requested.connect(self._show_template_modal)
            cards_layout.addWidget(card)
            self.template_cards[key] = card
        cards_layout.addStretch(1)
        cards_widget.setLayout(cards_layout)
        cards_scroll.setWidget(cards_widget)
        list_layout.addWidget(cards_scroll, 1)
        layout.addWidget(list_container, 1)

        preview_container = QtWidgets.QWidget(page)
        preview_layout = QtWidgets.QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(12)
        preview_layout.addWidget(QtWidgets.QLabel("Live preview"))
        self.template_preview = QWebEngineView(preview_container)
        preview_layout.addWidget(self.template_preview, 1)
        self.template_caption = QtWidgets.QLabel(
            "Select a template to see its hero styling and sections with your theme."
        )
        self.template_caption.setWordWrap(True)
        preview_layout.addWidget(self.template_caption)
        layout.addWidget(preview_container, 2)

        return page

    def _build_pages(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(QtWidgets.QLabel("Select pages"))
        self.page_checks: List[Tuple[QtWidgets.QCheckBox,
                                     QtWidgets.QLineEdit]] = []
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
        helper = QtWidgets.QLabel(
            "Home is required. Rename other pages to match your voice.")
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
        self.theme_combo.currentTextChanged.connect(
            lambda _: self._update_template_preview())
        self.heading_combo.currentTextChanged.connect(
            lambda _: self._update_template_preview())
        self.body_combo.currentTextChanged.connect(
            lambda _: self._update_template_preview())
        return page

    def _build_review(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(QtWidgets.QLabel("Review"))
        self.review_text = QtWidgets.QTextEdit(page)
        self.review_text.setReadOnly(True)
        layout.addWidget(self.review_text, 1)
        layout.addWidget(QtWidgets.QLabel(
            "Click Create project to open the editor."))
        return page

    def _highlight_template_cards(self) -> None:
        if not self.template_cards:
            return
        if self._selected_template_key not in self.template_cards:
            self._selected_template_key = next(iter(self.template_cards))
        for key, card in self.template_cards.items():
            card.setStyleSheet(
                "border: 2px solid #2563eb; border-radius: 12px;" if key == self._selected_template_key else "")

    def _current_palette(self) -> Dict[str, str]:
        theme_combo = getattr(self, "theme_combo", None)
        theme = theme_combo.currentText() if theme_combo is not None else "Calm Sky"
        return dict(THEME_PRESETS.get(theme, DEFAULT_PALETTE))

    def _current_fonts(self) -> Dict[str, str]:
        heading_combo = getattr(self, "heading_combo", None)
        body_combo = getattr(self, "body_combo", None)
        heading = heading_combo.currentText(
        ) if heading_combo is not None else DEFAULT_FONTS["heading"]
        body = body_combo.currentText(
        ) if body_combo is not None else DEFAULT_FONTS["body"]
        return {"heading": heading, "body": body}

    def _update_template_preview(self) -> None:
        if self.template_preview is None:
            return
        if self._selected_template_key not in PROJECT_TEMPLATES:
            self._selected_template_key = "starter"
        palette = self._current_palette()
        fonts = self._current_fonts()
        name_edit = getattr(self, "describe_name", None)
        project_name = name_edit.text().strip() if name_edit is not None else ""
        spec = PROJECT_TEMPLATES.get(
            self._selected_template_key,
            PROJECT_TEMPLATES["starter"])
        display_name = project_name or spec.name
        html = template_preview_html(
            self._selected_template_key,
            display_name,
            palette,
            fonts)
        self.template_preview.setHtml(html)
        if self.template_caption is not None:
            self.template_caption.setText(
                f"<b>{spec.name}</b> — {spec.description}")

    def _on_template_card_clicked(self, key: str) -> None:
        self._selected_template_key = key
        self._highlight_template_cards()
        self._update_template_preview()

    def _show_template_modal(self, key: str) -> None:
        palette = self._current_palette()
        fonts = self._current_fonts()
        spec = PROJECT_TEMPLATES.get(key, PROJECT_TEMPLATES["starter"])
        definition = TEMPLATES.get(key)
        title = definition.title if definition else spec.name
        name_edit = getattr(self, "describe_name", None)
        display_name = name_edit.text().strip() if name_edit is not None else ""
        html = template_preview_html(
            key, display_name or title, palette, fonts)
        dialog = TemplatePreviewDialog(title, self)
        dialog.set_preview_html(html)
        dialog.exec()

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
                QtWidgets.QMessageBox.warning(
                    self, "Missing name", "Please provide a project name.")
            return None, None
        location = self.describe_location.text().strip()
        if not location:
            if validate:
                QtWidgets.QMessageBox.warning(
                    self, "Missing location", "Choose where to save the project.")
            return None, None
        template_key = self._selected_template_key or "starter"
        if template_key not in PROJECT_TEMPLATES:
            template_key = "starter"
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
        path = Path(location) / f"{
            re.sub(
                r'[^a-zA-Z0-9_-]+',
                '-',
                name.lower()).strip('-') or 'site'}.siteproj"
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
    spec = PROJECT_TEMPLATES.get(template_key, PROJECT_TEMPLATES["starter"])
    palette_final = dict(spec.palette or palette)
    fonts_final = dict(spec.fonts or fonts)
    gradients = dict(spec.gradients or DEFAULT_GRADIENT)
    radius_scale = float(
        spec.radius_scale) if spec.radius_scale is not None else 1.0
    shadow_level = spec.shadow_level if spec.shadow_level in SHADOW_LEVELS else "md"

    pages: List[Page] = []
    spec_titles = {title: filename for filename, title, _ in spec.pages}
    existing_filenames: set[str] = set()

    for filename, default_title, html in spec.pages:
        title = page_titles.get(default_title, default_title)
        content = html.replace("{{SITE_NAME}}", name)
        if blurb and default_title.lower() == "home":
            content = re.sub(
                r"<p class=\"lead\">.*?</p>",
                f"<p class=\"lead\">{blurb}</p>",
                content,
                count=1,
            )
        pages.append(Page(filename=filename, title=title, html=content))
        existing_filenames.add(filename)

    for title in selected_pages:
        if title in spec_titles:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "page"
        filename = f"{slug}.html"
        counter = 1
        while filename in existing_filenames:
            filename = f"{slug}-{counter}.html"
            counter += 1
        body = (
            f"<section class=\"section\">\n  <h1>{
                page_titles.get(
                    title, title)}</h1>\n"
            "  <p>Write something helpful here.</p>\n</section>"
        )
        pages.append(
            Page(
                filename=filename,
                title=page_titles.get(
                    title,
                    title),
                html=body))
        existing_filenames.add(filename)

    css = generate_base_css(
        palette_final,
        fonts_final,
        radius_scale,
        shadow_level)
    if spec.include_helpers:
        css = ensure_block(css, CSS_HELPERS_SENTINEL, CSS_HELPERS_BLOCK)
    css = ensure_block(css, BG_HELPERS_SENTINEL, BG_HELPERS_BLOCK)
    css = ensure_block(css, GRADIENT_HELPERS_SENTINEL,
                       gradient_helpers_block(gradients))
    css = ensure_block(css, ANIM_HELPERS_SENTINEL, animation_helpers_block())
    if spec.extra_css.strip():
        css = ensure_block(css, TEMPLATE_EXTRA_SENTINEL, spec.extra_css)

    project = Project(
        name=name,
        pages=pages,
        css=css,
        palette=palette_final,
        fonts=fonts_final,
        template_key=template_key,
        images=placeholder_images(),
        gradients=gradients,
        radius_scale=radius_scale,
        shadow_level=shadow_level,
    )
    project.theme_preset = next(
        (key for key, val in THEME_PRESETS.items() if val == palette_final), "Custom")
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
            AssetImage(
                name=name,
                data_base64=data,
                width=pix.width(),
                height=pix.height(),
                mime="image/png")
        )
    return images


def generate_svg_placeholder(
        width: int, height: int, palette: Dict[str, str]) -> str:
    primary = palette.get("primary", DEFAULT_PALETTE["primary"])
    surface = palette.get("surface", DEFAULT_PALETTE["surface"])
    text = palette.get("text", DEFAULT_PALETTE["text"])
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>"
        f"<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
        f"<stop offset='0%' stop-color='{primary}' stop-opacity='0.85'/><stop offset='100%' stop-color='{primary}' stop-opacity='0.35'/></linearGradient></defs>"
        f"<rect width='100%' height='100%' fill='{surface}'/><rect x='{
            width *
            0.05}' y='{
            height *
            0.1}' rx='{
            width *
            0.04}' ry='{
                width *
                0.04}' width='{
                    width *
                    0.9}' height='{
                        height *
            0.8}' fill='url(#g)' opacity='0.65'/>"
        f"<rect x='{
            width *
            0.08}' y='{
            height *
            0.18}' width='{
            width *
            0.35}' height='{
                height *
                0.05}' rx='{
                    height *
            0.02}' fill='{primary}' opacity='0.35'/>"
        f"<rect x='{
            width *
            0.08}' y='{
            height *
            0.28}' width='{
            width *
            0.5}' height='{
                height *
                0.06}' rx='{
                    height *
            0.02}' fill='{primary}' opacity='0.28'/>"
        f"<rect x='{
            width *
            0.08}' y='{
            height *
            0.38}' width='{
            width *
            0.45}' height='{
                height *
                0.05}' rx='{
                    height *
            0.02}' fill='{primary}' opacity='0.18'/>"
        f"<text x='{
            width /
            2}' y='{
            height *
            0.65}' text-anchor='middle' fill='{text}' font-family='Inter, sans-serif' font-size='{
            max(
                18,
                width *
                0.04)}' font-weight='600' opacity='0.75'>Hero placeholder {width}×{height}</text>"
        "</svg>"
    )

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

        central = QtWidgets.QWidget(self)
        outer = QtWidgets.QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(central)

        self.nav_list = QtWidgets.QListWidget(central)
        self.nav_list.setFixedWidth(220)
        self.nav_list.setSpacing(4)
        self.nav_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
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
        outer = QtWidgets.QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        command_frame = QtWidgets.QFrame(page)
        command_frame.setFixedWidth(240)
        command_layout = QtWidgets.QVBoxLayout(command_frame)
        command_layout.setContentsMargins(24, 32, 24, 32)
        command_layout.setSpacing(12)
        command_layout.addWidget(QtWidgets.QLabel("<h2>Start</h2>"))
        self.btn_command_create = QtWidgets.QPushButton("Create New Project")
        self.btn_command_create.setMinimumHeight(44)
        self.btn_command_open = QtWidgets.QPushButton("Open…")
        self.btn_command_open.setMinimumHeight(40)
        self.btn_command_import = QtWidgets.QPushButton("Import Website…")
        self.btn_command_import.setMinimumHeight(40)
        command_layout.addWidget(self.btn_command_create)
        command_layout.addWidget(self.btn_command_open)
        command_layout.addWidget(self.btn_command_import)
        command_layout.addStretch()
        outer.addWidget(command_frame)

        scroll = QtWidgets.QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        content = QtWidgets.QWidget(scroll)
        scroll.setWidget(content)
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(24)

        title = QtWidgets.QLabel(
            "<h1>Welcome! Let's build something beautiful.</h1>")
        subtitle = QtWidgets.QLabel(
            "Pick a template, tune the theme, and jump into the builder with polished starter content."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        layout.addWidget(QtWidgets.QLabel("What are you making?"))
        self.quick_purpose = QtWidgets.QButtonGroup(self)
        purpose_row = QtWidgets.QHBoxLayout()
        radio_buttons = []
        for option in ["Landing", "Portfolio", "Resource", "Other"]:
            btn = QtWidgets.QRadioButton(option, content)
            btn.setMinimumHeight(36)
            self.quick_purpose.addButton(btn)
            radio_buttons.append((btn, option))
            purpose_row.addWidget(btn)
        if self.quick_purpose.buttons():
            self.quick_purpose.buttons()[0].setChecked(True)
        purpose_row.addStretch()
        layout.addLayout(purpose_row)
        for btn, option in radio_buttons:
            btn.toggled.connect(
                lambda checked,
                text=option: self._quick_purpose_changed(
                    text,
                    checked))

        form_group = QtWidgets.QGroupBox("Project details", content)
        form = QtWidgets.QFormLayout(form_group)
        self.create_name = QtWidgets.QLineEdit(form_group)
        self.create_name.setPlaceholderText("Project name")
        self.create_name.setText("My Site")
        self.create_location = QtWidgets.QLineEdit(form_group)
        self.create_location.setPlaceholderText(
            "Where to save the .siteproj file")
        self.create_location.setText(
            self.settings.get(
                "last_save_dir", str(
                    Path.home())))
        browse = QtWidgets.QPushButton("Browse…", form_group)
        browse.clicked.connect(self._browse_save_location)
        location_layout = QtWidgets.QHBoxLayout()
        location_layout.addWidget(self.create_location)
        location_layout.addWidget(browse)
        form.addRow("Project name", self.create_name)
        form.addRow("Save location", location_layout)
        layout.addWidget(form_group)

        recents_header = QtWidgets.QHBoxLayout()
        recents_header.addWidget(QtWidgets.QLabel("<h2>Recent projects</h2>"))
        self.btn_purge_tiles = QtWidgets.QPushButton("Remove missing")
        recents_header.addStretch()
        recents_header.addWidget(self.btn_purge_tiles)
        layout.addLayout(recents_header)

        self.recent_tiles = RecentTileList(content)
        self.recent_tiles.setIconSize(COVER_TILE_SIZE)
        layout.addWidget(self.recent_tiles)

        layout.addWidget(QtWidgets.QLabel("<h2>Template gallery</h2>"))
        gallery_scroll = QtWidgets.QScrollArea(content)
        gallery_scroll.setWidgetResizable(True)
        gallery_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        gallery_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        gallery_widget = QtWidgets.QWidget(gallery_scroll)
        self.template_gallery_layout = QtWidgets.QHBoxLayout(gallery_widget)
        self.template_gallery_layout.setContentsMargins(0, 0, 0, 0)
        self.template_gallery_layout.setSpacing(16)
        self.template_cards = {}
        for key, tmpl in TEMPLATES.items():
            pixmap = self._template_preview_pixmap(key)
            card = TemplateCard(tmpl, gallery_widget, preview_pixmap=pixmap)
            card.clicked.connect(self._on_template_selected)
            card.preview_requested.connect(self._show_template_preview)
            self.template_gallery_layout.addWidget(card)
            self.template_cards[key] = card
        self.template_gallery_layout.addStretch(1)
        gallery_scroll.setWidget(gallery_widget)
        layout.addWidget(gallery_scroll)

        self.template_caption = QtWidgets.QLabel(
            "Select a template to see details and update the live preview.")
        self.template_caption.setWordWrap(True)
        layout.addWidget(self.template_caption)

        pages_group = QtWidgets.QGroupBox("Add starter pages", content)
        pages_layout = QtWidgets.QGridLayout(pages_group)
        self._page_checks.clear()
        self._page_edits.clear()
        labels = [
            "About",
            "Projects",
            "Docs",
            "Contact",
            "Blog",
            "Pricing",
            "FAQ",
            "Updates"]
        for idx, label in enumerate(labels):
            check = QtWidgets.QCheckBox(label, pages_group)
            if label in ("About", "Contact"):
                check.setChecked(True)
            edit = QtWidgets.QLineEdit(label, pages_group)
            edit.setPlaceholderText(f"{label} title")
            edit.setMaximumWidth(180)
            self._page_checks[label] = check
            self._page_edits[label] = edit
            col = idx % 4
            row = idx // 4
            column = QtWidgets.QVBoxLayout()
            column.addWidget(check)
            column.addWidget(edit)
            container = QtWidgets.QWidget(pages_group)
            container.setLayout(column)
            pages_layout.addWidget(container, row, col)
        layout.addWidget(pages_group)

        theme_group = QtWidgets.QGroupBox("Theme & fonts", content)
        theme_layout = QtWidgets.QHBoxLayout(theme_group)
        self.create_theme = QtWidgets.QComboBox(theme_group)
        self.create_theme.addItems(list(THEME_PRESETS.keys()))
        self.create_theme.setCurrentText("Calm Sky")
        self.heading_font_combo = QtWidgets.QComboBox(theme_group)
        self.heading_font_combo.addItems(FONT_STACKS)
        self.body_font_combo = QtWidgets.QComboBox(theme_group)
        self.body_font_combo.addItems(FONT_STACKS)
        theme_layout.addWidget(QtWidgets.QLabel("Theme"))
        theme_layout.addWidget(self.create_theme)
        theme_layout.addWidget(QtWidgets.QLabel("Heading font"))
        theme_layout.addWidget(self.heading_font_combo)
        theme_layout.addWidget(QtWidgets.QLabel("Body font"))
        theme_layout.addWidget(self.body_font_combo)
        layout.addWidget(theme_group)

        self.create_summary = QtWidgets.QLabel(
            "Select a template, adjust options, and click Create to open the builder with rich starting pages."
        )
        self.create_summary.setWordWrap(True)
        layout.addWidget(self.create_summary)

        self.btn_create_project = QtWidgets.QPushButton(
            "Create project", content)
        self.btn_create_project.setMinimumHeight(44)
        self.btn_create_project.clicked.connect(self._create_project)
        layout.addWidget(self.btn_create_project)
        layout.addStretch()

        self.btn_command_create.clicked.connect(self._create_project)
        self.btn_command_open.clicked.connect(self._browse_open_file)
        self.btn_command_import.clicked.connect(self._browse_import_file)
        self.btn_purge_tiles.clicked.connect(self._purge_missing)
        self.recent_tiles.itemActivated.connect(self._open_recent_tile)
        self.recent_tiles.deleteRequested.connect(self._remove_recent_tile)

        self._on_template_selected(self._selected_template)
        return page

    def _template_preview_pixmap(self, key: str) -> QtGui.QPixmap:
        return template_cover_pixmap(key, COVER_TILE_SIZE)

    def _show_template_preview(self, key: str) -> None:
        spec = PROJECT_TEMPLATES.get(key, PROJECT_TEMPLATES["starter"])
        theme = self.create_theme.currentText() if hasattr(
            self, "create_theme") else "Calm Sky"
        palette = dict(
            THEME_PRESETS.get(
                theme,
                spec.palette or DEFAULT_PALETTE))
        fonts = {
            "heading": self.heading_font_combo.currentText() if hasattr(self, "heading_font_combo") else DEFAULT_FONTS["heading"],
            "body": self.body_font_combo.currentText() if hasattr(self, "body_font_combo") else DEFAULT_FONTS["body"],
        }
        name = self.create_name.text().strip() if hasattr(
            self, "create_name") else spec.name
        html = template_preview_html(key, name or spec.name, palette, fonts)
        dialog = TemplatePreviewDialog(TEMPLATES[key].title, self)
        dialog.set_preview_html(html)
        dialog.exec()

    def _open_recent_tile(self, item: QtWidgets.QListWidgetItem) -> None:
        path_str = str(item.data(Qt.ItemDataRole.UserRole))
        if not path_str:
            return
        path = Path(path_str)
        if not path.exists():
            QtWidgets.QMessageBox.warning(
                self, "Missing", "This project file is missing. Removing from list.")
            self.recents.remove(path_str)
            self.refresh_recents()
            return
        self._open_project_from_path(path)

    def _remove_recent_tile(self, item: QtWidgets.QListWidgetItem) -> None:
        path_str = str(item.data(Qt.ItemDataRole.UserRole))
        if not path_str:
            return
        self.recents.remove(path_str)
        self.refresh_recents()

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
        info = QtWidgets.QLabel(
            "Import Webineer v1 projects. We'll upgrade them safely to the new format.")
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
        self.import_summary.setPlaceholderText(
            "Migration summary will appear here.")
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
        self.recent_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.recent_list.itemDoubleClicked.connect(self._open_recent_item)
        self.recent_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.recent_list.customContextMenuRequested.connect(
            self._recent_context_menu)
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
                card.setStyleSheet(
                    "border: 2px solid #2563eb; border-radius: 12px;")
            else:
                card.setStyleSheet("")
        template = TEMPLATES[key]
        if hasattr(self, "template_caption"):
            self.template_caption.setText(
                f"<b>{template.title}</b> — {template.description}")
        self.status_bar.showMessage(
            f"Template set to {
                TEMPLATES[key].title}", 4000)

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
            QtWidgets.QMessageBox.warning(
                self, "Name required", "Please enter a project name.")
            return
        location = self.create_location.text().strip()
        if not location:
            QtWidgets.QMessageBox.warning(
                self, "Choose location", "Select where to save the project file.")
            return
        selected, titles = self._collect_pages()
        palette = dict(
            THEME_PRESETS.get(
                self.create_theme.currentText(),
                DEFAULT_PALETTE))
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
        slug = re.sub(
            r"[^a-zA-Z0-9_-]+",
            "-",
            name.lower()).strip("-") or "site"
        project_path = save_dir / f"{slug}.siteproj"
        if project_path.exists():
            if QtWidgets.QMessageBox.question(
                self, "Overwrite?", f"{
                    project_path.name} already exists. Replace it?") != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        try:
            save_project(project_path, project)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Could not save project:\n{exc}")
            return
        self.recents.add_or_bump(project_path, project)
        thumb = write_project_thumbnail(project, project_path)
        tile_path = Path(
            project.cover_tile_path) if project.cover_tile_path else thumb
        if project.cover_path:
            self.recents.set_cover(
                project_path,
                Path(
                    project.cover_path),
                tile_path=tile_path)
        elif tile_path:
            self.recents.set_thumbnail(project_path, tile_path)
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
            self.import_summary.setPlainText(
                "Upgraded to Webineer v2. You're all set!")
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
            QtWidgets.QMessageBox.warning(
                self, "Not found", "That project file no longer exists.")
            return
        try:
            result = load_project(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Couldn't open project:\n{exc}")
            return
        self.settings.set("last_open_dir", str(path.parent))
        if result.migrated:
            QtWidgets.QMessageBox.information(
                self, "Upgraded", "We upgraded this project to the latest format.")
            try:
                save_project(path, result.project)
            except Exception:
                pass
        self.project_opened.emit(result.project, path)
        self.close()

    def refresh_recents(self) -> None:
        self.recents.load()
        items = self.recents.list()
        if hasattr(self, "recent_tiles"):
            self.recent_tiles.clear()
            for entry in items:
                display = f"📌 {entry.name}" if entry.pinned else entry.name
                tile = QtWidgets.QListWidgetItem(display)
                tile.setData(Qt.ItemDataRole.UserRole, entry.path)
                tooltip = f"{entry.path}\nLast opened: {entry.last_opened}"
                tile.setToolTip(tooltip)
                icon_path = entry.cover or entry.thumbnail
                if icon_path and Path(icon_path).exists():
                    tile.setIcon(QtGui.QIcon(icon_path))
                else:
                    fallback = self._template_preview_pixmap(
                        self._selected_template)
                    tile.setIcon(QtGui.QIcon(fallback))
                tile.setData(Qt.ItemDataRole.AccessibleTextRole, display)
                self.recent_tiles.addItem(tile)
        if not hasattr(self, "recent_list"):
            return
        self.recent_list.clear()
        for item in items:
            list_item = QtWidgets.QListWidgetItem(item.name)
            list_item.setData(Qt.ItemDataRole.UserRole, item.path)
            subtitle = f"{item.path}\nLast opened: {item.last_opened}"
            if item.pinned:
                subtitle = "📌 " + subtitle
            list_item.setToolTip(subtitle)
            icon_path = item.thumbnail or item.cover
            if icon_path and Path(icon_path).exists():
                list_item.setIcon(QtGui.QIcon(icon_path))
            self.recent_list.addItem(list_item)

    def _open_recent_item(self, item: QtWidgets.QListWidgetItem) -> None:
        path = Path(str(item.data(Qt.ItemDataRole.UserRole)))
        if not path.exists():
            QtWidgets.QMessageBox.warning(
                self, "Missing", "This project file is missing. Removing from list.")
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
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(Path(path_str).parent)))
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
        self.resize(1280, 820)

        self._current_page_index: int = -1
        self._flush_row_override: Optional[int] = None
        self._dirty: bool = False

        self._ai_threads: List[QThread] = []
        self._ai_workers: List[QObject] = []
        self.ai_dock: Optional[QtWidgets.QDockWidget] = None
        self.ai_prompt: Optional[QtWidgets.QPlainTextEdit] = None
        self.ai_output: Optional[QtWidgets.QPlainTextEdit] = None

        self._preview_tmp: Optional[str] = None
        self._debounce = QtCore.QTimer(self)
        self._debounce.setInterval(400)
        self._debounce.setSingleShot(True)
        # Debounced auto-preview: call update_preview when timer fires
        self._debounce.timeout.connect(self.update_preview)
        self._last_cover_palette_hash: str = ""
        self._last_cover_content_hash: str = ""

        self._build_ui()
        self._build_menu()
        self._bind_events()
        self._load_project_into_ui()
        self.update_window_title()
        self.update_preview()

    # UI setup ----------------------------------------------------------
    def set_dirty(self, dirty: bool = True) -> None:
        self._dirty = dirty
        self.update_window_title()

    def maybe_save_before(self, action_label: str) -> bool:
        """Return True to proceed, False to abort (user chose Cancel)."""
        if not self._dirty:
            return True
        name = self.project.name if self.project else "Untitled"
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved changes")
        box.setText(f"Save changes to “{name}” before {action_label}?")
        box.setInformativeText("If you don’t save, your changes will be lost.")
        save_btn = box.addButton(
            "Save", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        discard_btn = box.addButton(
            "Don’t Save", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton(
            "Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked is save_btn:
            self.save_project()
            return not self._dirty
        if clicked is discard_btn:
            self.set_dirty(False)
            return True
        return False

    def update_window_title(self) -> None:
        name = self.project.name if self.project else "Untitled"
        suffix = f" ({self.project_path.name})" if self.project_path else ""
        dirty = " •" if getattr(self, "_dirty", False) else ""
        self.setWindowTitle(f"{APP_TITLE} — {name}{suffix}{dirty}")

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
        self.btn_preview = QtWidgets.QPushButton("Preview")
        header.addWidget(self.btn_add_page)
        header.addWidget(self.btn_remove_page)
        header.addWidget(self.btn_preview)
        left_layout.addLayout(header)

        self.pages_list = QtWidgets.QListWidget(left)
        self.pages_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        left_layout.addWidget(self.pages_list, 1)

        # Center tabs
        self.tab_editors = QtWidgets.QTabWidget(self)
        self.tab_editors.setDocumentMode(True)
        self.html_editor = QtWidgets.QPlainTextEdit(self.tab_editors)
        self.html_editor.setPlaceholderText("Write HTML for the current page.")
        font = QtGui.QFontDatabase.systemFont(
            QtGui.QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(11)
        self.html_editor.setFont(font)
        self.css_editor = QtWidgets.QPlainTextEdit(self.tab_editors)
        self.css_editor.setPlaceholderText("Global CSS")
        self.css_editor.setFont(font)
        self.tab_editors.addTab(self.html_editor, "Page HTML")
        self.tab_editors.addTab(self.css_editor, "Global CSS")
        self.design_tab = self._build_design_tab()
        # Apply comfortable spacing and field growth to Design tab
        _tune_design_layouts(self.design_tab)
        # Optional: add a little extra separation for group titles
        self.design_tab.setStyleSheet("""
            QGroupBox { margin-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 2px 6px; }
        """)

        self.assets_tab = self._build_assets_tab()
        self.external_tab = self._build_external_tab()
        self.tab_editors.addTab(self.design_tab, "Design")
        self.tab_editors.addTab(self.assets_tab, "Assets")
        self.tab_editors.addTab(self.external_tab, "External")

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
        main_layout = QtWidgets.QVBoxLayout(tab)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        theme_group = QtWidgets.QGroupBox("Theme & Palette", tab)
        theme_layout = QtWidgets.QFormLayout(theme_group)
        theme_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.design_theme_combo = QtWidgets.QComboBox(theme_group)
        self.design_theme_combo.addItems(
            list(THEME_PRESETS.keys()) + ["Custom"])
        self.design_theme_combo.setToolTip(
            "Try curated palettes and fonts to jump-start your design.")
        theme_layout.addRow("Try a theme", self.design_theme_combo)

        def color_field(line_edit: QtWidgets.QLineEdit,
                        swatch: QtWidgets.QLabel) -> QtWidgets.QWidget:
            widget = QtWidgets.QWidget(theme_group)
            row = QtWidgets.QHBoxLayout(widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            row.addWidget(line_edit, 1)
            swatch.setFixedSize(36, 20)
            swatch.setFrameShape(QtWidgets.QFrame.Shape.Panel)
            swatch.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
            row.addWidget(swatch)
            return widget

        self.design_primary = QtWidgets.QLineEdit(theme_group)
        self.design_primary.setPlaceholderText("#2563eb")
        self.design_primary.setToolTip(
            "Accent color used for buttons and highlights.")
        self.primary_swatch = QtWidgets.QLabel(theme_group)
        theme_layout.addRow(
            "Primary color",
            color_field(
                self.design_primary,
                self.primary_swatch))

        self.design_surface = QtWidgets.QLineEdit(theme_group)
        self.design_surface.setPlaceholderText("#f8fafc")
        self.design_surface.setToolTip(
            "Background color for sections and cards.")
        self.surface_swatch = QtWidgets.QLabel(theme_group)
        theme_layout.addRow(
            "Surface color",
            color_field(
                self.design_surface,
                self.surface_swatch))

        self.design_text = QtWidgets.QLineEdit(theme_group)
        self.design_text.setPlaceholderText("#0f172a")
        self.design_text.setToolTip(
            "Main text color for paragraphs and headings.")
        self.text_swatch = QtWidgets.QLabel(theme_group)
        theme_layout.addRow(
            "Text color",
            color_field(
                self.design_text,
                self.text_swatch))

        self.design_heading_font = QtWidgets.QComboBox(theme_group)
        self.design_heading_font.addItems(FONT_STACKS)
        self.design_heading_font.setToolTip(
            "Font used for headings and large titles.")
        theme_layout.addRow("Heading font", self.design_heading_font)

        self.design_body_font = QtWidgets.QComboBox(theme_group)
        self.design_body_font.addItems(FONT_STACKS)
        self.design_body_font.setToolTip(
            "Font used for body copy and long-form text.")
        theme_layout.addRow("Body font", self.design_body_font)

        button_row = QtWidgets.QHBoxLayout()
        self.btn_apply_theme = QtWidgets.QPushButton(
            "Apply theme", theme_group)
        self.btn_apply_theme.setMinimumHeight(40)
        self.btn_add_helpers = QtWidgets.QPushButton(
            "Add CSS helpers", theme_group)
        self.btn_add_helpers.setMinimumHeight(40)
        button_row.addWidget(self.btn_apply_theme)
        button_row.addWidget(self.btn_add_helpers)
        theme_layout.addRow(button_row)

        main_layout.addWidget(theme_group)

        gradient_group = QtWidgets.QGroupBox("Gradients", tab)
        gradient_layout = QtWidgets.QFormLayout(gradient_group)
        gradient_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.gradient_from = QtWidgets.QLineEdit(gradient_group)
        self.gradient_from.setPlaceholderText(DEFAULT_GRADIENT["from"])
        self.gradient_from.setToolTip(
            "Start color for the gradient background helper.")
        gradient_layout.addRow("From", self.gradient_from)

        self.gradient_to = QtWidgets.QLineEdit(gradient_group)
        self.gradient_to.setPlaceholderText(DEFAULT_GRADIENT["to"])
        self.gradient_to.setToolTip(
            "End color for the gradient background helper.")
        gradient_layout.addRow("To", self.gradient_to)

        self.gradient_angle_combo = QtWidgets.QComboBox(gradient_group)
        self.gradient_angle_combo.addItems(GRADIENT_ANGLES)
        self.gradient_angle_combo.setEditable(True)
        self.gradient_angle_combo.setInsertPolicy(
            QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.gradient_angle_combo.setToolTip(
            "Direction of the gradient (e.g., 135deg or to bottom).")
        angle_row = QtWidgets.QHBoxLayout()
        angle_widget = QtWidgets.QWidget(gradient_group)
        angle_widget.setLayout(angle_row)
        angle_row.setContentsMargins(0, 0, 0, 0)
        angle_row.setSpacing(6)
        angle_row.addWidget(self.gradient_angle_combo, 1)
        self.gradient_preview = QtWidgets.QLabel(gradient_group)
        self.gradient_preview.setFixedSize(60, 20)
        self.gradient_preview.setFrameShape(QtWidgets.QFrame.Shape.Panel)
        self.gradient_preview.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        angle_row.addWidget(self.gradient_preview)
        gradient_layout.addRow("Angle", angle_widget)

        gradient_buttons = QtWidgets.QHBoxLayout()
        self.btn_apply_gradient = QtWidgets.QPushButton(
            "Apply Gradient Helpers", gradient_group)
        self.btn_apply_gradient.setToolTip(
            "Updates the gradient utility classes in your CSS.")
        self.btn_insert_gradient_hero = QtWidgets.QPushButton(
            "Insert Gradient Hero Background", gradient_group)
        self.btn_insert_gradient_hero.setToolTip(
            "Insert a ready-made hero section that uses the gradient helpers.")
        gradient_buttons.addWidget(self.btn_apply_gradient)
        gradient_buttons.addWidget(self.btn_insert_gradient_hero)
        gradient_layout.addRow(gradient_buttons)

        main_layout.addWidget(gradient_group)

        background_group = QtWidgets.QGroupBox("Background", tab)
        background_layout = QtWidgets.QVBoxLayout(background_group)
        background_layout.setContentsMargins(14, 14, 14, 14)
        background_layout.setSpacing(12)

        background_form = QtWidgets.QFormLayout()
        background_form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        background_form.setHorizontalSpacing(12)
        background_form.setVerticalSpacing(10)

        self.bg_scope_combo = QtWidgets.QComboBox(background_group)
        self.bg_scope_combo.addItems(BACKGROUND_SCOPE_CHOICES)
        background_form.addRow("Scope", self.bg_scope_combo)

        self.bg_kind_combo = QtWidgets.QComboBox(background_group)
        self.bg_kind_combo.addItems(BACKGROUND_KIND_CHOICES)
        background_form.addRow("Kind", self.bg_kind_combo)

        self.bg_stack = QtWidgets.QStackedWidget(background_group)
        background_form.addRow("Options", self.bg_stack)
        self.bg_stack.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred
        )
        self.bg_stack.setMinimumHeight(240)

        # Solid background controls
        solid_widget = QtWidgets.QWidget(self.bg_stack)
        solid_layout = QtWidgets.QHBoxLayout(solid_widget)
        solid_layout.setContentsMargins(0, 0, 0, 0)
        solid_layout.setSpacing(6)
        self.bg_solid_color = ColorButton("#0f172a", solid_widget)
        solid_layout.addWidget(self.bg_solid_color)
        solid_layout.addStretch(1)
        solid_widget.setMinimumHeight(160)
        self.bg_stack.addWidget(solid_widget)

        # Gradient background controls
        gradient_widget = QtWidgets.QWidget(self.bg_stack)
        gradient_widget_form = QtWidgets.QFormLayout(gradient_widget)
        gradient_widget_form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.bg_gradient_from = ColorButton(
            DEFAULT_GRADIENT["from"], gradient_widget)
        self.bg_gradient_to = ColorButton(
            DEFAULT_GRADIENT["to"], gradient_widget)
        self.bg_gradient_angle = QtWidgets.QSpinBox(gradient_widget)
        self.bg_gradient_angle.setRange(0, 360)
        self.bg_gradient_angle.setSuffix("°")
        self.bg_gradient_angle.setValue(
            int(DEFAULT_GRADIENT.get("angle", "135deg").replace("deg", "")))
        gradient_widget_form.addRow("From", self.bg_gradient_from)
        gradient_widget_form.addRow("To", self.bg_gradient_to)
        gradient_widget_form.addRow("Angle", self.bg_gradient_angle)
        gradient_widget.setMinimumHeight(200)
        self.bg_stack.addWidget(gradient_widget)

        # Image background controls
        image_widget = QtWidgets.QWidget(self.bg_stack)
        image_form = QtWidgets.QFormLayout(image_widget)
        image_form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        image_path_row = QtWidgets.QHBoxLayout()
        image_path_row.setContentsMargins(0, 0, 0, 0)
        image_path_row.setSpacing(6)
        self.bg_image_path = QtWidgets.QLineEdit(image_widget)
        self.bg_image_browse = QtWidgets.QPushButton("Browse…", image_widget)
        image_path_row.addWidget(self.bg_image_path)
        image_path_row.addWidget(self.bg_image_browse)
        image_path_widget = QtWidgets.QWidget(image_widget)
        image_path_widget.setLayout(image_path_row)
        image_form.addRow("Image", image_path_widget)
        self.bg_image_position_combo = QtWidgets.QComboBox(image_widget)
        self.bg_image_position_combo.addItems(
            ["center", "top", "bottom", "left", "right"])
        image_form.addRow("Position", self.bg_image_position_combo)
        self.bg_image_size_combo = QtWidgets.QComboBox(image_widget)
        self.bg_image_size_combo.addItems(["cover", "contain", "auto"])
        image_form.addRow("Size", self.bg_image_size_combo)
        self.bg_image_fixed = QtWidgets.QCheckBox(
            "Fixed (parallax)", image_widget)
        image_form.addRow("Scrolling", self.bg_image_fixed)
        image_widget.setMinimumHeight(240)
        self.bg_stack.addWidget(image_widget)

        # Pattern background controls
        pattern_widget = QtWidgets.QWidget(self.bg_stack)
        pattern_layout = QtWidgets.QVBoxLayout(pattern_widget)
        pattern_layout.setContentsMargins(0, 0, 0, 0)
        pattern_layout.setSpacing(6)
        self.bg_pattern_combo = QtWidgets.QComboBox(pattern_widget)
        self.bg_pattern_combo.addItems(list(BACKGROUND_PATTERN_PRESETS.keys()))
        pattern_layout.addWidget(self.bg_pattern_combo)
        self.bg_pattern_preview = QtWidgets.QLabel("Pattern preview")
        self.bg_pattern_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bg_pattern_preview.setMinimumHeight(120)
        self.bg_pattern_preview.setStyleSheet(
            "border:1px solid rgba(148,163,184,0.6); border-radius:4px;")
        pattern_layout.addWidget(self.bg_pattern_preview)
        self.bg_stack.addWidget(pattern_widget)

        background_layout.addLayout(background_form)

        self.bg_insert_markup = QtWidgets.QCheckBox(
            "Also insert minimal markup", background_group)
        background_layout.addWidget(self.bg_insert_markup)

        background_buttons = QtWidgets.QHBoxLayout()
        background_buttons.setContentsMargins(0, 0, 0, 0)
        background_buttons.setSpacing(6)
        self.bg_apply_button = QtWidgets.QPushButton("Apply", background_group)
        self.bg_reset_button = QtWidgets.QPushButton("Reset", background_group)
        background_buttons.addWidget(self.bg_apply_button)
        background_buttons.addWidget(self.bg_reset_button)
        background_buttons.addStretch(1)
        background_layout.addLayout(background_buttons)
        background_layout.addStretch(1)

        main_layout.addWidget(background_group)
        self._update_background_pattern_preview()

        shape_group = QtWidgets.QGroupBox("Corners & Depth", tab)
        shape_layout = QtWidgets.QFormLayout(shape_group)
        shape_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.radius_spin = QtWidgets.QDoubleSpinBox(shape_group)
        self.radius_spin.setRange(0.5, 2.0)
        self.radius_spin.setSingleStep(0.05)
        self.radius_spin.setToolTip(
            "Makes corners more round across cards and buttons.")
        shape_layout.addRow("Radius scale", self.radius_spin)

        self.shadow_combo = QtWidgets.QComboBox(shape_group)
        self.shadow_combo.addItems(SHADOW_LEVELS)
        self.shadow_combo.setToolTip(
            "Adds soft shadow depth to the .shadow utility.")
        shape_layout.addRow("Shadow level", self.shadow_combo)

        main_layout.addWidget(shape_group)

        motion_group = QtWidgets.QGroupBox("Motion", tab)
        motion_layout = QtWidgets.QFormLayout(motion_group)
        motion_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.motion_enable_scroll = QtWidgets.QCheckBox(
            "Enable appear-on-scroll (adds small JS)", motion_group)
        self.motion_enable_scroll.setToolTip(
            "Reveals elements as they enter the viewport.")
        motion_layout.addRow(self.motion_enable_scroll)

        self.motion_pref_combo = QtWidgets.QComboBox(motion_group)
        self.motion_pref_combo.addItems(
            ["Respect visitor setting", "Force on", "Force off"])
        self.motion_pref_combo.setToolTip(
            "Choose how to handle reduced-motion preferences.")
        motion_layout.addRow("Reduced motion", self.motion_pref_combo)

        self.motion_effect_combo = QtWidgets.QComboBox(motion_group)
        self.motion_effect_combo.addItems(MOTION_EFFECTS)
        self.motion_effect_combo.setToolTip(
            "Default animation applied when wrapping content.")
        motion_layout.addRow("Default effect", self.motion_effect_combo)

        self.motion_easing_combo = QtWidgets.QComboBox(motion_group)
        self.motion_easing_combo.addItems(list(MOTION_EASINGS.keys()))
        self.motion_easing_combo.setToolTip(
            "Easing curve for wrapped animations.")
        motion_layout.addRow("Easing", self.motion_easing_combo)

        duration_row = QtWidgets.QHBoxLayout()
        duration_widget = QtWidgets.QWidget(motion_group)
        duration_widget.setLayout(duration_row)
        duration_row.setContentsMargins(0, 0, 0, 0)
        duration_row.setSpacing(6)
        self.motion_duration_spin = QtWidgets.QSpinBox(motion_group)
        self.motion_duration_spin.setRange(100, 5000)
        self.motion_duration_spin.setSingleStep(50)
        self.motion_duration_spin.setSuffix(" ms")
        self.motion_duration_spin.setToolTip("How long the animation plays.")
        duration_row.addWidget(self.motion_duration_spin)
        self.motion_delay_spin = QtWidgets.QSpinBox(motion_group)
        self.motion_delay_spin.setRange(0, 3000)
        self.motion_delay_spin.setSingleStep(50)
        self.motion_delay_spin.setSuffix(" ms")
        self.motion_delay_spin.setToolTip("Delay before the animation starts.")
        duration_row.addWidget(self.motion_delay_spin)
        motion_layout.addRow("Duration & delay", duration_widget)

        self.btn_wrap_motion_default = QtWidgets.QPushButton(
            "Wrap Selection with Animation", motion_group)
        self.btn_wrap_motion_default.setToolTip(
            "Wraps the selected HTML with your default animation settings.")
        motion_layout.addRow(self.btn_wrap_motion_default)

        main_layout.addWidget(motion_group)

        note = QtWidgets.QLabel(
            "Design changes update your CSS instantly. Helpers stay tidy thanks to sentinel markers."
        )
        note.setWordWrap(True)
        main_layout.addWidget(note)
        main_layout.addStretch(1)

        # Optional: wrap the Design tab in a scroll area for resilience
        scroller = QtWidgets.QScrollArea(self)
        scroller.setWidget(tab)
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        return scroller

    def _build_external_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        button_row = QtWidgets.QHBoxLayout()
        self.btn_external_add_css = QtWidgets.QPushButton("Add CSS link…")
        self.btn_external_add_js = QtWidgets.QPushButton("Add JS link…")
        self.btn_external_download = QtWidgets.QPushButton(
            "Download to assets")
        button_row.addWidget(self.btn_external_add_css)
        button_row.addWidget(self.btn_external_add_js)
        button_row.addWidget(self.btn_external_download)
        button_row.addStretch()
        layout.addLayout(button_row)
        self.external_table = QtWidgets.QTableWidget(0, 4, tab)
        self.external_table.setHorizontalHeaderLabels(
            ["Type", "Mode", "URL / Path", "Actions"])
        header = self.external_table.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(True)
            header.setSectionResizeMode(
                0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(
                1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(
                2, QtWidgets.QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(
                3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        vh = self.external_table.verticalHeader()
        if vh is not None:
            vh.setVisible(False)
        self.external_table.setAlternatingRowColors(True)
        self.external_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.external_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.external_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.external_table, 1)
        hint = QtWidgets.QLabel(
            "Link external styles or scripts. Download to keep an offline copy for export."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: rgba(71,85,105,0.9);")
        layout.addWidget(hint)
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
        action_row = QtWidgets.QHBoxLayout()
        self.btn_set_cover_image = QtWidgets.QPushButton("Set as Cover Image")
        self.btn_set_cover_image.setToolTip(
            "Use the selected asset as the hero photo for cover art.")
        self.btn_generate_placeholder = QtWidgets.QPushButton(
            "Generate placeholder…")
        self.btn_generate_placeholder.setToolTip(
            "Create an inline SVG placeholder image for hero areas.")
        action_row.addWidget(self.btn_set_cover_image)
        action_row.addWidget(self.btn_generate_placeholder)
        action_row.addStretch()
        layout.addLayout(action_row)
        self.asset_list = AssetListWidget(tab)
        self.asset_list.filesDropped.connect(self._import_assets)
        self.asset_list.currentRowChanged.connect(self._show_asset_preview)
        layout.addWidget(self.asset_list, 1)
        self.asset_preview = QtWidgets.QLabel("Drop images here or click Add.")
        self.asset_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.asset_preview.setMinimumHeight(160)
        layout.addWidget(self.asset_preview)
        self.btn_insert_image = QtWidgets.QPushButton(
            "Insert responsive image")
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
            self.menu_layouts = insert_menu.addMenu("Layouts")
            if self.menu_layouts is not None:
                for key, snippet in LAYOUT_SNIPPETS.items():
                    action = QtGui.QAction(snippet.label, self)
                    action.triggered.connect(
                        lambda checked=False, lib=LAYOUT_SNIPPETS, item_key=key: self.insert_snippet(
                            lib, item_key)
                    )
                    self.menu_layouts.addAction(action)
            self.menu_sections = insert_menu.addMenu("Sections")
            if self.menu_sections is not None:
                for key, snippet in SECTIONS_SNIPPETS.items():
                    action = QtGui.QAction(snippet.label, self)
                    action.triggered.connect(
                        lambda checked=False, lib=SECTIONS_SNIPPETS, item_key=key: self.insert_snippet(
                            lib, item_key)
                    )
                    self.menu_sections.addAction(action)
            self.menu_components = insert_menu.addMenu("Components")
            if self.menu_components is not None:
                for key, snippet in COMPONENT_SNIPPETS.items():
                    action = QtGui.QAction(snippet.label, self)
                    action.triggered.connect(
                        lambda checked=False, lib=COMPONENT_SNIPPETS, item_key=key: self.insert_snippet(
                            lib, item_key)
                    )
                    self.menu_components.addAction(action)
            self.menu_effects = insert_menu.addMenu("Effects")
            if self.menu_effects is not None:
                for key, snippet in EFFECT_SNIPPETS.items():
                    action = QtGui.QAction(snippet.label, self)
                    action.triggered.connect(
                        lambda checked=False, lib=EFFECT_SNIPPETS, item_key=key: self.insert_snippet(
                            lib, item_key)
                    )
                    self.menu_effects.addAction(action)
                self.menu_effects.addSeparator()
                act_blob = QtGui.QAction("Organic blob", self)
                act_blob.triggered.connect(
                    lambda checked=False: self.insert_graphic(svg_blob()))
                self.menu_effects.addAction(act_blob)
                act_dots = QtGui.QAction("Dots pattern", self)
                act_dots.triggered.connect(
                    lambda checked=False: self.insert_graphic(svg_dots()))
                self.menu_effects.addAction(act_dots)
                act_stripes = QtGui.QAction("Diagonal stripes", self)
                act_stripes.triggered.connect(
                    lambda checked=False: self.insert_graphic(svg_diagonal_stripes()))
                self.menu_effects.addAction(act_stripes)
                act_banner = QtGui.QAction("Gradient banner", self)
                act_banner.triggered.connect(
                    lambda checked=False: self.insert_graphic(
                        '<div class="bg-gradient" style="width:100%;height:220px;"></div>'
                    )
                )
                self.menu_effects.addAction(act_banner)
            self.menu_animation = insert_menu.addMenu("Animation")
            if self.menu_animation is not None:
                fade_up = QtGui.QAction("Wrap → anim-fade-up", self)
                fade_up.triggered.connect(
                    lambda checked=False: self.insert_animation_wrapper("anim-fade-up"))
                fade_in = QtGui.QAction("Wrap → anim-fade-in", self)
                fade_in.triggered.connect(
                    lambda checked=False: self.insert_animation_wrapper("anim-fade-in"))
                zoom_in = QtGui.QAction("Wrap → anim-zoom-in", self)
                zoom_in.triggered.connect(
                    lambda checked=False: self.insert_animation_wrapper("anim-zoom-in"))
                self.menu_animation.addActions([fade_up, fade_in, zoom_in])
                self.menu_animation.addSeparator()
                classic_fade = QtGui.QAction("Legacy wrap → Fade in", self)
                classic_fade.triggered.connect(
                    lambda checked=False: self._apply_motion_wrapper("fade"))
                classic_zoom = QtGui.QAction("Legacy wrap → Zoom in", self)
                classic_zoom.triggered.connect(
                    lambda checked=False: self._apply_motion_wrapper("zoom"))
                classic_blur = QtGui.QAction("Legacy wrap → Blur in", self)
                classic_blur.triggered.connect(
                    lambda checked=False: self._apply_motion_wrapper("blur"))
                loop_float = QtGui.QAction("Legacy loop → Float", self)
                loop_float.triggered.connect(
                    lambda checked=False: self._apply_motion_wrapper("float", loop=True))
                self.menu_animation.addActions(
                    [classic_fade, classic_zoom, classic_blur, loop_float])

        m_publish = bar.addMenu("&Publish")
        self.act_publish = QtGui.QAction("Publish…", self)
        if m_publish is not None:
            m_publish.addAction(self.act_publish)

        m_resources = bar.addMenu("&Resources")

        if m_resources is not None:
            def add_link(caption: str, url: str) -> None:
                act = QtGui.QAction(caption, self)
                act.triggered.connect(
                    lambda checked=False, link=url: open_url(link))
                m_resources.addAction(act)

            add_link("MDN HTML reference",
                     "https://developer.mozilla.org/en-US/docs/Web/HTML/Reference")
            add_link("MDN CSS reference",
                     "https://developer.mozilla.org/en-US/docs/Web/CSS/Reference")
            add_link("Learn CSS (web.dev)", "https://web.dev/learn/css/")
            add_link("Flexbox guide (CSS-Tricks)",
                     "https://css-tricks.com/snippets/css/a-guide-to-flexbox/")
            add_link("Grid garden (Game)", "https://cssgridgarden.com/")
            add_link("Accessibility basics (web.dev)",
                     "https://web.dev/learn/accessibility/")
            add_link("GitHub Pages quickstart",
                     "https://docs.github.com/en/pages/quickstart")
            add_link("Domain name ideas (LeanDomainSearch)",
                     "https://leandomainsearch.com/")

        help_menu = bar.addMenu("&Help")
        self.act_about = QtGui.QAction("About", self)
        self.act_get_started = QtGui.QAction("Get Started", self)
        self.act_ai = QtGui.QAction("AI Project Help", self)
        self.act_about.setShortcut("F1")
        if help_menu is not None:
            help_menu.addAction(self.act_about)
            help_menu.addAction(self.act_get_started)
            help_menu.addAction(self.act_ai)
            help_menu.addSeparator()
            self.act_replay_intro = QtGui.QAction("Replay intro sound", self)

            def _replay_intro() -> None:
                volume = 70
                try:
                    volume = int(self.settings.get("intro_volume", "70"))
                except Exception:
                    volume = 70
                play_intro_sound(volume_pct=max(0, min(100, volume)))

            self.act_replay_intro.triggered.connect(_replay_intro)
            help_menu.addAction(self.act_replay_intro)

    def _bind_events(self) -> None:
        self.pages_list.currentRowChanged.connect(self._on_page_selected)
        self.html_editor.textChanged.connect(self._on_editor_changed)
        self.css_editor.textChanged.connect(self._on_editor_changed)
        self.btn_add_page.clicked.connect(self.add_page)
        self.btn_remove_page.clicked.connect(self.remove_page)
        self.btn_preview.clicked.connect(
            lambda: self.update_preview(open_external=True))
        self.btn_apply_theme.clicked.connect(self.apply_theme)
        self.btn_add_helpers.clicked.connect(self.add_css_helpers)
        self.btn_apply_gradient.clicked.connect(self.apply_gradient_helpers)
        self.btn_insert_gradient_hero.clicked.connect(
            self.insert_gradient_hero)
        self.bg_kind_combo.currentIndexChanged.connect(
            self._on_background_kind_changed)
        self.bg_scope_combo.currentIndexChanged.connect(
            self._on_background_scope_changed)
        self.bg_pattern_combo.currentTextChanged.connect(
            self._update_background_pattern_preview)
        self.bg_image_browse.clicked.connect(self._browse_background_image)
        self.bg_apply_button.clicked.connect(self._apply_background_from_ui)
        self.bg_reset_button.clicked.connect(self._reset_background_from_ui)
        self.btn_add_asset.clicked.connect(self._browse_assets)
        self.btn_rename_asset.clicked.connect(self._rename_asset)
        self.btn_remove_asset.clicked.connect(self._remove_asset)
        self.btn_set_cover_image.clicked.connect(
            self._set_cover_image_from_asset)
        self.btn_generate_placeholder.clicked.connect(
            self._generate_placeholder_asset)
        self.btn_insert_image.clicked.connect(self._insert_image_dialog)
        self.btn_external_add_css.clicked.connect(
            lambda: self._add_external_asset("css"))
        self.btn_external_add_js.clicked.connect(
            lambda: self._add_external_asset("js"))
        self.btn_external_download.clicked.connect(
            self._download_external_asset)
        self.act_new.triggered.connect(lambda: self.maybe_save_before(
            "creating a new project") and self.new_project_bootstrap())
        self.act_open.triggered.connect(lambda: self.maybe_save_before(
            "opening another project") and self.open_project_dialog())
        self.act_save.triggered.connect(self.save_project)
        self.act_save_as.triggered.connect(self.save_project_as)
        self.act_export.triggered.connect(self.export_project)
        self.act_quit.triggered.connect(self.close)
        self.act_start.triggered.connect(
            lambda: self.controller.show_start_from_main("Recent"))
        self.act_about.triggered.connect(self.show_about)
        self.act_get_started.triggered.connect(self._open_help_page)
        self.act_publish.triggered.connect(self.open_publish_dialog)
        self.act_ai.triggered.connect(self.toggle_ai_dock)
        self.design_primary.textChanged.connect(self._update_color_swatches)
        self.design_surface.textChanged.connect(self._update_color_swatches)
        self.design_text.textChanged.connect(self._update_color_swatches)
        self.gradient_from.textChanged.connect(self._update_gradient_preview)
        self.gradient_to.textChanged.connect(self._update_gradient_preview)
        self.gradient_angle_combo.editTextChanged.connect(
            self._update_gradient_preview)
        self.radius_spin.valueChanged.connect(self._on_radius_scale_changed)
        self.shadow_combo.currentTextChanged.connect(
            self._on_shadow_level_changed)
        self.motion_enable_scroll.toggled.connect(
            self._toggle_scroll_animations)
        self.motion_pref_combo.currentIndexChanged.connect(
            self._on_motion_pref_changed)
        self.motion_effect_combo.currentTextChanged.connect(
            self._on_motion_defaults_changed)
        self.motion_easing_combo.currentTextChanged.connect(
            self._on_motion_defaults_changed)
        self.motion_duration_spin.valueChanged.connect(
            self._on_motion_defaults_changed)
        self.motion_delay_spin.valueChanged.connect(
            self._on_motion_defaults_changed)
        self.btn_wrap_motion_default.clicked.connect(
            self.wrap_selection_default_motion)

        self.shortcut_gradient = QtGui.QShortcut(
            QtGui.QKeySequence("Ctrl+G"), self)
        self.shortcut_gradient.activated.connect(self.apply_gradient_helpers)
        self.shortcut_motion = QtGui.QShortcut(
            QtGui.QKeySequence("Ctrl+M"), self)
        self.shortcut_motion.activated.connect(
            self.wrap_selection_default_motion)

    def _load_project_into_ui(self) -> None:
        self._last_cover_palette_hash = ""
        self._last_cover_content_hash = ""
        self._refresh_pages_list()
        self._current_page_index = -1
        self._flush_row_override = None
        self.html_editor.blockSignals(True)
        if self.project.pages:
            self.html_editor.setPlainText(self.project.pages[0].html)
        else:
            self.html_editor.clear()
        self.html_editor.blockSignals(False)
        self.css_editor.blockSignals(True)
        self.css_editor.setPlainText(self.project.css)
        self.css_editor.blockSignals(False)
        if self.project.backgrounds and BACKGROUND_BLOCK_START not in self.project.css:
            self._sync_background_css()
        if self.project.pages:
            self.pages_list.setCurrentRow(0)
        self.design_primary.setText(
            self.project.palette.get("primary", "#2563eb"))
        self.design_surface.setText(
            self.project.palette.get("surface", "#f8fafc"))
        self.design_text.setText(self.project.palette.get("text", "#0f172a"))
        self.design_heading_font.setCurrentText(
            self.project.fonts.get("heading", FONT_STACKS[0]))
        self.design_body_font.setCurrentText(
            self.project.fonts.get("body", FONT_STACKS[0]))
        self.design_theme_combo.setCurrentText(
            self.project.theme_preset if self.project.theme_preset in THEME_PRESETS else "Custom"
        )
        gradient = self.project.gradients or DEFAULT_GRADIENT
        self.gradient_from.blockSignals(True)
        self.gradient_to.blockSignals(True)
        self.gradient_angle_combo.blockSignals(True)
        self.gradient_from.setText(gradient.get(
            "from", DEFAULT_GRADIENT["from"]))
        self.gradient_to.setText(gradient.get("to", DEFAULT_GRADIENT["to"]))
        self.gradient_angle_combo.setCurrentText(
            gradient.get("angle", DEFAULT_GRADIENT["angle"]))
        self.gradient_from.blockSignals(False)
        self.gradient_to.blockSignals(False)
        self.gradient_angle_combo.blockSignals(False)
        self.radius_spin.blockSignals(True)
        self.radius_spin.setValue(float(self.project.radius_scale or 1.0))
        self.radius_spin.blockSignals(False)
        shadow_value = self.project.shadow_level if self.project.shadow_level in SHADOW_LEVELS else "md"
        self.shadow_combo.blockSignals(True)
        self.shadow_combo.setCurrentText(shadow_value)
        self.shadow_combo.blockSignals(False)
        self.motion_enable_scroll.blockSignals(True)
        self.motion_enable_scroll.setChecked(
            self.project.use_scroll_animations)
        self.motion_enable_scroll.blockSignals(False)
        pref_label = next(
            (label for label, value in MOTION_PREF_OPTIONS.items()
             if value == self.project.motion_pref),
            "Respect visitor setting",
        )
        self.motion_pref_combo.blockSignals(True)
        self.motion_pref_combo.setCurrentText(pref_label)
        self.motion_pref_combo.blockSignals(False)
        effect_value = (
            self.project.motion_default_effect if self.project.motion_default_effect in MOTION_EFFECTS else "none"
        )
        self.motion_effect_combo.blockSignals(True)
        self.motion_effect_combo.setCurrentText(effect_value)
        self.motion_effect_combo.blockSignals(False)
        easing_label = next(
            (label for label, value in MOTION_EASINGS.items()
             if value == self.project.motion_default_easing),
            "Gentle ease",
        )
        self.motion_easing_combo.blockSignals(True)
        self.motion_easing_combo.setCurrentText(easing_label)
        self.motion_easing_combo.blockSignals(False)
        self.motion_duration_spin.blockSignals(True)
        self.motion_duration_spin.setValue(
            int(self.project.motion_default_duration))
        self.motion_duration_spin.blockSignals(False)
        self.motion_delay_spin.blockSignals(True)
        self.motion_delay_spin.setValue(int(self.project.motion_default_delay))
        self.motion_delay_spin.blockSignals(False)
        self._update_color_swatches()
        self._update_gradient_preview()
        self._refresh_assets()
        self._refresh_external_assets_table()
        self._load_background_controls()
        self.update_window_title()

    # Page management ---------------------------------------------------
    def _refresh_pages_list(self) -> None:
        self.pages_list.blockSignals(True)
        self.pages_list.clear()
        for page in self.project.pages:
            self.pages_list.addItem(f"{page.title} ({page.filename})")
        self.pages_list.blockSignals(False)

    def new_project_bootstrap(self) -> None:
        self._flush_editors_to_model()
        dialog = TemplateSelectDialog(self, PROJECT_TEMPLATES)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        selection = dialog.result()
        if selection is None:
            return
        template_key = selection.template_key
        site_name = selection.project_name
        spec = PROJECT_TEMPLATES.get(
            template_key, PROJECT_TEMPLATES["starter"])
        palette = dict(spec.palette or DEFAULT_PALETTE)
        palette.update(selection.palette)
        fonts = dict(spec.fonts or DEFAULT_FONTS)
        fonts.update(selection.fonts)
        css = generate_base_css(palette, fonts)
        if spec.include_helpers:
            css = ensure_block(css, CSS_HELPERS_SENTINEL, CSS_HELPERS_BLOCK)
        css = ensure_block(css, BG_HELPERS_SENTINEL, BG_HELPERS_BLOCK)
        if spec.extra_css.strip():
            css = ensure_block(css, TEMPLATE_EXTRA_SENTINEL, spec.extra_css)
        pages = [
            Page(filename=filename, title=title,
                 html=html.replace("{{SITE_NAME}}", site_name))
            for filename, title, html in spec.pages
        ]
        project = Project(
            name=site_name,
            pages=pages,
            css=css,
            palette=palette,
            fonts=fonts,
            template_key=template_key,
            images=placeholder_images(),
        )
        project.theme_preset = selection.theme if selection.theme in THEME_PRESETS else "Custom"
        self.project = project
        self.project_path = None
        self.update_window_title()
        self._load_project_into_ui()
        self.update_preview()
        self.set_dirty(False)

    def add_page(self) -> None:
        self._flush_editors_to_model()
        dialog = PageTemplateDialog(self, PAGE_TYPES)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        title, filename, html = dialog.result()
        existing = {p.filename for p in self.project.pages}
        if filename in existing:
            base = filename[:-5] if filename.endswith(".html") else filename
            counter = 1
            new_filename = filename
            while new_filename in existing:
                new_filename = f"{base}-{counter}.html"
                counter += 1
            filename = new_filename
        self.project.pages.append(
            Page(filename=filename, title=title, html=html))
        self._refresh_pages_list()
        self.pages_list.setCurrentRow(len(self.project.pages) - 1)
        self.html_editor.blockSignals(True)
        self.html_editor.setPlainText(html)
        self.html_editor.blockSignals(False)
        self.update_preview()
        self.set_dirty(True)

    def remove_page(self) -> None:
        self._flush_editors_to_model()
        row = self.pages_list.currentRow()
        if row < 0 or row >= len(self.project.pages):
            return
        page = self.project.pages[row]
        if page.filename == "index.html":
            QtWidgets.QMessageBox.warning(
                self, "Not allowed", "Home cannot be removed.")
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
        self.set_dirty(True)

    def _on_page_selected(self, index: int) -> None:
        if not self.project or index < 0 or index >= len(self.project.pages):
            return
        previous = self._current_page_index
        self._flush_row_override = previous if previous not in (
            -1, index) else None
        self._flush_editors_to_model()
        page = self.project.pages[index]
        self.html_editor.blockSignals(True)
        self.html_editor.setPlainText(page.html)
        self.html_editor.blockSignals(False)
        self._current_page_index = index
        self.update_preview()
        self._load_background_controls()

    # Editing & preview -------------------------------------------------
    def _on_editor_changed(self) -> None:
        self._debounce.start()
        self.set_dirty(True)

    def _flush_editors_to_model(self) -> None:
        if not self.project:
            return
        index = self.pages_list.currentRow()
        if self._flush_row_override is not None:
            index = self._flush_row_override
            self._flush_row_override = None
        elif 0 <= self._current_page_index < len(self.project.pages):
            index = self._current_page_index
        if 0 <= index < len(self.project.pages):
            self.project.pages[index].html = self.html_editor.toPlainText()
        self.project.css = self.css_editor.toPlainText()

    def update_preview(self, open_external: bool = False) -> None:
        if not self.project:
            return
        self._flush_editors_to_model()
        if self._preview_tmp and os.path.isdir(self._preview_tmp):
            shutil.rmtree(self._preview_tmp, ignore_errors=True)
        self._preview_tmp = tempfile.mkdtemp(prefix="webineer_preview_")
        render_site(self.project, Path(self._preview_tmp))
        index = self.pages_list.currentRow()
        if index < 0 and self.project.pages:
            index = 0
        if 0 <= index < len(self.project.pages):
            page = self.project.pages[index]
            file_path = Path(self._preview_tmp) / page.filename
            self.preview.setUrl(QtCore.QUrl.fromLocalFile(str(file_path)))
            if open_external:
                try:
                    webbrowser.open(str(file_path))
                except Exception:
                    pass
        self.status_bar.showMessage("Preview updated", 1500)
        self._maybe_render_cover()

    def _cover_signatures(self) -> Tuple[str, str]:
        if not self.project:
            return "", ""
        palette_payload = {
            "palette": self.project.palette,
            "fonts": self.project.fonts,
            "theme": self.project.theme_preset,
            "radius": self.project.radius_scale,
            "shadow": self.project.shadow_level,
            "cover_asset": self.project.cover_asset_name or "",
            "template": self.project.template_key,
        }
        palette_hash = hashlib.sha1(json.dumps(
            palette_payload, sort_keys=True).encode("utf-8")).hexdigest()
        first_html = self.project.pages[0].html if self.project.pages else ""
        css = self.project.css or ""
        content_hash = hashlib.sha1(
            (first_html + "\n---\n" + css).encode("utf-8")).hexdigest()
        return palette_hash, content_hash

    def _maybe_render_cover(self, *, force: bool = False) -> None:
        if not self.project:
            return
        palette_hash, content_hash = self._cover_signatures()
        if not force and palette_hash == self._last_cover_palette_hash and content_hash == self._last_cover_content_hash:
            return
        thumb = write_project_thumbnail(self.project, self.project_path)
        tile_path = Path(
            self.project.cover_tile_path) if self.project.cover_tile_path else thumb
        if self.project_path and self.project.cover_path:
            self.recents.set_cover(self.project_path, Path(
                self.project.cover_path), tile_path=tile_path)
        elif self.project_path and tile_path:
            self.recents.set_thumbnail(self.project_path, tile_path)
        self._last_cover_palette_hash = palette_hash
        self._last_cover_content_hash = content_hash

    def wrap_selection_with(self, prefix: str, suffix: str) -> None:
        cursor = self.html_editor.textCursor()
        if not cursor.hasSelection():
            return
        selected = cursor.selectedText().replace("\u2029", "\n")
        cursor.insertText(f"{prefix}{selected}{suffix}")

    def insert_snippet(self, library: Dict[str, Snippet], key: str) -> None:
        snippet = library[key]
        cursor = self.html_editor.textCursor()
        if not cursor.hasSelection():
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        html = "\n\n" + snippet.html.strip() + "\n\n"
        cursor.insertText(html)
        self.html_editor.setTextCursor(cursor)
        if snippet.requires_js:
            self.project.use_main_js = True
        self.set_dirty(True)
        self.update_preview()

    def insert_graphic(self, markup: str) -> None:
        if not self.project:
            return
        cursor = self.html_editor.textCursor()
        if not cursor.hasSelection():
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        cursor.insertText(f"\n\n{markup.strip()}\n\n")
        self.html_editor.setTextCursor(cursor)
        self.set_dirty(True)
        self.update_preview()
        self.status_bar.showMessage("Graphic inserted", 2000)

    def insert_animation_wrapper(self, class_name: str) -> None:
        if not self.project:
            return
        cursor = self.html_editor.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n")
        if selected:
            cursor.insertText(
                f"<div class=\"{class_name}\">\n{selected}\n</div>")
        else:
            cursor.insertText(
                f"\n<div class=\"{class_name}\">\n  <p>Add animated content here.</p>\n</div>\n"
            )
        self.project.use_main_js = True
        self.set_dirty(True)
        self.update_preview()
        self.status_bar.showMessage(f"Added {class_name} wrapper", 2000)

    def _background_scope_value(self) -> str:
        if getattr(self, "bg_scope_combo", None) is None:
            return "site"
        return "site" if self.bg_scope_combo.currentIndex() == 0 else "page"

    def _background_kind_value(self) -> str:
        if getattr(self, "bg_kind_combo", None) is None:
            return "solid"
        index = self.bg_kind_combo.currentIndex()
        if 0 <= index < len(BACKGROUND_KIND_CHOICES):
            return BACKGROUND_KIND_CHOICES[index].lower()
        return "solid"

    def _current_page(self) -> Optional[Page]:
        if not self.project or not self.project.pages:
            return None
        index = self.pages_list.currentRow()
        if index < 0 or index >= len(self.project.pages):
            return None
        return self.project.pages[index]

    def _background_spec_for_scope(self, scope: str, page_filename: Optional[str]) -> Optional[BackgroundSpec]:
        for spec in self.project.backgrounds:
            if spec.scope != scope:
                continue
            if scope == "site":
                return spec
            if page_filename and spec.value.get("page") == page_filename:
                return spec
        return None

    def _store_background_spec(self, spec: BackgroundSpec, page_filename: Optional[str]) -> None:
        updated: List[BackgroundSpec] = []
        for existing in self.project.backgrounds:
            if existing.scope != spec.scope:
                updated.append(existing)
                continue
            if spec.scope == "page" and existing.value.get("page") != page_filename:
                updated.append(existing)
        updated.append(spec)
        self.project.backgrounds = updated

    def _remove_background_spec(self, scope: str, page_filename: Optional[str]) -> bool:
        removed = False
        remaining: List[BackgroundSpec] = []
        for spec in self.project.backgrounds:
            if spec.scope != scope:
                remaining.append(spec)
                continue
            if scope == "site":
                removed = True
                continue
            if spec.value.get("page") == page_filename:
                removed = True
            else:
                remaining.append(spec)
        if removed:
            self.project.backgrounds = remaining
        return removed

    def _strip_background_blocks(self, css: str) -> str:
        pattern = re.compile(
            re.escape(BACKGROUND_BLOCK_START) + r".*?" +
            re.escape(BACKGROUND_BLOCK_END), re.S
        )
        cleaned = re.sub(pattern, "", css)
        return cleaned.strip()

    def _sync_background_css(self) -> None:
        css = self.css_editor.toPlainText()
        css = self._strip_background_blocks(css)
        blocks = [self._build_background_block(
            spec) for spec in self.project.backgrounds]
        blocks = [block for block in blocks if block]
        if blocks:
            combined = f"{BACKGROUND_BLOCK_START}\n" + \
                "\n\n".join(blocks) + f"\n{BACKGROUND_BLOCK_END}"
            css = (css + "\n\n" + combined).strip() if css else combined
        self.css_editor.blockSignals(True)
        self.css_editor.setPlainText(css)
        self.css_editor.blockSignals(False)
        self.project.css = css

    def _build_background_block(self, spec: BackgroundSpec) -> Optional[str]:
        scope = spec.scope
        kind = spec.kind
        value = spec.value
        if scope == "site":
            if kind == "solid":
                color = value.get("color", "#0f0f0f")
                return f"{BACKGROUND_COMMENT_PREFIX} (site/solid) */\nbody {{ background: {color}; }}"
            if kind == "gradient":
                color_from = value.get("from", "#0ea5e9")
                color_to = value.get("to", "#a855f7")
                angle = value.get("angle", "135deg")
                return (
                    f"{BACKGROUND_COMMENT_PREFIX} (site/gradient) */\n"
                    "body::before {\n  content:\"\"; position:fixed; inset:0; z-index:-1;\n"
                    f"  background: linear-gradient({angle}, {color_from}, {color_to});\n}}"
                )
            if kind == "image":
                filename = value.get("file")
                if not filename:
                    return None
                position = value.get("position", "center")
                size = value.get("size", "cover")
                repeat = "no-repeat"
                fixed_line = "\nbody { background-attachment: fixed; }" if value.get(
                    "fixed") == "1" else ""
                return (
                    f"{BACKGROUND_COMMENT_PREFIX} (site/image) */\n"
                    f"body {{ background-image: url('assets/images/{filename}'); }}\n"
                    f"body {{ background-position:{position}; background-size:{size}; background-repeat:{repeat}; }}"
                    f"{fixed_line}"
                )
            if kind == "pattern":
                svg = value.get("svg", "")
                if not svg:
                    return None
                encoded = urllib.parse.quote(svg, safe="")
                return (
                    f"{BACKGROUND_COMMENT_PREFIX} (site/pattern) */\n"
                    "body::before {\n  content:\"\"; position:fixed; inset:0; z-index:-1;\n"
                    f"  background-image: url('data:image/svg+xml,{encoded}');\n  background-repeat: repeat;\n  opacity: 0.65;\n}}"
                )
            return None

        class_name = value.get(
            "class") or f"page-bg-{slugify(value.get('page', 'section'))}"
        if kind == "solid":
            color = value.get("color", "#0f172a")
            return f"{BACKGROUND_COMMENT_PREFIX} (page/solid) */\n.{class_name} {{ background: {color}; }}"
        if kind == "gradient":
            color_from = value.get("from", "#0ea5e9")
            color_to = value.get("to", "#a855f7")
            angle = value.get("angle", "135deg")
            return (
                f"{BACKGROUND_COMMENT_PREFIX} (page/gradient) */\n"
                f".{class_name} {{ background: linear-gradient({angle}, {color_from}, {color_to}); color:#fff; }}"
            )
        if kind == "image":
            filename = value.get("file")
            if not filename:
                return None
            position = value.get("position", "center")
            size = value.get("size", "cover")
            repeat = "no-repeat"
            lines = [
                f"{BACKGROUND_COMMENT_PREFIX} (page/image) */",
                f".{class_name} {{ background-image: url('assets/images/{filename}'); }}",
                f".{class_name} {{ background-position:{position}; background-size:{size}; background-repeat:{repeat}; }}",
            ]
            if value.get("fixed") == "1":
                lines.append(
                    f".{class_name}.bg-fixed {{ background-attachment: fixed; }}")
            return "\n".join(lines)
        if kind == "pattern":
            svg = value.get("svg", "")
            if not svg:
                return None
            encoded = urllib.parse.quote(svg, safe="")
            return (
                f"{BACKGROUND_COMMENT_PREFIX} (page/pattern) */\n"
                f".{class_name} {{ background-image: url('data:image/svg+xml,{encoded}'); background-repeat: repeat; }}"
            )
        return None

    def _apply_background_from_ui(self) -> None:
        if not self.project:
            return
        scope = self._background_scope_value()
        page = self._current_page()
        page_filename = page.filename if page else None
        if scope == "page" and not page_filename:
            QtWidgets.QMessageBox.information(
                self, "Select a page", "Choose a page before applying a page background.")
            return
        kind = self._background_kind_value()
        value: Dict[str, str] = {}
        if kind == "solid":
            value["color"] = self.bg_solid_color.color()
        elif kind == "gradient":
            value["from"] = self.bg_gradient_from.color()
            value["to"] = self.bg_gradient_to.color()
            value["angle"] = f"{self.bg_gradient_angle.value()}deg"
        elif kind == "image":
            path_str = self.bg_image_path.text().strip()
            if not path_str:
                QtWidgets.QMessageBox.warning(
                    self, "Choose an image", "Select an image to use as the background.")
                return
            path = Path(path_str)
            asset_name = self._ensure_background_image_asset(path)
            if not asset_name:
                return
            value["file"] = asset_name
            value["position"] = self.bg_image_position_combo.currentText()
            value["size"] = self.bg_image_size_combo.currentText()
            value["fixed"] = "1" if self.bg_image_fixed.isChecked() else "0"
        elif kind == "pattern":
            pattern_name = self.bg_pattern_combo.currentText()
            svg = BACKGROUND_PATTERN_PRESETS.get(pattern_name, "")
            if not svg:
                QtWidgets.QMessageBox.warning(
                    self, "Pattern unavailable", "Choose a different pattern preset.")
                return
            value["pattern"] = pattern_name
            value["svg"] = svg
        else:
            return
        if scope == "page" and page_filename:
            value["page"] = page_filename
            slug = slugify(Path(page_filename).stem)
            value.setdefault("class", f"page-bg-{slug}")
        spec = BackgroundSpec(scope=scope, kind=kind, value=value)
        self._store_background_spec(spec, page_filename)
        self._sync_background_css()
        self.set_dirty(True)
        if scope == "page" and page_filename:
            if self.bg_insert_markup.isChecked():
                self._insert_background_markup(spec)
            else:
                self._ensure_background_comment(spec)
        self._load_background_controls()
        self.update_preview()
        self.status_bar.showMessage("Background updated", 2500)

    def _reset_background_from_ui(self) -> None:
        scope = self._background_scope_value()
        page = self._current_page()
        page_filename = page.filename if page else None
        if scope == "page" and not page_filename:
            QtWidgets.QMessageBox.information(
                self, "Select a page", "Choose a page to reset its background.")
            return
        if not self._remove_background_spec(scope, page_filename):
            QtWidgets.QMessageBox.information(
                self, "Nothing to reset", "No background was set for this scope.")
            return
        self._sync_background_css()
        self.set_dirty(True)
        self._load_background_controls()
        self.update_preview()
        self.status_bar.showMessage("Background removed", 2000)

    def _on_background_kind_changed(self, index: int) -> None:
        if getattr(self, "bg_stack", None) is None:
            return
        self.bg_stack.setCurrentIndex(index)
        if getattr(self, "bg_pattern_combo", None) is not None and index == BACKGROUND_KIND_CHOICES.index("Pattern"):
            self._update_background_pattern_preview()

    def _on_background_scope_changed(self, index: int) -> None:  # noqa: ARG002
        self._load_background_controls()

    def _update_background_pattern_preview(self) -> None:
        if getattr(self, "bg_pattern_preview", None) is None:
            return
        pattern_name = self.bg_pattern_combo.currentText(
        ) if self.bg_pattern_combo is not None else ""
        svg = BACKGROUND_PATTERN_PRESETS.get(pattern_name, "")
        if not svg:
            self.bg_pattern_preview.setText("Pattern preview")
            self.bg_pattern_preview.setStyleSheet(
                "border:1px solid rgba(148,163,184,0.6); border-radius:4px;"
            )
            return
        encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        self.bg_pattern_preview.setText("")
        self.bg_pattern_preview.setStyleSheet(
            "border:1px solid rgba(148,163,184,0.6); border-radius:4px;"
            f" background-image:url(data:image/svg+xml;base64,{encoded});"
        )

    def _browse_background_image(self) -> None:
        start_dir = self.settings.get("last_background_dir", str(Path.home()))
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose background image",
            start_dir,
            "Images (*.png *.jpg *.jpeg *.gif *.svg *.webp)",
        )
        if path:
            self.settings.set("last_background_dir", str(Path(path).parent))
            if getattr(self, "bg_image_path", None) is not None:
                self.bg_image_path.setText(path)

    def _ensure_background_image_asset(self, path: Path) -> Optional[str]:
        if not path.exists():
            QtWidgets.QMessageBox.warning(
                self, "Missing file", f"Could not find {path}.")
            return None
        asset = self._asset_from_file(path)
        if asset is None:
            return None
        for existing in self.project.images:
            if existing.data_base64 == asset.data_base64:
                return existing.name
        asset.name = self._unique_asset_name(asset.name)
        self.project.images.append(asset)
        self._refresh_assets()
        self.status_bar.showMessage(
            f"Added background image {asset.name}", 2000)
        return asset.name

    def _insert_background_markup(self, spec: BackgroundSpec) -> None:
        class_name = spec.value.get("class")
        if not class_name:
            return
        snippet = (
            f"\n<section class=\"bg-cover {class_name}\">\n"
            "  <div class=\"glass tile\">\n"
            "    <h2>Headline on image</h2>\n"
            "    <p class=\"muted\">Your message goes here.</p>\n"
            "    <a class=\"btn neon-btn\" href=\"#\">Explore</a>\n"
            "  </div>\n"
            "</section>\n"
        )
        cursor = self.html_editor.textCursor()
        cursor.insertText(snippet)

    def _ensure_background_comment(self, spec: BackgroundSpec) -> None:
        class_name = spec.value.get("class")
        if not class_name:
            return
        comment = f"<!-- Add class \"{class_name}\" to a section to use this background -->"
        html = self.html_editor.toPlainText()
        if comment in html:
            return
        cursor = self.html_editor.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.Start)
        cursor.insertText(comment + "\n")

    def _load_background_controls(self) -> None:
        if getattr(self, "bg_kind_combo", None) is None:
            return
        scope = self._background_scope_value()
        page = self._current_page()
        page_filename = page.filename if page else None
        spec = self._background_spec_for_scope(scope, page_filename)
        kind_index = 0
        if spec:
            for idx, label in enumerate(BACKGROUND_KIND_CHOICES):
                if label.lower() == spec.kind:
                    kind_index = idx
                    break
        self.bg_kind_combo.blockSignals(True)
        self.bg_kind_combo.setCurrentIndex(kind_index)
        self.bg_kind_combo.blockSignals(False)
        self.bg_stack.setCurrentIndex(kind_index)

        if spec and spec.kind == "solid":
            self.bg_solid_color.setColor(spec.value.get(
                "color", self.project.palette.get("surface", "#0f172a")))
        else:
            default_solid = self.project.palette.get("surface", "#f8fafc")
            self.bg_solid_color.setColor(default_solid)

        if spec and spec.kind == "gradient":
            self.bg_gradient_from.setColor(
                spec.value.get("from", DEFAULT_GRADIENT["from"]))
            self.bg_gradient_to.setColor(
                spec.value.get("to", DEFAULT_GRADIENT["to"]))
            angle_val = spec.value.get(
                "angle", DEFAULT_GRADIENT["angle"]).replace("deg", "")
            try:
                self.bg_gradient_angle.setValue(int(float(angle_val)))
            except ValueError:
                self.bg_gradient_angle.setValue(
                    int(DEFAULT_GRADIENT["angle"].replace("deg", "")))
        else:
            self.bg_gradient_from.setColor(DEFAULT_GRADIENT["from"])
            self.bg_gradient_to.setColor(DEFAULT_GRADIENT["to"])
            self.bg_gradient_angle.setValue(
                int(DEFAULT_GRADIENT["angle"].replace("deg", "")))

        if spec and spec.kind == "image":
            self.bg_image_path.setText(spec.value.get("file", ""))
            self.bg_image_position_combo.setCurrentText(
                spec.value.get("position", "center"))
            self.bg_image_size_combo.setCurrentText(
                spec.value.get("size", "cover"))
            self.bg_image_fixed.setChecked(spec.value.get("fixed") == "1")
        else:
            self.bg_image_path.clear()
            self.bg_image_position_combo.setCurrentText("center")
            self.bg_image_size_combo.setCurrentText("cover")
            self.bg_image_fixed.setChecked(False)

        if spec and spec.kind == "pattern":
            pattern_name = spec.value.get("pattern")
            if pattern_name in BACKGROUND_PATTERN_PRESETS:
                self.bg_pattern_combo.setCurrentText(pattern_name)
        else:
            if self.bg_pattern_combo.count():
                self.bg_pattern_combo.setCurrentIndex(0)

        self.bg_insert_markup.setChecked(False)
        self._update_background_pattern_preview()

    # Theme helpers -----------------------------------------------------
    def _compose_css(
        self,
        *,
        extra_override: Optional[str] = None,
        helper_override: Optional[str] = None,
    ) -> str:
        if not self.project:
            return ""
        current_css = self.css_editor.toPlainText()
        helper_block = helper_override or extract_css_block(
            current_css, CSS_HELPERS_SENTINEL) or CSS_HELPERS_BLOCK
        extra_block = extra_override
        if extra_block is None:
            extra_block = extract_css_block(
                current_css, TEMPLATE_EXTRA_SENTINEL)
        base_css = generate_base_css(
            self.project.palette,
            self.project.fonts,
            self.project.radius_scale,
            self.project.shadow_level,
        )
        css = ensure_block(base_css, CSS_HELPERS_SENTINEL, helper_block)
        css = ensure_block(css, BG_HELPERS_SENTINEL, BG_HELPERS_BLOCK)
        css = ensure_block(css, GRADIENT_HELPERS_SENTINEL,
                           gradient_helpers_block(self.project.gradients))
        css = ensure_block(css, ANIM_HELPERS_SENTINEL,
                           animation_helpers_block(self.project.motion_pref))
        if extra_block:
            css = ensure_block(css, TEMPLATE_EXTRA_SENTINEL,
                               f"{TEMPLATE_EXTRA_SENTINEL}\n{extra_block}")
        css = self._strip_background_blocks(css)
        if self.project.backgrounds:
            blocks = [self._build_background_block(
                spec) for spec in self.project.backgrounds]
            blocks = [block for block in blocks if block]
            if blocks:
                combined = f"{BACKGROUND_BLOCK_START}\n" + \
                    "\n\n".join(blocks) + f"\n{BACKGROUND_BLOCK_END}"
                css = (css + "\n\n" + combined).strip() if css else combined
        return css

    def apply_theme(self) -> None:
        if not self.project:
            return
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
        current_css = self.css_editor.toPlainText()
        helper_block = extract_css_block(
            current_css, CSS_HELPERS_SENTINEL) or CSS_HELPERS_BLOCK
        existing_extra = extract_css_block(
            current_css, TEMPLATE_EXTRA_SENTINEL)
        clean_extra = strip_theme_extras(existing_extra)
        style = THEME_STYLE_PRESETS.get(theme)
        if theme in THEME_PRESETS:
            palette = dict(THEME_PRESETS[theme])
            self.design_primary.setText(palette["primary"])
            self.design_surface.setText(palette["surface"])
            self.design_text.setText(palette["text"])
        if style:
            fonts = style.get("fonts", fonts)
            gradient_info = style.get("gradients")
            if isinstance(gradient_info, dict):
                grad_from = str(gradient_info.get(
                    "from", DEFAULT_GRADIENT["from"]))
                grad_to = str(gradient_info.get("to", DEFAULT_GRADIENT["to"]))
                grad_angle = str(gradient_info.get(
                    "angle", DEFAULT_GRADIENT["angle"]))
                self.project.gradients = {
                    "from": grad_from, "to": grad_to, "angle": grad_angle}
                self.gradient_from.blockSignals(True)
                self.gradient_to.blockSignals(True)
                self.gradient_angle_combo.blockSignals(True)
                self.gradient_from.setText(grad_from)
                self.gradient_to.setText(grad_to)
                self.gradient_angle_combo.setCurrentText(grad_angle)
                self.gradient_from.blockSignals(False)
                self.gradient_to.blockSignals(False)
                self.gradient_angle_combo.blockSignals(False)
            if style.get("radius_scale") is not None:
                raw_radius = style.get("radius_scale", 1.0)
                if isinstance(raw_radius, (int, float, str)):
                    try:
                        radius_val = float(raw_radius)
                    except (TypeError, ValueError):
                        radius_val = 1.0
                else:
                    radius_val = 1.0
                self.project.radius_scale = radius_val
                self.radius_spin.blockSignals(True)
                self.radius_spin.setValue(float(radius_val))
                self.radius_spin.blockSignals(False)
            if style.get("shadow_level") in SHADOW_LEVELS:
                shadow_val = str(style.get("shadow_level"))
                self.project.shadow_level = shadow_val
                self.shadow_combo.blockSignals(True)
                self.shadow_combo.setCurrentText(shadow_val)
                self.shadow_combo.blockSignals(False)
            extra_css = str(style.get("extra_css", "")).strip()
            clean_extra = clean_extra.strip()
            if extra_css:
                clean_extra = f"{clean_extra}\n\n{extra_css}".strip(
                ) if clean_extra else extra_css
        self.project.palette = palette
        if not isinstance(fonts, dict):
            fonts = {"heading": str(fonts), "body": str(fonts)}
        self.project.fonts = fonts
        self.project.theme_preset = theme
        self.design_heading_font.setCurrentText(fonts.get("heading", ""))
        self.design_body_font.setCurrentText(fonts.get("body", ""))
        css = self._compose_css(
            extra_override=clean_extra or None, helper_override=helper_block)
        self.css_editor.setPlainText(css)
        self.project.css = css
        self._update_color_swatches()
        self._update_gradient_preview()
        self.set_dirty(True)
        self.update_preview()
        self.status_bar.showMessage("Theme applied", 4000)

    def add_css_helpers(self) -> None:
        css = self.css_editor.toPlainText()
        updated = ensure_block(css, CSS_HELPERS_SENTINEL, CSS_HELPERS_BLOCK)
        updated = ensure_block(updated, BG_HELPERS_SENTINEL, BG_HELPERS_BLOCK)
        if updated == css:
            QtWidgets.QMessageBox.information(
                self, "Already added", "CSS helpers are already in your stylesheet.")
            return
        self.css_editor.setPlainText(updated)
        self.project.css = updated
        self.update_preview()
        self.set_dirty(True)

    def apply_gradient_helpers(self) -> None:
        if not self.project:
            return
        grad_from = self.gradient_from.text(
        ).strip() or DEFAULT_GRADIENT["from"]
        grad_to = self.gradient_to.text().strip() or DEFAULT_GRADIENT["to"]
        grad_angle = self.gradient_angle_combo.currentText(
        ).strip() or DEFAULT_GRADIENT["angle"]
        self.project.gradients = {"from": grad_from,
                                  "to": grad_to, "angle": grad_angle}
        css = self._compose_css()
        self.css_editor.setPlainText(css)
        self.project.css = css
        self._update_gradient_preview()
        self.set_dirty(True)
        self.update_preview()
        self.status_bar.showMessage("Gradient helpers updated", 3000)

    def insert_gradient_hero(self) -> None:
        if not self.project:
            return
        cursor = self.html_editor.textCursor()
        if cursor.hasSelection():
            self.wrap_selection_with(
                '<section class="hero bg-gradient text-on-gradient">\n', '\n</section>')
        else:
            snippet = """\n\n<section class="hero bg-gradient text-on-gradient">\n  <h2>Gradient hero</h2>\n  <p>Add your pitch here.</p>\n  <a class="btn btn-gradient" href="#">Call to action</a>\n</section>\n\n"""
            cursor.insertText(snippet)
        self.set_dirty(True)
        self.update_preview()
        self.status_bar.showMessage("Gradient hero inserted", 2500)

    def _update_color_swatches(self) -> None:
        def set_swatch(label: QtWidgets.QLabel, color: str) -> None:
            label.setStyleSheet(
                f"background: {color}; border: 1px solid rgba(148,163,184,0.6); border-radius: 4px;"
            )

        set_swatch(self.primary_swatch, self.design_primary.text(
        ).strip() or DEFAULT_PALETTE["primary"])
        set_swatch(self.surface_swatch, self.design_surface.text(
        ).strip() or DEFAULT_PALETTE["surface"])
        set_swatch(self.text_swatch, self.design_text.text().strip()
                   or DEFAULT_PALETTE["text"])

    def _update_gradient_preview(self) -> None:
        grad_from = self.gradient_from.text(
        ).strip() or DEFAULT_GRADIENT["from"]
        grad_to = self.gradient_to.text().strip() or DEFAULT_GRADIENT["to"]
        grad_angle = self.gradient_angle_combo.currentText(
        ).strip() or DEFAULT_GRADIENT["angle"]
        self.gradient_preview.setStyleSheet(
            f"background: linear-gradient({grad_angle}, {grad_from}, {grad_to});"
            " border: 1px solid rgba(148,163,184,0.6); border-radius: 4px;"
        )

    def _on_radius_scale_changed(self, value: float) -> None:
        if not self.project:
            return
        self.project.radius_scale = float(value)
        css = self._compose_css()
        self.css_editor.setPlainText(css)
        self.project.css = css
        self.set_dirty(True)
        self.update_preview()
        self.status_bar.showMessage("Radius scale updated", 2000)

    def _on_shadow_level_changed(self, value: str) -> None:
        if not self.project or value not in SHADOW_LEVELS:
            return
        self.project.shadow_level = value
        css = self._compose_css()
        self.css_editor.setPlainText(css)
        self.project.css = css
        self.set_dirty(True)
        self.update_preview()
        self.status_bar.showMessage("Shadow level updated", 2000)

    def _toggle_scroll_animations(self, enabled: bool) -> None:
        if not self.project:
            return
        self.project.use_scroll_animations = bool(enabled)
        self.set_dirty(True)
        self.update_preview()
        message = "Scroll animations enabled" if enabled else "Scroll animations disabled"
        self.status_bar.showMessage(message, 2500)

    def _on_motion_pref_changed(self) -> None:
        if not self.project:
            return
        label = self.motion_pref_combo.currentText()
        pref = MOTION_PREF_OPTIONS.get(label, "respect")
        self.project.motion_pref = pref
        css = self._compose_css()
        self.css_editor.setPlainText(css)
        self.project.css = css
        self.set_dirty(True)
        self.update_preview()
        self.status_bar.showMessage("Motion preference updated", 2500)

    def _on_motion_defaults_changed(self) -> None:
        if not self.project:
            return
        effect = self.motion_effect_combo.currentText() or "none"
        easing_label = self.motion_easing_combo.currentText()
        easing = MOTION_EASINGS.get(
            easing_label, MOTION_EASINGS["Gentle ease"])
        self.project.motion_default_effect = effect
        self.project.motion_default_easing = easing
        self.project.motion_default_duration = int(
            self.motion_duration_spin.value())
        self.project.motion_default_delay = int(self.motion_delay_spin.value())
        self.set_dirty(True)

    def _motion_style_inline(self) -> str:
        if not self.project:
            return ""
        duration = max(int(self.project.motion_default_duration), 0)
        delay = max(int(self.project.motion_default_delay), 0)
        easing = self.project.motion_default_easing or MOTION_EASINGS["Gentle ease"]
        return (
            f' style="--anim-duration:{duration}ms;--anim-delay:{delay}ms;--anim-ease:{easing};"'
            if duration or delay or easing
            else ""
        )

    def _apply_motion_wrapper(self, effect: str, *, loop: bool = False) -> None:
        if not self.project:
            return
        if not loop and effect == "none":
            return
        prefix: str
        if loop:
            prefix = f'<div class="anim anim-float"{self._motion_style_inline()}>'
        elif self.project.use_scroll_animations:
            prefix = f'<div data-animate="{effect}"{self._motion_style_inline()}>'
        else:
            classes = "anim"
            if effect:
                classes += f" anim-{effect}"
            prefix = f'<div class="{classes}"{self._motion_style_inline()}>'
        self.wrap_selection_with(prefix, "</div>")
        self.set_dirty(True)
        self.update_preview()
        self.status_bar.showMessage("Animation wrapper applied", 2500)

    def wrap_selection_default_motion(self) -> None:
        if not self.project:
            return
        self._apply_motion_wrapper(self.project.motion_default_effect)

    # External assets management --------------------------------------
    def _refresh_external_assets_table(self, select_row: Optional[int] = None) -> None:
        if getattr(self, "external_table", None) is None:
            return
        table = self.external_table
        table.blockSignals(True)
        table.setRowCount(0)
        if not self.project or not self.project.external:
            table.blockSignals(False)
            return
        total = len(self.project.external)
        for row, asset in enumerate(self.project.external):
            table.insertRow(row)
            kind_text = asset.kind.upper() if asset.kind else "CSS"
            kind_item = QtWidgets.QTableWidgetItem(kind_text)
            kind_item.setFlags(Qt.ItemFlag.ItemIsSelectable |
                               Qt.ItemFlag.ItemIsEnabled)
            table.setItem(row, 0, kind_item)
            mode_label = "Local" if asset.mode == "local" else "CDN"
            mode_item = QtWidgets.QTableWidgetItem(mode_label)
            mode_item.setFlags(Qt.ItemFlag.ItemIsSelectable |
                               Qt.ItemFlag.ItemIsEnabled)
            table.setItem(row, 1, mode_item)
            href_display = asset.href
            if asset.mode == "local" and asset.original_url:
                tooltip = f"Local: {asset.href}\nSource: {asset.original_url}"
            else:
                tooltip = asset.href
            url_item = QtWidgets.QTableWidgetItem(href_display)
            url_item.setFlags(Qt.ItemFlag.ItemIsSelectable |
                              Qt.ItemFlag.ItemIsEnabled)
            url_item.setToolTip(tooltip)
            table.setItem(row, 2, url_item)
            table.setCellWidget(
                row, 3, self._create_external_action_widget(row, total))
        table.blockSignals(False)
        if select_row is not None and 0 <= select_row < table.rowCount():
            table.selectRow(select_row)
        elif table.rowCount() and table.currentRow() == -1:
            table.selectRow(0)

    def _create_external_action_widget(self, row: int, total_rows: int) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget(self.external_table)
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        btn_up = QtWidgets.QToolButton(container)
        style = self.style()
        if style is not None:
            btn_up.setIcon(style.standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_ArrowUp))
        btn_up.setToolTip("Move up")
        btn_up.setAutoRaise(True)
        btn_up.setEnabled(row > 0)
        btn_up.clicked.connect(lambda checked=False,
                               r=row: self._move_external_asset(r, -1))
        layout.addWidget(btn_up)
        btn_down = QtWidgets.QToolButton(container)
        style = self.style()
        if style is not None:
            btn_down.setIcon(style.standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_ArrowDown))
        btn_down.setToolTip("Move down")
        btn_down.setAutoRaise(True)
        btn_down.setEnabled(row < total_rows - 1)
        btn_down.clicked.connect(lambda checked=False,
                                 r=row: self._move_external_asset(r, 1))
        layout.addWidget(btn_down)
        btn_remove = QtWidgets.QToolButton(container)
        style = self.style()
        if style is not None:
            btn_remove.setIcon(style.standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_DialogCloseButton))
        btn_remove.setToolTip("Remove")
        btn_remove.setAutoRaise(True)
        btn_remove.clicked.connect(
            lambda checked=False, r=row: self._remove_external_asset(r))
        layout.addWidget(btn_remove)
        layout.addStretch()
        return container

    def _add_external_asset(self, kind: str) -> None:
        if not self.project:
            return
        title = "Add external CSS" if kind == "css" else "Add external JS"
        prompt = "Enter the stylesheet URL" if kind == "css" else "Enter the script URL"
        url, ok = QtWidgets.QInputDialog.getText(self, title, prompt)
        if not ok:
            return
        url = url.strip()
        if not url:
            return
        parsed = urllib.parse.urlparse(url)
        if not parsed.scheme:
            if url.startswith("//"):
                url = "https:" + url
                parsed = urllib.parse.urlparse(url)
            else:
                QtWidgets.QMessageBox.warning(
                    self, "Invalid URL", "Enter a full https:// URL.")
                return
        if parsed.scheme not in {"http", "https"}:
            QtWidgets.QMessageBox.warning(
                self, "Unsupported scheme", "Only HTTP and HTTPS URLs are supported.")
            return
        canonical = url
        for existing in self.project.external:
            source = existing.original_url if existing.mode == "local" and existing.original_url else existing.href
            if existing.kind == kind and source == canonical:
                QtWidgets.QMessageBox.information(
                    self, "Already added", "This asset is already in your list.")
                return
        asset = ExternalAsset(kind=kind, mode="cdn",
                              href=canonical, original_url=canonical)
        self.project.external.append(asset)
        self._refresh_external_assets_table(len(self.project.external) - 1)
        self.set_dirty(True)
        self.update_preview()
        self.status_bar.showMessage("External asset added", 2000)

    def _selected_external_rows(self) -> List[int]:
        if getattr(self, "external_table", None) is None:
            return []
        selection_model = cast(
            Optional[QtCore.QItemSelectionModel], self.external_table.selectionModel())
        if selection_model is None:
            return []
        return sorted({index.row() for index in selection_model.selectedRows()})

    def _move_external_asset(self, row: int, delta: int) -> None:
        if not self.project:
            return
        new_index = row + delta
        if row < 0 or new_index < 0 or row >= len(self.project.external) or new_index >= len(self.project.external):
            return
        self.project.external[row], self.project.external[new_index] = (
            self.project.external[new_index],
            self.project.external[row],
        )
        self._refresh_external_assets_table(new_index)
        self.set_dirty(True)
        self.update_preview()
        self.status_bar.showMessage("External assets reordered", 2000)

    def _remove_external_asset(self, row: int) -> None:
        if not self.project:
            return
        if row < 0 or row >= len(self.project.external):
            return
        asset = self.project.external[row]
        label = f"Remove {asset.kind.upper()} asset?"
        if (
            QtWidgets.QMessageBox.question(
                self,
                "Remove external asset",
                f"{label}\n{asset.href}",
            )
            != QtWidgets.QMessageBox.StandardButton.Yes
        ):
            return
        del self.project.external[row]
        next_row = min(row, len(self.project.external) -
                       1) if self.project.external else None
        self._refresh_external_assets_table(next_row)
        self.set_dirty(True)
        self.update_preview()
        self.status_bar.showMessage("External asset removed", 2000)

    def _download_external_asset(self) -> None:
        if not self.project or not self.project.external:
            QtWidgets.QMessageBox.information(
                self, "No assets", "Add an external link first.")
            return
        rows = self._selected_external_rows()
        if not rows:
            QtWidgets.QMessageBox.information(
                self, "Select asset", "Choose an external link to download.")
            return
        changed = False
        errors: List[str] = []
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for row in rows:
                success, error = self._download_external_row(row)
                if success:
                    changed = True
                elif error:
                    errors.append(error)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._refresh_external_assets_table(rows[0])
        if changed:
            self.set_dirty(True)
            self.update_preview()
            self.status_bar.showMessage(
                "Downloaded external assets for offline use", 3000)
        if errors:
            summary = "\n".join(errors[:3])
            if len(errors) > 3:
                summary += "\n…"
            QtWidgets.QMessageBox.warning(self, "Download issues", summary)
        if not changed and not errors:
            QtWidgets.QMessageBox.information(
                self, "Nothing to download", "The selected assets are already local.")

    def _download_external_row(self, row: int) -> Tuple[bool, Optional[str]]:
        if not self.project or row < 0 or row >= len(self.project.external):
            return False, None
        asset = self.project.external[row]
        if asset.mode != "cdn":
            return False, None
        url = asset.href
        try:
            with urllib.request.urlopen(url) as response:
                data = response.read()
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            return False, f"{url}: {reason}"
        except Exception as exc:  # pragma: no cover - network runtime guard
            return False, f"{url}: {exc}"
        if not data:
            return False, f"{url}: empty response"
        filename = self._unique_external_filename(
            Path(urllib.parse.urlparse(url).path).name or url, asset.kind, row)
        rel_path = Path("assets") / "vendor" / filename
        asset.original_url = asset.original_url or url
        asset.mode = "local"
        asset.href = rel_path.as_posix()
        asset.data_base64 = base64.b64encode(data).decode("ascii")
        asset.sri = None
        return True, None

    def _unique_external_filename(
        self, filename: str, kind: str, exclude_index: Optional[int] = None
    ) -> str:
        if not self.project:
            return filename
        normalized_kind = "css" if kind == "css" else "js"
        suffix = Path(filename).suffix.lower()
        if suffix not in {".css", ".js"}:
            suffix = ".css" if normalized_kind == "css" else ".js"
        raw_base = Path(filename).stem or f"{normalized_kind}-asset"
        base_slug = slugify(raw_base) or f"{normalized_kind}-asset"
        candidate = f"{base_slug}{suffix}"
        existing = {
            Path(item.href).name
            for idx, item in enumerate(self.project.external)
            if item.mode == "local" and (exclude_index is None or idx != exclude_index)
        }
        counter = 2
        while candidate in existing:
            candidate = f"{base_slug}-{counter}{suffix}"
            counter += 1
        return candidate

    # Asset management --------------------------------------------------
    def _refresh_assets(self) -> None:
        self.asset_list.clear()
        for asset in self.project.images:
            item = QtWidgets.QListWidgetItem(
                f"{asset.name} ({asset.width}×{asset.height})")
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
            self.set_dirty(True)
            self._refresh_assets()
            self.status_bar.showMessage(f"Added {added} asset(s)", 3000)
            self.update_preview()

    def _asset_from_file(self, path: Path) -> Optional[AssetImage]:
        if not path.exists():
            return None
        image = QtGui.QImage(str(path))
        if image.isNull():
            QtWidgets.QMessageBox.warning(
                self, "Unsupported", f"Could not load {path.name}.")
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
        existing = {
            asset.name for asset in self.project.images if asset.name != exclude}
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
        scaled = pixmap.scaled(240, 160, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        self.asset_preview.setPixmap(scaled)

    def _rename_asset(self) -> None:
        row = self.asset_list.currentRow()
        if row < 0 or row >= len(self.project.images):
            return
        asset = self.project.images[row]
        new_name, ok = QtWidgets.QInputDialog.getText(
            self, "Rename asset", "File name", text=asset.name)
        if not ok or not new_name.strip():
            return
        new_name = self._unique_asset_name(
            new_name.strip(), exclude=asset.name)
        asset.name = new_name
        self._refresh_assets()
        self.set_dirty(True)

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
        self.set_dirty(True)

    def _insert_image_dialog(self) -> None:
        row = self.asset_list.currentRow()
        if row < 0 or row >= len(self.project.images):
            QtWidgets.QMessageBox.information(
                self, "Select image", "Choose an image first.")
            return
        asset = self.project.images[row]
        alt, ok = QtWidgets.QInputDialog.getText(
            self, "Alt text", "Describe the image", text="")
        if not ok:
            return
        width, ok_w = QtWidgets.QInputDialog.getInt(
            self, "Width", "Width (px)", value=max(1, asset.width), min=1)
        if not ok_w:
            return
        height, ok_h = QtWidgets.QInputDialog.getInt(
            self, "Height", "Height (px)", value=max(1, asset.height), min=1)
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

    def _set_cover_image_from_asset(self) -> None:
        if not self.project or not self.project.images:
            return
        row = self.asset_list.currentRow()
        if row < 0 or row >= len(self.project.images):
            QtWidgets.QMessageBox.information(
                self, "Select image", "Choose an image to use as the cover.")
            return
        asset = self.project.images[row]
        self.project.cover_asset_name = asset.name
        self._maybe_render_cover(force=True)
        self.set_dirty(True)
        self.status_bar.showMessage(f"{asset.name} set as cover image", 3000)

    def _generate_placeholder_asset(self) -> None:
        if not self.project:
            return
        presets = ["1280×720", "1600×900", "1920×1080", "Custom…"]
        choice, ok = QtWidgets.QInputDialog.getItem(
            self,
            "Placeholder size",
            "Choose a placeholder size",
            presets,
            0,
            False,
        )
        if not ok or not choice:
            return
        if "×" in choice and choice != "Custom…":
            parts = choice.replace("×", "x").split("x")
            try:
                width, height = int(parts[0]), int(parts[1])
            except (ValueError, IndexError):
                width, height = 1280, 720
        else:
            width, ok_w = QtWidgets.QInputDialog.getInt(
                self, "Width", "Placeholder width (px)", value=1280, min=100, max=4000)
            if not ok_w:
                return
            height, ok_h = QtWidgets.QInputDialog.getInt(
                self, "Height", "Placeholder height (px)", value=720, min=100, max=4000)
            if not ok_h:
                return
        svg = generate_svg_placeholder(width, height, self.project.palette)
        data = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        name = self._unique_asset_name(f"placeholder-{width}x{height}.svg")
        asset = AssetImage(name=name, data_base64=data,
                           width=width, height=height, mime="image/svg+xml")
        self.project.images.append(asset)
        self._refresh_assets()
        self.set_dirty(True)
        self.status_bar.showMessage(
            f"Placeholder {width}×{height} added", 4000)
        data_uri = "data:image/svg+xml;base64," + \
            base64.b64encode(svg.encode("utf-8")).decode("ascii")
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(data_uri)
        self._maybe_render_cover(force=True)

    # File operations ---------------------------------------------------
    def open_project_dialog(self) -> None:
        self._flush_editors_to_model()
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
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Could not open project:\n{exc}")
            return
        self.project = result.project
        self.project_path = Path(path)
        self.project.output_dir = str(self.project_path.parent)
        if result.migrated:
            QtWidgets.QMessageBox.information(
                self, "Upgraded", "Project upgraded to the latest format.")
        self._load_project_into_ui()
        self.update_window_title()
        self.update_preview()
        self._maybe_render_cover(force=True)
        self.set_dirty(False)
        self.recents.add_or_bump(self.project_path, self.project)
        tile_path = Path(
            self.project.cover_tile_path) if self.project.cover_tile_path else None
        if self.project.cover_path:
            self.recents.set_cover(self.project_path, Path(
                self.project.cover_path), tile_path=tile_path)
        elif tile_path:
            self.recents.set_thumbnail(self.project_path, tile_path)

    def save_project(self) -> None:
        if self.project_path is None:
            self.save_project_as()
            return
        self._flush_editors_to_model()
        self._maybe_render_cover(force=True)
        try:
            save_project(self.project_path, self.project)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Could not save:\n{exc}")
            return
        self.status_bar.showMessage("Project saved", 2000)
        self.recents.add_or_bump(self.project_path, self.project)
        tile_path = Path(
            self.project.cover_tile_path) if self.project.cover_tile_path else None
        if self.project.cover_path:
            self.recents.set_cover(self.project_path, Path(
                self.project.cover_path), tile_path=tile_path)
        elif tile_path:
            self.recents.set_thumbnail(self.project_path, tile_path)
        self.set_dirty(False)

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
        self._maybe_render_cover(force=True)
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
        QtWidgets.QMessageBox.information(
            self, "Export complete", f"Your site was exported to:\n{out_dir}")

    def export_zip(self) -> None:
        if not self.project:
            return
        self._flush_editors_to_model()
        self._maybe_render_cover(force=True)
        out_zip, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save ZIP as…",
            "",
            "ZIP archive (*.zip)",
        )
        if not out_zip:
            return
        if not out_zip.lower().endswith(".zip"):
            out_zip += ".zip"
        tmp_dir = tempfile.mkdtemp(prefix="webineer_publish_")
        try:
            render_project(self.project, Path(tmp_dir))
            with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(tmp_dir):
                    for filename in files:
                        file_path = os.path.join(root, filename)
                        arcname = os.path.relpath(file_path, tmp_dir)
                        zf.write(file_path, arcname)
            QtWidgets.QMessageBox.information(
                self, "ZIP created", f"Archive saved to:\n{out_zip}")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"ZIP export failed:\n{exc}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def open_publish_dialog(self) -> None:
        dlg = PublishDialog(self)
        dlg.btn_export.clicked.connect(self.export_project)
        dlg.btn_zip.clicked.connect(self.export_zip)
        dlg.exec()

    # AI assistant -----------------------------------------------------
    def build_ai_dock(self) -> None:
        dock = QtWidgets.QDockWidget("AI Assistant", self)
        dock.setObjectName("aiDock")
        widget = QtWidgets.QWidget(dock)
        layout = QtWidgets.QVBoxLayout(widget)

        prompt = QtWidgets.QPlainTextEdit(widget)
        prompt.setPlaceholderText(
            "Describe what you want: e.g., ‘Suggest a 3-column features section’.")

        buttons = QtWidgets.QHBoxLayout()
        btn_suggest = QtWidgets.QPushButton("Suggest Section", widget)
        btn_css = QtWidgets.QPushButton("Suggest CSS Tweak", widget)
        btn_explain = QtWidgets.QPushButton("Explain Current Page", widget)
        buttons.addWidget(btn_suggest)
        buttons.addWidget(btn_css)
        buttons.addWidget(btn_explain)

        output = QtWidgets.QPlainTextEdit(widget)
        output.setReadOnly(True)

        layout.addWidget(prompt)
        layout.addLayout(buttons)
        layout.addWidget(QtWidgets.QLabel("Output", widget))
        layout.addWidget(output)
        widget.setLayout(layout)
        dock.setWidget(widget)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self.ai_dock = dock
        self.ai_prompt = prompt
        self.ai_output = output

        def run_ai(kind: str) -> None:
            if self.ai_output is None or self.ai_prompt is None:
                return
            if not self.project:
                self.ai_output.setPlainText("Open a project first.")
                return
            current_html = self.html_editor.toPlainText()
            css = self.css_editor.toPlainText()
            site = self.project.name if self.project else "Untitled"
            prompt_text = self.ai_prompt.toPlainText()
            prompt_payload = (
                f"[Task: {kind}]\n[Site: {site}]\n[Current page HTML]:\n{current_html}\n\n"
                f"[Global CSS]:\n{css}\n\n[User request]:\n{prompt_text}"
            )
            self.ai_output.setPlainText("Thinking…")
            thread = QThread(self)
            worker = _AIWorker(prompt_payload)
            worker.moveToThread(thread)

            def handle_finish(text: str) -> None:
                if self.ai_output is not None:
                    self.ai_output.setPlainText(text)
                thread.quit()

            def handle_error(message: str) -> None:
                if self.ai_output is not None:
                    self.ai_output.setPlainText(f"Error: {message}")
                thread.quit()

            def cleanup() -> None:
                if thread in self._ai_threads:
                    self._ai_threads.remove(thread)
                if worker in self._ai_workers:
                    self._ai_workers.remove(worker)
                worker.deleteLater()
                thread.deleteLater()

            worker.finished.connect(handle_finish)
            worker.errored.connect(handle_error)
            thread.finished.connect(cleanup)
            thread.started.connect(worker.run)
            self._ai_threads.append(thread)
            self._ai_workers.append(worker)
            thread.start()

        btn_suggest.clicked.connect(lambda: run_ai("Propose an HTML snippet"))
        btn_css.clicked.connect(lambda: run_ai(
            "Propose a focused CSS improvement"))
        btn_explain.clicked.connect(lambda: run_ai(
            "Explain the structure and accessible improvements"))

    def toggle_ai_dock(self) -> None:
        if self.ai_dock is None:
            self.build_ai_dock()
        if self.ai_dock is None:
            return
        visible = self.ai_dock.isVisible()
        self.ai_dock.setVisible(not visible)
        if not visible:
            self.ai_dock.raise_()
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
        if not self.maybe_save_before("quitting"):
            event.ignore()
            return
        if self._preview_tmp and os.path.isdir(self._preview_tmp):
            shutil.rmtree(self._preview_tmp, ignore_errors=True)
        event.accept()

    def show_tab(self, name: str) -> None:
        # MainWindow does not have nav_list; this method is a no-op or should be removed.
        pass


class _AIWorker(QObject):
    finished = pyqtSignal(str)
    errored = pyqtSignal(str)

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt

    def run(self) -> None:
        try:
            import os

            try:
                import requests
            except ModuleNotFoundError:
                self.errored.emit(
                    "Install the 'requests' package to enable AI suggestions.")
                return

            key = os.environ.get("OPENAI_API_KEY", "")
            if not key:
                self.errored.emit("Set OPENAI_API_KEY in your environment.")
                return
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": self.prompt}],
                    "temperature": 0.2,
                },
                timeout=60,
            )
            payload = response.json()
            if response.status_code >= 400 or "error" in payload:
                message = payload.get("error", {}).get(
                    "message", "Request failed")
                self.errored.emit(str(message))
                return
            choices = payload.get("choices") or []
            text = choices[0].get("message", {}).get(
                "content", "") if choices else ""
            if not text:
                text = "No response."
            self.finished.emit(text.strip())
        except Exception as exc:  # noqa: BLE001
            self.errored.emit(str(exc))


class PublishDialog(QtWidgets.QDialog):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Publish your site")
        self.resize(540, 380)
        layout = QtWidgets.QVBoxLayout(self)

        export_group = QtWidgets.QGroupBox("Export options", self)
        export_layout = QtWidgets.QVBoxLayout(export_group)
        btn_export = QtWidgets.QPushButton("Export to folder…", export_group)
        btn_zip = QtWidgets.QPushButton("Create ZIP archive…", export_group)
        export_layout.addWidget(btn_export)
        export_layout.addWidget(btn_zip)

        guides_group = QtWidgets.QGroupBox("Guides & hosting", self)
        guides_layout = QtWidgets.QGridLayout(guides_group)

        def link_btn(caption: str, url: str) -> QtWidgets.QPushButton:
            button = QtWidgets.QPushButton(caption, guides_group)
            button.clicked.connect(lambda checked=False,
                                   link=url: open_url(link))
            return button

        guides_layout.addWidget(link_btn(
            "GitHub Pages quickstart", "https://docs.github.com/en/pages/quickstart"), 0, 0)
        guides_layout.addWidget(
            link_btn("Static hosting tips (web.dev/hosting)",
                     "https://web.dev/learn/pwa/hosting/"),
            0,
            1,
        )
        guides_layout.addWidget(
            link_btn("Netlify docs", "https://docs.netlify.com/"), 1, 0)
        guides_layout.addWidget(
            link_btn("Vercel docs", "https://vercel.com/docs"), 1, 1)

        domain_group = QtWidgets.QGroupBox("Get a domain", self)
        domain_layout = QtWidgets.QHBoxLayout(domain_group)
        domain_layout.addWidget(
            link_btn("LeanDomainSearch", "https://leandomainsearch.com/"))
        domain_layout.addWidget(
            link_btn("Namecheap Generator",
                     "https://www.namecheap.com/domains/domain-name-generator/"),
        )
        domain_layout.addWidget(link_btn(
            "Cloudflare Registrar", "https://www.cloudflare.com/products/registrar/"))

        layout.addWidget(export_group)
        layout.addWidget(guides_group)
        layout.addWidget(domain_group)

        self.btn_export = btn_export
        self.btn_zip = btn_zip

# ---------------------------------------------------------------------------
# Application controller
# ---------------------------------------------------------------------------


class AppController(QtCore.QObject):
    def __init__(
        self,
        app: QtWidgets.QApplication,
        settings: Optional[SettingsManager] = None,
    ) -> None:
        super().__init__()
        self.app = app
        self.settings = settings if settings is not None else SettingsManager()
        self.recents = RecentProjectsManager()
        self.start_window: Optional[StartWindow] = None
        self.main_windows: List[MainWindow] = []

    def show_start(self, tab: Optional[str] = None) -> None:
        if self.start_window is None:
            self.start_window = StartWindow(self, self.recents, self.settings)
            self.start_window.project_opened.connect(
                self.open_project_from_start)
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
            tile_path = Path(
                project.cover_tile_path) if project.cover_tile_path else thumb
            if project.cover_path:
                self.recents.set_cover(path, Path(
                    project.cover_path), tile_path=tile_path)
            elif tile_path:
                self.recents.set_thumbnail(path, tile_path)
        if self.start_window is not None:
            self.start_window.close()
            self.start_window = None

    def _remove_main_window(self, window: MainWindow) -> None:
        self.main_windows = [w for w in self.main_windows if w is not window]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    # Optional: tag AppUserModelID so taskbar pinning groups properly
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Webineer.WebApp")
        except Exception:
            pass

    # Fast, one-shot post-install reset (used by installer)
    if "--reset-appdata" in sys.argv:
        clear_app_data()

    # Version-aware reset (runs on every startup; clears only when version changed)
    reset_if_new_install_or_version()

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Webineer")
    splash = show_splash_and_fade(app)

    settings: Optional[SettingsManager] = None
    volume = 70

    def play_sound_delayed():
        try:
            nonlocal settings, volume
            settings = SettingsManager()
            if settings.get("play_intro_sound", "1") == "1":
                try:
                    volume = int(settings.get("intro_volume", "70"))
                except Exception:
                    volume = 70
                play_intro_sound(volume_pct=max(0, min(100, volume)))
        except Exception:
            settings = None
            play_intro_sound(volume_pct=70)
    QTimer.singleShot(2000, play_sound_delayed)

    def launch_main():
        controller = AppController(app, settings=settings)
        controller.show_start()
        target: Optional[QtWidgets.QWidget] = None
        if controller.main_windows:
            target = controller.main_windows[-1]
        elif controller.start_window is not None:
            target = controller.start_window
        hide_splash_with_fade(splash, target)

    QTimer.singleShot(3000, launch_main)
    return app.exec()


if __name__ == "__main__":

    raise SystemExit(main())
