import os, sys
import numpy as np
import pyqtgraph as pg
from . import qt
import pyqtgraph.functions as fn
from .signal import SignalBlock

if sys.version[0] > '2':
    from urllib.request import urlopen
else:
    from urllib import urlopen


class AtlasSliceView(qt.QObject):
    """A collection of user interface elements bound together:
    
    * One AtlasImageItem displaying an orthogonal view of the atlas
    * An ROI object that defines the slice to be extracted from the orthogonal
      view of the atlas
    * A second AtlasImageItem that displays the sliced view
    * A HistogramLUTItem used to control color/contrast in both images
    * An AtlasDisplayCtrl that sets options for how all elements are drawn
    * A LabelTree that is used to selectively color specific brain regions
    
    These are stored as attributes of this object and are not inserted into
    any top-level layout. 
    """
    
    sig_slice_changed = qt.Signal()  # slice plane changed
    sig_image_changed = qt.Signal()  # orthogonal image changed
    mouseHovered = qt.Signal(object)
    mouseClicked = qt.Signal(object)
    
    def __init__(self):
        qt.QObject.__init__(self)

        self.scale = None
        self.interpolate = True
        
        self.img1 = AtlasImageItem()
        self.img2 = AtlasImageItem()
        self.img1.mouseHovered.connect(self.mouseHovered)
        self.img2.mouseHovered.connect(self.mouseHovered)
        
        self.line_roi = RulerROI([.005, 0], [.008, 0], angle=90, pen=(0, 9), movable=False)
        self.line_roi.sigRegionChanged.connect(self.update_slice_image)

        self.zslider = qt.QSlider(qt.Qt.Horizontal)
        self.zslider.valueChanged.connect(self.update_ortho_image)

        self.angle_slider = qt.QSlider(qt.Qt.Horizontal)
        self.angle_slider.setRange(-45, 45)
        self.angle_slider.valueChanged.connect(self.angle_slider_changed)
        
        self.lut = pg.HistogramLUTWidget()
        self.lut.setImageItem(self.img1.atlas_img)
        self.lut.sigLookupTableChanged.connect(self.histlut_changed)
        self.lut.sigLevelsChanged.connect(self.histlut_changed)

        self.display_ctrl = AtlasDisplayCtrl()
        self.display_ctrl.params.sigTreeStateChanged.connect(self.display_ctrl_changed)

        self.label_tree = LabelTree()
        self.label_tree.labels_changed.connect(self.labels_changed)

    def set_data(self, atlas_data):
        self.atlas_data = atlas_data
        self.display_atlas = None
        self.display_label = None
        self.label_tree.set_ontology(atlas_data.ontology)
        self.update_image_data()
        self.labels_changed()

    def update_image_data(self):
        if self.atlas_data.image is None or self.atlas_data.label is None:
            return
        axis = self.display_ctrl.params['Orientation']
        axes = {
            'right': ('right', 'anterior', 'dorsal'),
            'dorsal': ('dorsal', 'right', 'anterior'),
            'anterior': ('anterior', 'right', 'dorsal')
        }[axis]
        order = [self.atlas_data.image._interpretAxis(ax) for ax in axes]

        # transpose, flip, downsample images
        ds = self.display_ctrl.params['Downsample']
        self.display_atlas = self.atlas_data.image.view(np.ndarray).transpose(order)
        with pg.BusyCursor():
            for ax in (0, 1, 2):
                self.display_atlas = pg.downsample(self.display_atlas, ds, axis=ax)
        self.display_label = self.atlas_data.label.view(np.ndarray).transpose(order)[::ds, ::ds, ::ds]

        # make sure atlas/label have the same size after downsampling

        scale = self.atlas_data.image._info[-1]['vxsize']*ds
        self.scale = (scale, scale)

        self.zslider.setMaximum(self.display_atlas.shape[0])
        self.zslider.setValue(self.display_atlas.shape[0] // 2)
        self.angle_slider.setValue(0)
        self.update_ortho_image()
        self.update_slice_image()
        self.lut.setLevels(self.display_atlas.min(), self.display_atlas.max())

    def labels_changed(self):
        # reapply label colors
        lut = self.label_tree.lookup_table()
        self.set_label_lut(lut)        
        
    def display_ctrl_changed(self, param, changes):
        update = False
        for param, change, value in changes:
            if param.name() == 'Composition':
                self.set_overlay(value)
            elif param.name() == 'Opacity':
                self.set_label_opacity(value)
            elif param.name() == 'Interpolate':
                self.set_interpolation(value)
            else:
                update = True
        if update:
            self.update_image_data()

    def update_ortho_image(self):
        z = self.zslider.value()
        self.img1.set_data(self.display_atlas[z], self.display_label[z], scale=self.scale)
        self.sig_image_changed.emit()

    def update_slice_image(self):
        rotation = self.angle_slider.value()

        if self.display_atlas is None:
            return

        if rotation == 0:
            atlas = self.line_roi.getArrayRegion(self.display_atlas, self.img1.atlas_img, axes=(1, 2), order=int(self.interpolate))
            label = self.line_roi.getArrayRegion(self.display_label, self.img1.atlas_img, axes=(1, 2), order=0)
        else:
            atlas = self.line_roi.getArrayRegion(self.display_atlas, self.img1.atlas_img, rotation=rotation, axes=(1, 2, 0), order=int(self.interpolate))
            label = self.line_roi.getArrayRegion(self.display_label, self.img1.atlas_img, rotation=rotation, axes=(1, 2, 0), order=0)

        if atlas.size == 0:
            return
        
        self.img2.set_data(atlas, label, scale=self.scale)
        self.sig_slice_changed.emit()
        
        scene = self.img2.atlas_img.scene()
        if scene is not None:
            w = scene.views()
            if len(w) > 0:
                # repaint immediately to avoid processing more mouse events before next repaint
                w[0].viewport().repaint()
                #w[0].viewport().repaint()
        
    def angle_slider_changed(self):
        rotation = self.angle_slider.value()
        self.set_rotation_roi(self.img1.atlas_img, rotation)
        self.update_slice_image()

    def close(self):
        self.data = None

    def set_overlay(self, o):
        self.img1.set_overlay(o)
        self.img2.set_overlay(o)

    def set_label_opacity(self, o):
        self.img1.set_label_opacity(o)
        self.img2.set_label_opacity(o)

    def set_interpolation(self, interp):
        assert isinstance(interp, bool)
        self.interpolate = interp

    def set_label_lut(self, lut):
        self.img1.set_lut(lut)
        self.img2.set_lut(lut)

    def histlut_changed(self):
        # note: img1 is updated automatically; only bneed to update img2 to match
        self.img2.atlas_img.setLookupTable(self.lut.getLookupTable(n=256))
        self.img2.atlas_img.setLevels(self.lut.getLevels())

    def set_rotation_roi(self, img, rotation):

        h1, h2, h3, h4, h5 = self.line_roi.getHandles()

        d_angle = pg.Point(h2.pos() - h1.pos())  # This gives the length in ccf coordinate size 
        d = pg.Point(self.line_roi.mapToItem(img, h2.pos()) - self.line_roi.mapToItem(img, h1.pos()))

        origin_roi = self.line_roi.mapToItem(img, h1.pos())

        if rotation == 0:
            offset = 0
        else:
            offset = self.get_offset(rotation)
        
        # This calculates by how much the ROI needs to shift
        if d.angle(pg.Point(1, 0)) == 90.0:
            # when ROI is on a 90 degree angle, can't really calculate using a right-angle triangle, ugh
            hyp, opposite, adjacent = offset * self.scale[0], 0, offset * self.scale[0]
        else:
            hyp = (offset * self.scale[0])
            opposite = (np.sin(np.radians(-(90 - d.angle(pg.Point(1, 0)))))) * hyp
            adjacent = opposite / (np.tan(np.radians(-(90 - d.angle(pg.Point(1, 0))))))
        
        # This is kind of a hack to avoid recursion error. Using update=False doesn't move the handles.
        self.line_roi.sigRegionChanged.disconnect(self.update_slice_image)  
        # increase size to denote rotation
        self.line_roi.setSize(pg.Point(d_angle.length(), hyp * 2))
        # Shift position in order to keep the cutting axis in the middle
        self.line_roi.setPos(pg.Point((origin_roi.x() * self.scale[-1]) + adjacent, (origin_roi.y() * self.scale[-1]) + opposite))
        self.line_roi.sigRegionChanged.connect(self.update_slice_image)

    def get_offset(self, rotation):
        theta = np.radians(-rotation)

        # Figure out the unit vector with theta angle
        x, z = 0, 1
        dc, ds = np.cos(theta), np.sin(theta)
        xv = dc * x - ds * z
        zv = ds * x + dc * z

        # Figure out the slope of the unit vector
        m = zv / xv

        # y = mx + b
        # Calculate the x-intercept. using half the distance in the z-dimension as b. Since we want the axis of rotation in the middle
        offset = (-self.atlas_data.image.shape[0] / 2) / m

        return abs(offset)


class AtlasDisplayCtrl(pg.parametertree.ParameterTree):
    """UI for controlling how the atlas is displayed. 
    """
    def __init__(self, parent=None):
        pg.parametertree.ParameterTree.__init__(self, parent=parent)
        params = [
            {'name': 'Orientation', 'type': 'list', 'values': ['right', 'anterior', 'dorsal']},
            {'name': 'Opacity', 'type': 'float', 'limits': [0, 1], 'value': 0.5, 'step': 0.1},
            {'name': 'Composition', 'type': 'list', 'values': ['Multiply', 'Overlay', 'SourceOver']},
            {'name': 'Downsample', 'type': 'int', 'value': 1, 'limits': [1, None], 'step': 1},
            {'name': 'Interpolate', 'type': 'bool', 'value': True},
        ]
        self.params = pg.parametertree.Parameter(name='params', type='group', children=params)
        self.setParameters(self.params, showTop=False)
        self.setHeaderHidden(True)


class LabelTree(qt.QWidget):
    labels_changed = qt.Signal()

    def __init__(self, parent=None):
        self._block_signals = False
        qt.QWidget.__init__(self, parent)
        self.layout = qt.QGridLayout()
        self.setLayout(self.layout)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0,0,0,0)

        self.tree = qt.QTreeWidget(self)
        self.layout.addWidget(self.tree, 0, 0)
        self.tree.header().setSectionResizeMode(qt.QHeaderView.ResizeToContents)
        self.tree.headerItem().setText(0, "id")
        self.tree.headerItem().setText(1, "name")
        self.tree.headerItem().setText(2, "color")
        self.labels_by_id = {}
        self.labels_by_acronym = {}
        self.checked = set()
        self.tree.itemChanged.connect(self.item_change)

        self.layer_btn = qt.QPushButton('Color by cortical layer')
        self.layout.addWidget(self.layer_btn, 1, 0)
        self.layer_btn.clicked.connect(self.color_by_layer)

        self.reset_btn = qt.QPushButton('Reset colors')
        self.layout.addWidget(self.reset_btn, 2, 0)
        self.reset_btn.clicked.connect(self.reset_colors)

    def set_ontology(self, ontology):
        # prevent emission of multiple signals during update
        self._block_signals = True
        try:
            for rec in ontology:
                self.add_label(*rec)
        finally:
            self._block_signals = False
        
        self.labels_changed.emit()

    def add_label(self, id, parent, name, acronym, color):
        item = qt.QTreeWidgetItem([acronym.decode(), name.decode(), ''])
        item.setFlags(item.flags() | qt.Qt.ItemIsUserCheckable)
        item.setCheckState(0, qt.Qt.Unchecked)

        if parent in self.labels_by_id:
            root = self.labels_by_id[parent]['item']
        else:
            root = self.tree.invisibleRootItem()

        root.addChild(item)

        color_str = color.decode()
        if not color_str.startswith('#'):
            color_str = '#' + color_str
        btn = pg.ColorButton(color=pg.mkColor(color_str))
        btn.defaultColor = color_str
        btn.id = id
        self.tree.setItemWidget(item, 2, btn)

        self.labels_by_id[id] = {'item': item, 'btn': btn}
        item.id = id
        self.labels_by_acronym[acronym] = self.labels_by_id[id]

        btn.sigColorChanged.connect(self.item_color_changed)

    def item_change(self, item, col):
        checked = item.checkState(0) == qt.Qt.Checked
        with SignalBlock(self.tree.itemChanged, self.item_change):
            self.check_recursive(item, checked)
            
        if not self._block_signals:
            self.labels_changed.emit()

    def check_recursive(self, item, checked):
        if checked:
            self.checked.add(item.id)
            item.setCheckState(0, qt.Qt.Checked)
        else:
            if item.id in self.checked:
                self.checked.remove(item.id)
            item.setCheckState(0, qt.Qt.Unchecked)

        for i in range(item.childCount()):
            self.check_recursive(item.child(i), checked)

    def item_color_changed(self, btn):
        color = btn.color()
        self.set_label_color(btn.id, btn.color())
        
    def set_label_color(self, label_id, color, recursive=True, emit=True):
        item = self.labels_by_id[label_id]['item']
        btn = self.labels_by_id[label_id]['btn']
        with SignalBlock(btn.sigColorChanged, self.item_color_changed):
            btn.setColor(color)
        if recursive:
            for i in range(item.childCount()):
                ch = item.child(i)
                self.set_label_color(ch.id, color, recursive=recursive, emit=False)
        if emit:
            self.labels_changed.emit()

    def lookup_table(self):
        lut = np.zeros((2**16, 4), dtype=np.ubyte)
        for id in self.checked:
            if id >= lut.shape[0]:
                continue
            lut[id] = self.labels_by_id[id]['btn'].color(mode='byte')
        return lut

    def color_by_layer(self, root=None):
        try:
            unblock = False
            if not isinstance(root, qt.QTreeWidgetItem):
                self.blockSignals(True)
                unblock = True
                root = self.labels_by_acronym[b'Isocortex']['item']

            name = str(root.text(1))
            if ', layer' in name.lower():
                layer = name.split(' ')[-1]
                layer = {'1': 0, '2': 1, '2/3': 2, '4': 3, '5': 4, '6a': 5, '6b': 6}[layer]
                self.set_label_color(root.id, pg.intColor(layer, 10), recursive=False, emit=False)

            for i in range(root.childCount()):
                self.color_by_layer(root.child(i))
        finally:
            if unblock:
                self.blockSignals(False)
                self.labels_changed.emit()

    def reset_colors(self):
        try:
            self.blockSignals(True)
            for k,v in self.labels_by_id.items():
                self.set_label_color(k, v['btn'].defaultColor, recursive=False, emit=False)
        finally:
            self.blockSignals(False)
            self.labels_changed.emit()

    def describe(self, id):
        if id not in self.labels_by_id:
            return "Unknown label: %d" % id
        descr = []
        item = self.labels_by_id[id]['item']
        name = str(item.text(1))
        while item is not self.labels_by_acronym[b'root']['item']:
            descr.insert(0, str(item.text(0)))
            item = item.parent()
        return '[%d]' % id + ' > '.join(descr) + "  :  " + name


