from django.template.defaultfilters import stringfilter, floatformat
from django import template
register = template.Library()

from pgd_constants import AA_CHOICES_DICT

"""
Filter that returns the full AA code from the 1 letter AA code
"""
@register.filter(name='full_aa')
@stringfilter
def full_aa(value):
    return AA_CHOICES_DICT[value]
register.filter('full_aa',full_aa)


@register.filter(name='index_lookup')
def index_lookup(value, arg):
    """
    Filter that allows you to lookup the value of a list using another variable in the page
    """
    try:
        return value[int(arg)]
    except IndexError:
        return None
register.filter('index_lookup', index_lookup)


@register.filter(name='invalid')
def invalid(value, precision):
    """
    Filter that checks for invalid values 999.9 and 0 and replaces them with
    dashes.  valid values are formatted using floatformat and the inputed precision
    """
    if value:
        if value in (0,999.9):
            return '--'
        return floatformat(value, precision)
    return '--'
register.filter('invalid', invalid)