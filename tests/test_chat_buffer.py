
import os
import pytest
from PySide6.QtWidgets import QApplication
from ui.widgets.chat_display import ChatDisplayWidget

# Ensure we can run without a display
os.environ["QT_QPA_PLATFORM"] = "offscreen"

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

def test_chat_buffer_flushing(qapp):
    widget = ChatDisplayWidget()
    
    # 1. Test partial JSON fence suppression
    # The string "~~~j" should stay in buffer because it's a prefix of "~~~json"
    widget.append_token("Hello ")
    widget.append_token("~~~j")
    
    # "Hello " should be visible, "~~~j" should be buffered
    assert "Hello" in widget._narrative_display.toPlainText()
    assert "~~~j" not in widget._narrative_display.toPlainText()
    assert widget._token_buf == "~~~j"

    # 2. Test final flush
    # flush_final_buffer should force the buffered "~~~j" to appear 
    # (since it never completed into a real fence)
    widget.flush_final_buffer()
    assert "Hello ~~~j" in widget._narrative_display.toPlainText()
    assert widget._token_buf == ""

def test_json_fence_filtering(qapp):
    widget = ChatDisplayWidget()
    
    # Send tokens including a full JSON block
    widget.append_token("Narrative start. ")
    widget.append_token("~~~json\n{\"key\": \"val\"}\n~~~")
    widget.append_token(" Narrative end.")
    
    text = widget._narrative_display.toPlainText()
    assert "Narrative start." in text
    assert "Narrative end." in text
    assert "{\"key\"" not in text
    assert "~~~json" not in text
