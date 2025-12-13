import os
import sys

import pytest


@pytest.mark.skipif(
    sys.platform.startswith("win") and os.environ.get("CI") == "true",
    reason="Windows CI may lack Qt platform plugins",
)
def test_main_window_instantiates():
    # Ensure Qt can run headless
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from app.main_window import MainWindow

    QApplication.instance() or QApplication(sys.argv)
    w = MainWindow()
    try:
        assert w.windowTitle() == "VRPTW Workflow"
    finally:
        w.close()
        # Do not call app.quit() here; pytest may run multiple tests
