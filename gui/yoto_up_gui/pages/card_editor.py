"""Card Creator/Editor page for creating and editing Yoto cards."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread, QUrl
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from yoto_up.api.cards import create_or_update_card
from yoto_up.models.card import (
    Card,
    CardContent,
    CardMetadata,
    CardCover,
    Chapter,
    Track,
)

# ---------------------------------------------------------------------------
# Catppuccin Mocha palette
# ---------------------------------------------------------------------------
_BG = "#1e1e2e"
_SURFACE = "#313244"
_TEXT = "#cdd6f4"
_ACCENT = "#89b4fa"
_GREEN = "#a6e3a1"
_RED = "#f38ba8"
_YELLOW = "#f9e2af"
_SUBTEXT = "#a6adc8"

# Audio file extensions recognised when importing a folder.
_AUDIO_EXTENSIONS = {
    ".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus",
    ".flac", ".wav", ".wma", ".aiff", ".aif",
}

_CATEGORIES = [
    "none", "stories", "music", "radio",
    "podcast", "sfx", "activities", "alarms",
]


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class Worker(QThread):
    """Run *fn* with *args* in a background thread."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn = fn
        self.args = args

    def run(self):
        try:
            result = self.fn(*self.args)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Drag-and-drop tree widget for chapters/tracks
# ---------------------------------------------------------------------------


class _ChapterTreeWidget(QTreeWidget):
    """QTreeWidget subclass that accepts external audio file drops.

    Preserves the internal drag-drop reorder behaviour while also
    accepting file URLs dragged from the system file manager.
    """

    files_dropped = Signal(list)  # list[str] of file paths

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasUrls():
            # Check if any URLs are audio files
            for url in mime.urls():
                if url.isLocalFile():
                    suffix = Path(url.toLocalFile()).suffix.lower()
                    if suffix in _AUDIO_EXTENSIONS:
                        event.acceptProposedAction()
                        return
        # Fall through to default (internal reorder)
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasUrls():
            paths = []
            for url in mime.urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    suffix = Path(path).suffix.lower()
                    if suffix in _AUDIO_EXTENSIONS:
                        paths.append(path)
            if paths:
                self.files_dropped.emit(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)


# ---------------------------------------------------------------------------
# CardEditorPage
# ---------------------------------------------------------------------------

