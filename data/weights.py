import numpy as np
import theano

class Weighter(object):
    """
    A default Weighter object that returns 1 for each example

    Parameters
    ----------

    labelKey : str
        The key in the data dictionary that this weighter uses to compute its
        weights.

    statPool : dict or None
        The dictionary from which to calculate weights for new data.  It is
        ignored in the base :class:`Weighter` class.
    """
    def __init__(self,labelKey,statPool=None):
        self.statPool = statPool
        self.labelKey = labelKey
        if self.statPool is not None:
            self._init_stats()

    def _init_stats(self):
        pass

    def __call__(self,data):
        """
        Weighs data.

        Parameters
        ----------
        data : dict
            A data dictionary representing a batch of data.

        Returns
        -------
        :class:`numpy.ndarray`
            Weights for each example in the data dictionary.  These will all
            have a value of 1.

        """
        if isinstance(self.labelKey,list):
            return np.ones((data[self.labelKey[0]].shape[0],len(self.labelKey))).astype(theano.config.floatX)
        return np.ones((data[self.labelKey].shape[0],1)).astype(theano.config.floatX)
        
    def to_dict(self):
        """
        Returns
        -------
        dict
            A dictionary representation of this weighter.
        """
        properties = {}
        properties['weightType'] = 'None'
        for k in self.__dict__:
            if k == 'statPool':
                continue
            else:
                properties[k] = deepcopy(self.__dict__[k])
        return properties



class BinnedWeighter(Weighter):
    """
    Weighs examples based on the frequency of the bin to which they
    belong.  Examples with higher frequency labels get lower weights.

    Parameters
    ----------

    labelKey : str
        The key in the data dictionary that this weighter uses to compute its
        weights.

    bins : list
        The right edges of the bins that are used to assign the labels to
        categories.

    statPool : dict or None
        The dictionary from which to calculate weights for new data.  If None,
        weights are calculated from each batch.

    missingvalue : 
        the value in labels to ignore when calculating weights
    """
    def __init__(self,labelKey,bins,statPool=None,missingvalue=-12345.0):
        self.bins = bins
        self.missingvalue = missingvalue
        super(BinnedWeighter,self).__init__(labelKey,statPool)        

    def _init_stats(self):
        labels = self.statPool[self.labelKey]
        inds = np.logical_and(~np.isnan(labels),labels!=self.missingvalue)
        if np.sum(inds)==0:
            bincounts = np.zeros_like(self.bins)
        else:
            binlabels = np.digitize(labels[inds],bins=self.bins)
            bincounts = np.bincount(binlabels,minlength=len(self.bins))
            bincounts = bincounts[0:len(self.bins)]
        self.bincount = bincounts.astype(np.float32)
        # smooth the bin counts
        #if 0 in self.bincount:
            #TODO: make this smoothing dependent on data?
        self.bincount += .25
        self.binweight = 1./self.bincount
        self.binweight /= np.sum(self.binweight)

    def __call__(self,data):
        """
        Weighs data.

        Parameters
        ----------
        data : dict
            A data dictionary representing a batch of data.

        Returns
        -------
        :class:`numpy.ndarray`
            Weights for each example in the data dictionary. 
        """
        if self.statPool is None:
            self.statPool = data
            self._init_stats()
            self.statPool = None
        labels = data[self.labelKey]
        inds = np.logical_or(np.isnan(labels),labels==self.missingvalue)
        binlabels = np.digitize(labels.flatten(), bins=self.bins)
        binlabels[inds.flatten()] = len(self.bins) 
        weightsfunc = lambda x: self.binweight[x] if x < len(self.bins) else 0
        weights = np.array([weightsfunc(binlabel) for binlabel in binlabels])
        weights = weights.reshape(-1,1)
        weights[np.isnan(labels)] = 0
        return weights.astype(theano.config.floatX)


    def to_dict(self):
        """
        Returns
        -------
        dict
            A dictionary representation of this weighter.
        """
        properties = {}
        properties['weightType'] = 'Binned'
        for k in self.__dict__:
            if k == 'statPool':
                continue
            else:
                properties[k] = deepcopy(self.__dict__[k])
        return properties

        

