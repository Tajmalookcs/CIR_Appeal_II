"""Seed the Zone and Unit dropdowns.

Zone names are the office's actual zones. Unit names are still provisional
(Unit-01 .. Unit-10) - rename them from Admin > Units once confirmed.
Re-running this command is safe: it only fills gaps, it never renames or
deletes what is already there.
"""

from django.core.management.base import BaseCommand

from appeals.models import Unit, Zone

ZONES = [
    ("Corporate Zone", "CORP"),
    ("Lyallpur Zone", "LYP"),
    ("Chenab Zone", "CHN"),
    ("Jhang Zone", "JHG"),
    ("Withholding Zone", "WHT"),
    ("Refund Zone", "RFD"),
]

UNITS_PER_ZONE = 10

#: Created in every zone in addition to the numbered units.
EXTRA_UNITS = ["Range-I", "Range-II"]

#: District Tax Offices exist only in these zones; the other three have none.
DTO_ZONES = ("Lyallpur Zone", "Chenab Zone", "Jhang Zone")
DTOS_PER_ZONE = 10


class Command(BaseCommand):
    help = "Create the 6 office Zones and their Units (10 numbered + 2 ranges, plus 10 DTOs in the three DTO zones)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--units",
            type=int,
            default=UNITS_PER_ZONE,
            help=f"Units to create per zone (default {UNITS_PER_ZONE}).",
        )

    def handle(self, *args, **options):
        units_per_zone = options["units"]
        zones_made = units_made = 0

        for position, (zone_name, zone_code) in enumerate(ZONES, start=1):
            zone, created = Zone.objects.get_or_create(
                name=zone_name,
                defaults={"code": zone_code, "order": position},
            )
            if created:
                zones_made += 1

            for u in range(1, units_per_zone + 1):
                _, made = Unit.objects.get_or_create(
                    zone=zone,
                    name=f"Unit-{u:02d}",
                    defaults={"code": f"{zone_code}-U{u:02d}", "order": u},
                )
                if made:
                    units_made += 1

            # Ranges sort after the numbered units.
            for offset, range_name in enumerate(EXTRA_UNITS, start=1):
                _, made = Unit.objects.get_or_create(
                    zone=zone,
                    name=range_name,
                    defaults={
                        "code": f"{zone_code}-{range_name.replace('Range-', 'R')}",
                        "order": units_per_zone + offset,
                    },
                )
                if made:
                    units_made += 1

            # District Tax Offices, only in the zones that have them.
            if zone_name in DTO_ZONES:
                for d in range(1, DTOS_PER_ZONE + 1):
                    _, made = Unit.objects.get_or_create(
                        zone=zone,
                        name=f"DTO-{d:02d}",
                        defaults={
                            "code": f"{zone_code}-D{d:02d}",
                            "order": units_per_zone + len(EXTRA_UNITS) + d,
                        },
                    )
                    if made:
                        units_made += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {zones_made} zone(s) and {units_made} unit(s). "
                f"Totals now: {Zone.objects.count()} zones, {Unit.objects.count()} units."
            )
        )
