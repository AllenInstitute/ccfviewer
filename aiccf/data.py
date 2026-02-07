import os, sys, json
from collections import OrderedDict
import numpy as np
import pyqtgraph as pg
from MetaArray import MetaArray
from . import qt
from .ui import AtlasResolutionDialog, download


class CCFAtlasData(object):
    """Wrapper around CCF average image, annotation, and ontology to manage
    downloading, reformatting, and caching.
    """
    
    image_url = "http://download.alleninstitute.org/informatics-archive/current-release/mouse_ccf/average_template/average_template_{resolution}.nrrd"
    label_url = "http://download.alleninstitute.org/informatics-archive/current-release/mouse_ccf/annotation/ccf_2016/annotation_{resolution}.nrrd"
    ontology_url = "http://api.brain-map.org/api/v2/structure_graph_download/1.json"
    
    def __init__(self, cache_path=None, resolution=None):
        self.image = None
        self.label = None
        self.ontology = None
        self.available_resolutions = [10, 25, 50, 100]
        
        # Decide on a default cache path
        if cache_path is None:
            if sys.platform == 'win32':
                cache_path = os.path.join(os.getenv("APPDATA"), 'aiccf')
            else:
                cache_path = os.path.join(os.path.expanduser("~"), ".local", "share", 'aiccf')
        self._cache_path = cache_path
        
        # Have we already cached some resolutions of the atlas?
        self.cached_resolutions = {}
        for res in self.available_resolutions:
            image_file = os.path.join(cache_path, '%dum'%res, 'image.ma')
            label_file = os.path.join(cache_path, '%dum'%res, 'label.ma')
            if os.path.isfile(image_file) and os.path.isfile(label_file):
                self.cached_resolutions[res] = (image_file, label_file)
        
        # Which resolution to load?
        if resolution is None:
            if len(self.cached_resolutions) == 0:
                # offer to download and cache 
                resolution = self.download_and_cache()
            else:
                # by default, pick the highest resolution that has already been cached
                resolution = min(self.cached_resolutions.keys())
        elif resolution not in self.cached_resolutions:
            resolution = self.download_and_cache(resolution)
            
        self._image_cache_file, self._label_cache_file = self.cached_resolutions[resolution]
        self.load_image_cache()
        self.load_label_cache()

    def download_and_cache(self, resolution=None):
        """Download atlas data, convert to intermediate format, and store in cache
        folder.
        """
        if resolution is None:
            dlg = AtlasResolutionDialog(self.available_resolutions, self.cached_resolutions.keys())
            dlg.exec_()
            resolution = dlg.selected_resolution()
            if resolution is None:
                raise Exception("No atlas resolution selected.")

        cache_path = self.cache_path(resolution)
        if not os.path.exists(cache_path):
            os.makedirs(cache_path)
        
        with pg.ProgressDialog("Preparing %dum CCF data" % resolution, maximum=6, nested=True) as dlg: 
            image_url = self.image_url.format(resolution=resolution)
            image_file = os.path.join(cache_path, image_url.split('/')[-1])
            image_cache = os.path.join(cache_path, "image.ma")
            if not os.path.exists(image_file):
                download(image_url, image_file)
            dlg += 1
            
            label_url = self.label_url.format(resolution=resolution)
            label_file = os.path.join(cache_path, label_url.split('/')[-1])
            label_cache = os.path.join(cache_path, "label.ma")
            if not os.path.exists(label_file):
                download(label_url, label_file)
            dlg += 1
            
            onto_file = os.path.join(cache_path, 'ontology.json')
            if not os.path.exists(onto_file):
                download(self.ontology_url, onto_file)
            
            self.load_image_data(image_file)
            dlg += 1
            write_file(self.image, image_cache)
            dlg += 1
            
            self.load_label_data(label_file, onto_file)
            dlg += 1
            write_file(self.label, label_cache)
            dlg += 1

        self.cached_resolutions[resolution] = (image_cache, label_cache)
        return resolution

    def cache_path(self, resolution):
        return os.path.join(self._cache_path, '%dum'%resolution)

    @property
    def shape(self):
        return self.image.shape

    def load_image_data(self, filename):
        self.image = read_nrrd_atlas(filename)
        
    def load_label_data(self, label_file, ontology_file):
        self.label = read_nrrd_labels(label_file, ontology_file)
        self.ontology = self.label._info[-1]['ontology']
        
    def load_image_cache(self):
        """Load a MetaArray-format atlas image file.
        """
        filename = self._image_cache_file
        self.image = MetaArray(file=filename, readAllData=True)
        
    def load_label_cache(self):
        """Load a MetaArray-format atlas label file.
        """
        filename = self._label_cache_file
        self.label = MetaArray(file=filename, readAllData=True)
        self.ontology = self.label._info[-1]['ontology']
        
    def ccf_transform(self):
        """Return a 3D transform that maps from atlas voxel coordinates to CCF
        coordinates (in unscaled meters).
        """
        
    def stereotaxic_transform(self):
        """Return a 3D transform that maps from atlas voxel coodrinates to 
        stereotaxic coordinates.
        """

    
