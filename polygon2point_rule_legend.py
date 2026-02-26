# polygon2point_rule_legend.py
# @ Andrea Bistacchi 2024-06-26
"""
Use this script to convert the rule-symbol legend of a polygon layer into a legend with square markers
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
    QgsProcessingException,
    QgsMarkerSymbol,
    QgsSingleSymbolRenderer,
    QgsRuleBasedRenderer,
    Qgis,
)


class PolygonRuleLegendToPointRuleLegend(QgsProcessingAlgorithm):
    POLYGON = "POLYGON"
    POINT = "POINT"
    SIZE_PT = "SIZE_PT"
    OUTLINE_COLOR = "OUTLINE_COLOR"
    OUTLINE_WIDTH = "OUTLINE_WIDTH"

    def name(self):
        return "polygon_rule_legend_to_point_rule_legend"

    def displayName(self):
        return "Polygon rule-based legend → Point rule-based legend (square markers)"

    def group(self):
        return "Symbology"

    def groupId(self):
        return "symbology"

    def shortHelpString(self):
        return (
            "Copies a *rule-based* renderer from a polygon layer to a point layer.\n"
            "Each polygon rule symbol is converted to a square marker symbol using the same fill color.\n\n"
            "Note: This tool updates the *style of an existing point layer in your project*."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.POLYGON,
                "Polygon layer (source style, rule-based)",
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

    def _square_marker(self, fill_color: QColor, size_pt: float, outline_color: QColor, outline_width_pt: float):
        marker = QgsMarkerSymbol.createSimple(
            {
                "name": "square",
                "color": fill_color.name(),
                "outline_color": outline_color.name(),
            }
        )
        marker.setSize(size_pt)
        marker.setSizeUnit(Qgis.RenderUnit.Points)

        sl = marker.symbolLayer(0)
        if sl is not None:
            try:
                sl.setStrokeWidth(outline_width_pt)
                sl.setStrokeWidthUnit(Qgis.RenderUnit.Points)
            except Exception:
                pass

        return marker

    def _convert_rule_tree(self, src_rule: QgsRuleBasedRenderer.Rule, size_pt, outline_color, outline_width):
        """
        Recursively clones a rule and replaces its symbol with a square marker using the source symbol fill color.
        """
        # Clone metadata (label, filter, else, active, etc.)
        new_rule = QgsRuleBasedRenderer.Rule(None)
        new_rule.setLabel(src_rule.label())
        new_rule.setFilterExpression(src_rule.filterExpression())
        new_rule.setDescription(src_rule.description())
        new_rule.setActive(src_rule.active())

        # QGIS API: setElse() vs setIsElse() (varies by version/build)
        try:
            new_rule.setIsElse(src_rule.isElse())
        except AttributeError:
            new_rule.setElse(src_rule.isElse())

        try:
            new_rule.setCheckState(src_rule.checkState())
        except Exception:
            pass

        # Convert symbol (only if the rule has one)
        src_symbol = src_rule.symbol()
        if src_symbol is not None:
            fill = src_symbol.color()
            new_rule.setSymbol(self._square_marker(fill, size_pt, outline_color, outline_width))
        else:
            new_rule.setSymbol(None)

        # Recurse into children
        for child in src_rule.children():
            new_rule.appendChild(self._convert_rule_tree(child, size_pt, outline_color, outline_width))

        return new_rule

    def processAlgorithm(self, parameters, context, feedback):
        poly_layer = self.parameterAsVectorLayer(parameters, self.POLYGON, context)
        pt_layer = self.parameterAsVectorLayer(parameters, self.POINT, context)
        size_pt = self.parameterAsDouble(parameters, self.SIZE_PT, context)
        outline_color = self.parameterAsColor(parameters, self.OUTLINE_COLOR, context)
        outline_width = self.parameterAsDouble(parameters, self.OUTLINE_WIDTH, context)

        if poly_layer is None or pt_layer is None:
            raise QgsProcessingException("Invalid input layer(s).")

        src_renderer = poly_layer.renderer()
        if src_renderer is None:
            raise QgsProcessingException("Polygon layer has no renderer.")

        if src_renderer.type() != "RuleRenderer":
            raise QgsProcessingException(
                f"Unsupported renderer type: {src_renderer.type()}. This tool requires a rule-based renderer."
            )

        src_rule_renderer = src_renderer  # QgsRuleBasedRenderer
        src_root = src_rule_renderer.rootRule()
        if src_root is None:
            raise QgsProcessingException("Rule-based renderer has no root rule.")

        new_root = self._convert_rule_tree(src_root, size_pt, outline_color, outline_width)

        # Build and apply new renderer
        new_renderer = QgsRuleBasedRenderer(new_root)

        # Safety: QGIS expects a symbol for some render paths; if root has none and no children, fallback
        if new_root.symbol() is None and len(new_root.children()) == 0:
            fallback = self._square_marker(QColor("gray"), size_pt, outline_color, outline_width)
            pt_layer.setRenderer(QgsSingleSymbolRenderer(fallback))
        else:
            pt_layer.setRenderer(new_renderer)

        pt_layer.triggerRepaint()
        feedback.pushInfo("Applied rule-based renderer to point layer.")
        return {"UPDATED_LAYER": pt_layer.id()}

    def createInstance(self):
        return PolygonRuleLegendToPointRuleLegend()