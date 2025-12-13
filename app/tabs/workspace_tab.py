from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QSettings, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

DEFAULT_BASE = Path.home() / "Documents" / "VRPTW"


class WorkspaceTab(QWidget):
    # Emits the full workspace path as a string when selection changes, or empty string if none
    workspaceChanged = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None, base_path: Optional[Path] = None) -> None:
        super().__init__(parent)
        self.setObjectName("WorkspaceTab")

        self.base_path = base_path or DEFAULT_BASE
        self.base_path.mkdir(parents=True, exist_ok=True)

        # Settings for persisting last-selected client/workspace
        self.settings = QSettings("VRPTW", "Workflow")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("Select or create a Client and Workspace")
        header.setStyleSheet("font-weight: 600;")
        header.setWordWrap(True)
        layout.addWidget(header)

        form = QFormLayout()

        # Client row
        client_row = QHBoxLayout()
        self.client_combo = QComboBox()
        self.refresh_clients()
        self.client_combo.currentIndexChanged.connect(self.on_client_changed)
        new_client_btn = QPushButton("New Client…")
        new_client_btn.clicked.connect(self.on_new_client)
        client_row.addWidget(self.client_combo)
        client_row.addWidget(new_client_btn)
        form.addRow("Client:", self._wrap(client_row))

        # Workspace row
        ws_row = QHBoxLayout()
        self.workspace_combo = QComboBox()
        self.refresh_workspaces()
        self.workspace_combo.currentIndexChanged.connect(self.on_workspace_changed)
        new_ws_btn = QPushButton("New Workspace…")
        new_ws_btn.clicked.connect(self.on_new_workspace)
        ws_row.addWidget(self.workspace_combo)
        ws_row.addWidget(new_ws_btn)
        form.addRow("Workspace:", self._wrap(ws_row))

        layout.addLayout(form)

        # Active path display
        self.active_path_label = QLineEdit()
        self.active_path_label.setReadOnly(True)
        self.active_path_label.setPlaceholderText("No workspace selected")
        layout.addWidget(self._labeled("Active path:", self.active_path_label))

        # Load last selections (if available) and initialize state
        self._load_last_selection()
        self.update_active_path()
        self._update_controls_enabled()

    # UI helpers
    def _wrap(self, inner_layout: QHBoxLayout) -> QWidget:
        w = QWidget()
        w.setLayout(inner_layout)
        return w

    def _labeled(self, label: str, widget: QWidget) -> QWidget:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addWidget(widget)
        w = QWidget()
        w.setLayout(row)
        return w

    # Filesystem helpers
    def list_clients(self) -> list[str]:
        if not self.base_path.exists():
            return []
        return sorted([p.name for p in self.base_path.iterdir() if p.is_dir()])

    def list_workspaces(self, client: str) -> list[str]:
        client_dir = self.base_path / client
        if not client_dir.exists():
            return []
        return sorted([p.name for p in client_dir.iterdir() if p.is_dir()])

    def refresh_clients(self) -> None:
        current = self.client_combo.currentText() if hasattr(self, "client_combo") else ""
        self.client_combo.clear()
        clients = self.list_clients()
        if not clients:
            self.client_combo.addItem("<no clients>")
            self.client_combo.setEnabled(True)
        else:
            self.client_combo.addItems(clients)
            # Restore selection if possible
            if current and current in clients:
                self.client_combo.setCurrentText(current)

    def refresh_workspaces(self) -> None:
        client = self.client_combo.currentText() if hasattr(self, "client_combo") else ""
        self.workspace_combo.clear()
        if not client or client == "<no clients>":
            self.workspace_combo.addItem("<no workspaces>")
            return
        workspaces = self.list_workspaces(client)
        if not workspaces:
            self.workspace_combo.addItem("<no workspaces>")
        else:
            self.workspace_combo.addItems(workspaces)
            # Auto-select the first workspace if none currently selected
            if self.workspace_combo.currentText() in ("", "<no workspaces>"):
                self.workspace_combo.setCurrentIndex(0)

    # Event handlers
    def on_client_changed(self) -> None:
        self.refresh_workspaces()
        # After repopulating, update the active path to reflect new selection (or none)
        self.update_active_path()
        self._update_controls_enabled()
        self._save_last_selection()

    def on_workspace_changed(self) -> None:
        self.update_active_path()
        self._update_controls_enabled()
        self._save_last_selection()

    def on_new_client(self) -> None:
        name, ok = QInputDialog.getText(self, "New Client", "Client name (e.g., JITB):")
        name = name.strip()
        if not ok or not name:
            return
        safe = self._sanitize_name(name)
        client_dir = self.base_path / safe
        if client_dir.exists():
            # Already exists: just select it
            pass
        else:
            client_dir.mkdir(parents=True, exist_ok=True)
        self.refresh_clients()
        self.client_combo.setCurrentText(safe)
        self.refresh_workspaces()
        self._update_controls_enabled()
        self._save_last_selection()

    def on_new_workspace(self) -> None:
        client = self.client_combo.currentText()
        if not client or client == "<no clients>":
            return
        name, ok = QInputDialog.getText(self, "New Workspace", "Workspace name (e.g., 5-team):")
        name = name.strip()
        if not ok or not name:
            return
        safe = self._sanitize_name(name)
        ws_dir = self.base_path / client / safe
        if ws_dir.exists():
            pass
        else:
            ws_dir.mkdir(parents=True, exist_ok=True)
        self.refresh_workspaces()
        self.workspace_combo.setCurrentText(safe)
        self.update_active_path()
        self._update_controls_enabled()
        self._save_last_selection()

    # State
    def update_active_path(self) -> None:
        path = self.current_workspace_path()
        if path:
            self.active_path_label.setText(str(path))
            self.workspaceChanged.emit(str(path))
        else:
            self.active_path_label.clear()
            self.workspaceChanged.emit("")

    def _update_controls_enabled(self) -> None:
        has_client = self.client_combo.currentText() not in ("", "<no clients>")
        # workspace combo enabled only if we have a client
        self.workspace_combo.setEnabled(has_client)

    def current_workspace_path(self) -> Optional[Path]:
        client = self.client_combo.currentText()
        workspace = self.workspace_combo.currentText()
        if (not client or client == "<no clients>") or (
            not workspace or workspace == "<no workspaces>"
        ):
            return None
        return self.base_path / client / workspace

    @staticmethod
    def _sanitize_name(name: str) -> str:
        # Simple sanitization: remove path separators and strip
        return name.replace("/", "-").replace("\\", "-").strip()

    # Persistence helpers
    def _load_last_selection(self) -> None:
        last_client = self.settings.value("lastClient", "", type=str) or ""
        last_workspace = self.settings.value("lastWorkspace", "", type=str) or ""
        clients = self.list_clients()
        if last_client and last_client in clients:
            self.client_combo.setCurrentText(last_client)
            # Workspaces depend on client; refresh then set
            self.refresh_workspaces()
            workspaces = self.list_workspaces(last_client)
            if last_workspace and last_workspace in workspaces:
                self.workspace_combo.setCurrentText(last_workspace)

    def _save_last_selection(self) -> None:
        client = self.client_combo.currentText()
        workspace = self.workspace_combo.currentText()
        if client and client != "<no clients>":
            self.settings.setValue("lastClient", client)
        if workspace and workspace != "<no workspaces>":
            self.settings.setValue("lastWorkspace", workspace)
