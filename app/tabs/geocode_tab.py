from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QMetaObject, QObject, QSettings, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QTextCursor
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
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

from app.geocoding import GeocodingCache, GeocodingStrategy


class ClearCacheConfirmationDialog(QDialog):
    """
    Custom confirmation dialog for clearing the entire cache.
    Requires user to type "YES" to enable the confirmation button.
    """

    def __init__(self, cache_stats: Dict[str, int], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clear Entire Cache - Confirmation Required")
        self.setModal(True)
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Warning banner
        warning_banner = QLabel("⚠️  WARNING: DESTRUCTIVE ACTION  ⚠️")
        warning_banner.setStyleSheet(
            """
            QLabel {
                background-color: #ff6b6b;
                color: white;
                font-weight: bold;
                font-size: 14px;
                padding: 10px;
                border-radius: 5px;
            }
        """
        )
        warning_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(warning_banner)

        # Warning message
        warning_text = QLabel(
            "You are about to delete the ENTIRE geocoding cache.\n\n"
            "This action will:\n"
            "• Delete ALL cached geocoding results for ALL states\n"
            "• Require re-geocoding ALL addresses on the next run\n"
            "• Cannot be undone\n\n"
            "Consider using the context menu to clear specific states or sites instead."
        )
        warning_text.setWordWrap(True)
        warning_text.setStyleSheet("font-size: 12px; padding: 10px;")
        layout.addWidget(warning_text)

        # Cache statistics
        stats_label = QLabel(
            f"<b>Cache Statistics:</b><br>"
            f"Total entries: {cache_stats.get('total', 0)}<br>"
            f"Successful: {cache_stats.get('successful', 0)}<br>"
            f"Failed: {cache_stats.get('failed', 0)}"
        )
        stats_label.setStyleSheet("padding: 10px; background-color: #f0f0f0; border-radius: 5px;")
        layout.addWidget(stats_label)

        # Confirmation instruction
        instruction = QLabel('<b>To confirm, type "YES" (without quotes) in the box below:</b>')
        instruction.setWordWrap(True)
        layout.addWidget(instruction)

        # Text input for confirmation
        self.confirmation_input = QLineEdit()
        self.confirmation_input.setPlaceholderText("Type YES here to confirm")
        self.confirmation_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.confirmation_input)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)

        self.confirm_btn = QPushButton("Clear Entire Cache")
        self.confirm_btn.setEnabled(False)  # Disabled until "YES" is typed
        self.confirm_btn.setStyleSheet(
            """
            QPushButton:enabled {
                background-color: #d32f2f;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """
        )
        self.confirm_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.confirm_btn)

        layout.addLayout(button_layout)

    def _on_text_changed(self, text: str):
        """Enable confirm button only when 'YES' is typed."""
        self.confirm_btn.setEnabled(text == "YES")


