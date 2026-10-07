"""Create (or clear) sample appeals so the screens can be reviewed with data.

    python manage.py demo_data            # create sample records
    python manage.py demo_data --clear    # remove every record it created

Demo records use serial numbers from 9001 upwards so they can be removed
cleanly without touching real data.
"""

import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from appeals.models import IncomeTaxAppeal, SalesTaxAppeal, Unit, Zone

DEMO_SERIAL_BASE = 9000  # demo records use serials from 9001 up

APPELLANTS = [
    ("Al-Noor Textile Mills (Pvt) Ltd", "1234567-8", "33100-1234567-1"),
    ("Faisal Weaving Industries", "2345678-9", "33100-2345678-2"),
    ("Chenab Traders", "3456789-0", "33100-3456789-3"),
    ("Sitara Processing Mills", "4567890-1", "33100-4567890-4"),
    ("Madina Cotton Ginners", "5678901-2", "33100-5678901-5"),
    ("Crescent Fabrics Co.", "6789012-3", "33100-6789012-6"),
    ("Rehman Enterprises", "7890123-4", "33100-7890123-7"),
    ("Punjab Yarn Traders", "8901234-5", "33100-8901234-8"),
]

ST_ISSUES = [
    "Inadmissible input tax adjustment claimed against suspended suppliers.",
    "Non-payment of sales tax on taxable supplies declared in Annex-C.",
    "Short payment of output tax and default surcharge under section 34.",
    "Disallowance of input tax on account of unverified purchases.",
]

IT_ISSUES = [
    "Addition made under section 111(1)(b) on account of unexplained investment.",
    "Disallowance of expenses claimed under section 21(c).",
    "Non-deduction of withholding tax under section 153.",
    "Assessment framed under section 122(5A) treated as erroneous and prejudicial.",
]


