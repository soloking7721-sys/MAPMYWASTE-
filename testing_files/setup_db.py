#!/usr/bin/env python 
"""Direct database verification and creation"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
# Import all models to register them with SQLAlchemy
from app.models import User, WasteReport, ContactMessage

# Create app
app = create_app()

# Enable SQL echo to see what's happening 
app.config['SQLALCHEMY_ECHO'] = True

with app.app_context():
    print("Creating all tables...")
    db.create_all()
    print("Done!")
    
    # Now check tables
    import sqlite3
    con = sqlite3.connect('mapmywaste.db')
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [r[0] for r in cur.fetchall()]
    print(f"Tables created: {tables}")
    
    for table in tables:
        cur.execute(f"PRAGMA table_info({table});")
        cols = [r[1] for r in cur.fetchall()]
        print(f"  {table:20} -> {cols}")
    
    con.close()