"""Import the office's historic registers from the exported Excel files.

    python manage.py import_legacy --dry-run     # report only, writes nothing
    python manage.py import_legacy               # import for real
    python manage.py import_legacy --register sales
    python manage.py import_legacy --undo        # remove everything it imported

Records are matched on (serial_no, year), so re-running updates rather than
duplicates. Every imported row is stamped created_by_name = "Legacy import"
so it can be told apart from records typed in by a clerk.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import openpyxl
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from appeals.models import IncomeTaxAppeal, SalesTaxAppeal, Unit, Zone

IMPORT_STAMP = "Legacy import"

#: Rows that could not be imported are written here for manual entry.
RESIDUAL_FILE = "residual.xlsx"

FILES = {
    "sales": ("SalesTax.xlsx", "Table1"),
    "income": ("IncomeTax.xlsx", "New Pendency (3)"),
}

# The office writes the zone name loosely; normalise to the six real zones.
ZONE_ALIASES = {
    "corporate zone": "Corporate Zone",
    "lyallpur zone": "Lyallpur Zone",
    "chenab zone": "Chenab Zone",
    "jhang zone": "Jhang Zone",
    "withholding zone": "Withholding Zone",
    "wihholding zone": "Withholding Zone",
    "refund zone": "Refund Zone",
}

DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d/%m/%Y",
    "%d-%m-%Y",
)

UNIT_RE = re.compile(r"unit[\s\-]*0*(\d{1,2})", re.I)
RANGE_RE = re.compile(r"range[\s\-]*(III|II|I|3|2|1)\b", re.I)
RANGE_MAP = {"1": "I", "2": "II", "3": "III", "I": "I", "II": "II", "III": "III"}

# 1/ST/CIR(A-II)/FSD/25 and its many typed variants: (A-ll), CIR/(A-II), 26a ...
APPEAL_NO_RE = re.compile(
    r"^\s*(\d+)\s*([A-Za-z])?\s*[/(]\s*ST\s*[/(]?\s*CIR\s*/?\s*\(*\s*A+\s*[-–]\s*"
    r"(?:II|ll|11|I{1,3})\s*\)\s*/\s*FSD\s*/\s*(\d{2,4})\s*([A-Za-z])?",
    re.I,
)

#: 6522/1 and 6726-A are separate appeals that share a base number.
INCOME_NO_RE = re.compile(r"^\s*(\d+)\s*([/-]\s*[A-Za-z0-9]{1,3})?\s*$")


def text(v):
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in {"none", "nan", "-", "n/a"} else s


def parse_date(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = text(v)
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(v):
    s = text(v).replace(",", "").replace("Rs.", "").replace("Rs", "").strip()
    if not s:
        return Decimal("0")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def parse_year(raw, fallback):
    """Two-digit years in the file mean 20xx."""
    if raw is None:
        return fallback
    y = int(raw)
    if y < 100:
        y += 2000
    return y


class Command(BaseCommand):
    help = "Import the historic Sales Tax and Income Tax registers from Excel."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would happen; write nothing.")
        parser.add_argument("--register", choices=["sales", "income", "both"],
                            default="both")
        parser.add_argument("--undo", action="store_true",
                            help="Delete every record previously imported.")
        parser.add_argument("--limit", type=int, default=0,
                            help="Only process the first N rows (for testing).")

    # -- helpers ------------------------------------------------------------
    def load_sheet(self, filename, sheet):
        path = settings.MEDIA_ROOT / filename
        if not path.exists():
            self.stderr.write(f"Missing file: {path}")
            return []
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        ws = wb[sheet]
        rows = ws.iter_rows(values_only=True)
        header = [text(h) or f"col{i}" for i, h in enumerate(next(rows), 1)]
        self.headers[filename] = header
        out = [dict(zip(header, r)) for r in rows
               if any(v not in (None, "") for v in r)]
        wb.close()
        return out

    def resolve_zone(self, raw):
        name = text(raw).rstrip(",.").strip()
        if not name:
            return None, None
        canonical = ZONE_ALIASES.get(name.lower())
        if not canonical:
            return None, name          # unknown - reported, not guessed
        return self.zones.get(canonical), None

    def resolve_unit(self, zone, officer_text):
        """Units live inside the officer's designation, e.g. 'Unit-03, Lyallpur Zone'."""
        if not zone:
            return None
        blob = text(officer_text)
        if not blob:
            return None
        m = RANGE_RE.search(blob)
        if m:
            name = f"Range-{RANGE_MAP.get(m.group(1).upper(), m.group(1).upper())}"
            return self.units.get((zone.pk, name))
        m = UNIT_RE.search(blob)
        if m:
            return self.units.get((zone.pk, f"Unit-{int(m.group(1)):02d}"))
        return None

    # -- main ---------------------------------------------------------------
    def handle(self, *args, **opts):
        self.dry = opts["dry_run"]
        self.limit = opts["limit"]

        self.headers = {}
        self.residual = {"sales": [], "income": []}

        if opts["undo"]:
            return self.undo()

        self.zones = {z.name: z for z in Zone.objects.all()}
        self.units = {(u.zone_id, u.name): u for u in Unit.objects.all()}

        which = opts["register"]
        if which in ("sales", "both"):
            self.import_sales()
        if which in ("income", "both"):
            self.import_income()

        self.write_residual()

        if self.dry:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN - no records were imported. "
                "residual.xlsx was still written."))

    def undo(self):
        s = SalesTaxAppeal.objects.filter(created_by_name=IMPORT_STAMP)
        i = IncomeTaxAppeal.objects.filter(created_by_name=IMPORT_STAMP)
        n_s, n_i = s.count(), i.count()
        if self.dry:
            self.stdout.write(f"Would delete {n_s} sales tax and {n_i} income tax records.")
            return
        s.delete()
        i.delete()
        self.stdout.write(self.style.SUCCESS(
            f"Deleted {n_s} sales tax and {n_i} income tax imported records."))

    # -- Sales Tax ----------------------------------------------------------
    def import_sales(self):
        rows = self.load_sheet(*FILES["sales"])
        if self.limit:
            rows = rows[: self.limit]
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nSALES TAX  ({len(rows)} rows)"))

        created = updated = 0
        skipped, bad_zone, no_unit, bad_number = [], set(), 0, []
        seen, clashes = {}, []

        for n, r in enumerate(rows, start=2):
            raw_id = text(r.get("ID"))
            instituted = parse_date(r.get("DATE OF INSTI"))
            name = text(r.get("NAME OF APPEALENT"))

            if not instituted or not name:
                reason = "Missing date of institution or appellant name"
                skipped.append((n, raw_id, "missing institution date or appellant"))
                self.residual["sales"].append((n, reason, r))
                continue

            m = APPEAL_NO_RE.match(raw_id)
            if m:
                serial = int(m.group(1))
                suffix = (m.group(2) or m.group(4) or "").strip()
                year = parse_year(m.group(3), instituted.year)
            else:
                lead = re.match(r"^\s*(\d+)\s*([A-Za-z])?", raw_id)
                if not lead:
                    skipped.append((n, raw_id, "no serial number in ID"))
                    self.residual["sales"].append(
                        (n, "No serial number could be read from the ID", r))
                    continue
                serial = int(lead.group(1))
                suffix = (lead.group(2) or "").strip()
                year = instituted.year
                bad_number.append((n, raw_id, f"{serial}{suffix}/.../{year}"))

            zone, unknown = self.resolve_zone(r.get("ZONE"))
            if unknown:
                bad_zone.add(unknown)
            unit = self.resolve_unit(zone, r.get("PASSED BY"))
            if zone and not unit:
                no_unit += 1

            addr = " ".join(x for x in [text(r.get("ADDRESS OF APPEALENT 1")),
                                        text(r.get("ADDRESS OF APPEALENT 2"))] if x)
            ar_addr = " ".join(x for x in [text(r.get("ADDRESS OF AR 1")),
                                           text(r.get("ADDRESS OF AR 2"))] if x)

            values = dict(
                year=year,
                serial_suffix=suffix,
                date_of_institution=instituted,
                ntn=text(r.get("NTN"))[:15],
                strn=text(r.get("STRN"))[:20],
                appellant_name=name[:255],
                address=addr,
                city=text(r.get("CITY"))[:100],
                contact_no=text(r.get("CONTACT NO"))[:30],
                tax_year=text(r.get("TAX YEAR"))[:10],
                tax_period=text(r.get("TAX PERIOD"))[:50],
                sales_tax_involved=parse_amount(r.get("TAXED AMOUNT")),
                zone=zone, unit=unit,
                passing_officer_name=text(r.get("PASSED BY"))[:150],
                oio_no=text(r.get("OIO NO"))[:100],
                oio_date=parse_date(r.get("OIO DATE")),
                date_of_service=parse_date(r.get("DATE OF SERVICE")),
                ar_name=text(r.get("NAME OF AR"))[:150],
                ar_type=text(r.get("STATUS")).rstrip(",")[:50],
                ar_registration_no=text(r.get("REG NO OF AR"))[:50],
                ar_contact_no=text(r.get("CONTACT OF AR"))[:60],
                ar_address=ar_addr[:255],
                ar_city=text(r.get("CITY OF AR"))[:100],
                decision_status=SalesTaxAppeal.Decision.PENDING,
                created_by_name=IMPORT_STAMP,
                updated_by_name=IMPORT_STAMP,
            )

            key = (serial, suffix, year)
            if key in seen:
                first_row, first_name = seen[key]
                clashes.append((n, raw_id, name, first_row, first_name))
                self.residual["sales"].append((
                    n,
                    f"Appeal No. {serial}{suffix}/{year} already used by Excel row "
                    f"{first_row} ({first_name})",
                    r,
                ))
                continue
            seen[key] = (n, name)

            if self.dry:
                exists = SalesTaxAppeal.objects.filter(
                    serial_no=serial, serial_suffix=suffix, year=year).exists()
                updated += 1 if exists else 0
                created += 0 if exists else 1
                continue

            with transaction.atomic():
                obj, was_created = SalesTaxAppeal.objects.update_or_create(
                    serial_no=serial, serial_suffix=suffix, year=year, defaults=values)
            created += 1 if was_created else 0
            updated += 0 if was_created else 1

        self.report("Sales Tax", created, updated, skipped, bad_zone, no_unit,
                    bad_number, clashes)

    # -- Income Tax ---------------------------------------------------------
    def import_income(self):
        rows = self.load_sheet(*FILES["income"])
        if self.limit:
            rows = rows[: self.limit]
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nINCOME TAX  ({len(rows)} rows)"))

        created = updated = 0
        skipped, bad_zone, no_unit, bad_number = [], set(), 0, []
        seen, clashes = {}, []

        for n, r in enumerate(rows, start=2):
            raw_no = text(r.get("A.No."))
            instituted = parse_date(r.get("Date Of Institution"))
            name = text(r.get("Name of Appellant"))

            if not instituted or not name:
                reason = "Missing date of institution or appellant name"
                skipped.append((n, raw_no, "missing institution date or appellant"))
                self.residual["income"].append((n, reason, r))
                continue

            m = INCOME_NO_RE.match(raw_no)
            if m:
                serial = int(m.group(1))
                suffix = (m.group(2) or "").replace(" ", "")
            else:
                lead = re.match(r"^\s*(\d+)", raw_no)
                if not lead:
                    skipped.append((n, raw_no, "no serial number in A.No."))
                    self.residual["income"].append(
                        (n, "No serial number could be read from the A.No.", r))
                    continue
                serial, suffix = int(lead.group(1)), ""
                bad_number.append((n, raw_no, str(serial)))
            if suffix:
                bad_number.append((n, raw_no, f"{serial} + suffix {suffix!r}"))
            year = instituted.year

            zone, unknown = self.resolve_zone(r.get("Zone"))
            if unknown:
                bad_zone.add(unknown)
            unit = self.resolve_unit(zone, r.get("Name of Officers"))
            if zone and not unit:
                no_unit += 1

            # One column holds either an NTN or a CNIC. 13 digits means CNIC.
            ident = text(r.get("NTN/CNIC"))
            digits = re.sub(r"\D", "", ident)
            is_cnic = len(digits) == 13

            values = dict(
                year=year,
                serial_suffix=suffix,
                date_of_institution=instituted,
                ntn="" if is_cnic else ident[:15],
                cnic=ident[:15] if is_cnic else "",
                appellant_name=name[:255],
                address_line_1=text(r.get("Address"))[:255],
                tax_year=text(r.get("Tax Year"))[:10],
                order_section=text(r.get("U/S"))[:50],
                zone=zone, unit=unit,
                income_assessed=parse_amount(r.get("Income Assessed")),
                revenue_involved=parse_amount(r.get("Revenue Involved")),
                officer_name=text(r.get("Name of Officers"))[:150],
                date_of_assessment=parse_date(r.get("Date of Order ACIR/DCIR/IRO")),
                ar_name=text(r.get("Advocate"))[:150],
                appellate_order_date=parse_date(r.get("Date of appellate Order")),
                decision_status=IncomeTaxAppeal.Decision.PENDING,
                created_by_name=IMPORT_STAMP,
                updated_by_name=IMPORT_STAMP,
            )

            key = (serial, suffix, year)
            if key in seen:
                first_row, first_name = seen[key]
                clashes.append((n, raw_no, name, first_row, first_name))
                self.residual["income"].append((
                    n,
                    f"A.No. {serial}{suffix}/{year} already used by Excel row "
                    f"{first_row} ({first_name})",
                    r,
                ))
                continue
            seen[key] = (n, name)

            if self.dry:
                exists = IncomeTaxAppeal.objects.filter(
                    serial_no=serial, serial_suffix=suffix, year=year).exists()
                updated += 1 if exists else 0
                created += 0 if exists else 1
                continue

            with transaction.atomic():
                obj, was_created = IncomeTaxAppeal.objects.update_or_create(
                    serial_no=serial, serial_suffix=suffix, year=year, defaults=values)
            created += 1 if was_created else 0
            updated += 0 if was_created else 1

        self.report("Income Tax", created, updated, skipped, bad_zone, no_unit,
                    bad_number, clashes)

    # -- residual workbook --------------------------------------------------
    def write_residual(self):
        """Write every rejected row, with its reason, for manual entry."""
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        total = sum(len(v) for v in self.residual.values())
        path = settings.MEDIA_ROOT / RESIDUAL_FILE

        wb = Workbook()
        wb.remove(wb.active)

        head_fill = PatternFill("solid", fgColor="B3261E")
        head_font = Font(bold=True, color="FFFFFF", size=10)
        thin = Side(style="thin", color="BBBBBB")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        for key, label, filename in (
            ("sales", "Sales Tax", FILES["sales"][0]),
            ("income", "Income Tax", FILES["income"][0]),
        ):
            entries = self.residual.get(key) or []
            ws = wb.create_sheet(f"{label} ({len(entries)})")
            source_cols = self.headers.get(filename, [])
            columns = ["Excel Row", "Why it was not imported"] + source_cols

            ws.merge_cells(start_row=1, start_column=1,
                           end_row=1, end_column=max(len(columns), 3))
            title = ws.cell(row=1, column=1)
            title.value = (
                f"{settings.OFFICE_NAME} - {label} rows NOT imported from {filename}"
            )
            title.font = Font(bold=True, size=12, color="B3261E")
            title.alignment = Alignment(horizontal="center")

            ws.merge_cells(start_row=2, start_column=1,
                           end_row=2, end_column=max(len(columns), 3))
            sub_ = ws.cell(row=2, column=1)
            sub_.value = (
                f"Generated {timezone.localtime():%d-%m-%Y %H:%M} - {len(entries)} row(s). "
                "Check each against the file, then enter it in the system by hand."
            )
            sub_.font = Font(size=9, italic=True, color="666666")
            sub_.alignment = Alignment(horizontal="center")

            for c, heading in enumerate(columns, start=1):
                cell = ws.cell(row=3, column=c, value=heading)
                cell.fill = head_fill
                cell.font = head_font
                cell.border = border
                cell.alignment = Alignment(horizontal="center", vertical="center",
                                           wrap_text=True)
            ws.row_dimensions[3].height = 30

            for i, (row_no, reason, raw) in enumerate(entries, start=4):
                ws.cell(row=i, column=1, value=row_no).border = border
                rc = ws.cell(row=i, column=2, value=reason)
                rc.border = border
                rc.alignment = Alignment(wrap_text=True, vertical="top")
                rc.font = Font(color="B3261E")
                for c, col in enumerate(source_cols, start=3):
                    v = raw.get(col)
                    cell = ws.cell(row=i, column=c,
                                   value=v if isinstance(v, (int, float)) else text(v))
                    cell.border = border
                    cell.alignment = Alignment(vertical="top")

            widths = [10, 46] + [18] * len(source_cols)
            for c, w in enumerate(widths, start=1):
                ws.column_dimensions[get_column_letter(c)].width = w
            ws.freeze_panes = "C4"

            if not entries:
                ws.cell(row=4, column=2, value="Nothing was rejected from this register.")

        wb.save(path)
        self.stdout.write(self.style.SUCCESS(
            f"\nResidual workbook written: {path}  ({total} row(s) not imported)"))

    # -- reporting ----------------------------------------------------------
    def report(self, label, created, updated, skipped, bad_zone, no_unit,
               bad_number, clashes=()):
        verb = "would be created" if self.dry else "created"
        self.stdout.write(f"  {verb:18} {created}")
        self.stdout.write(f"  {'updated' if not self.dry else 'would be updated':18} {updated}")
        self.stdout.write(f"  {'skipped':18} {len(skipped)}")

        if bad_number:
            self.stdout.write(self.style.WARNING(
                f"  appeal numbers repaired: {len(bad_number)} (first 5 shown)"))
            for n, raw, fixed in bad_number[:5]:
                self.stdout.write(f"      row {n}: {raw!r} -> {fixed}")

        if no_unit:
            self.stdout.write(self.style.WARNING(
                f"  no unit identified from the officer text: {no_unit} rows"))

        if bad_zone:
            self.stdout.write(self.style.ERROR(
                f"  ZONE NOT RECOGNISED (left blank): {sorted(bad_zone)}"))

        if clashes:
            self.stdout.write(self.style.ERROR(
                f"  DUPLICATE numbers - NOT imported, need your review: {len(clashes)}"))
            for n, raw, nm, first_row, first_nm in clashes:
                self.stdout.write(f"      row {n}: {raw!r}  {nm[:34]!r}")
                self.stdout.write(f"          number already used by row {first_row}: {first_nm[:34]!r}")

        if skipped:
            self.stdout.write(self.style.ERROR("  skipped rows:"))
            for n, raw, why in skipped[:10]:
                self.stdout.write(f"      row {n}: {raw!r} - {why}")
