import os, glob, requests
from qgis.PyQt.QtGui import QFont, QColor
from qgis.PyQt.QtWidgets import QFileDialog, QDockWidget
from qgis.PyQt.QtXml import QDomDocument
from qgis.PyQt.QtCore import QVariant
from qgis.utils import iface, plugins
from qgis import processing
from qgis.core import (
    QgsLayerTreeGroup, QgsLayoutItemMapGrid,
    QgsLayerTreeLayer, QgsUnitTypes, Qgis,
    QgsLayoutItemScaleBar, QgsDistanceArea, QgsFillSymbol,
    QgsSingleSymbolRenderer, QgsLayoutItemMap,
    QgsLegendStyle, QgsLayoutItemLabel,
    QgsCoordinateReferenceSystem, QgsLayoutSize,
    QgsProject, QgsMapLayer, QgsMapLayerLegendUtils,
    QgsVectorLayer, QgsPrintLayout,
    QgsReadWriteContext, QgsLayoutItemLegend,
    QgsLayoutPoint, QgsScaleBarSettings, QgsWkbTypes,
    QgsRenderContext, QgsInvertedPolygonRenderer,
    QgsField, QgsFeature, QgsVectorFileWriter,
    QgsRasterLayer, QgsCategorizedSymbolRenderer, QgsGraduatedSymbolRenderer
)
class LayerLoader:
    def __init__(self):
        self.geopackage_layer = None
        self.selected_file_path = None
        # Mantener EPSG:5361 como CRS objetivo de trabajo
        self.target_crs = QgsCoordinateReferenceSystem('EPSG:5361')
        self.current_layout = None  # mantener referencia para evitar GC
        self.map_scale = 8000
    def add_layer_to_group(self, layer, group_name):
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(group_name)
        if not group:
            group = root.addGroup(group_name)
        QgsProject.instance().addMapLayer(layer, False)
        group.addLayer(layer)
    def find_layer_in_group(self, group_name, layer_name):
        """
        Busca una capa por nombre exacto dentro de un grupo. Si no encuentra, intenta
        una búsqueda por subcadena (case-insensitive) y devuelve la primera coincidencia.
        """
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(group_name)
        if group is not None:
            # búsqueda exacta
            for layer in group.findLayers():
                if layer.name() == layer_name:
                    return layer.layer()
            # búsqueda por subcadena (case-insensitive)
            lname_lower = layer_name.lower()
            for layer in group.findLayers():
                if lname_lower in layer.name().lower():
                    print(f"find_layer_in_group: matched by substring -> '{layer.name()}'")
                    return layer.layer()
        return None
    def select_and_load_geopackage(self):
        file_path = QFileDialog.getOpenFileName(None, 'Seleccionar poligono MCT', '', 'Archivos vectoriales (*.*)')[0]
        if not file_path:
            print('No se seleccionó ningún archivo')
            return
        self.selected_file_path = file_path
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        layer = QgsVectorLayer(file_path, base_name, 'ogr')
        if not layer.isValid():
            print(f'La capa no es válida! Error posible con el driver OGR para {file_path}')
            return
        # eliminar columna 'fid' si existe
        if 'fid' in [f.name() for f in layer.fields()]:
            try:
                layer.dataProvider().deleteAttributes([layer.fields().indexFromName('fid')])
                layer.updateFields()
                print('Columna "fid" eliminada.')
            except Exception as e:
                print(f"No fue posible eliminar campo 'fid': {e}")
        # Reproyectar a CRS objetivo (self.target_crs) si es distinto
        if layer.crs() != self.target_crs:
            params = {'INPUT': layer, 'TARGET_CRS': self.target_crs, 'OUTPUT': 'memory:'}
            result = processing.run('qgis:reprojectlayer', params)
            layer = result['OUTPUT']
            layer.setName(base_name + "_proj")
            print(f"Layer reproyectada a {self.target_crs.authid()}")
        # Si tiene >1 feature, dissolve para obtener un polígono único
        if layer.featureCount() > 1:
            params = {'INPUT': layer, 'FIELD': [], 'OUTPUT': 'memory:'}
            result = processing.run('native:dissolve', params)
            layer = result['OUTPUT']
            layer.setName(base_name + "_dissolve")
            print("Se hizo dissolve para unir features en un único polígono.")
        # medir área y escoger escala (usar target_crs para medidas)
        distance_area = QgsDistanceArea()
        distance_area.setSourceCrs(self.target_crs, QgsProject.instance().transformContext())
        distance_area.setEllipsoid(QgsProject.instance().ellipsoid())
        area_ha = 0
        for feat in layer.getFeatures():
            try:
                # si la geometría está en target_crs, medir directo
                area_m2 = distance_area.measureArea(feat.geometry())
            except Exception:
                area_m2 = 0
            area_ha += area_m2 / 10000.0
        if area_ha > 3000:
            self.map_scale = 100000
        elif area_ha > 20:
            self.map_scale = 70000
        else:
            self.map_scale = 8000
        print(f"Área del polígono: {area_ha:.2f} ha (escala {self.map_scale})")
        # guardar en memoria como la capa "maestra" en target_crs
        mem_layer = QgsVectorLayer("Polygon?crs={}".format(self.target_crs.authid()), base_name + "-", "memory")
        prov = mem_layer.dataProvider()
        prov.addAttributes(layer.fields())
        mem_layer.updateFields()
        for feat in layer.getFeatures():
            prov.addFeature(feat)
        mem_layer.updateExtents()
        self.geopackage_layer = mem_layer
        # renderer invertido y añadir al grupo
        base_symbol = QgsFillSymbol.createSimple({'color': '255,255,255,50', 'outline_color': '#0059ff', 'outline_width': '0.99'})
        base_renderer = QgsSingleSymbolRenderer(base_symbol)
        renderer = QgsInvertedPolygonRenderer(base_renderer)
        try:
            base_symbol.setColor(QColor.fromRgb(255, 255, 255))
            base_symbol.setOpacity(0.35)
        except Exception:
            pass
        self.geopackage_layer.setRenderer(renderer)
        self.add_layer_to_group(self.geopackage_layer, "Deslinde AT")
        print("Capa de entrada preparada y añadida al proyecto.")
    def load_layers_from_selected_folder(self):
        ruta_capas = QFileDialog.getExistingDirectory(None, "Seleccionar un directorio donde estan las variables")
        extension_de_busqueda = ".gpkg"
        root = QgsProject.instance().layerTreeRoot()
        lista_archivos = [f.name for f in os.scandir(ruta_capas) if f.is_file() and f.name.endswith(extension_de_busqueda)]
        for f in lista_archivos:
            file_name, file_ext = os.path.splitext(f)
            abs_path = os.path.join(ruta_capas, f)
            print(f)
            layer = QgsVectorLayer(abs_path, file_name, 'ogr')
            point_layers = []
            line_layers = []
            polygon_layers = []
            if layer.isValid():
                sublayers = layer.dataProvider().subLayers()
                for sublayer in sublayers:
                    name = sublayer.split('!!::!!')[1]
                    uri = f"{abs_path}|layername={name}"
                    sub_vlayer = QgsVectorLayer(uri, name, 'ogr')
                    sub_vlayer.setOpacity(0.9)
                    qml_path = f"/ruta/a/los/archivos/qml/{name}.qml"
                    if os.path.exists(qml_path):
                        sub_vlayer.loadNamedStyle(qml_path)
                    geometry_type = sub_vlayer.geometryType()
                    if geometry_type == QgsWkbTypes.PointGeometry:
                        point_layers.append(sub_vlayer)
                    elif geometry_type == QgsWkbTypes.LineGeometry:
                        line_layers.append(sub_vlayer)
                    elif geometry_type == QgsWkbTypes.PolygonGeometry:
                        polygon_layers.append(sub_vlayer)
                ordered_layers = point_layers + line_layers + polygon_layers
                for layer in ordered_layers:
                    self.add_layer_to_group(layer, file_name)
    def load_template_from_url(self, template_urls):
        for template_url in template_urls:
            try:
                response = requests.get(template_url, verify=False, timeout=15)
            except Exception as e:
                print(f"Error descargando {template_url}: {e}")
                continue
            if response.status_code == 200:
                template_content = response.text
                try:
                    self.load_template_content(template_content)
                    print(f"Plantilla cargada desde: {template_url}")
                    break
                except Exception as e:
                    print(f"Error al cargar plantilla desde {template_url}: {e}")
            else:
                print(f'Error al obtener el archivo QPT desde la URL: {template_url} (status {response.status_code})')
    def load_template_content(self, template_content):
        myDocument = QDomDocument()
        if not myDocument.setContent(template_content):
            raise RuntimeError("No se pudo parsear el contenido QPT (QDomDocument.setContent returned False).")
        project = QgsProject.instance()
        manager = project.layoutManager()
        base_name = "ImportedTemplate"
        name = base_name
        counter = 1
        while manager.layoutByName(name):
            counter += 1
            name = f"{base_name}_{counter}"
        new_layout = QgsPrintLayout(project)
        new_layout.setName(name)
        try:
            ctx = QgsReadWriteContext()
            new_layout.loadFromTemplate(myDocument, ctx)
        except Exception as e:
            raise RuntimeError(f"loadFromTemplate falló: {e}")
        manager.addLayout(new_layout)
        self.current_layout = new_layout
        map_item = new_layout.itemById('Mapa 3')
        if not map_item:
            ids = [item.id() for item in new_layout.items()]
            raise RuntimeError(f"No se encontró un mapa con ID 'Mapa 3' en la plantilla. IDs disponibles: {ids}")
        new_map = QgsLayoutItemMap(new_layout)
        new_map.attemptMove(map_item.positionWithUnits())
        new_map.attemptResize(map_item.sizeWithUnits())
        new_layout.addLayoutItem(new_map)
        # Usar target_crs para el mapa del layout
        new_map.setCrs(self.target_crs)
        canvas = iface.mapCanvas()
        try:
            new_map.setExtent(canvas.extent())
        except Exception:
            pass
        new_map.attemptResize(map_item.sizeWithUnits())
        new_map.setScale(getattr(self, 'map_scale', new_map.scale()))
        # --- Inicio: bloque corregido para info_label, scalebar y grid (usa new_layout / mm) ---
        font = QFont()
        font.setPointSize(7)
        # Escala gráfica
        scalebar = QgsLayoutItemScaleBar(new_layout)
        scalebar.setLinkedMap(new_map)
        if getattr(self, 'map_scale', 8000) <= 8900:
            scalebar.setUnits(QgsUnitTypes.DistanceMeters)
            scalebar.setNumberOfSegments(2)
            scalebar.setUnitsPerSegment(100.0)
            scalebar.setUnitLabel('m')
        else:
            scalebar.setUnits(QgsUnitTypes.DistanceKilometers)
            scalebar.setNumberOfSegments(2)
            scalebar.setUnitsPerSegment(1.0)
            scalebar.setUnitLabel('km')
        scale_label = QgsLayoutItemLabel(new_layout)
        scale_label.setText(f"1:{new_map.scale():,.0f}")
        scale_label.setFont(font)
        scale_label.adjustSizeToText()
        info_label = QgsLayoutItemLabel(new_layout)
        info_label.setId('INFO ADMINISTRATIVO')
        info_label.setText(f"Región: \nProvincia: \nComuna: \nLugar: ")
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup("01. Contexto territorial")
        if group:
            layer = None
            for child in group.children():
                if isinstance(child, QgsLayerTreeLayer) and child.name() == "Comunas":
                    layer = child.layer()
                    break
            if layer and self.geopackage_layer:
                try:
                    original_selection = layer.selectedFeatureIds()
                    params = {'INPUT': layer,'PREDICATE': [0],'INTERSECT': self.geopackage_layer,'METHOD': 0}
                    processing.run('native:selectbylocation', params)
                    selected_features = layer.selectedFeatures()
                    if selected_features:
                        feature = selected_features[0]
                        def get_attr(feat, name):
                            idx = feat.fields().indexFromName(name)
                            return feat.attribute(idx) if idx != -1 else ''
                        region = get_attr(feature, "REGION")
                        provincia = get_attr(feature, "PROVINCIA")
                        comuna = get_attr(feature, "COMUNA")
                        info_label.setText(f"Región: {region}\nProvincia: {provincia}\nComuna: {comuna}\nLugar: ")
                    layer.selectByIds(original_selection)
                except Exception as e:
                    print(f"Warning: no fue posible obtener 'Comunas' por selectbylocation: {e}")
        font.setPointSize(10)
        info_label.setFont(font)
        info_label.adjustSizeToText()
        info_label.attemptResize(QgsLayoutSize(45.0, 30.0, QgsUnitTypes.LayoutMillimeters))
        info_label.attemptMove(QgsLayoutPoint(162.0, 6.4, QgsUnitTypes.LayoutMillimeters))
        new_layout.addLayoutItem(info_label)
        scalebar.setFont(font)
        scalebar.attemptMove(QgsLayoutPoint(157.5, 256.0, QgsUnitTypes.LayoutMillimeters))
        scalebar.setSegmentSizeMode(QgsScaleBarSettings.SegmentSizeMode.SegmentSizeFitWidth)
        scalebar.setNumberOfSegmentsLeft(0)
        scalebar.setNumberOfSegments(2)
        scalebar.setMinimumBarWidth(30)
        scalebar.setMaximumBarWidth(40)
        new_layout.addLayoutItem(scalebar)
        # Grid: ajustar intervalos según escala y CRS (usar target_crs)
        grid = new_map.grid()
        proj_crs = self.target_crs
        if getattr(self, 'map_scale', 8000) == 70000:
            grid.setIntervalX(7500.0)
            grid.setIntervalY(7000.0)
        elif getattr(self, 'map_scale', 8000) == 8000:
            # si el CRS es geográfico (grados) usar intervalos en grados; si es proyectado usar metros
            if proj_crs.isGeographic():
                # ~0.008 grados ≈ ~900 m (aprox) — ajusta si es necesario
                grid.setIntervalX(0.008)
                grid.setIntervalY(0.008)
            else:
                grid.setIntervalX(800.0)
                grid.setIntervalY(800.0)
        else:
            grid.setIntervalX(9000.1)
            grid.setIntervalY(9000.1)
        grid.setUnits(QgsLayoutItemMapGrid.DynamicPageSizeBased)
        grid.setMinimumIntervalWidth(50)
        grid.setMaximumIntervalWidth(100)
        grid.setStyle(QgsLayoutItemMapGrid.FrameAnnotationsOnly)
        grid.setAnnotationEnabled(True)
        grid.setAnnotationPrecision(0)
        font_grid = QFont()
        font_grid.setPointSize(6)
        grid.setAnnotationFont(font_grid)
        grid.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Left)
        grid.setAnnotationDirection(QgsLayoutItemMapGrid.Vertical, QgsLayoutItemMapGrid.Left)
        grid.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Right)
        grid.setAnnotationDirection(QgsLayoutItemMapGrid.Vertical, QgsLayoutItemMapGrid.Right)
        grid.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Bottom)
        grid.setAnnotationDirection(QgsLayoutItemMapGrid.Horizontal, QgsLayoutItemMapGrid.Bottom)
        grid.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Top)
        grid.setAnnotationDirection(QgsLayoutItemMapGrid.Horizontal, QgsLayoutItemMapGrid.Top)
        # Añadir scalebar numérica
        scalebar_numerica = QgsLayoutItemScaleBar(new_layout)
        scalebar_numerica.setStyle('Numeric')
        scalebar_numerica.setLinkedMap(new_map)
        scalebar_numerica.setUnits(QgsUnitTypes.DistanceMeters)
        scalebar_numerica.setNumberOfSegments(2)
        scalebar_numerica.setUnitsPerSegment(100.0)
        scalebar_numerica.setUnitLabel('m')
        scalebar_numerica.attemptMove(QgsLayoutPoint(178.2, 270.5, QgsUnitTypes.LayoutMillimeters))
        scalebar_numerica.setFont(font_grid)
        new_layout.addLayoutItem(scalebar_numerica)
        # Forzar refresco del mapa y del layout (vista)
        try:
            new_map.updateBoundingRect()
            new_map.refresh()
        except Exception:
            pass
        try:
            designer = iface.openLayoutDesigner(QgsProject.instance().layoutManager().layoutByName(new_layout.name()))
            designer.view().refresh()
        except Exception:
            pass
        # Depuración: imprime tamaño de página para verificar si las coordenadas quedan dentro
        try:
            page = new_layout.pageCollection().page(0)
            size = page.pageSize()
            print(f"Página tamaño (mm): width={size.width()} height={size.height()}")
        except Exception:
            pass
        # --- Fin bloque corregido ---
        # Se remueve el mapa original importado (si existe)
        try:
            new_layout.removeLayoutItem(map_item)
        except Exception:
            pass
        self.current_layout = new_layout
        print(f"Plantilla cargada y layout creado con nombre '{new_layout.name()}'.")
    def hide_complementary_variables_group(self):
        root = QgsProject.instance().layerTreeRoot()
        for group in root.children():
            if isinstance(group, QgsLayerTreeGroup) and group.name() == "00. Variables complementarias":
                group.setItemVisibilityChecked(False)
    def update_group_visibility(self):
        root = QgsProject.instance().layerTreeRoot()
        for group in root.children():
            if isinstance(group, QgsLayerTreeGroup):
                visible_layers = [layer for layer in group.children() if layer.isVisible()]
                if not visible_layers:
                    group.setExpanded(False)
    def update_renderer(self, layer_names, attribute_names):
        for layer_name, attribute_name in zip(layer_names, attribute_names):
            layer_categorizada = self.find_layer_in_group("06. Variables de riesgo", layer_name)
            if not layer_categorizada:
                # Intentar buscar en todo el proyecto como fallback
                all_matches = [l for l in QgsProject.instance().mapLayers().values() if layer_name.lower() in l.name().lower()]
                if all_matches:
                    layer_categorizada = all_matches[0]
                    print(f"update_renderer: encontró capa por fallback en proyecto: '{layer_categorizada.name()}'")
                else:
                    print(f"La capa '{layer_name}' no existe en el proyecto.")
                    continue
            old_renderer = layer_categorizada.renderer()
            if isinstance(old_renderer, (QgsCategorizedSymbolRenderer, QgsGraduatedSymbolRenderer)):
                new_renderer = old_renderer.clone()
                new_renderer.deleteAllCategories()
                for cat in old_renderer.categories():
                    cat.setRenderState(any(feat[attribute_name] == cat.value() for feat in layer_categorizada.selectedFeatures()))
                    new_renderer.addCategory(cat)
                layer_categorizada.setRenderer(new_renderer)
    def update_legend(self, intersecting_layers):
        layout_name = '1'
        layout = QgsProject.instance().layoutManager().layoutByName(layout_name)
        if not layout:
            print(f"update_legend: no se encontró layout '{layout_name}'")
            return
        legend_id = 'Leyenda'
        legend = QgsLayoutItemLegend(layout)
        legend.setId(legend_id)
        legend.setTitle('Leyenda')
        layout.addLayoutItem(legend)
        legend.attemptMove(QgsLayoutPoint(44.7, 254.2))
        legend.setColumnCount(2)
        legend.setAutoUpdateModel(False)
        # Asegurar que la capa maestra esté incluida
        if self.geopackage_layer:
            master_name = self.geopackage_layer.name()
            if master_name not in intersecting_layers:
                intersecting_layers.insert(0, master_name)
        # --- Formato y fuentes ---
        if len(intersecting_layers) > 1:
            group_font = QFont("Arial", 7)
            group_font.setBold(True)
            title_font = QFont("Arial", 12)
            legend.setStyleFont(QgsLegendStyle.Title, title_font)
            legend.setSymbolHeight(5)
            legend.setSymbolWidth(5)
            legend.setStyleFont(QgsLegendStyle.Group, group_font)
            subgroup_font = QFont("Arial", 6)
            legend.setStyleFont(QgsLegendStyle.Subgroup, subgroup_font)
            symbol_label_font = QFont("Arial", 6)
            legend.setStyleFont(QgsLegendStyle.SymbolLabel, symbol_label_font)
        # --- Construcción de la leyenda filtrando sólo las capas intersectadas ---
        root = QgsProject.instance().layerTreeRoot()
        model = legend.model()
        group = model.rootGroup()
        group.clear()
        for group_node in root.children():
            if not isinstance(group_node, QgsLayerTreeGroup):
                continue
            # Excluir grupo "00. Variables complementarias" si contiene "Mapa Geológico"
            if group_node.name() == "00. Variables complementarias" and any(
                layer_node.name() == "Mapa Geológico" for layer_node in group_node.children()
            ):
                continue
            # Recorre las capas del grupo
            for layer_node in group_node.findLayers():
                layer_name = layer_node.name()

                # Excluir "Comunas" de "01. Contexto territorial"
                if group_node.name() == "01. Contexto territorial" and layer_name == "Comunas":
                    continue

                # Agregar solo las capas en intersecting_layers
                if layer_name in intersecting_layers:
                    parent_group = layer_node.parent()
                    legend_group = group.findGroup(parent_group.name())
                    if not legend_group:
                        legend_group = group.addGroup(parent_group.name())
                    legend_group.addLayer(layer_node.layer())
        legend.adjustBoxSize()
        print("Leyenda actualizada con capas:", intersecting_layers)
    def find_intersections_v5(self, intersection_types):
        """
        Encuentra capas que intersectan con self.geopackage_layer.
        - Selecciona las features intersectantes en la capa original (para que el analista pueda verlas).
        - Devuelve la lista de nombres de capas que intersectan.
        """
        intersecting_layers = []
        root = QgsProject.instance().layerTreeRoot()
        predicate_map = {'intersects': 0,'touches': 1,'contains': 2,'equals': 3,'overlaps': 4,'within': 5,'crosses': 6}
        predicates = [predicate_map[t] for t in intersection_types]
        if not self.geopackage_layer:
            print("No hay capa base para intersectar (self.geopackage_layer is None).")
            return intersecting_layers
        # Limpiar selección previa en la capa base por si acaso
        try:
            self.geopackage_layer.removeSelection()
        except Exception:
            pass
        for layer in QgsProject.instance().mapLayers().values():
            # Saltar si layer no es vectorial o si es la misma capa
            if not isinstance(layer, QgsVectorLayer):
                continue
            if layer.id() == self.geopackage_layer.id():
                continue
            # Limpiar selección previa en la capa objetivo
            try:
                layer.removeSelection()
            except Exception:
                pass
            # Preparamos un layer INTERSECT que esté en el CRS de 'layer' para que selectbylocation seleccione en la propia 'layer'
            intersect_layer_for_select = self.geopackage_layer
            reprojected_temp = None
            try:
                if self.geopackage_layer.crs() != layer.crs():
                    params = {'INPUT': self.geopackage_layer, 'TARGET_CRS': layer.crs(), 'OUTPUT': 'memory:'}
                    res = processing.run('qgis:reprojectlayer', params)
                    intersect_layer_for_select = res['OUTPUT']
                    reprojected_temp = intersect_layer_for_select  # marcar para posible limpieza (no es estrictamente necesario)
            except Exception as e:
                print(f"Warning: no fue posible reproyectar la capa base a CRS de '{layer.name()}': {e}")
                intersect_layer_for_select = self.geopackage_layer
            # Ejecutar select by location con INPUT = layer (así se selecciona en la capa original)
            try:
                params_sel = {
                    'INPUT': layer,
                    'PREDICATE': predicates,
                    'INTERSECT': intersect_layer_for_select,
                    'METHOD': 0
                }
                processing.run('native:selectbylocation', params_sel)
            except Exception as e:
                print(f"Error en selectbylocation para {layer.name()}: {e}")
            # Verificar cuántas features quedaron seleccionadas en la capa original
            try:
                sel_count = layer.selectedFeatureCount()
            except Exception:
                sel_count = 0
            layer_node = root.findLayer(layer.id())
            if sel_count > 0:
                intersecting_layers.append(layer.name())
                # Hacer visible la capa y su grupo
                if layer_node:
                    layer_node.setItemVisibilityChecked(True)
                    parent_group = layer_node.parent()
                    if parent_group:
                        parent_group.setItemVisibilityChecked(True)
            else:
                # Si no intersecta, ocultar (igual que antes)
                if layer_node:
                    layer_node.setItemVisibilityChecked(False)
            # Nota: no hay que eliminar explícitamente la capa reproyectada en memoria;
            # QGIS la liberará cuando se pierda la referencia. Si prefieres eliminarla del proyecto
            # (no la añadimos al proyecto) no hace falta.
        return intersecting_layers
    def export_intersecting_layers_v3(self, intersection_types):
        intersecting_layers = self.find_intersections_v5(intersection_types)
        if self.selected_file_path:
            file_name = os.path.basename(self.selected_file_path)
            base_name, _ = os.path.splitext(file_name)
            xlsx_file_name = f"{base_name}_capas_intersectadas.xlsx"
            xlsx_file_path = os.path.join(os.path.dirname(self.selected_file_path), xlsx_file_name)
        else:
            xlsx_file_path = 'capas_intersectadas.xlsx'
        vl = QgsVectorLayer("Point", "temporary_points", "memory")
        pr = vl.dataProvider()
        pr.addAttributes([QgsField("CAPAS", QVariant.String),QgsField("CAPAS INTERSECTADAS", QVariant.String)])
        vl.updateFields()
        root = QgsProject.instance().layerTreeRoot()
        for group in root.children():
            if isinstance(group, QgsLayerTreeGroup):
                if group.name() == "00. Variables complementarias":
                    continue
                for layer_node in group.children():
                    layer = layer_node.layer()
                    if layer != self.geopackage_layer:
                        if group.name() == "01. Contexto territorial" and layer_node.name() == "Comunas":
                            continue
                        fet = QgsFeature()
                        layer_name = layer.name().replace(':', ':')
                        if layer_name in intersecting_layers:
                            fet.setAttributes([layer_name, 'Intersecta'])
                        else:
                            fet.setAttributes([layer_name, 'No Intersecta'])
                        pr.addFeature(fet)
        QgsVectorFileWriter.writeAsVectorFormat(vl, xlsx_file_path, "utf-8", driverName="XLSX")
    def add_tile_layers_to_project(self):
        tile_layer_url_1 = "type=xyz&url=https://mt1.google.com/vt/lyrs%3Ds%26x%3D{x}%26y%3D{y}%26z%3D{z}&zmax=20&zmin=0&crs=EPSG3857"
        tile_layer_url_2 = "https://services.arcgisonline.com/ArcGIS/rest/services/NatGeo_World_Map/MapServer/tile/{z}/{y}/{x}"
        tile_layer_1 = QgsRasterLayer(f"type=xyz&url={tile_layer_url_1}", "Google Satellite", "wms")
        tile_layer_2 = QgsRasterLayer(f"type=xyz&url={tile_layer_url_2}", "NatGeo World Map", "wms")
        if tile_layer_1.isValid() and tile_layer_2.isValid():
            root = QgsProject.instance().layerTreeRoot()
            group_names = ["09. Variables de energia","08. Variables de minería", "07. Variables de turismo y patrimonio",
            "06. Variables de riesgo", "05. Variables indígenas", "04. Variables de conservación",
            "03. Variables ambientales", "02. Instrumentos de Planificación Territorial", "01. Contexto territorial"]
            group = None
            for group_name in group_names:
                group = root.findGroup(group_name)
                if group:
                    break
            if group:
                group_index = root.children().index(group)
                QgsProject.instance().addMapLayer(tile_layer_1, False)
                root.insertLayer(group_index + 1, tile_layer_1)
                QgsProject.instance().addMapLayer(tile_layer_2, False)
                root.insertLayer(group_index + 2, tile_layer_2)
            else:
                print(f"No se encontró ninguno de los grupos especificados")
                QgsProject.instance().addMapLayer(tile_layer_1)
                QgsProject.instance().addMapLayer(tile_layer_2)
            tile_layer_node_1 = root.findLayer(tile_layer_1.id())
            tile_layer_node_2 = root.findLayer(tile_layer_2.id())
            tile_layer_node_2.setItemVisibilityChecked(False)
            return tile_layer_1, tile_layer_2
        else:
            return None, None
    def update_sketch_map(self, tile_layer):
        layout_name = '1'
        layout = QgsProject.instance().layoutManager().layoutByName(layout_name)
        map_item = layout.itemById('Mapa esquicio')
        if map_item:
            new_map = QgsLayoutItemMap(layout)
            new_map.attemptMove(map_item.positionWithUnits())
            new_map.attemptResize(map_item.sizeWithUnits())
            layout.addLayoutItem(new_map)
            # mantener target_crs en el mapa esquicio
            new_map.setCrs(self.target_crs)
            canvas = iface.mapCanvas()
            try:
                new_map.setExtent(canvas.extent())
            except Exception:
                pass
            new_map.attemptResize(map_item.sizeWithUnits())
            new_map.setScale(4000000)
            if tile_layer and tile_layer.isValid():
                # si el tile layer está en 3857, QGIS hará reproyección en visual; dejamos las capas
                new_map.setLayers([self.geopackage_layer, tile_layer])
            else:
                print("La capa de teselas no es válida")
                new_map.setLayers([self.geopackage_layer])
            polygon_item = layout.itemById('POLIGONO DE UBICACION')
            if polygon_item:
                x = new_map.positionWithUnits().x() + new_map.sizeWithUnits().width() / 2 - polygon_item.sizeWithUnits().width() / 2
                y = new_map.positionWithUnits().y() + new_map.sizeWithUnits().height() / 2 - polygon_item.sizeWithUnits().height() / 2
                polygon_item.attemptMove(QgsLayoutPoint(x, y))
                if polygon_item.positionWithUnits().x() < new_map.positionWithUnits().x():
                    polygon_item.attemptMove(QgsLayoutPoint(new_map.positionWithUnits().x(),
                                                        polygon_item.positionWithUnits().y()))
                if polygon_item.positionWithUnits().y() < new_map.positionWithUnits().y():
                    polygon_item.attemptMove(QgsLayoutPoint(polygon_item.positionWithUnits().x(),
                                                        new_map.positionWithUnits().y()))
                if (polygon_item.positionWithUnits().x() + polygon_item.sizeWithUnits().width()) > (new_map.positionWithUnits().x() + new_map.sizeWithUnits().width()):
                    polygon_item.attemptMove(QgsLayoutPoint(new_map.positionWithUnits().x() + new_map.sizeWithUnits().width() - polygon_item.sizeWithUnits().width(),
                                                        polygon_item.positionWithUnits().y()))
                if (polygon_item.positionWithUnits().y() + polygon_item.sizeWithUnits().height()) > (new_map.positionWithUnits().y() + new_map.sizeWithUnits().height()):
                    polygon_item.attemptMove(QgsLayoutPoint(polygon_item.positionWithUnits().x(),
                                                        new_map.positionWithUnits().y() + new_map.sizeWithUnits().height() - polygon_item.sizeWithUnits().height()))
            else:
                print('No se encontró un objeto poligonal con el ID especificado en la plantilla')
            new_map.setKeepLayerSet(False)
            layout.removeLayoutItem(map_item)
        else:
            print('No se encontró un mapa con el ID especificado en la plantilla')
    def check_layer_and_categories(self,layer_name):
        all_layers = QgsProject.instance().mapLayersByName(layer_name)
        if not all_layers:
            print(f"La capa '{layer_name}' no existe en el proyecto.")
            return []
        map_layer = all_layers[0]
        if map_layer.renderer().type() == 'categorizedSymbol':
            return [cat.value() for cat in map_layer.renderer().categories() if not cat.renderState()]
        else:
            return []
    def check_layout_and_item(self, layout_name, item_id, layer_name, categories_to_remove):
        manager = QgsProject.instance().layoutManager()
        layout = manager.layoutByName(layout_name)
        if not layout:
            return
        legend = layout.itemById(item_id)
        if not legend or not isinstance(legend, QgsLayoutItemLegend):
            return
        target_layer = next((layer for layer in [layer.layer() for layer in legend.model().rootGroup().findLayers()] if layer.name() == layer_name), None)
        if target_layer and target_layer.renderer().type() == 'categorizedSymbol':
            root = legend.model().rootGroup().findLayer(target_layer)
            if root is not None:
                nodes = legend.model().layerLegendNodes(root)
                indexes_to_remove = [nodes.index(node) for node in nodes if node.data(0) in categories_to_remove]
                QgsMapLayerLegendUtils.setLegendNodeOrder(root, [i for i in range(len(nodes)) if i not in indexes_to_remove])
                legend.model().refreshLayerLegend(root)
        else:
            pass
    def process_layers(self, layer_names, layout_name, item_id):
        if isinstance(layer_names, str):
            layer_names = [layer_names]
        for layer_name in layer_names:
            self.check_layout_and_item(layout_name, item_id, layer_name, self.check_layer_and_categories(layer_name))
    def obtener_version_qgis(self):
        version = Qgis.QGIS_VERSION
        print(f"La versión de QGIS es: {version}")