class GeocodeWorker(QObject):
    # Signals
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # processed, total
    state_done = pyqtSignal(str, int)  # state, rows_written
    finished = pyqtSignal(
        int, int, int, int
    )  # total_lookups, cache_hits, new_geocoded, total_errors

    def __init__(self, workspace: Path, states: List[str], strategy: GeocodingStrategy) -> None:
        super().__init__()
        self.workspace = workspace
        self.states = states
        self.strategy = strategy
        self._cancel = False
        self.cache = GeocodingCache()

    @pyqtSlot()
    def request_cancel(self) -> None:
        # Called via queued connection from UI thread
        self.log.emit("request_cancel method called; setting self._cancel flag to True")
        self._cancel = True

    # --- Worker-local helpers (no UI calls) ---
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

    def _geocode(self, query: str) -> Optional[Dict[str, Any]]:
        """Geocode a query using the configured strategy.

        Args:
            query: Address string to geocode

        Returns:
            Dictionary with 'lat', 'lon', 'display_name' if successful, None otherwise
        """
        return self.strategy.geocode(query)

    def run(self) -> None:
        # Geocode states; emit signals instead of touching UI
        if not self.workspace:
            self.log.emit("No workspace selected.")
            self.finished.emit(0, 0, 0, 0)
            return

        # Set up strategy logger to emit diagnostic messages
        # Check if strategy has a logger attribute (NominatimStrategy does)
        if hasattr(self.strategy, "logger"):
            self.strategy.logger = lambda msg: self.log.emit(f"[Strategy] {msg}")

        self.log.emit(f"Using cache: {self.cache.get_cache_path()}")
        total_lookups = 0
        total_cache_hits = 0
        total_geocoded = 0
        total_errors = 0

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
            except Exception as e:
                self.log.emit(f"Failed to read {addr_csv}: {e}")
                continue

        grand_total = sum(len(v) for v in state_rows.values())
        processed = 0
        self.progress.emit(processed, grand_total)
        cancelled = False
        for state in self.states:
            if self._cancel:
                self.log.emit("Cancellation requested; stopping before next state…")
                cancelled = True
                break
            rows = state_rows.get(state, [])
            if not rows:
                continue
            self.log.emit(f"State {state}: reading {self.workspace / state / 'addresses.csv'}")
            out_rows: List[Dict[str, Any]] = []
            error_rows: List[Dict[str, Any]] = []
            for i, r in enumerate(rows, start=1):
                if self._cancel:
                    self.log.emit("Cancellation requested; finishing current row and stopping…")
                    cancelled = True
                    break
                site_id = str(r.get("id", "")).strip()
                address = str(r.get("address", "")).strip()
                city = str(r.get("city", "")).strip()
                st = str(r.get("state", "")).strip()
                zip5 = str(r.get("zip", "")).strip()
                if not (address and city and st and zip5):
                    # Track addresses with missing required fields
                    error_rows.append(
                        {
                            "id": site_id,
                            "address": address,
                            "city": city,
                            "state": st,
                            "zip": zip5,
                            "normalized_address": "",
                            "strategy": self.strategy.get_source_name(),
                            "reason": "missing_fields",
                            "attempted_queries": 0,
                        }
                    )
                    total_errors += 1
                    processed += 1
                    self.progress.emit(processed, grand_total)
                    continue
                norm = GeocodingCache.normalize_address(address, city, st, zip5)
                total_lookups += 1
                cached = self.cache.get(norm)
                if cached:
                    total_cache_hits += 1
                    lat = cached["lat"]
                    lon = cached["lon"]
                    disp = cached["display_name"]
                    if lat is not None and lon is not None:
                        # Successful cached result - add to output
                        source = "cache"
                        out_rows.append(
                            {
                                "id": site_id,
                                "address": norm,
                                "lat": lat,
                                "lon": lon,
                                "display_name": disp,
                            }
                        )
                        self.log.emit(
                            f"State {state}: [{i}/{len(rows)}] {site_id} -> {lat:.6f},{lon:.6f} (cache)"
                        )
                    else:
                        # Cached failure - add to errors
                        error_rows.append(
                            {
                                "id": site_id,
                                "address": address,
                                "city": city,
                                "state": st,
                                "zip": zip5,
                                "normalized_address": norm,
                                "strategy": self.strategy.get_source_name(),
                                "reason": "cached_failure",
                                "attempted_queries": 0,  # Already attempted previously
                            }
                        )
                        total_errors += 1
                        self.log.emit(
                            f"State {state}: [{i}/{len(rows)}] {site_id} -> cached failure (previously failed)"
                        )
                    processed += 1
                    self.progress.emit(processed, grand_total)
                    continue
                else:
                    rate_delay = self.strategy.get_rate_limit_delay()
                    time.sleep(rate_delay)  # rate limit
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
                        if self._cancel:
                            self.log.emit("Cancellation requested; breaking before geocode loop…")
                            cancelled = True
                            break
                        res = self._geocode(q)
                        if res:
                            got = res
                            which = label
                            break
                        # Check cancel again before sleeping to avoid delay
                        if self._cancel:
                            self.log.emit(
                                "Cancellation requested; breaking before sleep to avoid delay…"
                            )
                            cancelled = True
                            break
                        time.sleep(rate_delay)
                    if not got:
                        # No geocoding result found - add to errors
                        error_rows.append(
                            {
                                "id": site_id,
                                "address": address,
                                "city": city,
                                "state": st,
                                "zip": zip5,
                                "normalized_address": norm,
                                "strategy": self.strategy.get_source_name(),
                                "reason": "no_result",
                                "attempted_queries": len(strategies),
                            }
                        )
                        total_errors += 1
                        self.cache.put(norm, None, None, "", source="none")
                        self.log.emit(
                            f"State {state}: [{i}/{len(rows)}] {site_id} -> no result (tried {len(strategies)} queries)"
                        )
                    else:
                        # If match is coarse city/state centroid, do not cache/store lat/lon
                        if which == "city-state":
                            # Coarse match - add to errors
                            error_rows.append(
                                {
                                    "id": site_id,
                                    "address": address,
                                    "city": city,
                                    "state": st,
                                    "zip": zip5,
                                    "normalized_address": norm,
                                    "strategy": self.strategy.get_source_name(),
                                    "reason": "coarse_skip",
                                    "attempted_queries": len(strategies),
                                }
                            )
                            total_errors += 1
                            self.log.emit(
                                f"State {state}: [{i}/{len(rows)}] {site_id} -> coarse match skipped (city/state only)"
                            )
                        else:
                            # Success - add to output
                            lat = got["lat"]
                            lon = got["lon"]
                            disp = got["display_name"]
                            provider_name = self.strategy.get_source_name()
                            self.cache.put(norm, lat, lon, disp, source=provider_name)
                            total_geocoded += 1
                            source = f"{provider_name}:{which}"
                            out_rows.append(
                                {
                                    "id": site_id,
                                    "address": norm,
                                    "lat": lat,
                                    "lon": lon,
                                    "display_name": disp,
                                }
                            )
                            self.log.emit(
                                f"State {state}: [{i}/{len(rows)}] {site_id} -> {lat:.6f},{lon:.6f} ({source})"
                            )
                processed += 1
                self.progress.emit(processed, grand_total)

            # write outputs for this state
            try:
                out_dir = self.workspace / state
                out_dir.mkdir(parents=True, exist_ok=True)

                # Write successful geocodes
                out_csv = out_dir / "geocoded.csv"
                with out_csv.open("w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(
                        f, fieldnames=["id", "address", "lat", "lon", "display_name"]
                    )
                    writer.writeheader()
                    writer.writerows(out_rows)
                self.log.emit(
                    f"State {state}: wrote {len(out_rows)} successful geocodes to {out_csv}"
                )

                # Write geocoding errors if any
                if error_rows:
                    error_csv = out_dir / "geocode-errors.csv"
                    with error_csv.open("w", encoding="utf-8", newline="") as f:
                        writer = csv.DictWriter(
                            f,
                            fieldnames=[
                                "id",
                                "address",
                                "city",
                                "state",
                                "zip",
                                "normalized_address",
                                "strategy",
                                "reason",
                                "attempted_queries",
                            ],
                        )
                        writer.writeheader()
                        writer.writerows(error_rows)
                    self.log.emit(
                        f"State {state}: wrote {len(error_rows)} failed geocodes to {error_csv}"
                    )

                self.state_done.emit(state, len(out_rows))
            except Exception as e:
                self.log.emit(f"State {state}: failed writing output files: {e}")

            # If cancellation requested, stop after finishing current state write
            if cancelled:
                self.log.emit("Cancellation requested; breaking out of state loop…")
                break

        self.finished.emit(total_lookups, total_cache_hits, total_geocoded, total_errors)


