import os
from flask import render_template, redirect, url_for, flash, jsonify, abort, request
from flask_login import login_required, current_user
from functools import wraps
from app.admin import bp
from app.models import User, WasteReport
from app import db

def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@bp.route('/')
@login_required
@admin_required
def dashboard():
    total_reports = WasteReport.query.count()
    total_users = User.query.count()

    # Debug output
    print(f"Debug - Total reports: {total_reports}, Total users: {total_users}")

    # Check if sorting by score
    sort_by = request.args.get('sort', 'recent')
    is_sorted_by_score = False

    if sort_by == 'score':
        # Sort by waste_score (highest first), then by date
        recent_reports = WasteReport.query.order_by(
            WasteReport.waste_score.desc(),
            WasteReport.created_at.desc()
        ).limit(10).all()
        is_sorted_by_score = True
    else:
        # Default: sort by date (most recent first)
        recent_reports = WasteReport.query.order_by(WasteReport.created_at.desc()).limit(10).all()

    return render_template('admin/dashboard.html',
                         total_reports=total_reports,
                         total_users=total_users,
                         recent_reports=recent_reports,
                         is_sorted_by_score=is_sorted_by_score)

@bp.route('/map')
@login_required
@admin_required
def map():
    reports = WasteReport.query.filter(
        WasteReport.latitude.isnot(None),
        WasteReport.longitude.isnot(None)
    ).all()

    return render_template('admin/map.html', reports=reports)

@bp.route('/clear_reports', methods=['POST'])
@login_required
@admin_required
def clear_reports():
    try:
        # Count before deletion
        initial_report_count = WasteReport.query.count()
        initial_user_count = User.query.count()

        print(f"Initial counts - Reports: {initial_report_count}, Users: {initial_user_count}")

        # First, delete all non-admin users (this will cascade delete their reports due to relationship)
        user_count = 0
        for user in User.query.all():
            if user.role != 'admin':
                db.session.delete(user)
                user_count += 1
            else:
                # Reset admin user stats
                user.reports_count = 0
                user.points = 0
                user.tasks_completed = 0
                user.badges = '[]'

        # Delete any remaining reports (in case some reports don't have users or other edge cases)
        WasteReport.query.delete()

        # Commit the deletions and updates
        db.session.commit()

        # Ensure admin user exists (after commit, in case admin was deleted)
        admin = User.query.filter_by(email='admin@mapmywaste.com').first()
        if not admin:
            initial_password = os.environ.get('ADMIN_INITIAL_PASSWORD')
            if initial_password:
                admin = User(
                    name='Admin',
                    email='admin@mapmywaste.com',
                    role='admin',
                    points=0,
                    reports_count=0,
                    tasks_completed=0,
                    badges='[]'
                )
                admin.set_password(initial_password)
                db.session.add(admin)
                db.session.commit()
            else:
                flash('ADMIN_INITIAL_PASSWORD not set — admin user was not recreated.', 'warning')

        # Calculate deleted counts
        deleted_reports = initial_report_count
        deleted_users = user_count

        # Verify the deletions worked
        final_reports = WasteReport.query.count()
        final_users = User.query.count()

        flash(f'Database reset complete! Deleted {deleted_reports} reports and {deleted_users} users. Admin user recreated. Final counts: {final_reports} reports, {final_users} users.', 'success')
        print(f"Cleared {deleted_reports} reports and deleted {deleted_users} users. Final counts: {final_reports} reports, {final_users} users")  # Debug
    except Exception as e:
        db.session.rollback()
        flash(f'Error clearing database: {str(e)}', 'error')
        print(f"Error clearing database: {str(e)}")  # Debug

    return redirect(url_for('admin.dashboard'))

@bp.route('/clear-recent-reports', methods=['POST'])
@login_required
@admin_required
def clear_recent_reports():
    """Clear reports from the last 24 hours"""
    try:
        from datetime import datetime, timedelta

        # Calculate cutoff time (24 hours ago)
        cutoff_time = datetime.utcnow() - timedelta(hours=24)

        # Find recent reports
        recent_reports = WasteReport.query.filter(WasteReport.created_at >= cutoff_time).all()
        report_count = len(recent_reports)

        if report_count == 0:
            flash('No reports found from the last 24 hours.', 'info')
            return redirect(url_for('admin.dashboard'))

        # Delete recent reports
        for report in recent_reports:
            db.session.delete(report)

        # Update user stats for affected users
        affected_user_ids = set(report.user_id for report in recent_reports)
        for user_id in affected_user_ids:
            user = User.query.get(user_id)
            if user:
                # Recalculate user's stats
                user.reports_count = WasteReport.query.filter_by(user_id=user.id).count()
                user.points = user.reports_count * 10  # Recalculate points
                # You might want to recalculate badges too
                from app.services.gamification import update_user_achievements
                update_user_achievements(user)

        db.session.commit()

        flash(f'Cleared {report_count} reports from the last 24 hours. User stats updated.', 'success')
        print(f"Cleared {report_count} recent reports")  # Debug

    except Exception as e:
        db.session.rollback()
        flash(f'Error clearing recent reports: {str(e)}', 'error')
        print(f"Error clearing recent reports: {str(e)}")  # Debug

    return redirect(url_for('admin.dashboard'))

@bp.route('/debug')
@login_required
@admin_required
def debug():
    """Debug route to check database state"""
    users = User.query.all()
    reports = WasteReport.query.all()

    debug_info = {
        'total_users': len(users),
        'total_reports': len(reports),
        'users': [{'id': u.id, 'name': u.name, 'email': u.email, 'reports_count': u.reports_count, 'points': u.points} for u in users],
        'reports': [{'id': r.id, 'user_id': r.user_id, 'latitude': r.latitude, 'longitude': r.longitude} for r in reports[:5]]  # First 5 reports
    }

    return jsonify(debug_info)

@bp.route('/api/reports')
@login_required
@admin_required
def api_reports():
    """API endpoint for map data"""
    reports = WasteReport.query.filter(
        WasteReport.latitude.isnot(None),
        WasteReport.longitude.isnot(None)
    ).all()

    reports_data = []
    for report in reports:
        reports_data.append({
            'id': report.id,
            'latitude': report.latitude,
            'longitude': report.longitude,
            'description': report.description or '',
            'image_filename': report.image_filename,
            'user_name': report.user.name,
            'waste_score': float(report.waste_score) if report.waste_score is not None else None,
            'is_spam': bool(report.is_spam),
            'created_at': report.created_at.isoformat()
        })

    return jsonify(reports_data)
