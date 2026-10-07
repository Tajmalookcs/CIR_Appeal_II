from django.contrib.auth.models import AbstractUser
from django.db import models


class Designation(models.Model):
    """Office designations, managed from the admin rather than typed freehand.

    Kept as a lookup so a posting title can be corrected once and every user
    holding it follows, and so the list stays consistent between clerks.
    """

    name = models.CharField("Designation", max_length=120, unique=True)
    short_name = models.CharField("Short Form", max_length=30, blank=True)
    order = models.PositiveSmallIntegerField("Display Order", default=0)
    is_active = models.BooleanField("Active", default=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "Designation"
        verbose_name_plural = "Designations"

    def __str__(self):
        return self.name


class User(AbstractUser):
    """Custom user for the Commissioner (Appeals-II) office."""

    ROLE_ADMIN = "admin_supervisor"
    ROLE_COMMISSIONER = "commissioner"
    ROLE_DATA_ENTRY = "data_entry"

    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin / Supervisor"),
        (ROLE_COMMISSIONER, "Commissioner IR (View Only)"),
        (ROLE_DATA_ENTRY, "Data Entry Operator"),
    ]

    full_name = models.CharField("Full Name", max_length=150, blank=True)
    designation = models.ForeignKey(
        Designation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="users", verbose_name="Designation",
    )
    role = models.CharField(
        "Role", max_length=30, choices=ROLE_CHOICES, default=ROLE_DATA_ENTRY
    )
    contact_no = models.CharField("Contact No.", max_length=20, blank=True)

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["username"]

    def __str__(self):
        return f"{self.display_name} ({self.get_role_display()})"

    @property
    def display_name(self):
        return self.full_name or self.get_full_name() or self.username

    # ---- permission helpers -------------------------------------------------
    def is_admin(self):
        return self.is_superuser or self.role == self.ROLE_ADMIN

    def can_view(self):
        return self.is_active

    def can_add(self):
        return self.is_admin() or self.role == self.ROLE_DATA_ENTRY

    def can_edit(self):
        return self.is_admin() or self.role == self.ROLE_DATA_ENTRY

    def can_delete(self):
        return self.is_admin()

    def can_manage_users(self):
        return self.is_admin()

    def can_view_logs(self):
        return self.is_admin()
