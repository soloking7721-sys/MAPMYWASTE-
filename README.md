# MapMyWaste

A Flask web application for community-driven waste reporting: residents photograph and geotag waste dumping sites, and admins review reports on a live map.

## Problem Statement

Urban waste collection is often reactive rather than data-driven: municipal teams lack a simple channel for citizens to report waste hotspots with accurate locations, and there's no feedback loop between residents and the collection authority.

## Project Objectives

- Give residents a low-friction way to report waste (photo + location) and see the impact of their reports (points, badges, leaderboard).
- Give administrators a live view of reported waste locations on a map.
- Deploy the system as a real, persistent, publicly reachable web application rather than a local-only prototype.

## Features

- User registration/login (Flask-Login), role-based access (user/admin)
- Waste report submission: photo upload, GPS from EXIF metadata / browser geolocation / manual entry, duplicate detection (image hash + filename)
- Reverse geocoding of report coordinates into a human-readable location label (OSM Nominatim)
- Gamification: points, badges, public leaderboard
- Admin dashboard: report review, live map of all reported locations, sort by waste score, report cleanup tools
- Public leaderboard and contact form

## Tech Stack

- **Backend**: Python 3.10, Flask 2.3, Flask-SQLAlchemy, Flask-Login, Werkzeug
- **Database**: PostgreSQL via Supabase (production), SQLite (local dev fallback)
- **Storage**: Supabase Storage (REST API, publishable/anon key) for user-uploaded photos
- **Data/ML utilities**: Pillow (EXIF GPS extraction), numpy (waste-score detector)
- **Frontend**: Jinja2 templates, Bootstrap and Leaflet.js (via CDN)
- **Server**: gunicorn (production WSGI server)
- **Hosting**: Render (Free web service tier)
- **CI/CD**: GitHub Actions → Render Deploy Hook

## System Architecture

```
User
  |
Render Free Web Service (Flask + gunicorn)
  |
  +-- Supabase PostgreSQL   (all application data)
  +-- Supabase Storage      (user-uploaded waste-report photos)

GitHub
  |
GitHub Actions (validate on push/PR)
  |
Render Deploy Hook
  |
Render deployment
```

Static app assets (CSS/JS, marketing images in `images/`) are served directly by the app. Only user-uploaded `WasteReport` photos go to Supabase Storage — Render's free-tier disk is ephemeral and would otherwise lose them on every restart or redeploy.

## Project Structure

```
app/
  __init__.py          # app factory
  models.py            # SQLAlchemy models (User, WasteReport, ContactMessage)
  auth/                 # login / register / logout
  main/                 # core routes: upload, dashboard, leaderboard, /health
  admin/                # admin dashboard, report map
  services/             # detector, exif, geocoding, gamification, storage
  static/                # CSS / JS
  templates/
config.py               # environment-driven configuration
run.py                   # app entry point, admin bootstrap
Procfile                 # gunicorn start command
render.yaml              # Render service definition (documentation; dashboard is source of truth)
requirements.txt
.github/workflows/deploy.yml
example.env              # documents required environment variable names
uploads/                 # local fallback directory (dev only, gitignored)
images/                  # static marketing images (committed)
model/                   # pretrained weights (currently unused — see Testing/limitations)
scripts/, testing_files/  # development/debug utilities
```

## Local Setup

```bash
git clone https://github.com/soloking7721-sys/MAPMYWASTE-.git
cd MAPMYWASTE-
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
copy example.env .env        # Windows: copy; macOS/Linux: cp example.env .env
```

Leave `DATABASE_URL` and `ENVIRONMENT` blank in `.env` for local development — the app falls back to a local SQLite database automatically. Leave `SUPABASE_URL` / `SUPABASE_PUBLISHABLE_KEY` blank to keep uploads on local disk. Set `ADMIN_INITIAL_PASSWORD` to create the admin account on first run.

```bash
python run.py
```

The app runs at `http://localhost:5000`.

## Environment Variables

