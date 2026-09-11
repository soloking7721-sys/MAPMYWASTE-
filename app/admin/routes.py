import os
from flask import render_template, redirect, url_for, flash, jsonify, abort, request
from flask_login import login_required, current_user
from functools import wraps
from app.admin import bp
from app.models import User, WasteReport, Driver, Truck, Route, Assignment
from app import db
from app.services.clustering import run_clustering
from config import Config
from collections import defaultdict

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

    # Count clusters
    reports_with_clusters = WasteReport.query.filter(WasteReport.cluster_id.isnot(None)).all()
    cluster_count = len(set(r.cluster_id for r in reports_with_clusters if r.cluster_id is not None))

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
                         cluster_count=cluster_count,
                         recent_reports=recent_reports,
                         is_sorted_by_score=is_sorted_by_score) 

@bp.route('/cluster', methods=['POST'])
@login_required
@admin_required
def cluster():
    try:
        print("Starting clustering...")  # Debug
        k = request.form.get('k', type=int)
        print(f"Clustering with k={k}")  # Debug
        result = run_clustering(k=k)
        print(f"Clustering result: {result}")  # Debug

        if result['success']:
            flash(f"Clustering completed! {result['clusters']} clusters created from {result['total_reports']} reports.", 'success')
        else:
            flash(result['message'], 'error')
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        flash(f"Clustering failed: {str(e)}", 'error')
        print(f"Clustering error details: {error_details}")  # Debug

    return redirect(url_for('admin.dashboard'))

@bp.route('/map')
@login_required
@admin_required
def map():
    # Restrict map to Chennai area
    CHENNAI_MIN_LAT = 12.8
    CHENNAI_MAX_LAT = 13.4
    CHENNAI_MIN_LON = 80.0
    CHENNAI_MAX_LON = 80.6

    # Get all reports within Chennai bounds
    reports = WasteReport.query.filter(
        WasteReport.latitude.isnot(None),
        WasteReport.longitude.isnot(None),
        WasteReport.latitude >= CHENNAI_MIN_LAT,
        WasteReport.latitude <= CHENNAI_MAX_LAT,
        WasteReport.longitude >= CHENNAI_MIN_LON,
        WasteReport.longitude <= CHENNAI_MAX_LON
    ).all()
    
    # Calculate centroids
    centroids = []
    if reports:
        cluster_groups = defaultdict(list)
        for report in reports:
            if report.cluster_id is not None:
                cluster_groups[report.cluster_id].append(report)
        
        for cluster_id, cluster_reports in cluster_groups.items():
            avg_lat = sum(r.latitude for r in cluster_reports) / len(cluster_reports)
            avg_lon = sum(r.longitude for r in cluster_reports) / len(cluster_reports)
            centroids.append({
                'cluster_id': cluster_id,
                'latitude': avg_lat,
                'longitude': avg_lon,
                'count': len(cluster_reports)
            })
    
    return render_template('admin/map.html',
                         reports=reports,
                         centroids=centroids,
                         depot_lat=Config.DEPOT_LAT,
                         depot_lon=Config.DEPOT_LON)

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

@bp.route('/seed-data', methods=['POST'])
@login_required
@admin_required
def seed_data():
    """Generate sample data for prototyping"""
    try:
        print("Starting sample data generation...")  # Debug
        from app.services.sample_data import generate_sample_data
        result = generate_sample_data()
        print(f"Sample data result: {result}")  # Debug

        # Verify the data was created
        actual_users = User.query.count()
        actual_reports = WasteReport.query.count()

        flash(f'Sample data created: {result["users_created"]} users, {result["reports_created"]} reports. Total: {actual_users} users, {actual_reports} reports', 'success')
        print(f"Final counts - Users: {actual_users}, Reports: {actual_reports}")  # Debug
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        flash(f'Error creating sample data: {str(e)}', 'error')
        print(f"Sample data error details: {error_details}")  # Debug output

    return redirect(url_for('admin.dashboard'))


