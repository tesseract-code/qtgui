from __future__ import annotations

import ctypes
import mimetypes
import os
import shutil
import sys
import uuid
from pathlib import Path

from PyQt6.QtCore import QDir, QUrl, QModelIndex, QThreadPool
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QObject
)
from PyQt6.QtGui import QDesktopServices, QIcon, QPixmap
from PyQt6.QtWidgets import (QHBoxLayout, QAbstractItemView, QMenu,
                             QMessageBox, QTreeView, QToolButton)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFileDialog
)

from pycore.files import FileExtensionManager, FileInfo, FileExtensionCategory
from qtcore.worker import SyncWorker
from qtgui.edit import SearchLineEdit
from qtgui.file.watch.models.proxy import FileFilterProxyModel
from qtgui.file.watch.models.tree import FileTreeModel, FileNode
from qtgui.file.watch.watcher import DirectoryWatcher
from qtgui.pixmap import colorize_pixmap


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


# -------------------------------------------------------------------
# Platform‑specific on‑disk size for a single file
# -------------------------------------------------------------------
import ctypes
import os
import sys

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


# -------------------------------------------------------------------
# Disk allocation helpers
# -------------------------------------------------------------------

def _get_windows_cluster_size(path: str) -> int:
    """
    Return the filesystem cluster size for the volume containing *path*.

    Raises OSError if the Win32 API calls fail.
    """
    kernel32 = ctypes.windll.kernel32

    # Use a long buffer so paths longer than MAX_PATH have room.
    volume_root = ctypes.create_unicode_buffer(32768)

    abs_path = os.path.abspath(path)

    if not kernel32.GetVolumePathNameW(
        ctypes.c_wchar_p(abs_path),
        volume_root,
        len(volume_root),
    ):
        raise ctypes.WinError()

    sectors_per_cluster = ctypes.c_ulong(0)
    bytes_per_sector = ctypes.c_ulong(0)
    free_clusters = ctypes.c_ulong(0)
    total_clusters = ctypes.c_ulong(0)

    if not kernel32.GetDiskFreeSpaceW(
        ctypes.c_wchar_p(volume_root.value),
        ctypes.byref(sectors_per_cluster),
        ctypes.byref(bytes_per_sector),
        ctypes.byref(free_clusters),
        ctypes.byref(total_clusters),
    ):
        raise ctypes.WinError()

    cluster_size = sectors_per_cluster.value * bytes_per_sector.value
    if cluster_size <= 0:
        raise OSError("Invalid cluster size returned by GetDiskFreeSpaceW")

    return cluster_size


def get_file_on_disk_size(file_path: str) -> int:
    """
    Return the approximate allocated size, or "size on disk", for one file.

    Unix:
        Uses st_blocks * 512 when available.

    Windows:
        Uses logical file size rounded up to the filesystem cluster size.

    Notes:
        Windows sparse, compressed, deduplicated, cloud-placeholder, and
        special filesystem files may not match Explorer exactly.
    """
    try:
        if sys.platform == "win32":
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                return 0

            cluster_size = _get_windows_cluster_size(file_path)
            return ((file_size + cluster_size - 1) // cluster_size) * cluster_size

        stat_result = os.stat(file_path, follow_symlinks=False)

        # st_blocks is standard on Unix-like systems, but use st_size as a
        # fallback for unusual platforms/filesystems where it is unavailable.
        blocks = getattr(stat_result, "st_blocks", None)
        if blocks is not None:
            return blocks * 512

        return stat_result.st_size

    except OSError:
        return 0


# -------------------------------------------------------------------
# Worker that computes total size in a thread
# -------------------------------------------------------------------

class SizeCalculator(QObject):
    """
    Background worker that calculates allocated disk size.

    Signals
    -------
    result_ready(generation, total_bytes)
        Emitted only if the worker was not cancelled.

    finished(generation)
        Always emitted when the worker exits.
    """

    result_ready = pyqtSignal(int, int)
    finished = pyqtSignal(int)

    def __init__(self, root_path: str, generation: int):
        super().__init__()
        self.root_path = root_path
        self.generation = generation
        self._is_running = True

    def stop(self):
        self._is_running = False

    def calculate(self):
        total = 0

        try:
            if os.path.isfile(self.root_path):
                if self._is_running:
                    total = get_file_on_disk_size(self.root_path)

            elif os.path.isdir(self.root_path):
                total = self._calc_dir_size_iterative(self.root_path)

        except OSError:
            total = 0

        if self._is_running:
            self.result_ready.emit(self.generation, total)

        self.finished.emit(self.generation)

    def _calc_dir_size_iterative(self, root_dir: str) -> int:
        """
        Iteratively scan a directory tree.

        This avoids Python recursion limits and handles disappearing files,
        permission errors, and broken entries gracefully.
        """
        total = 0
        stack = [root_dir]

        while stack and self._is_running:
            dir_path = stack.pop()

            try:
                with os.scandir(dir_path) as entries:
                    for entry in entries:
                        if not self._is_running:
                            return 0

                        try:
                            if entry.is_file(follow_symlinks=False):
                                total += get_file_on_disk_size(entry.path)

                            elif entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)

                        except OSError:
                            # Entry may disappear, be inaccessible, or fail
                            # metadata lookup. Ignore and continue.
                            continue

            except OSError:
                # Permission denied, deleted directory, invalid path, etc.
                continue

        return total if self._is_running else 0


