"""Supabase Storage client for persisting user-uploaded waste-report photos.

Render Free's disk is ephemeral (wiped on restart/redeploy), so uploaded images
are pushed to a Supabase Storage bucket instead. Uses only the publishable/anon
key (never the service-role key) — the bucket must be public with RLS policies
allowing anon insert/select. See README for setup.
"""
import os
import requests

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_PUBLISHABLE_KEY = os.environ.get('SUPABASE_PUBLISHABLE_KEY', '')
SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', 'waste-images')


def is_configured():
    return bool(SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY)


def upload_file(local_path, object_name):
    """Upload a local file to the Supabase Storage bucket. Returns True on success,
    False on any failure — never raises, so a Storage hiccup never blocks report
    creation."""
    if not is_configured():
        return False
    try:
        url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{object_name}"
        headers = {
            'apikey': SUPABASE_PUBLISHABLE_KEY,
            'Authorization': f'Bearer {SUPABASE_PUBLISHABLE_KEY}',
            'x-upsert': 'true',
        }
        with open(local_path, 'rb') as f:
            response = requests.post(url, headers=headers, data=f, timeout=30)
        return response.status_code in (200, 201)
    except Exception as e:
        print(f"Supabase Storage upload failed for {object_name}: {e}")
        return False


def get_public_url(object_name):
    if not is_configured():
        return None
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{object_name}"
