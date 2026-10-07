# CLAUDE.md — CIR (Appeals-II) Appeals Management System

## Critical Standing Instruction
**ALWAYS ask the user before making any changes.** Confirm the approach first, then implement only after approval.

## Project Overview
- **Office:** Commissioner (Appeals-II), Inland Revenue
- **Address:** Building Regional Tax Office, Faisalabad
- **Framework:** Django 6.0.6 (Python 3.12)
- **Database:** SQLite (`db.sqlite3`)
- **Venv:** `D:\Claude_Projects\CIR_Appeal_II\venv\Scripts\python.exe`
- **Run (normal use):** double-click `Start Appeals System.vbs` - starts the server
  hidden on port 8020 and opens the browser. `Stop Appeals System.vbs` shuts it down.
- **Run (development):** `venv\Scripts\python manage.py runserver 8020`
- **Settings module:** `config.settings`
- **Source spec:** `media/taj.xlsx` (office-supplied column list)
- **Standalone project** — shares nothing with D:\InP_Office_Management.

## Django Apps
| App | Purpose |
|-----|---------|
| `accounts` | Custom User with roles: admin_supervisor, commissioner, data_entry |
| `appeals` | Zone, Unit, SalesTaxAppeal, IncomeTaxAppeal + Excel export |
| `core` | Dashboard, AuditLog |

## Key Models
- **Zone** — 6 zones: Corporate, Lyallpur, Chenab, Jhang, Withholding, Refund.
- **Unit** — FK to Zone, 12 per zone: Unit-01..Unit-10 plus Range-I and Range-II.
  Unique per (zone, name). `__str__` returns `"<Zone> - <Unit>"` because unit names
  repeat across zones; dropdowns rely on that label.
- **BaseAppeal** (abstract) — shared fields + limitation maths.
- **SalesTaxAppeal** — 28 register columns; decision date = `oia_date`.
- **IncomeTaxAppeal** — 26 register columns; decision date = `appellate_order_date`.
- **AuditLog** — create/update/delete/login/logout/login_failed, with field-level from→to diffs.

## Appeal Number
Only `serial_no` (integer) is stored. `year` is auto-set from `date_of_institution`.
`appeal_no` is a **read-only property** composed as `serial + NUMBER_INFIX + year`:
- SalesTaxAppeal.NUMBER_INFIX = `/ST/CIR(A-II)/FSD/` → `12/ST/CIR(A-II)/FSD/2026`
- IncomeTaxAppeal.NUMBER_INFIX = `/`                → `12/2026`

Unique per (serial_no, year) via a DB constraint plus a friendly form check.
The add form pre-fills `Model.next_serial_no(year)`; the clerk may overwrite it.
Register search parses digits out of the query, so `12`, `12/2026` and the full
number all find the record.

## File Cover
`templates/appeals/file_cover.html` reproduces the slip pasted on the physical file
jacket, one layout per register, matching the office's existing printed covers.
Opened from the **File Cover** button on the record page; standalone template, A4
portrait, toolbar hidden when printing. `?print=1` opens the print dialog directly.

## Limitation Rules
**THREE SEPARATE CLOCKS. Never combine them** - this was got wrong once and corrected
by the office.

1. **Filing, 30 days** - the *appellant's* obligation. Measured from
   `date_of_service` (else the order date) to `date_of_institution`.
   `days_taken_to_file`, `filing_delay_days`, `filing_status`, `filed_late`.
   A negative interval means the source data is wrong: `filing_dates_inconsistent`
   flags it rather than printing a nonsensical "Within Time (-138 days)".
2. **Decide by, 120 days** - *this office's* obligation, from institution.
   `first_expiry_120` (stored), `status_120`, `exceeded_120`.
3. **Extension to 180 days** - the 120 may be extended by 60, but only with
   **special approval**. `second_expiry_180` (stored), `status_180`,
   `exceeded_180`, `needs_special_approval`.

`expiry_level` (ok / due_soon / overdue_120 / overdue_180) drives row colouring and
uses only the office's own deadlines, never the filing rule.

## Roles
| Role | View | Add | Edit | Delete | Users | Audit Log |
|---|---|---|---|---|---|---|
| Admin / Supervisor | Y | Y | Y | Y | Y | Y |
| Commissioner IR | Y | - | - | - | - | - |
| Data Entry Operator | Y | Y | Y | - | - | - |

Enforced by `accounts/decorators.py` (403 on denial) and by template checks.

## Launcher Files
- `Start Appeals System.vbs` — double-click launcher. Checks the venv exists, skips
  starting if a server for this folder is already running, launches `run_server.bat`
  with window style 0 (hidden), polls `netstat` until port 8020 listens, then opens
  the browser.
- `Stop Appeals System.vbs` — terminates only the `python.exe` processes whose command
  line contains this project folder **and** `runserver`.
- `run_server.bat` — helper doing the actual run; appends output to `logs\server.log`.
  Not meant to be double-clicked (it would show a console window).
  Binds **0.0.0.0** so other PCs on the LAN can connect. Change to 127.0.0.1 to make
  the system local-only again.
- `Allow LAN Access (Run as Administrator).cmd` — adds the inbound firewall rule for
  TCP 8020 (Domain + Private profiles). Run once, on the host machine only.

The server runs with `--noreload`, so **code changes require a stop and start** of the
launcher before they appear in the browser.

## LAN Access
Host PC address: **10.10.14.230** (Ethernet). Staff browse to `http://10.10.14.230:8020/`.
Nothing is installed on staff PCs - a browser is all they need.

