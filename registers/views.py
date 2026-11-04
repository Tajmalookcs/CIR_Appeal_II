"""Stay Application Register and Stay Applications Disposal Report.

Sales Tax: STR-24 (Rule 150ZZC) and STR-26 (Rule 150ZZD(2)).
Income Tax: Rule 76K and Rule 76L(2) of the Income Tax Rules, 2002.

The two taxes never mix: every view takes `tax` ("sales" or "income") and
works only on that tax's appeals and entries.
"""

import calendar as pycal
from datetime import date

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.decorators import (can_add_required, can_delete_required,
                                 can_edit_required)
from appeals.models import IncomeTaxAppeal, SalesTaxAppeal, Zone
from core.models import AuditLog
from core.utils import diff, log_action, snapshot
from core.workdays import Calendar, stay_dispose_by, stay_fixation_date

from .forms import stay_form_for
from .models import IncomeTaxStayApplication, SalesTaxStayApplication

TAXES = {
    "sales": {
        "key": "sales",
        "label": "Sales Tax",
        "appeal_model": SalesTaxAppeal,
        "stay_model": SalesTaxStayApplication,
        "appeal_detail_url": "appeals:sales_tax_detail",
        "id_label": "STRN/ CNIC",
        "name_id_label": "Name, STRN/ CNIC",
        "period_label": "Tax Period(s)",
        "amount_field": "sales_tax_involved",
        "register_form": "STR-24",
        "register_rule": "(See Rule-150ZZC)",
        "report_form": "STR-26",
        "report_rule": "(See sub-rule (2) of Rule 150ZZD)",
        "law": "Sales Tax Rules, 2006",
        "stay_rule": "Rule 150ZZ",
    },
    "income": {
        "key": "income",
        "label": "Income Tax",
        "appeal_model": IncomeTaxAppeal,
        "stay_model": IncomeTaxStayApplication,
        "appeal_detail_url": "appeals:income_tax_detail",
        "id_label": "NTN/ CNIC",
        "name_id_label": "Name, NTN/ CNIC",
        "period_label": "Tax year",
        "amount_field": "revenue_involved",
        "register_form": "",
        "register_rule": "(See Rule-76K)",
        "report_form": "",
        "report_rule": "(See sub-rule (2) of Rule 76L)",
        "law": "Income Tax Rules, 2002",
        "stay_rule": "Rule 76G",
    },
}


def _tax(tax):
    if tax not in TAXES:
        raise Http404("Unknown register")
    return TAXES[tax]


def identity(appeal, tax):
    """STRN/CNIC (Sales Tax) or NTN/CNIC (Income Tax), as on the register."""
    if tax == "sales":
        return appeal.strn or appeal.ntn or ""
    return " / ".join(p for p in (appeal.ntn, appeal.cnic) if p)


def period(appeal, tax):
    return (appeal.tax_period if tax == "sales" else appeal.tax_year) or ""


def amount(appeal, tax):
    return getattr(appeal, TAXES[tax]["amount_field"]) or 0


def _who(user):
    if user.full_name:
        return f"{user.full_name} ({user.username})"
    return user.username


