from ast import literal_eval
import json
from collections import OrderedDict
import numpy as np
import pyqtgraph as pg
import pyqtgraph.metaarray as metaarray
from pyqtgraph.Qt import QtGui, QtCore

from aiccf.ui import AtlasDisplayCtrl, LabelTree, AtlasSliceView
from aiccf import points_to_aff


class AtlasViewer(QtGui.QWidget):
    """Class that assembles all of the available UI elements into
    one widget.
    """
    def __init__(self, parent=None):
        self.atlas = None
        self.label = None

        QtGui.QWidget.__init__(self, parent)
        self.layout = QtGui.QGridLayout()
        self.setLayout(self.layout)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0,0,0,0)

        self.splitter = QtGui.QSplitter()
        self.layout.addWidget(self.splitter, 0, 0)

        self.view_widget = QtGui.QWidget()
        self.view_layout = QtGui.QGridLayout()
        self.view_widget.setLayout(self.view_layout)
        self.view_layout.setSpacing(0)
        self.view_layout.setContentsMargins(0,0,0,0)
        self.splitter.addWidget(self.view_widget)

        self.w1 = pg.GraphicsLayoutWidget()
        self.w2 = pg.GraphicsLayoutWidget()
        self.view1 = self.w1.addViewBox()
        self.view2 = self.w2.addViewBox()
        self.view1.setAspectLocked()
        self.view2.setAspectLocked()
        self.view1.invertY(False)
        self.view2.invertY(False)
        self.view_layout.addWidget(self.w1, 0, 0)
        self.view_layout.addWidget(self.w2, 1, 0)

        self.atlas_view = AtlasSliceView()
        self.atlas_view.sig_slice_changed.connect(self.sliceChanged)
        self.img1 = self.atlas_view.img1
        self.img2 = self.atlas_view.img2
        self.img2.mouseClicked.connect(self.mouseClicked)
        self.view1.addItem(self.img1)
        self.view2.addItem(self.img2)

        self.target = Target()
        self.target.setZValue(5000)
        self.view2.addItem(self.target)
        self.target.setVisible(False)

        self.view1.addItem(self.atlas_view.line_roi, ignoreBounds=True)
        self.view_layout.addWidget(self.atlas_view.zslider, 2, 0)
        self.view_layout.addWidget(self.atlas_view.angle_slider, 3, 0)
        self.view_layout.addWidget(self.atlas_view.lut, 0, 1, 3, 1)

        self.clipboard = QtGui.QApplication.clipboard()
        
        QtGui.QShortcut(QtGui.QKeySequence("Alt+Up"), self, self.slider_up)
        QtGui.QShortcut(QtGui.QKeySequence("Alt+Down"), self, self.slider_down)
        QtGui.QShortcut(QtGui.QKeySequence("Alt+Left"), self, self.tilt_left)
        QtGui.QShortcut(QtGui.QKeySequence("Alt+Right"), self, self.tilt_right)
        QtGui.QShortcut(QtGui.QKeySequence("Alt+1"), self, self.move_left)
        QtGui.QShortcut(QtGui.QKeySequence("Alt+2"), self, self.move_right)

        self.atlas_view.mouseHovered.connect(self.mouseHovered)
        self.atlas_view.mouseClicked.connect(self.mouseClicked)
        
        self.statusLabel = QtGui.QLabel()
        self.layout.addWidget(self.statusLabel, 1, 0, 1, 1)
        self.statusLabel.setFixedHeight(30)

        self.pointLabel = QtGui.QLabel()
        self.layout.addWidget(self.pointLabel, 2, 0, 1, 1)
        self.pointLabel.setFixedHeight(30)

        self.ctrl = QtGui.QWidget(parent=self)
        self.splitter.addWidget(self.ctrl)
        self.ctrl_layout = QtGui.QVBoxLayout()
        self.ctrl.setLayout(self.ctrl_layout)

        self.ctrl_layout.addWidget(self.atlas_view.display_ctrl)
        self.ctrl_layout.addWidget(self.atlas_view.label_tree)
        
        self.coordinateCtrl = CoordinatesCtrl(self)
        self.coordinateCtrl.coordinateSubmitted.connect(self.coordinateSubmitted)
        self.ctrl_layout.addWidget(self.coordinateCtrl)

    def set_data(self, atlas_data):
        self.atlas_view.set_data(atlas_data)
        self.view1.autoRange(items=[self.img1.atlas_img])
        self.coordinateCtrl.atlas_shape = atlas_data.shape
        self.label = atlas_data.label
        self.atlas = atlas_data.image
        
    def mouseHovered(self, id):
        self.statusLabel.setText(self.atlas_view.label_tree.describe(id))
        
    def renderVolume(self):
        import pyqtgraph.opengl as pgl
        import scipy.ndimage as ndi
        self.glView = pgl.GLViewWidget()
        img = np.ascontiguousarray(self.displayAtlas[::8,::8,::8])
        
        # render volume
        #vol = np.empty(img.shape + (4,), dtype='ubyte')
        #vol[:] = img[..., None]
        #vol = np.ascontiguousarray(vol.transpose(1, 2, 0, 3))
        #vi = pgl.GLVolumeItem(vol)
        #self.glView.addItem(vi)
        #vi.translate(-vol.shape[0]/2., -vol.shape[1]/2., -vol.shape[2]/2.)
        
        verts, faces = pg.isosurface(ndi.gaussian_filter(img.astype('float32'), (2, 2, 2)), 5.0)
        md = pgl.MeshData(vertexes=verts, faces=faces)
        mesh = pgl.GLMeshItem(meshdata=md, smooth=True, color=[0.5, 0.5, 0.5, 0.2], shader='balloon')
        mesh.setGLOptions('additive')
        mesh.translate(-img.shape[0]/2., -img.shape[1]/2., -img.shape[2]/2.)
        self.glView.addItem(mesh)

        self.glView.show()
     
    # mouse_point[0] contains the Point object.
    # mouse_point[1] contains the structure id at Point
    def mouseClicked(self, mouse_point):
        point, to_clipboard = self.getCcfPoint(mouse_point)
        self.pointLabel.setText(point)
        self.target.setVisible(True)
        self.target.setPos(self.view2.mapSceneToView(mouse_point[0].scenePos()))
        self.clipboard.setText(to_clipboard)

    # Get CCF point coordinate and Structure id
    # Returns two strings. One used for display in a label and the other to put in the clipboard
    # PIR orientation where x axis = Anterior-to-Posterior, y axis = Superior-to-Inferior and z axis = Left-to-Right
    def getCcfPoint(self, mouse_point):
        axis = self.atlas_view.display_ctrl.params['Orientation']

        # find real lims id
        ai_ontology_map = self.label._info[-1]['ai_ontology_map']
        match_index = np.argwhere(ai_ontology_map[:,1] == mouse_point[1])[0, 0]
        lims_str_id = ai_ontology_map[match_index, 0]
        
        # compute the 4x4 transform matrix
        a = self.scale_point_to_CCF(self.atlas_view.line_roi.origin)
        ab = self.scale_vector_to_PIR(self.atlas_view.line_roi.ab_vector)
        ac = self.scale_vector_to_PIR(self.atlas_view.line_roi.ac_vector)
        
        M0, M0i = points_to_aff.points_to_aff(a, np.array(ab), np.array(ac))

        # Find what the mouse point position is relative to the coordinate
        ab_length = np.linalg.norm(self.atlas_view.line_roi.ab_vector)
        ac_length = np.linalg.norm(self.atlas_view.line_roi.ac_vector)        
        p = (mouse_point[0].pos().x()/ac_length, mouse_point[0].pos().y()/ab_length)
        
        ccf_location = np.dot(M0i, [p[1], p[0], 0, 1]) # use the inverse transform matrix and the mouse point
        
        # These should be x, y, z
        p1 = float(ccf_location[0])
        p2 = float(ccf_location[1])
        p3 = float(ccf_location[2])

        if axis == 'right':
            point = "x: " + str(p1) + " y: " + str(p2) + " z: " + str(p3) + " StructureID: " + str(lims_str_id)
            clipboard_text = str(p1) + ";" + str(p2) + ";" + str(p3) + ";" + str(lims_str_id)
        elif axis == 'anterior':
            point = "x: " + str(p3) + " y: " + str(p2) + " z: " + str(p1) + " StructureID: " + str(lims_str_id)
            clipboard_text = str(p3) + ";" + str(p2) + ";" + str(p1) + ";" + str(lims_str_id)
        elif axis == 'dorsal':
            point = "x: " + str(p2) + " y: " + str(p3) + " z: " + str(p1) + " StructureID: " + str(lims_str_id)
            clipboard_text = str(p2) + ";" + str(p3) + ";" + str(p1) + ";" + str(lims_str_id)
        else:
            point = 'N/A'
            clipboard_text = 'NULL'

        # Convert matrix transform to a LIMS dictionary
        ob = points_to_aff.aff_to_lims_obj(M0, M0i)

        # clipboard_text = "{};{}".format(clipboard_text, roi_params)
        clipboard_text = "{};{}".format(clipboard_text, ob)

        return point, clipboard_text
    
    def scale_point_to_CCF(self, point):
        """
        Returns a tuple (x, y, z) scaled from Item coordinates to CCF coordinates
        
        Point is a tuple with values x, y, z (ordered) 
        """
        vxsize = self.atlas._info[-1]['vxsize'] * 1e6
        p_to_ccf = ((self.atlas.shape[1] - point[0]) * vxsize,
                    (self.atlas.shape[2] - point[1]) * vxsize,
                    (self.atlas.shape[0] - point[2]) * vxsize)
        return p_to_ccf
    
    def scale_vector_to_PIR(self, vector):
        """
        Returns a list representing a vector. The new vector is scaled to CCF coordinate size. Also orients the vector to PIR orientaion.
        
        Vector must me specified as a list
        """
        p_to_ccf = []
        for p in vector:
            p_to_ccf.append(-(p * self.atlas._info[-1]['vxsize'] * 1e6))  # Need to use negative since using PIR orientation
        return p_to_ccf

    def ccf_point_to_view(self, pos):
        """
        This function translates a ccf's position to the view's coordinates.
                
        The pos is a tuple with values x, y, z
        """
        vxsize = self.atlas._info[-1]['vxsize'] * 1e6
        return ((self.atlas_view.atlas.shape[1] - (pos[0] / vxsize)) * self.atlas_view.scale[0],
                (self.atlas_view.atlas.shape[2] - (pos[1] / vxsize)) * self.atlas_view.scale[1],
                (self.atlas_view.atlas.shape[0] - (pos[2] / vxsize)) * self.atlas_view.scale[1])

    def vector_to_view(self, vector):
        """
        Scales vector to view coordinate size. vector is a tuple with x, y, z (in that order)   
        """
        vxsize = self.atlas._info[-1]['vxsize'] * 1e6
        new_point = ((vector[0] / vxsize) * self.atlas_view.scale[0],
                     (vector[1] / vxsize) * self.atlas_view.scale[1],
                     (vector[2] / vxsize) * self.atlas_view.scale[1])  
        return new_point
      
    # These are here to test. Add to coord_arg to test
    # to_pos = self.st_to_tuple(coord_args[5])
    # to_size = self.st_to_tuple(coord_args[6])
    # to_ab_angle = float(coord_args[7])
    # to_ac_angle = float(coord_args[8])
    # orientation = coord_args[9]    
    def coordinateSubmitted(self):
        if self.atlas_view.display_ctrl.params['Orientation'] != "right":
            displayError('Set Coordinate function is only supported with Right orientation')
            return
        
        coord_args = str(self.coordinateCtrl.line.text()).split(';')
        
        vxsize = self.atlas._info[-1]['vxsize'] * 1e6
        x = float(coord_args[0])
        y = float(coord_args[1])
        z = float(coord_args[2])
        
        if len(coord_args) < 3:
            return
        
        if len(coord_args) <= 4:
            # When only 4 points are given, assume point needs to be set using orientation == 'right'
            translated_x = (self.atlas.shape[1] - (float(coord_args[0])/vxsize)) * self.atlas_view.scale[0] 
            translated_y = (self.atlas.shape[2] - (float(coord_args[1])/vxsize)) * self.atlas_view.scale[0] 
            translated_z = (self.atlas.shape[0] - (float(coord_args[2])/vxsize)) * self.atlas_view.scale[0] 
            roi_origin = (translated_x, 0.0)
            to_size = (self.atlas.shape[2] * self.atlas_view.scale[1], 0.0) 
            to_ab_angle = 90
            to_ac_angle = 0
            target_p1 = translated_z 
            target_p2 = translated_y
        else:
            transform = literal_eval(coord_args[4])

            # Use LIMS matrices to get the origin and vectors of the plane
            M1, M1i = points_to_aff.lims_obj_to_aff(transform)
            origin, ab_vector, ac_vector = points_to_aff.aff_to_origin_and_vectors(M1i)
            
            target_p1, target_p2 = self.get_target_position([x, y, z, 1], M1, ab_vector, ac_vector, vxsize)
            
            # Put the origin and vectors back to view coordinates
            roi_origin = np.array(self.ccf_point_to_view(origin))
            ab_vector = -np.array(self.vector_to_view(ab_vector))
            ac_vector = -np.array(self.vector_to_view(ac_vector))
                
            to_ac_angle = self.atlas_view.line_roi.get_ac_angle(ac_vector)
            
            # Where the origin of the ROI should be
            if to_ac_angle > 0:
                roi_origin = ac_vector + roi_origin  
                
            to_size = self.atlas_view.line_roi.get_roi_size(ab_vector, ac_vector)
            to_ab_angle = self.atlas_view.line_roi.get_ab_angle(ab_vector)
        
        self.target.setPos(target_p1, target_p2)
        self.atlas_view.line_roi.setPos(pg.Point(roi_origin[0], roi_origin[1]))
        self.atlas_view.line_roi.setSize(pg.Point(to_size))
        self.atlas_view.line_roi.setAngle(to_ab_angle) 
        self.atlas_view.angle_slider.setValue(int(to_ac_angle))
        self.target.setVisible(True)  # TODO: keep target visible when coming back to the same slice... how?
       
    def get_target_position(self, ccf_location, M, ab_vector, ac_vector, vxsize):
        """
        Use affine transform matrix M to map ccf coordinate back to original coordinates  
        """
        img_location = np.dot(M, ccf_location)
        
        p1 = (np.linalg.norm(ac_vector) / vxsize * img_location[1]) * self.atlas_view.scale[0]
        p2 = (np.linalg.norm(ab_vector) / vxsize * img_location[0]) * self.atlas_view.scale[0]
        
        return p1, p2

    def slider_up(self):
        self.atlas_view.angle_slider.triggerAction(QtGui.QAbstractSlider.SliderSingleStepAdd)
        
    def slider_down(self):
        self.atlas_view.angle_slider.triggerAction(QtGui.QAbstractSlider.SliderSingleStepSub)
        
    def tilt_left(self):
        self.atlas_view.line_roi.rotate(1)
        
    def tilt_right(self):
        self.atlas_view.line_roi.rotate(-1)
        
    def move_right(self):
        # print '-- Pos'
        # print self.line_roi.pos()
        self.atlas_view.line_roi.setPos((self.atlas_view.line_roi.pos().x() + .0001, self.atlas_view.line_roi.pos().y()))
        
    def move_left(self):
        # print '-- Pos'
        # print self.line_roi.pos()
        self.atlas_view.line_roi.setPos((self.atlas_view.line_roi.pos().x() - .0001, self.atlas_view.line_roi.pos().y()))

    def sliceChanged(self):
        self.view2.autoRange(items=[self.img2.atlas_img])
        self.target.setVisible(False)
    
    def closeEvent(self, ev):
        self.view1.close()
        self.view2.close()
        self.atlas_view.close()

    