class CardEditorPage(QWidget):
    """Full-featured card creator / editor.

    Signals
    -------
    card_saved(str)
        Emitted with the card ID after a successful save.
    navigate_to(str)
        Request navigation to another page by key.
    """

    card_saved = Signal(str)
    navigate_to = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card_editor_page")
        self._client = None
        self._editing_card: Card | None = None
        self._cover_image_path: str | None = None
        self._worker: Worker | None = None
        self._toast_callback = None
        self._dirty: bool = False
        self._populating: bool = False

        self._build_ui()
        self._connect_dirty_signals()
        self.new_card()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_client(self, client) -> None:
        """Provide the authenticated :class:`YotoClient`."""
        self._client = client

    def set_toast_callback(self, callback) -> None:
        """Receive the main window's toast display callback."""
        self._toast_callback = callback

    def confirm_discard(self) -> bool:
        """If there are unsaved changes, ask the user to confirm discard.

        Returns ``True`` if navigation should proceed (no changes or user
        clicked Discard), ``False`` if the user wants to stay.
        """
        if not self._dirty:
            return True
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "You have unsaved changes. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return reply == QMessageBox.StandardButton.Discard

    def edit_card(self, card: Card) -> None:
        """Populate the form with *card* data for editing."""
        self._populating = True
        self._editing_card = card
        self._mode_label.setText("Edit Existing Card")
        self._mode_label.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {_YELLOW}; padding: 4px;"
        )

        # Metadata
        self._title_edit.setText(card.title or "")
        meta = card.metadata
        if meta:
            self._author_edit.setText(meta.author or "")
            self._description_edit.setPlainText(meta.description or "")
            cat = meta.category or "none"
            idx = self._category_combo.findText(cat)
            if idx >= 0:
                self._category_combo.setCurrentIndex(idx)
            self._genre_edit.setText(
                ", ".join(meta.genre) if meta.genre else ""
            )
            self._tags_edit.setText(
                ", ".join(meta.tags) if meta.tags else ""
            )
            self._min_age_spin.setValue(meta.minAge if meta.minAge is not None else 0)
            self._max_age_spin.setValue(meta.maxAge if meta.maxAge is not None else 0)

            # Cover preview
            if meta.cover and meta.cover.imageL:
                self._cover_path_label.setText(meta.cover.imageL)
        else:
            self._author_edit.clear()
            self._description_edit.clear()
            self._category_combo.setCurrentIndex(0)
            self._genre_edit.clear()
            self._tags_edit.clear()
            self._min_age_spin.setValue(0)
            self._max_age_spin.setValue(0)

        # Content / chapters
        self._chapter_tree.clear()
        content = card.content
        if content and content.chapters:
            for chapter in content.chapters:
                ch_item = QTreeWidgetItem(
                    self._chapter_tree,
                    [chapter.title or "Untitled Chapter", "", ""],
                )
                ch_item.setFlags(
                    ch_item.flags()
                    | Qt.ItemFlag.ItemIsDropEnabled
                    | Qt.ItemFlag.ItemIsDragEnabled
                )
                ch_item.setData(0, Qt.ItemDataRole.UserRole, "chapter")
                for track in chapter.tracks:
                    fmt = track.format or ""
                    dur = f"{track.duration:.1f}s" if track.duration else ""
                    t_item = QTreeWidgetItem(ch_item, [track.title, dur, fmt])
                    t_item.setFlags(
                        t_item.flags()
                        | Qt.ItemFlag.ItemIsDragEnabled
                        | Qt.ItemFlag.ItemNoDrop
                    )
                    t_item.setData(0, Qt.ItemDataRole.UserRole, "track")
                    t_item.setData(0, Qt.ItemDataRole.UserRole + 1, track.trackUrl)
                ch_item.setExpanded(True)

        self._save_btn.setText("Update Card")
        self._populating = False
        self._dirty = False
        self._update_drop_hint()

    def new_card(self) -> None:
        """Clear the form for creating a new card."""
        self._populating = True
        self._editing_card = None
        self._cover_image_path = None
        self._mode_label.setText("Create New Card")
        self._mode_label.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {_GREEN}; padding: 4px;"
        )
        self._title_edit.clear()
        self._author_edit.clear()
        self._description_edit.clear()
        self._category_combo.setCurrentIndex(0)
        self._genre_edit.clear()
        self._tags_edit.clear()
        self._min_age_spin.setValue(0)
        self._max_age_spin.setValue(0)
        self._cover_preview.clear()
        self._cover_preview.setText("No Image")
        self._cover_path_label.setText("")
        self._chapter_tree.clear()
        self._save_btn.setText("Save Card")
        self._populating = False
        self._dirty = False
        self._update_drop_hint()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # Mode / title header
        self._mode_label = QLabel("Create New Card")
        self._mode_label.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {_GREEN}; padding: 4px;"
        )
        root.addWidget(self._mode_label)

        # Splitter: left = metadata, right = chapters
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {_SURFACE}; width: 3px; }}"
        )
        root.addWidget(splitter, 1)

        # ---------- Left panel: metadata ----------
        left_frame = QFrame()
        left_frame.setStyleSheet(
            f"QFrame {{ background: {_SURFACE}; border-radius: 8px; }}"
        )
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(12, 12, 12, 12)

        meta_group = QGroupBox("Card Metadata")
        meta_group.setStyleSheet(
            f"QGroupBox {{ color: {_TEXT}; font-weight: bold; border: 1px solid {_SURFACE}; "
            f"border-radius: 6px; margin-top: 8px; padding-top: 14px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; }}"
        )
        form = QFormLayout(meta_group)
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Title
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("Card title (required)")
        self._title_edit.setStyleSheet(self._input_style())
        form.addRow(self._styled_label("Title *"), self._title_edit)

        # Author
        self._author_edit = QLineEdit()
        self._author_edit.setPlaceholderText("Author name")
        self._author_edit.setStyleSheet(self._input_style())
        form.addRow(self._styled_label("Author"), self._author_edit)

        # Description
        self._description_edit = QTextEdit()
        self._description_edit.setPlaceholderText("Card description")
        self._description_edit.setMaximumHeight(90)
        self._description_edit.setStyleSheet(self._input_style())
        form.addRow(self._styled_label("Description"), self._description_edit)

        # Category
        self._category_combo = QComboBox()
        self._category_combo.addItems(_CATEGORIES)
        self._category_combo.setStyleSheet(self._input_style())
        form.addRow(self._styled_label("Category"), self._category_combo)

        # Genre tags
        self._genre_edit = QLineEdit()
        self._genre_edit.setPlaceholderText("rock, jazz, classical")
        self._genre_edit.setStyleSheet(self._input_style())
        form.addRow(self._styled_label("Genre"), self._genre_edit)

        # Tags
        self._tags_edit = QLineEdit()
        self._tags_edit.setPlaceholderText("bedtime, favorite")
        self._tags_edit.setStyleSheet(self._input_style())
        form.addRow(self._styled_label("Tags"), self._tags_edit)

        # Age range
        age_row = QHBoxLayout()
        self._min_age_spin = QSpinBox()
        self._min_age_spin.setRange(0, 18)
        self._min_age_spin.setStyleSheet(self._input_style())
        self._max_age_spin = QSpinBox()
        self._max_age_spin.setRange(0, 18)
        self._max_age_spin.setStyleSheet(self._input_style())
        age_row.addWidget(QLabel("Min"))
        age_row.addWidget(self._min_age_spin)
        age_row.addWidget(QLabel("Max"))
        age_row.addWidget(self._max_age_spin)
        form.addRow(self._styled_label("Age Range"), age_row)

        # Cover image
        cover_row = QVBoxLayout()
        self._cover_preview = QLabel("No Image")
        self._cover_preview.setFixedSize(120, 120)
        self._cover_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_preview.setStyleSheet(
            f"background: {_BG}; border: 1px dashed {_SUBTEXT}; "
            f"border-radius: 6px; color: {_SUBTEXT}; font-size: 11px;"
        )
        cover_row.addWidget(self._cover_preview)

        self._cover_path_label = QLabel("")
        self._cover_path_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 10px;")
        self._cover_path_label.setWordWrap(True)
        cover_row.addWidget(self._cover_path_label)

        choose_cover_btn = QPushButton("Choose Image")
        choose_cover_btn.setStyleSheet(self._button_style(_ACCENT))
        choose_cover_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        choose_cover_btn.clicked.connect(self._choose_cover_image)
        cover_row.addWidget(choose_cover_btn)

        form.addRow(self._styled_label("Cover"), cover_row)

        left_layout.addWidget(meta_group)
        splitter.addWidget(left_frame)

        # ---------- Right panel: chapters / tracks ----------
        right_frame = QFrame()
        right_frame.setStyleSheet(
            f"QFrame {{ background: {_SURFACE}; border-radius: 8px; }}"
        )
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(12, 12, 12, 12)

        chapters_group = QGroupBox("Chapters & Tracks")
        chapters_group.setStyleSheet(
            f"QGroupBox {{ color: {_TEXT}; font-weight: bold; border: 1px solid {_SURFACE}; "
            f"border-radius: 6px; margin-top: 8px; padding-top: 14px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; }}"
        )
        ch_layout = QVBoxLayout(chapters_group)

        # Tree widget (with external file drop support)
        self._chapter_tree = _ChapterTreeWidget()
        self._chapter_tree.setHeaderLabels(["Name", "Duration", "Format"])
        self._chapter_tree.setColumnWidth(0, 260)
        self._chapter_tree.setColumnWidth(1, 80)
        self._chapter_tree.setColumnWidth(2, 80)
        self._chapter_tree.setDragDropMode(
            QTreeWidget.DragDropMode.InternalMove
        )
        self._chapter_tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._chapter_tree.setDragEnabled(True)
        self._chapter_tree.setAcceptDrops(True)
        self._chapter_tree.setSelectionMode(
            QTreeWidget.SelectionMode.SingleSelection
        )
        self._chapter_tree.setAlternatingRowColors(True)
        self._chapter_tree.setStyleSheet(
            f"QTreeWidget {{ background: {_BG}; color: {_TEXT}; border: 1px solid {_SURFACE}; "
            f"border-radius: 4px; font-size: 12px; }}"
            f"QTreeWidget::item {{ padding: 4px 2px; }}"
            f"QTreeWidget::item:selected {{ background: {_ACCENT}; color: {_BG}; }}"
            f"QHeaderView::section {{ background: {_SURFACE}; color: {_TEXT}; "
            f"padding: 4px; border: none; font-weight: bold; }}"
            f"QTreeWidget::item:alternate {{ background: #2a2a3e; }}"
        )
        self._chapter_tree.files_dropped.connect(self._on_files_dropped)
        ch_layout.addWidget(self._chapter_tree, 1)

        # Drop hint label (shown when tree is empty)
        self._drop_hint_label = QLabel(
            "Drag audio files here or use the buttons below"
        )
        self._drop_hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_hint_label.setStyleSheet(
            f"color: {_SUBTEXT}; font-size: 12px; font-style: italic; "
            f"padding: 8px; background: transparent;"
        )
        ch_layout.addWidget(self._drop_hint_label)

        # Action buttons row
        btn_row = QHBoxLayout()

        add_chapter_btn = QPushButton("Add Chapter")
        add_chapter_btn.setStyleSheet(self._button_style(_ACCENT))
        add_chapter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_chapter_btn.clicked.connect(self._add_chapter)
        btn_row.addWidget(add_chapter_btn)

        add_track_btn = QPushButton("Add Track")
        add_track_btn.setStyleSheet(self._button_style(_ACCENT))
        add_track_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_track_btn.clicked.connect(self._add_track)
        btn_row.addWidget(add_track_btn)

        import_folder_btn = QPushButton("Import Folder")
        import_folder_btn.setStyleSheet(self._button_style(_YELLOW))
        import_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_folder_btn.clicked.connect(self._import_folder)
        btn_row.addWidget(import_folder_btn)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.setStyleSheet(self._button_style(_RED))
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(remove_btn)

        ch_layout.addLayout(btn_row)
        right_layout.addWidget(chapters_group)
        splitter.addWidget(right_frame)

        # Initial splitter proportions
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        # ---------- Bottom bar ----------
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 12px;")
        bottom_bar.addWidget(self._status_label)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(self._button_style(_SUBTEXT))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self._on_cancel)
        bottom_bar.addWidget(cancel_btn)

        self._save_btn = QPushButton("Save Card")
        self._save_btn.setStyleSheet(self._button_style(_GREEN))
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.clicked.connect(self._on_save)
        bottom_bar.addWidget(self._save_btn)

        root.addLayout(bottom_bar)

    # ------------------------------------------------------------------
    # Styling helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _input_style() -> str:
        return (
            f"background: {_BG}; color: {_TEXT}; border: 1px solid {_SURFACE}; "
            f"border-radius: 4px; padding: 4px 6px; font-size: 12px;"
        )

    @staticmethod
    def _button_style(color: str) -> str:
        return (
            f"QPushButton {{ background: {color}; color: {_BG}; border: none; "
            f"border-radius: 4px; padding: 6px 14px; font-weight: bold; font-size: 12px; }}"
            f"QPushButton:hover {{ opacity: 0.85; }}"
            f"QPushButton:pressed {{ opacity: 0.7; }}"
        )

    @staticmethod
    def _styled_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {_TEXT}; font-size: 12px;")
        return lbl

    # ------------------------------------------------------------------
    # Dirty tracking
    # ------------------------------------------------------------------

    def _connect_dirty_signals(self) -> None:
        """Connect form widget change signals to _mark_dirty."""
        self._title_edit.textChanged.connect(self._mark_dirty)
        self._author_edit.textChanged.connect(self._mark_dirty)
        self._description_edit.textChanged.connect(self._mark_dirty)
        self._category_combo.currentIndexChanged.connect(self._mark_dirty)
        self._genre_edit.textChanged.connect(self._mark_dirty)
        self._tags_edit.textChanged.connect(self._mark_dirty)
        self._min_age_spin.valueChanged.connect(self._mark_dirty)
        self._max_age_spin.valueChanged.connect(self._mark_dirty)
        # Tree model changes
        model = self._chapter_tree.model()
        if model:
            model.rowsInserted.connect(self._mark_dirty)
            model.rowsRemoved.connect(self._mark_dirty)
            model.dataChanged.connect(self._mark_dirty)

    def _mark_dirty(self, *_args) -> None:
        """Mark the form as having unsaved changes."""
        if not self._populating:
            self._dirty = True

    # ------------------------------------------------------------------
    # Cover image
    # ------------------------------------------------------------------

    def _choose_cover_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Cover Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)",
        )
        if path:
            self._cover_image_path = path
            self._cover_path_label.setText(os.path.basename(path))
            self._mark_dirty()
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    120, 120,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._cover_preview.setPixmap(scaled)
            else:
                self._cover_preview.setText("Invalid Image")

    # ------------------------------------------------------------------
    # Chapter / track management
    # ------------------------------------------------------------------

    def _add_chapter(self) -> None:
        """Add a new empty chapter node to the tree."""
        ch_item = QTreeWidgetItem(
            self._chapter_tree,
            [f"Chapter {self._chapter_tree.topLevelItemCount() + 1}", "", ""],
        )
        ch_item.setFlags(
            ch_item.flags()
            | Qt.ItemFlag.ItemIsDropEnabled
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsEditable
        )
        ch_item.setData(0, Qt.ItemDataRole.UserRole, "chapter")
        ch_item.setExpanded(True)
        self._chapter_tree.setCurrentItem(ch_item)
        self._update_drop_hint()

    def _add_track(self) -> None:
        """Add an audio file as a track to the currently selected chapter."""
        current = self._chapter_tree.currentItem()
        chapter_item = self._find_parent_chapter(current)
        if chapter_item is None:
            QMessageBox.information(
                self, "No Chapter Selected",
                "Please select or create a chapter first.",
            )
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Audio File(s)",
            "",
            "Audio Files (*.mp3 *.m4a *.m4b *.aac *.ogg *.opus *.flac *.wav *.wma *.aiff);;All Files (*)",
        )
        for path in paths:
            self._add_track_to_chapter(chapter_item, path)

    def _import_folder(self) -> None:
        """Import all audio files from a folder as tracks in a new chapter."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder with Audio Files",
        )
        if not folder:
            return

        audio_files = sorted(
            p for p in Path(folder).iterdir()
            if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS
        )

        if not audio_files:
            QMessageBox.information(
                self, "No Audio Files",
                f"No supported audio files found in:\n{folder}",
            )
            return

        folder_name = Path(folder).name
        ch_item = QTreeWidgetItem(
            self._chapter_tree,
            [folder_name, "", ""],
        )
        ch_item.setFlags(
            ch_item.flags()
            | Qt.ItemFlag.ItemIsDropEnabled
            | Qt.ItemFlag.ItemIsDragEnabled
        )
        ch_item.setData(0, Qt.ItemDataRole.UserRole, "chapter")

        for audio_file in audio_files:
            self._add_track_to_chapter(ch_item, str(audio_file))

        ch_item.setExpanded(True)
        self._chapter_tree.setCurrentItem(ch_item)
        self._update_drop_hint()

    def _add_track_to_chapter(
        self, chapter_item: QTreeWidgetItem, file_path: str,
    ) -> None:
        """Create a track tree item under *chapter_item*."""
        p = Path(file_path)
        name = p.stem
        fmt = p.suffix.lstrip(".").upper()

        # Attempt to read duration with the audio module
        dur_str = ""
        try:
            from yoto_up.audio.waveform import get_audio_duration
            dur = get_audio_duration(file_path)
            if dur is not None:
                mins = int(dur // 60)
                secs = int(dur % 60)
                dur_str = f"{mins}:{secs:02d}"
        except Exception:
            pass

        t_item = QTreeWidgetItem(chapter_item, [name, dur_str, fmt])
        t_item.setFlags(
            t_item.flags()
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemNoDrop
        )
        t_item.setData(0, Qt.ItemDataRole.UserRole, "track")
        t_item.setData(0, Qt.ItemDataRole.UserRole + 1, file_path)

    def _remove_selected(self) -> None:
        """Remove the selected tree item (chapter or track)."""
        current = self._chapter_tree.currentItem()
        if current is None:
            return
        parent = current.parent()
        if parent:
            parent.removeChild(current)
        else:
            idx = self._chapter_tree.indexOfTopLevelItem(current)
            if idx >= 0:
                self._chapter_tree.takeTopLevelItem(idx)
        self._update_drop_hint()

    def _on_files_dropped(self, paths: list[str]) -> None:
        """Handle audio files dropped onto the tree widget."""
        # Find or create a chapter to add tracks to
        current = self._chapter_tree.currentItem()
        chapter_item = self._find_parent_chapter(current)
        if chapter_item is None:
            # Create a new chapter for the dropped files
            chapter_item = QTreeWidgetItem(
                self._chapter_tree,
                [f"Chapter {self._chapter_tree.topLevelItemCount() + 1}", "", ""],
            )
            chapter_item.setFlags(
                chapter_item.flags()
                | Qt.ItemFlag.ItemIsDropEnabled
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsEditable
            )
            chapter_item.setData(0, Qt.ItemDataRole.UserRole, "chapter")

        for path in paths:
            self._add_track_to_chapter(chapter_item, path)

        chapter_item.setExpanded(True)
        self._chapter_tree.setCurrentItem(chapter_item)
        self._update_drop_hint()

        if self._toast_callback:
            from yoto_up_gui.widgets.toast import ToastType
            count = len(paths)
            self._toast_callback(
                f"Added {count} track{'s' if count != 1 else ''}",
                ToastType.SUCCESS,
            )

    def _update_drop_hint(self) -> None:
        """Show/hide the drop hint based on whether the tree has items."""
        has_items = self._chapter_tree.topLevelItemCount() > 0
        self._drop_hint_label.setVisible(not has_items)

    @staticmethod
    def _find_parent_chapter(item: QTreeWidgetItem | None) -> QTreeWidgetItem | None:
        """Walk up to find the nearest chapter-level item."""
        if item is None:
            return None
        if item.data(0, Qt.ItemDataRole.UserRole) == "chapter":
            return item
        parent = item.parent()
        if parent and parent.data(0, Qt.ItemDataRole.UserRole) == "chapter":
            return parent
        return None

    # ------------------------------------------------------------------
    # Save / cancel
    # ------------------------------------------------------------------

    def _on_cancel(self) -> None:
        """Reset and navigate away (guarded by unsaved changes check)."""
        if not self.confirm_discard():
            return
        self.new_card()
        self.navigate_to.emit("card_library")

    def _on_save(self) -> None:
        title = self._title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "Validation", "Title is required.")
            return

        if self._client is None:
            QMessageBox.warning(
                self, "Not Connected",
                "No API client available. Please log in first.",
            )
            return

        card = self._build_card_from_form()
        self._save_btn.setEnabled(False)
        self._status_label.setText("Saving...")

        self._worker = Worker(create_or_update_card, self._client, card)
        self._worker.finished.connect(self._on_save_finished)
        self._worker.error.connect(self._on_save_error)
        self._worker.start()

    def _on_save_finished(self, saved_card: Card) -> None:
        self._save_btn.setEnabled(True)
        self._dirty = False
        card_id = saved_card.cardId or ""
        self._status_label.setText(f"Saved: {card_id}")
        self._status_label.setStyleSheet(f"color: {_GREEN}; font-size: 12px;")
        if self._toast_callback:
            from yoto_up_gui.widgets.toast import ToastType
            self._toast_callback(f"Card saved successfully ({card_id})", ToastType.SUCCESS)
        self.card_saved.emit(card_id)

    def _on_save_error(self, msg: str) -> None:
        self._save_btn.setEnabled(True)
        self._status_label.setText(f"Error: {msg}")
        self._status_label.setStyleSheet(f"color: {_RED}; font-size: 12px;")
        if self._toast_callback:
            from yoto_up_gui.widgets.toast import ToastType
            self._toast_callback(f"Save failed: {msg}", ToastType.ERROR, 6000)
        else:
            QMessageBox.critical(self, "Save Failed", msg)

    # ------------------------------------------------------------------
    # Build card model from form state
    # ------------------------------------------------------------------

    def _build_card_from_form(self) -> Card:
        """Assemble a :class:`Card` from the current form values."""
        title = self._title_edit.text().strip()

        # Parse comma-separated lists
        genre = [
            g.strip() for g in self._genre_edit.text().split(",") if g.strip()
        ] or None
        tags = [
            t.strip() for t in self._tags_edit.text().split(",") if t.strip()
        ] or None

        cat = self._category_combo.currentText()
        if cat == "none":
            cat = ""

        min_age_val = self._min_age_spin.value()
        min_age = min_age_val if min_age_val > 0 else None
        max_age_val = self._max_age_spin.value()
        max_age = max_age_val if max_age_val > 0 else None

        cover = None
        if self._cover_image_path:
            cover = CardCover(imageL=self._cover_image_path)
        elif self._editing_card and self._editing_card.metadata and self._editing_card.metadata.cover:
            cover = self._editing_card.metadata.cover

        metadata = CardMetadata(
            author=self._author_edit.text().strip() or None,
            description=self._description_edit.toPlainText().strip() or None,
            category=cat or None,
            genre=genre,
            tags=tags,
            minAge=min_age,
            maxAge=max_age,
            cover=cover,
        )

        # Build chapters/tracks from tree
        chapters: list[Chapter] = []
        for ci in range(self._chapter_tree.topLevelItemCount()):
            ch_item = self._chapter_tree.topLevelItem(ci)
            ch_title = ch_item.text(0)
            tracks: list[Track] = []
            for ti in range(ch_item.childCount()):
                t_item = ch_item.child(ti)
                track_url = t_item.data(0, Qt.ItemDataRole.UserRole + 1) or ""
                track_title = t_item.text(0)
                track_format = t_item.text(2).lower() or "mp3"
                track_key = str(uuid.uuid4())[:8]
                tracks.append(
                    Track(
                        title=track_title,
                        trackUrl=track_url,
                        key=track_key,
                        format=track_format,
                        type="audio",
                    )
                )
            ch_key = str(uuid.uuid4())[:8]
            chapters.append(
                Chapter(title=ch_title, key=ch_key, tracks=tracks)
            )

        content = CardContent(chapters=chapters) if chapters else None

        card = Card(
            title=title,
            metadata=metadata,
            content=content,
        )
        # Preserve cardId when editing
        if self._editing_card and self._editing_card.cardId:
            card.cardId = self._editing_card.cardId

        return card