class AtlasImageItem(qt.QGraphicsItemGroup):
    class SignalProxy(qt.QObject):
        mouseHovered = qt.Signal(object)  # id
        mouseClicked = qt.Signal(object)  # id

    def __init__(self):
        self._sigprox = AtlasImageItem.SignalProxy()
        self.mouseHovered = self._sigprox.mouseHovered
        self.mouseClicked = self._sigprox.mouseClicked

        qt.QGraphicsItemGroup.__init__(self)
        self.atlas_img = pg.ImageItem(levels=[0,1])
        self.label_img = pg.ImageItem()
        self.atlas_img.setParentItem(self)
        self.label_img.setParentItem(self)
        self.label_img.setZValue(10)
        self.label_img.setOpacity(0.5)
        self.set_overlay('Multiply')

        self.label_colors = {}
        self.setAcceptHoverEvents(True)

    def set_data(self, atlas, label, scale=None):
        self.label_data = label
        self.atlas_data = atlas
        if scale is not None:
            self.resetTransform()
            self.setScale(scale[0])
        self.atlas_img.setImage(self.atlas_data, autoLevels=False)
        self.label_img.setImage(self.label_data, autoLevels=False)  

    def set_lut(self, lut):
        self.label_img.setLookupTable(lut)

    def set_overlay(self, overlay):
        mode = getattr(qt.QPainter, 'CompositionMode_' + overlay)
        self.label_img.setCompositionMode(mode)

    def set_label_opacity(self, o):
        self.label_img.setOpacity(o)

    def setLabelColors(self, colors):
        self.label_colors = colors

    def hoverEvent(self, event):
        if event.isExit():
            return

        try:
            id = self.label_data[int(event.pos().x()), int(event.pos().y())]
        except (IndexError, AttributeError):
            return
        self.mouseHovered.emit(id)

    def mouseClickEvent(self, event):
        id = self.label_data[int(event.pos().x()), int(event.pos().y())]
        self.mouseClicked.emit([event, id])

    def boundingRect(self):
        return self.label_img.boundingRect()

    def shape(self):
        return self.label_img.shape()


