from datetime import date, time

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from appeals.models import IncomeTaxAppeal, SalesTaxAppeal
from appeals.views import _mpr_stay_figures
from core.models import Holiday, HolidayYear
from core.workdays import Calendar, stay_dispose_by, stay_fixation_date

from .models import IncomeTaxStayApplication, SalesTaxStayApplication


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