| Variable | Required in production | Purpose |
|---|---|---|
| `SECRET_KEY` | Yes | Flask session signing key |
| `DATABASE_URL` | Yes | Supabase Postgres connection string |
| `ENVIRONMENT` | Yes (`production`) | Enables production safety checks (no silent SQLite fallback) |
| `SUPABASE_URL` | Yes (for image persistence) | Supabase project URL |
| `SUPABASE_PUBLISHABLE_KEY` | Yes (for image persistence) | Supabase anon/publishable API key — never the service-role key |
| `SUPABASE_BUCKET` | No (defaults to `waste-images`) | Storage bucket name |
| `ADMIN_INITIAL_PASSWORD` | Recommended | Password for the auto-created `admin@mapmywaste.com` account on first boot |
| `GEOCODING_CONTACT_EMAIL` | No (defaults to a placeholder) | Contact address sent in the `User-Agent` header for reverse-geocoding requests to OSM Nominatim, per its usage policy |

Never commit real values — see `example.env` for names only.

## Supabase PostgreSQL Setup

1. In the Supabase dashboard, open **Project Settings → Database** and copy the connection string.
2. Set it as `DATABASE_URL` on Render (already configured for this deployment). The app normalizes `postgres://` to `postgresql://` automatically.
3. No manual schema migration is required — `db.create_all()` runs on boot and creates all tables/columns against a fresh Supabase database.

## Supabase Storage Setup

1. Create a Storage bucket named `waste-images` (or set `SUPABASE_BUCKET` to match a different name).
2. Mark the bucket **public**, and add RLS policies on `storage.objects` allowing `INSERT` and `SELECT` for the anon role scoped to that bucket.
3. Use the **publishable/anon key only** (Project Settings → API) as `SUPABASE_PUBLISHABLE_KEY`. The service-role key is never used by this application and must never be committed anywhere.

## Render Deployment

- Free Web Service, Python runtime, branch `main`, region Oregon
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn run:app --bind 0.0.0.0:$PORT`
- Health Check Path: `/health`
- Environment variables set manually in the Render dashboard: `SECRET_KEY`, `DATABASE_URL` (already configured), plus `ENVIRONMENT=production`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_BUCKET`, `ADMIN_INITIAL_PASSWORD`

## GitHub Actions CI/CD

On every push or pull request to `main`, `.github/workflows/deploy.yml`:
1. Installs dependencies.
2. Verifies the Flask app factory imports and initializes cleanly (no live database required for this check).
3. On a successful push to `main` only, POSTs to the Render Deploy Hook to trigger a redeploy.

**Required one-time setup**: add the Render Deploy Hook URL (Render dashboard → service → Settings → Deploy Hook) as a GitHub repository secret named `RENDER_DEPLOY_HOOK_URL` (Settings → Secrets and variables → Actions). Without this secret, the deploy step logs a message and exits without failing the workflow.

## Health Check

`GET /health` returns `{"status": "ok"}` with HTTP 200. It requires no authentication and performs no database queries, so Render's health probe stays fast and cheap. This is the path configured as the Render service's Health Check Path.

## Image Storage & Persistence

User-uploaded waste-report photos are the only data that needs special handling for persistence: Render's free-tier disk is wiped on every restart, redeploy, or spin-down. To avoid losing them:

- On upload, the photo is saved locally (used momentarily for EXIF GPS extraction and duplicate-hash checks), then pushed to the Supabase Storage bucket.
- The app's image-serving route redirects to the photo's public Supabase Storage URL when Storage is configured, so every existing template keeps working unchanged.
- If Supabase Storage environment variables are not set (e.g. local development), the app transparently falls back to serving images from local disk, matching the original pre-deployment behavior.
- Static assets that are part of the application itself (CSS, JS, marketing images in `images/`) are committed to the repository and are not affected by this — only user-generated uploads are stored externally.

## Testing

