# -*- coding: utf-8 -*-
import os
import sys
import traceback

# Plugin-local libraries (optional): stereo_gis/lib
LIB = os.path.join(os.path.dirname(__file__), "lib")
if os.path.isdir(LIB) and LIB not in sys.path:
    sys.path.insert(0, LIB)

import numpy as np

from qgis.PyQt.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QComboBox, QCheckBox,
    QPushButton, QSpinBox, QLineEdit, QFileDialog, QGroupBox,
    QRadioButton, QTableView, QAbstractItemView, QMessageBox
)
from qgis.PyQt.QtGui import QStandardItemModel, QStandardItem

from qgis.core import QgsProject, QgsVectorLayer

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

import mplstereonet

from .stereo_gis_analysis import (
    read_orientations_from_layer_selection,
    vmf_mean_axial,
    bingham_principal_axes_axial,
    kmedoids_pam_axial,
    xyz_to_trend_plunge,
    wrap360, dipdir2strike,
)


class CopyableTableView(QTableView):
    def keyPressEvent(self, event):
        if event.matches(event.StandardKey.Copy):
            self.copySelectionToClipboard()
            return
        super().keyPressEvent(event)

    def copySelectionToClipboard(self):
        selection = self.selectionModel().selectedIndexes()
        if not selection:
            return
        selection = sorted(selection, key=lambda x: (x.row(), x.column()))
        rows = {}
        for idx in selection:
            rows.setdefault(idx.row(), {})[idx.column()] = idx.data() if idx.data() is not None else ""
        lines = []
        for r in sorted(rows.keys()):
            cols = rows[r]
            maxc = max(cols.keys())
            line = "\t".join(str(cols.get(c, "")) for c in range(maxc + 1))
            lines.append(line)
        tsv = "\n".join(lines)
        from qgis.PyQt.QtWidgets import QApplication
        QApplication.clipboard().setText(tsv)


