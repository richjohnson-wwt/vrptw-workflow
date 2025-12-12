from __future__ import annotations

from PyQt6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
)

from .tabs.workspace_tab import WorkspaceTab
from .tabs.parse_tab import ParseTab
from .tabs.geocode_tab import GeocodeTab
from .tabs.cluster_tab import ClusterTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VRPTW Workflow")
        self.resize(1100, 800)

        # Central layout with active path bar above tabs
        central = QWidget(self)
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(6, 6, 6, 6)
        vbox.setSpacing(6)

        # Active workspace path display
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Active workspace:"))
        self.path_display = QLineEdit()
        self.path_display.setReadOnly(True)
        self.path_display.setPlaceholderText("No workspace selected")
        path_row.addWidget(self.path_display)
        vbox.addLayout(path_row)

        # Tabs
        self.tabs = QTabWidget()
        vbox.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        # Add tabs (Workspace first)
        self.workspace_tab = WorkspaceTab(self)
        self.parse_tab = ParseTab(self)
        self.geocode_tab = GeocodeTab(self)
        self.cluster_tab = ClusterTab(self)

        self.tabs.addTab(self.workspace_tab, "Workspace")
        self.tabs.addTab(self.parse_tab, "Parse")
        self.tabs.addTab(self.geocode_tab, "Geocode")
        self.tabs.addTab(self.cluster_tab, "Cluster")

        # Disable other tabs until a workspace is selected
        self._set_workflow_tabs_enabled(False)

        # React to workspace selection
        self.workspace_tab.workspaceChanged.connect(self.on_workspace_changed)

        # If workspace already selected during tab init, reflect it and enable tabs
        current_path = self.workspace_tab.current_workspace_path()
        self.on_workspace_changed(str(current_path) if current_path else "")

    def _set_workflow_tabs_enabled(self, enabled: bool) -> None:
        # Indices: 0 Workspace, 1 Parse, 2 Geocode, 3 Cluster
        for idx in (1, 2, 3):
            self.tabs.setTabEnabled(idx, enabled)

    def on_workspace_changed(self, path_str: str) -> None:
        # Update global path display and enable tabs when a valid workspace is selected
        if path_str:
            self.path_display.setText(path_str)
        else:
            self.path_display.clear()
        self._set_workflow_tabs_enabled(bool(path_str))
        # Propagate to tabs that care about workspace
        for tab in (getattr(self, "parse_tab", None), getattr(self, "geocode_tab", None), getattr(self, "cluster_tab", None)):
            if tab is not None and hasattr(tab, "set_workspace"):
                try:
                    tab.set_workspace(path_str)
                except Exception:
                    pass
