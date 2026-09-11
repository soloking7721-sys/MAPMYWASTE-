import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Database configuration
    database_url = os.environ.get('DATABASE_URL')
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    SQLALCHEMY_DATABASE_URI = database_url or 'sqlite:///mapmywaste.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    
    # Clustering settings
    DEFAULT_CLUSTERS = 5 
    MIN_REPORTS_PER_CLUSTER = 10
    
    # Gamification settings
    POINTS_PER_REPORT = 10
    BONUS_POINTS_FIRST_REPORT = 20
    BONUS_POINTS_5_REPORTS = 50
    BONUS_POINTS_20_REPORTS = 100
    
    # Badge thresholds
    BADGE_ROOKIE_REPORTER = 1
    BADGE_NEIGHBORHOOD_WATCHER = 5
    BADGE_WASTE_WARRIOR = 20
    
    # Admin depot location for route links
    DEPOT_LAT = 13.0827  # Chennai depot coordinates
    DEPOT_LON = 80.2707