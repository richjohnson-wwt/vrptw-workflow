from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Optional

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class VRPTWTab(QWidget):
    """
    VRPTW routing tab. Provides two subtabs:
    - Log: solver logs and diagnostics
    - Solve: selectors and results view

    First step: UI scaffolding. Next step will wire the OR-Tools solver.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("VRPTWTab")
        self.workspace: Optional[Path] = None
        self.last_solution: Optional[dict] = (
            None  # {'state': str, 'mode': 'clusters'|'statewide', 'routes': List[Tuple[str, List[str]]]}
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("Compute minimal vehicle-days to visit clustered sites (VRPTW)")
        header.setWordWrap(True)
        header.setStyleSheet("font-weight: 600;")
        layout.addWidget(header)

        # Workspace banner
        self.banner = QLabel("Workspace: (none)")
        self.banner.setStyleSheet("color: #555; font-style: italic;")
        self.banner.setWordWrap(True)
        layout.addWidget(self.banner)

        # Subtabs
        self.subtabs = QTabWidget()
        self.subtabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Log tab
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(140)
        self.log.setPlaceholderText("VRPTW solver logs will appear here…")
        self.subtabs.addTab(self.log, "Log")

        # Solve tab
        self.solve = QWidget()
        self._init_solve_tab(self.solve)
        self.subtabs.addTab(self.solve, "Solve")

        layout.addWidget(self.subtabs, 1)
        # Removed extra stretch to allow subtabs to occupy full vertical space

    # Workspace API for MainWindow
    def set_workspace(self, path_str: str) -> None:
        self.workspace = Path(path_str) if path_str else None
        if hasattr(self, "log"):
            self.log.clear()
        if hasattr(self, "banner"):
            self.banner.setText(f"Workspace: {path_str}" if path_str else "Workspace: (none)")
        # refresh selectors
        self._refresh_states()
        self._clear_results()
        self.run_btn.setEnabled(False)

    # --- UI builders ---
    def _init_solve_tab(self, container: QWidget) -> None:
        outer = QHBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # Left: selectors & params
        left = QVBoxLayout()
        left.setSpacing(8)

        # States
        left.addWidget(self._bold_label("States"))
        self.state_list = QListWidget()
        self.state_list.setMinimumWidth(160)
        self.state_list.currentTextChanged.connect(self.on_state_selected)
        left.addWidget(self.state_list, 1)

        # Clusters
        left.addWidget(self._bold_label("Clusters (from clustered.csv)"))
        self.cluster_combo = QComboBox()
        self.cluster_combo.currentIndexChanged.connect(self._on_cluster_changed)
        left.addWidget(self.cluster_combo)

        # Params
        params = QFormLayout()
        self.service_hours = QDoubleSpinBox()
        self.service_hours.setRange(0.0, 24.0)
        self.service_hours.setSingleStep(0.25)
        self.service_hours.setValue(4.0)
        params.addRow("Default service time (h):", self.service_hours)

        self.avg_speed = QDoubleSpinBox()
        self.avg_speed.setSuffix(" mph")
        self.avg_speed.setRange(1.0, 120.0)
        self.avg_speed.setSingleStep(1.0)
        self.avg_speed.setValue(50.0)
        params.addRow("Average speed:", self.avg_speed)

        self.ignore_clusters = QCheckBox("Ignore clusters (solve whole state)")
        self.ignore_clusters.setToolTip(
            "Solve a single VRPTW model with all sites in the state, allowing one vehicle to visit multiple former clusters."
        )
        self.ignore_clusters.setChecked(True)
        params.addRow(self.ignore_clusters)

        left.addLayout(params)

        # Actions
        actions = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_states)
        self.run_btn = QPushButton("Run VRPTW")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self.on_run)
        self.map_btn = QPushButton("View on Map")
        self.map_btn.setEnabled(False)
        self.map_btn.setToolTip(
            "Create a Folium HTML map for the current solution and save it next to clustered.csv"
        )
        self.map_btn.clicked.connect(self.on_view_map)
        actions.addStretch(1)
        actions.addWidget(refresh_btn)
        actions.addWidget(self.run_btn)
        actions.addWidget(self.map_btn)
        left.addLayout(actions)

        # Right: results table
        right = QVBoxLayout()
        right.addWidget(self._bold_label("Results"))
        self.results = QTableWidget()
        self.results.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.results.setColumnCount(0)
        self.results.setRowCount(0)
        right.addWidget(self.results, 1)

        outer.addLayout(left, 0)
        outer.addLayout(right, 1)
        self.map_btn.setEnabled(False)
        self.last_solution = None

    def on_view_map(self) -> None:
        # Create a Folium map for the selected state using the most recent solution
        if not self.last_solution:
            QMessageBox.information(
                self, "No solution", "Run VRPTW first to generate a solution to display on the map."
            )
            return
        state = self.last_solution.get("state")
        if not self.workspace or not state:
            QMessageBox.warning(
                self, "Missing workspace", "Please select a valid workspace and state."
            )
            return
        try:
            import folium
        except Exception as e:
            self.log_append(f"Folium not available: {e}")
            QMessageBox.critical(
                self,
                "Dependency missing",
                "folium is required to build the map.\nInstall with: uv add folium",
            )
            return

        csv_path = self.workspace / state / "clustered.csv"
        if not csv_path.exists():
            QMessageBox.warning(self, "Missing clustered.csv", f"Could not find {csv_path}")
            return

        # Load locations by id
        import csv as _csv

        points = {}
        meta = {}
        with csv_path.open("r", newline="", encoding="utf-8") as f:
            rdr = _csv.reader(f)
            header = next(rdr, None)
            if not header:
                QMessageBox.warning(self, "Empty CSV", f"No data in {csv_path}")
                return
            colmap = {name.lower(): idx for idx, name in enumerate(header)}
            id_idx = colmap.get("id")
            lat_idx = colmap.get("lat") or colmap.get("latitude")
            lon_idx = colmap.get("lon") or colmap.get("longitude")
            addr_idx = colmap.get("address")
            name_idx = colmap.get("display_name")
            for row in rdr:
                if id_idx is None or lat_idx is None or lon_idx is None:
                    continue
                sid = row[id_idx]
                try:
                    lat = float(row[lat_idx])
                    lon = float(row[lon_idx])
                except Exception:
                    continue
                points[sid] = (lat, lon)
                meta[sid] = {
                    "address": (
                        row[addr_idx] if addr_idx is not None and addr_idx < len(row) else ""
                    ),
                    "display_name": (
                        row[name_idx] if name_idx is not None and name_idx < len(row) else ""
                    ),
                }

        # Gather all points used by routes
        all_coords = []
        missing: set[str] = set()
        for _, seq_ids in self.last_solution["routes"]:
            for sid in seq_ids:
                if sid in points:
                    all_coords.append(points[sid])
                else:
                    missing.add(str(sid))
        if missing:
            self.log_append(
                f"Map note: {len(missing)} site id(s) from routes had no coordinates in clustered.csv: "
                + ", ".join(sorted(list(missing))[:10])
                + (" …" if len(missing) > 10 else "")
            )
            self.log_append(
                "If these should appear, check clustered.csv for blank/invalid lat/lon for those ids."
            )
        if not all_coords:
            QMessageBox.information(
                self, "No coordinates", "The current solution has no mappable coordinates."
            )
            return
        avg_lat = sum(lat for lat, _ in all_coords) / len(all_coords)
        avg_lon = sum(lon for _, lon in all_coords) / len(all_coords)
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=8, tiles="OpenStreetMap")
        # Ensure all points are visible regardless of initial zoom
        try:
            lats = [lat for lat, _ in all_coords]
            lons = [lon for _, lon in all_coords]
            sw = [min(lats), min(lons)]
            ne = [max(lats), max(lons)]
            m.fit_bounds([sw, ne])
        except Exception:
            pass

        # Color palette for up to many routes
        colors = [
            "red",
            "blue",
            "green",
            "purple",
            "orange",
            "darkred",
            "lightred",
            "beige",
            "darkblue",
            "darkgreen",
            "cadetblue",
            "darkpurple",
            "white",
            "pink",
            "lightblue",
            "lightgreen",
            "gray",
            "black",
            "lightgray",
        ]

        # Optional: cluster markers and jitter overlapping coordinates for visibility
        marker_cluster = None
        try:
            from folium.plugins import MarkerCluster  # type: ignore

            marker_cluster = MarkerCluster()
            marker_cluster.add_to(m)
        except Exception:
            marker_cluster = None

        seen_counts: dict[tuple[float, float], int] = {}

        # Plot each route
        for idx, (cluster_label, seq_ids) in enumerate(self.last_solution["routes"]):
            color = colors[idx % len(colors)]
            coords = [points[sid] for sid in seq_ids if sid in points]
            if len(coords) >= 2:
                folium.PolyLine(
                    coords,
                    color=color,
                    weight=4,
                    opacity=0.8,
                    tooltip=f"Route {idx} (Cluster {cluster_label})",
                ).add_to(m)
            # Add markers with order numbers
            for order, sid in enumerate(seq_ids, start=1):
                if sid not in points:
                    continue
                lat, lon = points[sid]
                # Jitter overlapping markers slightly so both can be clicked
                key = (lat, lon)
                n = seen_counts.get(key, 0)
                if n > 0:
                    # ~10 meters jitter per overlap (approx 1e-4 deg)
                    jitter = 1e-4 * n
                    lat += jitter
                    lon += jitter
                seen_counts[key] = n + 1
                popup = folium.Popup(
                    html=f"<b>{sid}</b><br>{meta.get(sid,{}).get('address','')}<br>{meta.get(sid,{}).get('display_name','')}",
                    max_width=300,
                )
                marker = folium.Marker(
                    location=[lat, lon],
                    popup=popup,
                    tooltip=f"{order}. {sid}",
                    icon=folium.Icon(color=color, icon="info-sign"),
                )
                try:
                    if marker_cluster is not None:
                        marker.add_to(marker_cluster)
                    else:
                        marker.add_to(m)
                except Exception:
                    marker.add_to(m)

        out_path = self.workspace / state / "routes_map.html"
        try:
            m.save(str(out_path))
            self.log_append(f"Map saved to {out_path}")
            QMessageBox.information(self, "Map saved", f"Map saved to {out_path}")
            # Open in default browser
            try:
                import webbrowser

                webbrowser.open(out_path.as_uri())
            except Exception:
                pass
        except Exception as e:
            self.log_append(f"Failed to save map: {e}")
            QMessageBox.critical(self, "Save failed", f"Failed to save map: {e}")

    def _bold_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: 600;")
        return lbl

    # --- Actions ---
    def on_state_selected(self, state_code: str) -> None:
        self.cluster_combo.clear()
        self.run_btn.setEnabled(False)
        self._clear_results()
        if not self.workspace or not state_code:
            return
        csv_path = self.workspace / state_code / "clustered.csv"
        if not csv_path.exists():
            self.log_append(f"No clustered.csv for state {state_code} at {csv_path}")
            return
        # Extract cluster counts and populate combo
        counts = self._read_cluster_counts(csv_path)
        if counts:
            self.cluster_combo.addItem("All clusters", userData=None)
            for cid in sorted(counts.keys()):
                label = f"{cid} (N={counts[cid]})"
                self.cluster_combo.addItem(label, userData=cid)
            self.run_btn.setEnabled(True)
        
        # Load previously solved solution if it exists
        loaded_solution = self._load_solution(state_code)
        if loaded_solution:
            self._display_loaded_solution(loaded_solution)

    def _on_cluster_changed(self, _: int) -> None:
        # Placeholder for future: show current cluster preview/summary
        pass

    def on_run(self) -> None:
        state = self.state_list.currentItem().text() if self.state_list.currentItem() else ""
        data = self.cluster_combo.currentData()
        # data is None for All clusters, or int for a specific cluster
        if not state or (
            not self.ignore_clusters.isChecked()
            and data is None
            and self.cluster_combo.currentIndex() < 0
        ):
            QMessageBox.information(self, "Select inputs", "Please select a state and cluster.")
            return
        # Try to import OR-Tools lazily
        try:
            pass
        except Exception as e:
            self.log_append(f"OR-Tools not available: {e}")
            QMessageBox.critical(
                self,
                "Dependency missing",
                "ortools is required to run the VRPTW solver.\nInstall with: uv add ortools",
            )
            return

        speed_mph = float(self.avg_speed.value())
        default_service_h = float(self.service_hours.value())
        clustered_path = (self.workspace / state / "clustered.csv") if self.workspace else None
        if not clustered_path or not clustered_path.exists():
            self.log_append(f"Missing clustered.csv for {state}: {clustered_path}")
            return

        # Run state-wide (ignore clusters) or per cluster(s)
        self._clear_results()
        all_rows: list[tuple[str, str, int, list[str]]] = (
            []
        )  # (state, cluster_label, vehicle_idx, visit_ids)
        cluster_ids: list[int]
        if self.ignore_clusters.isChecked():
            cluster_ids = []  # we won't iterate clusters
        else:
            if data is None:
                counts = self._read_cluster_counts(clustered_path)
                cluster_ids = sorted(counts.keys())
            else:
                cluster_ids = [int(data)]

        # If we're not ignoring clusters and none were found, show message and return.
        if not self.ignore_clusters.isChecked() and not cluster_ids:
            self.log_append(f"No clusters found to solve for state={state}.")
            # Prepare empty table with headers so user sees structure
            headers = ["State", "Cluster", "Vehicle (day)", "Stops", "Sequence (site ids)"]
            self.results.setColumnCount(len(headers))
            self.results.setHorizontalHeaderLabels(headers)
            self.results.setRowCount(1)
            self.results.setItem(0, 0, QTableWidgetItem(state))
            self.results.setItem(0, 1, QTableWidgetItem("-"))
            self.results.setItem(0, 2, QTableWidgetItem("-"))
            self.results.setItem(0, 3, QTableWidgetItem("0"))
            self.results.setItem(0, 4, QTableWidgetItem("No clusters available"))
            self.results.resizeColumnsToContents()
            return

        if self.ignore_clusters.isChecked():
            try:
                routes_ids = self._solve_state_wide(clustered_path, speed_mph, default_service_h)
            except Exception as e:
                self.log_append(f"Solver failed for state={state} (state-wide): {e}")
                routes_ids = []
            for v_idx, seq_ids in enumerate(routes_ids):
                all_rows.append((state, "ALL", v_idx, seq_ids))
        else:
            for cid in cluster_ids:
                try:
                    routes_ids = self._solve_single_cluster(
                        clustered_path, cid, speed_mph, default_service_h
                    )
                except Exception as e:
                    self.log_append(f"Solver failed for state={state} cluster={cid}: {e}")
                    continue
                for v_idx, seq_ids in enumerate(routes_ids):
                    all_rows.append((state, str(cid), v_idx, seq_ids))

        # Render results table
        headers = ["State", "Cluster", "Vehicle (day)", "Stops", "Sequence (site ids)"]
        self.results.setColumnCount(len(headers))
        self.results.setHorizontalHeaderLabels(headers)
        if all_rows:
            self.results.setRowCount(len(all_rows))
            for r, (st, cid_label, v, seq_ids) in enumerate(all_rows):
                self.results.setItem(r, 0, QTableWidgetItem(str(st)))
                self.results.setItem(r, 1, QTableWidgetItem(str(cid_label)))
                self.results.setItem(r, 2, QTableWidgetItem(str(v)))
                self.results.setItem(r, 3, QTableWidgetItem(str(len(seq_ids))))
                self.results.setItem(r, 4, QTableWidgetItem(", ".join(seq_ids)))
            self.results.resizeColumnsToContents()
            # Metrics
            vehicle_days = len(all_rows)
            total_stops = sum(len(seq_ids) for (_, _, _, seq_ids) in all_rows)
            avg_stops = (total_stops / vehicle_days) if vehicle_days > 0 else 0.0
            if self.ignore_clusters.isChecked():
                self.log_append(
                    f"Computed {vehicle_days} vehicle-days for state-wide solve. Avg stops/day: {avg_stops:.2f}"
                )
            else:
                self.log_append(
                    f"Computed {vehicle_days} vehicle-days across {len(cluster_ids)} cluster(s). Avg stops/day: {avg_stops:.2f}"
                )
            # Store last solution for mapping
            mode = "statewide" if self.ignore_clusters.isChecked() else "clusters"
            self.last_solution = {
                "state": state,
                "mode": mode,
                "routes": [(cid_label, seq_ids) for (_, cid_label, _, seq_ids) in all_rows],
            }
            self.map_btn.setEnabled(True)
            
            # Save solution to file for persistence
            self._save_solution(state, all_rows, mode, speed_mph, default_service_h)
        else:
            # Show an informative single row
            self.results.setRowCount(1)
            self.results.setItem(0, 0, QTableWidgetItem(state))
            self.results.setItem(
                0,
                1,
                QTableWidgetItem(
                    "ALL" if self.ignore_clusters.isChecked() else ", ".join(map(str, cluster_ids))
                ),
            )
            self.results.setItem(0, 2, QTableWidgetItem("-"))
            self.results.setItem(0, 3, QTableWidgetItem("0"))
            self.results.setItem(
                0, 4, QTableWidgetItem("No feasible routes found within 9–17 window")
            )
            self.results.resizeColumnsToContents()
            self.log_append(
                "No feasible routes found; consider increasing vehicles (more clusters), reducing service time, or increasing time window."
            )
            self.last_solution = None
            self.map_btn.setEnabled(False)

    # --- Helpers ---
    def _refresh_states(self) -> None:
        self.state_list.clear()
        if not self.workspace or not self.workspace.exists():
            return
        try:
            for p in sorted([d for d in self.workspace.iterdir() if d.is_dir()]):
                if p.name.startswith("."):
                    continue
                self.state_list.addItem(p.name)
        except Exception as e:
            self.log_append(f"Failed listing states: {e}")

    def _clear_results(self) -> None:
        self.results.clear()
        self.results.setColumnCount(0)
        self.results.setRowCount(0)

    # --- Solver helpers ---
    def _solve_single_cluster(
        self, csv_path: Path, cluster_id: int, speed_mph: float, default_service_h: float
    ) -> List[List[str]]:
        """
        Returns a list of routes. Each route is a list of site ids (strings) for the filtered rows in this cluster.
        """
        import math

        # Load and filter rows for the cluster; capture lat/lon and optional service_time_hours
        rows: list[list[str]]
        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            if not header:
                return []
            colmap = {name.lower(): idx for idx, name in enumerate(header)}
            cid_idx = colmap.get("cluster_id")
            if cid_idx is None:
                # try case-insensitive
                for name, idx in colmap.items():
                    if name.lower() == "cluster_id":
                        cid_idx = idx
                        break
            if cid_idx is None:
                raise ValueError("cluster_id column not found")
            lat_idx = colmap.get("lat") or colmap.get("latitude")
            lon_idx = colmap.get("lon") or colmap.get("longitude")
            if lat_idx is None or lon_idx is None:
                raise ValueError("lat/lon (or latitude/longitude) columns not found")
            svc_idx = colmap.get("service_time_hours")
            id_idx = colmap.get("id")
            rows = [
                row
                for row in reader
                if cid_idx < len(row)
                and row[cid_idx] != ""
                and int(float(row[cid_idx])) == int(cluster_id)
            ]

        n = len(rows)
        if n == 0:
            return []
        # Build vectors
        lats = [float(rows[i][lat_idx]) for i in range(n)]
        lons = [float(rows[i][lon_idx]) for i in range(n)]
        ids = [
            rows[i][id_idx] if id_idx is not None and rows[i][id_idx] != "" else str(i)
            for i in range(n)
        ]
        svc_min = [
            int(
                round(
                    (
                        float(rows[i][svc_idx])
                        if svc_idx is not None and rows[i][svc_idx] != ""
                        else default_service_h
                    )
                    * 60
                )
            )
            for i in range(n)
        ]

        # Haversine distance in miles
        def hav_miles(i: int, j: int) -> float:
            R = 3958.7613
            p = math.pi / 180.0
            dlat = (lats[j] - lats[i]) * p
            dlon = (lons[j] - lons[i]) * p
            a = (
                math.sin(dlat / 2) ** 2
                + math.cos(lats[i] * p) * math.cos(lats[j] * p) * math.sin(dlon / 2) ** 2
            )
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return R * c

        # Travel time minutes matrix between sites (n x n)
        def travel_min(i: int, j: int) -> int:
            if i == j:
                return 0
            miles = hav_miles(i, j)
            hours = miles / max(1e-6, speed_mph)
            return int(round(hours * 60))

        # Build full time matrix including a dummy depot at index 0
        # Sites will be mapped to 1..n in the matrix; depot=0
        size = n + 1
        time_matrix = [[0 for _ in range(size)] for __ in range(size)]
        # depot (0) to sites is 0 to allow start at 9:00 without travel
        # sites to depot will carry the site's service time so the last site's service is counted
        for i in range(n):
            for j in range(n):
                # time from site i to site j includes service at i
                t = travel_min(i, j) + svc_min[i]
                time_matrix[i + 1][j + 1] = t
            # Charge service time when finishing at depot from site i
            time_matrix[i + 1][0] = svc_min[i]
        # 0 -> sites remains 0

        # Log quick diagnostics
        total_service = sum(svc_min)
        self.log_append(
            f"Cluster {cluster_id}: n={n}, total service={total_service} min (~{total_service/60:.1f} h)"
        )

        # OR-Tools setup
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2

        manager = pywrapcp.RoutingIndexManager(size, n, 0)  # up to n vehicles (one per site)
        routing = pywrapcp.RoutingModel(manager)

        # Transit callback
        def transit_cb(from_index: int, to_index: int) -> int:
            i = manager.IndexToNode(from_index)
            j = manager.IndexToNode(to_index)
            return time_matrix[i][j]

        transit_cb_index = routing.RegisterTransitCallback(transit_cb)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_cb_index)

        # Time dimension with 8-hour horizon (480 minutes). Start cumul at 0 (represents 9:00 AM).
        horizon = 480
        routing.AddDimension(
            transit_cb_index,
            0,  # no slack
            horizon,
            True,  # force start cumul to 0
            "Time",
        )
        time_dim = routing.GetDimensionOrDie("Time")

        # Windows for all non-depot nodes (sites 1..n): [0, horizon]
        for node in range(1, size):
            index = manager.NodeToIndex(node)
            time_dim.CumulVar(index).SetRange(0, horizon)

        # Encourage minimal vehicles by assigning a fixed cost per used vehicle
        routing.SetFixedCostOfAllVehicles(100000)

        # Allow routes to end anywhere implicitly via default end at depot with 0 return time

        # Search parameters
        search = pywrapcp.DefaultRoutingSearchParameters()
        search.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        search.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search.time_limit.FromSeconds(5)

        solution = routing.SolveWithParameters(search)
        routes: List[List[str]] = []
        if not solution:
            return routes

        # Extract non-empty routes; map node indices back to site indices (0..n-1)
        for v in range(routing.vehicles()):
            index = routing.Start(v)
            seq_ids: List[str] = []
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                if node != 0:  # skip depot
                    seq_ids.append(ids[node - 1])
                index = solution.Value(routing.NextVar(index))
            if seq_ids:
                routes.append(seq_ids)

        return routes

    def _solve_state_wide(
        self, csv_path: Path, speed_mph: float, default_service_h: float
    ) -> List[List[str]]:
        """
        Solve VRPTW for all rows in the state's clustered.csv, ignoring cluster boundaries.
        Returns list of routes as lists of site ids.
        """
        import math

        rows: list[list[str]]
        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            if not header:
                return []
            colmap = {name.lower(): idx for idx, name in enumerate(header)}
            lat_idx = colmap.get("lat") or colmap.get("latitude")
            lon_idx = colmap.get("lon") or colmap.get("longitude")
            if lat_idx is None or lon_idx is None:
                raise ValueError("lat/lon (or latitude/longitude) columns not found")
            svc_idx = colmap.get("service_time_hours")
            id_idx = colmap.get("id")
            rows = [row for row in reader]

        n = len(rows)
        if n == 0:
            return []
        lats = [float(rows[i][lat_idx]) for i in range(n)]
        lons = [float(rows[i][lon_idx]) for i in range(n)]
        ids = [
            rows[i][id_idx] if id_idx is not None and rows[i][id_idx] != "" else str(i)
            for i in range(n)
        ]
        svc_min = [
            int(
                round(
                    (
                        float(rows[i][svc_idx])
                        if svc_idx is not None and rows[i][svc_idx] != ""
                        else default_service_h
                    )
                    * 60
                )
            )
            for i in range(n)
        ]

        def hav_miles(i: int, j: int) -> float:
            R = 3958.7613
            p = math.pi / 180.0
            dlat = (lats[j] - lats[i]) * p
            dlon = (lons[j] - lons[i]) * p
            a = (
                math.sin(dlat / 2) ** 2
                + math.cos(lats[i] * p) * math.cos(lats[j] * p) * math.sin(dlon / 2) ** 2
            )
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return R * c

        def travel_min(i: int, j: int) -> int:
            if i == j:
                return 0
            miles = hav_miles(i, j)
            hours = miles / max(1e-6, speed_mph)
            return int(round(hours * 60))

        size = n + 1
        time_matrix = [[0 for _ in range(size)] for __ in range(size)]
        for i in range(n):
            for j in range(n):
                t = travel_min(i, j) + svc_min[i]
                time_matrix[i + 1][j + 1] = t
            time_matrix[i + 1][0] = svc_min[i]

        from ortools.constraint_solver import pywrapcp, routing_enums_pb2

        manager = pywrapcp.RoutingIndexManager(size, n, 0)
        routing = pywrapcp.RoutingModel(manager)

        def transit_cb(from_index: int, to_index: int) -> int:
            i = manager.IndexToNode(from_index)
            j = manager.IndexToNode(to_index)
            return time_matrix[i][j]

        transit_cb_index = routing.RegisterTransitCallback(transit_cb)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_cb_index)

        horizon = 480
        routing.AddDimension(transit_cb_index, 0, horizon, True, "Time")
        time_dim = routing.GetDimensionOrDie("Time")
        for node in range(1, size):
            idx = manager.NodeToIndex(node)
            time_dim.CumulVar(idx).SetRange(0, horizon)

        routing.SetFixedCostOfAllVehicles(100000)

        search = pywrapcp.DefaultRoutingSearchParameters()
        search.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        search.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search.time_limit.FromSeconds(5)

        solution = routing.SolveWithParameters(search)
        routes_ids: List[List[str]] = []
        if not solution:
            return routes_ids
        for v in range(routing.vehicles()):
            index = routing.Start(v)
            seq_ids: List[str] = []
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                if node != 0:
                    seq_ids.append(ids[node - 1])
                index = solution.Value(routing.NextVar(index))
            if seq_ids:
                routes_ids.append(seq_ids)
        return routes_ids

    def _read_cluster_counts(self, csv_path: Path) -> dict[int, int]:
        counts: dict[int, int] = {}
        try:
            with csv_path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    return counts
                colmap = {name: idx for idx, name in enumerate(header)}
                cid_idx = colmap.get("cluster_id")
                if cid_idx is None:
                    # attempt case-insensitive
                    for name, idx in colmap.items():
                        if name.lower() == "cluster_id":
                            cid_idx = idx
                            break
                if cid_idx is None:
                    self.log_append(f"No cluster_id column found in {csv_path}")
                    return counts
                for row in reader:
                    if cid_idx < len(row):
                        try:
                            val = int(float(row[cid_idx]))
                        except Exception:
                            continue
                        counts[val] = counts.get(val, 0) + 1
        except Exception as e:
            self.log_append(f"Failed reading {csv_path}: {e}")
        return counts

    def _save_solution(
        self,
        state: str,
        all_rows: list[tuple[str, str, int, list[str]]],
        mode: str,
        speed_mph: float,
        service_hours: float,
    ) -> None:
        """
        Save the solved routes to a solved.csv file in the state directory.
        
        Args:
            state: State code
            all_rows: List of (state, cluster_label, vehicle_idx, seq_ids)
            mode: "statewide" or "clusters"
            speed_mph: Speed parameter used
            service_hours: Service time parameter used
        """
        if not self.workspace:
            return
        
        from datetime import datetime
        
        solved_path = self.workspace / state / "solved.csv"
        try:
            with solved_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                # Write header
                writer.writerow([
                    "state",
                    "cluster",
                    "vehicle",
                    "stops",
                    "sequence",
                    "mode",
                    "speed_mph",
                    "service_hours",
                    "solved_at",
                ])
                
                # Write routes
                solved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for st, cluster_label, vehicle_idx, seq_ids in all_rows:
                    writer.writerow([
                        st,
                        cluster_label,
                        vehicle_idx,
                        len(seq_ids),
                        ",".join(seq_ids),
                        mode,
                        speed_mph,
                        service_hours,
                        solved_at,
                    ])
            
            self.log_append(f"Solution saved to {solved_path}")
        except Exception as e:
            self.log_append(f"Failed to save solution: {e}")
    
    def _load_solution(self, state: str) -> Optional[dict]:
        """
        Load a previously solved solution from solved.csv if it exists.
        
        Args:
            state: State code
        
        Returns:
            Dictionary with solution data or None if no solution exists
        """
        if not self.workspace:
            return None
        
        solved_path = self.workspace / state / "solved.csv"
        if not solved_path.exists():
            return None
        
        try:
            all_rows: list[tuple[str, str, int, list[str]]] = []
            mode = "clusters"
            speed_mph = 50.0
            service_hours = 4.0
            solved_at = ""
            
            with solved_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    st = row.get("state", state)
                    cluster_label = row.get("cluster", "")
                    vehicle_idx = int(row.get("vehicle", 0))
                    stops = int(row.get("stops", 0))
                    sequence = row.get("sequence", "")
                    seq_ids = [s.strip() for s in sequence.split(",") if s.strip()]
                    
                    # Get parameters from first row
                    if not all_rows:
                        mode = row.get("mode", "clusters")
                        speed_mph = float(row.get("speed_mph", 50.0))
                        service_hours = float(row.get("service_hours", 4.0))
                        solved_at = row.get("solved_at", "")
                    
                    all_rows.append((st, cluster_label, vehicle_idx, seq_ids))
            
            if all_rows:
                self.log_append(f"Loaded solution from {solved_path} (solved at: {solved_at})")
                return {
                    "state": state,
                    "mode": mode,
                    "all_rows": all_rows,
                    "speed_mph": speed_mph,
                    "service_hours": service_hours,
                    "solved_at": solved_at,
                }
            
        except Exception as e:
            self.log_append(f"Failed to load solution from {solved_path}: {e}")
        
        return None
    
    def _display_loaded_solution(self, loaded_solution: dict) -> None:
        """
        Display a loaded solution in the results table.
        
        Args:
            loaded_solution: Dictionary with solution data from _load_solution
        """
        all_rows = loaded_solution["all_rows"]
        state = loaded_solution["state"]
        mode = loaded_solution["mode"]
        
        # Render results table
        headers = ["State", "Cluster", "Vehicle (day)", "Stops", "Sequence (site ids)"]
        self.results.setColumnCount(len(headers))
        self.results.setHorizontalHeaderLabels(headers)
        
        if all_rows:
            self.results.setRowCount(len(all_rows))
            for r, (st, cid_label, v, seq_ids) in enumerate(all_rows):
                self.results.setItem(r, 0, QTableWidgetItem(str(st)))
                self.results.setItem(r, 1, QTableWidgetItem(str(cid_label)))
                self.results.setItem(r, 2, QTableWidgetItem(str(v)))
                self.results.setItem(r, 3, QTableWidgetItem(str(len(seq_ids))))
                self.results.setItem(r, 4, QTableWidgetItem(", ".join(seq_ids)))
            self.results.resizeColumnsToContents()
            
            # Update last_solution for map functionality
            self.last_solution = {
                "state": state,
                "mode": mode,
                "routes": [(cid_label, seq_ids) for (_, cid_label, _, seq_ids) in all_rows],
            }
            self.map_btn.setEnabled(True)
            
            # Show metrics
            vehicle_days = len(all_rows)
            total_stops = sum(len(seq_ids) for (_, _, _, seq_ids) in all_rows)
            avg_stops = (total_stops / vehicle_days) if vehicle_days > 0 else 0.0
            self.log_append(
                f"Loaded solution: {vehicle_days} vehicle-days, {total_stops} total stops, "
                f"avg {avg_stops:.2f} stops/day (mode: {mode})"
            )

    def log_append(self, msg: str) -> None:
        self.log.append(msg)
        self.log.moveCursor(QTextCursor.MoveOperation.End)
        self.log.ensureCursorVisible()
