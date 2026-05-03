import os

from PyQt6.QtCore import QThread, pyqtSignal
from watchfiles import watch, Change

class DirectoryWatcher(QThread):
    files_added = pyqtSignal(str, bool)         # path, is_dir
    files_modified = pyqtSignal(str)
    files_deleted = pyqtSignal(str)

    def __init__(self, root_path: str, parent=None):
        super().__init__(parent)
        self._root_path = root_path
        self._running = False

    def run(self):
        self._running = True
        for changes in watch(self._root_path, recursive=True,
                             rust_timeout=1000):
            if not self._running:
                break
            for change, path_str in changes:
                if change == Change.added:
                    is_dir = os.path.isdir(path_str)  # we must check (watchfiles gives only path)
                    self.files_added.emit(path_str, is_dir)
                elif change == Change.modified:
                    self.files_modified.emit(path_str)
                elif change == Change.deleted:
                    self.files_deleted.emit(path_str)

    def stop(self):
        self._running = False
        self.wait(2000)