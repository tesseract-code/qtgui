"""Modern file attachment preview widget for PyQt6."""

from pathlib import Path
from typing import Dict

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QFont, QPainter, QColor
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel,
    QToolButton
)

from cross_platform.core.file_info import (FileExtensionCategory, FileTypeHelper,
                                           FileInfo)
from cross_platform.qt6_utils.qtdisplay.src.qtdisplay.layouts import FlowLayout


class FileIconGenerator:
    """Generate icons for different file types"""

    CATEGORY_COLORS = {
        FileExtensionCategory.IMAGE: QColor(76, 175, 80),  # Green
        FileExtensionCategory.DOCUMENT: QColor(33, 150, 243),  # Blue
        FileExtensionCategory.CODE: QColor(156, 39, 176),  # Purple
        FileExtensionCategory.SPREADSHEET: QColor(76, 175, 80),  # Green
        FileExtensionCategory.PDF: QColor(244, 67, 54),  # Red
        FileExtensionCategory.VIDEO: QColor(255, 152, 0),  # Orange
        FileExtensionCategory.AUDIO: QColor(233, 30, 99),  # Pink
        FileExtensionCategory.ARCHIVE: QColor(158, 158, 158),  # Gray
        FileExtensionCategory.UNKNOWN: QColor(96, 125, 139),  # Blue Gray
    }

    CATEGORY_SYMBOLS = {
        FileExtensionCategory.IMAGE: "🖼",
        FileExtensionCategory.DOCUMENT: "📄",
        FileExtensionCategory.CODE: "⚙",
        FileExtensionCategory.SPREADSHEET: "📊",
        FileExtensionCategory.PDF: "📕",
        FileExtensionCategory.VIDEO: "🎬",
        FileExtensionCategory.AUDIO: "🎵",
        FileExtensionCategory.ARCHIVE: "📦",
        FileExtensionCategory.UNKNOWN: "📎",
    }

    @classmethod
    def create_icon(cls, category: FileExtensionCategory,
                    size: QSize = QSize(48, 48)) -> QPixmap:
        """Create a colored icon for file category"""
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw rounded rectangle background
        color = cls.CATEGORY_COLORS.get(category, cls.CATEGORY_COLORS[
            FileExtensionCategory.UNKNOWN])
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, size.width(), size.height(), 8, 8)

        # Draw symbol
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Segoe UI Emoji", size.width() // 2)
        painter.setFont(font)
        symbol = cls.CATEGORY_SYMBOLS.get(category, cls.CATEGORY_SYMBOLS[
            FileExtensionCategory.UNKNOWN])
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, symbol)

        painter.end()
        return pixmap


