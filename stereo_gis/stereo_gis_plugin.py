# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon

from .stereo_gis_dialog import StereoGisDialog


class StereoGisPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dlg = None

    def initGui(self):
        self.action = QAction(QIcon(), "Stereo GIS", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("Stereo GIS", self.action)

    def unload(self):
        if self.action:
            self.iface.removePluginMenu("Stereo GIS", self.action)
            self.action = None

    def run(self):
        if self.dlg is None:
            self.dlg = StereoGisDialog(self.iface)
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()