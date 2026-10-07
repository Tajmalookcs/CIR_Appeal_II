"""Audit-log helpers."""

from django.forms.models import model_to_dict

from core.models import AuditLog


def get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def snapshot(instance):
    """Plain dict of an instance's editable fields, safe for JSON storage."""
    if instance is None or instance.pk is None:
        return {}
    data = model_to_dict(instance)
    return {k: _clean(v) for k, v in data.items()}


def _clean(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def diff(before, after):
    """Field-by-field old -> new for everything that actually changed."""
    changes = {}
    for field, new_value in after.items():
        old_value = before.get(field)
        if old_value != new_value:
            changes[field] = {"from": old_value, "to": new_value}
    return changes


def log_action(request, action, instance=None, changes=None, model_name="", object_repr=""):
    """Write one audit entry. Never raises - logging must not break a save."""
    user = getattr(request, "user", None)
    if user is not None and not user.is_authenticated:
        user = None

    try:
        AuditLog.objects.create(
            user=user,
            # Names are copied in, not looked up later: the account may be
            # renamed or handed to a different person, but history must not move.
            username=(user.username if user else (object_repr or "anonymous")),
            user_full_name=(user.full_name if user else ""),
            user_designation=(str(user.designation) if user and user.designation else ""),
            action=action,
            model_name=model_name or (instance._meta.verbose_name.title() if instance else ""),
            object_id=str(instance.pk) if instance is not None and instance.pk else "",
            object_repr=object_repr or (str(instance) if instance is not None else ""),
            changes=changes or {},
            ip_address=get_client_ip(request) if request else None,
        )
    except Exception:  # pragma: no cover - logging is best-effort
        pass
