# h5nuvola

![alt text](https://github.com/ElettraSciComp/h5nuvola/blob/master/h5nuvola-logo.png)

HDFView in the cloud.

[HDF5](https://www.hdfgroup.org/) has become the standard scientific data and metadata container in neutron and photon facilities. There is a large number of supporting tools ranging from standalone browsers like [HDFView](https://support.hdfgroup.org/products/java/hdfview/) to python modules like [h5py](https://pypi.org/project/h5py/). We designed and developed a web-based equivalent for HDFView which adds additional functionality. We call it **h5nuvola**. Cloud **file browsing**, data **visualisation** services, and selective **exporting of data** are allowed. Its modular architecture includes an API facilitating data and metadata exploration through REST services. Back-end tasks are based on the Python framework Flask. HDF5 files are accessed through h5py. Bokeh plotting library handles the visualisation. The front-end uses HTML5, CSS, and JavaScript. A fully functional prototype of h5nuvola is planned to be integrated with Elettra’s [Virtual Unified Office](https://vuo.elettra.eu). Integration with Jupyter is in the roadmap.

# Features
## HDFView in the cloud

![alt text](https://github.com/ElettraSciComp/h5nuvola/blob/master/screenshots/h5nuvola-screenshot-1.png)

## Web interface
![alt text](https://github.com/ElettraSciComp/h5nuvola/blob/master/screenshots/h5nuvola-screenshot-2.png)

## Facility Portal integration
![alt text](https://github.com/ElettraSciComp/h5nuvola/blob/master/screenshots/h5nuvola-screenshot-3.png)


# Jupyter Notebook demo
Click on the link below to see a Jupyter Notebook live demo:

[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/carlosesreis/h5nuvola-notebook-demo/master?urlpath=%2Fapps%2Fh5nuvola.ipynb)

# Dependencies
* Python 2.7
  * Flask
  * h5py
  * Numpy
  * Bokeh
* JS
  * jsTree
  * jQuery