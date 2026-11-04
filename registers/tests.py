from datetime import date, time

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from appeals.models import IncomeTaxAppeal, SalesTaxAppeal
from appeals.views import _mpr_stay_figures
from core.models import Holiday, HolidayYear
from core.workdays import Calendar, stay_dispose_by, stay_fixation_date

from .models import (IncomeTaxCourtDirection, IncomeTaxEarlyHearing,
                     IncomeTaxRectification, IncomeTaxStayApplication,
                     SalesTaxCourtDirection, SalesTaxRectification,
                     SalesTaxStayApplication)


class WorkingDaysTests(TestCase):
    def setUp(self):
        # A fixed calendar for November 2026: Iqbal Day on Monday 9 Nov.
        HolidayYear.objects.create(year=2026)
        Holiday.objects.create(date=date(2026, 11, 9), name="Iqbal Day")

    def test_before_one_pm_is_next_working_day(self):
        self.assertEqual(stay_fixation_date(date(2026, 11, 4), time(10, 0)), date(2026, 11, 5))

    def test_after_one_pm_is_day_after_next(self):
        self.assertEqual(stay_fixation_date(date(2026, 11, 4), time(13, 0)), date(2026, 11, 6))

    def test_friday_afternoon_skips_weekend_and_holiday(self):
        # Fri 6 Nov after 1 PM: next working day Tue 10 (Sat, Sun, Iqbal Day), then Wed 11.
        self.assertEqual(stay_fixation_date(date(2026, 11, 6), time(15, 0)), date(2026, 11, 11))

    def test_received_on_off_day(self):
        # Sunday 8 Nov: treated as handed in Tue 10 morning -> fixed Wed 11.
        self.assertEqual(stay_fixation_date(date(2026, 11, 8)), date(2026, 11, 11))

    def test_seven_working_days_after_fixation(self):
        self.assertEqual(stay_dispose_by(date(2026, 11, 5)), date(2026, 11, 17))

    def test_islamic_holidays_generated_once(self):
        cal = Calendar(date(2027, 3, 10))
        names = list(Holiday.objects.filter(date__year=2027, name__startswith="Eid-ul-Fitr"))
        self.assertEqual(len(names), 3)
        self.assertTrue(all(h.provisional for h in names))
        self.assertFalse(cal.is_working_day(names[0].date))
        # Admin deletes one; it must not come back.
        names[0].delete()
        Calendar(date(2027, 3, 10))
        self.assertEqual(Holiday.objects.filter(date__year=2027, name__startswith="Eid-ul-Fitr").count(), 2)


