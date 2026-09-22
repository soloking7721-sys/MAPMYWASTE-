from app import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import json

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user', nullable=False)
    points = db.Column(db.Integer, default=0, nullable=False)
    reports_count = db.Column(db.Integer, default=0, nullable=False)
    tasks_completed = db.Column(db.Integer, default=0, nullable=False)
    badges = db.Column(db.Text, default='[]')  # JSON array of badge names
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationship
    reports = db.relationship('WasteReport', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def get_badges(self):
        try:
            return json.loads(self.badges) if self.badges else []
        except:
            return []
    
    def add_badge(self, badge_name):
        badges = self.get_badges()
        if badge_name not in badges:
            badges.append(badge_name)
            self.badges = json.dumps(badges)
            return True
        return False
    
    def add_points(self, points):
        self.points += points
    
    def __repr__(self):
        return f'<User {self.email}>'


class WasteReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    image_filename = db.Column(db.String(255), nullable=False)
    image_hash = db.Column(db.String(64), nullable=True, index=True)
    description = db.Column(db.Text)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    location_source = db.Column(db.String(20), nullable=False)  # EXIF, BROWSER, MANUAL
    address = db.Column(db.String(255))
    waste_score = db.Column(db.Float, nullable=True)
    is_spam = db.Column(db.Boolean, default=False, nullable=False)
    cluster_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<WasteReport {self.id} by {self.user_id}>'


class ContactMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(200), nullable=True)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<ContactMessage {self.id} from {self.email}>'