class Command(BaseCommand):
    help = "Create or clear demonstration appeal records."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Delete demo records instead.")
        parser.add_argument("--count", type=int, default=8, help="Records per register.")

    def handle(self, *args, **options):
        if options["clear"]:
            s = SalesTaxAppeal.objects.filter(serial_no__gt=DEMO_SERIAL_BASE).delete()[0]
            i = IncomeTaxAppeal.objects.filter(serial_no__gt=DEMO_SERIAL_BASE).delete()[0]
            self.stdout.write(self.style.SUCCESS(f"Removed {s + i} demo record(s)."))
            return

        zones = list(Zone.objects.filter(is_active=True))
        if not zones:
            self.stderr.write("No zones found - run 'manage.py seed_lookups' first.")
            return

        creator = User.objects.filter(username="admin").first()
        today = timezone.localdate()
        rng = random.Random(20260904)
        count = options["count"]
        made = 0

        # Spread the institution dates so every limitation bucket is represented.
        offsets = [12, 45, 95, 128, 165, 178, 215, 260, 310, 400]

        for n in range(count):
            name, ntn, cnic = APPELLANTS[n % len(APPELLANTS)]
            zone = zones[n % len(zones)]
            unit = zone.units.filter(is_active=True).first()
            instituted = today - timedelta(days=offsets[n % len(offsets)])

            # Decide roughly half of them.
            decided = n % 3 == 0
            oia_date = instituted + timedelta(days=rng.randint(80, 210)) if decided else None
            if oia_date and oia_date > today:
                oia_date = None
            status = (
                rng.choice(["confirmed", "annulled", "modified", "remand_back"])
                if oia_date else "pending"
            )
            service = rng.choice(["delivered", "returned", "pending"]) if oia_date else "pending"

            obj, created = SalesTaxAppeal.objects.get_or_create(
                serial_no=DEMO_SERIAL_BASE + 1 + n,
                year=instituted.year,
                defaults=dict(
                    date_of_institution=instituted,
                    ntn=ntn, strn=f"32{rng.randint(10000000, 99999999)}",
                    appellant_name=name,
                    address=f"Plot {rng.randint(1, 300)}, Industrial Estate, Faisalabad",
                    contact_no=f"041-{rng.randint(2000000, 2999999)}",
                    sales_tax_involved=rng.randint(5, 450) * 100000,
                    zone=zone, unit=unit,
                    passing_officer_name=rng.choice(
                        ["Muhammad Asif, DCIR", "Ayesha Khan, ACIR", "Tariq Mehmood, DCIR"]
                    ),
                    tax_period=f"0{rng.randint(1, 9)}/2024 to 06/2025",
                    oio_no=f"{rng.randint(10, 99)}/{rng.randint(100, 999)}/2025",
                    oio_date=instituted - timedelta(days=rng.randint(20, 60)),
                    ar_name=rng.choice(["Sh. Imran Ali, Advocate", "M. Yousaf, ITP", "Kh. Nadeem, FCA"]),
                    ar_contact_no=f"0300-{rng.randint(1000000, 9999999)}",
                    issue_involved=rng.choice(ST_ISSUES),
                    section=rng.choice(["11(2)", "11(3)", "8(1)(ca)", "36(1)"]),
                    oia_no=f"{rng.randint(200, 400)}/2026" if oia_date else "",
                    oia_date=oia_date,
                    decision_status=status,
                    courier_no=f"TCS{rng.randint(10000000, 99999999)}" if oia_date else "",
                    courier_date=oia_date + timedelta(days=3) if oia_date else None,
                    service_status=service,
                    created_by=creator, updated_by=creator,
                ),
            )
            if created:
                made += 1

            decided_i = n % 2 == 0
            ao_date = instituted + timedelta(days=rng.randint(80, 210)) if decided_i else None
            if ao_date and ao_date > today:
                ao_date = None
            status_i = (
                rng.choice(["confirmed", "annulled", "modified", "remand_back"])
                if ao_date else "pending"
            )

            obj, created = IncomeTaxAppeal.objects.get_or_create(
                serial_no=DEMO_SERIAL_BASE + 1 + n,
                year=instituted.year,
                defaults=dict(
                    date_of_institution=instituted,
                    ntn=ntn, cnic=cnic,
                    appellant_name=name,
                    address_line_1=f"House {rng.randint(1, 500)}, Block {rng.choice('ABCD')}",
                    address_line_2="Peoples Colony No. 1, Faisalabad",
                    contact_no=f"041-{rng.randint(2000000, 2999999)}",
                    tax_year=str(rng.choice([2022, 2023, 2024])),
                    order_section=rng.choice(["122(1)", "122(5A)", "121(1)", "161/205"]),
                    zone=zone, unit=unit,
                    income_assessed=rng.randint(20, 900) * 100000,
                    revenue_involved=rng.randint(3, 220) * 100000,
                    date_of_assessment=instituted - timedelta(days=rng.randint(20, 70)),
                    officer_name=rng.choice(
                        ["Nadeem Akhtar, ACIR", "Sana Riaz, DCIR", "Faisal Iqbal, ACIR"]
                    ),
                    issues_involved=rng.choice(IT_ISSUES),
                    ar_name=rng.choice(["Rana Shahid, Advocate", "A. Rehman, ITP", "S. Bashir, ACA"]),
                    appellate_order_date=ao_date,
                    decision_status=status_i,
                    courier_no=f"TCS{rng.randint(10000000, 99999999)}" if ao_date else "",
                    courier_date=ao_date + timedelta(days=3) if ao_date else None,
                    service_status=rng.choice(["delivered", "returned"]) if ao_date else "pending",
                    created_by=creator, updated_by=creator,
                ),
            )
            if created:
                made += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {made} demo record(s). "
                f"Totals: {SalesTaxAppeal.objects.count()} sales tax, "
                f"{IncomeTaxAppeal.objects.count()} income tax. "
                f"Remove them any time with: manage.py demo_data --clear"
            )
        )
