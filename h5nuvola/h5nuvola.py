#!/usr/bin/env python

"""H5 Nuvola - VUO integration 
versions:
h5py = 2.7.1
numpy = 1.13.0
json = 2.0.9
flask = 1.0.3
werkzeug = 0.15.4
bokeh = 0.13.0 -> 1.2.0
"""

import re
import requests
import urllib
import webbrowser
import multiprocessing
import os
import pwd
import json
import time
import sys
import hashlib
import ssl

import h5py as h5
import numpy as np


from flask import Flask, request, redirect, url_for, render_template, make_response, Response
from werkzeug.utils import secure_filename

from bokeh.models import ColumnDataSource, HoverTool, CustomJS
from bokeh.plotting import figure
from bokeh.embed import components, json_item
from bokeh.models.widgets import DataTable, DateFormatter, TableColumn, Dropdown, NumberFormatter
from bokeh.colors import RGB
from bokeh.layouts import widgetbox
from bokeh.palettes import Greys
from bokeh.resources import INLINE
from bokeh.core.properties import Dict

##########################################################################
#
# Global variables 
#

# VUO lab
with open('/opt/vuo-h5nuvola/h5nuvola/h5nuvola/h5nuvola.config') as json_config:
    config_dict = json.load(json_config)
vlab_hash = str(config_dict.get("vlab_hash")) 

# jQuery File Tree 
fnfilter = lambda fn: True
dfilter = lambda d: True
extension_filter = ['.h5', '.hdf5'] # select desired file extensions to show

# h5 files manipulation
hf_dict = {} # dictionary object to store h5 file object, items, attributes and properties
hf_objects = []

##########################################################################
#
# Python auxiliar methods for file browser and h5 files manipulations
#

# Routine for remote file browsing 
def get_files_target(d, fnfilter, dfilter, rel, user_name, queue):
    fns_dirs_queue = {}
    uid = pwd.getpwnam(user_name).pw_uid
    os.setuid(uid)
    try:
        d = os.path.expanduser(d)
        dirs = []
        fns = []
        for fn in sorted(os.listdir(d)):
            ffn = os.path.join(d, fn)
            if not rel:
                fn = ffn
            if os.path.isdir(ffn):
                if dfilter(ffn):
                    dirs.append(fn)
            else:
                if fnfilter(ffn):
                    if extension_filter == ['*.*']:
                        fns.append(fn)
                    else:
                        if os.path.splitext(fn)[1] not in extension_filter:
                            pass
                        else:
                            fns.append(fn)

        fns_dirs_queue["fns"] = fns
        fns_dirs_queue["dirs"] = dirs
        
        queue.put(fns_dirs_queue)

    except Exception as E:
        print 'Could not load directory: %s' % str(E)
        fns_dirs_queue["exception"] = E

# Read h5 files and retrieve children objects from the root group 
def read_h5_target(filepath, user_name, queue):   
    uid = pwd.getpwnam(user_name).pw_uid    
    os.setuid(uid)    
    
    hf_dict = {}
    hf_dict[filepath] = {}
   
    try:
        with h5.File(filepath) as hf:
            # collect objects to render on template
            hf_name = str(hf.filename).split('/')[-1]
            hf_dict[filepath]['hf_name'] = hf_name

            hf_objects = []
            hf.visititems(hf_visit) # update hf_objects
            hf_dict[filepath]['hf_objects'] = hf_objects

            root_attrs=[]
            if hf.attrs.keys() == []: # if there is no attributes
                pass
            else:            
                for key in hf.attrs.keys():
                    root_attrs.append([key, hf.attrs[key]])
            hf_dict[filepath]['root_attrs'] = root_attrs      
            root_properties = [ hf_name, 'group', root_attrs, True, 'Group size', str(len(hf.items())) ]
            hf_dict[filepath]['root_properties'] = root_properties
            hf_root_items = get_hf_items(hf.items())
            hf_dict[filepath]['hf_root_items'] = hf_root_items
            hf_new_items = [[str(0)]]
            hf_dict[filepath]['hf_new_items'] = hf_new_items 
            
            hf.close()

            queue.put(hf_dict) # send content back to father process
    except IOError:
        print "IOError: user %s can't read file %s"%(user_name, filepath)

