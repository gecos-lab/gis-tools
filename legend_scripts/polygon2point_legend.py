# polygon2point_legend.py
# @ Andrea Bistacchi 2024-06-26
"""
Use this script to convert the legend of a polygon layer into a legend with square markers
for a point layer, keeping the same RGB colors for the same codes in the attribute table.

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
    QgsProcessingParameterString,
    QgsProcessingException,
    QgsProcessingParameterField,
    QgsMarkerSymbol,
    QgsRendererCategory,
    QgsCategorizedSymbolRenderer,
    QgsSingleSymbolRenderer,
    Qgis,
)


class PolygonLegendToPointLegend(QgsProcessingAlgorithm):
    """
    Copies polygon layer symbology (single or categorized) to a point layer,
    using square markers with the same fill RGB and a configurable size in points.
    """

    POLYGON = "POLYGON"
    POINT = "POINT"
    SIZE_PT = "SIZE_PT"
    OUTLINE_COLOR = "OUTLINE_COLOR"
    OUTLINE_WIDTH = "OUTLINE_WIDTH"
    TARGET_FIELD = "TARGET_FIELD"

    def name(self):
        return "polygon_legend_to_point_legend"

    def displayName(self):
        return "Polygon legend → Point legend (square markers)"

    def group(self):
        return "Symbology"

    def groupId(self):
        return "symbology"

    def shortHelpString(self):
        return (
            "Takes the renderer from a polygon layer (single symbol or categorized) and applies an "
            "equivalent renderer to a point layer, using square markers with the same fill color.\n\n"
            "Note: This tool updates the *style of an existing point layer in your project*."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.POLYGON,
                "Polygon layer (source style)",
                types=[QgsProcessing.TypeVectorPolygon],
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.POINT,
                "Point layer (apply style to)",
                types=[QgsProcessing.TypeVectorPoint],
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SIZE_PT,
                "Marker size (points)",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=10.0,
                minValue=0.1,
            )
        )
        self.addParameter(
            QgsProcessingParameterColor(
                self.OUTLINE_COLOR,
                "Marker outline color",
                defaultValue=QColor("black"),
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.OUTLINE_WIDTH,
                "Marker outline width (points)",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.2,
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.TARGET_FIELD,
                "Target layer field for categories (optional; leave empty to use polygon renderer field)",
                parentLayerParameterName=self.POINT,  # makes it a dropdown from the point layer
                optional=True,
                allowMultiple=False,
                defaultValue=None,
            )
        )

    def _square_marker(self, fill_color: QColor, size_pt: float, outline_color: QColor, outline_width_pt: float):
        marker = QgsMarkerSymbol.createSimple(
            {
                "name": "square",
                "color": fill_color.name(),  # keeps RGB; alpha is applied via setOpacity if needed
                "outline_color": outline_color.name(),
            }
        )
        marker.setSize(size_pt)
        marker.setSizeUnit(Qgis.RenderUnit.Points)

        # Outline width: set via symbol layer if available; fall back silently if not
        sl = marker.symbolLayer(0)
        if sl is not None:
            try:
                sl.setStrokeWidth(outline_width_pt)
                sl.setStrokeWidthUnit(Qgis.RenderUnit.Points)
            except Exception:
                pass

        return marker

    def processAlgorithm(self, parameters, context, feedback):
        poly_layer = self.parameterAsVectorLayer(parameters, self.POLYGON, context)
        pt_layer = self.parameterAsVectorLayer(parameters, self.POINT, context)

        size_pt = self.parameterAsDouble(parameters, self.SIZE_PT, context)
        outline_color = self.parameterAsColor(parameters, self.OUTLINE_COLOR, context)
        outline_width = self.parameterAsDouble(parameters, self.OUTLINE_WIDTH, context)
        target_field = (self.parameterAsString(parameters, self.TARGET_FIELD, context) or "").strip()

        if poly_layer is None or pt_layer is None:
            raise QgsProcessingException("Invalid input layer(s).")

        poly_renderer = poly_layer.renderer()
        if poly_renderer is None:
            raise QgsProcessingException("Polygon layer has no renderer.")

        rtype = poly_renderer.type()
        feedback.pushInfo(f"Polygon renderer type: {rtype}")

        if rtype == "singleSymbol":
            fill = poly_renderer.symbol().color()
            marker = self._square_marker(fill, size_pt, outline_color, outline_width)
            pt_layer.setRenderer(QgsSingleSymbolRenderer(marker))
            pt_layer.triggerRepaint()
            return {"UPDATED_LAYER": pt_layer.id()}

        if rtype == "categorizedSymbol":
            field_name = target_field if target_field else poly_renderer.classAttribute()
            if not field_name:
                raise QgsProcessingException(
                    "Could not determine the categorized field (and no target field selected).")

            categories = []
            for cat in poly_renderer.categories():
                fill = cat.symbol().color()
                marker = self._square_marker(fill, size_pt, outline_color, outline_width)
                categories.append(QgsRendererCategory(cat.value(), marker, cat.label()))

            pt_layer.setRenderer(QgsCategorizedSymbolRenderer(field_name, categories))
            pt_layer.triggerRepaint()
            return {"UPDATED_LAYER": pt_layer.id()}

        raise QgsProcessingException(
            f"Unsupported polygon renderer type: {rtype}. "
            "This script supports only 'singleSymbol' and 'categorizedSymbol'."
        )

    def createInstance(self):
        return PolygonLegendToPointLegend()