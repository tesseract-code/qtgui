from __future__ import annotations

import mimetypes
import shutil
import uuid
from pathlib import Path

from PyQt6.QtCore import QDir, QUrl, QModelIndex, QThreadPool
from PyQt6.QtGui import QDesktopServices, QIcon, QPixmap, QColor
from PyQt6.QtWidgets import (QHBoxLayout, QAbstractItemView, QMenu,
                             QMessageBox, QTreeView, QToolButton)

from pycore.files import FileExtensionManager, FileInfo, FileExtensionCategory
from qtcore.worker import SyncWorker
from qtgui.file.watch.models.proxy import FileFilterProxyModel
from qtgui.file.watch.models.tree import FileTreeModel, FileNode
from qtgui.file.watch.watcher import DirectoryWatcher
from qtgui.pixmap import colorize_pixmap
from qtgui.edit import SearchLineEdit


# ---------------------------------------------------------------------------
# Pure filesystem helpers — run inside SyncWorker, zero Qt references
# ---------------------------------------------------------------------------

def _fs_delete(path: Path) -> None:
    """Delete a file or directory tree."""
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _fs_move(src: Path, dst_dir: Path) -> Path:
    """Move *src* into *dst_dir*, returning the new path."""
    destination = dst_dir / src.name
    if destination.exists():
        raise FileExistsError(
            f"'{src.name}' already exists in '{dst_dir}'."
        )
    shutil.move(str(src), str(dst_dir))
    return destination


def build_file_info(path: Path) -> FileInfo:
    mime_type, _ = mimetypes.guess_type(path)
    mime_type = mime_type or "application/octet-stream"

    stat = path.stat()

    # Resolve category via your existing manager, fall back to UNKNOWN
    category = FileExtensionManager.get_category(path.suffix.lower())
    if category is None:
        category = FileExtensionCategory.UNKNOWN

    return FileInfo(
        path=path,
        name=path.name,
        size=stat.st_size,
        mime_type=mime_type,
        category=category,
    )

import os
import sys
import ctypes
from pathlib import Path
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QObject
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFileDialog
)


