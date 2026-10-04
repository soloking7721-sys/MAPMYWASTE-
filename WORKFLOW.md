# MapMyWaste — Project Workflow

A beginner-friendly walkthrough of how MapMyWaste works end to end: what happens when a user reports waste, where the data goes, and how the app runs in production. For setup, deployment steps and troubleshooting, see [README.md](README.md). This document only describes functionality that exists in the repository.

---

## 1. Overall Project Flow

```
Resident (browser)
   |  1. logs in, opens "Report Waste"
   |  2. picks a photo + location (GPS / EXIF / manual) + description
   v
Flask app on Render (gunicorn)               <-- app/main/routes.py : upload()
   |  3. saves photo, reads EXIF GPS, resolves coordinates
   |  4. reverse-geocodes coordinates -> place name
   |  5. scores the image, checks for duplicates
   |  6. saves the WasteReport row, awards points/badges
   |
   +--> Supabase PostgreSQL   (users, reports, contact messages)
   +--> Supabase Storage      (the uploaded photo)
   |
   v
Result page  (/report/<id>/result)  -> shows photo, location, score, points
   |
   v
Admin reviews reports on a live map  (/admin/map)
```

Roles: **user** (reports waste, sees own reports, points, badges, leaderboard) and **admin** (dashboard, map, cleanup tools).

---

## 2. User / Report Submission Flow

1. User registers or logs in (`app/auth/routes.py`, Flask-Login session cookie).
2. User opens `/upload` (`main.upload`, login required) — template `app/templates/main/upload.html`.
3. User chooses a photo, optionally writes a description, and provides a location (see section 4).
4. Browser POSTs a multipart form (`image`, `description`, `latitude`, `longitude`) to `/upload`.
5. Server processes it (section 6) and redirects to `/report/<id>/result`.
6. The report then appears under `/reports/my`, on the dashboard, and on the admin map.

---

## 3. Frontend → Backend Request Flow

| Step | Where | What |
|---|---|---|
| 1 | `upload.html` (Jinja2 + Bootstrap + Leaflet) | Form with file input and latitude/longitude fields |
| 2 | Browser JS in `upload.html` | "Get my location" button fills the lat/lon inputs and shows a Leaflet map preview |
| 3 | `POST /upload` | Sends the form to Flask |
| 4 | `main.upload()` in `app/main/routes.py` | Validates, processes, writes DB, redirects |
| 5 | `GET /report/<id>/result` | Renders `main/report_result.html` for the new report |

All pages are server-rendered Jinja2 templates. There is no separate SPA/API for the user flow. The admin map page is also server-rendered: `admin.map()` passes the reports into `admin/map.html`.

---

## 4. GPS / Location Capture Flow

A report always needs coordinates. They come from one of three sources, stored in `WasteReport.location_source`:

```
Photo has GPS in EXIF?  ── yes ──> use EXIF coords        -> source = "EXIF"
        |
        no
        v
Browser sent lat/lon?   ── yes ──> use form coords        -> source = "BROWSER"
        |                          (filled by the browser's geolocation button
        |                           or typed by the user)
        no
        v
Error: "Location is required — enable GPS or enter coordinates manually."
(the user is sent back to /upload)
```

- **Browser geolocation**: `navigator.geolocation.getCurrentPosition` in `upload.html`. If denied/unsupported, the page tells the user to enter coordinates manually.
- **EXIF**: `extract_gps_from_image()` in `app/services/exif_utils.py` (Pillow). EXIF coordinates **override** the form coordinates when present.
- The code also defines a `MANUAL` default, but a typed value arriving without EXIF is recorded as `BROWSER`, because the form cannot tell the two apart.

---

## 5. Reverse Geocoding Flow (coordinates → place name)

Handled by `app/services/geocoding.py`, function `reverse_geocode(lat, lon)`.