class StayApplicationTests(TestCase):
    def setUp(self):
        HolidayYear.objects.create(year=2026)
        Holiday.objects.create(date=date(2026, 11, 9), name="Iqbal Day")
        self.st = SalesTaxAppeal.objects.create(
            serial_no=1, date_of_institution=date(2026, 10, 1), appellant_name="ST Appellant",
            sales_tax_involved=5_000_000)
        self.it = IncomeTaxAppeal.objects.create(
            serial_no=1, date_of_institution=date(2026, 10, 1), appellant_name="IT Appellant",
            revenue_involved=2_000_000)
        self.clerk = User.objects.create_user("3310000000003", password="x", role=User.ROLE_DATA_ENTRY)
        self.viewer = User.objects.create_user("3310000000002", password="x", role=User.ROLE_COMMISSIONER)

    def test_fixation_filled_on_save(self):
        s = SalesTaxStayApplication.objects.create(
            appeal=self.st, date_of_receipt=date(2026, 11, 4), time_of_receipt=time(14, 30))
        self.assertEqual(s.date_of_fixation, date(2026, 11, 6))
        self.assertEqual(s.dispose_by, date(2026, 11, 18))

    def test_taxes_stay_separate(self):
        SalesTaxStayApplication.objects.create(appeal=self.st, date_of_receipt=date(2026, 11, 2))
        self.client.force_login(self.clerk)
        st = self.client.get(reverse("registers:stay_register", args=["sales"]))
        it = self.client.get(reverse("registers:stay_register", args=["income"]))
        self.assertEqual(len(st.context["rows"]), 1)
        self.assertEqual(len(it.context["rows"]), 0)

    def test_clerk_adds_viewer_cannot(self):
        url = reverse("registers:stay_create", args=["income", self.it.pk])
        data = {"date_of_receipt": "2026-11-04", "time_of_receipt": "10:00", "decision": "pending"}
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(url, data).status_code, 403)
        self.client.force_login(self.clerk)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(IncomeTaxStayApplication.objects.get().date_of_fixation, date(2026, 11, 5))

    def test_granted_needs_days_and_order_date(self):
        self.client.force_login(self.clerk)
        url = reverse("registers:stay_create", args=["sales", self.st.pk])
        r = self.client.post(url, {"date_of_receipt": "2026-11-04", "decision": "granted"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("days_granted", r.context["form"].errors)
        self.assertIn("date_of_order", r.context["form"].errors)

    def test_mpr_stay_figures(self):
        mk = SalesTaxStayApplication.objects.create
        mk(appeal=self.st, date_of_receipt=date(2026, 9, 25))                       # open all month
        mk(appeal=self.st, date_of_receipt=date(2026, 9, 28), decision="granted",
           days_granted=30, date_of_order=date(2026, 10, 5))                       # opening, decided
        mk(appeal=self.st, date_of_receipt=date(2026, 10, 10))                      # new, pending > 10
        mk(appeal=self.st, date_of_receipt=date(2026, 10, 28))                      # new, pending < 10
        f = _mpr_stay_figures(SalesTaxAppeal, "sales_tax_involved",
                              date(2026, 10, 1), date(2026, 11, 1))
        self.assertEqual(f["opening"]["count"], 2)
        self.assertEqual(f["new"]["count"], 2)
        self.assertEqual(f["decided"]["count"], 1)
        self.assertEqual(f["pending_10"]["count"], 2)
        self.assertEqual(f["closing"]["count"], 3)
        self.assertEqual(str(f["closing"]["revenue"]), "15.000")


class EarlyAndCourtTests(TestCase):
    def setUp(self):
        HolidayYear.objects.create(year=2026)
        self.st = SalesTaxAppeal.objects.create(
            serial_no=7, date_of_institution=date(2026, 9, 1), appellant_name="ST One",
            sales_tax_involved=3_000_000)
        self.it = IncomeTaxAppeal.objects.create(
            serial_no=7, date_of_institution=date(2026, 9, 1), appellant_name="IT One",
            revenue_involved=1_000_000)
        self.clerk = User.objects.create_user("3310000000003", password="x", role=User.ROLE_DATA_ENTRY)
        self.admin = User.objects.create_user("3310000000001", password="x", role=User.ROLE_ADMIN)

    def test_add_early_hearing_and_register_columns(self):
        self.client.force_login(self.clerk)
        url = reverse("registers:entry_create", args=["income", self.it.pk, "early"])
        r = self.client.post(url, {"request_date": "2026-11-02", "made_by": "department"})
        self.assertEqual(r.status_code, 302)
        page = self.client.get(reverse("registers:early_register", args=["income"]))
        row = page.context["rows"][0]["cells"]
        self.assertEqual(row[5], date(2026, 11, 2))
        self.assertEqual(row[6], "Department")
        self.assertEqual([n for _, n in page.context["headings"]][-1], "(10)")
        self.assertEqual(len(self.client.get(
            reverse("registers:early_register", args=["sales"])).context["rows"]), 0)

    def test_court_register_numbering_skips_four(self):
        SalesTaxCourtDirection.objects.create(
            appeal=self.st, date_of_receipt=date(2026, 10, 1), direction="Decide afresh",
            last_date_for_disposal=date(2026, 10, 31))
        self.client.force_login(self.clerk)
        page = self.client.get(reverse("registers:court_register", args=["sales"]))
        self.assertEqual([n for _, n in page.context["headings"]],
                         ["(1)", "(2)", "(3)", "(5)", "(6)", "(7)", "(8)"])
        overdue = self.client.get(reverse("registers:court_register", args=["sales"]) + "?status=overdue")
        self.assertEqual(len(overdue.context["rows"]), 1)

    def test_clerk_cannot_delete_admin_can(self):
        e = IncomeTaxEarlyHearing.objects.create(appeal=self.it, request_date=date(2026, 11, 1),
                                                 made_by="taxpayer")
        url = reverse("registers:entry_delete", args=["income", "early", e.pk])
        self.client.force_login(self.clerk)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(url)
        self.assertFalse(IncomeTaxEarlyHearing.objects.exists())

    def test_court_date_validation(self):
        self.client.force_login(self.clerk)
        url = reverse("registers:entry_create", args=["sales", self.st.pk, "court"])
        r = self.client.post(url, {"court": "high_court", "date_of_receipt": "2026-10-10",
                                   "direction": "x", "last_date_for_disposal": "2026-10-01"})
        self.assertIn("last_date_for_disposal", r.context["form"].errors)

    def test_mpr_court_figures(self):
        from appeals.views import _mpr_court_figures
        mk = IncomeTaxCourtDirection.objects.create
        mk(appeal=self.it, date_of_receipt=date(2026, 9, 10), direction="a")                # opening, open
        mk(appeal=self.it, date_of_receipt=date(2026, 9, 20), direction="b",
           date_of_appellate_order=date(2026, 10, 15))                                     # opening, decided
        mk(appeal=self.it, date_of_receipt=date(2026, 10, 5), direction="c")                # new
        f = _mpr_court_figures(IncomeTaxAppeal, "revenue_involved", date(2026, 10, 1), date(2026, 11, 1))
        self.assertEqual([f[k]["count"] for k in ("opening", "new", "decided", "closing")], [2, 1, 1, 2])


class RectificationTests(TestCase):
    def setUp(self):
        HolidayYear.objects.create(year=2026)
        self.st = SalesTaxAppeal.objects.create(
            serial_no=3, date_of_institution=date(2026, 8, 1), appellant_name="ST Rect",
            sales_tax_involved=4_000_000)
        self.it = IncomeTaxAppeal.objects.create(
            serial_no=3, date_of_institution=date(2026, 8, 1), appellant_name="IT Rect",
            revenue_involved=1_500_000)
        self.clerk = User.objects.create_user("3310000000003", password="x", role=User.ROLE_DATA_ENTRY)
        self.viewer = User.objects.create_user("3310000000002", password="x", role=User.ROLE_COMMISSIONER)

    def test_add_and_register(self):
        url = reverse("registers:entry_create", args=["sales", self.st.pk, "rect"])
        data = {"application_date": "2026-11-02", "application_no": "R-12/2026",
                "request_by": "suo_moto", "fixation_date": "2026-11-10", "decision": "pending"}
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(url, data).status_code, 403)
        self.client.force_login(self.clerk)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        page = self.client.get(reverse("registers:rect_register", args=["sales"]))
        cells = page.context["rows"][0]["cells"]
        self.assertEqual(cells[5], "R-12/2026")
        self.assertEqual(cells[7], "Suo moto")
        self.assertEqual(cells[9], "Pending")
        self.assertEqual(page.context["rule"], "(See Section 57)")
        self.assertEqual(len(self.client.get(
            reverse("registers:rect_register", args=["income"])).context["rows"]), 0)

    def test_decision_filters_and_validation(self):
        mk = IncomeTaxRectification.objects.create
        mk(appeal=self.it, application_date=date(2026, 10, 1), request_by="taxpayer",
           decision="partly_accepted", decision_date=date(2026, 10, 20))
        mk(appeal=self.it, application_date=date(2026, 10, 5), request_by="department")
        self.client.force_login(self.clerk)
        base = reverse("registers:rect_register", args=["income"])
        self.assertEqual(len(self.client.get(base + "?status=pending").context["rows"]), 1)
        self.assertEqual(len(self.client.get(base + "?status=decided").context["rows"]), 1)
        self.assertEqual(len(self.client.get(base + "?status=partly_accepted").context["rows"]), 1)
        self.assertEqual(len(self.client.get(base + "?by=department").context["rows"]), 1)
        r = self.client.post(reverse("registers:entry_create", args=["income", self.it.pk, "rect"]),
                             {"application_date": "2026-11-02", "request_by": "taxpayer",
                              "decision": "pending", "decision_date": "2026-11-05"})
        self.assertIn("decision", r.context["form"].errors)
