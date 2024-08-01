import os,glob,requests
from PyQt5.QtGui import QFont
from qgis.utils import iface,plugins
from qgis.core import QgsLayerTreeGroup,QgsLayoutItemMapGrid,QgsLayerTreeLayer,QgsUnitTypes,QgsLayoutItemScaleBar
from qgis.core import QgsDistanceArea,QgsFillSymbol,QgsSingleSymbolRenderer,QgsLayoutItemMap,QgsLegendStyle
from qgis.core import QgsLayoutItemLabel,QgsCoordinateReferenceSystem,QgsLayoutSize,QgsProject, QgsMapLayer, QgsMapLayerLegendUtils
from qgis.core import QgsVectorLayer, QgsProject, QgsPrintLayout, QgsReadWriteContext,QgsLayoutItemLegend, QgsLayoutPoint
from qgis.PyQt.QtWidgets import QFileDialog
from qgis.PyQt.QtXml import QDomDocument
from qgis import processing

class LayerLoader:
    def __init__(self):
        self.geopackage_layer = None
        self.selected_file_path = None
        self.target_crs = QgsCoordinateReferenceSystem('EPSG:5361')
    def add_layer_to_group(self, layer, group_name):
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(group_name)
        if not group:
            group = root.addGroup(group_name)
        QgsProject.instance().addMapLayer(layer, False)
        group.addLayer(layer)
    def find_layer_in_group(self, group_name, layer_name):
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(group_name)
        if group is not None:
            for layer in group.findLayers():
                if layer.name() == layer_name:
                    return layer.layer()
        return None
    def select_and_load_geopackage(self):
        file_path = QFileDialog.getOpenFileName(None, 'Seleccionar poligono MCT', '', 'Archivos (*.gpkg *.shp *.kml *.kmz)')[0]
        if file_path:
            self.selected_file_path = file_path
            layer = QgsVectorLayer(file_path, '', 'ogr')
            if not layer.isValid():
                error = layer.error().message()
                print(f'La capa no es válida! Error: {error}')
            else:
                # Verificar el tipo de geometría de la capa
                geometry_type = layer.geometryType()
                if geometry_type == QgsWkbTypes.PointGeometry:
                    print('La capa es de tipo PUNTO. Debe revisar el archivo.')
                elif geometry_type == QgsWkbTypes.LineGeometry:
                    print('La capa es de tipo LINEA. Debe revisar el archivo.')
                elif geometry_type == QgsWkbTypes.PolygonGeometry:
                    # Verificar si la capa es de tipo multipolígono
                    if layer.featureCount() > 1:
                        print('La capa es de tipo MULTIPOLÍGONO. Debe revisar el archivo. ')
                    else:
                        print('La capa es de tipo POLÍGONO.')
                else:
                    print('La capa tiene un tipo de geometría desconocido.')
                extent = layer.dataProvider().extent()
                distance_area = QgsDistanceArea()
                distance_area.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
                distance_area.setEllipsoid(QgsProject.instance().ellipsoid())
                area_ha = 0
                for feature in layer.getFeatures():
                    area_m2 = distance_area.measureArea(feature.geometry())
                    area_ha += area_m2 / 10000
                if area_ha > 3000:
                    self.map_scale = 100000
                    print(f"Área del polígono: {area_ha} ha")
                elif area_ha > 20:
                    self.map_scale = 70000
                    print(f"Área del polígono: {area_ha} ha")
                else:
                    self.map_scale = 8000
                    print(f"Área del polígono: {area_ha} ha")
                sublayers = layer.dataProvider().subLayers()
                for sublayer in sublayers:
                    name = sublayer.split('!!::!!')[1]
                    uri = f"{file_path}|layername={name}"
                    sub_vlayer = QgsVectorLayer(uri, name, 'ogr')
                    if sub_vlayer.isValid():
                        if sub_vlayer.crs() != self.target_crs:
                            params = {'INPUT': sub_vlayer,'TARGET_CRS': self.target_crs,'OUTPUT': 'memory:'}
                            result = processing.run('qgis:reprojectlayer', params)
                            reprojected_sub_vlayer = result['OUTPUT']
                            base_name = os.path.splitext(os.path.basename(file_path))[0]
                            reprojected_sub_vlayer.setName(base_name)
                            base_renderer = QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({'color': 'rgba(255, 255, 255, 0.3)', 'outline_color': '#0059ff', 'outline_width': 0.98}))
                            renderer = QgsInvertedPolygonRenderer(base_renderer)
                            # Define symbol from renderer
                            some_symbol = renderer.symbols(QgsRenderContext())[0]
                            # Define symbology
                            some_symbol.setColor(QColor.fromRgb(255,255,255))   # Colour
                            some_symbol.setOpacity(0.30)                         # Opacity
                            reprojected_sub_vlayer.setRenderer(renderer)
                            reprojected_sub_vlayer.triggerRepaint()
                            self.add_layer_to_group(reprojected_sub_vlayer, "Deslinde AT")
                        else:
                            base_name = os.path.splitext(os.path.basename(file_path))[0]
                            sub_vlayer.setName(base_name)
                            base_renderer = QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({'color': 'rgba(255, 255, 255, 0.3)', 'outline_color': '#0059ff', 'outline_width': 0.98}))
                            renderer = QgsInvertedPolygonRenderer(base_renderer)
                            # Define symbol from renderer
                            some_symbol = renderer.symbols(QgsRenderContext())[0]
                            # Define symbology
                            some_symbol.setColor(QColor.fromRgb(255,255,255))   # Colour
                            some_symbol.setOpacity(0.50)                         # Opacity
                            sub_vlayer.setRenderer(renderer)
                            sub_vlayer.triggerRepaint()
                            self.add_layer_to_group(sub_vlayer, "Deslinde AT")
                    else:
                        print(f"Sublayer {name} is not valid")
                self.geopackage_layer = layer
        else:
            print('No se seleccionó ningún archivo')
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
                    sub_vlayer.setOpacity(0.8) # Establecer la transparencia en 0.x (x0%)
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
            response = requests.get(template_url)
            if response.status_code == 200:
                template_content = response.text
                self.load_template_content(template_content)
                break
            else:
                print(f'Error al obtener el archivo QPT desde la URL: {template_url}')
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
                continue
            old_renderer = layer_categorizada.renderer()
            if isinstance(old_renderer, (QgsCategorizedSymbolRenderer, QgsGraduatedSymbolRenderer)):
                new_renderer = old_renderer.clone()
                new_renderer.deleteAllCategories()
                for cat in old_renderer.categories():
                    cat.setRenderState(any(feat[attribute_name] == cat.value() for feat in layer_categorizada.selectedFeatures()))
                    new_renderer.addCategory(cat)
                layer_categorizada.setRenderer(new_renderer)
    def load_template_content(self, template_content):
        myDocument = QDomDocument()
        myDocument.setContent(template_content)
        newcomp = QgsPrintLayout(QgsProject.instance())
        newcomp.loadFromTemplate(myDocument, QgsReadWriteContext())
        QgsProject.instance().layoutManager().addLayout(newcomp)
        map = newcomp.itemById('Mapa 3')
        if map:
            new_map = QgsLayoutItemMap(newcomp)
            new_map.attemptMove(map.positionWithUnits())
            new_map.attemptResize(map.sizeWithUnits())
            newcomp.addLayoutItem(new_map)
            new_map.setCrs(QgsProject.instance().crs())
            canvas = iface.mapCanvas()
            new_map.setExtent(canvas.extent())
            new_map.attemptResize(map.sizeWithUnits())
            new_map.setScale(self.map_scale)
            font = QFont()
            font.setPointSize(7)
            scalebar = QgsLayoutItemScaleBar(newcomp)
            scalebar.setLinkedMap(new_map)
            if self.map_scale <= 8900:
                scalebar.setUnits(QgsUnitTypes.DistanceMeters)
                scalebar.setNumberOfSegments(2)
                scalebar.setUnitsPerSegment(100.0)
                scalebar.setUnitLabel('m')
            else:
                scalebar.setUnits(QgsUnitTypes.DistanceKilometers)
                scalebar.setNumberOfSegments(2)
                scalebar.setUnitsPerSegment(1.0)
                scalebar.setUnitLabel('km')
            scale_label = QgsLayoutItemLabel(newcomp)
            scale_label.setText(f"1:{new_map.scale():,.0f}")
            scale_label.setFont(font)
            scale_label.adjustSizeToText()
            info_label = QgsLayoutItemLabel(newcomp)
            info_label.setId('INFO ADMINISTRATIVO')
            root = QgsProject.instance().layerTreeRoot()
            group = root.findGroup("01. Contexto territorial")
            info_label.setText(f"Región: \nProvincia: \nComuna: \nLugar: ")
            if group:
                layer = None
                for child in group.children():
                    if isinstance(child, QgsLayerTreeLayer) and child.name() == "Comunas":
                        layer = child.layer()
                        break
                if layer:
                    if self.geopackage_layer:
                        original_subset = self.geopackage_layer.subsetString()
                        self.geopackage_layer.setSubsetString('')
                        params = {'INPUT': layer,'PREDICATE': [0],'INTERSECT': self.geopackage_layer,'METHOD': 0}
                        processing.run('native:selectbylocation', params)
                        selected_features = layer.selectedFeatures()
                        if selected_features:
                            feature = selected_features[0]
                            region = feature["REGION"]
                            provincia = feature["PROVINCIA"]
                            comuna = feature["COMUNA"]
                            info_label.setText(f"Región: {region}\nProvincia: {provincia}\nComuna: {comuna}\nLugar: ")
                            self.geopackage_layer.setSubsetString(original_subset)
            font.setPointSize(10)
            info_label.setFont(font)
            info_label.adjustSizeToText()
            info_label.attemptResize(QgsLayoutSize(45, 30))
            info_label.attemptMove(QgsLayoutPoint(162.0, 6.4))
            newcomp.addLayoutItem(info_label)
            scalebar.setFont(font)
            scalebar.attemptMove(QgsLayoutPoint(161.4, 254.2))#escala grafica
            grid = new_map.grid()
            if self.map_scale == 70000:
                grid.setIntervalX(7500.1)
                grid.setIntervalY(7000.1)
            elif self.map_scale == 8000:
                grid.setIntervalX(800.1)
                grid.setIntervalY(800.1)
            else:
                grid.setIntervalX(9000.1)
                grid.setIntervalY(9000.1)
            newcomp.addLayoutItem(scalebar)
            grid.setStyle(QgsLayoutItemMapGrid.FrameAnnotationsOnly)
            grid.setAnnotationEnabled(True)
            grid.setAnnotationPrecision(0)
            font = QFont()
            font.setPointSize(6)
            grid.setAnnotationFont(font)
            grid.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Left)
            grid.setAnnotationDirection(QgsLayoutItemMapGrid.Vertical, QgsLayoutItemMapGrid.Left)
            grid.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Right)
            grid.setAnnotationDirection(QgsLayoutItemMapGrid.Vertical, QgsLayoutItemMapGrid.Right)
            grid.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Bottom)
            grid.setAnnotationDirection(QgsLayoutItemMapGrid.Horizontal, QgsLayoutItemMapGrid.Bottom)
            grid.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Top)
            grid.setAnnotationDirection(QgsLayoutItemMapGrid.Horizontal, QgsLayoutItemMapGrid.Top)
            new_map.updateBoundingRect()
            new_map.refresh()
            newcomp.removeLayoutItem(map)
            scalebar_numerica = QgsLayoutItemScaleBar(newcomp)
            scalebar_numerica.setStyle('Numeric')
            scalebar_numerica.setLinkedMap(new_map)
            scalebar_numerica.setUnits(QgsUnitTypes.DistanceMeters)
            scalebar_numerica.setNumberOfSegments(2)
            scalebar_numerica.setUnitsPerSegment(100.0)
            scalebar_numerica.setUnitLabel('m')
            scalebar_numerica.attemptMove(QgsLayoutPoint(179.7, 270.79))
            scalebar_numerica.setFont(font)
            newcomp.addLayoutItem(scalebar_numerica)
        else:
            print('No se encontró un mapa con el ID especificado en la plantilla')
    def update_legend(self, intersecting_layers):
        layout_name = '1'
        layout = QgsProject.instance().layoutManager().layoutByName(layout_name)
        legend_id = 'Leyenda'
        legend = QgsLayoutItemLegend(layout)
        legend.setId(legend_id)
        legend.setTitle('Leyenda')
        layout.addLayoutItem(legend)
        legend.attemptMove(QgsLayoutPoint(44.7, 254.2))
        legend.setColumnCount(2)
        legend.setAutoUpdateModel(False)
        if len(intersecting_layers) > 1:
            group_font = QFont("Arial", 7)
            group_font.setBold(True)
            title_font = QFont("Arial", 12)
            legend.setStyleFont(QgsLegendStyle.Title, title_font)
            legend.setSymbolHeight(5) # Establece la altura del símbolo en 5 
            legend.setSymbolWidth(5) # Establece el ancho del símbolo en 5 
            legend.setStyleFont(QgsLegendStyle.Group, group_font)
            subgroup_font = QFont("Arial", 6)
            legend.setStyleFont(QgsLegendStyle.Subgroup, subgroup_font)
            symbol_label_font = QFont("Arial", 6)
            legend.setStyleFont(QgsLegendStyle.SymbolLabel, symbol_label_font)
        root = QgsProject.instance().layerTreeRoot()
        model = legend.model()
        group = model.rootGroup()
        group.clear()
        for group_node in root.children():
            if isinstance(group_node, QgsLayerTreeGroup):
                # Si el grupo es "00. Variables complementarias" y contiene "Mapa Geológico", continúa con el siguiente grupo
                if group_node.name() == "00. Variables complementarias" and any(layer_node.name() == "Mapa Geológico" for layer_node in group_node.children()):
                    continue
            # Procesa las capas en el grupo
            for layer_node in group_node.children():
                if layer_node.isVisible() and layer_node.name() in intersecting_layers and not (group_node.name() == "01. Contexto territorial" and layer_node.name() == "Comunas"):
                    parent_group = layer_node.parent()
                    legend_group = group.findGroup(parent_group.name())
                    if not legend_group:
                        legend_group = group.addGroup(parent_group.name())
                    legend_group.addLayer(layer_node.layer())
        legend.updateLegend()
    def find_intersections_v5(self, intersection_types):
        intersecting_layers = []
        root = QgsProject.instance().layerTreeRoot()
        predicate_map = {'intersects': 0,'touches': 1,'contains': 2,'equals': 3,'overlaps': 4,'within': 5,'crosses': 6}
        predicates = [predicate_map[t] for t in intersection_types]
        for layer in QgsProject.instance().mapLayers().values():
            if layer != self.geopackage_layer:
                selected_features = 0
                for geopackage_feat in self.geopackage_layer.getFeatures():
                    sql_expression = f"fid = {geopackage_feat.id()}"
                    self.geopackage_layer.setSubsetString(sql_expression)
                    params = {'INPUT': layer,'PREDICATE': predicates,'INTERSECT': self.geopackage_layer,'METHOD': 0}
                    processing.run('native:selectbylocation', params)
                    selected_features += layer.selectedFeatureCount()
                    layer_node = root.findLayer(layer.id())
                    if selected_features > 0:
                        intersecting_layers.append(layer.name())
                        layer_node.setItemVisibilityChecked(True)
                        group_node = layer_node.parent()
                        group_node.setItemVisibilityChecked(True)
                    else:
                        layer_node.setItemVisibilityChecked(False)
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
                for layer_node in group.children():
                    layer = layer_node.layer()
                    if layer != self.geopackage_layer:
                        # No exportar la capa "Comunas"
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
        map = layout.itemById('Mapa esquicio')
        if map:
            new_map = QgsLayoutItemMap(layout)
            new_map.attemptMove(map.positionWithUnits())
            new_map.attemptResize(map.sizeWithUnits())
            layout.addLayoutItem(new_map)
            new_map.setCrs(QgsProject.instance().crs())
            canvas = iface.mapCanvas()
            new_map.setExtent(canvas.extent())
            new_map.attemptResize(map.sizeWithUnits())
            new_map.setScale(7000000)
            # Establecer las capas del mapa esquicio en una lista que contiene la capa de entrada y la capa de teselas
            if tile_layer and tile_layer.isValid():
                new_map.setLayers([self.geopackage_layer, tile_layer])
                #print(f"Capas del mapa esquicio: {[layer.name() for layer in new_map.layers()]}")
            else:
                print("La capa de teselas no es válida")
                new_map.setLayers([self.geopackage_layer])
                print(f"Capas del mapa esquicio: {[layer.name() for layer in new_map.layers()]}")
            polygon_item = layout.itemById('POLIGONO DE UBICACION')
            if polygon_item:
                # Cambiar la geometría del objeto poligonal para que se ubique en el centro del mapa de esquicio
                x = new_map.positionWithUnits().x() + new_map.sizeWithUnits().width() / 2 - polygon_item.sizeWithUnits().width() / 2
                y = new_map.positionWithUnits().y() + new_map.sizeWithUnits().height() / 2 - polygon_item.sizeWithUnits().height() / 2
                polygon_item.attemptMove(QgsLayoutPoint(x, y))
                # Restringir la posición del polígono para que no se salga del perímetro del mapa de esquicio
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
            new_map.setKeepLayerSet(False) # Desactivar la opción de dibujar elementos de la vista del mapa
            layout.removeLayoutItem(map)
        else:
            print('No se encontró un mapa con el ID especificado en la plantilla')

