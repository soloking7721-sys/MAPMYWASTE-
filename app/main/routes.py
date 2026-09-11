from flask import render_template, redirect, url_for, flash, request, jsonify, send_from_directory
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.main import bp
from app.models import User, WasteReport, ContactMessage
from app import db
from app.services.exif_utils import extract_gps_from_image
from app.services.detector import predict, image_md5
from app.services.gamification import update_user_achievements
from app.services import storage
from config import Config
import os
import random
from datetime import datetime

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

@bp.route('/')
def index():
    # Redirect authenticated users to appropriate dashboard
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        else:
            return redirect(url_for('main.dashboard'))

    # Get top users for leaderboard widget
    top_users = User.query.order_by(User.points.desc(), User.reports_count.desc()).limit(5).all()
    return render_template('main/index.html', top_users=top_users)

@bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        # Check if file is present
        if 'image' not in request.files:
            flash('No image file provided.', 'error')
            return redirect(url_for('main.upload'))
        
        file = request.files['image']
        if file.filename == '':
            flash('No file selected.', 'error')
            return redirect(url_for('main.upload'))
        
        if not allowed_file(file.filename):
            flash('Invalid file type. Allowed: PNG, JPG, JPEG, GIF, WEBP', 'error')
            return redirect(url_for('main.upload'))
        
        # Save file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = secure_filename(file.filename)
        filename = f"{current_user.id}_{timestamp}_{filename}"
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), Config.UPLOAD_FOLDER)
        os.makedirs(upload_dir, exist_ok=True)
        upload_path = os.path.join(upload_dir, filename)
        file.save(upload_path)
        storage.upload_file(upload_path, filename)

        # Get form data
        description = request.form.get('description', '').strip()
        latitude = request.form.get('latitude', type=float)
        longitude = request.form.get('longitude', type=float)
        location_source = 'MANUAL'
        
        # Try to extract GPS from EXIF
        lat_exif, lon_exif = extract_gps_from_image(upload_path)
        if lat_exif is not None and lon_exif is not None:
            latitude = lat_exif
            longitude = lon_exif
            location_source = 'EXIF'
        elif latitude is None or longitude is None:
            # Default to Chennai depot coords when no coordinates provided
            latitude = Config.DEPOT_LAT
            longitude = Config.DEPOT_LON
            location_source = 'DEFAULT_CHENNAI'
        else:
            location_source = 'BROWSER'
        
        # Compute image hash and run detector
        image_path = upload_path
        img_hash = image_md5(image_path)
        score = predict(image_path)
        
        # Extract original filename for duplicate checking
        original_filename = secure_filename(file.filename)

        # Check duplicate by hash
        existing_by_hash = WasteReport.query.filter_by(image_hash=img_hash).first()
        
        # Check duplicate by original filename
        existing_by_filename = WasteReport.query.filter(
            WasteReport.image_filename.like(f"%{original_filename}%")
        ).first()
        
        is_spam = False
        is_filename_duplicate = False
        
        if existing_by_hash:
            is_spam = True
            flash('Duplicate image detected (same content). This has been reported to admins as spam.', 'error')
        
        if existing_by_filename:
            is_spam = True
            is_filename_duplicate = True
            flash('Duplicate filename detected. This has been reported to admins as spam.', 'warning')

        # Create waste report
        report = WasteReport(
            user_id=current_user.id,
            image_filename=filename,
            image_hash=img_hash,
            waste_score=score,
            is_spam=is_spam,
            description=description,
            latitude=latitude,
            longitude=longitude,
            location_source=location_source
        )
        db.session.add(report)
        
        # Update user stats
        current_user.reports_count += 1
        current_user.add_points(Config.POINTS_PER_REPORT)
        
        # Update achievements
        badges_before = set(current_user.get_badges())
        new_badges = update_user_achievements(current_user)
        badges_after = set(current_user.get_badges())
        newly_earned = list(badges_after - badges_before)
        
        db.session.commit()
        
        # Store newly earned badges in session for result page
        from flask import session
        session['newly_earned_badges'] = newly_earned
        session['is_duplicate'] = is_filename_duplicate or bool(existing_by_hash)
        session['duplicate_type'] = 'filename' if is_filename_duplicate else ('hash' if existing_by_hash else None)

        
        # Redirect to result page with report ID
        return redirect(url_for('main.report_result', report_id=report.id))
    
    return render_template('main/upload.html')

