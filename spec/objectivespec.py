from copy import deepcopy
import lasagne.objectives as lasobjectives

class Objective(object):
    def __init__(self, **kwargs):
        if kwargs:
            self.additional_args = kwargs
        self.type = self.__class__.__name__

    def to_dict(self):
        properties = deepcopy(self.__dict__)
        return properties

class mse(Objective):
    def __init__(self, **kwargs):
        super(mse, self).__init__(**kwargs)

    def instantiate(self):
        return lasobjectives.Objective(loss_function=lasobjectives.mse)

class crossentropy(Objective):
    def __init__(self, **kwargs):
        super(crossentropy, self).__init__(**kwargs)

    def instantiate(self):
        return lasobjectives.Objective(loss_function=lasobjectives.crossentropy)

class categorical_crossentropy(Objective):
    def __init__(self, **kwargs):
        super(categorical_crossentropy, self).__init__(**kwargs)

    def instantiate(self):
        return lasobjectives.Objective(loss_function=lasobjectives.categorical_crossentropy)

class hinge_loss(Objective):
    def __init__(self, threshold=0.0, **kwargs):
        super(hinge_loss, self).__init__(**kwargs)
        self.threshold = threshold

    def instantiate(self):
        return lasobjectives.Objective(loss_function=lasobjectives.hinge_loss, threshold=self.threshold)

class squared_hinge_loss(Objective):
    def __init__(self, gamma=2.0, **kwargs):
        super(squared_hinge_loss, self).__init__(**kwargs)
        self.gamma = gamma

    def instantiate(self):
        return lasobjectives.Objective(loss_function=lasobjectives.squared_hinge_loss, gamma=self.gamma)

class kl_divergence(Objective):
    def __init__(self, eps=1e-08, **kwargs):
        super(kl_divergence, self).__init__(**kwargs)
        self.eps = eps

    def instantiate(self):
        return lasobjectives.Objective(loss_function=lasobjectives.kl_divergence, eps=self.eps)