class GeocodeTab(QWidget):
    # Signal to request cancellation on the worker via queued connection
    cancel_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("GeocodeTab")
        self.workspace: Optional[Path] = None
        self.settings = QSettings("VRPTW", "Workflow")
        self.strategy: Optional[GeocodingStrategy] = None
        self.cache = GeocodingCache()

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
        # If a worker is running, request cancel before switching context
        try:
            if hasattr(self, "worker") and self.worker is not None:
                QMetaObject.invokeMethod(
                    self.worker, "request_cancel", Qt.ConnectionType.QueuedConnection
                )
                self.log_append("Workspace changed: canceling active geocoding run…")
        except Exception:
            pass
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
        # Enable Geocode All whenever a workspace is selected (tabs are reset on context change)
        if hasattr(self, "geocode_all_btn"):
            try:
                self.geocode_all_btn.setEnabled(bool(self.workspace))
            except Exception:
                pass
        # Disable cancel until a new run starts
        if hasattr(self, "cancel_btn"):
            try:
                self.cancel_btn.setEnabled(False)
            except Exception:
                pass
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
        self.state_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.state_list.customContextMenuRequested.connect(self._show_state_context_menu)
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
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
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
        # Create strategy instance (will be configurable in the future)
        # Logger will be set up by the worker thread
        from app.geocoding import NominatimStrategy

        strategy = NominatimStrategy(email=email)

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
        self.worker = GeocodeWorker(self.workspace, states, strategy)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        # Connect signals
        self.worker.log.connect(self._on_worker_log)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.state_done.connect(self._on_worker_state_done)
        self.worker.finished.connect(self._on_worker_finished)
        # Route cancel signal to worker using a queued connection (more reliable than invokeMethod)
        try:
            self.cancel_requested.connect(
                self.worker.request_cancel, Qt.ConnectionType.QueuedConnection
            )
        except Exception:
            pass
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

    def _on_worker_finished(
        self, total_lookups: int, cache_hits: int, new_geocoded: int, total_errors: int
    ) -> None:
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
            f"Geocoding complete. Lookups: {total_lookups}, cache hits: {cache_hits}, "
            f"successful: {new_geocoded}, failed: {total_errors}"
        )

    def _on_cancel_clicked(self) -> None:
        # Request cancel on the worker (queued to worker thread)
        try:
            if hasattr(self, "worker") and self.worker is not None:
                # Emit signal wired as queued connection to the worker slot
                self.cancel_requested.emit()
                # Nudge the thread to stop ASAP as a backup
                if hasattr(self, "worker_thread") and self.worker_thread is not None:
                    try:
                        self.worker_thread.requestInterruption()
                    except Exception:
                        pass
                # Fallback: also invoke the slot by name to cover any signal wiring issues
                try:
                    QMetaObject.invokeMethod(
                        self.worker, "request_cancel", Qt.ConnectionType.QueuedConnection
                    )
                except Exception:
                    self.log_append("Failed to emit cancel signal to worker")
                # Last-resort: call directly (thread-safe here since we only set a boolean flag)
                try:
                    self.worker.request_cancel()
                except Exception:
                    self.log_append("Failed to call request_cancel directly on worker")
                # Ask the thread to quit its event loop when run() returns
                try:
                    if hasattr(self, "worker_thread") and self.worker_thread is not None:
                        self.worker_thread.quit()
                except Exception:
                    self.log_append("Failed to quit worker thread")
                self.log_append("Cancel requested…")
                if hasattr(self, "cancel_btn"):
                    self.cancel_btn.setEnabled(False)
        except Exception:
            self.log_append("Failed to request cancel")

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
            self.log_append("Failed to refresh state list")
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

        # Set fixed widths for narrow columns that shouldn't grow
        # Use Fixed resize mode to prevent these columns from stretching
        if "id" in name_to_index:
            idx = name_to_index["id"]
            try:
                header_view.setSectionResizeMode(idx, QHeaderView.ResizeMode.Fixed)
            except Exception:
                pass
            self.table.setColumnWidth(idx, 80)

        if "lat" in name_to_index:
            idx = name_to_index["lat"]
            try:
                header_view.setSectionResizeMode(idx, QHeaderView.ResizeMode.Fixed)
            except Exception:
                pass
            self.table.setColumnWidth(idx, 100)
            # Latitude values are typically 7-10 characters (e.g., "-123.456789")

        if "lon" in name_to_index:
            idx = name_to_index["lon"]
            try:
                header_view.setSectionResizeMode(idx, QHeaderView.ResizeMode.Fixed)
            except Exception:
                pass
            self.table.setColumnWidth(idx, 100)
            # Longitude values are typically 7-10 characters (e.g., "-123.456789")

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
        # Get cache statistics for the confirmation dialog
        try:
            cache_stats = self.cache.get_cache_stats()
        except Exception:
            cache_stats = {"total": 0, "successful": 0, "failed": 0}

        # Show custom confirmation dialog that requires typing "YES"
        dialog = ClearCacheConfirmationDialog(cache_stats, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            cache_path = self.cache.get_cache_path()
            if self.cache.clear():
                # Focus log tab and report
                if hasattr(self, "subtabs"):
                    self.subtabs.setCurrentIndex(0)
                self.log_append(f"Cache cleared: {cache_path}")
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

    def _show_state_context_menu(self, position) -> None:
        """Show context menu for state list."""
        item = self.state_list.itemAt(position)
        if not item:
            return

        state_code = item.text()

        # Get cache stats for this state
        try:
            stats = self.cache.get_cache_stats(state_code=state_code)
            total = stats["total"]
        except Exception:
            total = 0

        menu = QMenu(self)

        # Clear cache for this state
        clear_action = QAction(f"Clear Cache for {state_code} ({total} entries)", self)
        clear_action.triggered.connect(lambda: self._clear_cache_for_state(state_code))
        menu.addAction(clear_action)

        # Show cache statistics
        menu.addSeparator()
        stats_action = QAction(
            f"Cache Stats: {stats.get('successful', 0)} successful, {stats.get('failed', 0)} failed",
            self,
        )
        stats_action.setEnabled(False)  # Just informational
        menu.addAction(stats_action)

        menu.exec(self.state_list.mapToGlobal(position))

    def _show_table_context_menu(self, position) -> None:
        """Show context menu for geocoded table."""
        row = self.table.rowAt(position.y())
        if row < 0:
            return

        # Get the address from the table (column 1 is "address")
        address_item = self.table.item(row, 1)
        if not address_item:
            return

        normalized_address = address_item.text()

        # Get site ID for display (column 0)
        id_item = self.table.item(row, 0)
        site_id = id_item.text() if id_item else "Unknown"

        menu = QMenu(self)

        # Clear cache for this specific site
        clear_action = QAction(f"Clear Cache for Site {site_id}", self)
        clear_action.triggered.connect(
            lambda: self._clear_cache_for_site(normalized_address, site_id)
        )
        menu.addAction(clear_action)

        menu.exec(self.table.mapToGlobal(position))

    def _clear_cache_for_state(self, state_code: str) -> None:
        """Clear cache entries for a specific state."""
        # Confirm
        stats = self.cache.get_cache_stats(state_code=state_code)
        total = stats["total"]

        if total == 0:
            QMessageBox.information(
                self,
                "No Cache Entries",
                f"No cache entries found for state {state_code}.",
            )
            return

        confirm = QMessageBox.question(
            self,
            "Clear State Cache?",
            f"Clear {total} cache entries for state {state_code}?\n\n"
            f"({stats['successful']} successful, {stats['failed']} failed)\n\n"
            f"These addresses will be re-geocoded on the next run.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            deleted = self.cache.clear_by_state(state_code)
            # Focus log tab and report
            if hasattr(self, "subtabs"):
                self.subtabs.setCurrentIndex(0)
            self.log_append(f"Cleared {deleted} cache entries for state {state_code}")

            # Refresh UI
            self._update_state_geocode_status(state_code)
        except Exception as e:
            if hasattr(self, "subtabs"):
                self.subtabs.setCurrentIndex(0)
            self.log_append(f"Failed to clear cache for state {state_code}: {e}")

    def _clear_cache_for_site(self, normalized_address: str, site_id: str) -> None:
        """Clear cache entry for a specific site."""
        confirm = QMessageBox.question(
            self,
            "Clear Site Cache?",
            f"Clear cache for site {site_id}?\n\n"
            f"Address: {normalized_address}\n\n"
            f"This address will be re-geocoded on the next run.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            deleted = self.cache.clear_by_address(normalized_address)
            # Focus log tab and report
            if hasattr(self, "subtabs"):
                self.subtabs.setCurrentIndex(0)
            if deleted:
                self.log_append(f"Cleared cache for site {site_id}")
            else:
                self.log_append(f"No cache entry found for site {site_id}")

            # Refresh current state view
            current = self.state_list.currentItem().text() if self.state_list.currentItem() else ""
            if current:
                self._update_state_geocode_status(current)
        except Exception as e:
            if hasattr(self, "subtabs"):
                self.subtabs.setCurrentIndex(0)
            self.log_append(f"Failed to clear cache for site {site_id}: {e}")
