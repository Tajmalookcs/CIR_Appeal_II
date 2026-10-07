from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from accounts.decorators import admin_required
from appeals.models import IncomeTaxAppeal, SalesTaxAppeal, Zone

from .models import AuditLog


def _register_stats(model, decision_field, amount_field, today):
    """Counts and money totals for one register."""
    pending_q = Q(**{f"{decision_field}__isnull": True})
    qs = model.objects.all()

    pending = qs.filter(pending_q)
    soon = today + timedelta(days=30)

    return {
        "total": qs.count(),
        "pending": pending.count(),
        "decided": qs.exclude(pending_q).count(),
        "overdue_180": pending.filter(second_expiry_180__lt=today).count(),
        "overdue_120": pending.filter(
            first_expiry_120__lt=today, second_expiry_180__gte=today
        ).count(),
        "due_soon": pending.filter(
            second_expiry_180__gte=today, second_expiry_180__lte=soon
        ).count(),
        "amount": qs.aggregate(t=Sum(amount_field))["t"] or 0,
        "pending_amount": pending.aggregate(t=Sum(amount_field))["t"] or 0,
        "recent": qs.select_related("zone", "unit")[:5],
    }


@login_required
def dashboard(request):
    today = timezone.localdate()

    sales = _register_stats(SalesTaxAppeal, "oia_date", "sales_tax_involved", today)
    income = _register_stats(
        IncomeTaxAppeal, "appellate_order_date", "revenue_involved", today
    )

    zone_rows = []
    for zone in Zone.objects.filter(is_active=True):
        s = zone.salestaxappeals.count()
        i = zone.incometaxappeals.count()
        if s or i:
            zone_rows.append({"zone": zone, "sales": s, "income": i, "total": s + i})

    context = {
        "today": today,
        "sales": sales,
        "income": income,
        "grand_total": sales["total"] + income["total"],
        "grand_pending": sales["pending"] + income["pending"],
        "grand_overdue": sales["overdue_180"] + income["overdue_180"],
        "grand_due_soon": sales["due_soon"] + income["due_soon"],
        "zone_rows": zone_rows,
        "recent_activity": AuditLog.objects.select_related("user")[:8]
        if request.user.is_admin()
        else [],
    }
    return render(request, "core/dashboard.html", context)


def csrf_failure(request, reason=""):
    """Shown when a POST arrives with a missing or stale security token."""
    return render(request, "403_csrf.html", {"reason": reason}, status=403)


@login_required
@admin_required
def audit_log(request):
    logs = AuditLog.objects.select_related("user").all()

    action = request.GET.get("action", "").strip()
    if action:
        logs = logs.filter(action=action)

    username = request.GET.get("user", "").strip()
    if username:
        logs = logs.filter(
            Q(username__icontains=username) | Q(user_full_name__icontains=username)
        )

    model_name = request.GET.get("model", "").strip()
    if model_name:
        logs = logs.filter(model_name__icontains=model_name)

    date_from = request.GET.get("from", "").strip()
    if date_from:
        logs = logs.filter(timestamp__date__gte=date_from)

    date_to = request.GET.get("to", "").strip()
    if date_to:
        logs = logs.filter(timestamp__date__lte=date_to)

    paginator = Paginator(logs, 50)
    page = paginator.get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    return render(
        request,
        "core/audit_log.html",
        {
            "page_obj": page,
            "logs": page.object_list,
            "total_count": paginator.count,
            "action_choices": AuditLog.Action.choices,
            "querystring": params.urlencode(),
            "filters": {
                "action": action,
                "user": username,
                "model": model_name,
                "from": date_from,
                "to": date_to,
            },
        },
    )
