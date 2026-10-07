from datetime import timedelta

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

# Three separate statutory clocks. They are never combined.
#
#   FILING_DAYS  - the appellant must file within 30 days of the order being
#                  served. Late filing is the appellant's default.
#   FIRST_EXPIRY - this office must decide within 120 days of institution.
#   SECOND_EXPIRY- the 120 days may be extended to 180, but only with
#                  special approval.
FILING_DAYS = 30
FIRST_EXPIRY_DAYS = 120
SECOND_EXPIRY_DAYS = 180


# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------
class Zone(models.Model):
    name = models.CharField("Zone Name", max_length=100, unique=True)
    code = models.CharField("Code", max_length=20, blank=True)
    is_active = models.BooleanField("Active", default=True)
    order = models.PositiveSmallIntegerField("Display Order", default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Unit(models.Model):
    zone = models.ForeignKey(
        Zone, on_delete=models.PROTECT, related_name="units", verbose_name="Zone"
    )
    name = models.CharField("Unit Name", max_length=100)
    code = models.CharField("Code", max_length=20, blank=True)
    is_active = models.BooleanField("Active", default=True)
    order = models.PositiveSmallIntegerField("Display Order", default=0)

    class Meta:
        ordering = ["zone__order", "order", "name"]
        unique_together = [("zone", "name")]

    def __str__(self):
        """Unit names repeat across zones, so always qualify them."""
        return f"{self.zone.name} - {self.name}"


# ---------------------------------------------------------------------------
# Shared behaviour
# ---------------------------------------------------------------------------
class ServiceStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DELIVERED = "delivered", "Delivered"
    RETURNED = "returned", "Returned"


class BaseAppeal(models.Model):
    """Fields, expiry maths and stamping shared by both appeal registers.

    Only the serial number is stored. The full Appeal No. is composed for
    display from the serial and the year of institution - see `appeal_no`.
    """

    serial_no = models.PositiveIntegerField("Appeal No.")
    #: Optional suffix written on the file after the number - "a", "-A", "/1".
    #: Two different appeals can share a base number, so it is part of the key.
    serial_suffix = models.CharField("Suffix", max_length=5, blank=True)
    year = models.PositiveSmallIntegerField("Year", editable=False, db_index=True)
    date_of_institution = models.DateField("Date of Institution")

    ntn = models.CharField("NTN", max_length=15, db_index=True, blank=True)
    appellant_name = models.CharField("Name of Appellant", max_length=255, db_index=True)
    contact_no = models.CharField("Contact No.", max_length=30, blank=True)
    city = models.CharField("City", max_length=100, blank=True)
    tax_year = models.CharField("Tax Year", max_length=10, blank=True)

    # Date the order under appeal was served on the appellant. This starts the
    # 30-day filing clock, so it is kept apart from the order date itself.
    date_of_service = models.DateField("Date of Service of Order", null=True, blank=True)

    # --- Authorised Representative (kept separate from the appellant) -------
    ar_name = models.CharField("Name of AR", max_length=150, blank=True)
    ar_type = models.CharField("AR Type", max_length=50, blank=True)
    ar_registration_no = models.CharField("Registration No. of AR", max_length=50, blank=True)
    ar_contact_no = models.CharField("Contact No. of AR", max_length=60, blank=True)
    ar_address = models.CharField("Address of AR", max_length=255, blank=True)
    ar_city = models.CharField("City of AR", max_length=100, blank=True)

    zone = models.ForeignKey(
        Zone, on_delete=models.PROTECT, related_name="%(class)ss",
        verbose_name="Zone", null=True, blank=True,
    )
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, related_name="%(class)ss",
        verbose_name="Unit", null=True, blank=True,
    )

    # calculated, stored so they remain sortable and filterable
    first_expiry_120 = models.DateField(
        "First Expiry (120 Days)", null=True, blank=True, editable=False
    )
    second_expiry_180 = models.DateField(
        "2nd Expiry (180 Days)", null=True, blank=True, editable=False
    )

    courier_no = models.CharField("Courier No.", max_length=100, blank=True)
    courier_date = models.DateField("Courier Date", null=True, blank=True)
    service_status = models.CharField(
        "Service Status", max_length=20, choices=ServiceStatus.choices,
        default=ServiceStatus.PENDING,
    )

    # The foreign keys let us follow the account; the *_by_name snapshots record
    # who actually did the work. An account that is renamed or reassigned to a
    # new person must never reattribute an existing entry.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="%(class)s_created", editable=False,
    )
    created_by_name = models.CharField(
        "Registered By", max_length=200, blank=True, editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="%(class)s_updated", editable=False,
    )
    updated_by_name = models.CharField(
        "Last Updated By", max_length=200, blank=True, editable=False
    )
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        abstract = True
        ordering = ["-year", "-serial_no"]

    def __str__(self):
        return f"{self.appeal_no} - {self.appellant_name}"

    # -- appeal number ------------------------------------------------------
    #: Rendered between the serial and the year, e.g. "/ST/CIR(A-II)/FSD/".
    #: A plain "/" gives the short "12/2026" form.
    NUMBER_INFIX = "/"

    #: 2 renders the year as it is written on the file (e.g. 25), 4 as 2025.
    YEAR_DIGITS = 4

    @property
    def appeal_no(self):
        """Full Appeal No. as written on the file, composed for display."""
        if self.serial_no is None or not self.year:
            return ""
        year = f"{self.year % 100:02d}" if self.YEAR_DIGITS == 2 else str(self.year)
        return f"{self.serial_no}{self.serial_suffix}{self.NUMBER_INFIX}{year}"

    @classmethod
    def next_serial_no(cls, year):
        """The next free serial for a given year."""
        last = (
            cls.objects.filter(year=year)
            .order_by("-serial_no")
            .values_list("serial_no", flat=True)
            .first()
        )
        return (last or 0) + 1

    # -- expiry maths -------------------------------------------------------
    def save(self, *args, **kwargs):
        if self.date_of_institution:
            if not self.year:
                self.year = self.date_of_institution.year
            self.first_expiry_120 = self.date_of_institution + timedelta(days=FIRST_EXPIRY_DAYS)
            self.second_expiry_180 = self.date_of_institution + timedelta(days=SECOND_EXPIRY_DAYS)
        else:
            self.first_expiry_120 = None
            self.second_expiry_180 = None
        super().save(*args, **kwargs)

    @property
    def order_date(self):
        """Date of the order under appeal - overridden per model."""
        raise NotImplementedError

    @property
    def decision_date(self):
        """Date the appeal was decided - overridden per model."""
        raise NotImplementedError

    @property
    def is_decided(self):
        return self.decision_date is not None

    @property
    def reference_date(self):
        """Measure against the decision date once decided, otherwise against today."""
        return self.decision_date or timezone.localdate()

    def _days_against(self, deadline):
        if not deadline:
            return None
        return (deadline - self.reference_date).days

    # -- Rule 1: the appellant's 30-day filing window --------------------------
    @property
    def filing_clock_start(self):
        """Date the 30 days runs from: service of the order, else the order date."""
        return self.date_of_service or self.order_date

    @property
    def days_taken_to_file(self):
        """Days between the order reaching the appellant and the appeal arriving."""
        start = self.filing_clock_start
        if not start or not self.date_of_institution:
            return None
        return (self.date_of_institution - start).days

    @property
    def filing_delay_days(self):
        """Days late. Zero or less means filed within the 30 days allowed."""
        taken = self.days_taken_to_file
        if taken is None:
            return None
        return taken - FILING_DAYS

    @property
    def filing_dates_inconsistent(self):
        """The order appears to post-date the appeal - a source data error."""
        taken = self.days_taken_to_file
        return taken is not None and taken < 0

    @property
    def filing_status(self):
        taken = self.days_taken_to_file
        if taken is None:
            return "-"
        if taken < 0:
            return f"Check dates ({abs(taken)} days before order)"
        late = self.filing_delay_days
        if late <= 0:
            return f"Within Time ({taken} days)"
        return f"Late {late} days"

    @property
    def filed_late(self):
        late = self.filing_delay_days
        return late is not None and late > 0 and not self.filing_dates_inconsistent

    # -- Rule 2: this office must decide within 120 days ----------------------
    @property
    def days_to_first_expiry(self):
        return self._days_against(self.first_expiry_120)

    @property
    def status_120(self):
        days = self.days_to_first_expiry
        if days is None:
            return "-"
        if days >= 0:
            return f"{days} days left"
        return f"Exceeded by {abs(days)} days"

    @property
    def exceeded_120(self):
        days = self.days_to_first_expiry
        return days is not None and days < 0

    # -- Rule 3: extension to 180 days, which needs special approval ----------
    @property
    def days_to_second_expiry(self):
        return self._days_against(self.second_expiry_180)

    @property
    def status_180(self):
        days = self.days_to_second_expiry
        if days is None:
            return "-"
        if days >= 0:
            return f"{days} days left"
        return f"Exceeded by {abs(days)} days"

    @property
    def exceeded_180(self):
        days = self.days_to_second_expiry
        return days is not None and days < 0

    @property
    def needs_special_approval(self):
        """Past 120 days and still undecided - the extension must be approved."""
        return self.exceeded_120 and not self.is_decided

    # -- Row colouring, driven by the office's own deadlines only ------------
    @property
    def expiry_level(self):
        """ok / due_soon / overdue_120 / overdue_180."""
        first = self.days_to_first_expiry
        second = self.days_to_second_expiry
        if second is None:
            return "ok"
        if second < 0:
            return "overdue_180"
        if first is not None and first < 0:
            return "overdue_120"
        if second <= 30:
            return "due_soon"
        return "ok"


