"""Reverse geocoding via OSM Nominatim's public API.

Turns exact report coordinates into a short human-readable location label.
Called once per report, at creation time, and the result is persisted to
WasteReport.address — never re-requested on every page view.

Follows Nominatim's usage policy (https://operations.osmfoundation.org/policies/nominatim/):
identifying User-Agent, max ~1 request/second, and OSM data attribution
(already shown on every map via the tile-layer attribution string).
"""
import os
import time
import requests

NOMINATIM_URL = 'https://nominatim.openstreetmap.org/reverse'
USER_AGENT = f"MapMyWaste/1.0 (contact: {os.environ.get('GEOCODING_CONTACT_EMAIL', 'crudreview@datadrone.biz')})"

_last_request_time = 0.0
_MIN_REQUEST_INTERVAL = 1.0  # Nominatim public API: max 1 request/second

# Priority order for composing a short label from Nominatim's structured address parts
_LABEL_FIELDS = ['suburb', 'neighbourhood', 'city', 'town', 'village', 'state', 'country']


def _throttle():
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


def _compose_label(address_parts):
    """Build a short 'Area, State, Country'-style label from Nominatim's structured
    address object, picking at most one city-level field plus state/country."""
    parts = []
    city_field_used = False
    for field in _LABEL_FIELDS:
        value = address_parts.get(field)
        if not value:
            continue
        if field in ('suburb', 'neighbourhood', 'city', 'town', 'village'):
            if city_field_used:
                continue
            city_field_used = True
        parts.append(value)
    return ', '.join(parts) if parts else None


def reverse_geocode(lat, lon):
    """Return a short human-readable location label for the exact (lat, lon), or
    None on any failure. Never raises, never returns a hardcoded/sample address."""
    if lat is None or lon is None:
        return None
    try:
        _throttle()
        response = requests.get(
            NOMINATIM_URL,
            params={'format': 'jsonv2', 'lat': lat, 'lon': lon, 'zoom': 14, 'addressdetails': 1},
            headers={'User-Agent': USER_AGENT},
            timeout=5,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        address_parts = data.get('address') or {}
        label = _compose_label(address_parts)
        if label:
            return label
        display_name = data.get('display_name')
        if display_name:
            return display_name[:255]
        return None
    except Exception as e:
        print(f"Reverse geocoding failed for ({lat}, {lon}): {e}")
        return None