# Expand h5Tree 
def expand_tree_target(user_name, filepath, node_selected, queue):
    global hf_objects
    uid = pwd.getpwnam(user_name).pw_uid
    os.setuid(uid)
    try:    
        with h5.File(filepath) as hf:

            hf_objects = []
            hf.visititems(hf_visit)

            for obj in hf_objects:                        
                    if str(obj.name) == node_selected:                        
                        if len(obj.items()) != 0:
                            hf_new_items = get_hf_items(obj.items())                    
                        else:
                            hf_new_items = [[str(1)]]
            
            queue.put(hf_new_items) # send content back to parent process       
    except IOError:
        print "IOError: user %s can't read file %s"%(user_name, filepath)

# Called by expand_tree_traget
def hf_visit(name, obj):
    global hf_objects    
    hf_objects.append(obj)

# Retrieve attributes, type (group or dataset), children, dtype and dshape from h5 objects
def get_hf_items(items):
    l = []
    for item in items:
        attrs = []
        tp = ''
        children = None
        dtype = ''
        dshape = ''
        if item[1].attrs.keys() == []: # if there is no attributes
            pass
        else:            
            for key in item[1].attrs.keys():                
                if type(item[1].attrs[key] == type(np.zeros((0,1)))): # if attibute is an array
                    attrs.append([key, str(item[1].attrs[key])]) # convert attribute to str
                else:                    
                    attrs.append([key, item[1].attrs[key]])
        if type(item[1]) == h5._hl.dataset.Dataset:
            if h5.check_dtype(vlen=item[1].dtype) == str:
                dtype = 'string'
            else:
                dtype = str(item[1].dtype)            
            dshape = str(list(item[1].shape))
            tp = 'dataset'
            children = False
        else:            
            tp = 'group'
            dtype = 'Group size'
            dshape = str(len(item[1].items()))
            if len(item[1].items()) == 0:
                children = False
            else:
                children = True
        l.append( [str(item[1].name), #0
                   tp, #1
                   attrs, #2
                   children, #3
                   dtype, #4
                   dshape] ) #5
    return l

##########################################################################
#
# Bokeh plotting routines - raw, curve and image
#

def create_bokeh_tools():
    bokeh_tools = ["pan","wheel_zoom","box_zoom","reset","save","box_select"]
    hover = HoverTool(tooltips=[
                ("pixel_value", "@image{0.00}"),
                ("point_value", "$y{0.00}"),            
                ("(x,y)", "($x{0.},$y{0.})"),            
            ])
    bokeh_tools.append(hover)
    return bokeh_tools

def bokeh_to_json_item(items):
    bokeh_json_items = [json_item(item) for item in items]
    return bokeh_json_items