class StereoGisDialog(QDialog):
    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.setWindowTitle("Stereo GIS")
        self.resize(1100, 750)

        self._picked_medoid_indices = []
        self._picking_enabled = False
        self._last_vectors_xyz = None
        self._last_projected = None

        self._init_ui()
        self._populate_layers()

    def _init_ui(self):
        main = QHBoxLayout(self)

        left = QVBoxLayout()
        right = QVBoxLayout()
        main.addLayout(left, 0)
        main.addLayout(right, 1)

        # Inputs
        g_in = QGroupBox("Inputs (selected features only)")
        left.addWidget(g_in)
        grid = QGridLayout(g_in)

        grid.addWidget(QLabel("Layer:"), 0, 0)
        self.layer_combo = QComboBox()
        grid.addWidget(self.layer_combo, 0, 1, 1, 3)

        grid.addWidget(QLabel("Data:"), 1, 0)
        self.data_combo = QComboBox()
        self.data_combo.addItems(["Planes (dip/dipdir)", "Lines (plunge/trend)"])
        grid.addWidget(self.data_combo, 1, 1, 1, 3)

        self.field1_label = QLabel("Dip field:")
        self.field2_label = QLabel("DipDir field:")
        self.field1_combo = QComboBox()
        self.field2_combo = QComboBox()
        grid.addWidget(self.field1_label, 2, 0)
        grid.addWidget(self.field1_combo, 2, 1, 1, 3)
        grid.addWidget(self.field2_label, 3, 0)
        grid.addWidget(self.field2_combo, 3, 1, 1, 3)

        self.layer_combo.currentIndexChanged.connect(self._refresh_fields)
        self.data_combo.currentIndexChanged.connect(self._refresh_field_controls)

        # Plot options
        g_plot = QGroupBox("Plot options")
        left.addWidget(g_plot)
        gridp = QGridLayout(g_plot)

        self.chk_individual = QCheckBox("Plot individual data")
        self.chk_individual.setChecked(True)
        self.chk_contours = QCheckBox("Plot contours (points)")
        self.chk_contours.setChecked(False)
        self.contour_levels = QSpinBox()
        self.contour_levels.setRange(3, 30)
        self.contour_levels.setValue(10)

        gridp.addWidget(self.chk_individual, 0, 0, 1, 2)
        gridp.addWidget(self.chk_contours, 1, 0, 1, 1)
        gridp.addWidget(QLabel("Levels:"), 1, 1)
        gridp.addWidget(self.contour_levels, 1, 2)

        self.plane_mode_combo = QComboBox()
        self.plane_mode_combo.addItems(["Poles", "Great circles", "Both"])
        gridp.addWidget(QLabel("Planes mode:"), 2, 0)
        gridp.addWidget(self.plane_mode_combo, 2, 1, 1, 2)

        # Means
        g_means = QGroupBox("Means / models")
        left.addWidget(g_means)
        gridm = QGridLayout(g_means)

        self.chk_vmf = QCheckBox("Plot VMF axial mean (mirror upper hemisphere)")
        self.chk_vmf.setChecked(True)
        self.chk_bingham = QCheckBox("Plot Bingham summary (β axis + girdle)")
        self.chk_bingham.setChecked(True)

        gridm.addWidget(self.chk_vmf, 0, 0, 1, 2)
        gridm.addWidget(self.chk_bingham, 1, 0, 1, 2)

        # K-medoids
        g_km = QGroupBox("K-medoids clustering")
        left.addWidget(g_km)
        gridk = QGridLayout(g_km)

        self.chk_kmedoids = QCheckBox("Enable k-medoids")
        self.chk_kmedoids.setChecked(False)
        gridk.addWidget(self.chk_kmedoids, 0, 0, 1, 2)

        gridk.addWidget(QLabel("k classes:"), 1, 0)
        self.k_spin = QSpinBox()
        self.k_spin.setRange(1, 999999)
        self.k_spin.setValue(2)
        gridk.addWidget(self.k_spin, 1, 1)

        self.init_random = QRadioButton("Random init")
        self.init_pick = QRadioButton("Pick medoids on plot")
        self.init_random.setChecked(True)
        gridk.addWidget(self.init_random, 2, 0, 1, 2)
        gridk.addWidget(self.init_pick, 3, 0, 1, 2)

        gridk.addWidget(QLabel("Random seed:"), 4, 0)
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 10**9)
        self.seed_spin.setValue(0)
        gridk.addWidget(self.seed_spin, 4, 1)

        self.btn_pick = QPushButton("Pick medoids")
        self.btn_clear_picks = QPushButton("Clear picks")
        self.lbl_picks = QLabel("Picked: 0")
        gridk.addWidget(self.btn_pick, 5, 0)
        gridk.addWidget(self.btn_clear_picks, 5, 1)
        gridk.addWidget(self.lbl_picks, 6, 0, 1, 2)

        self.btn_pick.clicked.connect(self._toggle_picking)
        self.btn_clear_picks.clicked.connect(self._clear_picks)

        self.chk_plot_clusters = QCheckBox("Plot clustered results")
        self.chk_plot_clusters.setChecked(True)
        gridk.addWidget(self.chk_plot_clusters, 7, 0, 1, 2)

        # Saving
        g_save = QGroupBox("Saving (off by default)")
        left.addWidget(g_save)
        grids = QGridLayout(g_save)

        self.chk_save = QCheckBox("Save outputs")
        self.chk_save.setChecked(False)
        grids.addWidget(self.chk_save, 0, 0, 1, 2)

        grids.addWidget(QLabel("Directory:"), 1, 0)
        self.out_dir = QLineEdit("")
        self.btn_browse = QPushButton("Browse…")
        grids.addWidget(self.out_dir, 1, 1)
        grids.addWidget(self.btn_browse, 1, 2)
        self.btn_browse.clicked.connect(self._browse_dir)

        self.chk_save_png = QCheckBox("Save plot PNG")
        self.chk_save_png.setChecked(True)
        grids.addWidget(self.chk_save_png, 2, 0, 1, 2)

        # Run
        self.btn_run = QPushButton("Run analysis")
        left.addWidget(self.btn_run)
        self.btn_run.clicked.connect(self._run_analysis)

        left.addStretch(1)

        # Plot
        self.fig = Figure(figsize=(6, 6), dpi=120)
        self.canvas = FigureCanvas(self.fig)
        right.addWidget(self.canvas, 2)

        self.ax = self.fig.add_subplot(111, projection="stereonet")
        self.ax.grid(True)
        self.canvas.mpl_connect("button_press_event", self._on_plot_click)

        # Tables
        right.addWidget(QLabel("Clustering summary (Ctrl+C copy)"))
        self.cluster_table = CopyableTableView()
        self.cluster_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cluster_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        right.addWidget(self.cluster_table, 1)

        right.addWidget(QLabel("Hypothesis tests (placeholder)"))
        self.tests_table = CopyableTableView()
        self.tests_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tests_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        right.addWidget(self.tests_table, 1)

        self._refresh_field_controls()

    def _populate_layers(self):
        self.layer_combo.clear()
        layers = [l for l in QgsProject.instance().mapLayers().values() if isinstance(l, QgsVectorLayer)]
        for lyr in layers:
            self.layer_combo.addItem(lyr.name(), lyr.id())
        self._refresh_fields()

    def _current_layer(self):
        layer_id = self.layer_combo.currentData()
        if not layer_id:
            return None
        return QgsProject.instance().mapLayer(layer_id)

    def _refresh_fields(self):
        layer = self._current_layer()
        self.field1_combo.clear()
        self.field2_combo.clear()
        if not layer:
            return
        for f in layer.fields():
            self.field1_combo.addItem(f.name())
            self.field2_combo.addItem(f.name())

    def _refresh_field_controls(self):
        is_planes = (self.data_combo.currentIndex() == 0)
        if is_planes:
            self.field1_label.setText("Dip field:")
            self.field2_label.setText("DipDir field:")
            self.plane_mode_combo.setEnabled(True)
        else:
            self.field1_label.setText("Plunge field:")
            self.field2_label.setText("Trend field:")
            self.plane_mode_combo.setEnabled(False)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select output directory", "")
        if d:
            self.out_dir.setText(d)

    def _toggle_picking(self):
        if not self.init_pick.isChecked():
            QMessageBox.information(self, "Pick medoids", "Select 'Pick medoids on plot' first.")
            return
        self._picking_enabled = not self._picking_enabled
        self.btn_pick.setText("Picking: ON" if self._picking_enabled else "Pick medoids")

    def _clear_picks(self):
        self._picked_medoid_indices = []
        self.lbl_picks.setText("Picked: 0")

    def _on_plot_click(self, event):
        if not self._picking_enabled:
            return
        if event.inaxes != self.ax:
            return
        if self._last_projected is None:
            QMessageBox.information(self, "Pick medoids", "Run analysis first (to compute point projection), then pick medoids.")
            return

        k = int(self.k_spin.value())
        if len(self._picked_medoid_indices) >= k:
            return

        x, y = float(event.xdata), float(event.ydata)
        P = self._last_projected
        d2 = (P[:, 0] - x) ** 2 + (P[:, 1] - y) ** 2
        idx = int(np.argmin(d2))
        if idx in self._picked_medoid_indices:
            return

        self._picked_medoid_indices.append(idx)
        self.lbl_picks.setText(f"Picked: {len(self._picked_medoid_indices)} / {k}")
        if len(self._picked_medoid_indices) == k:
            self._picking_enabled = False
            self.btn_pick.setText("Pick medoids")

    def _set_table(self, table_view, headers, rows):
        model = QStandardItemModel()
        model.setColumnCount(len(headers))
        model.setHorizontalHeaderLabels(headers)
        for r in rows:
            items = [QStandardItem(str(v)) for v in r]
            model.appendRow(items)
        table_view.setModel(model)
        table_view.resizeColumnsToContents()

    def _run_analysis(self):
        layer = self._current_layer()
        if layer is None:
            QMessageBox.critical(self, "Stereo GIS", "No vector layer selected.")
            return

        if not layer.selectedFeatureIds():
            QMessageBox.warning(self, "Stereo GIS", "No selected features. Select rows/features first, then run.")
            return

        is_planes = (self.data_combo.currentIndex() == 0)
        field1 = self.field1_combo.currentText()
        field2 = self.field2_combo.currentText()

        try:
            data = read_orientations_from_layer_selection(layer, is_planes, field1, field2)
            vectors_xyz = data["vectors_xyz"]
            n = vectors_xyz.shape[0]
            if n == 0:
                QMessageBox.warning(self, "Stereo GIS", "No valid orientation values in the selected features.")
                return

            trends = data["trends_deg"]
            plunges = data["plunges_deg"]

            # clear plot
            self.fig.clear()
            self.ax = self.fig.add_subplot(111, projection="stereonet")
            self.ax.grid(True)

            show_individual = self.chk_individual.isChecked()
            show_contours = self.chk_contours.isChecked()

            plane_mode = self.plane_mode_combo.currentIndex()  # 0 poles,1 gcs,2 both
            plot_poles = (not is_planes) or (plane_mode in (0, 2))
            plot_gcs = is_planes and (plane_mode in (1, 2))

            # base plot
            if show_individual and plot_poles:
                if is_planes:
                    self.ax.pole(trends, plunges, "k.", markersize=4, alpha=0.85)
                else:
                    self.ax.line(plunges, trends, "k.", markersize=4, alpha=0.85)

            if show_individual and plot_gcs:
                self.ax.plane(data["strikes_deg"], data["dips_deg"], color="0.4", linewidth=0.7, alpha=0.6)

            if show_contours:
                try:
                    self.ax.density_contourf(plunges, trends, measurement="lines", cmap="Greys", alpha=0.6, levels=int(self.contour_levels.value()))
                except TypeError:
                    self.ax.density_contourf(plunges, trends, cmap="Greys", alpha=0.6)

            # overlays
            if self.chk_vmf.isChecked():
                vmf = vmf_mean_axial(vectors_xyz)
                m = vmf["mean_xyz"]
                if np.isfinite(m).all():
                    tr, pl = xyz_to_trend_plunge(m)
                    self.ax.line(pl, tr, "r*", markersize=12)

            if self.chk_bingham.isChecked():
                b = bingham_principal_axes_axial(vectors_xyz)
                beta = b["beta_axis_xyz"]
                tr, pl = xyz_to_trend_plunge(beta)
                self.ax.line(pl, tr, "D", color="#1f77b4", markersize=7)

                dipdir = tr
                dip = 90.0 - pl
                strike = dipdir2strike(dipdir)
                self.ax.plane(strike, dip, color="#1f77b4", linewidth=1.4, alpha=0.85)

            # k-medoids
            cluster_summary = []
            if self.chk_kmedoids.isChecked():
                k = int(self.k_spin.value())
                if k > n:
                    QMessageBox.warning(self, "Stereo GIS", f"k={k} cannot exceed number of valid selected observations n={n}.")
                    return

                if self.init_pick.isChecked():
                    if len(self._picked_medoid_indices) != k:
                        QMessageBox.warning(self, "Stereo GIS", f"Pick exactly k={k} medoids on plot (picked {len(self._picked_medoid_indices)}).")
                        return
                    init_medoids = np.array(self._picked_medoid_indices, dtype=int)
                else:
                    rng = np.random.default_rng(int(self.seed_spin.value()))
                    init_medoids = rng.choice(n, size=k, replace=False)

                labels, medoids = kmedoids_pam_axial(vectors_xyz, k=k, maxiter=100, init_medoids=init_medoids)

                if self.chk_plot_clusters.isChecked():
                    cmap = plt.get_cmap("tab10")
                    for ci in range(k):
                        idx = np.where(labels == ci)[0]
                        color = cmap(ci % 10)
                        if plot_poles:
                            if is_planes:
                                self.ax.pole(trends[idx], plunges[idx], ".", color=color, markersize=6, alpha=0.9)
                            else:
                                self.ax.line(plunges[idx], trends[idx], ".", color=color, markersize=6, alpha=0.9)
                        if is_planes and plot_gcs:
                            self.ax.plane(data["strikes_deg"][idx], data["dips_deg"][idx], color=color, linewidth=1.0, alpha=0.45)

                    for ci, mi in enumerate(medoids):
                        color = cmap(ci % 10)
                        if is_planes:
                            self.ax.pole([trends[mi]], [plunges[mi]], marker="*", color=color, markersize=14, markeredgecolor="k")
                        else:
                            self.ax.line([plunges[mi]], [trends[mi]], marker="*", color=color, markersize=14, markeredgecolor="k")

                for ci in range(k):
                    idx = np.where(labels == ci)[0]
                    if idx.size == 0:
                        continue
                    vmf_c = vmf_mean_axial(vectors_xyz[idx])
                    m_tr, m_pl = xyz_to_trend_plunge(vmf_c["mean_xyz"]) if np.isfinite(vmf_c["mean_xyz"]).all() else (float("nan"), float("nan"))
                    cluster_summary.append((ci, int(idx.size), int(medoids[ci]), f"{m_tr:.2f}", f"{m_pl:.2f}", f"{vmf_c['Rbar']:.3f}", f"{vmf_c['kappa']:.3g}"))

            self.ax.set_title(f"{'Planes' if is_planes else 'Lines'} (selected n={n})")
            self.canvas.draw()

            # cache projected XY for picking
            try:
                from mplstereonet import stereonet_math
                x, y = stereonet_math.line(plunges, trends)
                self._last_projected = np.column_stack([x, y]).astype(float)
            except Exception:
                self._last_projected = None

            self._last_vectors_xyz = vectors_xyz

            self._set_table(
                self.cluster_table,
                headers=["Cluster", "n", "Medoid index", "VMF mean trend", "VMF mean plunge", "R̄", "κ≈"],
                rows=cluster_summary
            )

            self._set_table(
                self.tests_table,
                headers=["Test", "H0", "Statistic", "p-value", "Decision"],
                rows=[("Not implemented yet", "", "", "", "")]
            )

            # save only on request
            if self.chk_save.isChecked():
                out_dir = self.out_dir.text().strip()
                if not out_dir or not os.path.isdir(out_dir):
                    QMessageBox.warning(self, "Stereo GIS", "Save enabled, but output directory is invalid.")
                    return
                if self.chk_save_png.isChecked():
                    self.fig.savefig(os.path.join(out_dir, "stereonet.png"), dpi=200, bbox_inches="tight")

        except Exception as e:
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Stereo GIS", f"Error: {type(e).__name__}: {e}\n\n{tb}")