from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.validators import RegexValidator

from .models import Designation, User

#: Staff sign in with their CNIC. This is a form-level rule only - the stored
#: username column keeps Django's own definition, so no migration is needed and
#: accounts created before this rule still work.
CNIC_DIGITS = 13
CNIC_HELP = "13 digits, no dashes. This is the sign-in ID."
cnic_validator = RegexValidator(
    r"^[0-9]{13}$",
    message="Enter the 13 digit CNIC without dashes.",
)
CNIC_ATTRS = {
    "class": "form-control",
    "inputmode": "numeric",
    "autocomplete": "off",
    "maxlength": "13",
    "minlength": "13",
    "pattern": "[0-9]{13}",
    "placeholder": "3310012345671",
}

TEXT = {"class": "form-control"}
SELECT = {"class": "form-select"}

SHARED_FIELDS = ["username", "full_name", "designation", "role", "contact_no", "email", "is_active"]
SHARED_WIDGETS = {
    "username": forms.TextInput(attrs=CNIC_ATTRS),
    "full_name": forms.TextInput(attrs=TEXT),
    "designation": forms.Select(attrs=SELECT),
    "role": forms.Select(attrs=SELECT),
    "contact_no": forms.TextInput(attrs=TEXT),
    "email": forms.EmailInput(attrs=TEXT),
    "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
}


class DesignationChoiceMixin(forms.ModelForm):
    """Offer only designations that are still in use."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields.get("designation")
        if field is not None:
            field.queryset = Designation.objects.filter(is_active=True)
            field.empty_label = "-- Select Designation --"


class CnicUsernameMixin(forms.ModelForm):
    """Present the username as a CNIC: 13 digits, no dashes.

    Nothing about the database changes. An account that already exists keeps
    whatever username it has until someone actually edits that box.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["username"]
        field.label = "CNIC"
        field.help_text = CNIC_HELP
        field.max_length = CNIC_DIGITS
        field.widget.attrs.update(CNIC_ATTRS)
        # The rule lives in clean_username, not in field.validators, so that an
        # untouched legacy username on the edit form can still be saved.
        field.validators = []

    def clean_username(self):
        value = (self.cleaned_data.get("username") or "").strip()
        if self.instance.pk and value == self.instance.username:
            return value
        cnic_validator(value)
        return value


class UserCreateForm(CnicUsernameMixin, DesignationChoiceMixin, UserCreationForm):
    class Meta:
        model = User
        fields = SHARED_FIELDS
        widgets = SHARED_WIDGETS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("password1", "password2"):
            self.fields[name].widget.attrs.update(TEXT)


class UserUpdateForm(CnicUsernameMixin, DesignationChoiceMixin):
    new_password = forms.CharField(
        label="Reset Password",
        required=False,
        widget=forms.PasswordInput(attrs={**TEXT, "autocomplete": "new-password"}),
        help_text="Leave blank to keep the current password.",
    )

    class Meta:
        model = User
        fields = SHARED_FIELDS
        widgets = SHARED_WIDGETS

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("new_password")
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user