def bokeh_table_target(user_name, filepath, dataset_name, queue):
    uid = pwd.getpwnam(user_name).pw_uid
    os.setuid(uid)    
    try:
        with h5.File(filepath) as hf:
            data = hf[dataset_name][()]            
        if type(data) == str: # String dataset            
            table = dict(x=[data])
            columns = [
                TableColumn( field='x', title='0', width=400, sortable=False )
            ]
            width=400
            height=200
            table_source = ColumnDataSource(table)
            data_table = DataTable(source=table_source, columns=columns,                            
                                fit_columns=False, sizing_mode="scale_width",
                                width=width, height=height,
                                selectable=True, sortable=False)
            
            # convert bokeh model obj into json_item to be embedded in HTML
            bokeh_json_item_tables = bokeh_to_json_item([data_table])
            
            # send data back to parent process through the queue            
            queue.put(bokeh_json_item_tables)

        else:
            if data.ndim == 0: # Scalar dataset
                table = dict( x=[data] )
                columns = [
                    TableColumn( field='x', title='0', width=100,
                                sortable=False, formatter=NumberFormatter(format="0,0.0000000000") )
                ]
                width=200
                height=200
                table_source = ColumnDataSource(table)
                data_table = DataTable(source=table_source, columns=columns,                            
                                    fit_columns=False, sizing_mode="scale_width",
                                    width=width, height=height,
                                    selectable=True, sortable=False)
                
                bokeh_json_item_tables = bokeh_to_json_item([data_table])            
                queue.put(bokeh_json_item_tables)

            elif data.ndim == 1: # 1D dataset                
                table = dict( x=data.tolist() )
                columns = [
                    TableColumn( field='x', title='0', width=100,
                                sortable=False, formatter=NumberFormatter(format="0,0.0000000000") )
                ]
                width=200
                height=800
                table_source = ColumnDataSource(table)
                data_table = DataTable(source=table_source, columns=columns,                            
                                    fit_columns=False, sizing_mode="scale_width",
                                    width=width, height=height,
                                    selectable=True, sortable=False)                
                
                              
                bokeh_json_item_tables = bokeh_to_json_item([data_table])            
                queue.put(bokeh_json_item_tables)

            elif data.ndim == 2: # 2D dataset
                table = {}
                i = 0
                columns = []
                for column in data.transpose():
                    table.update({str(i):column})
                    columns.append( TableColumn( field=str(i), title=str(i), width=100,
                                                sortable=False, formatter=NumberFormatter(format="0,0.0000000000") ) )
                    i = i + 1
                width=800
                height=800
                table_source = ColumnDataSource(table)            
                data_table = DataTable(source=table_source, columns=columns,                            
                                    fit_columns=False, sizing_mode="scale_width",
    ##                                   width=width, height=height,
                                    selectable=True, sortable=False, editable=False)

                bokeh_json_item_tables = bokeh_to_json_item([data_table])            
                queue.put(bokeh_json_item_tables)

            elif data.ndim == 3: # 3D dataset
                                
                tables = []
                for i in np.arange(0,data.shape[2]):
                    table = {}
                    j = 0
                    columns = []
                    for column in data[:,:,i].transpose():
                        table.update({str(j):column})
                        columns.append( TableColumn( field=str(j), title=str(j), width=100, sortable=False ) )
                        # print "table i=%d, j=%d"%(i, j)    
                        j = j + 1
                        
                    width = 800
                    height = 800
                    table_source = ColumnDataSource(table)
                    data_table = DataTable(source=table_source, columns=columns,                            
                                        fit_columns=False, sizing_mode="scale_width",
                                        width=width, height=height,
                                        selectable=True, sortable=False)
                    tables.append(data_table)                               

                bokeh_json_item_tables = bokeh_to_json_item(tables)            
                queue.put(bokeh_json_item_tables)               
                
    except IOError:
        print "IOError: user %s can't read file %s"%(user_name, filepath)

def bokeh_plot_target(user_name, filepath, dataset_name, queue):    
    uid = pwd.getpwnam(user_name).pw_uid
    os.setuid(uid)
    try:
        with h5.File(filepath) as hf:
            data = hf[dataset_name][()]
    
        if data.ndim == 0:
            bokeh_tools = create_bokeh_tools()
            y=[data]
            x=[0]
            source = ColumnDataSource(data=dict(x=x, y=y))
            plot = figure(title=dataset_name.split('/')[-1], toolbar_location="above",
                        sizing_mode="scale_both", tools=bokeh_tools)
            plot.line('x', 'y', source=source, legend=dataset_name.split('/')[-1],
                    line_width=3, line_alpha=0.6, line_color=RGB(0,158,234))
            plot.circle('x', 'y', source=source, fill_color="white", size=10)
            
            bokeh_json_item_plots = bokeh_to_json_item([plot])            
            queue.put(bokeh_json_item_plots)
        
        elif data.ndim == 1:
            bokeh_tools = create_bokeh_tools()
            y = data
            x = np.arange(data.shape[0])

            source = ColumnDataSource(data=dict(x=x, y=y))
            
            plot = figure(title=dataset_name.split('/')[-1], toolbar_location="above",
                        sizing_mode="scale_both", tools=bokeh_tools)
            plot.line('x', 'y', source=source, legend=dataset_name.split('/')[-1],
                    line_width=3, line_alpha=0.6, line_color=RGB(0,158,234))
            plot.circle('x', 'y', source=source, fill_color="white", size=10)

            bokeh_json_item_plots = bokeh_to_json_item([plot])            
            queue.put(bokeh_json_item_plots)           
        
        elif data.ndim == 2:
            plots = []
            i = 0
            for p in data:
                bokeh_tools = create_bokeh_tools()
                y = p
                x = np.arange(p.shape[0])

                source = ColumnDataSource(data=dict(x=x, y=y))

                p = figure(title=dataset_name.split('/')[-1], toolbar_location="above",
                        sizing_mode="scale_both", tools=bokeh_tools)
                p.line('x', 'y', source=source, legend=dataset_name.split('/')[-1],
                    line_width=3, line_alpha=0.6, line_color=RGB(0,158,234))
                p.circle('x', 'y', source=source, fill_color="white", size=10)
                plots.append(p)
                print str(i)
                i += 1

            bokeh_json_item_plots = bokeh_to_json_item(plots)            
            queue.put(bokeh_json_item_plots)
        
        elif data.ndim == 3:
            print "3D data"
            # Try plotly 3D scatter, 3D isosurface,           
    
    except IOError:
        print "IOError: user %s can't read file %s"%(user_name, filepath)

