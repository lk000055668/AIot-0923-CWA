"""Canonical region names shared by CWA parsing, geometry and aggregation."""
import unicodedata


def normalizeCountyName(value):
    return "".join(unicodedata.normalize("NFKC", str(value or "")).split()).replace("台", "臺")


def normalizeDistrictName(value):
    return normalizeCountyName(value)