```
reverse_geocode(lat, lon)
   |
   |-- Attempt 1: OSM Nominatim  (throttled to ~1 req/sec, 8 s timeout)
   |       success -> short label e.g. "Bhayander East, Maharashtra, India"
   |
   |-- Attempt 2: Nominatim again after a 1.5 s pause (only if attempt 1 failed)
   |
   |-- Fallback: BigDataCloud free reverse-geocode endpoint (no API key)
   |       success -> label e.g. "Bhayandar, Maharashtra, India"
   |
   '-- All failed -> returns None   (function never raises)
```

- Label building: `_compose_label()` picks one area-level field (`suburb`, `neighbourhood`, `city`, `town`, `village`) plus `state` and `country`. If that yields nothing it uses Nominatim's `display_name` (max 255 chars).
- Nominatim usage-policy compliance: identifying `User-Agent` (uses `GEOCODING_CONTACT_EMAIL`), at most one request per second.
- The label is stored in `WasteReport.address` (a 255-char string column).

### Location fallback / retry (when the label is missing)

If every geocoder fails during upload, the report is still saved with `address = NULL` and the exact coordinates intact. The result page then shows **"Location unavailable"** under the coordinates. To recover automatically:

```
Open /report/<id>/result
   |
   address already saved?  ── yes ──> show it (no network call)
   |
   no, but lat/lon exist
   v
reverse_geocode(lat, lon) again
   |-- got a label -> save it to report.address, commit  (done once, never repeated)
   '-- still failing -> page renders normally with "Location unavailable"
                        (next visit tries again)
```

This backfill lives in `report_result()` in `app/main/routes.py` and is wrapped in `try/except` so it can never break the page.

---

## 6. Waste Report Creation Flow (`main.upload`)

In order:

1. **Validate file** — a file must be present, non-empty, and have an allowed extension (`png, jpg, jpeg, gif, webp`; max 16 MB via `MAX_CONTENT_LENGTH`).
2. **Save locally** — filename becomes `<user_id>_<timestamp>_<secure_name>` inside `uploads/`.
3. **Push to Supabase Storage** — `storage.upload_file()` (section 7).
4. **Read form data** — description, latitude, longitude.
5. **Resolve location** — EXIF first, else browser/manual (section 4).
6. **Reverse geocode** — `reverse_geocode()` → `address` (section 5).
7. **Hash + score** — `image_md5()` and `predict()` from `app/services/detector.py`. Note: the waste score is currently a **stub returning a randomized value** (see README → Testing).
8. **Duplicate checks** — same image hash, or same original filename already in the DB → the report is flagged `is_spam = True` and the user sees a flash warning.
9. **Create `WasteReport` row** — user, filename, hash, score, spam flag, description, lat/lon, `location_source`, `address`.
10. **Gamification** — `reports_count += 1`, `+10` points; `update_user_achievements()` (`app/services/gamification.py`) grants badges at 1 / 5 / 20 reports (Rookie Reporter, Neighborhood Watcher, Waste Warrior) with bonus points.
11. **Commit**, store newly-earned badges and duplicate info in the session, redirect to the result page.

---

## 7. Image Upload / Storage Flow

```
Browser ──multipart──> Flask  ──save──> uploads/<file>   (temporary on Render: disk is ephemeral)
                                  |
                                  |-- used for EXIF GPS + MD5 hash + score
                                  |
                                  '-- storage.upload_file() ──POST──> Supabase Storage bucket
                                            (publishable/anon key, x-upsert: true)

Displaying a photo:  <img src="/uploads/<filename>">
   -> route uploaded_file():
        Supabase configured?  yes -> HTTP redirect to the public Supabase URL
                              no  -> serve from local uploads/ (local dev)
```

`upload_file()` returns `True/False` and never raises, so a Storage outage never blocks report creation (the image would just not persist beyond the local disk). Config lives in `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_BUCKET`.

---

## 8. Database Flow

Defined in `app/models.py` (Flask-SQLAlchemy). Tables are created automatically by `db.create_all()` in `run.py` on boot — there are no migration files.

