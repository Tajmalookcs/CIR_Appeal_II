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


# ---------------------------------------------------------------------------
# Early hearing requests
# ---------------------------------------------------------------------------
EARLY_FIELDS = ["request_date", "made_by", "remarks"]
EARLY_WIDGETS = {
    "request_date": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
    "made_by": forms.Select(attrs={"class": "form-select"}),
    "remarks": forms.TextInput(attrs={"class": "form-control"}),
}


def early_form_for(model):
    return forms.modelform_factory(model, fields=EARLY_FIELDS, widgets=EARLY_WIDGETS)


# ---------------------------------------------------------------------------
# Court directions
# ---------------------------------------------------------------------------
COURT_FIELDS = ["court", "date_of_receipt", "direction", "last_date_for_disposal",
                "date_of_appellate_order", "remarks"]
COURT_WIDGETS = {
    "court": forms.Select(attrs={"class": "form-select"}),
    "date_of_receipt": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
    "direction": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    "last_date_for_disposal": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
    "date_of_appellate_order": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
    "remarks": forms.TextInput(attrs={"class": "form-control"}),
}


class CourtFormBase(forms.ModelForm):
    def clean(self):
        data = super().clean()
        received = data.get("date_of_receipt")
        for field in ("last_date_for_disposal", "date_of_appellate_order"):
            value = data.get(field)
            if received and value and value < received:
                self.add_error(field, "Cannot be before the date of receipt of the court order.")
        return data


def court_form_for(model):
    return forms.modelform_factory(model, form=CourtFormBase,
                                   fields=COURT_FIELDS, widgets=COURT_WIDGETS)


# ---------------------------------------------------------------------------
# Rectification applications
# ---------------------------------------------------------------------------
RECT_FIELDS = ["application_date", "application_no", "request_by", "fixation_date",
               "decision", "decision_date", "remarks"]
RECT_WIDGETS = {
    "application_date": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
    "application_no": forms.TextInput(attrs={"class": "form-control"}),
    "request_by": forms.Select(attrs={"class": "form-select"}),
    "fixation_date": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
    "decision": forms.Select(attrs={"class": "form-select"}),
    "decision_date": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
    "remarks": forms.TextInput(attrs={"class": "form-control"}),
}


class RectFormBase(forms.ModelForm):
    def clean(self):
        data = super().clean()
        applied = data.get("application_date")
        for field in ("fixation_date", "decision_date"):
            value = data.get(field)
            if applied and value and value < applied:
                self.add_error(field, "Cannot be before the date of the application.")
        if data.get("decision_date") and data.get("decision") == "pending":
            self.add_error("decision", "Choose the decision when a date of decision is given.")
        return data


def rect_form_for(model):
    return forms.modelform_factory(model, form=RectFormBase,
                                   fields=RECT_FIELDS, widgets=RECT_WIDGETS)
