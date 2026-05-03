import json
import os
from pathlib import Path
from typing import Optional, List

from PyQt6.QtCore import (QAbstractItemModel, QModelIndex, QMimeData,
                           Qt, QFileInfo, pyqtSignal)
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QFileIconProvider

from pycore.files import FileExtensionCategory, FileTypeHelper


# MIME type used to carry dragged paths between model and drop target
_MIME_TYPE = "application/x-filetree-paths"


class FileNode:
    __slots__ = ('path', 'name', 'is_dir', 'size', 'mime_type',
                 'category', 'line_count', 'preview_available',
                 'parent', 'children', 'loaded')

    def __init__(self, path: str | Path, is_dir: bool,
                 parent: Optional['FileNode'] = None):
        self.path = Path(path)
        self.name = self.path.name or str(path)  # root might be empty
        self.is_dir = is_dir
        self.size = 0
        self.mime_type = ''
        self.category = FileExtensionCategory.UNKNOWN
        self.line_count = None
        self.preview_available = False
        self.parent = parent
        self.children: List['FileNode'] = []
        self.loaded = False

        if not is_dir:
            self._populate_file_info()

    def _populate_file_info(self):
        try:
            self.size = self.path.stat().st_size
        except OSError:
            self.size = 0
        self.mime_type = FileTypeHelper.get_mime_type(self.path)
        self.category = FileTypeHelper.get_category(self.path)
        self.preview_available = FileTypeHelper.can_preview_image(self.path)


