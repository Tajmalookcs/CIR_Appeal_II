"""Working days for the office: weekly off days, national holidays and the
Islamic holidays of the Hijri (lunar) calendar.

Used for the stay application deadlines in Sales Tax Rule 150ZZ and Income
Tax Rule 76G:

  * received before 01:00 PM on a working day -> hearing fixed on the next
    working day; received after 01:00 PM -> the day after the next working day;
  * disposed of within seven working days of fixation.

Islamic holidays are worked out with the Umm al-Qura calendar (hijridate) and
shifted by settings.HIJRI_OFFSET_DAYS, because Pakistan usually sights the moon
a day later than Saudi Arabia. They are saved as *provisional*: Admin moves a
date on the Holidays page when Ruet-e-Hilal announces otherwise. A year's
holidays are generated the first time that year is needed, and only once, so
Admin's corrections and deletions are never overwritten.
"""

from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction

#: Monday is 0. Saturday and Sunday are the weekly off days.
WEEKEND = set(getattr(settings, "OFFICE_WEEKEND", (5, 6)))

#: Days added to the Umm al-Qura date to reach Pakistan's moon-sighted date.
HIJRI_OFFSET_DAYS = getattr(settings, "HIJRI_OFFSET_DAYS", 1)

#: Applications received at or after this time count as "after 01:00 PM".
CUTOFF = time(13, 0)

#: Gazetted national holidays on fixed Gregorian dates: (month, day, name).
NATIONAL_HOLIDAYS = [
    (2, 5, "Kashmir Solidarity Day"),
    (3, 23, "Pakistan Day"),
    (5, 1, "Labour Day"),
    (5, 28, "Youm-e-Takbeer"),
    (8, 14, "Independence Day"),
    (11, 9, "Iqbal Day"),
    (12, 25, "Quaid-e-Azam Day"),
]

#: Islamic holidays: (Hijri month, first day, number of days, name).
ISLAMIC_HOLIDAYS = [
    (10, 1, 3, "Eid-ul-Fitr"),
    (12, 10, 3, "Eid-ul-Azha"),
    (1, 9, 2, "Ashura (9th & 10th Muharram)"),
    (3, 12, 1, "Eid Milad-un-Nabi"),
]


def islamic_dates(year):
    """[(date, name)] of the Islamic holidays falling in a Gregorian year."""
    from hijridate import Gregorian, Hijri

    out = []
    first = Gregorian(year, 1, 1).to_hijri().year
    last = Gregorian(year, 12, 31).to_hijri().year
    for hyear in range(first, last + 1):
        for hmonth, hday, days, name in ISLAMIC_HOLIDAYS:
            try:
                start = Hijri(hyear, hmonth, hday).to_gregorian().datetuple()
            except (ValueError, OverflowError):
                continue
            start = date(*start) + timedelta(days=HIJRI_OFFSET_DAYS)
            for i in range(days):
                d = start + timedelta(days=i)
                if d.year == year:
                    label = name if days == 1 else f"{name} (day {i + 1})"
                    out.append((d, label))
    return out


def ensure_year(year):
    """Generate a year's holidays the first time it is needed."""
    from .models import Holiday, HolidayYear

    if HolidayYear.objects.filter(year=year).exists():
        return
    try:
        with transaction.atomic():
            HolidayYear.objects.create(year=year)
            for month, day, name in NATIONAL_HOLIDAYS:
                Holiday.objects.get_or_create(
                    date=date(year, month, day),
                    defaults={"name": name, "kind": Holiday.Kind.NATIONAL},
                )
            for d, name in islamic_dates(year):
                holiday, created = Holiday.objects.get_or_create(
                    date=d,
                    defaults={"name": name, "kind": Holiday.Kind.ISLAMIC,
                              "provisional": True},
                )
                if not created and name not in holiday.name:
                    # Falls on a national holiday: keep both names.
                    holiday.name = f"{holiday.name} / {name}"[:100]
                    holiday.save(update_fields=["name"])
    except IntegrityError:
        # Another request generated the same year at the same moment.
        pass


def holiday_dates(start, end):
    """Set of holiday dates between start and end inclusive."""
    from .models import Holiday

    for y in range(start.year, end.year + 1):
        ensure_year(y)
    return set(Holiday.objects.filter(date__gte=start, date__lte=end)
               .values_list("date", flat=True))


class Calendar:
    """Answers working-day questions for a span, with one database read."""

    def __init__(self, around, span_days=120):
        self.start = around - timedelta(days=span_days)
        self.end = around + timedelta(days=span_days)
        self.holidays = holiday_dates(self.start, self.end)

    def is_working_day(self, d):
        if not (self.start <= d <= self.end):
            # Outside the loaded span - load around this date instead.
            self.__init__(d)
        return d.weekday() not in WEEKEND and d not in self.holidays

    def next_working_day(self, d):
        """The first working day strictly after d."""
        d += timedelta(days=1)
        while not self.is_working_day(d):
            d += timedelta(days=1)
        return d

    def add_working_days(self, d, n):
        """The n-th working day after d."""
        for _ in range(n):
            d = self.next_working_day(d)
        return d

    def working_days_between(self, start, end):
        """Working days after start, up to and including end."""
        if end <= start:
            return 0
        count, d = 0, start
        while d < end:
            d += timedelta(days=1)
            if self.is_working_day(d):
                count += 1
        return count


def stay_fixation_date(received_on, received_at=None, calendar=None):
    """Hearing date for a stay application under Rule 150ZZ / 76G.

    Before 01:00 PM on a working day -> next working day. After 01:00 PM -> the
    day after the next working day. When the time is not recorded it is
    treated as before 01:00 PM. An application received on an off day is
    treated as received after hours, i.e. as if handed in the next working
    morning and fixed the working day after that.
    """
    cal = calendar or Calendar(received_on)
    if not cal.is_working_day(received_on):
        return cal.next_working_day(cal.next_working_day(received_on))
    if received_at is not None and received_at >= CUTOFF:
        return cal.add_working_days(received_on, 2)
    return cal.next_working_day(received_on)


#: Stay applications must be disposed of within this many working days of fixation.
STAY_DISPOSAL_WORKING_DAYS = 7


def stay_dispose_by(fixation_date, calendar=None):
    cal = calendar or Calendar(fixation_date)
    return cal.add_working_days(fixation_date, STAY_DISPOSAL_WORKING_DAYS)