@bp.route('/dashboard')
@login_required
def dashboard():
    """User dashboard with overview"""
    recent_reports = WasteReport.query.filter_by(user_id=current_user.id)\
        .order_by(WasteReport.created_at.desc()).limit(5).all()
    all_users = User.query.order_by(User.points.desc(), User.reports_count.desc()).all()
    return render_template('main/dashboard.html', recent_reports=recent_reports, all_users=all_users)

@bp.route('/profile')
@login_required
def profile():
    recent_reports = WasteReport.query.filter_by(user_id=current_user.id)\
        .order_by(WasteReport.created_at.desc()).limit(5).all()
    return render_template('main/profile.html', recent_reports=recent_reports)

@bp.route('/reports/my')
@login_required
def my_reports():
    reports = WasteReport.query.filter_by(user_id=current_user.id)\
        .order_by(WasteReport.created_at.desc()).all()
    return render_template('main/my_reports.html', reports=reports)

@bp.route('/leaderboard')
def leaderboard():
    users = User.query.order_by(User.points.desc(), User.reports_count.desc()).all()
    return render_template('main/leaderboard.html', users=users)

@bp.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()

        if not name or not email or not message:
            flash('All fields are required.', 'error')
            return render_template('main/contact.html')

        contact_msg = ContactMessage(name=name, email=email, subject=subject, message=message)
        db.session.add(contact_msg)
        db.session.commit()

        flash('Thank you for your message! We will get back to you soon.', 'success')
        return redirect(url_for('main.contact'))

    return render_template('main/contact.html')

@bp.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded images: redirect to Supabase Storage when configured
    (Render Free's local disk is ephemeral), else serve from local disk."""
    if storage.is_configured():
        return redirect(storage.get_public_url(filename))
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), Config.UPLOAD_FOLDER)
    return send_from_directory(upload_dir, filename)


@bp.route('/health')
def health():
    """Lightweight health check for Render — no auth, no DB access."""
    return {'status': 'ok'}, 200

@bp.route('/images/<filename>')
def images(filename):
    """Serve static images like hero image"""
    images_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'images')
    return send_from_directory(images_dir, filename)

@bp.route('/report/<int:report_id>/result')
@login_required
def report_result(report_id):
    """Show result page after successful report submission"""
    report = WasteReport.query.get_or_404(report_id)
    
    # Verify the report belongs to the current user
    if report.user_id != current_user.id:
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))
    
    # Sample Tamil Nadu addresses for display
    tamil_nadu_addresses = [
        "Anna Nagar, Chennai, Tamil Nadu 600040",
        "T. Nagar, Chennai, Tamil Nadu 600017",
        "Adyar, Chennai, Tamil Nadu 600020",
        "Velachery, Chennai, Tamil Nadu 600042",
        "Porur, Chennai, Tamil Nadu 600116",
        "Tambaram, Chennai, Tamil Nadu 600045",
        "Coimbatore, Tamil Nadu 641001",
        "Madurai, Tamil Nadu 625001",
        "Trichy, Tamil Nadu 620001",
        "Salem, Tamil Nadu 636001"
    ]
    
    # Generate a sample address based on coordinates (for demo)
    sample_address = random.choice(tamil_nadu_addresses)
    
    # Get newly earned badges from session
    from flask import session
    newly_earned_badges = session.pop('newly_earned_badges', [])
    is_duplicate = session.pop('is_duplicate', False)
    duplicate_type = session.pop('duplicate_type', None)
    
    return render_template('main/report_result.html', 
                         report=report, 
                         sample_address=sample_address,
                         badges=newly_earned_badges,
                         is_duplicate=is_duplicate,
                         duplicate_type=duplicate_type)
