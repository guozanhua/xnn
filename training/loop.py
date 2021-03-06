import xnn
import numpy as np
from bokeh.plotting import output_server, figure, push, curdoc, cursession,vplot
import time

class Loop(object):
    """
    An example training loop.  The trainer will learn from learndata, apply metrics to validdata, plot to bokeh server at url if supplied, and save to csv file.

    Parameters
    ----------

    trainer : :class:`Trainer`
        The trainer to run
    learndata : list
        A list of generator functions that yield batches of data from which the
        trainer will learn
    validdata : list
        A list of generator functions that yield batches of data to which the
        metrics will be applied
    metrics :  list
        A list of metrics to apply to the validdata.  Each entry is a tuple,
        the first element of which is the key in the model.predict output from
        which the metric should be calculated, the second element of which is
        the metric, the third element of which is either 'max' or 'min' to
        specify which direction is best
    url: str or None
        A string representing the url where the bokeh server is running (e.g.
        'http://127.0.0.1:5006'). If None, or if server cannot be connected, no
        plotting will occur
    savefilenamecsv : str
        The name of a file into which to write metric results at each epoch.
    weightdict :  dict or None
        Dictionary of :class:`Weighter` objects.  Keys in weightdict are keys
        into which the weight results will be inserted in the data dictionary.
        Weights are calculated for every training batch.  If None, do no
        weighting.
    printflag : bool
        Whether to print results to stdout after each epoch
    plotmetricmean : bool
        Whether to print/save/plot mean of all metrics.  Depending on the
        metrics, this value might not make sense.
    savemodelnamebase : str
        Base name for saving metrics.  If not None, models will be saved for
        the best values of each metric as looping procedes.
    """

    def __init__(self,trainer,learndata=[],validdata=[],metrics=[],url=None,savefilenamecsv=None,weightdict={},printflag=True,plotmetricmean=True,savemodelnamebase=None):
        self.trainer = trainer
        self.learndata = self._listify(learndata)
        self.validdata = self._listify(validdata)
        self.metrics = [(k,m) for k,m,_ in metrics]
        self.metdirs = [d for _,_,d in metrics]
        self.weightdict = weightdict
        if url is not None:
            self._plot_flag = self._init_plotsession(url)
            self._datasources = None
        else:
            self._plot_flag = False
        if savefilenamecsv is not None:
            self.savefilenamecsv=savefilenamecsv 
            self._savecsv_flag = True
        else:
            self._savecsv_flag = False
        if savemodelnamebase is not None:
            self.savemodelnamebase = savemodelnamebase
            self._savemodel_flag = True
        else:
            self._savemodel_flag = False
        self._print_flag = printflag
        self._plotmetricmean=plotmetricmean
        self._bestmetvals = None
        self._bestatep = None
        self.meandur = None
        self.ep = 0
        


    def __call__(self,nepoch=1):
        """
        Run the Loop by calling it with a number of epochs as argument
    
        Parameters
        ----------

        nepoch : int
            number of epochs to run
        """
        endep = self.ep+nepoch
        for ep in xrange(self.ep,endep):
            start = time.time()
            self.ep += 1
            # training
            trainerrs = []
            for ld in self.learndata:
                for batch in ld():
                    batch = self._weight(batch)
                    outs = self.trainer.train_step(batch)
                    trainerrs.append(outs[-1])
            trainerr = np.mean(trainerrs)

            # validation
            metvals = []
            for vd in self.validdata:
                vals = []
                for batch in vd():
                    outs = self.trainer.model.predict(batch)
                    bmv = []
                    for metkey,met in self.metrics:
                        bmv.append(met(outs[metkey],batch))
                    vals.append(bmv)
                metvals.append(np.mean(np.array(vals),axis=0).tolist())
            metvals = np.mean(metvals,axis=0).tolist()
            end = time.time()
            dur = end-start
            if self.meandur is None:
                self.meandur = dur
            else:
                self.meandur = 0.3*self.meandur + 0.7*dur

            #update best values
            isbest = self._update_best(ep,trainerr,metvals)

            #print summary to stdout
            if self._print_flag:
                self._print(ep,trainerr,metvals,dur,endep)

            #plot
            if self._plot_flag:
                self._plot(ep,trainerr,metvals)

            #save to csv
            if self._savecsv_flag:
                self._save(ep,trainerr,metvals)

            #save model if best for any metrics
            isbest_nontrainerr = isbest[1:]
            if self._savemodel_flag and any(isbest_nontrainerr):
                self._savemodel(isbest_nontrainerr)

        if self._print_flag:
            print('Finished %d epochs at %s'%(nepoch,time.strftime('%I:%M:%S %p')))
        return metvals

    def _weight(self,batch):
        for k,w in self.weightdict.iteritems():
            batch[k] = w(batch)
        return batch

    def _savemodel(self,isbest):
        if self._plotmetricmean:
            if isbest[0]:
                fname = self.savemodelnamebase + '_metricmean'
                self.trainer.model.save_model(fname)
            isbest = isbest[1:] 
        for (mk,mt),ib in zip(self.metrics,isbest):
            if ib:
                if mt.metric in xnn.metrics.metric_names:
                    name = xnn.metrics.metric_names[mt.metric]
                else:
                    name = mt.metric.__name__
                fname = self.savemodelnamebase + '_' + mk + '_'+ name
                self.trainer.model.save_model(fname)
    
    def _update_best(self,ep,trainerr,metvals):
        isbest = []
        best = []
        bestatep = []
        if self._plotmetricmean:
            vals = [trainerr] + [np.nanmean(metvals)] + metvals
            dirs = ['min'] + ['min'] + self.metdirs
        else:
            vals = [trainerr]+metvals
            dirs = ['min'] + self.metdirs
        if self._bestmetvals is None:
            self._bestmetvals = vals
            self._bestatep = [ep]*(len(vals))
            isbest = [True]*(len(vals))
        else:
            for v,b,e,d in zip(vals,self._bestmetvals,self._bestatep,dirs):
                if d == 'max':
                    bestcheck = v > b
                else:
                    bestcheck = v < b
                if bestcheck:
                    isbest.append(True)
                    best.append(v)
                    bestatep.append(ep)
                else:
                    isbest.append(False)
                    best.append(b)
                    bestatep.append(e)
            self._bestmetvals = best
            self._bestatep = bestatep
        return isbest

    def _plot(self,ep,trainerr,metvals):
        if self._datasources is None:
            self._make_figures(ep,trainerr,metvals)
        if self._plotmetricmean:
            vals = [trainerr] + [np.nanmean(metvals)] + metvals
        else:
            vals = [trainerr] + metvals
        for v,ds in zip(vals,self._datasources):
            self._update_datasource(ds,v,ep)

    def _update_datasource(self,ds,v,ep):
        ds.data['x'].append(ep)
        ds.data['y'].append(v)
        cursession().store_objects(ds)

    def _make_figures(self,ep,trainerr,metvals):
        self._datasources = []
        figures = []
        fig = figure(title='Total Training Cost',x_axis_label='Epoch',y_axis_label='Cost')
        fig.line([ep],[trainerr],name='plot')
        ds = fig.select(dict(name='plot'))[0].data_source
        self._datasources.append(ds)
        if self._plotmetricmean:
            figures.append(fig)
            fig = figure(title='Metric Mean',x_axis_label='Epoch',y_axis_label='Mean')
            fig.line([ep],[np.nanmean(metvals)],name='plot')
            ds = fig.select(dict(name='plot'))[0].data_source
            self._datasources.append(ds)
            figures.append(fig)
        for mv,(mk,m) in zip(metvals,self.metrics):
            if m.metric in xnn.metrics.metric_names:
                name = xnn.metrics.metric_names[m.metric]
            else:
                name = m.metric.__name__
            fig = figure(title=mk,x_axis_label='Epoch',y_axis_label=name)
            fig.line([ep],[mv],name='plot')
            ds = fig.select(dict(name='plot'))[0].data_source
            self._datasources.append(ds)
            figures.append(fig)
        allfigs = vplot(*figures)
        push()

    def _print(self,ep,trainerr,metvals,dur,totalep):
        fmt = '{0:45} {1:20}:   {2:0.4f} (best {3:0.4f} at epoch {4:g})'
        print '=========='
        print('Epoch %d / %d -- %0.2f seconds'%(ep,totalep-1,dur))
        print('Expected Finish: %s'%(self._timedone(ep,totalep)))
        print '----------'
        print(fmt.format('Training total cost','',trainerr,self._bestmetvals[0],self._bestatep[0]))
        print '----------'
        beststartid = 1
        if self._plotmetricmean:
            print fmt.format('Overall Mean','',np.nanmean(metvals),self._bestmetvals[1],self._bestatep[1])
            print '----------'
            beststartid = 2
        for mv,(mk,m),bv,be in zip(metvals,self.metrics,self._bestmetvals[beststartid:],self._bestatep[beststartid:]):
            if m.metric in xnn.metrics.metric_names:
                name = xnn.metrics.metric_names[m.metric]
            else:
                name = m.metric.__name__
            print fmt.format(name,mk,mv,bv,be)
            
    def _timedone(self,ep,totalep):
        now = time.time()
        done = now + self.meandur*(totalep-1-ep)
        ts = time.localtime(done)
        return time.strftime('%a, %I:%M:%S %p',ts)

    def _save(self,ep,trainerr,metvals):
        if (not hasattr(self,'_headers_written')) or (not self._headers_written):
            self._save_header()
            self._headers_written = True
        with open(self.savefilenamecsv,'a') as f:
            f.write(('%0.4f,'%trainerr))
            if self._plotmetricmean:
                f.write(('%0.4f,'%np.nanmean(metvals)))
            for mv in metvals:
                f.write(('%0.4f,'%mv))
            f.write('\n')
            f.flush()
    
    def _save_header(self):
        with open(self.savefilenamecsv,'a') as f:
            f.write('Training cost,')
            if self._plotmetricmean:
                f.write('Overall mean,')
            for mk,m in self.metrics:
                if m.metric in xnn.metrics.metric_names:
                    name = xnn.metrics.metric_names[m.metric]
                else:
                    name = m.metric.__name__
                f.write(name+'_'+mk+',')
            f.write('\n')
            f.flush()

    def _init_plotsession(self,url):
        docname = self.trainer.model.name
        try:
            output_server(docname,url=url)
        except:
            return False
        d = curdoc()
        self.plot_address = '%s/bokeh/doc/%s/%s'%(url,d.docid,d.ref['id'])
        print('plots available at: %s'%(self.plot_address))
        return True



    def _listify(self,thing):
        if not isinstance(thing,list):
            return [thing]
        return thing