class CategoricalWeighter(Weighter):
    """
    Weighs examples based on the frequency of the category to which they
    belong.  Examples with higher frequency labels get lower weights.

    Parameters
    ----------

    labelKey : str
        The key in the data dictionary that this weighter uses to compute its
        weights.

    statPool : dict or None
        The dictionary from which to calculate weights for new data.  If None,
        weights are calculated from each batch.
    """
    def __init__(self,labelKey,statPool=None):
        super(CategoricalWeighter,self).__init__(labelKey,statPool)        

    def _get_labels(self,source):
        if isinstance(self.labelKey,list):
            labs = []
            for l in self.labelKey:
                labs.append(source[l])
            retval =  np.hstack(labs)
        else:
            retval = source[self.labelKey]
        return retval


    def _init_stats(self):
        labels = self._get_labels(self.statPool) #self.statPool[self.labelKey] 

        inds = np.all(np.logical_and(labels<=1.0,labels>=0),axis=1)
        self.inds = inds
        self.frequencies = np.nansum(labels[inds,...], axis=0, keepdims=True)
        #if 0 in self.frequencies:
        self.frequencies += .1 
        self.proportions = (1./self.frequencies).astype(theano.config.floatX)
        self.proportions /= np.sum(self.proportions)
        

    def __call__(self,data):
        """
        Weighs data.

        Parameters
        ----------
        data : dict
            A data dictionary representing a batch of data.

        Returns
        -------
        :class:`numpy.ndarray`
            Weights for each example in the data dictionary.  

        """
        if self.statPool is None:
            self.statPool = data
            self._init_stats()
            self.statPool = None
        labels = self._get_labels(data) #data[self.labelKey]
        wgt = labels.dot(self.proportions.T).astype(theano.config.floatX)
        wgt[np.isnan(wgt)] = 0
        wgt[np.any(np.logical_or(labels<0,labels>1),axis=1,keepdims=True)] = 0
        return wgt 
    
    def to_dict(self):
        """
        Returns
        -------
        dict
            A dictionary representation of this weighter.
        """
        properties = {}
        properties['weightType'] = 'Categorical'
        for k in self.__dict__:
            if k == 'statPool':
                continue
            else:
                properties[k] = deepcopy(self.__dict__[k])
        return properties

class BinaryWeighter(Weighter):
    """
    Weighs examples based on the frequency of their binary label.  Examples in
    the higher frequency category get lower weights.

    Parameters
    ----------

    labelKey : str
        The key in the data dictionary that this weighter uses to compute its
        weights.

    statPool : dict or None
        The dictionary from which to calculate weights for new data.  If None,
        weights are calculated from each batch.
    """
    def __init__(self,labelKey,statPool=None):
        super(BinaryWeighter,self).__init__(labelKey,statPool)        
    
    def _init_stats(self):
        lab = self.statPool[self.labelKey]
        numPos = np.nansum(lab==1, axis=0, keepdims=True)
        numNeg = np.nansum(lab==0, axis=0, keepdims=True)
        meanNum = numPos+numNeg/2
        self.posWeight = meanNum / (numPos+.1) 
        self.negWeight = meanNum / (numNeg+.1)
        nrm = self.posWeight + self.negWeight
        self.posWeight/=nrm
        self.negWeight/=nrm
        self.numNeg = numNeg
        self.numPos = numPos

    def __call__(self,data):
        """
        Weighs data.

        Parameters
        ----------
        data : dict
            A data dictionary representing a batch of data.

        Returns
        -------
        :class:`numpy.ndarray`
            Weights for each example in the data dictionary. 

        """
        if self.statPool is None:
            self.statPool = data
            self._init_stats()
            self.statPool = None

        labels = data[self.labelKey].flatten()
        weights = np.zeros_like(labels)
        weights[labels==1] = self.posWeight
        weights[labels==0] = self.negWeight
        return weights[:,np.newaxis].astype(theano.config.floatX)

    def to_dict(self):
        """
        Returns
        -------
        dict
            A dictionary representation of this weighter.
        """
        properties = {}
        properties['weightType'] = 'Binary'
        for k in self.__dict__:
            if k == 'statPool':
                continue
            else:
                properties[k] = deepcopy(self.__dict__[k])
        return properties
