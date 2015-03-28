from spec.outputspec import *
from copy import deepcopy
import sys

class layerContainer():
    def __init__(self, name, layer, type, output_settings=None):
        self.name = name
        self.layer = layer
        self.type = type
        self.output_settings = output_settings

class modelSpec(object):

    def __init__(self, **kwargs):
        if kwargs:
            self.additional_args = kwargs
        self.layers = []
        self.instantiated_layers = dict()

    def to_dict(self):
        modeldict = deepcopy(self.__dict__)
        if 'instantiated_layers' in modeldict:
            del(modeldict['instantiated_layers'])
        modeldict['outputs'] = []
        for i in range(len(modeldict['layers'])):
            layer_name = modeldict['layers'][i].name
            layer = modeldict['layers'][i].layer
            output_settings = modeldict['layers'][i].output_settings
            modeldict['layers'][i] = layer.to_dict()
            modeldict['layers'][i]['name'] = layer_name
            if output_settings:
                output_settings = output_settings.to_dict()
                output_settings['layer_name'] = layer_name
                modeldict['outputs'].append(output_settings)
        return modeldict

    def bind_output(self, layername, settings=outputSpec()):
        if not isinstance(settings, outputSpec):
            raise TypeError("settings must be an object of type outputSpec.")
        layer = self.get_layer(layername)
        layer.output_settings = settings

    def add(self, layer_spec, name=None):
        if not isinstance(layer_spec, layerSpec):
            raise TypeError("layer_spec must be an object of type layerSpec!")
        if len(self.layers)==0:
            if not isinstance(layer_spec, inputLayerSpec):
                raise TypeError("The first layer_spec added to the model must be an object of type inputLayerSpec!")
        if name is not None and not isinstance(name, str):
            raise TypeError("name is an optional argument that must be a string or None. "
                            "Otherwise name is auto-generated.")
        # auto generate layer name if not passed in
        if name is None:
            layernum = len(self.layers)
            name = layer_spec.__class__.__name__.replace('Spec', '') + '_%d' % layernum
        # make sure name is unique
        layer_names = self.get_layer_names()
        if name in layer_names:
            raise RuntimeError("Layer name %s is already used by the model. "
                               "Each layer must have a unique name!" % name)

        # create layer container with extra information used to keep track of layers in a graph
        layercontainer = layerContainer(
            layer=layer_spec,
            name=name,
            type=layer_spec.__class__.__name__,
            output_settings=None
        )
        self.layers.append(layercontainer)
        return layercontainer

    def first(self):
        return self.layers[0]

    def last(self):
        return self.layers[-1]

    def get_layer_names(self):
        layer_names = [layer.name for layer in self.layers]
        return layer_names

    def get_layer(self, name):
        layer_names = self.get_layer_names()
        if name not in layer_names:
            print >>sys.stderr, "Name '%s' is not in layer_names" % name
            return None
        else:
            return self.layers[layer_names.index(name)]

    def instantiate(self):
        layers = []
        for layerctr in self.layers:
            layername = layerctr.name
            layerobj = layerctr.layer.instantiate(self.instantiated_layers, layername)
            layerdata = dict(
                layer=layerobj,
                name=layername
            )
            if layerctr.output_settings:
                outputobj = layerctr.output_settings.instantiate(self.instantiated_layers)
                layerdata['output_settings']=outputobj
            layers.append(layerdata)
        return layers
