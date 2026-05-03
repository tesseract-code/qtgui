from pathlib import Path
from typing import List, Set

from PyQt6.QtCore import (
    Qt, pyqtSignal, QFileInfo, QTimer, QPoint, QUrl, QSize
)
from PyQt6.QtGui import (
    QDragEnterEvent, QDropEvent, QFont, QDragLeaveEvent,
    QDesktopServices
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QProgressBar, QMenu, QFileDialog,
    QMessageBox, QFrame
)

from cross_platform.core.file_info import FileExtensionManager
from cross_platform.ollama_utils.chat.file_preview import AttachmentListWidget
from cross_platform.qt6_utils.qtgui.src.qtgui.pixmap import create_pixmap_from_svg


class DropZoneWidget(QFrame):
    """Custom drop zone widget with visual feedback."""

    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.is_drag_over = False

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # Drop zone content
        self.icon_label = QLabel()
        self.icon_label.setPixmap(create_pixmap_from_svg(
            Path(r"/cross_platform/svg_icons/fill/file-upload.svg"),
            QSize(64, 64)))
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel("Drag&Drop files here")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.title_label.setStyleSheet("""color: black;""")

        layout.addWidget(self.icon_label)
        layout.addWidget(self.title_label)

        self.setMinimumHeight(150)
        self.update_appearance()

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter event."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.is_drag_over = True
            self.update_appearance()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        """Handle drag leave event."""
        self.is_drag_over = False
        self.update_appearance()

    def dropEvent(self, event: QDropEvent):
        """Handle drop event."""
        self.is_drag_over = False
        self.update_appearance()

        if event.mimeData().hasUrls():
            file_paths = []
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    file_paths.append(url.toLocalFile())

            if file_paths:
                self.files_dropped.emit(file_paths)

            event.acceptProposedAction()

    def update_appearance(self):
        """Update visual appearance based on state."""
        if self.is_drag_over:
            self.setStyleSheet("""
                DropZoneWidget {
                    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #e3f2fd, stop:1 #bbdefb);
                    border: 3px dashed #2196f3;
                    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
                }
            """)
        else:
            self.setStyleSheet("""
                DropZoneWidget {
                    background-color: palette(dark);
                    border: 3px dashed #bdbdbd;
                    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
                }
                DropZoneWidget:hover {
                    border: 3px dashed #2196f3;
                    background-color: palette(dark);
                }
            """)


