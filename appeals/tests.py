from datetime import date
from importlib import import_module

from django.apps import apps as global_apps
from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import IncomeTaxAppeal, SalesTaxAppeal
from .views import REGISTERS, mpr_figures


class MprMonthTests(TestCase):
    """MPR Month: which month's MPR counts an appeal as decided."""

    def make(self, model=SalesTaxAppeal, serial=1, **kw):
        amount = "sales_tax_involved" if model is SalesTaxAppeal else "revenue_involved"
        return model.objects.create(
            serial_no=serial, date_of_institution=date(2026, 9, 1),
            appellant_name=f"Appellant {serial}", **{amount: 1_000_000}, **kw)

    def test_filled_from_decision_date_and_cleared_when_pending(self):
        a = self.make(oia_date=date(2026, 10, 30), decision_status="confirmed")
        self.assertEqual(a.mpr_month, date(2026, 10, 1))
        a.mpr_month = date(2026, 11, 17)          # moved by the clerk; kept, as the 1st
        a.save()
        self.assertEqual(a.mpr_month, date(2026, 11, 1))
        a.oia_date = None
        a.save()
        self.assertIsNone(a.mpr_month)
        it = self.make(IncomeTaxAppeal, appellate_order_date=date(2026, 10, 5))
        self.assertEqual(it.mpr_month, date(2026, 10, 1))

    def test_mpr_counts_by_mpr_month(self):
        # Decided 30 Oct, processed in the November MPR.
        self.make(serial=1, oia_date=date(2026, 10, 30), decision_status="confirmed",
                  mpr_month=date(2026, 11, 1))
        # Decided and reported in October.
        self.make(serial=2, oia_date=date(2026, 10, 10), decision_status="annulled")
        cfg = REGISTERS["sales"]
        october = mpr_figures(cfg, 2026, 10)
        november = mpr_figures(cfg, 2026, 11)
        self.assertEqual(october["decided_month"], 1)
        self.assertEqual(october["balance_pendency"], 1)      # still pending in October
        self.assertEqual(november["opening_balance"], 1)
        self.assertEqual(november["decided_month"], 1)
        self.assertEqual(november["decided_upto_month"], 2)   # financial year to date
        confirmed = next(r for r in november["analysis"] if r["label"] == "Confirmed")
        self.assertEqual(confirmed["month_cases"], 1)

    def test_form_checks_and_register_filter(self):
        clerk = User.objects.create_user("3310000000003", password="x", role=User.ROLE_DATA_ENTRY)
        a = self.make(oia_date=date(2026, 10, 30), decision_status="confirmed")
        self.make(serial=2, oia_date=date(2026, 9, 2), decision_status="confirmed")
        self.client.force_login(clerk)
        page = self.client.get(reverse("appeals:sales_tax_list") + "?mpr=2026-10")
        self.assertEqual([x.pk for x in page.context["appeals"]], [a.pk])

        from .forms import SalesTaxAppealForm
        data = {f: v for f, v in SalesTaxAppealForm(instance=a).initial.items() if v is not None}
        data.update({"oia_date": "2026-10-30", "mpr_month": "2026-09"})
        form = SalesTaxAppealForm(data, instance=a)
        self.assertFalse(form.is_valid())
        self.assertIn("mpr_month", form.errors)
        data.update({"oia_date": "", "mpr_month": "2026-11"})
        form = SalesTaxAppealForm(data, instance=a)
        self.assertFalse(form.is_valid())
        self.assertIn("mpr_month", form.errors)

    def test_migration_backfills_existing_decisions(self):
        a = self.make(oia_date=date(2026, 8, 20), decision_status="confirmed")
        SalesTaxAppeal.objects.filter(pk=a.pk).update(mpr_month=None)
        migration = import_module("appeals.migrations.0009_mpr_month")
        migration.fill_from_decision_date(global_apps, None)
        a.refresh_from_db()
        self.assertEqual(a.mpr_month, date(2026, 8, 1))
