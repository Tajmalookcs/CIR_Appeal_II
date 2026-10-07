"""Role gates used across the appeal views."""

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def _guard(check, message):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect("accounts:login")
            if not check(user):
                messages.error(request, message)
                raise PermissionDenied(message)
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


can_add_required = _guard(
    lambda u: u.can_add(), "You do not have permission to add records."
)
can_edit_required = _guard(
    lambda u: u.can_edit(), "You do not have permission to edit records."
)
can_delete_required = _guard(
    lambda u: u.can_delete(), "Only an Admin / Supervisor may delete records."
)
admin_required = _guard(
    lambda u: u.is_admin(), "This section is restricted to Admin / Supervisor users."
)