def bokeh_image_target(user_name, filepath, dataset_name, queue):
    uid = pwd.getpwnam(user_name).pw_uid
    os.setuid(uid)
    try:
        with h5.File(filepath) as hf:
            data = hf[dataset_name][()]       
        if data.ndim == 2:
            bokeh_tools = create_bokeh_tools()
            plot = figure(title=dataset_name.split('/')[-1], toolbar_location="above",
                        sizing_mode="scale_both", aspect_ratio=1.5, tools=bokeh_tools,
                        max_height=1200, # height_policy="fit",
                        max_width=1500, # width_policy="fit",
                        x_range=(0,data.shape[0]), y_range=(0,data.shape[1]))
            plot.image(image=[data], x=0, y=0, dw=data.shape[0], dh=data.shape[1])
            
            bokeh_json_item_images = bokeh_to_json_item([plot])                    
            queue.put(bokeh_json_item_images)
        
        elif data.ndim == 3:
            if 1 in data.shape: # one of the dimensions are 1, means it is a 2D image
                ind = data.shape.index(1)
                if ind == 0:
                    new_shape = (data.shape[1], data.shape[2])
                elif ind == 1:
                    new_shape = (data.shape[0], data.shape[2])
                else:
                    new_shape = (data.shape[0], data.shape[1])
                
                data = data.reshape(new_shape)
                bokeh_tools = create_bokeh_tools()
                plot = figure(title=dataset_name.split('/')[-1], toolbar_location="above",
                            sizing_mode="scale_both", aspect_ratio="auto", height_policy="fit", tools=bokeh_tools,
                            x_range=(0,data.shape[0]), y_range=(0,data.shape[1]))
                plot.image(image=[data], x=0, y=0, dw=data.shape[0], dh=data.shape[1])
                
                bokeh_json_item_images = bokeh_to_json_item([plot])                    
                queue.put(bokeh_json_item_images)

            else:
                pass
                # Embed Plotly in HTML
                # https://blog.heptanalytics.com/2018/08/07/flask-plotly-dashboard/
                # Try plotly 3D surface, 3D volume
    
    except IOError:
        print "IOError: user %s can't read file %s"%(user_name, filepath)


##########################################################################
#
# VUO auxiliar functions - vuo id, vlab function call 
#

def get_vuo_user(cookie):
    vuo_function = 'https://vuo.elettra.eu/pls/vuo/vuo_sso.detail' # PL SQL function
    r = requests.get(vuo_function, params={'cookie': cookie , 'what_detail': 'unix'})
    response = str(r.text)[:-1] #  exclude '\n' at the end of the string
    response = response.split(':') # take each field of the response, convert to a list
    print(response)
    if response[0] == 'OK':
        response_dic = {
                            'status': response[0],
                            'vuo_user_id': response[1],
                            'unix_user_name': response[2],
                            'unix_user_id': response[3],
                            'unix_group_id': response[4]
                        }
    else:
        response_dic = {
                            'status': response[0],
                            'redirect_url': ':'.join(response[1:3]).replace('trieste.it', 'eu')
                        }
    return response_dic