# ====== Flujo principal ======
layer_loader = LayerLoader()
layer_loader.select_and_load_geopackage()
layer_loader.load_layers_from_selected_folder()
intersecting_layers = layer_loader.find_intersections_v5(['intersects'])
template_urls = ["https://gitlab.com/camiloceacarvajal1/plantilla_MBN/-/raw/main/22.qpt?ref_type=heads",
                 "https://raw.githubusercontent.com/camiloceacarvajal/PLANTILLA-MBN/main/21.qpt"]
layer_loader.load_template_from_url(template_urls)
layer_loader.update_legend(intersecting_layers)
layer_loader.export_intersecting_layers_v3(['intersects'])
tile_layer_1, tile_layer_2 = layer_loader.add_tile_layers_to_project()
layer_loader.update_sketch_map(tile_layer_2)
designer = iface.openLayoutDesigner(QgsProject.instance().layoutManager().layoutByName('1'))
designer.view().setZoomLevel(0.7)
layer_names = ["Riesgo de incendios forestales", "Cartas de inundación por tsunami", 'Áreas de peligro por actividad volcánica: áreas de peligro']
attribute_names = ["Riesgo ", "Name", 'peligro']
layer_loader.update_renderer(layer_names, attribute_names)
layer_loader.update_group_visibility()
layer_loader.process_layers(layer_names, "1", "Leyenda")
layer_loader.hide_complementary_variables_group()
layer_loader.obtener_version_qgis()
try:
    iface.mainWindow().findChild(QDockWidget, 'PythonConsole').close()
except Exception:
    pass
# Version Desarrollo -01-10-2025 LTR -