class FileTreeModel(QAbstractItemModel):
    # Custom roles
    NameRole      = Qt.ItemDataRole.DisplayRole
    PathRole      = Qt.ItemDataRole.UserRole + 100
    SizeRole      = Qt.ItemDataRole.UserRole + 101
    MimeRole      = Qt.ItemDataRole.UserRole + 102
    CategoryRole  = Qt.ItemDataRole.UserRole + 103
    IsDirRole     = Qt.ItemDataRole.UserRole + 104
    PreviewRole   = Qt.ItemDataRole.UserRole + 105

    # Emitted when a drag-drop move should be executed (src_path, dst_dir)
    # The widget connects this to SyncWorker — no file I/O happens here.
    move_requested = pyqtSignal(str, str)

    def __init__(self, root_path: Path, parent=None):
        super().__init__(parent)
        self._root_path = Path(root_path)
        self._root_node = FileNode(self._root_path, is_dir=True)
        self._icon_provider = QFileIconProvider()
        self._icon_cache: dict = {}

    # ------------------------------------------------------------------
    # QAbstractItemModel interface
    # ------------------------------------------------------------------

    def index(self, row: int, column: int, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_node = parent.internalPointer() if parent.isValid() else self._root_node
        child = parent_node.children[row]
        return self.createIndex(row, column, child)

    def parent(self, index: QModelIndex):
        if not index.isValid():
            return QModelIndex()
        node: FileNode = index.internalPointer()
        if node.parent is None or node.parent is self._root_node:
            return QModelIndex()
        grandparent = node.parent
        if grandparent.parent is None:
            return self.createIndex(0, 0, grandparent)
        row = grandparent.parent.children.index(grandparent)
        return self.createIndex(row, 0, grandparent)

    def rowCount(self, parent=QModelIndex()):
        if parent.column() > 0:
            return 0
        node = parent.internalPointer() if parent.isValid() else self._root_node
        return len(node.children)

    def columnCount(self, parent=QModelIndex()):
        return 1

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node: FileNode = index.internalPointer()
        if role == Qt.ItemDataRole.DisplayRole:
            return node.name
        elif role == Qt.ItemDataRole.DecorationRole:
            if node.is_dir:
                return self._icon_provider.icon(QFileIconProvider.IconType.Folder)
            ext = node.path.suffix.lower()
            icon = self._icon_cache.get(ext)
            if icon is None:
                icon = self._icon_provider.icon(QFileInfo(str(node.path)))
                self._icon_cache[ext] = icon
            return icon
        elif role == self.SizeRole:
            return node.size if not node.is_dir else None
        elif role == self.MimeRole:
            return node.mime_type
        elif role == self.CategoryRole:
            return node.category
        elif role == self.PathRole:
            return node.path
        elif role == self.IsDirRole:
            return node.is_dir
        elif role == self.PreviewRole:
            return node.preview_available
        return None

    def hasChildren(self, parent=QModelIndex()):
        node = parent.internalPointer() if parent.isValid() else self._root_node
        return node.is_dir  # directories always might have children

    def canFetchMore(self, parent: QModelIndex):
        node = parent.internalPointer() if parent.isValid() else self._root_node
        return node.is_dir and not node.loaded

    def fetchMore(self, parent: QModelIndex):
        node = parent.internalPointer() if parent.isValid() else self._root_node
        if not node.is_dir or node.loaded:
            return
        children = []
        try:
            for entry in os.scandir(str(node.path)):
                child_node = FileNode(Path(entry.path),
                                      is_dir=entry.is_dir(),
                                      parent=node)
                children.append(child_node)
        except OSError:
            pass
        self.beginInsertRows(parent, 0, max(len(children) - 1, 0))
        node.children = children
        node.loaded = True
        self.endInsertRows()

    # ------------------------------------------------------------------
    # Drag and drop
    # ------------------------------------------------------------------

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if not index.isValid():
            return base
        node: FileNode = index.internalPointer()
        # Every item can be dragged
        result = base | Qt.ItemFlag.ItemIsDragEnabled
        # Only directories (and the invisible root) accept drops
        if node.is_dir:
            result |= Qt.ItemFlag.ItemIsDropEnabled
        return result

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:
        return [_MIME_TYPE]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:
        """Encode the dragged paths as JSON inside the custom MIME type."""
        paths = [
            str(idx.internalPointer().path)
            for idx in indexes
            if idx.isValid() and idx.column() == 0
        ]
        mime = QMimeData()
        mime.setData(_MIME_TYPE, json.dumps(paths).encode())
        return mime

    def dropMimeData(self, data: QMimeData, action: Qt.DropAction,
                     row: int, column: int, parent: QModelIndex) -> bool:
        """
        Called by Qt (via the proxy's forwarding) when items are dropped.
        We don't do any I/O here; we emit move_requested so the widget can
        hand the work off to a SyncWorker on the thread pool.
        """
        if action == Qt.DropAction.IgnoreAction:
            return True
        if not data.hasFormat(_MIME_TYPE):
            return False

        # Resolve the destination directory
        if parent.isValid():
            dst_node: FileNode = parent.internalPointer()
            dst_dir = dst_node.path if dst_node.is_dir else dst_node.path.parent
        else:
            # Dropped on empty space → root directory
            dst_dir = self._root_path

        paths: list[str] = json.loads(bytes(data.data(_MIME_TYPE)).decode())
        for src_str in paths:
            src = Path(src_str)

            # Skip: item is already in that directory
            if src.parent == dst_dir:
                continue

            # Skip: would move a directory inside itself or a descendant
            try:
                dst_dir.relative_to(src)
                continue
            except ValueError:
                pass  # dst_dir is NOT inside src — safe to proceed

            self.move_requested.emit(src_str, str(dst_dir))

        return True

    # ------------------------------------------------------------------
    # Filesystem update methods — called by DirectoryWatcher signals
    # ------------------------------------------------------------------

    def on_file_added(self, file_path: str, is_dir: bool):
        path = Path(file_path)
        parent_index = self._find_index_for_path(path.parent)
        if parent_index is None:
            return
        parent_node: FileNode = (
            parent_index.internalPointer()
            if parent_index.isValid()
            else self._root_node
        )
        if not parent_node.loaded:
            return
        for child in parent_node.children:
            if child.path == path:
                return
        new_node = FileNode(path, is_dir=is_dir, parent=parent_node)
        row = len(parent_node.children)
        self.beginInsertRows(parent_index, row, row)
        parent_node.children.append(new_node)
        self.endInsertRows()

    def on_file_removed(self, file_path: str):
        path = Path(file_path)
        index = self._find_index_for_path(path)
        if index is None or not index.isValid():
            return
        node: FileNode = index.internalPointer()
        parent_index = self.parent(index)
        parent_node: FileNode = (
            parent_index.internalPointer()
            if parent_index.isValid()
            else self._root_node
        )
        row = parent_node.children.index(node)
        self.beginRemoveRows(parent_index, row, row)
        del parent_node.children[row]
        self.endRemoveRows()

    def on_file_modified(self, file_path: str):
        index = self._find_index_for_path(Path(file_path))
        if index is None or not index.isValid():
            return
        node: FileNode = index.internalPointer()
        if not node.is_dir:
            node._populate_file_info()
        self.dataChanged.emit(index, index, [])

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _find_index_for_path(self, path: Path) -> Optional[QModelIndex]:
        """Walk the loaded tree to find the QModelIndex for *path*."""
        if path == self._root_path:
            return QModelIndex()
        try:
            parts = path.relative_to(self._root_path).parts
        except ValueError:
            return None
        current_node = self._root_node
        current_index = QModelIndex()
        for part in parts:
            if not current_node.loaded:
                return None
            for row, child in enumerate(current_node.children):
                if child.name == part:
                    current_index = self.index(row, 0, current_index)
                    current_node = child
                    break
            else:
                return None
        return current_index

    def reset_root(self, new_root: Path):
        self.beginResetModel()
        self._root_path = Path(new_root)
        self._root_node = FileNode(self._root_path, is_dir=True)
        self._icon_cache.clear()
        self.endResetModel()