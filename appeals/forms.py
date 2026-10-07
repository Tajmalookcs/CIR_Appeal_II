from django import forms
from django.utils import timezone

from .models import IncomeTaxAppeal, SalesTaxAppeal, Unit, Zone

DATE_ATTRS = {"type": "date", "class": "form-control"}
TEXT = {"class": "form-control"}
AREA = {"class": "form-control", "rows": 3}
SELECT = {"class": "form-select"}
MONEY = {"class": "form-control text-end", "step": "0.01", "min": "0"}


class AppealFormBase(forms.ModelForm):
    """Zone/Unit dependency plus Appeal No. serial handling."""

    #: When the record was last saved, as it stood when this form was drawn.
    #: The view compares it on POST to notice that another clerk saved the same
    #: appeal while this one had the form open.
    edited_at = forms.CharField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk and self.instance.updated_at:
            self.fields["edited_at"].initial = self.instance.updated_at.isoformat()

        self.fields["zone"].queryset = Zone.objects.filter(is_active=True)
        self.fields["zone"].empty_label = "-- Select Zone --"
        self.fields["unit"].empty_label = "-- Select Unit --"

        # Pre-fill the next free serial for the current year on a new record.
        if not self.instance.pk and not self.data.get("serial_no"):
            year = timezone.localdate().year
            self.fields["serial_no"].initial = self._meta.model.next_serial_no(year)

        zone_id = None
        if self.data.get("zone"):
            zone_id = self.data.get("zone")
        elif self.instance.pk and self.instance.zone_id:
            zone_id = self.instance.zone_id

        if zone_id:
            self.fields["unit"].queryset = Unit.objects.filter(
                zone_id=zone_id, is_active=True
            )
        else:
            self.fields["unit"].queryset = Unit.objects.none()

    def clean(self):
        cleaned = super().clean()

        zone, unit = cleaned.get("zone"), cleaned.get("unit")
        if unit and zone and unit.zone_id != zone.pk:
            self.add_error("unit", "This unit does not belong to the selected zone.")

        # The Appeal No. must be unique within its year of institution.
        serial = cleaned.get("serial_no")
        instituted = cleaned.get("date_of_institution")
        if serial and instituted:
            model = self._meta.model
            clash = model.objects.filter(serial_no=serial, year=instituted.year)
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            # On a new appeal the view moves to the next free number and says so,
            # because the clerk was handed this one by the form and another clerk
            # may have taken it in the meantime. Editing is different: the number
            # on an existing file is deliberate, so a clash is an error.
            if clash.exists() and self.instance.pk:
                sample = model(serial_no=serial, year=instituted.year)
                self.add_error(
                    "serial_no",
                    f"Appeal No. {sample.appeal_no} already exists. "
                    f"Next free number for {instituted.year} is "
                    f"{model.next_serial_no(instituted.year)}.",
                )
        return cleaned


class SalesTaxAppealForm(AppealFormBase):
    class Meta:
        model = SalesTaxAppeal
        fields = [
            "serial_no", "date_of_institution", "ntn", "strn",
            "appellant_name", "address", "city", "contact_no",
            "sales_tax_involved", "zone", "unit", "passing_officer_name",
            "passing_officer_designation",
            "tax_period", "tax_year", "oio_no", "oio_date", "date_of_service",
            "ar_name", "ar_type", "ar_registration_no", "ar_contact_no",
            "ar_address", "ar_city",
            "issue_involved", "section",
            "oia_no", "oia_date", "decision_status",
            "courier_no", "courier_date", "service_status",
        ]
        widgets = {
            "serial_no": forms.NumberInput(attrs={**TEXT, "min": "1", "placeholder": "e.g. 12"}),
            "date_of_institution": forms.DateInput(attrs=DATE_ATTRS, format="%Y-%m-%d"),
            "ntn": forms.TextInput(attrs=TEXT),
            "strn": forms.TextInput(attrs=TEXT),
            "appellant_name": forms.TextInput(attrs=TEXT),
            "address": forms.Textarea(attrs=AREA),
            "contact_no": forms.TextInput(attrs=TEXT),
            "sales_tax_involved": forms.NumberInput(attrs=MONEY),
            "zone": forms.Select(attrs={**SELECT, "id": "id_zone"}),
            "unit": forms.Select(attrs={**SELECT, "id": "id_unit"}),
            "passing_officer_name": forms.TextInput(attrs=TEXT),
            "passing_officer_designation": forms.TextInput(
                attrs={**TEXT, "placeholder": "e.g. IRO, ACIR, DCIR, Addl. CIR"}),
            "tax_period": forms.TextInput(attrs={**TEXT, "placeholder": "e.g. 07/2024 to 06/2025"}),
            "oio_no": forms.TextInput(attrs=TEXT),
            "oio_date": forms.DateInput(attrs=DATE_ATTRS, format="%Y-%m-%d"),
            "city": forms.TextInput(attrs=TEXT),
            "tax_year": forms.TextInput(attrs={**TEXT, "placeholder": "e.g. 2025"}),
            "date_of_service": forms.DateInput(attrs=DATE_ATTRS, format="%Y-%m-%d"),
            "ar_name": forms.TextInput(attrs=TEXT),
            "ar_type": forms.TextInput(attrs={**TEXT, "placeholder": "Advocate / ITP / CA ..."}),
            "ar_registration_no": forms.TextInput(attrs=TEXT),
            "ar_contact_no": forms.TextInput(attrs=TEXT),
            "ar_address": forms.TextInput(attrs=TEXT),
            "ar_city": forms.TextInput(attrs=TEXT),
            "issue_involved": forms.Textarea(attrs=AREA),
            "section": forms.TextInput(attrs=TEXT),
            "oia_no": forms.TextInput(attrs=TEXT),
            "oia_date": forms.DateInput(attrs=DATE_ATTRS, format="%Y-%m-%d"),
            "decision_status": forms.Select(attrs=SELECT),
            "courier_no": forms.TextInput(attrs=TEXT),
            "courier_date": forms.DateInput(attrs=DATE_ATTRS, format="%Y-%m-%d"),
            "service_status": forms.Select(attrs=SELECT),
        }