class RulerROI(pg.ROI):
    """
    ROI subclass with one rotate handle, one scale-rotate handle and one translate handle. Rotate handles handles define a line. 
    
    ============== =============================================================
    **Arguments**
    positions      (list of two length-2 sequences) 
    **args         All extra keyword arguments are passed to ROI()
    ============== =============================================================
    """
    
    def __init__(self, pos, size, **args):
        pg.ROI.__init__(self, pos, size, **args)
        self.ab_vector = (0, 0, 0)  # This is the vector pointing up/down from the origin
        self.ac_vector = (0, 0, 0)  # This is the vector pointing across form the orign
        self.origin = (0, 0, 0)     # This is the origin
        self.ab_angle = 90  # angle on the ab_vector
        self.ac_angle = 0   # angle of the ac_vector 
        self.addRotateHandle([0, 0.5], [1, 1])
        self.addScaleRotateHandle([1, 0.5], [0.5, 0.5])
        self.addTranslateHandle([0.5, 0.5])
        self.addFreeHandle([0, 1], [0, 0])  
        self.addFreeHandle([0, 0], [0, 0])
        self.newRoi = pg.ROI((0, 0), [1, 5], parent=self, pen=pg.mkPen('w', style=qt.Qt.DotLine))

    def paint(self, p, *args):
        pg.ROI.paint(self, p, *args)
        h1 = self.handles[0]['item'].pos()
        h2 = self.handles[1]['item'].pos()
        h4 = self.handles[3]['item'] 
        h5 = self.handles[4]['item'] 
        h4.setVisible(False)
        h5.setVisible(False)
        p1 = p.transform().map(h1)
        p2 = p.transform().map(h2)

        vec = pg.Point(h2) - pg.Point(h1)
        length = vec.length()

        pvec = p2 - p1
        pvecT = pg.Point(pvec.y(), -pvec.x())
        pos = 0.5 * (p1 + p2) + pvecT * 40 / pvecT.length()

        angle = pg.Point(1, 0).angle(pg.Point(pvec)) 
        self.ab_angle = angle
        
        # Overlay a line to signal which side of the ROI is the back.
        if self.ac_angle > 0:
            self.newRoi.setVisible(True)
            self.newRoi.setPos(h5.pos())
        elif self.ac_angle < 0:
            self.newRoi.setVisible(True)
            self.newRoi.setPos(h4.pos())
        else:
            self.newRoi.setVisible(False)
            
        self.newRoi.setSize(pg.Point(self.size()[0], 0))
        
        p.resetTransform()

        txt = pg.siFormat(length, suffix='m') + '\n%0.1f deg' % angle + '\n%0.1f deg' % self.ac_angle
        opts = qt.QTextOption()
        opts.setAlignment(qt.Qt.AlignCenter | qt.Qt.AlignVCenter)
        p.drawText(qt.QRectF(pos.x() - 50, pos.y() - 50, 100, 100), txt, opts)

    def boundingRect(self):
        r = pg.ROI.boundingRect(self)
        pxl = self.pixelLength(pg.Point([1, 0]))
        if pxl is None:
            return r
        pxw = 50 * pxl
        return r.adjusted(-50, -50, 50, 50)

    def getArrayRegion(self, data, img, axes=(0, 1), order=1, rotation=0, **kwds):

        imgPts = [self.mapToItem(img, h.pos()) for h in self.getHandles()]

        d = pg.Point(imgPts[1] - imgPts[0]) # This is the xy direction vector
        o = pg.Point(imgPts[0])
       
        if rotation != 0:
            ac_vector, ac_vector_length, origin = self.get_affine_slice_params(data, img, rotation)
            rgn = fn.affineSlice(data, shape=(int(ac_vector_length), int(d.length())), vectors=[ac_vector, (d.norm().x(), d.norm().y(), 0)],
                                 origin=origin, axes=axes, order=order, **kwds) 
            
            # Save vector and origin
            self.origin = origin
            self.ac_vector = ac_vector * ac_vector_length
        else:
            rgn = fn.affineSlice(data, shape=(int(d.length()),), vectors=[pg.Point(d.norm())], origin=o, axes=axes, order=order, **kwds)
            # Save vector and origin
            self.ac_vector = (0, 0, data.shape[0])
            self.origin = (o.x(), o.y(), 0.0) 
        
        # save this as well
        self.ab_vector = (d.x(), d.y(), 0)
        self.ac_angle = rotation
        
        return rgn

    def get_affine_slice_params(self, data, img, rotation):
        """
        Use the position of this ROI handles to get a new vector for the slice view's x-z direction.
        """
        counter_clockwise = rotation < 0
        
        h1, h2, h3, h4, h5 = self.getHandles()
        origin_roi = self.mapToItem(img, h5.pos())
        left_corner = self.mapToItem(img, h4.pos())
        
        if counter_clockwise:
            origin = np.array([origin_roi.x(), origin_roi.y(), 0])
            end_point = np.array([left_corner.x(), left_corner.y(), data.shape[0]])
        else:
            origin = np.array([left_corner.x(), left_corner.y(), 0])
            end_point = np.array([origin_roi.x(), origin_roi.y(), data.shape[0]])

        new_vector = end_point - origin
        ac_vector_length = np.sqrt(new_vector.dot(new_vector))
        
        return (new_vector[0], new_vector[1], new_vector[2]) / ac_vector_length, ac_vector_length, (origin[0], origin[1], origin[2])
    
    def get_roi_size(self, ab_vector, ac_vector):
        """
        Returns the size of the ROI expected from the given vectors.
        """
        # Find the width
        w = pg.Point(ab_vector[0], ab_vector[1]) 
    
        # Find the length
        l = pg.Point(ac_vector[0], ac_vector[1])
        
        return w.length(), l.length()
    
    def get_ab_angle(self, with_ab_vector=None):
        """
        Gets ROI.ab_angle. If with_ab_vector is given, then the angle returned is with respect to the given vector 
        """
        if with_ab_vector is not None:
            corner = pg.Point(with_ab_vector[0], with_ab_vector[1])
            return corner.angle(pg.Point(1, 0))
        else:
            return self.ab_angle
        
    def get_ac_angle(self, with_ac_vector=None):
        """
        Gets ROI.ac_angle. If with_ac_vector is given, then the angle returned is with respect to the given vector 
        """
        if with_ac_vector is not None:
            l = pg.Point(with_ac_vector[0], with_ac_vector[1])  # Explain this. 
            corner = pg.Point(l.length(), with_ac_vector[2])
            
            if with_ac_vector[0] < 0:  # Make sure this points to the correct direction 
                corner = pg.Point(-l.length(), with_ac_vector[2])
            
            return pg.Point(0, 1).angle(corner)
        else:
            return self.ac_angle


