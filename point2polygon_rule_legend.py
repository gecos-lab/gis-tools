# point2polygon_rule_legend.py
# @ Andrea Bistacchi 2024-06-26
"""
Use this script to convert the legend of a point layer with square markers and RGB fill colors into a rule-symbol
legend for a polygon layer, keeping the same RGB colors for the same codes in the attribute table.

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
    QgsFillSymbol,
    QgsSingleSymbolRenderer,
    QgsRuleBasedRenderer,
    Qgis,
)


class PointRuleLegendToPolygonRuleLegend(QgsProcessingAlgorithm):
    POINT = "POINT"
    POLYGON = "POLYGON"
    OUTLINE_COLOR = "OUTLINE_COLOR"
    OUTLINE_WIDTH = "OUTLINE_WIDTH"

    def name(self):
        return "point_rule_legend_to_polygon_rule_legend"

    def displayName(self):
        return "Point rule-based legend → Polygon rule-based legend (simple fill)"

    def group(self):
        return "Symbology"

    def groupId(self):
        return "symbology"

    def shortHelpString(self):
        return (
            "Copies a *rule-based* renderer from a point layer to a polygon layer.\n"
            "Each point rule symbol is converted to a polygon fill symbol using the same color.\n\n"
            "Note: This tool updates the *style of an existing polygon layer in your project*."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.POINT,
                "Point layer (source style, rule-based)",
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

    def _fill_symbol(self, fill_color: QColor, outline_color: QColor, outline_width_pt: float):
        fill = QgsFillSymbol.createSimple(
            {
                "color": fill_color.name(),
                "outline_color": outline_color.name(),
            }
        )

        sl = fill.symbolLayer(0)
        if sl is not None:
            try:
                sl.setStrokeWidth(outline_width_pt)
                sl.setStrokeWidthUnit(Qgis.RenderUnit.Points)
            except Exception:
                pass

        return fill

    def _convert_rule_tree(self, src_rule: QgsRuleBasedRenderer.Rule, outline_color, outline_width):
        """
        Recursively clones a rule and replaces its symbol with a fill symbol using the source symbol color.
        """
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

        src_symbol = src_rule.symbol()
        if src_symbol is not None:
            color = src_symbol.color()
            new_rule.setSymbol(self._fill_symbol(color, outline_color, outline_width))
        else:
            new_rule.setSymbol(None)

        for child in src_rule.children():
            new_rule.appendChild(self._convert_rule_tree(child, outline_color, outline_width))

        return new_rule

    def processAlgorithm(self, parameters, context, feedback):
        pt_layer = self.parameterAsVectorLayer(parameters, self.POINT, context)
        poly_layer = self.parameterAsVectorLayer(parameters, self.POLYGON, context)
        outline_color = self.parameterAsColor(parameters, self.OUTLINE_COLOR, context)
        outline_width = self.parameterAsDouble(parameters, self.OUTLINE_WIDTH, context)

        if pt_layer is None or poly_layer is None:
            raise QgsProcessingException("Invalid input layer(s).")

        src_renderer = pt_layer.renderer()
        if src_renderer is None:
            raise QgsProcessingException("Point layer has no renderer.")

        if src_renderer.type() != "RuleRenderer":
            raise QgsProcessingException(
                f"Unsupported renderer type: {src_renderer.type()}. This tool requires a rule-based renderer."
            )

        src_rule_renderer = src_renderer  # QgsRuleBasedRenderer
        src_root = src_rule_renderer.rootRule()
        if src_root is None:
            raise QgsProcessingException("Rule-based renderer has no root rule.")

        new_root = self._convert_rule_tree(src_root, outline_color, outline_width)
        new_renderer = QgsRuleBasedRenderer(new_root)

        if new_root.symbol() is None and len(new_root.children()) == 0:
            fallback = self._fill_symbol(QColor("gray"), outline_color, outline_width)
            poly_layer.setRenderer(QgsSingleSymbolRenderer(fallback))
        else:
            poly_layer.setRenderer(new_renderer)

        poly_layer.triggerRepaint()
        feedback.pushInfo("Applied rule-based renderer to polygon layer.")
        return {"UPDATED_LAYER": poly_layer.id()}

    def createInstance(self):
        return PointRuleLegendToPolygonRuleLegend()