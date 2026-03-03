# -*- coding: utf-8 -*-

def classFactory(iface):
    from .stereo_gis_plugin import StereoGisPlugin
    return StereoGisPlugin(iface)