def vlab_call(vuo_user_id, investigation_id ):    
    vlab_hash_digested = hashlib.sha1(vlab_hash + vuo_user_id + investigation_id).hexdigest()
    vlab_function = 'https://vuo.elettra.eu/pls/vuo/vlab.sm_get_investigation_info'

    r = requests.get(vlab_function, params={'FRM_HASH':vlab_hash_digested,
                                            'FRM_USR_ID':vuo_user_id,
                                            'FRM_INVESTIGATION_ID':investigation_id})
    
    response = str(r.text)[:-1] #  exclude '\n' at the end of the string
    response = response.split(':')    

    if response[0] == 'OK':
        unix_user_id = response[1].split('/')[0] # rertieve unix_user_id
        unix_user_name = pwd.getpwuid(int(unix_user_id)).pw_name # 'name.surname'
        h5nuvola_user_name = unix_user_name.replace('.', ' ').title() # 'Name Surname'
        base_dir = "/" + "/".join(response[1].split('/')[1::]) # retrieve base dir path to browse
            
        response_dic = {
                            'status': response[0],
                            'unix_user_id': unix_user_id,
                            'unix_user_name': unix_user_name,
                            'h5nuvola_user_name': h5nuvola_user_name,
                            'base_dir': base_dir
                        }
    else:
        response_dic = {
                            'status': response[0],
                            'message': response[1]
                        }        

    return response_dic


##########################################################################
#
# Flask app config 
#

app = Flask(__name__)
app.secret_key = 'some super secret key here'


##########################################################################
#
# Flask app routes/endpoints - remote browser, h5 visualisation, plotting
#

@app.route('/test')
def test():
    return render_template('h5nuvola_web_interface.html')

# VUO vlab link will call this endpoint
@app.route('/h5nuvola/vlab/<investigation_id>')
def vlab_verify(investigation_id):
    # Get vuo_session cookie from flask 'request' global context variable
    
    try:
        cookies = str(request.headers['Cookie'])
        
        if ";" in cookies: # check if there are more than one cookie set
            print "More than one cookie"
            print cookies
            cookies = cookies.split(';')
            print cookies
            for cookie in cookies:
                if "vuo_session" in cookie:
                    vuo_session_cookie = cookie.strip().split('=')[-1]
        else:
            print "Single cookie"
            vuo_session_cookie = cookies.split('=')[-1]            
         
        
        response_vuo = get_vuo_user(vuo_session_cookie)    

        if response_vuo['status'] == 'OK':
            print("Valid session on VUO!")
            vuo_user_id = response_vuo['vuo_user_id']

            response_vlab = vlab_call(vuo_user_id, investigation_id)

            if response_vlab['status'] == 'OK':        
                return render_template("h5nuvola_web_interface.html",
                                        UNIX_USER_NAME=json.dumps(response_vlab['unix_user_name']),
                                        H5NUVOLA_USER_NAME=json.dumps(response_vlab['h5nuvola_user_name']),
                                        BASE_DIR=json.dumps(response_vlab['base_dir']),
                                        INVESTIGATION_ID=json.dumps(investigation_id))
            else:
                return response_vlab['message'][0:-1] + " to access investigation ID " + investigation_id
        
        else:
            print("NOT a valid session on VUO! Please log in.")
            print(response_vuo['redirect_url'])
            return redirect(response_vuo['redirect_url'] + 
                            urllib.quote('https://users-nuvola.elettra.eu/h5nuvola/vlab/' +
                            investigation_id))
    except KeyError: # Could not find Cookie in the headers
        return "Could not verify if user is logged in VUO. Please log in and try again."



