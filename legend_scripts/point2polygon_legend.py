# point2polygon_legend.py
# @ Andrea Bistacchi 2024-06-26
"""
Use this script to convert the legend of a point layer with square markers and RGB fill colors into a legend
for a polygon layer, keeping the same RGB colors for the same codes in the attribute table.

TO use it as a Processing Script with GUI (drop-in) in QGIS:

Processing → Toolbox
In the toolbox panel: Scripts → Tools → Create New Script
Paste the code below
Save as e.g. polygon_legend_to_point_legend.py
It will appear under Processing Toolbox → Scripts.
"""

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterColor,
    QgsProcessingParameterField,
    QgsProcessingException,
    QgsFillSymbol,
    QgsRendererCategory,
    QgsCategorizedSymbolRenderer,
    QgsSingleSymbolRenderer,
    Qgis,
)


class PointLegendToPolygonLegend(QgsProcessingAlgorithm):
    """
    Copies point layer symbology (single or categorized) to a polygon layer,
    using fill symbols with the same RGB colors as the point markers.
    """

    POINT = "POINT"
    POLYGON = "POLYGON"
    OUTLINE_COLOR = "OUTLINE_COLOR"
    OUTLINE_WIDTH = "OUTLINE_WIDTH"
    TARGET_FIELD = "TARGET_FIELD"

    def name(self):
        return "point_legend_to_polygon_legend"

    def displayName(self):
        return "Point legend → Polygon legend (fill symbols)"

    def group(self):
        return "Symbology"

    def groupId(self):
        return "symbology"

    def shortHelpString(self):
        return (
            "Takes the renderer from a point layer (single symbol or categorized) and applies an "
            "equivalent renderer to a polygon layer, using fill symbols with the same colors.\n\n"
            "Note: This tool updates the *style of an existing polygon layer in your project*."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.POINT,
                "Point layer (source style)",
                types=[QgsProcessing.TypeVectorPoint],
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.POLYGON,
                "Polygon layer (apply style to)",
                types=[QgsProcessing.TypeVectorPolygon],
            )
        )
        self.addParameter(
            QgsProcessingParameterColor(
                self.OUTLINE_COLOR,
                "Polygon outline color",
                defaultValue=QColor("black"),
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.OUTLINE_WIDTH,
                "Polygon outline width (points)",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.2,
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.TARGET_FIELD,
                "Target polygon field for categories (optional; leave empty to use point renderer field)",
                parentLayerParameterName=self.POLYGON,  # dropdown from polygon fields
                optional=True,
                allowMultiple=False,
                defaultValue=None,
            )
        )

    def _fill_symbol_from_color(self, fill_color: QColor, outline_color: QColor, outline_width_pt: float):
        sym = QgsFillSymbol.createSimple(
            {
                "color": fill_color.name(),
                "outline_color": outline_color.name(),
            }
        )

        sl = sym.symbolLayer(0)
        if sl is not None:
            try:
                sl.setStrokeWidth(outline_width_pt)
                sl.setStrokeWidthUnit(Qgis.RenderUnit.Points)
            except Exception:
                pass

        return sym

    def processAlgorithm(self, parameters, context, feedback):
        pt_layer = self.parameterAsVectorLayer(parameters, self.POINT, context)
        poly_layer = self.parameterAsVectorLayer(parameters, self.POLYGON, context)

        outline_color = self.parameterAsColor(parameters, self.OUTLINE_COLOR, context)
        outline_width = self.parameterAsDouble(parameters, self.OUTLINE_WIDTH, context)
        target_field = (self.parameterAsString(parameters, self.TARGET_FIELD, context) or "").strip()

        if pt_layer is None or poly_layer is None:
            raise QgsProcessingException("Invalid input layer(s).")

        pt_renderer = pt_layer.renderer()
        if pt_renderer is None:
            raise QgsProcessingException("Point layer has no renderer.")

        rtype = pt_renderer.type()
        feedback.pushInfo(f"Point renderer type: {rtype}")

        # Single symbol → Single symbol fill
        if rtype == "singleSymbol":
            fill = pt_renderer.symbol().color()
            poly_sym = self._fill_symbol_from_color(fill, outline_color, outline_width)

            poly_layer.setRenderer(QgsSingleSymbolRenderer(poly_sym))
            poly_layer.triggerRepaint()
            return {"UPDATED_LAYER": poly_layer.id()}

        # Categorized → Categorized
        if rtype == "categorizedSymbol":
            field_name = target_field if target_field else pt_renderer.classAttribute()
            if not field_name:
                raise QgsProcessingException(
                    "Could not determine the categorized field (and no target polygon field selected)."
                )

            categories = []
            for cat in pt_renderer.categories():
                fill = cat.symbol().color()
                poly_sym = self._fill_symbol_from_color(fill, outline_color, outline_width)
                categories.append(QgsRendererCategory(cat.value(), poly_sym, cat.label()))

            poly_layer.setRenderer(QgsCategorizedSymbolRenderer(field_name, categories))
            poly_layer.triggerRepaint()
            return {"UPDATED_LAYER": poly_layer.id()}

        raise QgsProcessingException(
            f"Unsupported point renderer type: {rtype}. "
            "This script supports only 'singleSymbol' and 'categorizedSymbol'."
        )

    def createInstance(self):
        return PointLegendToPolygonLegend()