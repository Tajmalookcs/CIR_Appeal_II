from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Immutable record of every change made in the system."""

    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        LOGIN = "login", "Login"
        LOGOUT = "logout", "Logout"
        LOGIN_FAILED = "login_failed", "Failed Login"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="audit_logs",
    )
    # Snapshots taken at the time of the action. The FK above may be renamed,
    # reassigned to a different person, or deleted; these must not change.
    username = models.CharField("Username", max_length=150, blank=True)
    user_full_name = models.CharField("Name of User", max_length=150, blank=True)
    user_designation = models.CharField("Designation", max_length=100, blank=True)

    action = models.CharField("Action", max_length=20, choices=Action.choices)
    model_name = models.CharField("Record Type", max_length=50, blank=True)
    object_id = models.CharField("Record ID", max_length=50, blank=True)
    object_repr = models.CharField("Record", max_length=255, blank=True)
    changes = models.JSONField("Changes", default=dict, blank=True)
    ip_address = models.GenericIPAddressField("IP Address", null=True, blank=True)
    timestamp = models.DateTimeField("Timestamp", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Audit Log Entry"
        verbose_name_plural = "Audit Log"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp:%d-%m-%Y %H:%M} | {self.actor} | {self.get_action_display()} | {self.object_repr}"

    @property
    def actor(self):
        """Who did this, as recorded at the time - never the current account holder."""
        if self.user_full_name and self.username:
            return f"{self.user_full_name} ({self.username})"
        return self.user_full_name or self.username or "—"

    @property
    def change_summary(self):
        """Readable one-line summary of what changed."""
        if not self.changes:
            return ""
        return ", ".join(f"{field}" for field in self.changes.keys())