# endpoint called every time a folder is clicked in the jQuery FileTree app
@app.route('/sfiles/<unix_user_name>', methods=["GET", "POST"])
def sfiles(unix_user_name):    
    r = []
    
    d = urllib.unquote(request.form.get('dir', './'))

    queue = multiprocessing.Queue()

    p = multiprocessing.Process(target=get_files_target,
                                args=(d,
                                        fnfilter,
                                        dfilter,
                                        True,
                                        unix_user_name,
                                        queue)
                                )        
    p.start()

    fns_dirs_queue = queue.get()

    p.join()

    # user can't read the directory requested
    if "exeception" in fns_dirs_queue.keys():
        print("\n\n Exception \n\n")        
        r.append('Could not load directory: %s' % (str(fns_dirs_queue["exception"])))
    else:
        fns, dirs = fns_dirs_queue["fns"], fns_dirs_queue["dirs"]

        r = ['<ul class="jqueryFileTree" style="display: none;">']
        for f in dirs:
            ff = os.path.join(d, f)
            r.append('<li class="directory collapsed">' \
                    '<a href="#" rel="%s/">%s</a></li>' % (ff, f))
        for f in fns:
            ff = os.path.join(d, f)
            e = os.path.splitext(f)[1][1:]  # get .ext and remove dot
            r.append('<li class="file ext_%s">' \
            '<a href="#" rel="%s">%s</a></li>' % (e, ff, f))
        r.append('</ul>') 

    return ''.join(r)

# Load h5 files 
@app.route('/loadH5File', methods=['POST']) 
def loadH5File():       

    user_name = str(request.form['username']).strip()
    filepath = str(request.form['filepath']).strip()       
        
    # read file using multiprocessing
    queue = multiprocessing.Queue()    
    
    p = multiprocessing.Process(target=read_h5_target, args=(filepath, user_name, queue))        
    p.start()

    p.join() # here I must call join before queue.get(), not clear why ...

    hf_dict = queue.get()

    return json.dumps({'filepath':filepath,
                    'hf_name':hf_dict[filepath]['hf_name'],
                    'hf_root_items':hf_dict[filepath]['hf_root_items'], 
                    'hf_new_items':hf_dict[filepath]['hf_new_items'],
                    'root_properties':hf_dict[filepath]['root_properties']
                    })

# Close h5 file -> delete node from tree, remove dictionary key and content of selected file
@app.route('/closeH5File', methods=['POST'])
def closeH5File():    

    user_name = str(request.form['username']).strip()
    filepath = str(request.form['filepath']).strip()    

    return ''

# Expand/Update the h5 Tree 
@app.route('/h5TreeUpdate', methods=['POST', 'GET'])
def h5TreeUpdate():    
    
    user_name = str(request.form['username']).strip()
    filepath = str(request.form['filepath']).strip()
    node_selected = str(request.form['node']).strip()

    queue = multiprocessing.Queue()

    p = multiprocessing.Process(target=expand_tree_target, 
                                    args=(user_name,
                                          filepath,
                                          node_selected,
                                          queue)
                                )        
    p.start()        
    
    hf_new_items = queue.get()

    p.join()       
    
    return json.dumps({'filepath': filepath,
                       'hf_new_items':hf_new_items
                       })

@app.route('/raw', methods=['GET', 'POST'])
def raw():     
    if request.method == 'POST':

        user_name = str(request.form['username']).strip()
        filepath = str(request.form['filepath']).strip()        
        node_selected = str(request.form['node']).strip()        

        queue = multiprocessing.Queue()

        p = multiprocessing.Process(target=bokeh_table_target,
                                    args=(user_name,
                                          filepath,
                                          node_selected,
                                          queue)
                                    )
        p.start()       
        
        bokeh_json_item_tables = queue.get()
        
        p.join() # here I must call join after queue.get(), not clear why ...       

    return json.dumps(bokeh_json_item_tables)

@app.route('/curve', methods=['GET', 'POST'])
def curve():     
    if request.method == 'POST':

        user_name = str(request.form['username']).strip()
        filepath = str(request.form['filepath']).strip()        
        node_selected = str(request.form['node']).strip()        

        queue = multiprocessing.Queue()

        p = multiprocessing.Process(target=bokeh_plot_target,
                                    args=(user_name,
                                          filepath,
                                          node_selected,
                                          queue)
                                    )
        p.start()       
        
        bokeh_json_item_plots = queue.get()
        
        p.join() # here I must call join after queue.get(), not clear why ...       

    return json.dumps(bokeh_json_item_plots)

@app.route('/image', methods=['GET', 'POST'])
def image():     
    if request.method == 'POST':

        user_name = str(request.form['username']).strip()
        filepath = str(request.form['filepath']).strip()        
        node_selected = str(request.form['node']).strip()        

        queue = multiprocessing.Queue()

        p = multiprocessing.Process(target=bokeh_image_target,
                                    args=(user_name,
                                          filepath,
                                          node_selected,
                                          queue)
                                    )
        p.start()       
        
        bokeh_json_item_images = queue.get()
        
        p.join() # here I must call join after queue.get(), not clear why ...       

    return json.dumps(bokeh_json_item_images)

