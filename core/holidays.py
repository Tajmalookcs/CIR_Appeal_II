"""Holidays page: Admin confirms or moves the Islamic holidays each year."""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import admin_required

from .models import AuditLog, Holiday
from .utils import diff, log_action, snapshot
from .workdays import HIJRI_OFFSET_DAYS, ensure_year


class HolidayForm(forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ["date", "name", "kind", "provisional", "notes"]
        labels = {"provisional": "Provisional - not yet confirmed by moon sighting"}
        help_texts = {"provisional": ""}
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"},
                                    format="%Y-%m-%d"),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "kind": forms.Select(attrs={"class": "form-select"}),
            "provisional": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notes": forms.TextInput(attrs={"class": "form-control"}),
        }


def _year(request):
    try:
        year = int(request.GET.get("year", ""))
        if 2000 <= year <= 2075:
            return year
    except ValueError:
        pass
    return timezone.localdate().year


@login_required
@admin_required
def holiday_list(request):
    year = _year(request)
    ensure_year(year)
    holidays = Holiday.objects.filter(date__year=year)
    return render(request, "core/holiday_list.html", {
        "year": year,
        "holidays": holidays,
        "provisional_count": holidays.filter(provisional=True).count(),
        "offset": HIJRI_OFFSET_DAYS,
    })


def _save(request, pk=None):
    holiday = get_object_or_404(Holiday, pk=pk) if pk else None
    before = snapshot(holiday) if holiday else {}
    form = HolidayForm(request.POST or None, instance=holiday)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        log_action(
            request,
            AuditLog.Action.UPDATE if holiday else AuditLog.Action.CREATE,
            instance=obj,
            changes=diff(before, snapshot(obj)) if holiday else snapshot(obj),
            model_name="Holiday",
        )
        messages.success(request, f"Holiday saved: {obj}.")
        return redirect(f"{_list_url()}?year={obj.date.year}")
    return render(request, "core/simple_form.html", {
        "form": form,
        "title": "Edit Holiday" if holiday else "Add Holiday",
        "subtitle": "Office holidays used to count working days",
        "back_url": f"{_list_url()}?year={(holiday.date.year if holiday else _year(request))}",
        "submit_label": "Save Holiday",
    })


def _list_url():
    from django.urls import reverse
    return reverse("core:holiday_list")


@login_required
@admin_required
def holiday_create(request):
    return _save(request)


@login_required
@admin_required
def holiday_update(request, pk):
    return _save(request, pk)


@login_required
@admin_required
def holiday_confirm(request, pk):
    """One click: the provisional date was right."""
    holiday = get_object_or_404(Holiday, pk=pk)
    if request.method == "POST" and holiday.provisional:
        before = snapshot(holiday)
        holiday.provisional = False
        holiday.save()
        log_action(request, AuditLog.Action.UPDATE, instance=holiday,
                   changes=diff(before, snapshot(holiday)), model_name="Holiday")
        messages.success(request, f"Confirmed: {holiday}.")
    return redirect(f"{_list_url()}?year={holiday.date.year}")


@login_required
@admin_required
def holiday_delete(request, pk):
    holiday = get_object_or_404(Holiday, pk=pk)
    if request.method == "POST":
        repr_ = str(holiday)
        log_action(request, AuditLog.Action.DELETE, instance=holiday,
                   changes=snapshot(holiday), model_name="Holiday", object_repr=repr_)
        year = holiday.date.year
        holiday.delete()
        messages.success(request, f"Holiday removed: {repr_}.")
        return redirect(f"{_list_url()}?year={year}")
    return redirect(f"{_list_url()}?year={holiday.date.year}")