# -------------------------------------------------------------------
# Platform‑specific on‑disk size for a single file
# -------------------------------------------------------------------
def get_file_on_disk_size(file_path: str) -> int:
    """
    Return the 'size on disk' for a single file.
    On Unix: st_blocks * 512
    On Windows: file size rounded up to the volume cluster size
    """
    try:
        if sys.platform == 'win32':
            # Get the volume cluster size using GetDiskFreeSpaceW
            drive = os.path.splitdrive(file_path)[0] + '\\'
            if not drive:
                drive = None  # current drive default

            sectors_per_cluster = ctypes.c_ulonglong(0)
            bytes_per_sector = ctypes.c_ulonglong(0)
            free_clusters = ctypes.c_ulonglong(0)
            total_clusters = ctypes.c_ulonglong(0)

            kernel32 = ctypes.windll.kernel32
            kernel32.GetDiskFreeSpaceW(
                ctypes.c_wchar_p(drive),
                ctypes.byref(sectors_per_cluster),
                ctypes.byref(bytes_per_sector),
                ctypes.byref(free_clusters),
                ctypes.byref(total_clusters)
            )
            cluster_size = sectors_per_cluster.value * bytes_per_sector.value

            file_size = os.path.getsize(file_path)
            if file_size == 0:
                return 0
            return ((file_size + cluster_size - 1) // cluster_size) * cluster_size
        else:
            # Unix (Linux, macOS)
            stat = os.stat(file_path)
            return stat.st_blocks * 512
    except OSError:
        return 0


# -------------------------------------------------------------------
# Worker that computes total size in a thread
# -------------------------------------------------------------------
class SizeCalculator(QObject):
    result_ready = pyqtSignal(int)   # total bytes (on disk)
    finished = pyqtSignal()

    def __init__(self, root_path: str):
        super().__init__()
        self.root_path = root_path
        self._is_running = True

    def stop(self):
        self._is_running = False

    def calculate(self):
        total = 0
        try:
            for entry in os.scandir(self.root_path):
                if not self._is_running:
                    break
                if entry.is_file(follow_symlinks=False):
                    total += get_file_on_disk_size(entry.path)
                elif entry.is_dir(follow_symlinks=False):
                    total += self._calc_dir_size(entry.path)
        except PermissionError:
            pass
        if self._is_running:
            self.result_ready.emit(total)
        self.finished.emit()

    def _calc_dir_size(self, dir_path: str) -> int:
        total = 0
        try:
            for entry in os.scandir(dir_path):
                if not self._is_running:
                    return 0
                if entry.is_file(follow_symlinks=False):
                    total += get_file_on_disk_size(entry.path)
                elif entry.is_dir(follow_symlinks=False):
                    total += self._calc_dir_size(entry.path)
        except PermissionError:
            pass
        return total


# -------------------------------------------------------------------
# Main monitoring widget
# -------------------------------------------------------------------
class FolderSizeMonitor(QWidget):
    """
    A PyQt6 widget that actively monitors the on‑disk size of a folder.

    Usage:
        monitor = FolderSizeMonitor()
        monitor.set_path('/path/to/folder')   # starts monitoring
        monitor.stop()                        # stops monitoring
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # UI layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)


        self.size_label = QLabel("Size: --")
        self.size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.size_label)

        # Internal state
        self.current_path = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._trigger_update)
        self._worker_thread = None
        self._worker = None

    def set_path(self, path: str):
        """Set the folder to monitor and start updating immediately."""
        self.stop()                        # stop any previous monitoring
        self.current_path = path
        self._start_monitoring()

    def stop(self):
        """Stop monitoring and clean up the background worker."""
        self._timer.stop()

        # Stop the worker (if running)
        worker = self._worker
        if worker:
            worker.stop()
            # Disconnect signals to avoid queued calls after cleanup
            try:
                worker.finished.disconnect(self._on_calculation_finished)
            except (TypeError, RuntimeError):
                pass
            self._worker = None

        # Quit and wait for the worker thread
        thread = self._worker_thread
        if thread:
            thread.quit()
            thread.wait(2000)
            thread.deleteLater()
            self._worker_thread = None

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _start_monitoring(self):
        """Begin periodic updates (every 1 second)."""
        self._timer.start(1000)
        self._trigger_update()   # immediate first update

    def _trigger_update(self):
        """Start a background size calculation if not already running."""
        if not self.current_path:
            return
        # Only allow one calculation at a time
        if self._worker_thread and self._worker_thread.isRunning():
            return

        # If there’s a leftover thread (shouldn't happen), clean it
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait()
            self._worker_thread.deleteLater()
            self._worker_thread = None

        # Create worker and thread
        self._worker_thread = QThread()
        self._worker = SizeCalculator(self.current_path)
        self._worker.moveToThread(self._worker_thread)

        self._worker_thread.started.connect(self._worker.calculate)
        self._worker.result_ready.connect(self._update_size_label)
        # Handle cleanup when the worker finishes
        self._worker.finished.connect(self._on_calculation_finished)

        self._worker_thread.start()

    def _on_calculation_finished(self):
        """Clean up worker and its thread after calculation ends."""
        if not self._worker or not self._worker_thread:
            return   # stop() already cleaned up

        worker = self._worker
        thread = self._worker_thread

        # Stop the worker (redundant but safe)
        worker.stop()

        # Disconnect to prevent re‑entry
        try:
            worker.finished.disconnect(self._on_calculation_finished)
        except (TypeError, RuntimeError):
            pass

        thread.quit()
        thread.wait()
        thread.deleteLater()

        self._worker = None
        self._worker_thread = None

    def _update_size_label(self, total_bytes: int):
        """Convert bytes to a human‑readable string and update the label."""
        if total_bytes < 1024:
            text = f"{total_bytes} B"
        elif total_bytes < 1024 ** 2:
            text = f"{total_bytes / 1024:.1f} KB"
        elif total_bytes < 1024 ** 3:
            text = f"{total_bytes / (1024 ** 2):.1f} MB"
        else:
            text = f"{total_bytes / (1024 ** 3):.2f} GB"
        self.size_label.setText(f"Size on disk: {text}")


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class DirectoryWidget(QWidget):
    file_opened = pyqtSignal(FileInfo)
    root_dir_changed = pyqtSignal(FileInfo)

    def __init__(self, start_dir: str = QDir.homePath(), parent=None):
        super().__init__(parent)
        self._current_dir = Path(start_dir)

        # ── Model & proxy ────────────────────────────────────────────────
        self._model = FileTreeModel(self._current_dir)
        self._proxy = FileFilterProxyModel()
        self._proxy.setSourceModel(self._model)

        # ── Tree view ────────────────────────────────────────────────────
        self._view = QTreeView()
        self._view.setModel(self._proxy)
        self._view.setHeaderHidden(True)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._show_context_menu)
        self._view.expanded.connect(self._on_expanded)

        # Drag and drop — items can be dragged out and directories accept
        # drops.  InternalMove is not used because we cross directory
        # boundaries and want the watcher to confirm the change.
        self._view.setDragEnabled(True)
        self._view.setAcceptDrops(True)
        self._view.setDropIndicatorShown(True)
        self._view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._view.setDefaultDropAction(Qt.DropAction.MoveAction)

        # ── Search bar ───────────────────────────────────────────────────
        self._search_bar = SearchLineEdit()
        self._search_bar.setPlaceholderText("Search files...")
        self._search_bar.textChanged.connect(self._proxy.setFilterText)

        # ── Toolbar button ───────────────────────────────────────────────
        self._dir_btn = QToolButton()
        self._dir_btn.setIcon(QIcon(colorize_pixmap(
            QPixmap("line-icons:folder-add.svg"), self.palette().highlight().color())))
        self._dir_btn.setStyleSheet("""background-color: palette(base);""")
        self._dir_btn.clicked.connect(self._choose_directory)
        self._dir_btn.setMaximumWidth(40)

        self._path_size = FolderSizeMonitor()
        self._path_size.set_path(str(self._current_dir))
        # ── Layout ───────────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        self._search_bar.setMinimumHeight(30)
        layout.addWidget(self._search_bar)
        layout.addWidget(self._view)

        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.addWidget(self._dir_btn)
        h_layout.addStretch()
        h_layout.addWidget(self._path_size, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(h_layout)
        self.setMinimumWidth(200)


        # ── Thread pool & worker registry ────────────────────────────────
        # _active_workers keeps a strong reference so the GC cannot collect
        # a worker while it is still running in the pool.
        self._pool = QThreadPool.globalInstance()
        self._active_workers: dict[str, SyncWorker] = {}

        # ── Watcher & model signal ───────────────────────────────────────
        self._watcher = None
        # The model emits move_requested when a drag-drop completes; we
        # treat it exactly like a context-menu move.
        self._model.move_requested.connect(self._on_move_requested)
        self._start_watching()

    # ------------------------------------------------------------------
    # Expand / fetch
    # ------------------------------------------------------------------

    def _on_expanded(self, index: QModelIndex):
        source_index = self._proxy.mapToSource(index)
        self._model.fetchMore(source_index)

    # ------------------------------------------------------------------
    # Watcher lifecycle
    # ------------------------------------------------------------------

    def _start_watching(self):
        self._stop_watching()
        self._model.reset_root(self._current_dir)
        self._model.fetchMore(QModelIndex())
        self._view.expand(self._model.index(0, 0, QModelIndex()))

        self._watcher = DirectoryWatcher(str(self._current_dir))
        self._watcher.files_added.connect(self._on_fs_added)
        self._watcher.files_modified.connect(self._on_fs_modified)
        self._watcher.files_deleted.connect(self._on_fs_deleted)
        self._watcher.start()

    def _stop_watching(self):
        if self._watcher is not None and self._watcher.isRunning():
            self._watcher.stop()

    def _on_fs_added(self, path_str: str, is_dir: bool):
        self._model.on_file_added(path_str, is_dir)

    def _on_fs_modified(self, path_str: str):
        self._model.on_file_modified(path_str)

    def _on_fs_deleted(self, path_str: str):
        self._model.on_file_removed(path_str)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos):
        index = self._view.indexAt(pos)
        if not index.isValid():
            return
        source_index = self._proxy.mapToSource(index)
        node: FileNode = source_index.internalPointer()

        menu = QMenu(self)

        if node.is_dir:
            open_action = menu.addAction("Open Folder")
            open_action.triggered.connect(
                lambda: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(node.path))))
        else:
            open_action = menu.addAction("Open")
            open_action.triggered.connect(
                lambda checked=False, p=node.path: self.file_opened.emit(
                    build_file_info(p)
                )
            )
            ext = node.path.suffix.lower()
            handler = FileExtensionManager.get_handler(ext)
            if handler:
                menu.addAction(f"Run handler for {ext}").triggered.connect(
                    lambda: handler(node.path))

        menu.addSeparator()

        move_action = menu.addAction("Move To…")
        move_action.triggered.connect(lambda: self._pick_destination(node.path))

        label = "Delete Folder…" if node.is_dir else "Delete File…"
        delete_action = menu.addAction(label)
        delete_action.triggered.connect(lambda: self._confirm_delete(node.path,
                                                                     node.is_dir))

        menu.exec(self._view.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Move — initiated by either context menu or drag-drop signal
    # ------------------------------------------------------------------

    def _pick_destination(self, src: Path):
        """Open a folder picker then schedule a move via SyncWorker."""
        dst_dir = QFileDialog.getExistingDirectory(
            self,
            f"Move '{src.name}' to…",
            str(src.parent),
        )
        if not dst_dir:
            return
        dst_path = Path(dst_dir)
        if dst_path == src.parent:
            QMessageBox.information(
                self, "Move",
                "The destination is the same as the current location."
            )
            return
        # Prevent moving a directory into itself or a descendant
        try:
            dst_path.relative_to(src)
            QMessageBox.warning(
                self, "Move",
                "Cannot move a folder into itself or one of its sub-folders."
            )
            return
        except ValueError:
            pass
        self._run_move(src, dst_path)

    def _on_move_requested(self, src_str: str, dst_dir_str: str):
        """Slot connected to FileTreeModel.move_requested (from drag-drop)."""
        self._run_move(Path(src_str), Path(dst_dir_str))

    def _run_move(self, src: Path, dst_dir: Path):
        job_id = f"move-{uuid.uuid4().hex}"
        worker = SyncWorker(job_id, _fs_move, src, dst_dir)
        worker.signals.finished.connect(
            lambda jid, _: self._active_workers.pop(jid, None)
        )
        worker.signals.error.connect(
            lambda jid, exc: self._on_worker_error(jid, exc, "Move failed", src)
        )
        self._active_workers[job_id] = worker
        self._pool.start(worker)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def _confirm_delete(self, path: Path, is_dir: bool):
        kind = "folder and all its contents" if is_dir else "file"
        answer = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Permanently delete the {kind}\n\n  {path}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_delete(path)

    def _run_delete(self, path: Path):
        job_id = f"delete-{uuid.uuid4().hex}"
        worker = SyncWorker(job_id, _fs_delete, path)
        worker.signals.finished.connect(
            lambda jid, _: self._active_workers.pop(jid, None)
        )
        worker.signals.error.connect(
            lambda jid, exc: self._on_worker_error(jid, exc, "Delete failed",
                                                   path)
        )
        self._active_workers[job_id] = worker
        self._pool.start(worker)

    # ------------------------------------------------------------------
    # Shared error handler
    # ------------------------------------------------------------------

    def _on_worker_error(self, job_id: str, exc: Exception,
                         title: str, path: Path):
        self._active_workers.pop(job_id, None)
        QMessageBox.critical(self, title, f"{path.name}:\n\n{exc}")

    # ------------------------------------------------------------------
    # Choose root directory
    # ------------------------------------------------------------------

    def _choose_directory(self):
        new_dir = QFileDialog.getExistingDirectory(
            self, "Select Root Directory", str(self._current_dir))
        if new_dir:
            self._current_dir = Path(new_dir)
            self._path_size.set_path(str(self._current_dir))
            self.root_dir_changed.emit(build_file_info(self._current_dir))
            self._start_watching()