@bp.route('/seed-fleet-data', methods=['POST'])
@login_required
@admin_required
def seed_fleet_data():
    """Generate sample fleet data (trucks, drivers, routes)"""
    try:
        from datetime import datetime, time

        # Sample drivers
        drivers_data = [
            {'name': 'Raj kumar', 'license_number': 'TN123456789', 'phone': '+91 98765 43210', 'email': 'raj.driver@mapmywaste.com'},
            {'name': 'Suresh Babu', 'license_number': 'TN987654321', 'phone': '+91 98765 43211', 'email': 'suresh.driver@mapmywaste.com'},
            {'name': 'Mohan Raj', 'license_number': 'TN456789123', 'phone': '+91 98765 43212', 'email': 'mohan.driver@mapmywaste.com'},
            {'name': 'Karthik Nair', 'license_number': 'TN789123456', 'phone': '+91 98765 43213', 'email': 'karthik.driver@mapmywaste.com'},
        ]

        drivers_created = 0
        for driver_data in drivers_data:
            if not Driver.query.filter_by(license_number=driver_data['license_number']).first():
                driver = Driver(**driver_data)
                db.session.add(driver)
                drivers_created += 1

        # Sample trucks
        trucks_data = [
            {'truck_number': 'TN01-AA-1234', 'capacity': 8.0, 'truck_type': 'Garbage Compactor', 'driver_id': 1},
            {'truck_number': 'TN01-BB-5678', 'capacity': 6.0, 'truck_type': 'Dump Truck', 'driver_id': 2},
            {'truck_number': 'TN01-CC-9012', 'capacity': 10.0, 'truck_type': 'Garbage Compactor', 'driver_id': 3},
            {'truck_number': 'TN01-DD-3456', 'capacity': 7.0, 'truck_type': 'Dump Truck', 'driver_id': 4},
        ]

        trucks_created = 0
        for truck_data in trucks_data:
            if not Truck.query.filter_by(truck_number=truck_data['truck_number']).first():
                truck = Truck(**truck_data)
                db.session.add(truck)
                trucks_created += 1

        # Sample routes (around Tamil Nadu locations)
        routes_data = [
            {
                'route_name': 'Chennai Central Route',
                'description': 'Central Chennai residential areas',
                'estimated_duration': 180,  # 3 hours
                'distance_km': 45.0,
                'stops': '[[13.0827,80.2707],[13.0475,80.1960],[13.0060,80.2580]]'
            },
            {
                'route_name': 'Adyar-T. Nagar Route',
                'description': 'South Chennai upscale areas',
                'estimated_duration': 150,  # 2.5 hours
                'distance_km': 32.0,
                'stops': '[[13.0060,80.2580],[12.9200,80.0800],[12.9800,80.1500]]'
            },
            {
                'route_name': 'Coimbatore Route',
                'description': 'Coimbatore city center',
                'estimated_duration': 120,  # 2 hours
                'distance_km': 28.0,
                'stops': '[[11.0168,76.9558],[10.7905,78.7047],[10.7905,78.7047]]'
            },
            {
                'route_name': 'Madurai Route',
                'description': 'Madurai residential and commercial',
                'estimated_duration': 140,  # 2.3 hours
                'distance_km': 35.0,
                'stops': '[[9.9252,78.1198],[8.1762,77.4415],[8.7139,77.7567]]'
            }
        ]

        routes_created = 0
        for route_data in routes_data:
            if not Route.query.filter_by(route_name=route_data['route_name']).first():
                route = Route(**route_data)
                db.session.add(route)
                routes_created += 1

        # Sample assignments for today
        from datetime import date
        today = date.today()

        assignments_data = [
            {'truck_id': 1, 'driver_id': 1, 'route_id': 1, 'assignment_date': today, 'start_time': time(8, 0)},
            {'truck_id': 2, 'driver_id': 2, 'route_id': 2, 'assignment_date': today, 'start_time': time(9, 30)},
            {'truck_id': 3, 'driver_id': 3, 'route_id': 3, 'assignment_date': today, 'start_time': time(10, 0)},
        ]

        assignments_created = 0
        for assignment_data in assignments_data:
            # Check if assignment already exists for today
            existing = Assignment.query.filter_by(
                truck_id=assignment_data['truck_id'],
                assignment_date=assignment_data['assignment_date']
            ).first()
            if not existing:
                assignment = Assignment(**assignment_data)
                db.session.add(assignment)
                assignments_created += 1

        db.session.commit()

        flash(f'Fleet data created: {drivers_created} drivers, {trucks_created} trucks, {routes_created} routes, {assignments_created} assignments', 'success')
        print(f"Fleet data: {drivers_created} drivers, {trucks_created} trucks, {routes_created} routes, {assignments_created} assignments")

    except Exception as e:
        db.session.rollback()
        import traceback
        error_details = traceback.format_exc()
        flash(f'Error creating fleet data: {str(e)}', 'error')
        print(f"Fleet data error: {str(e)}")
        print(f"Error details: {error_details}")

    return redirect(url_for('admin.truck_assignments'))

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
        'reports': [{'id': r.id, 'user_id': r.user_id, 'latitude': r.latitude, 'longitude': r.longitude, 'cluster_id': r.cluster_id} for r in reports[:5]]  # First 5 reports
    }

    return jsonify(debug_info)

