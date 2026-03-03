# gis-tools
gis-tools © 2026 by Andrea Bistacchi, released under GNU AGPLv3 license.

__Useful scripts for structural geology in QGis__

Generally QGis scripts must be placed in:
C:\Users\<your_user_name>\AppData\Roaming\QGIS\QGIS3\profiles\default\processing\scripts

- _Legend scripts_

[Legend scripts](https://github.com/gecos-lab/gis-tools/tree/master/legend_scripts) are used to automatically convert QGis legends from point to polygon layers and vice versa, keeping the same RGB color scheme. To install, download and place them in the QGis scripts folder that under Windows is C:\Users\<your user name>\AppData\Roaming\QGIS\QGIS3\profiles\default\processing\scripts. Then you will find them in the Processing Toolbox side panel under Scripts.


- _Stereo Gis plugin_

On the fly stereoplot and orientation analysis plugin. To install, first install the PackageInstallerQgis plugin by BRG, available in QGis under Plugins > Manage and Install Plugins. This is used to manage requirede libraries for this and other plugins. Then download and place the [stereo_gis folder](https://github.com/gecos-lab/gis-tools/tree/master/stereo_gis) in your QGis plugins folder, which under Windows is C:\Users\<your user name>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins. Then you will find the Stereo Gis plugin under Plugins > Manage and Install Plugins and you will be able to activate it.
