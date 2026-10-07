import re
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import DurationField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import (admin_required, can_add_required,
                                 can_delete_required, can_edit_required)
from core.models import AuditLog
from core.utils import diff, log_action, snapshot

from .forms import IncomeTaxAppealForm, SalesTaxAppealForm
from .models import IncomeTaxAppeal, SalesTaxAppeal, Unit, Zone

PAGE_SIZE = 25

# Per-register configuration, so one set of views drives both registers.
REGISTERS = {
    "sales": {
        "model": SalesTaxAppeal,
        "form": SalesTaxAppealForm,
        "label": "Sales Tax",
        "amount_field": "sales_tax_involved",
        "amount_label": "Sales Tax Involved",
        "decision_date_field": "oia_date",
        "search_fields": [
            "ntn", "strn", "appellant_name",
            "oio_no", "oia_no", "ar_name", "passing_officer_name",
            "passing_officer_designation",
        ],
        "number_hint": "12/ST/CIR(A-II)/FSD/25",
        "order_date_fields": ["oio_date"],
        "list_url": "appeals:sales_tax_list",
        "detail_url": "appeals:sales_tax_detail",
        "create_url": "appeals:sales_tax_create",
        "update_url": "appeals:sales_tax_update",
        "delete_url": "appeals:sales_tax_delete",
        "export_url": "appeals:sales_tax_export",
        "cover_url": "appeals:sales_tax_cover",
        "call_proof_url": "appeals:sales_tax_call_proof",
        "order_sheet_url": "appeals:sales_tax_order_sheet",
        # Sales Tax only, for now: the office supplied these three formats for
        # that register alone. The detail template skips any key it cannot find.
        "receiving_slip_url": "appeals:sales_tax_receiving_slip",
        "hearing_notice_url": "appeals:sales_tax_hearing_notice",
        "stay_call_url": "appeals:sales_tax_stay_call",
        "section_branch": "Sales Tax / Appeals-II, Faisalabad",
    },
    "income": {
        "model": IncomeTaxAppeal,
        "form": IncomeTaxAppealForm,
        "label": "Income Tax",
        "amount_field": "revenue_involved",
        "amount_label": "Revenue Involved",
        "decision_date_field": "appellate_order_date",
        "search_fields": [
            "ntn", "cnic", "appellant_name",
            "order_section", "officer_name", "officer_designation", "ar_name",
        ],
        "number_hint": "6398/2026",
        "order_date_fields": ["date_of_assessment"],
        "list_url": "appeals:income_tax_list",
        "detail_url": "appeals:income_tax_detail",
        "create_url": "appeals:income_tax_create",
        "update_url": "appeals:income_tax_update",
        "delete_url": "appeals:income_tax_delete",
        "export_url": "appeals:income_tax_export",
        "cover_url": "appeals:income_tax_cover",
        "call_proof_url": "appeals:income_tax_call_proof",
        "order_sheet_url": "appeals:income_tax_order_sheet",
        "section_branch": "Income Tax / Appeals-II, Faisalabad",
    },
}


# ---------------------------------------------------------------------------
# Monthly Performance Report
# ---------------------------------------------------------------------------
#: The office financial year runs 1 July to 30 June, so the proforma's
#: "upto preceding month" column counts from 1 July of the year in question.
FY_START_MONTH = 7

#: Age buckets shared by both aging tables on the proforma, in months.
AGE_BUCKETS = [
    ("3 Months Old", 0, 3),
    ("4 to 6 Months Old", 3, 6),
    ("7 to 9 Months Old", 6, 9),
    ("10 to 12 Months Old", 9, 12),
    ("More than 12 months Old", 12, None),
]


def fy_start(year, month):
    """1 July of the financial year that the given month falls in."""
    return date(year if month >= FY_START_MONTH else year - 1, FY_START_MONTH, 1)


def month_bounds(year, month):
    """First day of the month, and the first day of the month after it."""
    start = date(year, month, 1)
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, nxt


def _millions(value):
    """The proforma states every amount in millions."""
    return (Decimal(value or 0) / Decimal(1000000)).quantize(Decimal("0.001"))


def _months_between(start, end):
    """Whole months from start to end, the way the office counts age."""
    if not start or not end:
        return None
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def _age_table(appeals, as_of_getter, amount_field):
    """Split appeals across AGE_BUCKETS by age at a per-appeal reference date."""
    rows = [{"label": label, "cases": 0, "revenue": Decimal(0)}
            for label, _, _ in AGE_BUCKETS]
    for a in appeals:
        age = _months_between(a.date_of_institution, as_of_getter(a))
        if age is None:
            continue
        for i, (_, low, high) in enumerate(AGE_BUCKETS):
            if age >= low and (high is None or age < high):
                rows[i]["cases"] += 1
                rows[i]["revenue"] += getattr(a, amount_field) or 0
                break
    for r in rows:
        r["revenue"] = _millions(r["revenue"])
    return rows


