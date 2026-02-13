"""Keyboard shortcut help overlay.

Displays a semi-transparent overlay with a centred panel listing all
keyboard shortcuts grouped by section.  Dismissed via Escape, ``?``,
``Ctrl+/``, or clicking outside.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Catppuccin Mocha palette
# ---------------------------------------------------------------------------

_BG_BASE = "#1e1e2e"
_BG_SURFACE = "#313244"
_TEXT = "#cdd6f4"
_TEXT_DIM = "#a6adc8"
_ACCENT = "#89b4fa"
_OVERLAY_CLR = "#45475a"
_SCRIM = QColor(17, 17, 27, 180)


# ---------------------------------------------------------------------------
# Shortcut data
# ---------------------------------------------------------------------------

_SHORTCUTS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Global",
        [
            ("?  /  Ctrl+/", "Show this help overlay"),
            ("Escape", "Close overlay / dialog"),
        ],
    ),
    (
        "Card Library",
        [
            ("\u2190 \u2191 \u2192 \u2193", "Move selection in grid"),
            ("Enter", "Open selected card"),
            ("[  /  Page Up", "Previous page"),
            ("]  /  Page Down", "Next page"),
            ("Scroll wheel", "Navigate pages"),
        ],
    ),
    (
        "Card Detail",
        [
            ("Escape  /  Enter", "Close card detail"),
            ("Click outside", "Close card detail"),
        ],
    ),
    (
        "Navigation",
        [
            ("\u2630  (hamburger)", "Toggle navigation drawer"),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Shortcut overlay widget
# ---------------------------------------------------------------------------


class ShortcutOverlay(QWidget):
    """Full-screen overlay displaying keyboard shortcuts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Fade-in effect
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity")
        self._fade.setDuration(150)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._build_ui()
        self.hide()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Central panel
        self._panel = QFrame()
        self._panel.setFixedWidth(520)
        self._panel.setMaximumHeight(560)
        self._panel.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self._panel.setStyleSheet(f"""
            QFrame {{
                background-color: {_BG_SURFACE};
                border-radius: 14px;
            }}
        """)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(24, 20, 24, 20)
        panel_layout.setSpacing(0)

        # Header
        header = QHBoxLayout()
        title = QLabel("Keyboard Shortcuts")
        title.setStyleSheet(f"""
            color: {_TEXT};
            font-size: 20px;
            font-weight: 700;
        """)
        header.addWidget(title)
        header.addStretch()

        close_btn = QPushButton("\u2715")
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {_TEXT_DIM};
                font-size: 16px;
                font-weight: 700;
                border: none;
                border-radius: 16px;
            }}
            QPushButton:hover {{
                background-color: {_OVERLAY_CLR};
                color: {_TEXT};
            }}
        """)
        close_btn.clicked.connect(self._dismiss)
        header.addWidget(close_btn)
        panel_layout.addLayout(header)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background-color: {_BG_SURFACE};
                width: 6px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {_OVERLAY_CLR};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 12, 0, 0)
        content_layout.setSpacing(16)

        for section_title, shortcuts in _SHORTCUTS:
            # Section header
            sec_label = QLabel(section_title)
            sec_label.setStyleSheet(f"""
                color: {_ACCENT};
                font-size: 14px;
                font-weight: 600;
                padding-top: 4px;
            """)
            content_layout.addWidget(sec_label)

            for key_text, desc_text in shortcuts:
                row = QHBoxLayout()
                row.setSpacing(12)

                # Key badge
                key_label = QLabel(key_text)
                key_label.setMinimumWidth(140)
                key_label.setStyleSheet(f"""
                    background-color: {_OVERLAY_CLR};
                    color: {_TEXT};
                    font-size: 12px;
                    font-weight: 600;
                    font-family: monospace;
                    padding: 4px 10px;
                    border-radius: 4px;
                """)
                row.addWidget(key_label)

                # Description
                desc_label = QLabel(desc_text)
                desc_label.setStyleSheet(f"""
                    color: {_TEXT_DIM};
                    font-size: 13px;
                """)
                row.addWidget(desc_label, 1)
                content_layout.addLayout(row)

        content_layout.addStretch()
        scroll.setWidget(content)
        panel_layout.addWidget(scroll, 1)

        # Centre the panel
        root.addStretch()
        centre = QHBoxLayout()
        centre.addStretch()
        centre.addWidget(self._panel)
        centre.addStretch()
        root.addLayout(centre)
        root.addStretch()

    # ------------------------------------------------------------------
    # Show / hide
    # ------------------------------------------------------------------

    def toggle(self) -> None:
        """Toggle overlay visibility."""
        if self.isVisible():
            self._dismiss()
        else:
            self._show()

    def _show(self) -> None:
        if self.parent():
            self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        self.setFocus()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def _dismiss(self) -> None:
        self.hide()

    # ------------------------------------------------------------------
    # Painting -- scrim
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), _SCRIM)
        painter.end()

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if not self._panel.geometry().contains(event.pos()):
            self._dismiss()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._dismiss()
            return
        if key == Qt.Key.Key_Question:
            self._dismiss()
            return
        if key == Qt.Key.Key_Slash and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._dismiss()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Resize
    # ------------------------------------------------------------------

    def parentResizeEvent(self) -> None:
        """Keep overlay covering parent on resize."""
        if self.parent():
            self.setGeometry(self.parent().rect())