| Model | Key fields |
|---|---|
| `User` | name, email, password hash, role (`user`/`admin`), points, reports_count, badges, tasks_completed |
| `WasteReport` | user_id, image_filename, image_hash, description, latitude, longitude, location_source (`EXIF`/`BROWSER`/`MANUAL`), **address**, waste_score, is_spam, cluster_id, created_at |
| `ContactMessage` | name, email, subject, message, created_at |

Which database: `DATABASE_URL` set → that Postgres (Supabase in production, `postgres://` is normalized to `postgresql://`). Not set → local SQLite (`sqlite:///mapmywaste.db`). In production (`ENVIRONMENT=production`) a missing `DATABASE_URL` or `SECRET_KEY` stops the app at startup instead of silently falling back.

---

## 9. Supabase Interaction

The app uses Supabase in two independent ways:

1. **PostgreSQL** — normal SQLAlchemy connection through `DATABASE_URL`; stores all application data.
2. **Storage (REST)** — `app/services/storage.py` calls `POST {SUPABASE_URL}/storage/v1/object/{bucket}/{name}` to upload and builds `.../object/public/{bucket}/{name}` URLs to display. Only the **publishable/anon** key is used; the bucket must be public with anon insert/select policies.

---

## 10. How Report Data Is Stored and Retrieved

| Need | Route | Query |
|---|---|---|
| Show just-submitted report | `/report/<id>/result` | `WasteReport.query.get_or_404(id)`; only the owner may view it |
| My reports list | `/reports/my` | reports filtered by `user_id`, newest first |
| Dashboard / profile | `/dashboard`, `/profile` | user stats + recent reports |
| Leaderboard | `/leaderboard` | users ordered by points, then reports_count |
| Admin dashboard / map | `/admin/`, `/admin/map` (plus a JSON endpoint `/admin/api/reports`) | all reports with coordinates, rendered into the Leaflet map |

Templates print `report.address` or, when empty, the text "Location unavailable" (`report_result.html`, `my_reports.html`, `admin/map.html`).

---

## 11. How the Report Result Page Works

`GET /report/<id>/result` (`report_result()`):

1. Load the report; refuse (flash + redirect to dashboard) if it belongs to another user.
2. **Backfill the address** if it is missing (section 5).
3. Pop one-time session values: newly earned badges, duplicate flag/type.
4. Render `main/report_result.html`: photo, submitted time, coordinates + place name, location source, description, waste score, points/stats, and next-step links.

---

## 12. Important API / Service Interactions

| Service | Used for | Called from | Key needed |
|---|---|---|---|
| OSM Nominatim (`nominatim.openstreetmap.org/reverse`) | Primary reverse geocoding | `geocoding.py` | No (needs identifying User-Agent) |
| BigDataCloud (`api.bigdatacloud.net/data/reverse-geocode-client`) | Geocoding fallback | `geocoding.py` | No |
| Supabase Storage REST | Persist/display photos | `storage.py` | Publishable key |
| Supabase Postgres | All app data | SQLAlchemy via `DATABASE_URL` | Connection string |
| OpenStreetMap tiles + Leaflet (CDN) | Maps in upload preview and admin map | templates | No |
| Browser Geolocation API | "Get my location" | `upload.html` | User permission |
| Render Deploy Hook | Trigger redeploy | GitHub Actions | `RENDER_DEPLOY_HOOK_URL` secret |

---

## 13. Error / Failure Handling

| Failure | Behavior |
|---|---|
| No file / bad extension | Flash message, back to `/upload` |
| No location at all | Flash "Location is required…", back to `/upload` |
| Duplicate image or filename | Report is saved but flagged `is_spam`; user warned |
| Geocoders unavailable | Report saved with exact coordinates, `address = NULL`, shows "Location unavailable"; retried on next result-page view |
| Supabase Storage upload fails | Logged; report creation continues |
| Supabase env vars missing | Images served from local disk (dev behavior) |
| Backfill error on result page | Rolled back and logged; page still renders |
| Missing `SECRET_KEY`/`DATABASE_URL` in production | App refuses to start |

Geocoding/storage helpers print errors to the server log (visible in Render logs) rather than raising.

---

## 14. Deployment / Runtime Flow

