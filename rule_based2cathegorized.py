# -*- coding: utf-8 -*-
"""
Rule-based to Categorized Symbology Converter
QGIS Processing Script
"""

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterString,
    QgsProcessingOutputVectorLayer,
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsRuleBasedRenderer,
    QgsSimpleMarkerSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleFillSymbolLayer,
    QgsSvgMarkerSymbolLayer,
    QgsField,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import QVariant
import re


class RulesToCategorized(QgsProcessingAlgorithm):

    INPUT = 'INPUT'
    MODIFY_IN_PLACE = 'MODIFY_IN_PLACE'
    FALLBACK_MODE = 'FALLBACK_MODE'
    FALLBACK_FIELD = 'FALLBACK_FIELD'
    OUTPUT = 'OUTPUT'

    FALLBACK_OPTIONS = [
        'Skip complex rules (warn in log)',
        'Use rule label as category (adds virtual field)',
    ]

    def name(self):
        return 'rulestocategorized'

    def displayName(self):
        return 'Convert rule-based to categorized symbology'

    def group(self):
        return 'Symbology'

    def groupId(self):
        return 'symbology'

    def shortHelpString(self):
        return (
            "Converts rule-based symbology to categorized symbology.\n\n"
            "Handles:\n"
            "  • Simple equality rules: \"Field\" = 'value'\n"
            "  • concat()-based composite rules (extracts the varying field)\n"
            "  • ELSE / catch-all rules\n"
            "  • Nested rule trees (recursively walked)\n\n"
            "For rules that cannot be parsed automatically, two fallback modes\n"
            "are available:\n"
            "  • Skip: log a warning and ignore the rule\n"
            "  • Label field: add a '__rule_label__' virtual field and categorize\n"
            "    by rule label — preserves all symbols regardless of expression\n"
            "    complexity. Use the fallback field name to override '__rule_label__'."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT,
                'Input layer (rule-based symbology)',
                types=[QgsProcessing.TypeVectorAnyGeometry]
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.MODIFY_IN_PLACE,
                'Apply new symbology to layer (modify in place)',
                defaultValue=True
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.FALLBACK_MODE,
                'How to handle complex / unparseable rules',
                options=self.FALLBACK_OPTIONS,
                defaultValue=0
            )
        )
        p = QgsProcessingParameterString(
            self.FALLBACK_FIELD,
            'Virtual field name (used when fallback = "Use rule label")',
            defaultValue='__rule_label__',
            optional=True
        )
        self.addParameter(p)
        self.addOutput(
            QgsProcessingOutputVectorLayer(
                self.OUTPUT,
                'Layer with categorized symbology'
            )
        )

    # ------------------------------------------------------------------
    # Symbol deep clone
    # ------------------------------------------------------------------

    def clone_symbol_full(self, symbol):
        if symbol is None:
            return None
        cloned = symbol.clone()
        for i in range(cloned.symbolLayerCount()):
            sl = cloned.symbolLayer(i)
            src_sl = symbol.symbolLayer(i)
            sl.setColor(QColor(src_sl.color()))
            if hasattr(sl, 'setStrokeColor') and hasattr(src_sl, 'strokeColor'):
                sl.setStrokeColor(QColor(src_sl.strokeColor()))
            if hasattr(sl, 'setBorderColor') and hasattr(src_sl, 'borderColor'):
                sl.setBorderColor(QColor(src_sl.borderColor()))
            if hasattr(sl, 'setOpacity') and hasattr(src_sl, 'opacity'):
                sl.setOpacity(src_sl.opacity())
            if isinstance(sl, QgsSimpleMarkerSymbolLayer):
                sl.setShape(src_sl.shape())
                sl.setSize(src_sl.size())
                sl.setSizeUnit(src_sl.sizeUnit())
                sl.setAngle(src_sl.angle())
                sl.setOffset(src_sl.offset())
                sl.setOffsetUnit(src_sl.offsetUnit())
                sl.setStrokeWidth(src_sl.strokeWidth())
                sl.setStrokeWidthUnit(src_sl.strokeWidthUnit())
                sl.setStrokeStyle(src_sl.strokeStyle())
                sl.setPenJoinStyle(src_sl.penJoinStyle())
            elif isinstance(sl, QgsSvgMarkerSymbolLayer):
                sl.setPath(src_sl.path())
                sl.setSize(src_sl.size())
                sl.setSizeUnit(src_sl.sizeUnit())
                sl.setAngle(src_sl.angle())
                sl.setFillColor(QColor(src_sl.fillColor()))
                sl.setStrokeColor(QColor(src_sl.strokeColor()))
                sl.setStrokeWidth(src_sl.strokeWidth())
            elif isinstance(sl, QgsSimpleLineSymbolLayer):
                sl.setWidth(src_sl.width())
                sl.setWidthUnit(src_sl.widthUnit())
                sl.setPenStyle(src_sl.penStyle())
                sl.setPenCapStyle(src_sl.penCapStyle())
                sl.setPenJoinStyle(src_sl.penJoinStyle())
                sl.setOffset(src_sl.offset())
                sl.setOffsetUnit(src_sl.offsetUnit())
                if hasattr(src_sl, 'useCustomDashPattern') and src_sl.useCustomDashPattern():
                    sl.setUseCustomDashPattern(True)
                    sl.setCustomDashVector(src_sl.customDashVector())
                    sl.setCustomDashPatternUnit(src_sl.customDashPatternUnit())
            elif isinstance(sl, QgsSimpleFillSymbolLayer):
                sl.setBrushStyle(src_sl.brushStyle())
                sl.setStrokeWidth(src_sl.strokeWidth())
                sl.setStrokeWidthUnit(src_sl.strokeWidthUnit())
                sl.setStrokeStyle(src_sl.strokeStyle())
                sl.setPenJoinStyle(src_sl.penJoinStyle())
                sl.setOffset(src_sl.offset())
                sl.setOffsetUnit(src_sl.offsetUnit())
            for prop_key in src_sl.dataDefinedProperties().propertyKeys():
                ddp = src_sl.dataDefinedProperties().property(prop_key)
                if ddp.isActive():
                    sl.dataDefinedProperties().setProperty(prop_key, ddp)
        cloned.setOpacity(symbol.opacity())
        return cloned

    # ------------------------------------------------------------------
    # Expression parser
    # ------------------------------------------------------------------

    def parse_expression(self, expr):
        """
        Returns:
          ('__else__', None)          — ELSE / catch-all
          (field_name, value)         — simple equality "Field" = 'val'
          ('__concat__', field_name)  — concat()-based rule, returns the
                                        varying field name extracted from
                                        the concat arguments
          (None, None)                — unparseable
        """
        expr_s = (expr or "").strip()

        if not expr_s:
            return '__else__', None
        if re.fullmatch(r"(?i)['\"]?else['\"]?", expr_s):
            return '__else__', None

        # Simple equality: "Field" = 'value'  or  "Field" = 123
        m = re.fullmatch(
            r'"([^"]+)"\s*=\s*(?:\'([^\']*)\'|"([^"]*)"|([-\d.]+))',
            expr_s
        )
        if m:
            field = m.group(1)
            raw = m.group(2) or m.group(3) or m.group(4)
            try:
                value = int(raw)
            except (ValueError, TypeError):
                try:
                    value = float(raw)
                except (ValueError, TypeError):
                    value = raw
            return field, value

        # Unquoted field equality: Field = 'value'
        m2 = re.fullmatch(
            r'(\w+)\s*=\s*(?:\'([^\']*)\'|"([^"]*)"|([-\d.]+))',
            expr_s
        )
        if m2:
            field = m2.group(1)
            raw = m2.group(2) or m2.group(3) or m2.group(4)
            try:
                value = int(raw)
            except (ValueError, TypeError):
                try:
                    value = float(raw)
                except (ValueError, TypeError):
                    value = raw
            return field, value

        # concat()-based: find all field names inside concat(...)
        # e.g. concat("KIND", ', ', "MPLA_POLARITY", ', ', "DIP")
        concat_match = re.match(r'(?i)concat\s*\((.+)\)\s*(=|in)\s*', expr_s)
        if concat_match:
            concat_args = concat_match.group(1)
            # Extract all quoted field names from concat arguments
            fields_in_concat = re.findall(r'"([^"]+)"', concat_args)
            if fields_in_concat:
                # Find the field whose values actually vary across the IN list
                # by looking at which position in the concat changes
                varying = self._find_varying_concat_field(expr_s, fields_in_concat)
                return '__concat__', varying or fields_in_concat[-1]

        return None, None

    def _find_varying_concat_field(self, expr_s, fields):
        """
        Given a concat(...) IN (...) expression, parse the value list and
        find which positional slot has more than one distinct value — that
        is the "varying" field (e.g. DIP), while the others are constants.
        """
        # Extract all quoted values from the IN list
        values_match = re.search(r'(?i)\bin\s*\((.+)\)\s*$', expr_s, re.DOTALL)
        if not values_match:
            # Single equality: concat(...) = 'val'
            return fields[-1]  # assume last field varies

        raw_list = values_match.group(1)
        # Parse each quoted value tuple
        tuples = re.findall(r"'([^']*)'", raw_list)
        if not tuples:
            return fields[-1]

        # Split each tuple by ', ' to get positional slots
        split_tuples = [t.split(', ') for t in tuples]
        n_fields = len(fields)

        # Find positions with more than one distinct value
        varying_positions = []
        for pos in range(n_fields):
            vals_at_pos = set()
            for tup in split_tuples:
                if pos < len(tup):
                    vals_at_pos.add(tup[pos])
            if len(vals_at_pos) > 1:
                varying_positions.append(pos)

        if varying_positions:
            return fields[varying_positions[-1]]  # use last varying field (e.g. DIP)
        return fields[-1]

    # ------------------------------------------------------------------
    # Recursive rule walker
    # ------------------------------------------------------------------

    def collect_leaf_rules(self, rule, depth=0):
        children = rule.children()
        if not children:
            return [(rule.label(), rule.filterExpression(), rule.symbol())]
        children_have_symbols = any(c.symbol() is not None for c in children)
        if not children_have_symbols:
            return [(rule.label(), rule.filterExpression(), rule.symbol())]
        leaves = []
        for child in children:
            leaves.extend(self.collect_leaf_rules(child, depth + 1))
        return leaves

    # ------------------------------------------------------------------
    # Label-based fallback: add virtual field, categorize on it
    # ------------------------------------------------------------------

    def build_label_based_renderer(self, layer, all_leaves, field_name, feedback):
        """
        Fallback: categorize by rule label. Adds a virtual (expression)
        field that evaluates which rule label applies to each feature,
        then builds categories on that field.
        """
        # Build a CASE WHEN expression that reproduces the rule logic
        # so the virtual field returns the rule label for each feature
        case_parts = []
        for label, expr, symbol in all_leaves:
            expr_s = (expr or "").strip()
            if not expr_s or re.fullmatch(r"(?i)['\"]?else['\"]?", expr_s):
                continue  # ELSE handled as default
            safe_label = label.replace("'", "''")
            case_parts.append(f"WHEN ({expr_s}) THEN '{safe_label}'")

        if case_parts:
            case_expr = "CASE " + " ".join(case_parts) + " ELSE '' END"
        else:
            case_expr = "''"

        # Add virtual field if not already present
        fields = layer.fields()
        if fields.indexFromName(field_name) == -1:
            vf = QgsField(field_name, QVariant.String)
            layer.addExpressionField(case_expr, vf)
            feedback.pushInfo(
                f"  Added virtual field '{field_name}' with CASE expression."
            )
        else:
            feedback.pushInfo(
                f"  Virtual field '{field_name}' already exists, reusing."
            )

        # Build categories on the label field
        categories = []
        for label, expr, symbol in all_leaves:
            expr_s = (expr or "").strip()
            cloned = self.clone_symbol_full(symbol)
            if not expr_s or re.fullmatch(r"(?i)['\"]?else['\"]?", expr_s):
                cat_value = ""
            else:
                cat_value = label
            cat = QgsRendererCategory(cat_value, cloned, label, True)
            categories.append(cat)

        return QgsCategorizedSymbolRenderer(field_name, categories)

    # ------------------------------------------------------------------
    # Main processing
    # ------------------------------------------------------------------

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        modify = self.parameterAsBoolean(parameters, self.MODIFY_IN_PLACE, context)
        fallback_mode = self.parameterAsEnum(parameters, self.FALLBACK_MODE, context)
        fallback_field = self.parameterAsString(
            parameters, self.FALLBACK_FIELD, context
        ) or '__rule_label__'

        renderer = layer.renderer()
        if not isinstance(renderer, QgsRuleBasedRenderer):
            feedback.reportError(
                "The selected layer does not use rule-based symbology. Aborting.",
                fatalError=True
            )
            return {}

        root = renderer.rootRule()
        feedback.pushInfo("Walking rule tree…")
        all_leaves = []
        for top_rule in root.children():
            all_leaves.extend(self.collect_leaf_rules(top_rule))
        feedback.pushInfo(f"Found {len(all_leaves)} leaf rules.")

        # ---- Attempt normal parse first ----
        categories = []
        field_names = []
        skipped = []
        all_complex = True  # will be set False if any rule parses normally

        for i, (label, expr, symbol) in enumerate(all_leaves):
            feedback.setProgress(int(i / max(len(all_leaves), 1) * 100))
            if feedback.isCanceled():
                break

            label = label or expr or f"(rule {i+1})"
            field, value = self.parse_expression(expr)

            if field is None:
                skipped.append((label, expr, symbol))
                feedback.pushWarning(
                    f"  Cannot parse '{label}': {expr!r}"
                )
                continue

            if field == '__else__':
                cloned = self.clone_symbol_full(symbol)
                cat = QgsRendererCategory("", cloned, label, True)
                categories.append(cat)
                feedback.pushInfo(f"  ELSE rule → '{label}'")
                continue

            if field == '__concat__':
                # value holds the varying field name
                varying_field = value
                feedback.pushInfo(
                    f"  concat() rule '{label}': maps to varying field '{varying_field}'"
                )
                if varying_field not in field_names:
                    field_names.append(varying_field)
                # For concat rules we cannot reliably map to a single value,
                # so treat as skipped for categorized, but note the field
                skipped.append((label, expr, symbol))
                continue

            all_complex = False
            cloned = self.clone_symbol_full(symbol)
            if field not in field_names:
                field_names.append(field)
            cat = QgsRendererCategory(value, cloned, label, True)
            categories.append(cat)
            feedback.pushInfo(
                f"  OK  '{label}' → field={field!r}  value={value!r}"
            )

        # ---- Decide outcome ----

        # Case A: all rules are concat()/complex — use label fallback if chosen
        if not field_names and fallback_mode == 1:
            feedback.pushInfo(
                "\nNo simple equality rules found. "
                f"Falling back to label-based categorization on '{fallback_field}'."
            )
            new_renderer = self.build_label_based_renderer(
                layer, all_leaves, fallback_field, feedback
            )
            if modify:
                layer.setRenderer(new_renderer)
                layer.triggerRepaint()
                feedback.pushInfo(
                    f"Done. Label-based categorized renderer applied on "
                    f"'{fallback_field}' — {len(all_leaves)} categories."
                )
            return {self.OUTPUT: layer.id()}

        # Case B: no parseable field at all and fallback is Skip → hard error
        if not field_names:
            feedback.reportError(
                "No parseable field name found in any rule.\n\n"
                "This layer uses concat()-based or other complex expressions.\n"
                "Switch the fallback mode to 'Use rule label as category' to\n"
                "convert it anyway by categorizing on the rule label.\n\n"
                "Rule expressions found:\n" +
                "\n".join(f"  '{lbl}': {ex!r}" for lbl, ex, _ in all_leaves),
                fatalError=True
            )
            return {}

        # Case C: some rules parsed, some skipped — report and continue
        if skipped:
            if fallback_mode == 1:
                feedback.pushInfo(
                    f"\n{len(skipped)} complex rule(s) could not be parsed as simple "
                    f"equality. Adding them via label fallback on '{fallback_field}'."
                )
                for lbl, ex, sym in skipped:
                    safe_lbl = lbl.replace("'", "''")
                    cloned = self.clone_symbol_full(sym)
                    cat = QgsRendererCategory(lbl, cloned, lbl, True)
                    categories.append(cat)
            else:
                feedback.pushWarning(
                    f"\n{len(skipped)} rule(s) skipped (complex expressions):"
                )
                for lbl, ex, _ in skipped:
                    feedback.pushWarning(f"  '{lbl}': {ex!r}")

        if len(set(field_names)) > 1:
            feedback.pushWarning(
                f"Multiple fields detected: {set(field_names)}. "
                f"Using first: '{field_names[0]}'"
            )

        target_field = field_names[0]
        new_renderer = QgsCategorizedSymbolRenderer(target_field, categories)

        if modify:
            layer.setRenderer(new_renderer)
            layer.triggerRepaint()
            feedback.pushInfo(
                f"\nDone. Categorized renderer applied on field '{target_field}' "
                f"— {len(categories)} categories"
                + (f", {len(skipped)} skipped." if skipped else ".")
            )

        return {self.OUTPUT: layer.id()}

    def createInstance(self):
        return RulesToCategorized()