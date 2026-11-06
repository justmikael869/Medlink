from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User, Facility, District
from datetime import datetime

auth_bp = Blueprint('auth', __name__)

FACILITY_TYPES = [
    ('government_clinic', 'Government Clinic / Hospital'),
    ('private_clinic', 'Private Clinic'),
    ('pharmacy', 'Pharmacy'),
    ('drug_shop', 'Drug Shop / Local Medicine Shop'),
    ('distributor', 'Distributor / Wholesaler'),
    ('manufacturer', 'Manufacturer / Supplier'),
    ('ngo_clinic', 'NGO / Mission Clinic'),
]

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    from flask_login import current_user
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        password = request.form.get('password','')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and user.active:
            login_user(user)
            user.last_login = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('dashboard.index'))
        flash('Invalid email or password.', 'danger')
    return render_template('auth/login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    districts = District.query.order_by(District.name).all()
    if request.method == 'POST':
        step = request.form.get('step','facility')

        if step == 'patient':
            # Patient — no facility needed
            email = request.form.get('email','').strip().lower()
            if User.query.filter_by(email=email).first():
                flash('Email already registered.', 'danger')
                return render_template('auth/register.html', districts=districts,
                                       facility_types=FACILITY_TYPES)
            u = User(name=request.form.get('name','').strip(),
                     email=email,
                     phone=request.form.get('phone','').strip(),
                     role='patient')
            u.set_password(request.form.get('password',''))
            db.session.add(u)
            db.session.commit()
            flash('Account created! You can now search for medicines near you.', 'success')
            return redirect(url_for('auth.login'))

        else:
            # Facility staff / admin
            email = request.form.get('email','').strip().lower()
            if User.query.filter_by(email=email).first():
                flash('Email already registered.', 'danger')
                return render_template('auth/register.html', districts=districts,
                                       facility_types=FACILITY_TYPES)

            facility_id = request.form.get('existing_facility_id')
            if not facility_id:
                # Create a new facility
                fac = Facility(
                    name = request.form.get('facility_name','').strip(),
                    facility_type = request.form.get('facility_type','pharmacy'),
                    level = request.form.get('level',''),
                    country = request.form.get('country','Uganda'),
                    district_id = int(request.form.get('district_id')) if request.form.get('district_id') else None,
                    address = request.form.get('address','').strip(),
                    phone = request.form.get('facility_phone','').strip(),
                    email = request.form.get('facility_email','').strip(),
                    licence_no = request.form.get('licence_no','').strip(),
                    latitude = float(request.form.get('latitude') or 0) or None,
                    longitude = float(request.form.get('longitude') or 0) or None,
                )
                db.session.add(fac)
                db.session.flush()
                facility_id = fac.id
                flash_fac = f'Facility "{fac.name}" registered and pending verification.'
            else:
                flash_fac = ''

            role = 'facility_admin' if not request.form.get('existing_facility_id') else 'staff'
            u = User(name=request.form.get('name','').strip(),
                     email=email,
                     phone=request.form.get('phone','').strip(),
                     role=role,
                     facility_id=int(facility_id))
            u.set_password(request.form.get('password',''))
            db.session.add(u)
            db.session.commit()
            if flash_fac:
                flash(flash_fac, 'info')
            flash('Account created! You can now manage your inventory.', 'success')
            return redirect(url_for('auth.login'))

    facilities = Facility.query.filter_by(active=True).order_by(Facility.name).all()
    return render_template('auth/register.html', districts=districts,
                           facility_types=FACILITY_TYPES, facilities=facilities)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@auth_bp.route('/register-driver', methods=['GET', 'POST'])
@login_required
def register_driver():
    """Upgrade current user account to driver role."""
    if request.method == 'POST':
        current_user.role = 'driver'
        current_user.vehicle_type = request.form.get('vehicle_type', 'boda')
        current_user.plate_number = request.form.get('plate_number', '').strip()
        current_user.has_cold_box = request.form.get('has_cold_box') == 'yes'
        current_user.verified_driver = False
        db.session.commit()
        flash('Driver profile submitted. An admin will verify your details shortly.', 'info')
        return redirect(url_for('dashboard.index'))
    return render_template('auth/register_driver.html')


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC REGISTRATION LANDING PAGE
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route('/register/choose')
def register_choose():
    """Landing page to pick the type of account to register."""
    return render_template('auth/register_choose.html')


# ─────────────────────────────────────────────────────────────────────────────
# REGISTER AS DELIVERY COMPANY (pending admin approval)
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route('/register/delivery-company', methods=['GET', 'POST'])
def register_delivery_company():
    from app.models import DeliveryCompany
    districts = District.query.order_by(District.name).all()

    if request.method == 'POST':
        name = request.form.get('company_name', '').strip()
        contact_email = request.form.get('contact_email', '').strip().lower()
        contact_phone = request.form.get('contact_phone', '').strip()
        districts_str = ','.join(request.form.getlist('coverage_districts'))
        has_cold = request.form.get('has_cold_chain') == 'on'
        manager_name = request.form.get('manager_name', '').strip()
        manager_email = request.form.get('manager_email', '').strip().lower()
        manager_pwd = request.form.get('password', '')

        if not name or not contact_email or not manager_email or not manager_pwd:
            flash('Company name, contact email, manager email and password are required.', 'danger')
            return render_template('auth/register_delivery_company.html', districts=districts)

        if User.query.filter_by(email=manager_email).first():
            flash('That manager email is already registered.', 'danger')
            return render_template('auth/register_delivery_company.html', districts=districts)

        # Create company (unverified — pending admin approval)
        company = DeliveryCompany(
            name = name,
            contact_email = contact_email,
            contact_phone = contact_phone,
            coverage_districts = districts_str,
            verified = False,
            active = True,
        )
        db.session.add(company)
        db.session.flush()

        # Create manager account
        manager = User(
            name = manager_name or name + ' Manager',
            email = manager_email,
            phone = contact_phone,
            role = 'driver', # will show as company_manager once verified
            delivery_company_id = company.id,
            active = True,
        )
        manager.set_password(manager_pwd)
        db.session.add(manager)
        db.session.commit()

        flash('Your delivery company application has been submitted. '
              'The system admin will review and verify your details. '
              'You will be notified by email once approved.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register_delivery_company.html', districts=districts)


# ─────────────────────────────────────────────────────────────────────────────
# REGISTER AS FACILITY (hospital, clinic, pharmacy, distributor)
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route('/register/facility', methods=['GET', 'POST'])
def register_facility():
    districts = District.query.order_by(District.name).all()

    FACILITY_REGISTER_TYPES = [
        ('government_clinic', 'Government Clinic / Hospital'),
        ('private_clinic', 'Private Hospital / Clinic'),
        ('pharmacy', 'Pharmacy'),
        ('drug_shop', 'Drug Shop'),
        ('distributor', 'Distributor / Wholesaler'),
        ('manufacturer', 'Manufacturer / Supplier'),
        ('ngo_clinic', 'NGO / Mission Hospital'),
        ('laboratory', 'Laboratory'),
    ]

    if request.method == 'POST':
        fac_name = request.form.get('facility_name', '').strip()
        fac_type = request.form.get('facility_type', 'private_clinic')
        district_id = request.form.get('district_id')
        address = request.form.get('address', '').strip()
        fac_phone = request.form.get('facility_phone', '').strip()
        fac_email = request.form.get('facility_email', '').strip().lower()
        licence_no = request.form.get('licence_no', '').strip()
        latitude = float(request.form.get('latitude') or 0) or None
        longitude = float(request.form.get('longitude') or 0) or None

        admin_name = request.form.get('admin_name', '').strip()
        admin_email = request.form.get('admin_email', '').strip().lower()
        admin_phone = request.form.get('admin_phone', '').strip()
        admin_pwd = request.form.get('password', '')

        if not fac_name or not admin_email or not admin_pwd:
            flash('Facility name, admin email and password are required.', 'danger')
            return render_template('auth/register_facility.html',
                                   districts=districts, facility_types=FACILITY_REGISTER_TYPES)

        if User.query.filter_by(email=admin_email).first():
            flash('That email is already registered.', 'danger')
            return render_template('auth/register_facility.html',
                                   districts=districts, facility_types=FACILITY_REGISTER_TYPES)

        is_supplier = fac_type in ('distributor', 'manufacturer')

        fac = Facility(
            name = fac_name,
            facility_type = fac_type,
            district_id = int(district_id) if district_id else None,
            address = address,
            phone = fac_phone,
            email = fac_email,
            licence_no = licence_no,
            latitude = latitude,
            longitude = longitude,
            verified = False, # pending admin approval
            active = True,
            is_supplier = is_supplier,
        )
        db.session.add(fac)
        db.session.flush()

        admin_user = User(
            name = admin_name or fac_name + ' Admin',
            email = admin_email,
            phone = admin_phone,
            role = 'facility_admin',
            facility_id = fac.id,
            active = True,
        )
        admin_user.set_password(admin_pwd)
        db.session.add(admin_user)
        db.session.commit()

        flash(f'"{fac_name}" has been registered and is pending verification by the system admin. '
              f'You can log in now and set up your profile while awaiting approval.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register_facility.html',
                           districts=districts, facility_types=FACILITY_REGISTER_TYPES)


# ─────────────────────────────────────────────────────────────────────────────
# REGISTER AS INDIVIDUAL DOCTOR / HEALTHCARE WORKER
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route('/register/doctor', methods=['GET', 'POST'])
def register_doctor():
    districts = District.query.order_by(District.name).all()
    facilities = Facility.query.filter_by(active=True).order_by(Facility.name).all()

    SPECIALISATIONS = [
        'General Practice', 'Internal Medicine', 'Paediatrics', 'Obstetrics & Gynaecology',
        'Surgery', 'Orthopaedics', 'Ophthalmology', 'ENT', 'Dermatology', 'Psychiatry',
        'Oncology', 'Cardiology', 'Neurology', 'Pulmonology', 'Nephrology',
        'Gastroenterology', 'Endocrinology', 'Emergency Medicine', 'Anaesthesiology',
        'Radiology', 'Pathology', 'Public Health', 'Dentistry', 'Pharmacy', 'Nursing',
    ]

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'doctor') # doctor, nurse, pharmacist
        umdpc = request.form.get('umdpc_number', '').strip()
        specialisation= request.form.get('specialisation', '').strip()
        district_id = request.form.get('district_id')
        facility_id = request.form.get('facility_id') or None
        fee_ugx = float(request.form.get('consultation_fee_ugx') or 0) or None

        if not name or not email or not password:
            flash('Name, email, and password are required.', 'danger')
            return render_template('auth/register_doctor.html',
                                   districts=districts, facilities=facilities,
                                   specialisations=SPECIALISATIONS)

        if User.query.filter_by(email=email).first():
            flash('That email is already registered.', 'danger')
            return render_template('auth/register_doctor.html',
                                   districts=districts, facilities=facilities,
                                   specialisations=SPECIALISATIONS)

        u = User(
            name = name,
            email = email,
            phone = phone,
            role = role,
            district_id = int(district_id) if district_id else None,
            facility_id = int(facility_id) if facility_id else None,
            umdpc_number = umdpc,
            specialisation = specialisation,
            consultation_fee_ugx = fee_ugx,
            verified_doctor = False, # pending admin approval
            active = True,
        )
        u.set_password(password)
        db.session.add(u)
        db.session.commit()

        flash('Your account has been created. A system admin will verify your '
              'professional credentials shortly. You can log in now.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register_doctor.html',
                           districts=districts, facilities=facilities,
                           specialisations=SPECIALISATIONS)