# -------------------------------------------------------------------
# Main monitoring widget
# -------------------------------------------------------------------

class FolderSizeMonitor(QWidget):
    """
    A PyQt6 widget that actively monitors the on-disk size of a folder.

    Usage:
        monitor = FolderSizeMonitor()
        monitor.set_path("/path/to/folder")
        monitor.stop()
    """

    def __init__(self, parent=None, interval_ms: int = 1000):
        super().__init__(parent)

        self.interval_ms = interval_ms

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.size_label = QLabel("Size: --")
        self.size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.size_label)

        self.current_path: str | None = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._trigger_update)

        self._worker_thread: QThread | None = None
        self._worker: SizeCalculator | None = None

        # Incremented whenever monitoring is reset/stopped so stale queued
        # signals from previous workers cannot update the label.
        self._generation = 0

    def set_path(self, path: str):
        """
        Set the file or folder to monitor and start updating immediately.
        """
        self.stop()

        self.current_path = path
        self._generation += 1

        if not path or not os.path.exists(path):
            self.size_label.setText("Size: --")
            return

        self._start_monitoring()

    def stop(self):
        """
        Stop monitoring and request background worker cancellation.

        This method never deletes a still-running QThread. If the worker does
        not stop within the timeout, cleanup is completed when the worker
        eventually emits finished.
        """
        self._timer.stop()
        self._generation += 1

        worker = self._worker
        thread = self._worker_thread

        if worker is not None:
            worker.stop()

        if thread is not None:
            thread.quit()

            if thread.wait(2000):
                # Thread has stopped. Normal signal-based deleteLater cleanup
                # may already be queued, but clearing references is safe.
                self._worker = None
                self._worker_thread = None
            else:
                # Do not delete or null the running thread. It will be cleaned
                # up in _clear_worker_refs() after finished is emitted.
                pass

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _start_monitoring(self):
        self._timer.start(self.interval_ms)
        self._trigger_update()

    def _trigger_update(self):
        """
        Start a background size calculation if one is not already running.
        """
        if not self.current_path:
            return

        if not os.path.exists(self.current_path):
            self.size_label.setText("Size: --")
            return

        # Only allow one calculation at a time.
        if self._worker_thread is not None and self._worker_thread.isRunning():
            return

        # Clear any stale non-running thread reference.
        if self._worker_thread is not None:
            self._worker_thread = None
            self._worker = None

        generation = self._generation

        thread = QThread(self)
        worker = SizeCalculator(self.current_path, generation)
        worker.moveToThread(thread)

        self._worker_thread = thread
        self._worker = worker

        thread.started.connect(worker.calculate)

        worker.result_ready.connect(self._update_size_label)

        # Safe Qt cleanup pattern.
        worker.finished.connect(lambda _gen: thread.quit())
        worker.finished.connect(lambda _gen: worker.deleteLater())
        thread.finished.connect(thread.deleteLater)

        # Clear Python references after the thread finishes.
        thread.finished.connect(
            lambda t=thread, w=worker, g=generation: self._clear_worker_refs(t, w, g)
        )

        thread.start()

    def _clear_worker_refs(
        self,
        thread: QThread,
        worker: SizeCalculator,
        generation: int,
    ):
        """
        Clear worker/thread refs only if they still refer to this calculation.
        """
        if self._worker_thread is thread:
            self._worker_thread = None

        if self._worker is worker:
            self._worker = None

    def _update_size_label(self, generation: int, total_bytes: int):
        """
        Convert bytes to a human-readable string and update the label.

        Stale results from older workers are ignored.
        """
        if generation != self._generation:
            return

        self.size_label.setText(
            f"Size on disk: {self._format_bytes(total_bytes)}"
        )

    @staticmethod
    def _format_bytes(total_bytes: int) -> str:
        if total_bytes < 1024:
            return f"{total_bytes} B"

        if total_bytes < 1024 ** 2:
            return f"{total_bytes / 1024:.2f} KB"

        if total_bytes < 1024 ** 3:
            return f"{total_bytes / (1024 ** 2):.2f} MB"

        if total_bytes < 1024 ** 4:
            return f"{total_bytes / (1024 ** 3):.2f} GB"

        return f"{total_bytes / (1024 ** 4):.2f} TB"

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)

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
            QPixmap("line-icons:folder-add.svg"),
            self.palette().highlight().color())))
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
        h_layout.addWidget(self._path_size,
                           alignment=Qt.AlignmentFlag.AlignRight)
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