def read_nrrd_atlas(nrrd_file):
    """
    Download atlas files from:
      http://help.brain-map.org/display/mouseconnectivity/API#API-DownloadAtlas
    """
    try:
        import nrrd
    except ImportError:
        raise Exception("Could not import module 'nrrd'  (please install pynrrd)")

    data, header = nrrd.read(nrrd_file)

    # convert to ubyte to compress a bit
    # (no inplace multiply; nrrd returns read-only array)
    data = data * (255./data.max())  
    data = data.astype('ubyte')

    # data must have axes (anterior, dorsal, right)
    # rearrange axes to fit -- CCF data comes in (posterior, inferior, right) order.
    data = data[::-1, ::-1, :]

    # voxel size in um
    vxsize = 1e-6 * float(header['space directions'][0][0])

    info = [
        {'name': 'anterior', 'values': np.arange(data.shape[0]) * vxsize, 'units': 'm'},
        {'name': 'dorsal', 'values': np.arange(data.shape[1]) * vxsize, 'units': 'm'},
        {'name': 'right', 'values': np.arange(data.shape[2]) * vxsize, 'units': 'm'},
        {'vxsize': vxsize}
    ]
    ma = MetaArray(data, info=info)
    return ma


def read_nrrd_labels(nrrd_file, ontology_file):
    """
    Download label files from:
      http://help.brain-map.org/display/mouseconnectivity/API#API-DownloadAtlas

    Download ontology files from:
      http://api.brain-map.org/api/v2/structure_graph_download/1.json

      see:
      http://help.brain-map.org/display/api/Downloading+an+Ontology%27s+Structure+Graph
      http://help.brain-map.org/display/api/Atlas+Drawings+and+Ontologies#AtlasDrawingsandOntologies-StructuresAndOntologies

    This method compresses the annotation data down to a 16-bit array by remapping
    the larger annotations to smaller, unused values.
    """
    global onto, ontology, data, mapping, inds, vxsize, info, ma

    import nrrd

    with pg.ProgressDialog("Loading annotation file...", 0, 5, wait=0, nested=True) as dlg:
        print("Loading annotation file...")
        qt.processEvents()
        # Read ontology and convert to flat table
        onto = json.load(open(ontology_file, 'rb'))
        onto = parse_ontology(onto['msg'][0])
        l1 = max([len(row[2]) for row in onto])
        l2 = max([len(row[3]) for row in onto])
        ontology = np.array(onto, dtype=[('id', 'int32'), ('parent', 'int32'), ('name', 'S%d'%l1), ('acronym', 'S%d'%l2), ('color', 'S6')])
        if dlg.wasCanceled():
            return
        dlg += 1

        # read annotation data
        data, header = nrrd.read(nrrd_file)

        if dlg.wasCanceled():
            return
        dlg += 1

        # data must have axes (anterior, dorsal, right)
        # rearrange axes to fit -- CCF data comes in (posterior, inferior, right) order.
        data = data[::-1, ::-1, :]

        if dlg.wasCanceled():
            return
        dlg += 1

    # compress down to uint16
    print("Compressing..")
    u = np.unique(data)
    
    # decide on a 32-to-64-bit label mapping
    mask = u <= 2**16-1
    next_id = 2**16-1
    mapping = OrderedDict()
    inds = set()
    for i in u[mask]:
        mapping[i] = i
        inds.add(i)
   
    with pg.ProgressDialog("Remapping annotations to 16-bit (please be patient with me; this can take several minutes) ...", 0, (~mask).sum(), wait=0, nested=True) as dlg:
        qt.processEvents()
        for i in u[~mask]:
            while next_id in inds:
                next_id -= 1
            mapping[i] = next_id
            inds.add(next_id)
            data[data == i] = next_id
            ontology['id'][ontology['id'] == i] = next_id
            ontology['parent'][ontology['parent'] == i] = next_id
            if dlg.wasCanceled():
                return
            dlg += 1
        
    data = data.astype('uint16')
    mapping = np.array(list(mapping.items()))    
 
    # voxel size in um
    vxsize = 1e-6 * float(header['space directions'][0][0])

    info = [
        {'name': 'anterior', 'values': np.arange(data.shape[0]) * vxsize, 'units': 'm'},
        {'name': 'dorsal', 'values': np.arange(data.shape[1]) * vxsize, 'units': 'm'},
        {'name': 'right', 'values': np.arange(data.shape[2]) * vxsize, 'units': 'm'},
        {'vxsize': vxsize, 'ai_ontology_map': mapping, 'ontology': ontology}
    ]
    ma = MetaArray(data, info=info)
    return ma


def parse_ontology(root, parent=-1):
    ont = [(root['id'], parent, root['name'], root['acronym'], root['color_hex_triplet'])]
    for child in root['children']:
        ont += parse_ontology(child, root['id'])
    return ont


def write_file(data, filename):
    data_dir = os.path.dirname(filename)
    if data_dir != '' and not os.path.exists(data_dir):
        os.makedirs(data_dir)

    tmp = filename + '.tmp'
    if max(data.shape) > 200 and min(data.shape) > 200:
        data.write(tmp, chunks=(200, 200, 200))
    else:
        data.write(tmp)
        
    os.rename(tmp, filename)