def mpr_figures(cfg, year, month):
    """Everything on the proforma that the register can work out on its own.

    Anything the register does not record - transfers, withdrawals, remand
    backs, ADRC stays, stay applications and superior court directions - is
    deliberately absent here and printed as an empty box for the office to
    fill in by hand.
    """
    model = cfg["model"]
    amount = cfg["amount_field"]
    decided_on = cfg["decision_date_field"]
    start, nxt = month_bounds(year, month)
    fy = fy_start(year, month)

    base = model.objects.all()
    undecided_at = lambda d: Q(**{f"{decided_on}__isnull": True}) | Q(**{f"{decided_on}__gte": d})

    # Carried in from before the month: filed earlier and still open on day one.
    opening = base.filter(Q(date_of_institution__lt=start) & undecided_at(start))
    fresh = base.filter(date_of_institution__gte=start, date_of_institution__lt=nxt)

    decided_month = base.filter(**{f"{decided_on}__gte": start, f"{decided_on}__lt": nxt})
    decided_fy_before = base.filter(**{f"{decided_on}__gte": fy, f"{decided_on}__lt": start})

    opening_count = opening.count()
    fresh_count = fresh.count()
    available = opening_count + fresh_count
    decided_count = decided_month.count()

    # Still open at the end of the month.
    pendency = base.filter(Q(date_of_institution__lt=nxt) & undecided_at(nxt))

    sum_of = lambda qs: qs.aggregate(t=Sum(amount))["t"] or 0
    end_of_month = nxt - timedelta(days=1)

    analysis = []
    for value, label in model.Decision.choices:
        if value == model.Decision.PENDING:
            continue
        m = decided_month.filter(decision_status=value)
        f = base.filter(decision_status=value,
                        **{f"{decided_on}__gte": fy, f"{decided_on}__lt": nxt})
        analysis.append({
            "label": label,
            "month_cases": m.count(), "month_revenue": _millions(sum_of(m)),
            "fy_cases": f.count(), "fy_revenue": _millions(sum_of(f)),
        })

    decided_fy = base.filter(**{f"{decided_on}__gte": fy, f"{decided_on}__lt": nxt})
    return {
        "period": start,
        "fy_start": fy,
        "opening_balance": opening_count,
        "fresh_filing": fresh_count,
        "fresh_revenue": _millions(sum_of(fresh)),
        "available": available,
        "decided_month": decided_count,
        "decided_upto_preceding": decided_fy_before.count(),
        "decided_upto_month": decided_fy_before.count() + decided_count,
        "decided_revenue_month": _millions(sum_of(decided_month)),
        "decided_revenue_upto": _millions(sum_of(decided_fy)),
        "balance_pendency": available - decided_count,
        "pendency_revenue": _millions(sum_of(pendency)),
        "decided_ages": _age_table(
            decided_month.only("pk", "date_of_institution", decided_on, amount),
            lambda a: getattr(a, decided_on), amount),
        "pendency_ages": _age_table(
            pendency.only("pk", "date_of_institution", amount),
            lambda a: end_of_month, amount),
        "analysis": analysis,
        "analysis_total_month": decided_count,
        "analysis_revenue_month": _millions(sum_of(decided_month)),
        "analysis_total_fy": decided_fy.count(),
        "analysis_revenue_fy": _millions(sum_of(decided_fy)),
    }


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------
#: Column key -> the field list handed to order_by(), ascending. A key that is
#: not in here is ignored, so a hand-typed ?sort= cannot reach the ORM.
#: "amount" and "filing" are resolved per register in sort_fields() below,
#: because the underlying column differs between the two.
SORTABLE = {
    "appeal_no": ["year", "serial_no", "serial_suffix"],
    "instituted": ["date_of_institution"],
    "appellant": ["appellant_name"],
    "ntn": ["ntn"],
    "tax": None,
    "zone": ["zone__order", "unit__order"],
    "amount": None,
    "filing": ["filing_gap"],
    "decide_by": ["first_expiry_120"],
    "extension": ["second_expiry_180"],
    "decision": ["decision_status"],
    "service": ["service_status"],
}

DEFAULT_SORT = "appeal_no"
DEFAULT_DIR = "desc"