class CoordinatesCtrl(QtGui.QWidget):
    coordinateSubmitted = QtCore.Signal()
    
    def __init__(self, parent=None):
        QtGui.QWidget.__init__(self, parent)
        self.layout = QtGui.QGridLayout()
        self.setLayout(self.layout)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.atlas_viewer = parent
        
        self.line = QtGui.QLineEdit(self)
        self.line.returnPressed.connect(self.set_coordinate)
        self.layout.addWidget(self.line, 0, 0)

        self.btn = QtGui.QPushButton('Set Coordinate', self)
        self.layout.addWidget(self.btn, 1, 0)
        self.btn.clicked.connect(self.set_coordinate)
    
    def set_coordinate(self):
        errors = self.validate_location()
        if not errors:
            self.coordinateSubmitted.emit()
        else:
            displayError(errors)
            
    def validate_location(self):
        location = self.line.text()
        if location:
            tokens = str(self.line.text()).split(';')
            if len(tokens) < 3:
                return "Coordinate is malformed"
            elif len(tokens) == 3 or len(tokens) == 4:
                errors = self.target_within_range(float(tokens[0]), float(tokens[1]), float(tokens[2])) 
            else:
                errors = self.target_within_range(float(tokens[0]), float(tokens[1]), float(tokens[2]))
                
            return errors
        else:
            return "No coordinate provided"
    
    def target_within_range(self, x, y, z):

        vxsize = self.atlas_viewer.atlas._info[-1]['vxsize'] * 1e6
        error = ""
        if z > (self.atlas_shape[2] * vxsize) or z < 0:
            error += "z coordinate {} is not within CCF range".format(z)
        if x > self.atlas_shape[0] * vxsize or x < 0:
            error += " x coordinate {} is not within CCF range".format(x)
        if y > self.atlas_shape[1] * vxsize or y < 0:
            error += " y coordinate {} is not within CCF range".format(y)
        
        return error