# ---------------------------------------------------------------------------
# Entering stay applications (from the appeal's page)
# ---------------------------------------------------------------------------
def _stay_save(request, tax, appeal_pk=None, pk=None):
    cfg = _tax(tax)
    model = cfg["stay_model"]
    if pk:
        entry = get_object_or_404(model.objects.select_related("appeal"), pk=pk)
        appeal = entry.appeal
    else:
        entry = None
        appeal = get_object_or_404(cfg["appeal_model"], pk=appeal_pk)
    before = snapshot(entry) if entry else {}
    back = reverse(cfg["appeal_detail_url"], args=[appeal.pk]) + "#stay-applications"

    form = stay_form_for(model)(request.POST or None, instance=entry)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.appeal = appeal
        stamp = _who(request.user)
        if entry is None:
            obj.created_by = request.user
            obj.created_by_name = stamp
        obj.updated_by = request.user
        obj.updated_by_name = stamp
        obj.save()
        log_action(
            request,
            AuditLog.Action.UPDATE if entry else AuditLog.Action.CREATE,
            instance=obj,
            changes=diff(before, snapshot(obj)) if entry else snapshot(obj),
            model_name=model._meta.verbose_name.title(),
        )
        messages.success(
            request,
            f"Stay application {'updated' if entry else 'entered'} for appeal "
            f"{appeal.appeal_no}. Hearing fixed for {obj.date_of_fixation:%d-%m-%Y}; "
            f"to be disposed of by {obj.dispose_by:%d-%m-%Y}.",
        )
        return redirect(back)

    today = timezone.localdate()
    suggestion = stay_fixation_date(today)
    intro = (
        f"<strong>{cfg['stay_rule']}, {cfg['law']}:</strong> an application received before "
        f"01:00 PM on a working day is fixed for hearing on the next working day; after "
        f"01:00 PM, on the day after the next working day. It must be disposed of within "
        f"seven working days of fixation. Leave <em>Date of Fixation</em> blank and it is "
        f"worked out from the receipt date and time, counting weekends and the holidays on "
        f"the Holidays page (for an application received this morning: "
        f"{suggestion:%d-%m-%Y})."
    )
    return render(request, "core/simple_form.html", {
        "form": form,
        "title": ("Edit" if entry else "Add") + " Stay Application",
        "subtitle": f"{cfg['label']} appeal {appeal.appeal_no} - {appeal.appellant_name}",
        "intro": intro,
        "back_url": back,
        "submit_label": "Save Stay Application",
    })


@login_required
@can_add_required
def stay_create(request, tax, appeal_pk):
    return _stay_save(request, tax, appeal_pk=appeal_pk)


@login_required
@can_edit_required
def stay_update(request, tax, pk):
    return _stay_save(request, tax, pk=pk)


@login_required
@can_delete_required
def stay_delete(request, tax, pk):
    cfg = _tax(tax)
    entry = get_object_or_404(cfg["stay_model"].objects.select_related("appeal"), pk=pk)
    back = reverse(cfg["appeal_detail_url"], args=[entry.appeal_id]) + "#stay-applications"
    if request.method == "POST":
        repr_ = str(entry)
        log_action(request, AuditLog.Action.DELETE, instance=entry, changes=snapshot(entry),
                   model_name=cfg["stay_model"]._meta.verbose_name.title(), object_repr=repr_)
        entry.delete()
        messages.success(request, f"{repr_} was deleted.")
    return redirect(back)


# ---------------------------------------------------------------------------
# Shared helpers for the register and the report
# ---------------------------------------------------------------------------
def _with_deadlines(entries):
    """Attach dispose-by / overdue, using one calendar for the whole list."""
    entries = list(entries)
    today = timezone.localdate()
    cal = Calendar(today, span_days=400)
    for e in entries:
        fixed = e.date_of_fixation or stay_fixation_date(e.date_of_receipt, e.time_of_receipt, cal)
        e.due = stay_dispose_by(fixed, cal) if fixed else None
        end = e.date_of_order or today
        e.overdue = bool(e.due and end > e.due)
        e.late_days = (end - e.due).days if e.overdue else 0
    return entries