layer_loader = LayerLoader()
layer_loader.select_and_load_geopackage()
layer_loader.load_layers_from_selected_folder()
intersecting_layers = layer_loader.find_intersections_v5(['intersects'])
template_urls = ["https://raw.githubusercontent.com/camiloceacarvajal/plantilla_MBN/main/17.qpt", "https://gitlab.com/camiloceacarvajal1/plantilla_MBN/-/raw/main/17.qpt?ref_type=heads"]
layer_loader.load_template_from_url(template_urls)
layer_loader.update_legend(intersecting_layers)
layer_loader.export_intersecting_layers_v3(['intersects'])
tile_layer_1, tile_layer_2 = layer_loader.add_tile_layers_to_project()
layer_loader.update_sketch_map(tile_layer_2)
designer=iface.openLayoutDesigner(QgsProject.instance().layoutManager().layoutByName('1'))
designer.view().setZoomLevel(0.7)
layer_names = ["Riesgo de incendios forestales", "Cartas de inundación por tsunami",'Áreas de peligro por actividad volcánica: áreas de peligro']
attribute_names = ["Riesgo ", "Name",'peligro']
layer_loader.update_renderer(layer_names, attribute_names)
layer_loader.update_group_visibility()
layer_loader.hide_complementary_variables_group()
#Version julio-2024
