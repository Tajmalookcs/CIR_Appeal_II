import os

from django.conf import settings

#: Checked in order; the first one that exists is used as the office logo.
LOGO_CANDIDATES = [
    "img/fbr-logo.png",
    "img/fbr-logo.jpg",
    "img/fbr-logo.jpeg",
    "img/fbr-logo.svg",
    "img/logo.png",
]

#: The three crests across the top of an official letter.
CREST_CANDIDATES = {
    "CREST_FBR": ["img/fbr-logo.png", "img/fbr-logo.jpg"],
    "CREST_GOP": ["img/gop-logo.png", "img/gop-logo.jpg"],
    "CREST_IRS": ["img/irs-logo.png", "img/irs-logo.jpg"],
}

#: Optional full-width scan of the office letterhead, used on printed letters.
LETTERHEAD_CANDIDATES = [
    "img/letterhead.png",
    "img/letterhead.jpg",
    "img/letterhead.jpeg",
]


def office_info(request):
    return {
        "OFFICE_NAME": settings.OFFICE_NAME,
        "OFFICE_SUBTITLE": settings.OFFICE_SUBTITLE,
        "OFFICE_SHORT": settings.OFFICE_SHORT,
        "OFFICE_LOGO": _find_logo(),
        "OFFICE_LETTERHEAD": _find_first(LETTERHEAD_CANDIDATES),
        **{name: _find_first(paths) for name, paths in CREST_CANDIDATES.items()},
    }


def _find_first(candidates):
    """First candidate that exists under a static dir, else None.

    Deliberately not cached: dropping the file into static/img/ takes effect
    on the next page load, with no server restart.
    """
    for relative in candidates:
        for static_dir in settings.STATICFILES_DIRS:
            if os.path.exists(os.path.join(static_dir, *relative.split("/"))):
                return relative
    return None


def _find_logo():
    """Static path of the logo, or None so templates fall back to the icon."""
    return _find_first(LOGO_CANDIDATES)


def user_counts(request):
    """Active/total user counts for the Users menu badge.

    Only queried for users who can actually open that section, so ordinary
    pages for a clerk or the Commissioner cost nothing extra.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.can_manage_users():
        return {}

    from accounts.models import User

    total = User.objects.count()
    active = User.objects.filter(is_active=True).count()

    return {
        "user_count_total": total,
        "user_count_active": active,
        "user_count_disabled": total - active,
    }