def sort_fields(key, cfg):
    """The ascending order_by() list for one column of one register."""
    if key == "amount":
        return [cfg["amount_field"]]
    if key == "tax":
        return ["tax_period" if cfg["model"] is SalesTaxAppeal else "tax_year"]
    return SORTABLE.get(key)


def apply_sorting(request, qs, cfg):
    """Order the register by ?sort= and ?dir=, falling back to the default."""
    key = request.GET.get("sort", "").strip() or DEFAULT_SORT
    if key not in SORTABLE:
        key = DEFAULT_SORT
    direction = request.GET.get("dir", "").strip()
    if direction not in ("asc", "desc"):
        direction = DEFAULT_DIR if key == DEFAULT_SORT else "asc"

    fields = sort_fields(key, cfg)
    if not fields:
        return qs, DEFAULT_SORT, DEFAULT_DIR

    if key == "filing":
        # Days taken to file. The clock starts at the service date when there is
        # one, otherwise at the order date, so mirror that in the database.
        qs = qs.annotate(
            filing_gap=ExpressionWrapper(
                F("date_of_institution") - Coalesce(
                    F("date_of_service"), F(cfg["order_date_fields"][0])
                ),
                output_field=DurationField(),
            )
        )

    # Nulls last in both directions, so empty cells never head the register.
    if direction == "desc":
        order = [F(f).desc(nulls_last=True) for f in fields]
    else:
        order = [F(f).asc(nulls_last=True) for f in fields]
    return qs.order_by(*order), key, direction


def sort_columns(request, cfg, current_key, current_dir):
    """What the template needs to draw each heading: link target and arrow."""
    out = {}
    for key in SORTABLE:
        if not sort_fields(key, cfg):
            continue
        active = key == current_key
        # Clicking the active column flips it; a new column starts ascending.
        out[key] = {
            "key": key,
            "active": active,
            "dir": current_dir if active else "",
            "next_dir": "desc" if (active and current_dir == "asc") else "asc",
        }
    return out


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def apply_filters(request, cfg):
    qs = cfg["model"].objects.select_related("zone", "unit").all()
    today = timezone.localdate()

    q = request.GET.get("q", "").strip()
    if q:
        lookup = Q()
        for field in cfg["search_fields"]:
            lookup |= Q(**{f"{field}__icontains": q})

        # The Appeal No. is composed, not stored, so match its parts instead.
        # Accepts "12", "12/2026" or a full "12/ST/CIR(A-II)/FSD/2026".
        parts = [p for p in re.split(r"[/\s]+", q) if p.isdigit()]
        if parts:
            serial = int(parts[0])
            number_lookup = Q(serial_no=serial)
            years = []
            for p in parts[1:]:
                if len(p) == 4:
                    years.append(int(p))
                elif len(p) == 2:
                    years.append(2000 + int(p))
            if years:
                number_lookup &= Q(year=years[0])
            lookup |= number_lookup

        qs = qs.filter(lookup)

    zone = request.GET.get("zone", "").strip()
    if zone:
        qs = qs.filter(zone_id=zone)

    unit = request.GET.get("unit", "").strip()
    if unit:
        qs = qs.filter(unit_id=unit)

    status = request.GET.get("status", "").strip()
    if status:
        qs = qs.filter(decision_status=status)

    service = request.GET.get("service", "").strip()
    if service:
        qs = qs.filter(service_status=service)

    date_field = cfg["decision_date_field"]
    pendency = request.GET.get("pendency", "").strip()
    if pendency == "pending":
        qs = qs.filter(**{f"{date_field}__isnull": True})
    elif pendency == "decided":
        qs = qs.filter(**{f"{date_field}__isnull": False})

    expiry = request.GET.get("expiry", "").strip()
    if expiry == "overdue_180":
        qs = qs.filter(**{f"{date_field}__isnull": True}, second_expiry_180__lt=today)
    elif expiry == "overdue_120":
        qs = qs.filter(
            **{f"{date_field}__isnull": True},
            first_expiry_120__lt=today,
            second_expiry_180__gte=today,
        )
    elif expiry == "due_soon":
        qs = qs.filter(
            **{f"{date_field}__isnull": True},
            second_expiry_180__gte=today,
            second_expiry_180__lte=today + timedelta(days=30),
        )

    date_from = request.GET.get("from", "").strip()
    if date_from:
        qs = qs.filter(date_of_institution__gte=date_from)

    date_to = request.GET.get("to", "").strip()
    if date_to:
        qs = qs.filter(date_of_institution__lte=date_to)

    # Filing delay depends on which date starts the clock, which differs per
    # register, so it is evaluated in Python and applied as a pk filter.
    filing = request.GET.get("filing", "").strip()
    if filing in {"late", "in_time"}:
        want_late = filing == "late"
        pks = [a.pk for a in qs.only("pk", "date_of_institution", "date_of_service",
                                     *cfg["order_date_fields"])
               if a.filing_delay_days is not None and a.filed_late == want_late]
        qs = qs.filter(pk__in=pks)

    return qs