```
git push origin main
   |
GitHub Actions (.github/workflows/deploy.yml)
   |-- validate: install deps, create_app() smoke test, check Procfile/render.yaml/requirements.txt
   '-- deploy (push to main only): POST to Render Deploy Hook
          |
Render builds:  pip install -r requirements.txt
Render starts:  gunicorn run:app --bind 0.0.0.0:$PORT
          |
run.py on import: load .env, create_app(), db.create_all(),
                  create admin@mapmywaste.com if ADMIN_INITIAL_PASSWORD is set
          |
Render health probe: GET /health -> {"status": "ok"}
```

Render Free spins down when idle; the first request afterwards is a cold start. Local dev: `python run.py` (SQLite, local `uploads/`).

---

## 15. Environment Variables

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session signing (required in production) |
| `DATABASE_URL` | Supabase Postgres connection string (required in production; blank locally → SQLite) |
| `ENVIRONMENT` | Set to `production` to enable startup safety checks |
| `SUPABASE_URL` | Supabase project URL for Storage |
| `SUPABASE_PUBLISHABLE_KEY` | Supabase anon/publishable key for Storage (never the service-role key) |
| `SUPABASE_BUCKET` | Storage bucket name (default `waste-images`) |
| `ADMIN_INITIAL_PASSWORD` | Creates `admin@mapmywaste.com` on first boot if set |
| `GEOCODING_CONTACT_EMAIL` | Contact address placed in the User-Agent of geocoding requests |

Names only are documented in `example.env`; never commit real values.

---

## 16. Important Files

| File | Role |
|---|---|
| `run.py` | Entry point; creates tables and the admin account; `app` object for gunicorn |
| `config.py` | Environment-driven config, upload limits, gamification constants |
| `app/__init__.py` | App factory, extensions, blueprints (`auth`, `main`, `admin`) |
| `app/models.py` | `User`, `WasteReport`, `ContactMessage` |
| `app/main/routes.py` | Upload, result page, dashboard, my reports, leaderboard, contact, image serving, `/health` |
| `app/auth/routes.py` | Register / login / logout |
| `app/admin/routes.py` | Admin dashboard, map, report API, cleanup tools |
| `app/services/geocoding.py` | Reverse geocoding with retry + fallback |
| `app/services/storage.py` | Supabase Storage upload and public URLs |
| `app/services/exif_utils.py` | EXIF GPS extraction |
| `app/services/detector.py` | Image MD5 hash and waste score (currently a stub score) |
| `app/services/gamification.py` | Badges, tasks, bonus points |
| `app/templates/` | Jinja2 pages (`main/`, `auth/`, `admin/`, `base.html`) |
| `Procfile`, `render.yaml` | Start command and Render service definition |
| `.github/workflows/deploy.yml` | CI validation and deploy trigger |
| `testing_files/`, `scripts/` | Manual dev/debug utilities |

---

## 17. End-to-End Example

Asha opens MapMyWaste on her phone, logs in, and taps **Report Waste**.

1. She selects a photo of a garbage pile and types a short description.
2. She taps **Get my location**; the browser asks permission and returns `19.307761, 72.861671`. A map preview appears.
3. She submits. Flask saves `12_20261004_074500_pile.jpg` and uploads it to Supabase Storage.
4. The photo has no EXIF GPS, so the form coordinates are used and `location_source = BROWSER`.
5. `reverse_geocode()` asks Nominatim for the place. It is rate-limited, so it retries once, then falls back to BigDataCloud and gets "Bhayandar, Maharashtra, India".
6. The image hash is not in the DB, so it is not spam. A waste score is computed.
7. A `WasteReport` row is inserted with address, coordinates, score and source. Asha gets +10 points and, as her first report, the *Rookie Reporter* badge plus bonus points.
8. She is redirected to `/report/<id>/result` and sees her photo, the place name, the score and her new stats.
9. If both geocoders had failed, the page would show "Location unavailable" and the label would be filled in automatically the next time she opens that page.
10. An admin opens `/admin/map` and sees the pin at her coordinates.
