"""Statutory registers kept alongside the appeals.

Sales Tax Rules 2006, Rule 150ZZC (STR-24) and Income Tax Rules 2002,
Rule 76K, require four registers. The Appeals Register is the appeal record
itself; the other three each hold entries made against an appeal. Every entry
points at its appeal, so the appeal's particulars (number, name, STRN/NTN,
tax period/year, zone, revenue, appellate order) are never typed twice.

Sales Tax and Income Tax are kept apart: each register has its own table per
tax, just as the appeals do.
"""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from appeals.models import IncomeTaxAppeal, SalesTaxAppeal


class EntryBase(models.Model):
    """Who entered a register line, and when - snapshotted like the appeals."""

    remarks = models.CharField("Remarks", max_length=255, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", editable=False,
    )
    created_by_name = models.CharField("Entered By", max_length=200, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", editable=False,
    )
    updated_by_name = models.CharField("Last Updated By", max_length=200, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Stay applications - Rule 150ZZ (Sales Tax) / Rule 76G (Income Tax)
# ---------------------------------------------------------------------------
class StayApplicationBase(EntryBase):
    """One application for stay, made in an appeal.

    The rule: fixed for hearing on the next working day (or the day after, if
    received after 01:00 PM) and disposed of within seven working days of
    fixation. The suggested dates are worked out in core.workdays.
    """

    class Decision(models.TextChoices):
        PENDING = "pending", "Pending"
        GRANTED = "granted", "Stay granted"
        NOT_GRANTED = "not_granted", "Stay not granted"

    #: An application still undecided after this many days counts as
    #: "pending for more than 10 days" on the MPR.
    MPR_PENDING_DAYS = 10

    date_of_receipt = models.DateField("Date of Receipt")
    time_of_receipt = models.TimeField(
        "Time of Receipt", null=True, blank=True,
        help_text="Decides the hearing date: before 01:00 PM -> next working day; "
                  "after 01:00 PM -> the working day after that.",
    )
    date_of_fixation = models.DateField(
        "Date of Fixation", null=True, blank=True,
        help_text="Hearing date. Left blank, it is worked out from the receipt date and time.",
    )
    decision = models.CharField(
        "Decision", max_length=20, choices=Decision.choices, default=Decision.PENDING,
    )
    days_granted = models.PositiveSmallIntegerField(
        "Stay Granted For (days)", null=True, blank=True,
    )
    date_of_order = models.DateField(
        "Date of Order (Disposal)", null=True, blank=True,
    )

    class Meta:
        abstract = True
        ordering = ["date_of_receipt", "pk"]

    def __str__(self):
        return f"Stay application {self.date_of_receipt:%d-%m-%Y} in {self.appeal.appeal_no}"

    # -- deadlines --------------------------------------------------------
    @property
    def is_disposed(self):
        return self.date_of_order is not None

    @property
    def suggested_fixation(self):
        from core.workdays import stay_fixation_date
        return stay_fixation_date(self.date_of_receipt, self.time_of_receipt)

    @property
    def dispose_by(self):
        """Last day to dispose of it: seven working days after fixation."""
        from core.workdays import stay_dispose_by
        fixed = self.date_of_fixation or self.suggested_fixation
        return stay_dispose_by(fixed) if fixed else None

    @property
    def is_overdue(self):
        due = self.dispose_by
        if self.is_disposed:
            return bool(due and self.date_of_order > due)
        return bool(due and timezone.localdate() > due)

    @property
    def days_late(self):
        due = self.dispose_by
        if not due:
            return 0
        end = self.date_of_order or timezone.localdate()
        return max((end - due).days, 0)

    @property
    def outcome(self):
        """Column 9 of the register: stay granted for number of days / not granted."""
        if self.decision == self.Decision.GRANTED:
            if self.days_granted:
                return f"Granted for {self.days_granted} day{'s' if self.days_granted != 1 else ''}"
            return "Granted"
        if self.decision == self.Decision.NOT_GRANTED:
            return "Not granted"
        return ""

    def save(self, *args, **kwargs):
        if self.date_of_receipt and not self.date_of_fixation:
            self.date_of_fixation = self.suggested_fixation
        if self.decision != self.Decision.GRANTED:
            self.days_granted = None
        super().save(*args, **kwargs)

    # -- MPR -----------------------------------------------------------------
    @classmethod
    def open_on(cls, qs, day):
        """Received before `day` and not disposed of before it."""
        return qs.filter(date_of_receipt__lt=day).filter(
            models.Q(date_of_order__isnull=True) | models.Q(date_of_order__gte=day)
        )

    @classmethod
    def pending_over(cls, qs, as_of, days=None):
        """Still undisposed at the end of `as_of`, received more than `days` ago."""
        days = cls.MPR_PENDING_DAYS if days is None else days
        nxt = as_of + timedelta(days=1)
        return cls.open_on(qs, nxt).filter(date_of_receipt__lt=as_of - timedelta(days=days))


class SalesTaxStayApplication(StayApplicationBase):
    appeal = models.ForeignKey(
        SalesTaxAppeal, on_delete=models.CASCADE, related_name="stay_applications",
        verbose_name="Appeal",
    )

    class Meta(StayApplicationBase.Meta):
        verbose_name = "Sales Tax Stay Application"
        verbose_name_plural = "Sales Tax Stay Applications"


class IncomeTaxStayApplication(StayApplicationBase):
    appeal = models.ForeignKey(
        IncomeTaxAppeal, on_delete=models.CASCADE, related_name="stay_applications",
        verbose_name="Appeal",
    )

    class Meta(StayApplicationBase.Meta):
        verbose_name = "Income Tax Stay Application"
        verbose_name_plural = "Income Tax Stay Applications"