def register_context(request, key):
    cfg = REGISTERS[key]
    qs = apply_filters(request, cfg)

    totals = qs.aggregate(total=Sum(cfg["amount_field"]))
    qs, sort_key, sort_dir = apply_sorting(request, qs, cfg)

    paginator = Paginator(qs, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    # Everything except the paging and sorting keys, so a heading link keeps the
    # filters the clerk has already set.
    sort_params = params.copy()
    sort_params.pop("sort", None)
    sort_params.pop("dir", None)

    return {
        "cfg": cfg,
        "register": key,
        "page_obj": page,
        "appeals": page.object_list,
        "total_count": paginator.count,
        "total_amount": totals["total"] or 0,
        "zones": Zone.objects.filter(is_active=True),
        "units": Unit.objects.filter(is_active=True).select_related("zone"),
        "decision_choices": cfg["model"].Decision.choices,
        "service_choices": cfg["model"]._meta.get_field("service_status").choices,
        "querystring": params.urlencode(),
        "sort_querystring": sort_params.urlencode(),
        "sort_key": sort_key,
        "sort_dir": sort_dir,
        "sort_cols": sort_columns(request, cfg, sort_key, sort_dir),
        "filters": {
            "q": request.GET.get("q", ""),
            "zone": request.GET.get("zone", ""),
            "unit": request.GET.get("unit", ""),
            "status": request.GET.get("status", ""),
            "service": request.GET.get("service", ""),
            "pendency": request.GET.get("pendency", ""),
            "expiry": request.GET.get("expiry", ""),
            "filing": request.GET.get("filing", ""),
            "from": request.GET.get("from", ""),
            "to": request.GET.get("to", ""),
        },
    }


# ---------------------------------------------------------------------------
# Sales Tax register
# ---------------------------------------------------------------------------
@login_required
def sales_tax_list(request):
    return render(request, "appeals/appeal_list.html", register_context(request, "sales"))


@login_required
def income_tax_list(request):
    return render(request, "appeals/appeal_list.html", register_context(request, "income"))


# ---------------------------------------------------------------------------
# Monthly Performance Report - Admin / Supervisor only
# ---------------------------------------------------------------------------
def _mpr(request, key):
    cfg = REGISTERS[key]
    today = timezone.localdate()

    # ?month=YYYY-MM, defaulting to the month just gone, which is the one the
    # office actually reports on.
    raw = request.GET.get("month", "").strip()
    try:
        year, month = (int(x) for x in raw.split("-"))
        date(year, month, 1)
    except (ValueError, TypeError):
        first = today.replace(day=1)
        last_month = first - timedelta(days=1)
        year, month = last_month.year, last_month.month

    # Blank by default, the way the office fills it today. ?fill=1 works out
    # everything the register can supply and prints the rest as empty boxes.
    figures = mpr_figures(cfg, year, month) if request.GET.get("fill") == "1" else None

    return render(request, "appeals/mpr.html", {
        "cfg": cfg,
        "register": key,
        "figures": figures,
        "period": date(year, month, 1),
        "month_value": "%04d-%02d" % (year, month),
        "age_buckets": [label for label, _, _ in AGE_BUCKETS],
        "decision_labels": [l for v, l in cfg["model"].Decision.choices
                            if v != cfg["model"].Decision.PENDING],
        "auto_print": request.GET.get("print") == "1",
    })


@login_required
@admin_required
def sales_tax_mpr(request):
    return _mpr(request, "sales")


@login_required
@admin_required
def income_tax_mpr(request):
    return _mpr(request, "income")


@login_required
@admin_required
def mpr_letter(request):
    """The covering letter that goes on top of the two proformas."""
    today = timezone.localdate()
    raw = request.GET.get("month", "").strip()
    try:
        year, month = (int(x) for x in raw.split("-"))
        date(year, month, 1)
    except (ValueError, TypeError):
        first = today.replace(day=1)
        last_month = first - timedelta(days=1)
        year, month = last_month.year, last_month.month
    fy = fy_start(year, month)
    return render(request, "appeals/mpr_letter.html", {
        "period": date(year, month, 1),
        "month_value": "%04d-%02d" % (year, month),
        # The office writes the financial year on the file number as 2026-27.
        "fy_label": "%d-%02d" % (fy.year, (fy.year + 1) % 100),
        "auto_print": request.GET.get("print") == "1",
    })


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------
def _detail(request, key, pk):
    cfg = REGISTERS[key]
    appeal = get_object_or_404(cfg["model"].objects.select_related("zone", "unit"), pk=pk)
    history = AuditLog.objects.filter(
        model_name=cfg["model"]._meta.verbose_name.title(), object_id=str(pk)
    )[:20]
    return render(
        request,
        "appeals/appeal_detail.html",
        {"appeal": appeal, "cfg": cfg, "register": key, "history": history},
    )


def _file_cover(request, key, pk):
    """The slip pasted on the physical file jacket."""
    cfg = REGISTERS[key]
    appeal = get_object_or_404(cfg["model"].objects.select_related("zone", "unit"), pk=pk)
    return render(
        request,
        "appeals/file_cover.html",
        {"appeal": appeal, "cfg": cfg, "register": key},
    )


def _call_proof_subject(appeal, key):
    """The subject line, worded per register and drawn from the record."""
    who = (appeal.appellant_name or "").strip()
    ident = (appeal.cnic or appeal.ntn or "").strip() if key == "income" else (
        appeal.ntn or appeal.strn or "").strip()

    if key == "income":
        section = appeal.order_section or "____"
        order_date = appeal.date_of_assessment
        period = f"TAX YEAR {appeal.tax_year}" if appeal.tax_year else "THE RELEVANT TAX YEAR"
        return (
            f"Proof of service of assessment order passed under section {section} "
            f"under Rule 74 of the Income Tax Rule 2002 "
            f"dated {order_date:%d-%m-%Y} " if order_date else
            f"Proof of service of assessment order passed under section {section} "
            f"under Rule 74 of the Income Tax Rule 2002 "
        ) + f"in the case of {who}, Reg. No. {ident or '____'} for {period}"

    oio = appeal.oio_no or "____"
    order_date = appeal.oio_date
    dated = f"dated {order_date:%d-%m-%Y} " if order_date else ""
    period = f"tax period {appeal.tax_period}" if appeal.tax_period else "the relevant tax period"
    return (
        f"Proof of service of Order-in-Original No. {oio} {dated}"
        f"in the case of {who}, NTN/STRN {ident or '____'} for {period}"
    )


def _call_proof(request, key, pk):
    """Letter to the Unit Officer asking for proof of service of the order."""
    cfg = REGISTERS[key]
    appeal = get_object_or_404(cfg["model"].objects.select_related("zone", "unit"), pk=pk)
    return render(
        request,
        "appeals/call_proof.html",
        {
            "appeal": appeal,
            "cfg": cfg,
            "register": key,
            "subject": _call_proof_subject(appeal, key),
            "today": timezone.localdate(),
        },
    )


def _sales_letter(request, template, pk, extra=None):
    """Render one of the Sales Tax letter formats supplied by the office."""
    cfg = REGISTERS["sales"]
    appeal = get_object_or_404(
        cfg["model"].objects.select_related("zone", "unit"), pk=pk
    )
    context = {
        "appeal": appeal,
        "cfg": cfg,
        "register": "sales",
        "today": timezone.localdate(),
    }
    if extra:
        context.update(extra(appeal))
    return render(request, template, context)


def _hearing_notice_subject(appeal):
    """Subject of the hearing notice, naming the order being appealed."""
    oio = appeal.oio_no or "____"
    dated = f" dated {appeal.oio_date:%d-%b-%y}" if appeal.oio_date else ""
    officer = appeal.passing_officer or "the officer concerned"
    where = ", ".join(
        part for part in (
            appeal.unit.name if appeal.unit_id else "",
            appeal.zone.name if appeal.zone_id else "",
        ) if part
    )
    passed_by = f" passed by the {officer}" + (f", {where}" if where else "")
    return (
        f"Hearing in appeal filed against Sales Tax Order in Original No. {oio}"
        f"{dated}{passed_by}"
    )


@login_required
def sales_tax_receiving_slip(request, pk):
    return _sales_letter(request, "appeals/order_receiving_slip.html", pk)


@login_required
def sales_tax_hearing_notice(request, pk):
    return _sales_letter(
        request,
        "appeals/hearing_notice.html",
        pk,
        extra=lambda appeal: {"subject": _hearing_notice_subject(appeal)},
    )


@login_required
def sales_tax_stay_call(request, pk):
    return _sales_letter(request, "appeals/stay_call_notice.html", pk)


def _order_sheet(request, key, pk):
    """The opening noting on the file's order sheet, plus ruled space."""
    cfg = REGISTERS[key]
    appeal = get_object_or_404(cfg["model"].objects.select_related("zone", "unit"), pk=pk)

    user = request.user
    designation = str(user.designation) if user.designation else ""

    return render(
        request,
        "appeals/order_sheet.html",
        {
            "appeal": appeal,
            "cfg": cfg,
            "register": key,
            "order_date": appeal.order_date,
            "prepared_by": user.full_name or user.username,
            "prepared_by_designation": designation,
            "today": timezone.localdate(),
        },
    )


@login_required
def sales_tax_order_sheet(request, pk):
    return _order_sheet(request, "sales", pk)


@login_required
def income_tax_order_sheet(request, pk):
    return _order_sheet(request, "income", pk)


@login_required
def sales_tax_call_proof(request, pk):
    return _call_proof(request, "sales", pk)


@login_required
def income_tax_call_proof(request, pk):
    return _call_proof(request, "income", pk)


@login_required
def sales_tax_cover(request, pk):
    return _file_cover(request, "sales", pk)


@login_required
def income_tax_cover(request, pk):
    return _file_cover(request, "income", pk)


@login_required
def sales_tax_detail(request, pk):
    return _detail(request, "sales", pk)


@login_required
def income_tax_detail(request, pk):
    return _detail(request, "income", pk)


# ---------------------------------------------------------------------------
# Create / Update
# ---------------------------------------------------------------------------
def _who(user):
    """Name recorded against a record, fixed at the moment of the action."""
    if not user or not user.is_authenticated:
        return ""
    if user.full_name:
        return f"{user.full_name} ({user.username})"
    return user.username


def _save_with_free_serial(obj, cfg, attempts=6):
    """Save a new appeal, stepping to the next free serial if one is taken.

    Two clerks adding an appeal at the same moment are both offered the same
    number, and both forms validate before either saves. The loser used to hit
    the database constraint and get a crash page. Now the second one quietly
    moves to the next free serial, and the view tells the clerk it changed.

    Returns the number that had to be given up, or None if the first try stuck.
    """
    if not obj.year and obj.date_of_institution:
        obj.year = obj.date_of_institution.year
    given_up = None
    for _ in range(attempts):
        try:
            with transaction.atomic():
                obj.save()
            return given_up
        except IntegrityError as exc:
            if "unique" not in str(exc).lower():
                raise
            # The save left the instance thinking it has a row; it has not.
            obj.pk = None
            obj._state.adding = True
            if given_up is None:
                given_up = obj.appeal_no
            obj.serial_no = cfg["model"].next_serial_no(obj.year)
    raise IntegrityError(
        "Could not find a free Appeal No. for %s after %d tries." % (obj.year, attempts)
    )


def _save(request, key, pk=None):
    cfg = REGISTERS[key]
    instance = get_object_or_404(cfg["model"], pk=pk) if pk else None
    before = snapshot(instance) if instance else {}
    # Read these before the form binds, because binding overwrites the instance.
    was_saved_at = instance.updated_at if instance else None
    was_saved_by = instance.updated_by_name if instance else ""

    if request.method == "POST":
        form = cfg["form"](request.POST, instance=instance)
        if form.is_valid():
            obj = form.save(commit=False)
            stamp = _who(request.user)
            if instance is None:
                obj.created_by = request.user
                obj.created_by_name = stamp
            obj.updated_by = request.user
            obj.updated_by_name = stamp

            # Did somebody else save this appeal while the form was open?
            clashed_with = None
            if instance is not None and was_saved_at:
                seen = (form.cleaned_data.get("edited_at") or "").strip()
                if seen and seen != was_saved_at.isoformat():
                    clashed_with = (was_saved_by, was_saved_at)

            renumbered_from = _save_with_free_serial(obj, cfg) if instance is None else None
            if instance is not None:
                obj.save()

            after = snapshot(obj)
            log_action(
                request,
                AuditLog.Action.UPDATE if instance else AuditLog.Action.CREATE,
                instance=obj,
                changes=diff(before, after) if instance else after,
                model_name=cfg["model"]._meta.verbose_name.title(),
            )
            messages.success(
                request,
                f"{cfg['label']} appeal {obj.appeal_no} "
                f"{'updated' if instance else 'registered'} successfully.",
            )
            if renumbered_from:
                messages.warning(
                    request,
                    f"Appeal No. {renumbered_from} was taken by another clerk a "
                    f"moment before you saved. This appeal has been registered "
                    f"as {obj.appeal_no} instead.",
                )
            if clashed_with:
                who, when = clashed_with
                messages.warning(
                    request,
                    f"{who or 'Another user'} also saved this appeal at "
                    f"{timezone.localtime(when):%d-%m-%Y %H:%M} while you had it "
                    f"open. Your version has replaced theirs. Check the Audit Log "
                    f"if anything looks wrong.",
                )
            return redirect(cfg["detail_url"], pk=obj.pk)
        messages.error(request, "Please correct the highlighted errors.")
    else:
        form = cfg["form"](instance=instance)

    return render(
        request,
        "appeals/appeal_form.html",
        {"form": form, "cfg": cfg, "register": key, "appeal": instance},
    )


@login_required
@can_add_required
def sales_tax_create(request):
    return _save(request, "sales")


@login_required
@can_edit_required
def sales_tax_update(request, pk):
    return _save(request, "sales", pk)


@login_required
@can_add_required
def income_tax_create(request):
    return _save(request, "income")


@login_required
@can_edit_required
def income_tax_update(request, pk):
    return _save(request, "income", pk)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------
def _delete(request, key, pk):
    cfg = REGISTERS[key]
    appeal = get_object_or_404(cfg["model"], pk=pk)

    if request.method == "POST":
        repr_ = str(appeal)
        log_action(
            request,
            AuditLog.Action.DELETE,
            instance=appeal,
            changes=snapshot(appeal),
            model_name=cfg["model"]._meta.verbose_name.title(),
            object_repr=repr_,
        )
        appeal.delete()
        messages.success(request, f"Appeal {repr_} was deleted.")
        return redirect(cfg["list_url"])

    return render(
        request,
        "appeals/appeal_confirm_delete.html",
        {"appeal": appeal, "cfg": cfg, "register": key},
    )


@login_required
@can_delete_required
def sales_tax_delete(request, pk):
    return _delete(request, "sales", pk)


@login_required
@can_delete_required
def income_tax_delete(request, pk):
    return _delete(request, "income", pk)


# ---------------------------------------------------------------------------
# Dependent dropdown
# ---------------------------------------------------------------------------
@login_required
def units_for_zone(request, zone_id):
    units = Unit.objects.filter(zone_id=zone_id, is_active=True).select_related("zone")
    return JsonResponse(
        {"units": [{"id": u.pk, "name": str(u)} for u in units]}
    )


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------
SALES_COLUMNS = [
    ("ID", lambda a: a.serial_no),
    ("NTN", lambda a: a.ntn),
    ("STRN", lambda a: a.strn),
    ("Appeal No.", lambda a: a.appeal_no),
    ("Date of Institution", lambda a: a.date_of_institution),
    ("Name of Appellant", lambda a: a.appellant_name),
    ("Address", lambda a: a.address),
    ("Contact No.", lambda a: a.contact_no),
    ("Sales Tax Involved", lambda a: a.sales_tax_involved),
    ("Unit", lambda a: a.unit.name if a.unit else ""),
    ("Zone", lambda a: a.zone.name if a.zone else ""),
    ("Passing Officer Name", lambda a: a.passing_officer_name),
    ("Passing Officer Designation", lambda a: a.passing_officer_designation),
    ("Tax Period", lambda a: a.tax_period),
    ("Order-In-Original No.", lambda a: a.oio_no),
    ("Order-In-Original Date", lambda a: a.oio_date),
    ("Name of AR", lambda a: a.ar_name),
    ("AR Type", lambda a: a.ar_type),
    ("Registration No. of AR", lambda a: a.ar_registration_no),
    ("Contact No. of AR", lambda a: a.ar_contact_no),
    ("Date of Service", lambda a: a.date_of_service),
    ("Days Taken to File", lambda a: a.days_taken_to_file),
    ("Filing Status (30 Days)", lambda a: a.filing_status),
    ("First Expiry 120-Days", lambda a: a.first_expiry_120),
    ("Status vs 120 Days", lambda a: a.status_120),
    ("2nd Expiry 180-Days", lambda a: a.second_expiry_180),
    ("Status vs 180 Days", lambda a: a.status_180),
    ("Special Approval Needed", lambda a: "Yes" if a.needs_special_approval else "No"),
    ("Issue Involved", lambda a: a.issue_involved),
    ("Section", lambda a: a.section),
    ("Order-In-Appeal Date", lambda a: a.oia_date),
    ("Order-In-Appeal No.", lambda a: a.oia_no),
    ("Status", lambda a: a.get_decision_status_display()),
    ("Courier No.", lambda a: a.courier_no),
    ("Courier Date", lambda a: a.courier_date),
    ("Service Status", lambda a: a.get_service_status_display()),
]

INCOME_COLUMNS = [
    ("ID / Appeal No.", lambda a: a.appeal_no),
    ("Date of Institution", lambda a: a.date_of_institution),
    ("CNIC", lambda a: a.cnic),
    ("NTN", lambda a: a.ntn),
    ("Name of Appellant", lambda a: a.appellant_name),
    ("Address Line 1", lambda a: a.address_line_1),
    ("Address Line 2", lambda a: a.address_line_2),
    ("Contact No.", lambda a: a.contact_no),
    ("Tax Year", lambda a: a.tax_year),
    ("Order Section", lambda a: a.order_section),
    ("Zone", lambda a: a.zone.name if a.zone else ""),
    ("Unit", lambda a: a.unit.name if a.unit else ""),
    ("Income Assessed", lambda a: a.income_assessed),
    ("Revenue Involved", lambda a: a.revenue_involved),
    ("Date of Assessment", lambda a: a.date_of_assessment),
    ("Name of Officer", lambda a: a.officer_name),
    ("Designation of Officer", lambda a: a.officer_designation),
    ("Issues Involved", lambda a: a.issues_involved),
    ("Date of Service", lambda a: a.date_of_service),
    ("Days Taken to File", lambda a: a.days_taken_to_file),
    ("Filing Status (30 Days)", lambda a: a.filing_status),
    ("First Expiry 120-Days", lambda a: a.first_expiry_120),
    ("Status vs 120 Days", lambda a: a.status_120),
    ("2nd Expiry 180-Days", lambda a: a.second_expiry_180),
    ("Status vs 180 Days", lambda a: a.status_180),
    ("Special Approval Needed", lambda a: "Yes" if a.needs_special_approval else "No"),
    ("Advocate / ITP / AR", lambda a: a.ar_name),
    ("AR Type", lambda a: a.ar_type),
    ("Date of Appellate Order", lambda a: a.appellate_order_date),
    ("Status", lambda a: a.get_decision_status_display()),
    ("Courier No.", lambda a: a.courier_no),
    ("Courier Date", lambda a: a.courier_date),
    ("Service Status", lambda a: a.get_service_status_display()),
]


def _export(request, key, columns):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    cfg = REGISTERS[key]
    qs = apply_filters(request, cfg)

    wb = Workbook()
    ws = wb.active
    ws.title = f"{cfg['label']} Appeals"

    header_fill = PatternFill("solid", fgColor="00693E")
    header_font = Font(bold=True, color="FFFFFF", size=10)
    thin = Side(style="thin", color="BBBBBB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # Title band
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(columns))
    title = ws.cell(row=1, column=1)
    title.value = (
        f"{settings.OFFICE_NAME}, {settings.OFFICE_SUBTITLE} "
        f"— {cfg['label']} Appeals Register"
    )
    title.font = Font(bold=True, size=13, color="00693E")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 24

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(columns))
    sub = ws.cell(row=2, column=1)
    sub.value = (
        f"Generated {timezone.localtime():%d-%m-%Y %H:%M} by {request.user.display_name} "
        f"— {qs.count()} record(s)"
    )
    sub.font = Font(size=9, italic=True, color="666666")
    sub.alignment = Alignment(horizontal="center")

    for col, (heading, _) in enumerate(columns, start=1):
        cell = ws.cell(row=3, column=col, value=heading)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[3].height = 32

    for row_idx, appeal in enumerate(qs, start=4):
        for col, (_, getter) in enumerate(columns, start=1):
            cell = ws.cell(row=row_idx, column=col, value=getter(appeal))
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=False)

    sample = list(qs[:200])
    for col, (heading, getter) in enumerate(columns, start=1):
        letter = ws.cell(row=3, column=col).column_letter
        longest = max(
            [len(str(heading))] + [len(str(getter(a) or "")) for a in sample] or [0]
        )
        ws.column_dimensions[letter].width = min(max(longest + 2, 12), 40)

    ws.freeze_panes = "A4"

    filename = f"{cfg['label'].replace(' ', '_')}_Appeals_{timezone.localdate():%Y-%m-%d}.xlsx"
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


@login_required
def sales_tax_export(request):
    return _export(request, "sales", SALES_COLUMNS)


@login_required
def income_tax_export(request):
    return _export(request, "income", INCOME_COLUMNS)
