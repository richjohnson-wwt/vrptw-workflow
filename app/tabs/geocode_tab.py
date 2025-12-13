from __future__ import annotations

import csv
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from PyQt6.QtCore import QCoreApplication, QMetaObject, QObject, QSettings, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class GeocodeWorker(QObject):
    # Signals
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # processed, total
    state_done = pyqtSignal(str, int)  # state, rows_written
    finished = pyqtSignal(int, int, int)  # total_lookups, cache_hits, new_geocoded

    def __init__(self, workspace: Path, states: List[str], email: str) -> None:
        super().__init__()
        self.workspace = workspace
        self.states = states
        self.email = email
        self._cancel = False

    def request_cancel(self) -> None:
        # Called via queued connection from UI thread
        self._cancel = True

    # --- Worker-local helpers (no UI calls) ---
    def _cache_path(self) -> Path:
        base = Path.home() / "Documents" / "VRPTW" / ".cache"
        base.mkdir(parents=True, exist_ok=True)
        return base / "nominatim.sqlite"

    def _ensure_cache(self) -> sqlite3.Connection:
        db_path = self._cache_path()
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS addresses (
              id INTEGER PRIMARY KEY,
              normalized_address TEXT UNIQUE,
              latitude REAL,
              longitude REAL,
              display_name TEXT,
              source TEXT,
              updated_at TEXT
            )
            """
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_addresses_norm ON addresses(normalized_address)"
        )
        conn.commit()
        return conn

    @staticmethod
    def _normalize_address(address: str, city: str, state: str, zip5: str) -> str:
        parts = [address.strip(), city.strip(), f"{state.strip()} {zip5.strip()}", "USA"]
        return ", ".join([p for p in parts if p])

    @staticmethod
    def _territory_full_name(code: str) -> Optional[str]:
        mapping = {
            "PR": "Puerto Rico",
            "GU": "Guam",
            "VI": "U.S. Virgin Islands",
            "MP": "Northern Mariana Islands",
            "AS": "American Samoa",
            "DC": "District of Columbia",
        }
        return mapping.get(code.upper())

    @staticmethod
    def _cache_get(conn: sqlite3.Connection, norm: str) -> Optional[Dict[str, Any]]:
        cur = conn.cursor()
        cur.execute(
            "SELECT latitude, longitude, display_name, source, updated_at FROM addresses WHERE normalized_address = ?",
            (norm,),
        )
        row = cur.fetchone()
        if row:
            return {
                "lat": row[0],
                "lon": row[1],
                "display_name": row[2],
                "source": row[3],
                "updated_at": row[4],
            }
        return None

    @staticmethod
    def _cache_put(
        conn: sqlite3.Connection,
        norm: str,
        lat: Optional[float],
        lon: Optional[float],
        display_name: str,
        source: str = "nominatim",
    ) -> None:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO addresses (normalized_address, latitude, longitude, display_name, source, updated_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (norm, lat, lon, display_name, source),
        )
        conn.commit()

    def _nominatim_geocode(self, query: str) -> Optional[Dict[str, Any]]:
        url = "https://nominatim.openstreetmap.org/search"
        headers = {
            "User-Agent": f"VRPTW-Workflow/0.1 (contact: {self.email})",
            "Accept-Language": "en",
        }
        params = {
            "q": query,
            "format": "jsonv2",
            "limit": 5,
            "addressdetails": 1,
            "countrycodes": "us,pr,gu,vi,mp,as",
        }

        resp = requests.get(url, headers=headers, params=params, timeout=15)

        if resp.status_code != 200:
            # log resp.status_code + resp.text[:200]
            return None

        try:
            data = resp.json()
        except ValueError:
            # log resp.text[:200]
            return None

        if not data:
            return None

        # Pick the best street-level match
        for item in data:
            if item.get("lat") and item.get("lon"):
                if item.get("type") in ("house", "building", "residential", "yes"):
                    return {
                        "lat": float(item["lat"]),
                        "lon": float(item["lon"]),
                        "display_name": item.get("display_name", ""),
                    }

        # fallback: first valid lat/lon
        top = data[0]
        return {
            "lat": float(top["lat"]),
            "lon": float(top["lon"]),
            "display_name": top.get("display_name", ""),
        }


    def run(self) -> None:
        # Geocode states; emit signals instead of touching UI
        if not self.workspace:
            self.log.emit("No workspace selected.")
            self.finished.emit(0, 0, 0)
            return
        conn = self._ensure_cache()
        self.log.emit(f"Using cache: {self._cache_path()}")
        total_lookups = 0
        total_cache_hits = 0
        total_geocoded = 0

        # Pre-read rows to know grand total
        state_rows: Dict[str, List[Dict[str, str]]] = {}
        for state in self.states:
            addr_csv = self.workspace / state / "addresses.csv"
            if not addr_csv.exists():
                continue
            try:
                rows: List[Dict[str, str]] = []
                with addr_csv.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        rows.append(r)
                state_rows[state] = rows
            except Exception:
                self.log.emit(f"Failed to read {addr_csv}: {e}")
                continue

        grand_total = sum(len(v) for v in state_rows.values())
        processed = 0
        self.progress.emit(processed, grand_total)

        for state in self.states:
            if self._cancel:
                self.log.emit("Cancellation requested; stopping before next state…")
                break
            rows = state_rows.get(state, [])
            if not rows:
                continue
            self.log.emit(f"State {state}: reading {self.workspace / state / 'addresses.csv'}")
            out_rows: List[Dict[str, Any]] = []
            for i, r in enumerate(rows, start=1):
                if self._cancel:
                    self.log.emit("Cancellation requested; finishing current row and stopping…")
                    break
                site_id = str(r.get("id", "")).strip()
                address = str(r.get("address", "")).strip()
                city = str(r.get("city", "")).strip()
                st = str(r.get("state", "")).strip()
                zip5 = str(r.get("zip", "")).strip()
                if not (address and city and st and zip5):
                    processed += 1
                    self.progress.emit(processed, grand_total)
                    continue
                norm = self._normalize_address(address, city, st, zip5)
                total_lookups += 1
                cached = self._cache_get(conn, norm)
                if cached:
                    total_cache_hits += 1
                    lat = cached["lat"]
                    lon = cached["lon"]
                    disp = cached["display_name"]
                    source = "cache" if (lat is not None and lon is not None) else "cache-none"
                else:
                    time.sleep(1.05)  # rate limit
                    # multi-strategy
                    strategies = [(norm, "full")]
                    no_zip = ", ".join([address, city, st, "USA"])
                    if zip5:
                        strategies.append((no_zip, "no-zip"))
                    terr = self._territory_full_name(st)
                    if terr:
                        strategies.append((", ".join([address, city, terr]), "territory"))
                    strategies.append((f"{city}, {st}", "city-state"))
                    got = None
                    which = ""
                    for q, label in strategies:
                        res = self._nominatim_geocode(q)
                        if res:
                            got = res
                            which = label
                            break
                        time.sleep(1.05)
                    if not got:
                        lat = None
                        lon = None
                        disp = ""
                        source = "miss"
                        self._cache_put(conn, norm, lat, lon, disp, source="none")
                    else:
                        lat = got["lat"]
                        lon = got["lon"]
                        disp = got["display_name"]
                        self._cache_put(conn, norm, lat, lon, disp, source="nominatim")
                        total_geocoded += 1
                        source = f"nominatim:{which}"
                out_rows.append(
                    {
                        "id": site_id,
                        "address": norm,
                        "lat": lat if lat is not None else "",
                        "lon": lon if lon is not None else "",
                        "display_name": disp,
                    }
                )
                # per-row log & progress
                if lat is not None and lon is not None:
                    self.log.emit(
                        f"State {state}: [{i}/{len(rows)}] {site_id} -> {lat:.6f},{lon:.6f} ({source})"
                    )
                else:
                    self.log.emit(
                        f"State {state}: [{i}/{len(rows)}] {site_id} -> no result ({source})"
                    )
                processed += 1
                self.progress.emit(processed, grand_total)

            # write outputs for this state
            try:
                out_dir = self.workspace / state
                out_dir.mkdir(parents=True, exist_ok=True)
                out_csv = out_dir / "geocoded.csv"
                with out_csv.open("w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(
                        f, fieldnames=["id", "address", "lat", "lon", "display_name"]
                    )
                    writer.writeheader()
                    writer.writerows(out_rows)
                self.log.emit(f"State {state}: wrote {len(out_rows)} rows to {out_csv}")
                self.state_done.emit(state, len(out_rows))
            except Exception as e:
                self.log.emit(f"State {state}: failed writing geocoded.csv: {e}")

        self.finished.emit(total_lookups, total_cache_hits, total_geocoded)


class GeocodeTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("GeocodeTab")
        self.workspace: Optional[Path] = None
        self.settings = QSettings("VRPTW", "Workflow")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("Geocode addresses to coordinates (Nominatim)")
        header.setWordWrap(True)
        header.setStyleSheet("font-weight: 600;")
        layout.addWidget(header)

        # Workspace banner
        self.banner = QLabel("Workspace: (none)")
        self.banner.setStyleSheet("color: #555; font-style: italic;")
        self.banner.setWordWrap(True)
        layout.addWidget(self.banner)

        form = QFormLayout()
        self.email_input = QLineEdit()
        # Make email input wider and allow horizontal expansion
        try:
            self.email_input.setMinimumWidth(360)
            self.email_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        except Exception:
            pass
        self.email_input.setPlaceholderText("Your email (required by Nominatim)")
        form.addRow("Email:", self.email_input)
        # Load persisted email
        self._load_email()
        # Save when editing finishes
        self.email_input.editingFinished.connect(
            lambda: self._save_email(self.email_input.text().strip())
        )

        layout.addLayout(form)

        actions_row = QHBoxLayout()
        self.geocode_btn = QPushButton("Geocode")
        self.geocode_btn.setEnabled(False)  # enabled when a state is selected
        self.geocode_btn.clicked.connect(self.on_geocode)
        self.geocode_all_btn = QPushButton("Geocode All")
        self.geocode_all_btn.setEnabled(True)
        self.geocode_all_btn.clicked.connect(self.on_geocode_all)
        self.clear_cache_btn = QPushButton("Clear Cache")
        self.clear_cache_btn.setToolTip("Delete the shared Nominatim cache database")
        self.clear_cache_btn.clicked.connect(self.on_clear_cache)
        # Cancel button to stop background geocoding
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setToolTip("Cancel the current geocoding run")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        actions_row.addStretch(1)
        actions_row.addWidget(self.geocode_btn)
        actions_row.addWidget(self.geocode_all_btn)
        actions_row.addWidget(self.clear_cache_btn)
        actions_row.addWidget(self.cancel_btn)
        layout.addLayout(actions_row)

        # Simple progress indicator
        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # Sub-tabs: Geocode Log and Geocode View
        self.subtabs = QTabWidget()
        self.subtabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Log tab
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(200)
        self.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log.setPlaceholderText("Geocoding logs will appear here…")
        self.subtabs.addTab(self.log, "Geocode Log")

        # View tab
        self.view = QWidget()
        self._init_view_tab(self.view)
        self.subtabs.addTab(self.view, "Geocode View")

        layout.addWidget(self.subtabs, 1)

    # Workspace API for MainWindow
    def set_workspace(self, path_str: str) -> None:
        # Update workspace and clear UI to prevent accidental geocoding into the wrong workspace
        self.workspace = Path(path_str) if path_str else None
        # Clear logs when changing workspace (keep email persisted)
        if hasattr(self, "log"):
            self.log.clear()
        if hasattr(self, "banner"):
            self.banner.setText(f"Workspace: {path_str}" if path_str else "Workspace: (none)")
        # Refresh view
        self.refresh_state_list()
        self.clear_table()
        # Disable single-state geocode until a state is selected
        if hasattr(self, "geocode_btn"):
            self.geocode_btn.setEnabled(False)
        # reset progress
        if hasattr(self, "progress"):
            self.progress.setValue(0)

    def _wrap(self, inner_layout: QHBoxLayout) -> QWidget:
        w = QWidget()
        w.setLayout(inner_layout)
        return w

    # View helpers
    def _init_view_tab(self, container: QWidget) -> None:
        outer = QHBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # Left: State list
        left_box = QVBoxLayout()
        left_label = QLabel("States")
        left_label.setStyleSheet("font-weight: 600;")
        self.state_list = QListWidget()
        self.state_list.setMinimumWidth(140)
        self.state_list.currentTextChanged.connect(self.on_state_selected)
        left_box.addWidget(left_label)
        left_box.addWidget(self.state_list, 1)
        # Status row: site count, geocode status, refresh button
        status_row = QHBoxLayout()
        self.state_count = QLabel("0 sites")
        self.state_count.setStyleSheet("color: #555; font-style: italic;")
        self.geocode_status = QLabel("0 of 0 geocoded")
        self.geocode_status.setStyleSheet("color: #555; font-style: italic;")
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setFixedWidth(90)
        self.refresh_btn.clicked.connect(self._on_refresh_view)
        status_row.addWidget(self.state_count, 0)
        status_row.addSpacing(8)
        status_row.addWidget(self.geocode_status, 0)
        status_row.addStretch(1)
        status_row.addWidget(self.refresh_btn, 0)
        left_box.addLayout(status_row)

        # Right: geocoded.csv preview table
        right_box = QVBoxLayout()
        right_label = QLabel("geocoded.csv preview")
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

    def on_geocode(self) -> None:
        email = self.email_input.text().strip()
        if not email:
            self.log_append("Please enter your email (required by Nominatim usage policy).")
            QMessageBox.warning(
                self,
                "Email required",
                "Please enter your email (required by Nominatim usage policy).",
            )
            return
        if "@" not in email:
            self.log_append("The email entered doesn't look valid. Please provide a valid email.")
            QMessageBox.warning(
                self,
                "Invalid email",
                "The email entered doesn't look valid. Please provide a valid email.",
            )
            return
        self._save_email(email)
        # Determine selected state
        state = (
            self.state_list.currentItem().text()
            if hasattr(self, "state_list") and self.state_list.currentItem()
            else ""
        )
        if not state:
            self.log_append("Select a state to geocode or use 'Geocode All'.")
            return
        # Focus the Log subtab
        if hasattr(self, "subtabs"):
            self.subtabs.setCurrentIndex(0)
        self._start_geocoding([state], email)

    def on_geocode_all(self) -> None:
        email = self.email_input.text().strip()
        if not email:
            self.log_append("Please enter your email (required by Nominatim usage policy).")
            QMessageBox.warning(
                self,
                "Email required",
                "Please enter your email (required by Nominatim usage policy).",
            )
            return
        if "@" not in email:
            self.log_append("The email entered doesn't look valid. Please provide a valid email.")
            QMessageBox.warning(
                self,
                "Invalid email",
                "The email entered doesn't look valid. Please provide a valid email.",
            )
            return
        self._save_email(email)
        # Confirm running Geocode All
        confirm = QMessageBox.question(
            self,
            "Run Geocode All?",
            "This will geocode all states with addresses.csv at ~1 request/sec. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if not self.workspace:
            self.log_append("Please select a workspace first.")
            return
        # Focus the Log subtab
        if hasattr(self, "subtabs"):
            self.subtabs.setCurrentIndex(0)
        # Determine states ready to geocode (have addresses.csv)
        states: List[str] = []
        try:
            for p in sorted(self.workspace.iterdir()):
                if p.is_dir() and (p / "addresses.csv").exists():
                    states.append(p.name)
        except Exception:
            pass
        if not states:
            self.log_append("No states found with addresses.csv to geocode.")
            return
        self._start_geocoding(states, email)

    def log_append(self, msg: str) -> None:
        self.log.append(msg)
        self.log.moveCursor(QTextCursor.MoveOperation.End)
        self.log.ensureCursorVisible()

    # -----------------
    # Worker lifecycle
    # -----------------
    def _start_geocoding(self, states: List[str], email: str) -> None:
        if not self.workspace:
            return
        # Disable actions during run
        if hasattr(self, "geocode_btn"):
            self.geocode_btn.setEnabled(False)
        if hasattr(self, "geocode_all_btn"):
            self.geocode_all_btn.setEnabled(False)
        if hasattr(self, "clear_cache_btn"):
            self.clear_cache_btn.setEnabled(False)
        if hasattr(self, "cancel_btn"):
            self.cancel_btn.setEnabled(True)
        # Reset progress
        if hasattr(self, "progress"):
            self.progress.setMaximum(0)  # indeterminate until first progress arrives
            self.progress.setValue(0)
        # Start worker thread
        self.worker_thread = QThread(self)
        self.worker = GeocodeWorker(self.workspace, states, email)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        # Connect signals
        self.worker.log.connect(self._on_worker_log)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.state_done.connect(self._on_worker_state_done)
        self.worker.finished.connect(self._on_worker_finished)
        # Ensure cleanup
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.start()

    def _on_worker_log(self, msg: str) -> None:
        self.log_append(msg)

    def _on_worker_progress(self, processed: int, total: int) -> None:
        if not hasattr(self, "progress"):
            return
        if total > 0:
            if self.progress.maximum() != total:
                self.progress.setMaximum(total)
            self.progress.setValue(processed)
        else:
            self.progress.setMaximum(0)

    def _on_worker_state_done(self, state: str, rows_written: int) -> None:
        # Refresh list/status; keep current selection
        current = self.state_list.currentItem().text() if self.state_list.currentItem() else ""
        self.refresh_state_list()
        if current:
            items = self.state_list.findItems(current, Qt.MatchFlag.MatchExactly)
            if items:
                self.state_list.setCurrentItem(items[0])
                self._update_state_site_count(current)
                self._update_state_geocode_status(current)
            if current == state:
                # If the finished state is selected, reload table
                self.on_state_selected(state)

    def _on_worker_finished(self, total_lookups: int, cache_hits: int, new_geocoded: int) -> None:
        # Re-enable actions
        if hasattr(self, "geocode_btn"):
            self.geocode_btn.setEnabled(self.state_list.currentItem() is not None)
        if hasattr(self, "geocode_all_btn"):
            self.geocode_all_btn.setEnabled(True)
        if hasattr(self, "clear_cache_btn"):
            self.clear_cache_btn.setEnabled(True)
        if hasattr(self, "cancel_btn"):
            self.cancel_btn.setEnabled(False)
        # Final progress to full
        if hasattr(self, "progress") and self.progress.maximum() > 0:
            self.progress.setValue(self.progress.maximum())
        self.log_append(
            f"Geocoding complete. Lookups: {total_lookups}, cache hits: {cache_hits}, new: {new_geocoded}"
        )

    def _on_cancel_clicked(self) -> None:
        # Request cancel on the worker (queued to worker thread)
        try:
            if hasattr(self, "worker") and self.worker is not None:
                QMetaObject.invokeMethod(
                    self.worker, "request_cancel", Qt.ConnectionType.QueuedConnection
                )
                self.log_append("Cancel requested…")
                if hasattr(self, "cancel_btn"):
                    self.cancel_btn.setEnabled(False)
        except Exception:
            pass

    # ---------
    # View APIs
    # ---------
    def refresh_state_list(self) -> None:
        if not hasattr(self, "state_list"):
            return
        self.state_list.clear()
        if not self.workspace:
            return
        try:
            states = []
            for p in sorted(self.workspace.iterdir()):
                if p.is_dir():
                    # Include states that are ready to geocode (addresses.csv)
                    # as well as those already geocoded (geocoded.csv)
                    has_addresses = (p / "addresses.csv").exists()
                    has_geocoded = (p / "geocoded.csv").exists()
                    if has_addresses or has_geocoded:
                        states.append(p.name)
            for st in states:
                self.state_list.addItem(st)
        except Exception:
            pass
        # Update single-state geocode button enabled state
        self.geocode_btn.setEnabled(self.state_list.currentItem() is not None)
        # Reset counts
        if hasattr(self, "state_count"):
            self.state_count.setText("0 sites")
        if hasattr(self, "geocode_status"):
            self.geocode_status.setText("0 of 0 geocoded")

    def on_state_selected(self, state_code: str) -> None:
        if not self.workspace or not state_code:
            self.clear_table()
            self.geocode_btn.setEnabled(False)
            if hasattr(self, "state_count"):
                self.state_count.setText("0 sites")
            if hasattr(self, "geocode_status"):
                self.geocode_status.setText("0 of 0 geocoded")
            return
        # enable button when a state is selected
        self.geocode_btn.setEnabled(True)
        # Update site count for selected state
        self._update_state_site_count(state_code)
        # Update geocode status for selected state
        self._update_state_geocode_status(state_code)
        csv_path = self.workspace / state_code / "geocoded.csv"
        if not csv_path.exists():
            self.clear_table()
            return
        # Load CSV and populate table
        try:
            import pandas as pd  # type: ignore

            df = pd.read_csv(csv_path)
            self.populate_table_from_dataframe(df)
        except Exception:
            try:
                import csv

                with csv_path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.reader(f)
                    rows = list(reader)
                if not rows:
                    self.clear_table()
                    return
                headers = rows[0]
                data_rows = rows[1:]
                self.table.setColumnCount(len(headers))
                self.table.setHorizontalHeaderLabels(headers)
                self.table.setRowCount(len(data_rows))
                for r, row_vals in enumerate(data_rows):
                    for c, val in enumerate(row_vals):
                        self.table.setItem(r, c, QTableWidgetItem(str(val)))
                self._apply_table_column_sizing(headers)
            except Exception:
                self.clear_table()

    def populate_table_from_dataframe(self, df) -> None:  # type: ignore[no-untyped-def]
        headers = list(df.columns)
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels([str(h) for h in headers])
        self.table.setRowCount(len(df))
        for r, (_, row) in enumerate(df.iterrows()):
            for c, h in enumerate(headers):
                self.table.setItem(r, c, QTableWidgetItem(str(row[h])))
        self._apply_table_column_sizing([str(h) for h in headers])

    def clear_table(self) -> None:
        if hasattr(self, "table"):
            self.table.clear()
            self.table.setColumnCount(0)
            self.table.setRowCount(0)

    def _on_refresh_view(self) -> None:
        self.refresh_state_list()
        current = self.state_list.currentItem().text() if self.state_list.currentItem() else ""
        if current:
            self._update_state_site_count(current)
            self._update_state_geocode_status(current)

    def _update_state_site_count(self, state_code: str) -> None:
        try:
            if not self.workspace:
                self.state_count.setText("0 sites")
                return
            addr_csv = self.workspace / state_code / "addresses.csv"
            if not addr_csv.exists():
                self.state_count.setText("0 sites")
                return
            count = 0
            with addr_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                # skip header
                next(reader, None)
                for _ in reader:
                    count += 1
            self.state_count.setText(f"{count} site" + ("s" if count != 1 else ""))
        except Exception:
            self.state_count.setText("0 sites")

    def _update_state_geocode_status(self, state_code: str) -> None:
        try:
            if not self.workspace:
                self.geocode_status.setText("0 of 0 geocoded")
                return
            addr_csv = self.workspace / state_code / "addresses.csv"
            total = 0
            if addr_csv.exists():
                with addr_csv.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.reader(f)
                    next(reader, None)
                    for _ in reader:
                        total += 1
            done = 0
            geo_csv = self.workspace / state_code / "geocoded.csv"
            if geo_csv.exists():
                with geo_csv.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        lat = str(r.get("lat", "")).strip()
                        lon = str(r.get("lon", "")).strip()
                        if lat and lon:
                            done += 1
            self.geocode_status.setText(f"{done} of {total} geocoded")
        except Exception:
            self.geocode_status.setText("0 of 0 geocoded")

    def _apply_table_column_sizing(self, headers: list[str]) -> None:
        header_view = self.table.horizontalHeader()
        header_view.setStretchLastSection(True)
        try:
            header_view.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        except Exception:
            pass
        name_to_index = {str(h).strip().lower(): i for i, h in enumerate(headers)}
        if "state" in name_to_index:
            idx = name_to_index["state"]
            try:
                header_view.setSectionResizeMode(idx, QHeaderView.ResizeMode.Interactive)
            except Exception:
                pass
            self.table.setColumnWidth(idx, 50)
        if "zip" in name_to_index:
            idx = name_to_index["zip"]
            try:
                header_view.setSectionResizeMode(idx, QHeaderView.ResizeMode.Interactive)
            except Exception:
                pass
            self.table.setColumnWidth(idx, 70)

    # ---------------------
    # Geocoding core logic
    # ---------------------
    def _load_email(self) -> None:
        saved = self.settings.value("geocodeEmail", "", type=str) or ""
        if saved:
            self.email_input.setText(saved)

    def _save_email(self, email: str) -> None:
        if email and "@" in email:
            self.settings.setValue("geocodeEmail", email)
            try:
                self.settings.sync()
            except Exception:
                pass

    def _cache_path(self) -> Path:
        base = Path.home() / "Documents" / "VRPTW" / ".cache"
        base.mkdir(parents=True, exist_ok=True)
        return base / "nominatim.sqlite"

    def _ensure_cache(self) -> sqlite3.Connection:
        db_path = self._cache_path()
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS addresses (
              id INTEGER PRIMARY KEY,
              normalized_address TEXT UNIQUE,
              latitude REAL,
              longitude REAL,
              display_name TEXT,
              source TEXT,
              updated_at TEXT
            )
            """
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_addresses_norm ON addresses(normalized_address)"
        )
        conn.commit()
        return conn

    def _normalize_address(self, address: str, city: str, state: str, zip5: str) -> str:
        parts = [address.strip(), city.strip(), f"{state.strip()} {zip5.strip()}", "USA"]
        return ", ".join([p for p in parts if p])

    def _cache_get(self, conn: sqlite3.Connection, norm: str) -> Optional[Dict[str, Any]]:
        cur = conn.cursor()
        cur.execute(
            "SELECT latitude, longitude, display_name, source, updated_at FROM addresses WHERE normalized_address = ?",
            (norm,),
        )
        row = cur.fetchone()
        if row:
            return {
                "lat": row[0],
                "lon": row[1],
                "display_name": row[2],
                "source": row[3],
                "updated_at": row[4],
            }
        return None

    def _cache_put(
        self,
        conn: sqlite3.Connection,
        norm: str,
        lat: Optional[float],
        lon: Optional[float],
        display_name: str,
        source: str = "nominatim",
    ) -> None:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO addresses (normalized_address, latitude, longitude, display_name, source, updated_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (norm, lat, lon, display_name, source),
        )
        conn.commit()

    def _nominatim_geocode(self, query: str, email: str) -> Optional[Dict[str, Any]]:
        url = "https://nominatim.openstreetmap.org/search"
        headers = {
            "User-Agent": f"VRPTW-Workflow/0.1 (+{email})",
            "Accept-Language": "en",
        }
        params = {
            "q": query,
            "format": "json",
            "limit": 1,
            "addressdetails": 0,
            # Include US and territories commonly present in client data
            "countrycodes": "us,pr,gu,vi,mp,as",
            # Providing email helps contact policy
            "email": email,
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            if resp.status_code == 429:
                # Too many requests; caller should slow down
                self.log_append("Nominatim returned 429 Too Many Requests; backing off")
                return None
            if resp.status_code != 200:
                self.log_append(f"Nominatim HTTP {resp.status_code}: {resp.text[:120]}")
                return None
            data = resp.json()
            if not data:
                return None
            top = data[0]
            return {
                "lat": float(top.get("lat")),
                "lon": float(top.get("lon")),
                "display_name": str(top.get("display_name", "")),
            }
        except Exception:
            return None

    def _territory_full_name(self, code: str) -> Optional[str]:
        mapping = {
            "PR": "Puerto Rico",
            "GU": "Guam",
            "VI": "U.S. Virgin Islands",
            "MP": "Northern Mariana Islands",
            "AS": "American Samoa",
            "DC": "District of Columbia",
        }
        return mapping.get(code.upper())

    def on_clear_cache(self) -> None:
        # Clear the shared SQLite cache and refresh UI. Do not reference geocoding counters here.
        # Confirm cache clear
        confirm = QMessageBox.question(
            self,
            "Clear Geocode Cache?",
            "This deletes the shared geocode cache for all clients/workspaces. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            p = self._cache_path()
            if p.exists():
                p.unlink()
                # Focus log tab and report
                if hasattr(self, "subtabs"):
                    self.subtabs.setCurrentIndex(0)
                self.log_append(f"Cache cleared: {p}")
            else:
                if hasattr(self, "subtabs"):
                    self.subtabs.setCurrentIndex(0)
                self.log_append("Cache file not found; nothing to clear.")
        except Exception as e:
            if hasattr(self, "subtabs"):
                self.subtabs.setCurrentIndex(0)
            self.log_append(f"Failed to clear cache: {e}")
        # Refresh state list/status after cache changes
        self.refresh_state_list()
        current = self.state_list.currentItem().text() if self.state_list.currentItem() else ""
        if current:
            self._update_state_site_count(current)
            self._update_state_geocode_status(current)
        # Nothing else to do in cache clear
