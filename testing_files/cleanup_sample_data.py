#!/usr/bin/env python
"""ONE-OFF MAINTENANCE SCRIPT — run manually, never from a route/CI/deploy step.

Deletes ONLY rows matching the deterministic markers left by the old
"Generate Sample Data" admin feature (now removed):
  - User.email LIKE '%@example.com'
  - WasteReport.image_filename LIKE 'sample\\_%' (escaped underscore, exact prefix)

Dry-run by default: prints what it would delete and makes no changes.
Set CONFIRM=yes to actually delete, only after reviewing the dry-run output.

Usage:
    python testing_files/cleanup_sample_data.py                # dry run
    CONFIRM=yes python testing_files/cleanup_sample_data.py     # delete for real
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import User, WasteReport

app = create_app()

with app.app_context():
    sample_reports = WasteReport.query.filter(
        WasteReport.image_filename.like('sample\\_%', escape='\\')
    ).all()
    sample_users = User.query.filter(User.email.like('%@example.com')).all()

    print(f"Found {len(sample_reports)} sample report(s), {len(sample_users)} sample user(s).")
    for r in sample_reports:
        print(f"  report id={r.id} filename={r.image_filename}")
    for u in sample_users:
        print(f"  user id={u.id} email={u.email}")

    if os.environ.get('CONFIRM') != 'yes':
        print("\nDry run only - nothing deleted. Set CONFIRM=yes to actually delete.")
    else:
        for r in sample_reports:
            db.session.delete(r)
        for u in sample_users:
            db.session.delete(u)  # cascades to any remaining reports for that user
        db.session.commit()
        print("\nDeleted.")