class FileDropWidget(QWidget):
    """Modern file drop widget with filtering and management capabilities."""

    # Signals
    files_dropped = pyqtSignal(list)  # List of file paths
    files_selected = pyqtSignal(list)  # List of selected file paths
    files_uploaded = pyqtSignal(list)  # List of uploaded file paths
    upload_progress = pyqtSignal(int, str)  # Progress percentage, filename

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dropped_files = []  # List of (file_path, file_info) tuples
        self.selected_files = set()  # Set of selected file paths
        self.supported_formats = FileExtensionManager.get_all_extensions()
        self.max_file_size = 100 * 1024 * 1024  # 100MB
        self.upload_in_progress = False

        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)

        # Drop zone
        self.drop_zone = DropZoneWidget()
        self.drop_zone.files_dropped.connect(self.handle_files_dropped)
        layout.addWidget(self.drop_zone)


        # File list
        self.file_list = AttachmentListWidget()

        layout.addWidget(self.file_list)

        # Progress bar (initially hidden)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

    def handle_files_dropped(self, file_paths: List[str]):
        """Handle files dropped onto the drop zone."""
        valid_files = []
        rejected_files = []

        for file_path in file_paths:
            file_info = QFileInfo(file_path)

            # Check if file exists and is readable
            if not file_info.exists() or not file_info.isReadable():
                rejected_files.append((file_path, "File not accessible"))
                continue

            # Check file size
            if file_info.size() > self.max_file_size:
                rejected_files.append((file_path,
                                       f"File too large (> {self.max_file_size // (1024 * 1024)}MB)"))
                continue

            # Check file extension
            suffix = file_info.suffix().lower()
            if f'.{suffix}' not in self.supported_formats:
                rejected_files.append((file_path, "Unsupported file type"))
                continue

            # Check for duplicates
            if any(existing_path == file_path for existing_path, _ in
                   self.dropped_files):
                rejected_files.append((file_path, "Duplicate file"))
                continue

            valid_files.append(file_path)

        # Add valid files
        for file_path in valid_files:
            self.file_list.add_file(file_path=file_path)

        # Show rejection summary if any
        if rejected_files:
            self.show_rejection_summary(rejected_files)

    def remove_file(self, file_path: str):
        """Remove a file from the list."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == file_path:
                self.file_list.takeItem(i)
                break

        # Remove from internal lists
        self.dropped_files = [(path, info) for path, info in self.dropped_files
                              if path != file_path]
        self.selected_files.discard(file_path)

        

    def clear_all_files(self):
        """Clear all files from the list."""
        if not self.dropped_files:
            return

        reply = QMessageBox.question(
            self, "Clear All Files",
            "Are you sure you want to remove all files?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.file_list.clear()
            self.dropped_files.clear()
            self.selected_files.clear()
            

    def select_all_files(self):
        """Select all files in the list."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            item.setCheckState(Qt.CheckState.Checked)

    def select_no_files(self):
        """Deselect all files in the list."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            item.setCheckState(Qt.CheckState.Unchecked)

    def invert_selection(self):
        """Invert the current selection."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                item.setCheckState(Qt.CheckState.Unchecked)
            else:
                item.setCheckState(Qt.CheckState.Checked)

    def filter_file_list(self):
        """Filter the file list based on selected file type."""
        current_filter = self.file_type_filter.currentData()

        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            file_path = item.data(Qt.ItemDataRole.UserRole)
            file_info = QFileInfo(file_path)
            suffix = f'.{file_info.suffix().lower()}'

            if current_filter is None or suffix in current_filter:
                item.setHidden(False)
            else:
                item.setHidden(True)

    def on_item_changed(self, item):
        """Handle item checkbox state changes."""
        file_path = item.data(Qt.ItemDataRole.UserRole)

        if item.checkState() == Qt.CheckState.Checked:
            self.selected_files.add(file_path)
        else:
            self.selected_files.discard(file_path)

        

    def browse_files(self):
        """Open file browser to select files."""
        file_dialog = QFileDialog(self)
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        file_dialog.setNameFilter(
            "Supported Files ("
            "*.pdf *.txt *.doc *.docx *.md *.rtf "
            "*.html *.htm *.json *.xml *.csv "
            "*.py *.js *.java *.cpp *.c *.h *.cs "
            "*.ipynb *.pptx *.ppt *.xlsx *.xls)"
        )

        if file_dialog.exec() == QFileDialog.DialogCode.Accepted:
            self.handle_files_dropped(file_dialog.selectedFiles())

    def upload_selected_files(self):
        """Upload selected files to context."""
        if not self.selected_files:
            QMessageBox.warning(self, "Upload", "No files selected for upload.")
            return

        if self.upload_in_progress:
            QMessageBox.warning(self, "Upload", "Upload already in progress.")
            return

        self.upload_in_progress = True
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.upload_btn.setEnabled(False)

        # Simulate upload process (in real implementation, this would be async)
        selected_list = list(self.selected_files)
        total_files = len(selected_list)

        for i, file_path in enumerate(selected_list):
            progress = int((i + 1) / total_files * 100)
            file_name = Path(file_path).name

            self.progress_bar.setValue(progress)
            self.upload_progress.emit(progress, file_name)

            # Simulate processing time
            QTimer.singleShot(100, lambda: None)

        # Complete upload
        QTimer.singleShot(500, lambda: self.complete_upload(selected_list))

    def complete_upload(self, uploaded_files: List[str]):
        """Complete the upload process."""
        self.upload_in_progress = False
        self.progress_bar.setVisible(False)
        self.upload_btn.setEnabled(True)

        self.files_uploaded.emit(uploaded_files)

        QMessageBox.information(
            self, "Upload Complete",
            f"Successfully uploaded {len(uploaded_files)} files to context."
        )

    def show_context_menu(self, position: QPoint):
        """Show context menu for file list."""
        if not self.dropped_files:
            return

        menu = QMenu(self)

        remove_action = menu.addAction("Remove Selected")
        remove_all_action = menu.addAction("Remove All")
        menu.addSeparator()
        open_action = menu.addAction("Open File Location")

        action = menu.exec(self.file_list.mapToGlobal(position))

        if action == remove_action:
            self.remove_selected_files()
        elif action == remove_all_action:
            self.clear_all_files()
        elif action == open_action:
            self.open_selected_locations()

    def remove_selected_files(self):
        """Remove currently selected files."""
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            return

        for item in selected_items:
            file_path = item.data(Qt.ItemDataRole.UserRole)
            self.remove_file(file_path)

    def open_selected_locations(self):
        """Open file location for selected files."""
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            return

        for item in selected_items:
            file_path = item.data(Qt.ItemDataRole.UserRole)
            file_dir = str(Path(file_path).parent)
            QDesktopServices.openUrl(QUrl.fromLocalFile(file_dir))

    def show_rejection_summary(self, rejected_files: List[tuple]):
        """Show summary of rejected files."""
        if not rejected_files:
            return

        message = f"{len(rejected_files)} file(s) were rejected:\n\n"
        for file_path, reason in rejected_files[:10]:  # Show first 10
            message += f"• {Path(file_path).name}: {reason}\n"

        if len(rejected_files) > 10:
            message += f"\n... and {len(rejected_files) - 10} more files."

        QMessageBox.warning(self, "Some Files Rejected", message)

    def format_file_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format."""
        if size_bytes == 0:
            return "0 B"

        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1

        return f"{size_bytes:.1f} {size_names[i]}"

    def set_supported_formats(self, formats: Set[str]):
        """Set supported file formats."""
        self.supported_formats = formats

    def set_max_file_size(self, size_mb: int):
        """Set maximum file size in MB."""
        self.max_file_size = size_mb * 1024 * 1024



# Demo integration
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # Test the file drop widget standalone

    window = QWidget()
    layout = QVBoxLayout(window)

    file_drop = FileDropWidget()
    layout.addWidget(file_drop)

    # Connect signals for testing
    file_drop.files_dropped.connect(
        lambda files: print(f"Files dropped: {files}"))
    file_drop.files_selected.connect(
        lambda files: print(f"Files selected: {files}"))
    file_drop.files_uploaded.connect(
        lambda files: print(f"Files uploaded: {files}"))

    window.setWindowTitle("File Drop Widget Test")
    window.resize(600, 700)
    window.show()


    sys.exit(app.exec())