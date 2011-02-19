# -*- coding: utf-8 -*-
# pylint: disable=W0212, R0904
"""
State tracking functionality for django models
"""
from collections import defaultdict
from functools import wraps
from django.db import models

# South support; see http://south.aeracode.org/docs/tutorial/part4.html#simple-inheritance
try:
    from south.modelsinspector import add_introspection_rules
except ImportError:
    pass
else:
    add_introspection_rules([], [r"^django_fsm\.db\.fields\.fsmfield\.FSMField"])
    add_introspection_rules([], [r"^django_fsm\.db\.fields\.fsmfield\.FSMKeyField"])


class TransitionNotAllowed(Exception):
    """Raise when a transition is not allowed"""


class FSMMeta(object):
    """
    Models methods transitions meta information
    """
    def __init__(self, field=None):
        self.field = field
        self.transitions = defaultdict()
        self.conditions  = defaultdict()
    
    def _get_state_field(self, instance):
        """
        Lookup for FSMField in django model instance
        """
        if self.field:
            return self.field
        else:
            fields = [field for field in instance._meta.fields 
                      if isinstance(field, FSMField) or isinstance(field, FSMKeyField)]
            found = len(fields)
            if found == 0:
                raise TypeError("No FSMField found in model")
            elif found > 1:
                raise TypeError("More than one FSMField found in model")
            return fields[0]
    
    def current_state(self, instance):
        """
        Return current state of Django model
        """
        field_name = self._get_state_field(instance).name
        return getattr(instance, field_name)
        
    def has_transition(self, instance):
        """
        Lookup if any transition exists from current model state
        """
        return self.transitions.has_key(self.current_state(instance)) or self.transitions.has_key('*')

    def conditions_met(self, instance):
        """
        Check if all conditions has been met
        """
        current_state = self.current_state(instance)
        next = self.transitions.has_key(current_state) and self.transitions[current_state] or self.transitions['*']

        return all(map(lambda f: f(instance), self.conditions[next]))

    def to_next_state(self, instance):
        """
        Switch to next state
        """
        field_name = self._get_state_field(instance).name
        curr_state = getattr(instance, field_name)
        
        next_state = None
        try:
            next_state = self.transitions[curr_state]
        except KeyError:
            next_state = self.transitions['*']
        
        if next_state:
            setattr(instance, field_name, next_state)


def transition(field=None, source='*', target=None, save=False, conditions=[]):
    """
    Method decorator for mark allowed transition

    Set target to None if current state need to be validated and not
    changed after function call
    """
    # pylint: disable=C0111
    def inner_transition(func):
        if not hasattr(func, '_django_fsm'):
            setattr(func, '_django_fsm', FSMMeta(field=field))

        if isinstance(source, (list, tuple)):
            for state in source:
                func._django_fsm.transitions[state] = target
        else:
            func._django_fsm.transitions[source] = target

        func._django_fsm.conditions[target] = conditions

        @wraps(func)
        def _change_state(instance, *args, **kwargs):            
            meta = func._django_fsm
            if not meta.has_transition(instance):
                raise TransitionNotAllowed("Can't switch from state '%s' using method '%s'" % (meta.current_state(instance), func.func_name))
            
            for condition in conditions:
                if not condition(instance):
                    return False

            result = func(instance, *args, **kwargs)

            meta.to_next_state(instance)
            if save:
                instance.save()

            return result
        
        return _change_state
    
    return inner_transition


def can_proceed(bound_method):
    """
    Returns True if model in state allows to call bound_method 
    """
    if not hasattr(bound_method, '_django_fsm'):
        raise TypeError('%s method is not transition' % bound_method.im_func.__name__)

    meta = bound_method._django_fsm
    return meta.has_transition(bound_method.im_self) and meta.conditions_met(bound_method.im_self)


class FSMField(models.Field):
    """
    State Machine support for Django model

    """
    __metaclass__ = models.SubfieldBase
    
    def __init__(self, *args, **kwargs):
        kwargs['max_length'] = 50
        super(FSMField, self).__init__(*args, **kwargs)

    def get_internal_type(self):
        return 'CharField'


class FSMKeyField(models.ForeignKey):
    """
    State Machine support for Django model

    """