Requirements on the host: server bound to 0.0.0.0, firewall rule added, PC switched on,
and the network profile set to Private or Domain (a Public profile blocks the rule).

Four notes worth remembering:
- `pythonw.exe` cannot be used — it leaves `sys.stdout` unset and Django's runserver
  exits as soon as it prints its banner. Use `python.exe` with a hidden window instead.
- Do not probe readiness with `MSXML2.ServerXMLHTTP` — it honours WinHTTP proxy
  settings, so a proxy can answer for `127.0.0.1` and make a dead server look alive.
- A Windows venv launches two processes (the `venv\Scripts\python.exe` stub plus the
  real interpreter). Both must be terminated to stop the server.
- `PortIsListening` must accept **both** `0.0.0.0:<port>` and `127.0.0.1:<port>` in the
  netstat output, otherwise the launcher times out after switching the bind address.

## Management Commands
- `manage.py seed_lookups` — create the 6 named zones x 10 units (idempotent)
- `manage.py demo_data` / `demo_data --clear` — sample records, serials 9001+
- `manage.py import_legacy [--dry-run] [--register sales|income] [--undo]` —
  imports `media/SalesTax.xlsx` and `media/IncomeTax.xlsx`. Idempotent: matches on
  (serial_no, serial_suffix, year). Stamps `created_by_name = "Legacy import"`.
  Refuses to let one source row overwrite another and reports the clashes instead.

## Office Logo
`static/img/fbr-logo.png` (1080x507, transparent PNG). Resolved at request time by
`core.context_processors.office_info` -> `OFFICE_LOGO`, which checks LOGO_CANDIDATES
and returns None if absent, so templates fall back to a Bootstrap icon crest rather
than a broken image. Dropping a replacement file in needs no restart.

The mark is landscape with dark lettering, so on the green header it sits on a white
plate (`.brand-logo`), not inside the round crest. On the white login card it is shown
plain at 190px (`.login-logo`).

## Theme
FBR-inspired green. Tokens in `static/css/fbr.css`:
`--fbr-green: #00693e`, `--fbr-green-dark: #004d2e`, `--fbr-gold: #c8a951`.
Base template: `templates/base/base.html`.

**No external dependencies.** Bootstrap 5.3.3 and Bootstrap Icons 1.11.3 are vendored
under `static/vendor/` and served by Django, not from a CDN. The system therefore works
on a LAN with no internet access at all - client PCs need only a browser.
Keep `bootstrap-icons.css` in the same folder as its `fonts/` subfolder: the stylesheet
references the font files by relative path.

    static/vendor/bootstrap/bootstrap.min.css
    static/vendor/bootstrap/bootstrap.bundle.min.js
    static/vendor/bootstrap-icons/bootstrap-icons.css
    static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2
    static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff

Never reintroduce a CDN `<link>` or `<script>` into the templates.

## Production Settings
`DEBUG` defaults to **False**. For development: `set CIR_DEBUG=1` before running.

- `SECRET_KEY` is read from `CIR_SECRET_KEY`, else from `secret_key.txt` (auto-created
  on first run, gitignored). Never commit it - changing it signs everyone out.
- `ALLOWED_HOSTS` is an explicit list in settings.py. Add a machine there, or at run
  time via `set CIR_ALLOWED_HOSTS=10.10.14.55,10.10.14.60`. An unlisted host gets 400.
- Static files are served by **WhiteNoise** with `CompressedManifestStaticFilesStorage`.
  Run `manage.py collectstatic` after ANY change to a file under `static/`, or the
  change will not appear. Filenames carry a content hash, so browser cache is no
  longer an issue - no more Ctrl+F5.
- Vendored JS/CSS must not reference `.map` sourcemaps; collectstatic fails on the
  missing file. The `sourceMappingURL` comments have been stripped.
- Custom `templates/404.html` and `templates/500.html`. The 500 page is deliberately
  standalone (no `{% extends %}`) so it still renders if the base template is the fault.
- Errors are written to `logs/errors.log` (rotating, 5 MB x 5) since there is no
  console window to watch.
- SQLite runs in WAL mode with a 20s busy timeout, for concurrent clerks.
- Sessions expire after 8 hours idle.

`manage.py check --deploy` reports only the four HTTPS warnings, which are expected
on a plain-HTTP LAN.

## Attribution and Audit
Names are **snapshotted**, never looked up later:
- `AuditLog.username` / `user_full_name` / `user_designation`, shown via `log.actor`
- `BaseAppeal.created_by_name` / `updated_by_name`, shown on the detail footer

The FK (`user`, `created_by`) still points at the account, but display never uses it.
Renaming an account, handing it to a new person, or deleting it entirely leaves
historic attribution intact - verified by test.

**Office policy:** never hand an account to a new person. Create a new user and set the
old one to inactive.

## Amount Formatting
`{% load humanize %}` + `|floatformat:0|intcomma`.

## Known Pending Items
1. Unit names are still placeholders (Unit-01..Unit-10, Range-I, Range-II). Zone names are final.
2. `SECRET_KEY` and `DEBUG=True` must be changed before any production/network use.
3. LAN deployment pending: intended host is the office data server 10.10.12.99
   (static IP, always on). Needs bind 0.0.0.0, ALLOWED_HOSTS, DEBUG off with static
   files handled, firewall rule, and a backup job to \10.10.12.99\CIR-AII.
   Only ONE machine may run the server - SQLite over SMB corrupts under concurrent writes.
