from django import forms

from .models import StayApplicationBase

DATE = {"type": "date", "class": "form-control"}

STAY_FIELDS = [
    "date_of_receipt", "time_of_receipt", "date_of_fixation",
    "decision", "days_granted", "date_of_order", "remarks",
]
STAY_WIDGETS = {
    "date_of_receipt": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
    "time_of_receipt": forms.TimeInput(attrs={"type": "time", "class": "form-control"},
                                       format="%H:%M"),
    "date_of_fixation": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
    "decision": forms.Select(attrs={"class": "form-select"}),
    "days_granted": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
    "date_of_order": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
    "remarks": forms.TextInput(attrs={"class": "form-control"}),
}


class StayFormBase(forms.ModelForm):
    """Checks shared by both taxes' stay application forms."""

    def clean(self):
        data = super().clean()
        received = data.get("date_of_receipt")
        fixed = data.get("date_of_fixation")
        ordered = data.get("date_of_order")
        decision = data.get("decision")
        pending = StayApplicationBase.Decision.PENDING

        if received and fixed and fixed < received:
            self.add_error("date_of_fixation", "Fixation cannot be before the date of receipt.")
        if received and ordered and ordered < received:
            self.add_error("date_of_order", "The order cannot be before the date of receipt.")
        if ordered and decision == pending:
            self.add_error("decision", "Choose granted or not granted when an order date is given.")
        if decision and decision != pending and not ordered:
            self.add_error("date_of_order", "Enter the date of the order for a decided application.")
        if decision == StayApplicationBase.Decision.GRANTED and not data.get("days_granted"):
            self.add_error("days_granted", "Enter the number of days the stay was granted for.")
        return data


def stay_form_for(model):
    """A ModelForm for one tax's stay application table."""
    return forms.modelform_factory(model, form=StayFormBase,
                                   fields=STAY_FIELDS, widgets=STAY_WIDGETS)
