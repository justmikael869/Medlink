"""
MedLink — Create / Reset Demo Accounts (PostgreSQL / any SQLAlchemy DB)
Safe to run multiple times — will not create duplicates.

Usage: python create_demo_accounts.py   (with DATABASE_URL set)
"""
import os, sys, random

# ── Now use Flask/SQLAlchemy to create demo accounts ─────────────────────────
from app import create_app, db
app = create_app()

with app.app_context():
    from app.models import (User, Facility, District, DeliveryCompany,
                            SupplierCatalogue, Medicine)
    from werkzeug.security import generate_password_hash

    # ── 1. Delivery Company ───────────────────────────────────────────────────
    co = DeliveryCompany.query.filter_by(name='SafeRide Medical Deliveries').first()
    if not co:
        co = DeliveryCompany(
            name='SafeRide Medical Deliveries',
            contact_phone='+256702000001',
            contact_email='dispatch@saferide.ug',
            verified=True, active=True,
        )
        db.session.add(co)
        db.session.flush()
        print(f" Created delivery company: SafeRide Medical Deliveries (id={co.id})")
    else:
        co.verified = True
        print(f" Delivery company exists: SafeRide (id={co.id})")

    # ── 2. Delivery Company Manager account ───────────────────────────────────
    manager = User.query.filter_by(email='manager@saferide.ug').first()
    if not manager:
        manager = User(
            name='SafeRide Manager',
            email='manager@saferide.ug',
            phone='+256702000010',
            role='driver',
            delivery_company_id=co.id,
            active=True,
            wallet_balance_ugx=0.0,
        )
        manager.set_password('saferide123')
        db.session.add(manager)
        print(" Created: manager@saferide.ug / saferide123")
    else:
        manager.delivery_company_id = co.id
        manager.role = 'driver'
        manager.active = True
        manager.set_password('saferide123')
        print(" Updated: manager@saferide.ug")

    # ── 3. Link existing drivers to SafeRide ──────────────────────────────────
    for email in ['ali@driver.ug', 'hassan@driver.ug']:
        d = User.query.filter_by(email=email).first()
        if d:
            d.delivery_company_id = co.id
            d.verified_driver = True
            d.is_available = True
    print(" Drivers linked to SafeRide")

    # ── 4. Ensure Quality Chemicals facility exists ───────────────────────────
    qc = Facility.query.filter(Facility.name.ilike('%Quality Chemicals%')).first()
    if not qc:
        kampala = District.query.filter_by(name='Kampala').first()
        qc = Facility(
            name='Quality Chemicals Distributor',
            facility_type='distributor',
            district=kampala,
            address='Plot 49-51, Industrial Area, Kampala',
            phone='+256414320000',
            email='orders@qcl.ug',
            latitude=0.3089, longitude=32.5634,
            verified=True, active=True,
            is_supplier=True, supplier_type='national',
            lead_time_days=3, min_order_ugx=500000,
        )
        db.session.add(qc)
        db.session.flush()
        print(f" Created facility: Quality Chemicals Distributor (id={qc.id})")
    else:
        qc.is_supplier = True
        qc.supplier_type = 'national'
        qc.verified = True
        print(f" Facility exists: Quality Chemicals (id={qc.id})")

    # ── 5. Distributor user account ───────────────────────────────────────────
    dist = User.query.filter_by(email='distributor@qcl.ug').first()
    if not dist:
        dist = User(
            name='Quality Chemicals Ltd',
            email='distributor@qcl.ug',
            phone='+256414320001',
            role='supplier',
            facility_id=qc.id,
            active=True,
            wallet_balance_ugx=0.0,
        )
        dist.set_password('dist123')
        db.session.add(dist)
        print(" Created: distributor@qcl.ug / dist123")
    else:
        dist.role = 'supplier'
        dist.facility_id = qc.id
        dist.active = True
        dist.set_password('dist123')
        print(" Updated: distributor@qcl.ug")

    # ── 6. Populate Quality Chemicals catalogue ───────────────────────────────
    medicines = Medicine.query.all()
    cat_added = 0
    for med in medicines:
        exists = SupplierCatalogue.query.filter_by(
            supplier_id=qc.id, medicine_id=med.id).first()
        if not exists:
            import random as _r
            db.session.add(SupplierCatalogue(
                supplier_id=qc.id,
                medicine_id=med.id,
                unit_price_ugx=round(_r.uniform(800, 18000) / 100) * 100,
                min_order_qty=_r.choice([10, 20, 50, 100]),
                lead_time_days=_r.choice([2, 3, 5, 7]),
                in_stock=_r.random() > 0.15,
            ))
            cat_added += 1
    if cat_added:
        print(f" Added {cat_added} medicines to QC catalogue")

    # ── 7. MedPharm also a distributor ───────────────────────────────────────
    medpharm = Facility.query.filter(Facility.name.ilike('%MedPharm%')).first()
    if medpharm:
        medpharm.is_supplier = True
        medpharm.supplier_type = 'regional'
        medpharm.lead_time_days = 1
        medpharm.min_order_ugx = 50000
        ph_user = User.query.filter_by(email='pharm@medlink.ug').first()
        if ph_user:
            ph_user.role = 'pharmacist'
            ph_user.facility_id = medpharm.id
        print(" MedPharm marked as regional distributor")

    # ── 8. Demo drivers ───────────────────────────────────────────────────────
    drivers_data = [
        ('Ali Boda','ali@driver.ug','driver123','+256702222001','boda','UAA 231B',False),
        ('Hassan Van','hassan@driver.ug','driver123','+256702222002','van','UAB 444K',True),
    ]
    for name,email,pw,phone,vtype,plate,cold in drivers_data:
        d = User.query.filter_by(email=email).first()
        if not d:
            d = User(name=name, email=email, phone=phone, role='driver',
                     vehicle_type=vtype, plate_number=plate,
                     has_cold_box=cold, verified_driver=True,
                     is_available=True, wallet_balance_ugx=0.0,
                     delivery_company_id=co.id)
            d.set_password(pw)
            db.session.add(d)
            print(f" Created driver: {email}")
        else:
            d.delivery_company_id = co.id
            d.verified_driver = True
            d.set_password(pw)

    db.session.commit()
    print()
    print("=" * 58)
    print(" Demo accounts ready:")
    print("=" * 58)
    print()
    print(" SYSTEM ADMIN")
    print(" admin@medlink.ug / admin123")
    print()
    print(" DISTRICT OFFICER")
    print(" district@medlink.ug / admin123")
    print()
    print(" FACILITY ADMIN (Mulago Hospital)")
    print(" doctor@medlink.ug / admin123")
    print()
    print(" FACILITY STAFF / NURSE (Mulago)")
    print(" nurse@medlink.ug / admin123")
    print()
    print(" PHARMACIST (MedPharm — also distributes)")
    print(" pharm@medlink.ug / admin123")
    print()
    print(" PATIENT")
    print(" patient@medlink.ug / medlink123")
    print()
    print(" DOCTORS")
    print(" sarah@medlink.ug / doctor123 (General Practice)")
    print(" james@medlink.ug / doctor123 (Paediatrics)")
    print(" grace@medlink.ug / doctor123 (OB/GYN)")
    print(" moses@medlink.ug / doctor123 (HIV/Infectious Disease)")
    print()
    print(" DISTRIBUTOR (Quality Chemicals Ltd)")
    print(" distributor@qcl.ug / dist123")
    print()
    print(" DELIVERY COMPANY MANAGER (SafeRide)")
    print(" manager@saferide.ug / saferide123")
    print()
    print(" DRIVERS (SafeRide)")
    print(" ali@driver.ug / driver123 (Boda)")
    print(" hassan@driver.ug / driver123 (Van, Cold Chain)")
    print()
    print(" Run: python run.py")
    print("=" * 58)