class AtlasResolutionDialog(qt.QDialog):
    def __init__(self, resolutions, cached):
        qt.QDialog.__init__(self)
        self.setWindowTitle("Select CCF resolution to download")
        self.resize(400, 200)
        self.layout = qt.QGridLayout()
        self.setLayout(self.layout)
        self.radios = {}
        for i,res in enumerate(resolutions):
            if res in cached:
                extra = " (already cached)"
            else:
                extra = ""
            r = qt.QRadioButton("%d um%s" % (res, extra))
            self.layout.addWidget(r, i, 0, 1, 2)
            self.radios[res] = r
            r.resolution = res
        self.ok_btn = qt.QPushButton('Download')
        self.layout.addWidget(self.ok_btn, 4, 0)
        self.cancel_btn = qt.QPushButton('Cancel')
        self.layout.addWidget(self.cancel_btn, 4, 1)
        self.ok_btn.clicked.connect(self.ok_clicked)
        self.cancel_btn.clicked.connect(self.reject)
        for r in self.radios.values():
            r.toggled.connect(self.ok_btn.setEnabled)

    def exec(self):
        self.ok_btn.setEnabled(False)
        qt.QDialog.exec(self)

    def selected_resolution(self):
        for r in self.radios.values():
            if r.isChecked():
                return r.resolution
        return None

    def ok_clicked(self):
        if self.selected_resolution() is None:
            self.reject()
        else:
            self.accept()


def download(url, dest, chunksize=1000000):
    """Download a file from *url* and save it to *dest*, while displaying a
    progress bar.
    """
    req = urlopen(url)
    size = req.info().get('content-length')
    size = 0 if size is None else int(size)
    tmpdst = dest+'.partial'
    with pg.ProgressDialog("Downloading %0.2f MB:\n%s" % (size/1e6, url), maximum=size, nested=True) as dlg:
        try:
            with open(tmpdst, 'wb') as fh:
                tot = 0
                while True:
                    chunk = req.read(chunksize)
                    if len(chunk) == 0:
                        break
                    fh.write(chunk)
                    tot += len(chunk)
                    dlg.setValue(tot)
                    if dlg.wasCanceled():
                        raise Exception("User cancelled download.")
            os.rename(tmpdst, dest)
        finally:
            if os.path.isfile(tmpdst):
                os.remove(tmpdst)