# ---------------------------------------------------------------------------
# Sales Tax register
# ---------------------------------------------------------------------------
class SalesTaxAppeal(BaseAppeal):
    class Decision(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        ANNULLED = "annulled", "Annulled"
        MODIFIED = "modified", "Modified"
        REMAND_BACK = "remand_back", "Remand Back"
        OTHERS = "others", "Others"

    strn = models.CharField("STRN", max_length=20, blank=True)
    address = models.TextField("Address", blank=True)
    sales_tax_involved = models.DecimalField(
        "Sales Tax Involved", max_digits=18, decimal_places=2, default=0
    )
    passing_officer_name = models.CharField("Passing Officer Name", max_length=150, blank=True)
    passing_officer_designation = models.CharField(
        "Passing Officer Designation", max_length=60, blank=True,
        help_text="Rank of the officer who passed the order, e.g. IRO, ACIR, DCIR, Addl. CIR. "
                  "Most Sales Tax orders name the post rather than the person, so the name "
                  "above may be empty while this is filled.",
    )

    @property
    def passing_officer(self):
        """Officer who passed the order, as it should read on paper.

        Most Sales Tax orders name only the post, so the name is often empty
        and this falls back to the rank alone rather than printing nothing.
        """
        parts = [p for p in (self.passing_officer_name.strip(),
                             self.passing_officer_designation.strip()) if p]
        return ", ".join(parts)
    tax_period = models.CharField("Tax Period", max_length=50, blank=True)

    oio_no = models.CharField("Order-In-Original No.", max_length=100, blank=True)
    oio_date = models.DateField("Order-In-Original Date", null=True, blank=True)

    issue_involved = models.TextField("Issue Involved", blank=True)
    section = models.CharField("Section", max_length=50, blank=True)

    oia_no = models.CharField("Order-In-Appeal No.", max_length=100, blank=True)
    oia_date = models.DateField("Order-In-Appeal Date", null=True, blank=True)
    decision_status = models.CharField(
        "Status", max_length=20, choices=Decision.choices, default=Decision.PENDING
    )

    #: e.g. 12/ST/CIR(A-II)/FSD/25 - the office writes the year in two digits
    NUMBER_INFIX = "/ST/CIR(A-II)/FSD/"
    YEAR_DIGITS = 2

    class Meta(BaseAppeal.Meta):
        verbose_name = "Sales Tax Appeal"
        verbose_name_plural = "Sales Tax Appeals"
        constraints = [
            models.UniqueConstraint(
                fields=["serial_no", "serial_suffix", "year"],
                name="unique_sales_tax_appeal_no",
            )
        ]

    @property
    def order_date(self):
        """Date of the order under appeal, for the 30-day filing rule."""
        return self.oio_date

    @property
    def decision_date(self):
        return self.oia_date

    def get_absolute_url(self):
        return reverse("appeals:sales_tax_detail", args=[self.pk])


# ---------------------------------------------------------------------------
# Income Tax register
# ---------------------------------------------------------------------------
class IncomeTaxAppeal(BaseAppeal):
    class Decision(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        ANNULLED = "annulled", "Annulled"
        MODIFIED = "modified", "Modified"
        REMAND_BACK = "remand_back", "Remand Back"

    cnic = models.CharField("CNIC", max_length=15, blank=True)
    address_line_1 = models.CharField("Address Line 1", max_length=255, blank=True)
    address_line_2 = models.CharField("Address Line 2", max_length=255, blank=True)

    order_section = models.CharField("Order Section", max_length=50, blank=True)

    income_assessed = models.DecimalField(
        "Income Assessed", max_digits=18, decimal_places=2, default=0
    )
    revenue_involved = models.DecimalField(
        "Revenue Involved", max_digits=18, decimal_places=2, default=0
    )
    date_of_assessment = models.DateField("Date of Assessment", null=True, blank=True)
    officer_name = models.CharField("Name of Officer", max_length=150, blank=True)
    # Held apart from the name so the register can be sorted and filtered by
    # rank. Stored as the office writes it: IRO, ACIR, DCIR, Addl. CIR.
    officer_designation = models.CharField(
        "Designation of Officer", max_length=50, blank=True
    )
    issues_involved = models.TextField("Issues Involved", blank=True)

    appellate_order_date = models.DateField("Date of Appellate Order", null=True, blank=True)
    decision_status = models.CharField(
        "Status", max_length=20, choices=Decision.choices, default=Decision.PENDING
    )

    #: e.g. 6398/2026
    NUMBER_INFIX = "/"
    YEAR_DIGITS = 4

    class Meta(BaseAppeal.Meta):
        verbose_name = "Income Tax Appeal"
        verbose_name_plural = "Income Tax Appeals"
        constraints = [
            models.UniqueConstraint(
                fields=["serial_no", "serial_suffix", "year"],
                name="unique_income_tax_appeal_no",
            )
        ]

    @property
    def order_date(self):
        """Date of the assessment order, for the 30-day filing rule."""
        return self.date_of_assessment

    @property
    def address(self):
        return ", ".join(p for p in [self.address_line_1, self.address_line_2] if p)

    @property
    def decision_date(self):
        return self.appellate_order_date

    def get_absolute_url(self):
        return reverse("appeals:income_tax_detail", args=[self.pk])