- `python -c "from app import create_app; create_app()"` — smoke-tests that the app factory imports and initializes without errors; this is the same check GitHub Actions runs in CI.
- `testing_files/test_integration.py` — a manual (non-pytest) script that exercises the detector/hashing service and waste-report creation, including duplicate-detection logic.
- `testing_files/cleanup_sample_data.py` — a manual, dry-run-by-default maintenance script for removing leftover demo/sample rows (identified by the `@example.com` email domain and `sample_` filename prefix). Never runs automatically; requires `CONFIRM=yes` to actually delete.
- `scripts/` contains development utilities for inspecting the database (`check_db.py`, `print_db_location.py`) and a legacy SQLite-only schema patcher (`ensure_schema.py`), kept for reference.
- There is currently no automated pytest suite covering routes or authentication — this is a known gap, listed under Future Scope.
- Note: the waste-detection "AI score" (`app/services/detector.py`) is currently a stub that returns a randomized score for demonstration purposes; the committed model weights in `model/` are not yet wired into an inference path.

## Security

- Secrets (`SECRET_KEY`, `DATABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `ADMIN_INITIAL_PASSWORD`) are read from environment variables only — never hardcoded or committed. `.env` is gitignored.
- Only the Supabase **publishable/anon** key is used server-side; the service-role key is never required or used by this application.
- The database connection string and the Render deploy hook are stored as Render/GitHub secrets, not in source control.
- The admin account is created only when `ADMIN_INITIAL_PASSWORD` is explicitly set — there is no hardcoded default credential anywhere in a production code path.
- In production (`ENVIRONMENT=production`), the app refuses to start if `SECRET_KEY` or `DATABASE_URL` are missing, instead of silently falling back to an insecure default or a local SQLite database.
- Known pre-existing limitations, out of scope for this deployment work: no CSRF protection (no Flask-WTF) and no rate-limiting on login/registration forms.

## Free-Tier Limitations

- **Spin-down**: the Render service sleeps after a period of inactivity and wakes on the next incoming request (cold start, up to roughly a minute).
- **Monthly instance-hours**: the Free plan has a limited monthly compute quota.
- **Ephemeral filesystem**: anything written to local disk is lost on restart/redeploy — the reason user-uploaded photos live in Supabase Storage rather than on Render's disk.
- No keep-alive pings, cron jobs, or background workers are used to bypass spin-down; sleep and cold-start behavior are expected and accepted as part of running on the free tier.

## Troubleshooting

- **App fails to start / crash loop**: check Render logs. `DATABASE_URL is not set` means `ENVIRONMENT=production` is set but `DATABASE_URL` isn't — add it in the dashboard.
- **Missing `DATABASE_URL`**: production intentionally refuses to fall back to SQLite; set it to the Supabase connection string.
- **Supabase connection failure**: verify the connection string and that the Supabase project is active.
- **Uploaded images don't appear / broken image links**: verify `SUPABASE_URL` / `SUPABASE_PUBLISHABLE_KEY` are set and that the `waste-images` bucket is public with anon insert/select RLS policies.
- **GitHub Actions failure**: check the `validate` job logs — usually a dependency or import error.
- **Render deployment doesn't trigger after a push**: confirm `RENDER_DEPLOY_HOOK_URL` is set as a repository secret.
- **Health check failing on Render**: confirm the Start Command binds `$PORT` (`gunicorn run:app --bind 0.0.0.0:$PORT`) and matches what's configured in the Render dashboard.
- **Report shows "Location unavailable" instead of a place name**: reverse geocoding (via the public OSM Nominatim API, see `app/services/geocoding.py`) failed for that request — network error, timeout, or rate limiting. The report's exact coordinates are always preserved regardless; only the human-readable label is affected. This is best-effort and does not require a key or paid tier.

## Future Scope

- Wire up a real image-classification model for waste scoring (replacing the current stub in `app/services/detector.py`).
- Add an automated pytest suite covering authentication and report submission.
- Add CSRF protection and rate-limiting on authentication/report forms.
- Add signed/expiring URLs for Supabase Storage objects if reports need to become private in the future.

## Maintainer

**Ankit Rana** ([itsakrana](https://github.com/itsakrana)) — current maintainer, responsible for the production deployment (Supabase integration, Render configuration, CI/CD pipeline, and security hardening).