def _excel(filename, title, subtitle, headings, rows):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    n = len(headings)

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n)
    ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=13)
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="center")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=n)
    ws.cell(row=2, column=1, value=subtitle).alignment = Alignment(horizontal="center")

    for col, (label, num) in enumerate(headings, start=1):
        c = ws.cell(row=3, column=col, value=label)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="00693E")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border
        k = ws.cell(row=4, column=col, value=num)
        k.alignment = Alignment(horizontal="center")
        k.border = border
    ws.row_dimensions[3].height = 45

    for r, row in enumerate(rows, start=5):
        for col, value in enumerate(row, start=1):
            c = ws.cell(row=r, column=col, value=value)
            c.border = border
            if isinstance(value, date):
                c.number_format = "DD-MM-YYYY"
    for col, (label, _) in enumerate(headings, start=1):
        width = max([len(str(label)) // 2 + 4] + [len(str(r[col - 1] or "")) + 2 for r in rows])
        ws.column_dimensions[ws.cell(row=3, column=col).column_letter].width = min(width, 45)
    ws.freeze_panes = "A5"

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


def _parse_date(raw):
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Stay Application Register
# ---------------------------------------------------------------------------
@login_required
def stay_register(request, tax):
    cfg = _tax(tax)
    qs = cfg["stay_model"].objects.select_related("appeal", "appeal__zone", "appeal__unit")

    f = {k: request.GET.get(k, "").strip() for k in ("from", "to", "zone", "status", "q")}
    d_from, d_to = _parse_date(f["from"]), _parse_date(f["to"])
    if d_from:
        qs = qs.filter(date_of_receipt__gte=d_from)
    if d_to:
        qs = qs.filter(date_of_receipt__lte=d_to)
    if f["zone"]:
        qs = qs.filter(appeal__zone_id=f["zone"])
    if f["status"] == "pending":
        qs = qs.filter(date_of_order__isnull=True)
    elif f["status"] in ("disposed", "granted", "not_granted"):
        qs = qs.filter(date_of_order__isnull=False)
        if f["status"] != "disposed":
            qs = qs.filter(decision=f["status"])
    if f["q"]:
        q = f["q"]
        lookup = Q(appeal__appellant_name__icontains=q) | Q(appeal__ntn__icontains=q)
        lookup |= Q(appeal__strn__icontains=q) if tax == "sales" else Q(appeal__cnic__icontains=q)
        digits = [p for p in q.replace("/", " ").split() if p.isdigit()]
        if digits:
            lookup |= Q(appeal__serial_no=int(digits[0]))
        qs = qs.filter(lookup)

    entries = _with_deadlines(qs.order_by("date_of_receipt", "pk"))
    if f["status"] == "overdue":
        entries = [e for e in entries if e.overdue and not e.date_of_order]

    headings = [
        ("S.#", "(1)"), ("Appeal No.", "(2)"), ("Date of institution of Appeal", "(3)"),
        (cfg["name_id_label"], "(4)"), ("Date of receipt", "(5)"),
        (cfg["period_label"], "(6)"), ("Zone/Field formation", "(7)"),
        ("Revenue involved", "(8)"), ("Stay granted for number of days/not granted", "(9)"),
        ("Date of order", "(10)"),
    ]
    rows = []
    for i, e in enumerate(entries, start=1):
        a = e.appeal
        rows.append({
            "entry": e,
            "cells": [
                i, a.appeal_no, a.date_of_institution,
                f"{a.appellant_name}\n{identity(a, tax)}".strip(),
                e.date_of_receipt, period(a, tax), _zone(a),
                amount(a, tax), e.outcome, e.date_of_order,
            ],
        })

    period_line = _range_line(d_from, d_to)
    if request.GET.get("export") == "xlsx":
        return _excel(
            f"{cfg['label'].replace(' ', '_')}_Stay_Application_Register.xlsx",
            f"{cfg['label']} - Stay Application Register",
            f"{cfg['register_form']} {cfg['register_rule']} {cfg['law']}. {period_line}".strip(),
            headings,
            [[c.replace("\n", ", ") if isinstance(c, str) else c for c in r["cells"]] for r in rows],
        )

    context = {
        "cfg": cfg, "tax": tax, "headings": headings, "rows": rows, "filters": f,
        "zones": Zone.objects.filter(is_active=True), "period_line": period_line,
        "title": "Stay Application Register",
        "form_no": cfg["register_form"], "rule": cfg["register_rule"],
        "amount_col": 7,
    }
    if request.GET.get("print") == "1":
        return render(request, "registers/print_sheet.html", context)
    return render(request, "registers/stay_register.html", context)


def _zone(appeal):
    parts = [appeal.zone.name if appeal.zone_id else "", appeal.unit.name if appeal.unit_id else ""]
    return ", ".join(p for p in parts if p)


def _range_line(d_from, d_to):
    if d_from and d_to:
        return f"From {d_from:%d-%m-%Y} to {d_to:%d-%m-%Y}"
    if d_from:
        return f"From {d_from:%d-%m-%Y}"
    if d_to:
        return f"Up to {d_to:%d-%m-%Y}"
    return ""


# ---------------------------------------------------------------------------
# Stay Applications Disposal Report (submitted by the 5th and the 20th)
# ---------------------------------------------------------------------------
PARTS = {
    "full": "Whole month",
    "first": "1st to 15th",
    "second": "16th to end of month",
}


def report_period(year, month, part):
    last = pycal.monthrange(year, month)[1]
    if part == "first":
        return date(year, month, 1), date(year, month, 15)
    if part == "second":
        return date(year, month, 16), date(year, month, last)
    return date(year, month, 1), date(year, month, last)


@login_required
def stay_report(request, tax):
    cfg = _tax(tax)
    today = timezone.localdate()
    raw = request.GET.get("month", "")
    try:
        year, month = (int(x) for x in raw.split("-"))
        date(year, month, 1)
    except (ValueError, TypeError):
        year, month = today.year, today.month
    part = request.GET.get("part", "full")
    if part not in PARTS:
        part = "full"
    start, end = report_period(year, month, part)

    # Every application dealt with in the period: received by its end and not
    # already disposed of before it began - so the report shows those received,
    # those decided, and those still pending.
    qs = (cfg["stay_model"].objects.select_related("appeal")
          .filter(date_of_receipt__lte=end)
          .filter(Q(date_of_order__isnull=True) | Q(date_of_order__gte=start))
          .order_by("date_of_receipt", "pk"))
    entries = _with_deadlines(qs)

    headings = [
        ("S.#", "(1)"), ("Appeal No.", "(2)"), ("Name of Taxpayer", "(3)"),
        (cfg["id_label"], "(4)"), ("Date of Receipt of Application", "(5)"),
        ("Date of Fixation", "(6)"), ("Date of Disposal", "(7)"),
    ]
    rows = []
    for i, e in enumerate(entries, start=1):
        a = e.appeal
        disposal = e.date_of_order if (e.date_of_order and e.date_of_order <= end) else None
        rows.append({
            "entry": e,
            "cells": [i, a.appeal_no, a.appellant_name, identity(a, tax),
                      e.date_of_receipt, e.date_of_fixation, disposal],
        })

    month_label = date(year, month, 1).strftime("%B, %Y")
    period_line = "" if part == "full" else f"Period: {start:%d-%m-%Y} to {end:%d-%m-%Y}"
    if request.GET.get("export") == "xlsx":
        return _excel(
            f"{cfg['label'].replace(' ', '_')}_Stay_Disposal_Report_{year}-{month:02d}_{part}.xlsx",
            f"{cfg['label']} - Stay Applications Disposal Report for the month of {month_label}",
            f"{cfg['report_form']} {cfg['report_rule']} {cfg['law']}. {period_line}".strip(),
            headings, [r["cells"] for r in rows],
        )

    context = {
        "cfg": cfg, "tax": tax, "headings": headings, "rows": rows,
        "title": "Stay Applications Disposal Report",
        "title_line2": f"For the month of {month_label}",
        "form_no": cfg["report_form"], "rule": cfg["report_rule"],
        "period_line": period_line, "month_value": f"{year:04d}-{month:02d}",
        "part": part, "parts": PARTS, "amount_col": None,
    }
    if request.GET.get("print") == "1":
        return render(request, "registers/print_sheet.html", context)
    return render(request, "registers/stay_report.html", context)
