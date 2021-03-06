import lasagne
import theano
import theano.tensor as T
from .. import layers
from .. import regularization
from collections import OrderedDict
from ..utils import Tnanmean, Tnansum
from inspect import getargspec
import numpy as np
import copy

class ParamUpdateSettings(object):
    """
    Settings to be used for parameters to be updated. 

    Parameters
    ----------
    update : :class:`lasagne.updates` function.
        Used to update parameters
    **kwargs : Parameters for update. Read docstring for function in :class:`lasagne.updates` for more information.
        Must contain all required arguments for the update function. Values not passed in will use the defaults if available.
    """
    def __init__(self,
                 update=None,
                 **kwargs
                 ):
        self.settings = kwargs
        self.update = update
        self._update_args = []

    def _check_settings(self):
        settings = self.settings
        update   = self.update
        assert update is not None
        argspec  = getargspec(update)
        all_args = argspec.args
        defs     = argspec.defaults
        ndef     = len(defs) if defs is not None else 0
        req_args = all_args[2:-ndef] if ndef>0 else all_args[2:]
        def_args = all_args[-ndef:] if ndef>0 else []
        assert all([kw in all_args for kw in settings])
        assert all([req in settings for req in req_args])
        z = zip(defs,def_args) if defs is not None else []
        for dval,darg in z:
            if not darg in settings:
                settings[darg] = dval
        self._update_args = all_args[2:]
        self.settings = settings

    def to_dict(self):
        properties           = self.__dict__.copy()
        properties['update'] = properties['update'].func_name
        del(properties['_update_args'])
        return properties

