from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Optional

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
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

        # Controls common to clustering
        form = QFormLayout()
        self.k_clusters = QSpinBox()
        self.k_clusters.setRange(1, 1000)
        self.k_clusters.setValue(10)
        form.addRow("Number of clusters:", self.k_clusters)
        layout.addLayout(form)

        # Sub-tabs: Log and Clustering View
        self.subtabs = QTabWidget()
        self.subtabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Log tab
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        self.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log.setPlaceholderText("Clustering logs will appear here…")
        self.subtabs.addTab(self.log, "Log")

        # Clustering tab (list of states on left, table preview on right)
        self.view = QWidget()
        self._init_view_tab(self.view)
        self.subtabs.addTab(self.view, "Clustering")

        layout.addWidget(self.subtabs, 1)
        # Removed extra stretch to allow subtabs to occupy full vertical space

    # Workspace API for MainWindow
    def set_workspace(self, path_str: str) -> None:
        # Update workspace and clear logs to avoid mixing scenarios
        self.workspace = Path(path_str) if path_str else None
        if hasattr(self, "log"):
            self.log.clear()
        if hasattr(self, "banner"):
            self.banner.setText(f"Workspace: {path_str}" if path_str else "Workspace: (none)")
        # Refresh clustering view
        self.refresh_state_list()
        self.clear_table()
        if hasattr(self, "cluster_btn"):
            self.cluster_btn.setEnabled(False)

    def on_cluster(self) -> None:
        # Trigger clustering for the currently selected state
        if not self.workspace:
            QMessageBox.warning(self, "No workspace", "Please select a workspace first.")
            return
        state = self.state_list.currentItem().text() if self.state_list.currentItem() else ""
        if not state:
            QMessageBox.information(self, "Select a state", "Please select a state to cluster.")
            return
        k = int(self.k_clusters.value())
        self.log_append(f"Clustering state {state} with k={k}…")
        state_dir = self.workspace / state
        geo_csv = state_dir / "geocoded.csv"
        out_csv = state_dir / "clustered.csv"
        if not geo_csv.exists():
            self.log_append(f"State {state}: geocoded.csv not found at {geo_csv}")
            QMessageBox.warning(self, "Missing geocoded.csv", f"Could not find {geo_csv}")
            return
        # Read data with pandas; do lazy import to keep app light if unused
        try:
            import pandas as pd
        except Exception as e:
            self.log_append(f"Pandas not available: {e}")
            QMessageBox.critical(self, "Dependency missing", "pandas is required for clustering.")
            return
        try:
            from sklearn.cluster import KMeans
        except Exception as e:
            self.log_append(f"scikit-learn not available: {e}")
            QMessageBox.critical(
                self, "Dependency missing", "scikit-learn is required for KMeans clustering."
            )
            return

        try:
            df = pd.read_csv(geo_csv)
        except Exception as e:
            self.log_append(f"Failed reading {geo_csv}: {e}")
            QMessageBox.critical(self, "Read error", f"Failed to read {geo_csv}: {e}")
            return

        # Determine lat/lon column names robustly
        cols = {c.lower(): c for c in df.columns}
        lat_col = cols.get("lat") or cols.get("latitude")
        lon_col = cols.get("lon") or cols.get("longitude")
        if not lat_col or not lon_col:
            self.log_append(
                "Could not find latitude/longitude columns (lat/lon or latitude/longitude)."
            )
            QMessageBox.warning(
                self,
                "Missing columns",
                "Expected latitude/longitude columns (lat/lon or latitude/longitude).",
            )
            return

        try:
            X = df[[lat_col, lon_col]].to_numpy()
            if len(X) == 0:
                self.log_append(f"State {state}: no rows to cluster.")
                return
            k = max(1, min(k, len(X)))
            model = KMeans(n_clusters=k, n_init="auto", random_state=42)
            labels = model.fit_predict(X)
            df["cluster_id"] = labels
            df.to_csv(out_csv, index=False)
            self.log_append(f"State {state}: wrote clustered.csv with {k} clusters -> {out_csv}")
            # Reload preview on success
            self._load_table_from_csv(out_csv)
        except Exception as e:
            self.log_append(f"State {state}: clustering failed: {e}")
            QMessageBox.critical(self, "Clustering failed", str(e))

    def log_append(self, msg: str) -> None:
        self.log.append(msg)
        self.log.moveCursor(QTextCursor.MoveOperation.End)
        self.log.ensureCursorVisible()

    # --- View tab helpers ---
    def _init_view_tab(self, container: QWidget) -> None:
        outer = QHBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # Left: State list and actions
        left_box = QVBoxLayout()
        left_label = QLabel("States")
        left_label.setStyleSheet("font-weight: 600;")
        self.state_list = QListWidget()
        self.state_list.setMinimumWidth(160)
        self.state_list.currentTextChanged.connect(self.on_state_selected)
        left_box.addWidget(left_label)
        left_box.addWidget(self.state_list, 1)

        actions_row = QHBoxLayout()
        self.cluster_btn = QPushButton("Cluster")
        self.cluster_btn.setEnabled(False)
        self.cluster_btn.clicked.connect(self.on_cluster)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._on_refresh_view)
        actions_row.addStretch(1)
        actions_row.addWidget(refresh_btn)
        actions_row.addWidget(self.cluster_btn)
        left_box.addLayout(actions_row)

        # Right: clustered.csv preview table
        right_box = QVBoxLayout()
        right_label = QLabel("clustered.csv preview")
        right_label.setStyleSheet("font-weight: 600;")
        self.table = QTableWidget()
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.setColumnCount(0)
        self.table.setRowCount(0)
        right_box.addWidget(right_label)
        right_box.addWidget(self.table, 1)

        outer.addLayout(left_box, 0)
        outer.addLayout(right_box, 1)

        # Populate initial list if workspace is set
        self.refresh_state_list()

    def _on_refresh_view(self) -> None:
        self.refresh_state_list()
        self.clear_table()

    def refresh_state_list(self) -> None:
        if not hasattr(self, "state_list"):
            return
        self.state_list.clear()
        if not self.workspace or not self.workspace.exists():
            return
        # List subdirectories at workspace root as potential state folders
        try:
            for p in sorted([d for d in self.workspace.iterdir() if d.is_dir()]):
                # Skip hidden folders like .cache
                if p.name.startswith("."):
                    continue
                self.state_list.addItem(p.name)
        except Exception as e:
            self.log_append(f"Failed to list states in {self.workspace}: {e}")

    def on_state_selected(self, state_code: str) -> None:
        # Enable cluster when a state is selected
        if hasattr(self, "cluster_btn"):
            self.cluster_btn.setEnabled(bool(state_code))
        # Try to load clustered.csv if present; otherwise clear table
        if not self.workspace or not state_code:
            self.clear_table()
            return
        csv_path = self.workspace / state_code / "clustered.csv"
        if csv_path.exists():
            self._load_table_from_csv(csv_path)
        else:
            self.clear_table()

    def clear_table(self) -> None:
        if hasattr(self, "table"):
            self.table.clear()
            self.table.setColumnCount(0)
            self.table.setRowCount(0)

    def _load_table_from_csv(self, csv_path: Path) -> None:
        # Lightweight CSV preview without pandas to avoid duplication
        try:
            with csv_path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows: List[List[str]] = [row for row in reader]
        except Exception as e:
            self.log_append(f"Failed reading {csv_path}: {e}")
            return
        if not rows:
            self.clear_table()
            return
        headers = rows[0]
        data = rows[1:]
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setRowCount(min(len(data), 1000))  # cap preview rows
        self.table.setHorizontalHeaderLabels(headers)
        for r, row in enumerate(data[:1000]):
            for c, val in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(val))
