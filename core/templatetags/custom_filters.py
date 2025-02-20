from django import template
import datetime

register = template.Library()



@register.filter
def get_item(dictionary, key):
    if dictionary:
        return dictionary.get(key, None)
    return None

#@register.filter
#def get_item(dictionary, key):
#    return dictionary.get(key)

@register.filter(name='format_gain')
def format_gain(value):
    if value is None:
        return "-"
    try:
        value = round(float(value), 2)
        if value > 0:
            return f'<span class="text-green-500">+{value}</span>'
        elif value < 0:
            return f'<span class="text-red-500">{value}</span>'
        return f"{value}"
    except (ValueError, TypeError):
        return "-"

@register.filter(name='round_2')
def round_2(value):
    try:
        return round(float(value), 2)
    except (ValueError, TypeError):
        return value
    
@register.filter
def timestamp_to_datetime(value):
    try:
        return datetime.datetime.fromtimestamp(value / 1000).strftime('%d/%m/%Y %H:%M:%S')
    except (ValueError, TypeError):
        return value
    
@register.filter(name='get_attr')
def get_attr(obj, attr_name):
    return getattr(obj, attr_name, None)

@register.filter(name='getattr')
def getattr_filter(obj, attr):
    return getattr(obj, attr, None)