class AttachmentWidget(QFrame):
    """Modern file attachment preview widget"""

    remove_requested = pyqtSignal(str)  # file_path

    THUMBNAIL_SIZE = QSize(56, 56)
    MAX_NAME_LENGTH = 20

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = Path(file_path)
        self.file_info = self._analyze_file()
        self._init_ui()

    def _analyze_file(self) -> FileInfo:
        """Analyze file and gather information"""
        stat = self.file_path.stat()
        category = FileTypeHelper.get_category(self.file_path)
        mime_type = FileTypeHelper.get_mime_type(self.file_path)

        line_count = None
        if FileTypeHelper.can_count_lines(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8',
                          errors='ignore') as f:
                    line_count = sum(1 for _ in f)
            except Exception:
                pass

        preview_available = (
                category == FileExtensionCategory.IMAGE and
                FileTypeHelper.can_preview_image(self.file_path)
        )

        return FileInfo(
            path=self.file_path,
            name=self.file_path.name,
            size=stat.st_size,
            mime_type=mime_type,
            category=category,
            line_count=line_count,
            preview_available=preview_available
        )

    def _init_ui(self) -> None:
        """Initialize the UI"""
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedSize(120, 140)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop |
                                 Qt.AlignmentFlag.AlignCenter)

        # Remove button at top right
        remove_btn = self._create_remove_button()
        remove_layout = QHBoxLayout()
        remove_layout.addStretch()
        remove_layout.addWidget(remove_btn)
        main_layout.addLayout(remove_layout)

        # Thumbnail/Icon (centered)
        thumbnail_layout = QHBoxLayout()
        thumbnail_layout.addStretch()
        thumbnail_layout.addWidget(self._create_thumbnail())
        thumbnail_layout.addStretch()
        main_layout.addLayout(thumbnail_layout)

        # File information (centered)
        info_layout = self._create_info_section()
        main_layout.addLayout(info_layout)

        main_layout.addStretch()

        self._apply_styling()

    def _create_thumbnail(self) -> QLabel:
        """Create thumbnail or icon"""
        thumbnail = QLabel()
        thumbnail.setFixedSize(self.THUMBNAIL_SIZE)
        thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if self.file_info.preview_available:
            pixmap = self._load_image_preview()
        else:
            pixmap = FileIconGenerator.create_icon(
                self.file_info.category,
                self.THUMBNAIL_SIZE
            )

        thumbnail.setPixmap(pixmap)
        thumbnail.setStyleSheet("border-radius: 8px;")
        return thumbnail

    def _load_image_preview(self) -> QPixmap:
        """Load and scale image preview"""
        pixmap = QPixmap(str(self.file_path))
        if not pixmap.isNull():
            return pixmap.scaled(
                self.THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
        return FileIconGenerator.create_icon(
            FileExtensionCategory.IMAGE,
            self.THUMBNAIL_SIZE
        )

    def _create_info_section(self) -> QVBoxLayout:
        """Create file information section"""
        layout = QVBoxLayout()
        layout.setSpacing(4)

        # File name
        name_label = QLabel(self._truncate_name(self.file_info.name))
        name_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        name_label.setToolTip(self.file_info.name)
        layout.addWidget(name_label, alignment=Qt.AlignmentFlag.AlignTop |
                                 Qt.AlignmentFlag.AlignCenter)

        # File details
        details = self._format_details()
        details_label = QLabel(details)
        details_label.setFont(QFont("Segoe UI", 9))
        details_label.setStyleSheet("color: #888;")
        layout.addWidget(details_label, alignment=Qt.AlignmentFlag.AlignTop |
                                 Qt.AlignmentFlag.AlignCenter)

        # Additional info
        if self.file_info.line_count is not None:
            lines_label = QLabel(f"{self.file_info.line_count:,} lines")
            lines_label.setFont(QFont("Segoe UI", 8))
            lines_label.setStyleSheet("color: #666;")
            layout.addWidget(lines_label, alignment=Qt.AlignmentFlag.AlignTop |
                                 Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()
        return layout

    def _create_remove_button(self) -> QToolButton:
        """Create remove button"""
        button = QToolButton()
        button.setText("✕")
        button.setFont(QFont("Segoe UI", 12))
        button.setFixedSize(24, 24)
        button.setToolTip("Remove attachment")
        button.clicked.connect(
            lambda: self.remove_requested.emit(str(self.file_path))
        )
        button.setStyleSheet("""
            QToolButton {
                background-color: transparent;
                border: none;
                color: #888;
                border-radius: 12px;
            }
            QToolButton:hover {
                background-color: rgba(255, 0, 0, 0.1);
                color: #ff4444;
            }
        """)
        return button

    def _truncate_name(self, name: str) -> str:
        """Truncate long file names"""
        if len(name) <= self.MAX_NAME_LENGTH:
            return name

        stem = self.file_path.stem
        suffix = self.file_path.suffix
        max_stem = self.MAX_NAME_LENGTH - len(suffix) - 3

        if len(stem) > max_stem:
            return f"{stem[:max_stem]}...{suffix}"
        return name

    def _format_details(self) -> str:
        """Format file details string"""
        size_str = self._format_size(self.file_info.size)
        ext = self.file_path.suffix.upper()[
              1:] if self.file_path.suffix else "FILE"
        return f"{ext} • {size_str}"

    @staticmethod
    def _format_size(size: int) -> str:
        """Format file size to human-readable string"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}" if size != int(
                    size) else f"{int(size)} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    def _apply_styling(self) -> None:
        """Apply widget styling"""
        self.setStyleSheet("""
            AttachmentWidget {
                background: #2D2D30;
                border: 1px solid #3E3E42;
                border-radius: 10px;
            }
            AttachmentWidget:hover {
                background: #323235;
                border-color: #4E4E52;
            }
            QLabel {
                color: #CCCCCC;
                background: transparent;
                border: none;
            }
        """)


class AttachmentListWidget(QFrame):
    """Container widget for multiple attachments"""

    files_changed = pyqtSignal(list)  # List of file paths

    def __init__(self, parent=None):
        super().__init__(parent)
        self.attachments: Dict[str, AttachmentWidget] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        """Initialize the UI"""
        vertical_compress = QVBoxLayout(self)
        horizontal_compress = QHBoxLayout()
        self.content_view = QFrame()
        self.content_view.setObjectName("attachmentListContent")
        FlowLayout(self.content_view)
        # # self.content_view.layout().setSpacing(5)
        # self.content_view.layout().setContentsMargins(10, 10, 10, 10)
        horizontal_compress.addWidget(self.content_view)
        # horizontal_compress.addStretch()
        vertical_compress.addLayout(horizontal_compress)
        # vertical_compress.addStretch()

        self.content_view.setStyleSheet("""
            #attachmentListContent {
                background: transparent;
                border: none;
            }
        """)

        self.setStyleSheet("""background-color: palette(base); 
        border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;""")

    def add_file(self, file_path: str) -> None:
        """Add a file attachment"""
        if file_path in self.attachments:
            return

        widget = AttachmentWidget(file_path)
        widget.remove_requested.connect(self.remove_file)

        self.attachments[file_path] = widget
        self.content_view.layout().addWidget(widget)
        self._emit_files_changed()

    def remove_file(self, file_path: str) -> None:
        """Remove a file attachment"""
        if file_path in self.attachments:
            widget = self.attachments.pop(file_path)
            self.content_view.layout().removeWidget(widget)
            widget.deleteLater()
            self._emit_files_changed()

    def clear(self) -> None:
        """Remove all attachments"""
        for file_path in list(self.attachments.keys()):
            self.remove_file(file_path)

    def get_file_paths(self) -> list[str]:
        """Get list of all attached file paths"""
        return list(self.attachments.keys())

    def _emit_files_changed(self) -> None:
        """Emit files changed signal"""
        self.files_changed.emit(self.get_file_paths())


# Example usage
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget
    import sys

    app = QApplication(sys.argv)

    window = QMainWindow()
    window.setWindowTitle("Attachment Widget Demo")
    window.setStyleSheet("background: #1E1E1E;")

    central = QWidget()
    layout = QVBoxLayout(central)

    # Create attachment list
    attachment_list = AttachmentListWidget()
    attachment_list.files_changed.connect(
        lambda files: print(f"Files: {files}")
    )

    # Add some demo files (use real file paths for testing)
    demo_files = [
        "/Users/pkkenne/PycharmProjects/dev/cross_platform/ollama_utils/chess_utils/context_bldr.py",
        "/Users/pkkenne/PycharmProjects/dev/cross_platform/service_a_state.pkl"
    ]

    for file in demo_files:
        if Path(file).exists():
            attachment_list.add_file(file)

    layout.addWidget(attachment_list)
    # layout.addStretch()

    window.setCentralWidget(central)
    window.resize(500, 400)
    window.show()

    sys.exit(app.exec())
