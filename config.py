import os


def _is_production():
    """Production = explicit ENVIRONMENT=production, or Render's own auto-injected RENDER=true."""
    if os.environ.get('ENVIRONMENT', '').strip().lower() == 'production':
        return True
    if os.environ.get('RENDER', '').strip().lower() == 'true':
        return True
    return False


class Config:
    IS_PRODUCTION = _is_production()

    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        if IS_PRODUCTION:
            raise RuntimeError(
                "SECRET_KEY is not set. Set it in the Render dashboard environment variables."
            )
        SECRET_KEY = 'dev-secret-key-change-in-production'

    # Database configuration
    database_url = os.environ.get('DATABASE_URL')
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    if not database_url:
        if IS_PRODUCTION:
            raise RuntimeError(
                "DATABASE_URL is not set. Set it in the Render dashboard to the Supabase "
                "Postgres connection string — production must not fall back to SQLite."
            )
        database_url = 'sqlite:///mapmywaste.db'

    SQLALCHEMY_DATABASE_URI = database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

    # Supabase Storage (user-uploaded waste-report photos only)
    SUPABASE_URL = os.environ.get('SUPABASE_URL')
    SUPABASE_PUBLISHABLE_KEY = os.environ.get('SUPABASE_PUBLISHABLE_KEY')
    SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', 'waste-images')
    
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