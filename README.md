Atlas Viewer for the Allen Institute Common Coordinate Framework
================================================================

Features
--------

* Display CCF atlas data sliced at arbitrary angles
* Color atlas regions based on their anatomical labels or by cortical layer
* Displays anatomical label of the atlas region under the mouse pointer
* Reusable PyQt widgets can be embedded into existing GUIs

The viewer downloads three pieces of data from the Allen Institute website:

* Atlas data: http://download.alleninstitute.org/informatics-archive/current-release/mouse_ccf/average_template/
* Label data: http://download.alleninstitute.org/informatics-archive/current-release/mouse_ccf/annotation/ccf_2015/
* Ontology: http://api.brain-map.org/api/v2/structure_graph_download/1.json

More information about the atlas data and ontology files is available at:
* http://help.brain-map.org/display/mouseconnectivity/API#API-DownloadAtlas
* http://help.brain-map.org/display/api/Downloading+an+Ontology%27s+Structure+Graph
* http://help.brain-map.org/display/api/Atlas+Drawings+and+Ontologies#AtlasDrawingsandOntologies-StructuresAndOntologies


Requirements
------------

* Python 3+
* PyQt5
* PyQtGraph
* numpy
* nrrd
* h5py 


Running the application
-----------------------

Start the viewer from the command prompt:

```
$ python viewer.py
```

The first time the viewer runs, it will download atlas data from the Allen Institute website.
Data is then converted into a format that is more memory- and processor-efficient; this process can take
several minutes depending on the resolution of the atlas/label files you select.


Setup
-----

Optionally, the package can be installed to make its functionality available 
to other applications

```
$ python setup.py install
```




