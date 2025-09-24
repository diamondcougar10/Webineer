from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional, List, cast
from PyQt6 import QtCore, QtGui, QtWidgets
import os


@dataclass
class TourStep:
    title: str
    body: str
    target: QtWidgets.QWidget | Callable[[], Optional[QtWidgets.QWidget]]
    on_before: Optional[Callable[[], None]] = None
    on_after: Optional[Callable[[], None]] = None


class CalloutOverlay(QtWidgets.QWidget):
    nextRequested = QtCore.pyqtSignal()
    prevRequested = QtCore.pyqtSignal()
    skipRequested = QtCore.pyqtSignal()
    finished = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget):
        super().__init__(parent)
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.Tool)
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._target_rect = QtCore.QRect()
        self._title = ""
        self._body = ""
        # Controls — larger, high-contrast buttons for visibility
        self._next = QtWidgets.QPushButton("Next", self)
        self._prev = QtWidgets.QPushButton("Back", self)
        self._skip = QtWidgets.QPushButton("Skip", self)
        self._done = QtWidgets.QPushButton("Done", self)
        for b in (self._prev, self._next, self._skip, self._done):
            b.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            b.setAttribute(
                QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        # Prominent primary action (Next / Done)
        # Support two palettes selectable via env var WEBINEER_ONBOARDING_THEME
        theme = os.getenv("WEBINEER_ONBOARDING_THEME", "dark").lower()
        if theme == "high_contrast":
            primary_bg = "#111827"
            primary_text = "#ffffff"
            secondary_bg = "#f3f4f6"
            secondary_text = "#0f172a"
            skip_border = "#fde68a"
            skip_text = "#0f172a"
        else:
            # dark theme default
            primary_bg = "#06b6d4"
            primary_text = "#0f172a"
            secondary_bg = "#1f2937"
            secondary_text = "#ffffff"
            skip_border = "rgba(255,255,255,0.12)"
            skip_text = "#cbd5e1"

        primary_style = (
            f"background-color: {primary_bg}; color: {primary_text}; border: none;"
            " border-radius: 8px; padding: 8px 14px; font-weight:600;"
        )
        secondary_style = (
            f"background-color: {secondary_bg}; color: {secondary_text}; border: none;"
            " border-radius: 8px; padding: 8px 12px;"
        )
        subtle_style = (
            f"background-color: transparent; color: {skip_text};"
            f" border: 1px solid {skip_border}; border-radius: 8px; padding: 7px 10px;"
        )
        self._next.setStyleSheet(primary_style)
        self._done.setStyleSheet(primary_style)
        self._prev.setStyleSheet(secondary_style)
        self._skip.setStyleSheet(subtle_style)
        self._prev.clicked.connect(self.prevRequested.emit)
        self._next.clicked.connect(self.nextRequested.emit)
        self._skip.clicked.connect(self.skipRequested.emit)
        self._done.clicked.connect(self.finished.emit)
        self._done.hide()
        # keyboard shortcut (create defensively to avoid analyzer complaints)
        Shortcut = getattr(QtWidgets, "QShortcut", None)
        if callable(Shortcut):
            try:
                Shortcut(QtGui.QKeySequence(QtCore.Qt.Key.Key_Escape),
                         self, activated=self.skipRequested.emit)
            except Exception:
                pass

    def setStep(self, title: str, body: str, target_rect: QtCore.QRect, *, is_last: bool) -> None:
        self._title, self._body, self._target_rect = title, body, target_rect
        self._done.setVisible(is_last)
        self._next.setVisible(not is_last)
        self._layoutButtons()
        self.update()
        self.raise_()
        self.show()

    def _layoutButtons(self) -> None:
        pad = 12
        parent_w = 0
        parent_h = 0
        parent_widget = None
        try:
            parent_widget = cast(Optional[QtWidgets.QWidget], self.parent())
        except Exception:
            parent_widget = None
        if parent_widget is not None:
            try:
                parent_w = parent_widget.width()
            except Exception:
                parent_w = 0
            try:
                parent_h = parent_widget.height()
            except Exception:
                parent_h = 0
        # Compute a safe baseline and prefer placing controls under the target
        y = max(self._target_rect.bottom() + pad, parent_h - 56 - pad)
        # Button sizing tuned for readability
        prev_w, next_w, skip_w, done_w = 96, 108, 88, 108
        total_w = prev_w + next_w + skip_w + 3 * 12
        x = max(12, min(self._target_rect.left(),
                max(0, parent_w - total_w - 16)))

        # Place buttons left-to-right: Back | Next/Done | Skip (Skip aligned right)
        self._prev.setFixedSize(prev_w, 40)
        self._prev.move(x, y)

        self._next.setFixedSize(next_w, 40)
        self._next.move(x + prev_w + 12, y)

        self._done.setFixedSize(done_w, 40)
        self._done.move(x + prev_w + 12, y)

        self._skip.setFixedSize(skip_w, 36)
        self._skip.move(x + prev_w + next_w + 24, y + 2)

    def paintEvent(self, ev: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor(15, 23, 42, 180))
        hole = QtGui.QPainterPath()
        try:
            hole.addRoundedRect(QtCore.QRectF(
                self._target_rect.adjusted(-8, -8, 8, 8)), 10.0, 10.0)
        except Exception:
            hole.addRoundedRect(QtCore.QRectF(0, 0, 0, 0), 10.0, 10.0)
        path = QtGui.QPainterPath()
        try:
            path.addRect(QtCore.QRectF(self.rect()))
        except Exception:
            path.addRect(QtCore.QRectF(0, 0, 0, 0))
        path = path.subtracted(hole)
        p.setCompositionMode(
            QtGui.QPainter.CompositionMode.CompositionMode_Clear)
        p.fillPath(path, QtGui.QColor(0, 0, 0, 0))
        p.setCompositionMode(
            QtGui.QPainter.CompositionMode.CompositionMode_SourceOver)
        bubble = self._bubbleRect()
        p.setBrush(QtGui.QColor(255, 255, 255))
        p.setPen(QtGui.QPen(QtGui.QColor(148, 163, 184), 1))
        p.drawRoundedRect(bubble, 10, 10)
        # Small triangular pointer from bubble to target
        try:
            tgt_center = self._target_rect.center()
            # pick a point on the bubble edge closest to target
            if tgt_center.y() < bubble.top():
                # target is above bubble -> pointer on top edge
                p1 = QtCore.QPointF(bubble.center().x()-10, bubble.top())
                p2 = QtCore.QPointF(bubble.center().x()+10, bubble.top())
                p3 = QtCore.QPointF(tgt_center.x(), self._target_rect.bottom())
            elif tgt_center.y() > bubble.bottom():
                # target is below bubble -> pointer on bottom edge
                p1 = QtCore.QPointF(bubble.center().x()-10, bubble.bottom())
                p2 = QtCore.QPointF(bubble.center().x()+10, bubble.bottom())
                p3 = QtCore.QPointF(tgt_center.x(), self._target_rect.top())
            else:
                # left/right
                if tgt_center.x() < bubble.left():
                    p1 = QtCore.QPointF(bubble.left(), bubble.center().y()-10)
                    p2 = QtCore.QPointF(bubble.left(), bubble.center().y()+10)
                    p3 = QtCore.QPointF(
                        self._target_rect.right(), tgt_center.y())
                else:
                    p1 = QtCore.QPointF(bubble.right(), bubble.center().y()-10)
                    p2 = QtCore.QPointF(bubble.right(), bubble.center().y()+10)
                    p3 = QtCore.QPointF(
                        self._target_rect.left(), tgt_center.y())
            tri = QtGui.QPainterPath()
            tri.moveTo(p1)
            tri.lineTo(p2)
            tri.lineTo(p3)
            tri.closeSubpath()
            p.setBrush(QtGui.QColor(255, 255, 255))
            p.setPen(QtGui.QPen(QtGui.QColor(148, 163, 184), 1))
            p.drawPath(tri)
        except Exception:
            pass

        p.setPen(QtGui.QColor(15, 23, 42))
        title_font = self.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize()+2)
        p.setFont(title_font)
        p.drawText(bubble.adjusted(12, 10, -12, -10), QtCore.Qt.AlignmentFlag.AlignLeft |
                   QtCore.Qt.AlignmentFlag.AlignTop, self._title)
        p.setFont(self.font())
        body_rect = bubble.adjusted(12, 36, -12, -10)
        p.drawText(body_rect, QtCore.Qt.AlignmentFlag.AlignLeft |
                   QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.TextFlag.TextWordWrap, self._body)

    def _bubbleRect(self) -> QtCore.QRect:
        parent_widget = None
        try:
            parent_widget = cast(Optional[QtWidgets.QWidget], self.parent())
        except Exception:
            parent_widget = None
        parent_w = parent_widget.width() if parent_widget is not None else 0
        w = min(380, max(260, (parent_w // 3) if parent_w else 260))
        above = QtCore.QRect(self._target_rect.left(),
                             self._target_rect.top()-140, w, 120)
        below = QtCore.QRect(self._target_rect.left(),
                             self._target_rect.bottom()+10, w, 120)
        right = QtCore.QRect(self._target_rect.right()+10,
                             self._target_rect.top(), w, 120)
        for r in (above, below, right):
            if parent_widget is not None:
                if 0 <= r.left() and r.right() <= parent_widget.width() and 0 <= r.top() and r.bottom() <= parent_widget.height():
                    return r
        if parent_widget is not None:
            return QtCore.QRect(max(0, parent_widget.width()-w-16), 16, w, 120)
        return QtCore.QRect(16, 16, w, 120)


class TourGuide(QtCore.QObject):
    def __init__(self, top: QtWidgets.QWidget, steps: List[TourStep]):
        super().__init__(top)
        self._top = top
        self._steps = steps
        self._idx = 0
        self._overlay = CalloutOverlay(top)
        self._overlay.nextRequested.connect(self._next)
        self._overlay.prevRequested.connect(self._prev)
        self._overlay.skipRequested.connect(self.stop)
        self._overlay.finished.connect(self.stop)
        top.installEventFilter(self)

    def start(self):
        self._idx = 0
        self._show()

    def stop(self):
        self._overlay.hide()
        self._overlay.setParent(None)
        self.deleteLater()

    def _show(self):
        if not (0 <= self._idx < len(self._steps)):
            self.stop()
            return
        step = self._steps[self._idx]

        # Run any pre-show callback (e.g. switch tabs) and allow Qt to process
        if step.on_before:
            try:
                step.on_before()
            except Exception:
                pass

        try:
            QtCore.QCoreApplication.processEvents()
        except Exception:
            pass

        # Re-evaluate the target widget after on_before
        target = step.target() if callable(step.target) else step.target
        if not target or not getattr(target, "isVisible", lambda: False)():
            self._next()
            return

        # Compute target rect relative to top; fall back to global mapping if needed
        try:
            r = target.rect()
            try:
                top_left = target.mapTo(self._top, r.topLeft())
            except Exception:
                try:
                    global_pt = target.mapToGlobal(r.topLeft())
                    top_left = self._top.mapFromGlobal(global_pt)
                except Exception:
                    top_left = r.topLeft()
            target_rect = QtCore.QRect(top_left, r.size())
        except Exception:
            self._next()
            return

        self._overlay.setGeometry(self._top.rect())
        self._overlay.setStep(
            step.title,
            step.body,
            target_rect,
            is_last=(self._idx == len(self._steps)-1),
        )

    def _next(self): self._idx = min(
        len(self._steps)-1, self._idx+1); self._show()

    def _prev(self): self._idx = max(0, self._idx-1); self._show()

    def eventFilter(self, obj, ev):
        if obj is self._top and ev.type() in (QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.Move):
            self._show()
        return super().eventFilter(obj, ev)


class WelcomeTourDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome")
        self.setModal(True)
        l = QtWidgets.QVBoxLayout(self)
        msg = QtWidgets.QLabel(
            "<h3>Welcome!</h3><p>Take a short tour to learn the basics.</p>")
        msg.setWordWrap(True)
        l.addWidget(msg)
        self.dont_show = QtWidgets.QCheckBox("Don\'t show this again", self)
        l.addWidget(self.dont_show)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                          QtWidgets.QDialogButtonBox.StandardButton.Cancel, parent=self)
        ok = btns.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setText("Start tour")
        cancel = btns.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        if cancel is not None:
            cancel.setText("Skip")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        l.addWidget(btns)