class IncomeTaxAppealForm(AppealFormBase):
    class Meta:
        model = IncomeTaxAppeal
        fields = [
            "serial_no", "date_of_institution", "cnic", "ntn",
            "appellant_name", "address_line_1", "address_line_2", "city", "contact_no",
            "tax_year", "order_section", "zone", "unit",
            "income_assessed", "revenue_involved",
            "date_of_assessment", "date_of_service", "officer_name", "officer_designation",
            "issues_involved",
            "ar_name", "ar_type", "ar_registration_no", "ar_contact_no",
            "ar_address", "ar_city",
            "appellate_order_date", "decision_status",
            "courier_no", "courier_date", "service_status",
        ]
        widgets = {
            "serial_no": forms.NumberInput(attrs={**TEXT, "min": "1", "placeholder": "e.g. 12"}),
            "date_of_institution": forms.DateInput(attrs=DATE_ATTRS, format="%Y-%m-%d"),
            "cnic": forms.TextInput(attrs={**TEXT, "placeholder": "33100-1234567-1"}),
            "ntn": forms.TextInput(attrs=TEXT),
            "appellant_name": forms.TextInput(attrs=TEXT),
            "address_line_1": forms.TextInput(attrs=TEXT),
            "address_line_2": forms.TextInput(attrs=TEXT),
            "contact_no": forms.TextInput(attrs=TEXT),
            "tax_year": forms.TextInput(attrs={**TEXT, "placeholder": "e.g. 2024"}),
            "order_section": forms.TextInput(attrs=TEXT),
            "zone": forms.Select(attrs={**SELECT, "id": "id_zone"}),
            "unit": forms.Select(attrs={**SELECT, "id": "id_unit"}),
            "income_assessed": forms.NumberInput(attrs=MONEY),
            "revenue_involved": forms.NumberInput(attrs=MONEY),
            "date_of_assessment": forms.DateInput(attrs=DATE_ATTRS, format="%Y-%m-%d"),
            "officer_name": forms.TextInput(attrs=TEXT),
            "officer_designation": forms.TextInput(
                attrs={**TEXT, "placeholder": "IRO / ACIR / DCIR / Addl. CIR"}),
            "issues_involved": forms.Textarea(attrs=AREA),
            "city": forms.TextInput(attrs=TEXT),
            "date_of_service": forms.DateInput(attrs=DATE_ATTRS, format="%Y-%m-%d"),
            "ar_name": forms.TextInput(attrs=TEXT),
            "ar_type": forms.TextInput(attrs={**TEXT, "placeholder": "Advocate / ITP / CA ..."}),
            "ar_registration_no": forms.TextInput(attrs=TEXT),
            "ar_contact_no": forms.TextInput(attrs=TEXT),
            "ar_address": forms.TextInput(attrs=TEXT),
            "ar_city": forms.TextInput(attrs=TEXT),
            "appellate_order_date": forms.DateInput(attrs=DATE_ATTRS, format="%Y-%m-%d"),
            "decision_status": forms.Select(attrs=SELECT),
            "courier_no": forms.TextInput(attrs=TEXT),
            "courier_date": forms.DateInput(attrs=DATE_ATTRS, format="%Y-%m-%d"),
            "service_status": forms.Select(attrs=SELECT),
        }
