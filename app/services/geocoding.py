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

BIGDATACLOUD_URL = 'https://api.bigdatacloud.net/data/reverse-geocode-client'
_TIMEOUT = 8
_NOMINATIM_ATTEMPTS = 2
_RETRY_BACKOFF = 1.5

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


def _nominatim_lookup(lat, lon):
    """One Nominatim request. Returns a label, or None on any failure."""
    try:
        _throttle()
        response = requests.get(
            NOMINATIM_URL,
            params={'format': 'jsonv2', 'lat': lat, 'lon': lon, 'zoom': 14, 'addressdetails': 1},
            headers={'User-Agent': USER_AGENT},
            timeout=_TIMEOUT,
        )
        if response.status_code != 200:
            print(f"Nominatim returned HTTP {response.status_code} for ({lat}, {lon})")
            return None
        data = response.json()
        label = _compose_label(data.get('address') or {})
        if label:
            return label
        display_name = data.get('display_name')
        return display_name[:255] if display_name else None
    except Exception as e:
        print(f"Nominatim lookup failed for ({lat}, {lon}): {e}")
        return None


def _bigdatacloud_lookup(lat, lon):
    """Keyless fallback used when Nominatim is unreachable or rate-limiting us."""
    try:
        response = requests.get(
            BIGDATACLOUD_URL,
            params={'latitude': lat, 'longitude': lon, 'localityLanguage': 'en'},
            headers={'User-Agent': USER_AGENT},
            timeout=_TIMEOUT,
        )
        if response.status_code != 200:
            print(f"BigDataCloud returned HTTP {response.status_code} for ({lat}, {lon})")
            return None
        data = response.json()
        parts = [data.get('locality') or data.get('city'),
                 data.get('principalSubdivision'),
                 data.get('countryName')]
        label = ', '.join(dict.fromkeys(p for p in parts if p))
        return label[:255] if label else None
    except Exception as e:
        print(f"BigDataCloud lookup failed for ({lat}, {lon}): {e}")
        return None


def reverse_geocode(lat, lon):
    """Return a short human-readable location label for the exact (lat, lon), or
    None on any failure. Never raises, never returns a hardcoded/sample address.

    Tries Nominatim (with one retry), then falls back to BigDataCloud."""
    if lat is None or lon is None:
        return None
    for attempt in range(_NOMINATIM_ATTEMPTS):
        label = _nominatim_lookup(lat, lon)
        if label:
            return label
        if attempt < _NOMINATIM_ATTEMPTS - 1:
            time.sleep(_RETRY_BACKOFF)
    return _bigdatacloud_lookup(lat, lon)
