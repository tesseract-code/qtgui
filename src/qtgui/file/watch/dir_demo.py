import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtCore import QDir

from pycore.files import FileExtensionManager, FileExtensionCategory
from qtgui.file.watch.widget import DirectoryWidget


# Assuming AsyncDirectoryWidget is in a module named async_dir_widget

def my_json_handler(path: Path):
    print(f"Custom handler for JSON: {path}")

FileExtensionManager.register_extension(
    '.json',
    FileExtensionCategory.CODE,
    handler=my_json_handler,
    metadata={'description': 'JSON file handler'}
)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Async Directory Watcher")
        self.setGeometry(100, 100, 800, 600)
        # Create the widget with home directory as start
        self.dir_widget = DirectoryWidget(start_dir=QDir.homePath())
        self.setCentralWidget(self.dir_widget)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())