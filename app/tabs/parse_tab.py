from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QComboBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ParseTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.setObjectName("ParseTab")
        self.workspace: Optional[Path] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Header
        header = QLabel("Parse input data (Excel .xlsx orders)")
        header.setWordWrap(True)
        header.setStyleSheet("font-weight: 600;")
        layout.addWidget(header)

        # Workspace banner
        self.banner = QLabel("Workspace: (none)")
        self.banner.setStyleSheet("color: #555; font-style: italic;")
        self.banner.setWordWrap(True)
        layout.addWidget(self.banner)

        # File picker row
        file_row = QHBoxLayout()
        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText("Select Excel .xlsx file…")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self.on_browse)
        file_row.addWidget(self.file_input)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)

        # Sheet selection row (populated after choosing a file)
        sheet_row = QHBoxLayout()
        sheet_label = QLabel("Sheet:")
        self.sheet_combo = QComboBox()
        self.sheet_combo.setEditable(False)
        self.sheet_combo.setEnabled(False)
        sheet_row.addWidget(sheet_label)
        sheet_row.addWidget(self.sheet_combo, 1)
        layout.addLayout(sheet_row)

        # Actions
        actions_row = QHBoxLayout()
        self.parse_btn = QPushButton("Parse")
        self.parse_btn.clicked.connect(self.on_parse)
        actions_row.addStretch(1)
        actions_row.addWidget(self.parse_btn)
        layout.addLayout(actions_row)

        # Sub-tabs: ParseLogTab and ParseViewTab
        self.subtabs = QTabWidget()
        self.subtabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Log tab
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(200)
        self.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log.setPlaceholderText("Logs will appear here…")
        self.subtabs.addTab(self.log, "Parse Log")

        # View tab
        self.parse_view = QWidget()
        self._init_parse_view(self.parse_view)
        self.subtabs.addTab(self.parse_view, "Parse View")

        layout.addWidget(self.subtabs, 1)

        # Remove trailing stretch so the sub-tabs can occupy available space

    def on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Excel .xlsx file",
            str(Path.home()),
            "Excel Files (*.xlsx);;All Files (*)",
        )
        if path:
            self.file_input.setText(path)
            # Populate available sheets and default to the first
            self._populate_sheet_list(path)

    def _populate_sheet_list(self, path: str) -> None:
        try:
            import pandas as pd  # type: ignore

            xls = pd.ExcelFile(path, engine="openpyxl")
            sheets = xls.sheet_names
        except Exception as e:
            # Disable and clear on error
            if hasattr(self, "sheet_combo"):
                self.sheet_combo.clear()
                self.sheet_combo.setEnabled(False)
            self.log_append(f"Failed to list sheets: {e}")
            return
        # Populate combo
        self.sheet_combo.clear()
        for name in sheets:
            self.sheet_combo.addItem(str(name))
        self.sheet_combo.setEnabled(bool(sheets))
        if sheets:
            self.sheet_combo.setCurrentIndex(0)

    def on_parse(self) -> None:
        path = self.file_input.text().strip()
        if not path:
            self.log_append("Please select an input file before parsing.")
            return
        if not self.workspace:
            self.log_append("Please select a workspace on the Workspace tab first.")
            return
        self.log_append(f"Parsing started for: {path}")
        # Attempt to import pandas with openpyxl engine for .xlsx
        try:
            import pandas as pd  # type: ignore
        except Exception as e:  # pragma: no cover
            self.log_append("pandas is required. Please run: uv add pandas openpyxl")
            self.log_append(f"Import error: {e}")
            return

        try:
            # Use selected sheet if available; otherwise default to first sheet (index 0)
            if hasattr(self, "sheet_combo") and self.sheet_combo.isEnabled() and self.sheet_combo.count() > 0:
                selected_sheet = self.sheet_combo.currentText() or 0
            else:
                selected_sheet = 0
            df = pd.read_excel(path, engine="openpyxl", sheet_name=selected_sheet)
        except Exception as e:
            self.log_append(f"Failed to read Excel file: {e}")
            return

        # Normalize headers (strip, lower) for detection, keep original for access
        original_cols = list(df.columns)
        cols_norm = {str(c).strip().lower(): c for c in original_cols}

        def has_cols(required: List[str]) -> bool:
            return all(rc in cols_norm for rc in required)

        # Detect client schema and map to standard fields via external YAML only
        mapping: Optional[str] = None
        mapping_def: Optional[Dict[str, Any]] = None
        try:
            from pathlib import Path as _Path
            import yaml  # type: ignore

            base_dir = _Path(__file__).resolve().parent.parent / "config" / "clients"
            client_defs: List[Dict[str, Any]] = []
            if not base_dir.exists():
                self.log_append(f"Client definitions folder not found: {base_dir}")
            else:
                for yml in sorted(base_dir.glob("*.yaml")):
                    try:
                        with yml.open("r", encoding="utf-8") as f:
                            data = yaml.safe_load(f) or {}
                        name = str(data.get("name", "")).strip()
                        required = [str(x).strip().lower() for x in (data.get("required_headers") or [])]
                        fields = data.get("fields", {})
                        if name and required:
                            client_defs.append({"name": name, "required": required, "fields": fields})
                    except Exception as e:
                        self.log_append(f"Skipping client YAML {yml.name}: {e}")
            for cdef in client_defs:
                if has_cols(cdef["required"]):
                    mapping = cdef["name"]
                    mapping_def = cdef
                    break
        except Exception as e:
            self.log_append(f"Failed to load client definitions: {e}")

        if not mapping:
            self.log_append("Could not detect a client schema from headers.")
            self.log_append(f"Columns found: {original_cols}")
            return

        self.log_append(f"Detected schema: {mapping}")

        # US state name to code mapping (partial; include all states)
        state_name_to_code = {
            "alabama": "AL",
            "alaska": "AK",
            "arizona": "AZ",
            "arkansas": "AR",
            "california": "CA",
            "colorado": "CO",
            "connecticut": "CT",
            "delaware": "DE",
            "florida": "FL",
            "georgia": "GA",
            "hawaii": "HI",
            "idaho": "ID",
            "illinois": "IL",
            "indiana": "IN",
            "iowa": "IA",
            "kansas": "KS",
            "kentucky": "KY",
            "louisiana": "LA",
            "maine": "ME",
            "maryland": "MD",
            "massachusetts": "MA",
            "michigan": "MI",
            "minnesota": "MN",
            "mississippi": "MS",
            "missouri": "MO",
            "montana": "MT",
            "nebraska": "NE",
            "nevada": "NV",
            "new hampshire": "NH",
            "new jersey": "NJ",
            "new mexico": "NM",
            "new york": "NY",
            "north carolina": "NC",
            "north dakota": "ND",
            "ohio": "OH",
            "oklahoma": "OK",
            "oregon": "OR",
            "pennsylvania": "PA",
            "rhode island": "RI",
            "south carolina": "SC",
            "south dakota": "SD",
            "tennessee": "TN",
            "texas": "TX",
            "utah": "UT",
            "vermont": "VT",
            "virginia": "VA",
            "washington": "WA",
            "west virginia": "WV",
            "wisconsin": "WI",
            "wyoming": "WY",
            "district of columbia": "DC",
        }

        def norm_state(val: Any) -> Optional[str]:
            if val is None:
                return None
            s = str(val).strip()
            if not s:
                return None
            if len(s) == 2:
                return s.upper()
            return state_name_to_code.get(s.lower())

        def norm_zip(val: Any) -> Optional[str]:
            if val is None:
                return None
            s = str(val).strip()
            if not s:
                return None
            m = re.match(r"(\d{5})", s)
            return m.group(1) if m else None

        # Clean a dataframe value into a safe string: drop NaN/None/"nan" and trim
        def clean_part(val: Any) -> str:
            try:
                import pandas as pd  # type: ignore

                if pd.isna(val):
                    return ""
            except Exception:
                pass
            s = str(val).strip()
            if not s or s.lower() == "nan":
                return ""
            return s

        # Prepare output collectors per state
        outputs: Dict[str, List[Dict[str, str]]] = {}
        total = 0
        skipped = 0

        for _, row in df.iterrows():
            try:
                # Use YAML-defined field mapping to extract row values
                def get_field_value(spec: Any) -> str:
                    # spec can be a string (column key) or a dict with join: [keys]
                    try:
                        if isinstance(spec, str):
                            key = spec.strip().lower()
                            col = cols_norm.get(key)
                            return clean_part(row[col]) if col in row else ""
                        if isinstance(spec, dict) and "join" in spec:
                            parts: list[str] = []
                            for k in spec.get("join", []):
                                key = str(k).strip().lower()
                                col = cols_norm.get(key)
                                parts.append(clean_part(row[col]) if col in row else "")
                            return " ".join(p for p in parts if p)
                    except Exception:
                        return ""
                    return ""

                fields = (mapping_def or {}).get("fields", {}) if mapping_def else {}
                loc = get_field_value(fields.get("id", ""))
                addr = get_field_value(fields.get("address", ""))
                city = get_field_value(fields.get("city", ""))
                state_raw = get_field_value(fields.get("state", ""))
                zip_raw = get_field_value(fields.get("zip", ""))

                state = norm_state(state_raw)
                zip5 = norm_zip(zip_raw)
                if not state or not city or not addr or not zip5:
                    skipped += 1
                    continue

                rec = {
                    "id": clean_part(loc),
                    "address": addr,
                    "city": city,
                    "state": state,
                    "zip": zip5,
                }

                outputs.setdefault(state, []).append(rec)
                total += 1
            except Exception:
                skipped += 1

        # Write outputs per state
        for state, rows in outputs.items():
            out_dir = self.workspace / state
            assert out_dir is not None
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / "addresses.csv"
            try:
                # Write with header, overwrite existing for now (MVP). Could be append later.
                import csv

                with out_file.open("w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=["id", "address", "city", "state", "zip"])
                    writer.writeheader()
                    writer.writerows(rows)
                self.log_append(f"Wrote {len(rows)} rows to {out_file}")
            except Exception as e:
                self.log_append(f"Failed writing {out_file}: {e}")

        self.log_append(f"Parsing complete. Total kept: {total}, skipped: {skipped}.")
        # Refresh state list so new outputs appear in the view
        self.refresh_state_list()

    def log_append(self, msg: str) -> None:
        self.log.append(msg)
        self.log.moveCursor(QTextCursor.MoveOperation.End)
        self.log.ensureCursorVisible()

    # Workspace API for MainWindow
    def set_workspace(self, path_str: str) -> None:
        # Update workspace and clear UI so users don't accidentally parse into the wrong workspace
        self.workspace = Path(path_str) if path_str else None
        self.file_input.clear()
        self.log.clear()
        self.banner.setText(f"Workspace: {path_str}" if path_str else "Workspace: (none)")
        # Reset view tab contents
        self.refresh_state_list()
        self.clear_table()

    # -----------------
    # Parse View helpers
    # -----------------
    def _init_parse_view(self, container: QWidget) -> None:
        outer = QHBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # Left pane: state list
        left_box = QVBoxLayout()
        left_label = QLabel("States")
        left_label.setStyleSheet("font-weight: 600;")
        self.state_list = QListWidget()
        self.state_list.currentTextChanged.connect(self.on_state_selected)
        # Optional: fixed width for nicer layout
        self.state_list.setMinimumWidth(140)
        left_box.addWidget(left_label)
        left_box.addWidget(self.state_list, 1)

        # Right pane: CSV table
        right_box = QVBoxLayout()
        right_label = QLabel("addresses.csv preview")
        right_label.setStyleSheet("font-weight: 600;")
        self.state_table = QTableWidget()
        self.state_table.setColumnCount(0)
        self.state_table.setRowCount(0)
        right_box.addWidget(right_label)
        right_box.addWidget(self.state_table, 1)

        outer.addLayout(left_box, 0)
        outer.addLayout(right_box, 1)

        # Populate initial state list if workspace set
        self.refresh_state_list()

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
                    csv_path = p / "addresses.csv"
                    if csv_path.exists():
                        states.append(p.name)
            for st in states:
                self.state_list.addItem(st)
        except Exception:
            # ignore filesystem errors for now
            pass

    def on_state_selected(self, state_code: str) -> None:
        if not self.workspace or not state_code:
            self.clear_table()
            return
        csv_path = self.workspace / state_code / "addresses.csv"
        if not csv_path.exists():
            self.clear_table()
            return
        # Load CSV and populate table
        try:
            import pandas as pd  # type: ignore

            df = pd.read_csv(csv_path)
            self.populate_table_from_dataframe(df)
        except Exception:
            # Fallback to csv module if pandas has an issue
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
                self.state_table.setColumnCount(len(headers))
                self.state_table.setHorizontalHeaderLabels(headers)
                self.state_table.setRowCount(len(data_rows))
                for r, row_vals in enumerate(data_rows):
                    for c, val in enumerate(row_vals):
                        self.state_table.setItem(r, c, QTableWidgetItem(str(val)))
                # Apply column sizing
                self._apply_table_column_sizing(headers)
            except Exception:
                self.clear_table()

    def populate_table_from_dataframe(self, df) -> None:  # type: ignore[no-untyped-def]
        headers = list(df.columns)
        self.state_table.setColumnCount(len(headers))
        self.state_table.setHorizontalHeaderLabels([str(h) for h in headers])
        self.state_table.setRowCount(len(df))
        for r, (_, row) in enumerate(df.iterrows()):
            for c, h in enumerate(headers):
                self.state_table.setItem(r, c, QTableWidgetItem(str(row[h])))
        # Apply column sizing
        self._apply_table_column_sizing([str(h) for h in headers])

    def clear_table(self) -> None:
        if hasattr(self, "state_table"):
            self.state_table.clear()
            self.state_table.setColumnCount(0)
            self.state_table.setRowCount(0)

    def _apply_table_column_sizing(self, headers: list[str]) -> None:
        # Default: stretch columns to fill space
        header_view = self.state_table.horizontalHeader()
        header_view.setStretchLastSection(True)
        try:
            header_view.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        except Exception:
            pass
        # Set narrow fixed widths for 'state' and 'zip' columns when present
        name_to_index = {str(h).strip().lower(): i for i, h in enumerate(headers)}
        if "state" in name_to_index:
            idx = name_to_index["state"]
            try:
                header_view.setSectionResizeMode(idx, QHeaderView.ResizeMode.Interactive)
            except Exception:
                pass
            self.state_table.setColumnWidth(idx, 50)  # 2-letter
        if "zip" in name_to_index:
            idx = name_to_index["zip"]
            try:
                header_view.setSectionResizeMode(idx, QHeaderView.ResizeMode.Interactive)
            except Exception:
                pass
            self.state_table.setColumnWidth(idx, 70)  # 5-digit