class Target(pg.GraphicsObject):
    def __init__(self, movable=True):
        pg.GraphicsObject.__init__(self)
        self._bounds = None
        self.color = (255, 255, 0)

    def boundingRect(self):
        if self._bounds is None:
            # too slow!
            w = self.pixelLength(pg.Point(1, 0))
            if w is None:
                return QtCore.QRectF()
            h = self.pixelLength(pg.Point(0, 1))
            # o = self.mapToScene(QtCore.QPointF(0, 0))
            # w = abs(1.0 / (self.mapToScene(QtCore.QPointF(1, 0)) - o).x())
            # h = abs(1.0 / (self.mapToScene(QtCore.QPointF(0, 1)) - o).y())
            self._px = (w, h)
            w *= 21
            h *= 21
            self._bounds = QtCore.QRectF(-w, -h, w*2, h*2)
        return self._bounds

    def viewTransformChanged(self):
        self._bounds = None
        self.prepareGeometryChange()

    def paint(self, p, *args):
        p.setRenderHint(p.Antialiasing)
        px, py = self._px
        w = 4 * px
        h = 4 * py
        r = QtCore.QRectF(-w, -h, w*2, h*2)
        p.setPen(pg.mkPen(self.color))
        p.setBrush(pg.mkBrush(0, 0, 255, 100))
        p.drawEllipse(r)
        p.drawLine(pg.Point(-w*2, 0), pg.Point(w*2, 0))
        p.drawLine(pg.Point(0, -h*2), pg.Point(0, h*2))


def displayError(error):
    print(error)
    err = QtGui.QErrorMessage()
    err.showMessage(error)
    err.exec_()


def displayMessage(message):
    box = QtGui.QMessageBox()
    box.setIcon(QtGui.QMessageBox.Information)
    box.setText(message)
    box.setStandardButtons(QtGui.QMessageBox.Ok)
    box.exec_()
