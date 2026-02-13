"""Non-blocking toast / snackbar notification system.

Toasts appear as small coloured pills anchored to the bottom-right of
the parent widget, auto-dismiss after a configurable timeout, and stack
vertically (newest at bottom, max 5 visible).
"""

from __future__ import annotations

from enum import Enum, auto

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)


# ---------------------------------------------------------------------------
# Catppuccin Mocha palette tokens
# ---------------------------------------------------------------------------

_BG_BASE = "#1e1e2e"
_SURFACE = "#313244"
_TEXT = "#cdd6f4"


# ---------------------------------------------------------------------------
# Toast types
# ---------------------------------------------------------------------------


class ToastType(Enum):
    SUCCESS = auto()
    ERROR = auto()
    INFO = auto()
    WARNING = auto()


_TOAST_COLOURS: dict[ToastType, str] = {
    ToastType.SUCCESS: "#a6e3a1",
    ToastType.ERROR: "#f38ba8",
    ToastType.INFO: "#89b4fa",
    ToastType.WARNING: "#f9e2af",
}

_TOAST_ICONS: dict[ToastType, str] = {
    ToastType.SUCCESS: "\u2713",  # check mark
    ToastType.ERROR: "\u2717",    # cross mark
    ToastType.INFO: "\u2139",     # info
    ToastType.WARNING: "\u26A0",  # warning
}


# ---------------------------------------------------------------------------
# Single toast widget
# ---------------------------------------------------------------------------


class _ToastWidget(QFrame):
    """A single toast notification pill."""

    def __init__(
        self,
        message: str,
        toast_type: ToastType = ToastType.INFO,
        duration_ms: int = 4000,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._duration_ms = duration_ms
        colour = _TOAST_COLOURS.get(toast_type, _TOAST_COLOURS[ToastType.INFO])

        # Re-enable mouse events so close button works
        # (parent ToastManager is transparent for mouse events)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        self.setFixedHeight(48)
        self.setMinimumWidth(280)
        self.setMaximumWidth(400)

        self.setStyleSheet(
            f"QFrame {{ background: {_SURFACE}; border-left: 4px solid {colour}; "
            f"border-radius: 8px; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 8, 4)
        layout.setSpacing(8)

        # Icon
        icon_label = QLabel(_TOAST_ICONS.get(toast_type, ""))
        icon_label.setFixedWidth(20)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(f"color: {colour}; font-size: 16px; background: transparent;")
        layout.addWidget(icon_label)

        # Message
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; background: transparent;"
        )
        layout.addWidget(msg_label, 1)

        # Close button
        close_btn = QPushButton("\u2715")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ color: {_TEXT}; background: transparent; border: none; "
            f"font-size: 13px; border-radius: 12px; }}"
            f"QPushButton:hover {{ background: {_BG_BASE}; }}"
        )
        close_btn.clicked.connect(self._dismiss)
        layout.addWidget(close_btn)

        # Fade-in effect
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        self._fade_in = QPropertyAnimation(self._opacity, b"opacity")
        self._fade_in.setDuration(200)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Auto-dismiss timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dismiss)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fade_in.start()
        if self._duration_ms > 0:
            self._timer.start(self._duration_ms)

    def _dismiss(self) -> None:
        self._timer.stop()
        # Notify parent manager
        p = self.parent()
        if p and hasattr(p, "_remove_toast"):
            p._remove_toast(self)
        self.deleteLater()


# ---------------------------------------------------------------------------
# Toast manager -- stacks toasts in bottom-right of parent
# ---------------------------------------------------------------------------

_MAX_TOASTS = 5
_MARGIN_RIGHT = 16
_MARGIN_BOTTOM = 16
_TOAST_SPACING = 8


class ToastManager(QWidget):
    """Manages a stack of toast notifications anchored bottom-right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._toasts: list[_ToastWidget] = []
        # Fully transparent, no interaction with underlying widgets
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.raise_()

    def show_toast(
        self,
        message: str,
        toast_type: ToastType = ToastType.INFO,
        duration_ms: int = 4000,
    ) -> None:
        """Show a new toast notification."""
        # Enforce max
        while len(self._toasts) >= _MAX_TOASTS:
            oldest = self._toasts[0]
            self._remove_toast(oldest)

        toast = _ToastWidget(message, toast_type, duration_ms, parent=self)
        self._toasts.append(toast)
        toast.show()
        self._reposition()

    def _remove_toast(self, toast: _ToastWidget) -> None:
        """Remove a toast from the managed list."""
        if toast in self._toasts:
            self._toasts.remove(toast)
        toast.hide()
        self._reposition()

    def _reposition(self) -> None:
        """Reposition all visible toasts stacked from bottom-right."""
        parent = self.parent()
        if parent is None:
            return

        parent_rect = parent.rect() if hasattr(parent, "rect") else self.rect()

        # Resize self to cover the parent
        self.setGeometry(parent_rect)

        y = parent_rect.height() - _MARGIN_BOTTOM
        for toast in reversed(self._toasts):
            toast.adjustSize()
            tw = toast.sizeHint().width()
            th = toast.height()
            x = parent_rect.width() - tw - _MARGIN_RIGHT
            y -= th
            toast.setGeometry(x, y, tw, th)
            y -= _TOAST_SPACING

        self.raise_()

    def reposition(self) -> None:
        """Public wrapper for repositioning (called on parent resize)."""
        self._reposition()
