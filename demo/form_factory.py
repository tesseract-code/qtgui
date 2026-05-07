import sys
from dataclasses import dataclass
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton

from qtgui.form.widget import create_form_for_callable, \
    create_callable_from_dataclass_instance


@dataclass
class AppSettings:
    """A dataclass representing application settings."""
    width: int = 800
    height: int = 600
    title: str = "My App"
    fullscreen: bool = False
    opacity: float = 1.0


# 1) Create an instance with the current ("live") values
current_settings = AppSettings(width=1024, height=768, title="Editor", fullscreen=True, opacity=0.95)

# 2) Make it callable – returns a class where the __init__ defaults match the instance values
CallableSettings = create_callable_from_dataclass_instance(current_settings)

# Now CallableSettings(...) will use 1024, 768, "Editor", True, 0.95 as defaults,
# while the annotations are unwrapped (e.g., Optional[int] → int).


class ExampleWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dynamic Form from Dataclass Instance")
        self.setMinimumSize(400, 300)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 3) Generate the form using the callable we just created
        #    Optional group_mapping can organise fields into collapsible groups.
        self.form = create_form_for_callable(CallableSettings, group_mapping=None, parent=self)

        # 4) Add a button to retrieve and display the current form values
        submit_btn = QPushButton("Show Current Values")
        submit_btn.clicked.connect(self.on_submit)

        layout.addWidget(self.form)
        layout.addWidget(submit_btn)

    def on_submit(self):
        # The DynamicFormWidget typically provides a method to get the current data.
        # Here we assume a 'get_data()' method returns a dictionary of field names to values.
        # (Adjust to your actual form API if different, e.g., form.current_values)
        data = self.form.get_values()
        print("Form values:", data)
        # Example output: {'width': 1024, 'height': 768, 'title': 'Editor', 'fullscreen': True, 'opacity': 0.95}
        # You can now instantiate AppSettings with these values, save them, etc.
        new_settings = AppSettings(**data)
        print("New settings object:", new_settings)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ExampleWindow()
    window.show()
    sys.exit(app.exec())