class Trainer(object):
    """
    The default trainer object. Updates parameters in a given model using given update parameters.

    Parameters
    ----------
    model : A :class:`Model` object
        Model to be trained.
    global_update_settings : A :class:`ParamUpdateSettings` object
        Update settings to be used for all parameters which haven't been given
        their own settings via :func:`bind_update`
    dataSharedVarDict : a dict or None, optional
        Only to be used if the data is stored on shared variables.  If so,
        dataSharedVarDict should be a dictionary with the data keys bound to
        the model as keys and the cooresponding shared variables as values.
    missingvalue :
        value of labels that should be treated as missing.

    Notes
    ---------
    Data passed to the trainer should not have NaN values, since Theano seems
    to have difficulty calculating gradients with NaN labels. Instead, use a
    particular value to signify that an example is missing, and pass that value
    into the :py:attr:`missingvalue` parameter of the trainer.
    """
    def __init__(self, model, global_update_settings,dataSharedVarDict=None,missingvalue=-12345.0):#trainerSettings = TrainerSettings()):
        # self.__dict__.update(trainerSettings.__dict__)
        global_update_settings._check_settings()
        self.global_update_settings = global_update_settings
        self.dataSharedVarDict = dataSharedVarDict
        self.layer_updates = dict()
        self.set_model(model)
        self.regularizations=dict()
        self.missingvalue = missingvalue

    def bind_regularization(self, penalty, lnamelist=None):
        """
        Attach a regularization penalty to a list of layers. 

        Parameters
        ----------
        penalty : A theano expression compatible with :func:`lasagne.regularization.apply_penalty`
            See :func:`lasagne.regularization.apply_penalty` docstring for
            details.
        lnamelist : A list of strings or a list of tuples or a float or None, optional
            If a list of strings, list of layer names to which this
            regularization should apply.  If a list of tuples, specify
            regularization coefficents: [(lname,coeff),...].
            If a float, all layers will be added with the float as a coefficient
            If None, all layers in the model will be added.
        """
        if isinstance(lnamelist,float):
            lnamelist = [(l,lnamelist) for l in self.model.layers.keys()]
        if lnamelist is None:
            lnamelist = self.model.layers.keys()
        if type(lnamelist) != list:
            lnamelist = [lnamelist]
        if penalty not in self.regularizations.keys():
            self.regularizations[penalty] = []
        self.regularizations[penalty].extend(lnamelist)
        self.train_func=None

    def bind_update(self, layerlist, update_settings):
        """
        Set update settings to a list of layers. 

        Parameters
        ----------
        layerlist : A string or :class:`lasagne.layer` object, or list of strings or :class:`lasagne.layers` objects
            Strings must be names of layers in the model. These layers will
            have the given update settings rather than the global update
            settings.
        update_settings : A :class:`ParamUpdateSettings` object
            Settings to be used on layer or layers in layerlist.

        Notes
        -----
        If the update type is the same as the previous update type, update can
        be left as None in update_settings
        """
        if type(layerlist) != list:
            layerlist = [layerlist]
        for layer in layerlist:
            update_setting = copy.copy(update_settings)
            layer_name = layer if type(layer) == str else layer.name
            prev_settings = self.layer_updates[layer_name] if layer_name in self.layer_updates else self.global_update_settings
            u = update_setting.update
            if (u is None) or (u == prev_settings.update):
                update_setting.update = prev_settings.update
                pdict = dict(prev_settings.settings.items()+update_setting.settings.items())
                update_setting.settings = pdict
            else:
                self.train_func = None
            update_setting._check_settings()
            self.layer_updates[layer_name] = update_setting

    def bind_global_update(self, update_settings, overwrite=False):
        """
        Set new global update settings.

        Parameters
        ----------
        update_settings : A :class:`ParamUpdateSettings` object
            Settings to be used as new global settings
        overwrite : A Boolean or None, optional
            If True, all layers given settings via :func:`bind_update` will use the new global update settings instead.

        Notes
        -----
        If the update type is the same as the previous update type, update can be left as None in update_settings
        """
        prev_settings = self.global_update_settings
        u = update_settings.update
        if (u is None) or (u == prev_settings.update):
            update_settings.update = prev_settings.update
            pdict = dict(prev_settings.settings.items() + update_settings.settings.items())
            update_settings.settings = pdict
        else:
            self.train_func = None
        update_settings._check_settings()
        self.global_update_settings = update_settings
        if overwrite:
            self.layer_updates=dict()

    def set_model(self,model):
        """Assign a different model to the trainer."""
        self.layer_updates=dict()
        self.train_func = None
        self.model = model

    def _init_ins_variables(self):
        inputs = self.model.inputs
        ins    = []#OrderedDict()
        for input_key,input_layers in inputs.iteritems():
            for input_layer in input_layers:
                ins.append((input_key, input_layer.input_var))
        return ins

    def _get_outputs(self):
        all_layers_dict = self.model.layers
        outputs         = self.model.outputs
        all_layers      = all_layers_dict.values()
        all_outs        = layers.get_output(all_layers, deterministic=False)
        all_outs_dict   = dict(zip(all_layers_dict.keys(),all_outs))
        outsTrain       = [all_outs_dict[outputlayer] for outputlayer in outputs.keys()]
        return all_outs_dict,outsTrain

    def _get_cost(self,layer_name,layer_dict,all_outs_dict,ins):
        preds = all_outs_dict[layer_name]
        target_type = layer_dict['target_type']
        TfloatZero = np.array(0,dtype=theano.config.floatX)
        if target_type == 'label':
            targs = T.matrix('targets')
            ins.append((layer_dict['target'], targs))
        elif target_type == 'recon':
            targs = all_outs_dict[layer_dict['target']]
        else:
            raise Exception('This should have been caught earlier')
        cost = layer_dict['loss_function'](preds,targs)
        aggregation_type = layer_dict['aggregation_type']
        # regular aggregations
        if aggregation_type == 'mean':
            cost = cost.mean()
        elif aggregation_type == 'sum':
            cost = cost.sum()
        elif aggregation_type == 'weighted_mean':
            weights = T.matrix('weights')
            ins.append((layer_dict['weight_key'], weights))
            wsum = T.sum(weights)
            if cost.ndim < 2:
                cost = theano.ifelse.ifelse(T.eq(wsum,0),TfloatZero,T.sum(cost*weights.T)/wsum)
            else:
                cost = theano.ifelse.ifelse(T.eq(wsum,0),TfloatZero,T.sum(cost*weights)/wsum)
        elif aggregation_type == 'weighted_sum':
            weights = T.matrix('weights')
            ins.append((layer_dict['weight_key'], weights))
            if cost.ndim < 2:
                cost = T.sum(cost*weights.T)
            else:
                cost = T.sum(cost*weights)
        # nan-protected aggregations
        elif aggregation_type == 'nanmean':
            if cost.ndim < 2:
                inds = T.all(T.neq(targs,self.missingvalue),axis=1)
            else:
                inds = T.all(T.neq(targs,self.missingvalue),axis=1,keepdims=True)
            cost = T.switch(inds,cost,TfloatZero)
            cost = T.mean(cost)
        elif aggregation_type == 'nansum':
            if cost.ndim < 2:
                inds = T.all(T.neq(targs,self.missingvalue),axis=1)
            else:
                inds = T.all(T.neq(targs,self.missingvalue),axis=1,keepdims=True)
            cost = T.switch(inds,cost,TfloatZero)
            cost = T.mean(cost)
        elif aggregation_type == 'nanweighted_mean':
            weights = T.matrix('weights')
            ins.append((layer_dict['weight_key'], weights))
            wsum = T.sum(weights)
            if cost.ndim < 2:
                inds = T.all(T.neq(targs,self.missingvalue),axis=1)
                wc = cost*weights.T 
                wc = T.switch(inds,wc,0)
                cost = theano.ifelse.ifelse(T.eq(wsum,0),TfloatZero,(T.sum(wc)/wsum))
            else:
                inds = T.all(T.neq(targs,self.missingvalue),axis=1,keepdims=True)
                wc = cost*weights 
                wc = T.switch(inds,wc,0)
                cost = theano.ifelse.ifelse(T.eq(wsum,0),TfloatZero,(T.sum(wc)/wsum))
        elif aggregation_type == 'nanweighted_sum':
            weights = T.matrix('weights')
            ins.append((layer_dict['weight_key'], weights))
            if cost.ndim < 2:
                inds = T.all(T.neq(targs,self.missingvalue),axis=1)
                wc = cost*weights.T 
                wc = T.switch(inds,wc,0)
                cost = T.sum(wc)
            else:
                inds = T.all(T.neq(targs,self.missingvalue),axis=1,keepdims=True)
                wc = cost*weights 
                wc = T.switch(inds,wc,0)
                cost = T.sum(wc)
        else:
            raise Exception('This should have been caught earlier')
        return cost, ins

    def _get_update(self,layer_name,ins,costTotal):
        all_layers = self.model.layers
        params = all_layers[layer_name].get_params()
        update = OrderedDict()
        if len(params)>0:
            update_ins = []
            update_settings = self.layer_updates[layer_name] if layer_name in self.layer_updates else self.global_update_settings
            update_func = update_settings.update
            for arg in update_settings._update_args:
                argname = '%s_%s'%(arg,layer_name)
                self._all_update_args[argname] = layer_name
                argvar = T.scalar(argname)
                update_ins.append(argvar)
                ins.append((argname,argvar))
            update = update_func(costTotal, params, *update_ins)
        return update, ins

    def _get_regularization_costs(self):
        costs = []
        for p,lnamel in self.regularizations.iteritems():
            weights={}
            for ln in lnamel:
                if isinstance(ln,tuple):
                    wgt = ln[1]
                    name = ln[0]
                else:
                    wgt = 1
                    name = ln
                weights[self.model.layers[name]]=wgt
            costs.append(regularization.regularize_layer_params_weighted(weights,p))
        return costs

    def _create_train_func(self):
        if self.model is None:
            raise Exception("No model has been set to train!")
        inputs     = self.model.inputs
        outputs    = self.model.outputs
        all_layers = self.model.layers

        # Get costs
        ins = self._init_ins_variables()
        all_outs_dict,outsTrain = self._get_outputs()

        costs = []
        for layer_name, layer_dict in outputs.iteritems():
            # {layer_name:{output_layer,target,target_type,loss_function,aggregation_type}}
            cost,ins = self._get_cost(layer_name,layer_dict,all_outs_dict,ins)
            cost *= layer_dict['scale']
            costs.append(cost)
        costs.extend(self._get_regularization_costs())
        costTotal = T.sum(costs)
        #outsTrain.extend(costs)
        outsTrain.append(costTotal)
        # Get updates
        updates = OrderedDict()
        self._all_update_args = dict()
        for layer_name in all_layers:
            update,ins = self._get_update(layer_name,ins,costTotal)
            updates.update(update)

        # Create functions
        givens = dict()
        if self.dataSharedVarDict is not None:
            batch_index = T.iscalar('Batch index')
            ins.append(('batch_index', batch_index))
            batch_size = T.iscalar('Batch size')
            ins.append(('batch_size', batch_size))
            batch_slice = slice(batch_index * batch_size,(batch_index + 1) * batch_size)
            for input_key,input_layers in self.model.inputs.iteritems():
                for input_layer in input_layers:
                    ind = [item[0] for item in ins].index(input_key)
                    _, inVar = ins.pop(ind)
                    givens[inVar] = self.dataSharedVarDict[input_key][batch_slice]
            for output_layer_name,output_layer_dict in self.model.outputs.iteritems():
                if output_layer_dict['target_type'] == 'label':
                    targKey = output_layer_dict['target']
                    ind = [item[0] for item in ins].index(targKey)
                    _, targVar = ins.pop(ind)
                    givens[targVar]=self.dataSharedVarDict[targKey][batch_slice]
                weightKey = output_layer_dict['weight_key']
                if weightKey in [item[0] for item in ins]:
                    ind = [item[0] for item in ins].index(weightKey)
                    _, weightVar = ins.pop(ind)
                    givens[weightVar]=self.dataSharedVarDict[weightKey][batch_slice]

        inkeys = [items[0] for items in ins]
        invals = [items[1] for items in ins]
        train = theano.function(
            invals,
            outsTrain,
            updates=updates,
            givens=givens,
            on_unused_input='warn'
        )

        self.train_func = train
        self.insKeys = inkeys
        return self.train_func

    def _sort_ins(self,batch_dict):
        ins = []
        param_names = self._all_update_args
        for key in self.insKeys:
            if key in param_names:
                layer_name = param_names[key]
                param = key.split('_%s'%layer_name)[0]
                if layer_name in self.layer_updates:
                    inval = self.layer_updates[layer_name].settings[param]
                else:
                    inval = self.global_update_settings.settings[param]
            else:
                inval = batch_dict[key]
            ins.append(inval)
        return ins
    def train_step(self,batch_dict):
        """Perform training on one chunk of data. Compiles first time it is called."""
        if self.train_func is None:
            self.train_func = self._create_train_func()
        ins = self._sort_ins(batch_dict)
        return self.train_func(*ins)

    def to_dict(self):
        d = {}
        settings = self.__dict__
        d['model'] = settings['model'].name
        d['global_update_settings'] = settings['global_update_settings'].to_dict()
        lu = dict([[layer,params.to_dict()] for layer,params in settings['layer_updates'].iteritems()])
        d['layer_updates'] = lu
        lr = dict([[regularization.func_name,layers] for regularization,layers in settings['regularizations'].iteritems()])
        d['regularizations'] = lr
        return d
