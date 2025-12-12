from __future__ import annotations

from typing import Optional
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QFormLayout,
)


class ClusterTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ClusterTab")
        self.workspace: Optional[Path] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("Cluster geocoded points into groups (e.g., k-means or capacity-based)")
        header.setWordWrap(True)
        header.setStyleSheet("font-weight: 600;")
        layout.addWidget(header)

        # Workspace banner
        self.banner = QLabel("Workspace: (none)")
        self.banner.setStyleSheet("color: #555; font-style: italic;")
        self.banner.setWordWrap(True)
        layout.addWidget(self.banner)

        form = QFormLayout()
        self.k_clusters = QSpinBox()
        self.k_clusters.setRange(1, 1000)
        self.k_clusters.setValue(10)
        form.addRow("Number of clusters:", self.k_clusters)

        layout.addLayout(form)

        actions_row = QHBoxLayout()
        self.cluster_btn = QPushButton("Run clustering")
        self.cluster_btn.clicked.connect(self.on_cluster)
        actions_row.addStretch(1)
        actions_row.addWidget(self.cluster_btn)
        layout.addLayout(actions_row)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(200)
        self.log.setPlaceholderText("Clustering logs will appear here…")
        layout.addWidget(self.log, 1)

        layout.addStretch(1)

    # Workspace API for MainWindow
    def set_workspace(self, path_str: str) -> None:
        # Update workspace and clear logs to avoid mixing scenarios
        self.workspace = Path(path_str) if path_str else None
        if hasattr(self, "log"):
            self.log.clear()
        if hasattr(self, "banner"):
            self.banner.setText(f"Workspace: {path_str}" if path_str else "Workspace: (none)")

    def on_cluster(self) -> None:
        k = int(self.k_clusters.value())
        self.log_append(f"Running clustering with k={k} (placeholder)…")
        # TODO: Implement real clustering once data model is ready
        self.log_append("Clustering complete (placeholder).")

    def log_append(self, msg: str) -> None:
        self.log.append(msg)
        self.log.moveCursor(QTextCursor.MoveOperation.End)
        self.log.ensureCursorVisible()