@bp.route('/truck-assignments')
@login_required
@admin_required
def truck_assignments():
    """Truck assignment management page"""
    # Get all trucks with their current assignments
    trucks = Truck.query.all()
    drivers = Driver.query.all()
    routes = Route.query.all()

    # Get today's assignments
    from datetime import date
    today = date.today()
    today_assignments = Assignment.query.filter_by(assignment_date=today).all()

    # Restrict reports shown on the admin assignment map to Chennai only
    CHENNAI_MIN_LAT = 12.8
    CHENNAI_MAX_LAT = 13.4
    CHENNAI_MIN_LON = 80.0
    CHENNAI_MAX_LON = 80.6

    reports = WasteReport.query.filter(
        WasteReport.latitude.isnot(None),
        WasteReport.longitude.isnot(None),
        WasteReport.latitude >= CHENNAI_MIN_LAT,
        WasteReport.latitude <= CHENNAI_MAX_LAT,
        WasteReport.longitude >= CHENNAI_MIN_LON,
        WasteReport.longitude <= CHENNAI_MAX_LON
    ).all()

    # Calculate centroids for clusters
    centroids = []
    if reports:
        cluster_groups = defaultdict(list)
        for report in reports: 
            if report.cluster_id is not None:
                cluster_groups[report.cluster_id].append(report)

        for cluster_id, cluster_reports in cluster_groups.items():
            avg_lat = sum(r.latitude for r in cluster_reports) / len(cluster_reports)
            avg_lon = sum(r.longitude for r in cluster_reports) / len(cluster_reports)
            centroids.append({
                'cluster_id': cluster_id,
                'latitude': avg_lat,
                'longitude': avg_lon,
                'count': len(cluster_reports)
            })

    return render_template('admin/truck_assignments.html',
                         trucks=trucks,
                         drivers=drivers,
                         routes=routes,
                         today_assignments=today_assignments,
                         reports=reports,
                         centroids=centroids,
                         depot_lat=Config.DEPOT_LAT,
                         depot_lon=Config.DEPOT_LON)


@bp.route('/manage-trucks', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_trucks():
    if request.method == 'POST':
        truck_number = request.form.get('truck_number')
        capacity = request.form.get('capacity', type=float)
        truck_type = request.form.get('truck_type')
        driver_id = request.form.get('driver_id', type=int)
        if truck_number:
            truck = Truck(truck_number=truck_number, capacity=capacity or 0.0, truck_type=truck_type or '', driver_id=driver_id)
            db.session.add(truck)
            db.session.commit()
            flash('Truck created.', 'success')
        return redirect(url_for('admin.manage_trucks'))

    trucks = Truck.query.all()
    drivers = Driver.query.all()
    return render_template('admin/manage_trucks.html', trucks=trucks, drivers=drivers)


@bp.route('/manage-drivers', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_drivers():
    if request.method == 'POST':
        name = request.form.get('name')
        license_number = request.form.get('license_number')
        phone = request.form.get('phone')
        email = request.form.get('email')
        if name:
            driver = Driver(name=name, license_number=license_number or '', phone=phone or '', email=email or '')
            db.session.add(driver)
            db.session.commit()
            flash('Driver added.', 'success')
        return redirect(url_for('admin.manage_drivers'))

    drivers = Driver.query.all()
    return render_template('admin/manage_drivers.html', drivers=drivers)


@bp.route('/manage-routes', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_routes():
    if request.method == 'POST':
        route_name = request.form.get('route_name')
        description = request.form.get('description')
        distance_km = request.form.get('distance_km', type=float)
        est_duration = request.form.get('estimated_duration', type=int)
        stops = request.form.get('stops')
        if route_name:
            route = Route(route_name=route_name, description=description or '', distance_km=distance_km or 0.0, estimated_duration=est_duration or 0, stops=stops or '[]')
            db.session.add(route)
            db.session.commit()
            flash('Route created.', 'success')
        return redirect(url_for('admin.manage_routes'))

    routes = Route.query.all()
    return render_template('admin/manage_routes.html', routes=routes)


@bp.route('/optimize-routes', methods=['GET', 'POST'])
@login_required
@admin_required
def optimize_routes():
    if request.method == 'POST':
        k = request.form.get('k', type=int) or 5
        result = run_clustering(k=k)
        if result.get('success'):
            flash('Route optimization completed (clustering).', 'success')
        else:
            flash('Route optimization failed: ' + result.get('message', 'unknown'), 'error')
        return redirect(url_for('admin.optimize_routes'))

    # show a simple map limited to Chennai
    CHENNAI_MIN_LAT = 12.8
    CHENNAI_MAX_LAT = 13.4
    CHENNAI_MIN_LON = 80.0
    CHENNAI_MAX_LON = 80.6
    reports = WasteReport.query.filter(
        WasteReport.latitude.isnot(None),
        WasteReport.longitude.isnot(None),
        WasteReport.latitude >= CHENNAI_MIN_LAT,
        WasteReport.latitude <= CHENNAI_MAX_LAT,
        WasteReport.longitude >= CHENNAI_MIN_LON,
        WasteReport.longitude <= CHENNAI_MAX_LON
    ).all()

    return render_template('admin/optimize_routes.html', reports=reports, depot_lat=Config.DEPOT_LAT, depot_lon=Config.DEPOT_LON)

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
            'cluster_id': report.cluster_id,
            'description': report.description or '',
            'image_filename': report.image_filename,
            'user_name': report.user.name,
            'waste_score': float(report.waste_score) if report.waste_score is not None else None,
            'is_spam': bool(report.is_spam),
            'created_at': report.created_at.isoformat()
        })

    return jsonify(reports_data)

