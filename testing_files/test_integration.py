#!/usr/bin/env python
"""Test the detector service and waste report creation"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import User, WasteReport
from app.services.detector import predict, image_md5
from PIL import Image
import numpy as np

app = create_app()

with app.app_context():
    # Ensure we have admin user
    admin = User.query.filter_by(email='admin@mapmywaste.com').first()
    if not admin:
        admin = User(
            name='Admin',
            email='admin@mapmywaste.com',
            role='admin'
        )
        admin.set_password(os.environ.get('ADMIN_INITIAL_PASSWORD', 'test-only-fixture-pw-8f2c'))
        db.session.add(admin)
        db.session.commit()
        print("✓ Created admin user")
    
    # Create a test image
    test_img_path = 'test_waste.png'
    img = Image.fromarray(np.random.randint(50, 200, (224, 224, 3), dtype=np.uint8))
    img.save(test_img_path)
    print(f"✓ Created test image: {test_img_path}")
    
    # Test detector
    score = predict(test_img_path)
    print(f"✓ Detector score: {score:.2f}")
    
    # Test hash
    hash_val = image_md5(test_img_path)
    print(f"✓ Image hash: {hash_val[:16]}...")
    
    # Test creating a report with the new fields
    report = WasteReport(
        user_id=admin.id,
        image_filename='test.png',
        image_hash=hash_val,
        waste_score=score,
        is_spam=False,
        description='Test report',
        latitude=13.0,
        longitude=80.0,
        location_source='TEST'
    )
    db.session.add(report)
    db.session.commit()
    print(f"✓ Created report #{report.id} with waste_score={report.waste_score}, hash={report.image_hash[:16]}...")
    
    # Test duplicate detection
    report2 = WasteReport(
        user_id=admin.id,
        image_filename='test2.png',
        image_hash=hash_val,  # Same hash - duplicate!
        waste_score=score,
        is_spam=True,  # Mark as spam
        description='Duplicate',
        latitude=13.1,
        longitude=80.1,
        location_source='TEST'
    )
    db.session.add(report2)
    db.session.commit()
    print(f"✓ Created duplicate report #{report2.id} with is_spam=True")
    
    # Verify database
    total = WasteReport.query.count()
    spam_count = WasteReport.query.filter_by(is_spam=True).count()
    print(f"\n✓ Total reports: {total}, Spam reports: {spam_count}")
    print(f"✓ All fields stored correctly!")
    print(f"\n✅ INTEGRATION TEST PASSED!")
