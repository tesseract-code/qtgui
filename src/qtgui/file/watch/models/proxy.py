from PyQt6.QtCore import QSortFilterProxyModel, QModelIndex

from qtgui.file.watch.models.tree import FileNode


class FileFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_text = ""

    def setFilterText(self, text: str):
        self._filter_text = text.strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self._filter_text:
            return True
        source_model = self.sourceModel()
        index = source_model.index(source_row, 0, source_parent)
        node: FileNode = index.internalPointer()
        # If the node itself matches, accept it
        if self._matches(node.name):
            return True
        # Accept folders that contain a matching descendant
        if node.is_dir:
            return self._has_matching_child(index)
        return False

    def _matches(self, name: str) -> bool:
        return self._filter_text.lower() in name.lower()

    def _has_matching_child(self, parent_index: QModelIndex) -> bool:
        """Recursive check – ensures folder stays if any grandchild matches."""
        model = self.sourceModel()
        row_count = model.rowCount(parent_index)
        for r in range(row_count):
            child_idx = model.index(r, 0, parent_index)
            child_node: FileNode = child_idx.internalPointer()
            if self._matches(child_node.name):
                return True
            if child_node.is_dir and self._has_matching_child(child_idx):
                return True
        return False