"""Who the stress network was trained on. Shared by the training universe screen and the live app's search gate,
so an issuer the training screen would have excluded is never scored."""
from __future__ import annotations


def excluded_sic(sic) -> str | None:
    """None if the SIC code is inside the training population, else the reason it is outside."""
    if sic in (None, "", "0"):
        return "sic_missing"
    s = int(sic)
    if 6000 <= s <= 6799:
        return "financial_sector"
    if s in (6770, 9995):
        return "blank_check"
    return None


REASONS = {
    "sic_missing": "SEC lists no industry (SIC) code for this filer; the network was trained only on classified "
                   "non-financial companies",
    "financial_sector": "financial-sector filer (SIC 6000-6799): banks, insurers and investment vehicles were "
                        "excluded from the network's training population, and its leverage and coverage inputs do "
                        "not mean the same thing for them",
    "blank_check": "blank-check or shell company: outside the network's training population",
}
