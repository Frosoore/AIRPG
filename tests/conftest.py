import pytest
import sys
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="session", autouse=True)
def q_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app
