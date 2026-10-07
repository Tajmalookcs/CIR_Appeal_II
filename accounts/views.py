from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from core.models import AuditLog
from core.utils import diff, log_action, snapshot

from .decorators import admin_required
from .forms import UserCreateForm, UserUpdateForm
from .models import User


def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)

        if user is not None:
            if not user.is_active:
                messages.error(request, "This account has been disabled.")
            else:
                login(request, user)
                log_action(request, AuditLog.Action.LOGIN, object_repr=user.username)
                return redirect(request.GET.get("next") or "core:dashboard")
        else:
            log_action(
                request, AuditLog.Action.LOGIN_FAILED,
                object_repr=username or "unknown",
                model_name="Authentication",
            )
            messages.error(request, "Invalid username or password.")

    return render(request, "accounts/login.html")


@login_required
def logout_view(request):
    log_action(request, AuditLog.Action.LOGOUT, object_repr=request.user.username)
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("accounts:login")


@login_required
def profile(request):
    return render(request, "accounts/profile.html")


# ---------------------------------------------------------------------------
# User management (Admin / Supervisor only)
# ---------------------------------------------------------------------------
@login_required
@admin_required
def user_list(request):
    return render(request, "accounts/user_list.html", {"users": User.objects.all()})


@login_required
@admin_required
def user_create(request):
    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_action(
                request, AuditLog.Action.CREATE, instance=user,
                changes={"username": user.username, "role": user.role},
                model_name="User",
            )
            messages.success(request, f"User '{user.username}' created.")
            return redirect("accounts:user_list")
        messages.error(request, "Please correct the highlighted errors.")
    else:
        form = UserCreateForm()
    return render(request, "accounts/user_form.html", {"form": form, "creating": True})


@login_required
@admin_required
def user_update(request, pk):
    user_obj = get_object_or_404(User, pk=pk)
    before = snapshot(user_obj)

    if request.method == "POST":
        form = UserUpdateForm(request.POST, instance=user_obj)
        if form.is_valid():
            updated = form.save()
            log_action(
                request, AuditLog.Action.UPDATE, instance=updated,
                changes=diff(before, snapshot(updated)), model_name="User",
            )
            messages.success(request, f"User '{updated.username}' updated.")
            return redirect("accounts:user_list")
        messages.error(request, "Please correct the highlighted errors.")
    else:
        form = UserUpdateForm(instance=user_obj)

    return render(
        request, "accounts/user_form.html",
        {"form": form, "creating": False, "user_obj": user_obj},
    )
