from datetime import date
from decimal import Decimal

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def cell(value):
    """One register cell: dates as dd-mm-yyyy, money with commas, line breaks kept."""
    if value is None or value == "":
        return ""
    if isinstance(value, date):
        return mark_safe(f'<span style="white-space:nowrap">{value:%d-%m-%Y}</span>')
    if isinstance(value, Decimal):
        return f"{value:,.0f}"
    return mark_safe(escape(str(value)).replace("\n", "<br>"))