@app.route('/logout', methods=['GET','POST'])
def logout():    
    
    user_name = str(request.form['username']).strip()
    
    return ''
    # return redirect('https://vuo.elettra.eu/pls/vuo/guest.startup')

def geth5dset_target( user_name, queue, h5fn,  dsetname, slicing='[:]' ):     
    uid = pwd.getpwnam(user_name).pw_uid
    os.setuid(uid)
    try:
        exec( 'with h5.File(h5fn) as hf: d = hf[ dsetname ]%s'%slicing )   

        data = {'dbytes':d.tobytes(),
                'dinfo':{'Content-type': 'application/octet-stream',
                        'shape': d.shape,
                        'dtype': d.dtype}
                }   

        queue.put(data)
    except Exception as ex:
        data =  {'dbytes':"An exception of type %s occurred: %s"%(ex.__class__.__name__, ex.args),
                 'dinfo':{'Content-type': 'application/octet-stream',
                        'shape': '',
                        'dtype': ''}
                }
        queue.put(data)   
    

def parsepathstr( pathstr, h5ext='.h5' ):
    h5fn = '/' + pathstr.rsplit(h5ext,1)[0] + h5ext
    dsetnameslicing = pathstr.rsplit(h5ext,1)[-1]
    dsetname = dsetnameslicing.split('[',1)[0]
    slicing = dsetnameslicing.replace(dsetname,'')
    if slicing == '' :
        slicing = '[:]'
    return h5fn, dsetname, slicing


@app.route('/h5data/<path:filepath>', methods=['POST'])
def h5data(filepath):
    # get HDF5 file extension
    h5ext = str(request.form['ext']).strip()    
    # get vuo session from POST request
    vuo_session_cookie = str(request.form['vuotoken']).strip()    
    # verify if vuo session is valid
    response_vuo = get_vuo_user(vuo_session_cookie)
    if response_vuo['status'] == 'OK': # if valid vuo session, retrieve data
        user_name = response_vuo['unix_user_name']

        h5fn, dsetname, slicing  = parsepathstr( filepath, h5ext=h5ext )

        # check slicing string with regex
        # r = re.search('^\[(?:-?\d)*:(?:-?\d)*(?:,\s?(?:-?\d)*:(?:-?\d)*)*\]$',
        #               slicing)
        r = re.search('^\[(?:-?\d)*:?(?:-?\d)*(?:,\s?(?:-?\d)*:?(?:-?\d)*)*\]$',
                      slicing)

        if r: # if it matches the expected pattern       
            queue = multiprocessing.Queue()

            p = multiprocessing.Process(target=geth5dset_target,
                                        args=(user_name,
                                            queue,
                                            h5fn,
                                            dsetname,
                                            slicing)                                      
                                        )

            p.start()    

            data = queue.get() # {'dbytes':dbytes, 'dinfo':{} }

            p.join()    
            
            resp = Response(data['dbytes']) # response content
            resp.headers['Content-type'] = data['dinfo']['Content-type']
            resp.headers['shape'] = data['dinfo']['shape']
            resp.headers['dtype'] = data['dinfo']['dtype']    

            return resp
        else:
            resp = Response("NOT a valid slicing string!")
            return resp
    
    else:
        print("NOT a valid session on VUO! Please log in.")
        resp = Response("NOT a valid session on VUO! Please log in.")
        return resp

##########################################################################
#
# Configure https/certificate | ssl_context
#

context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
# context.verify_mode = ssl.CERT_REQUIRED
context.load_verify_locations("/root/certs/DigiCertCA.crt")
context.load_cert_chain("/root/certs/users-nuvola.elettra.eu.crt", "/root/certs/users-nuvola.elettra.eu.key")
# sslcontext = ("/root/certs/users-nuvola.elettra.eu.crt", "/root/certs/users-nuvola.elettra.eu.key")


app.run(host='users-nuvola.elettra.eu', port=443, debug=True, ssl_context=context)