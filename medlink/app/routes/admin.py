from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.models import Facility, Medicine, User, District, StockTransaction, Notification
from datetime import datetime

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.role != 'system_admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated

@admin_bp.route('/facilities')
@login_required
@admin_required
def facilities():
    fs = Facility.query.order_by(Facility.facility_type, Facility.name).all()
    return render_template('admin/facilities.html', facilities=fs)

@admin_bp.route('/facilities/<int:fid>/verify', methods=['POST'])
@login_required
@admin_required
def verify_facility(fid):
    f = Facility.query.get_or_404(fid)
    f.verified = not f.verified
    db.session.commit()
    flash(f'{"Verified" if f.verified else "Unverified"}: {f.name}', 'success')
    return redirect(url_for('admin.facilities'))

# medicines route moved to bottom of file

@admin_bp.route('/users')
@login_required
@admin_required
def users():
    us = User.query.order_by(User.role, User.name).all()
    return render_template('admin/users.html', users=us)


# ── Doctor verification ───────────────────────────────────────────────────────

@admin_bp.route('/doctors')
@login_required
def doctors():
    if current_user.role != 'system_admin':
        flash('Admin only.', 'danger')
        return redirect(url_for('dashboard.index'))
    docs = User.query.filter_by(role='doctor').order_by(User.created_at.desc()).all()
    return render_template('admin/doctors.html', doctors=docs)


@admin_bp.route('/doctors/<int:user_id>/verify', methods=['POST'])
@login_required
def verify_doctor(user_id):
    if current_user.role != 'system_admin':
        flash('Admin only.', 'danger')
        return redirect(url_for('admin.doctors'))
    doc = User.query.get_or_404(user_id)
    doc.verified_doctor = not doc.verified_doctor
    db.session.commit()
    flash(f'Dr {doc.name} {"verified" if doc.verified_doctor else "unverified"}.', 'success')
    return redirect(url_for('admin.doctors'))


@admin_bp.route('/drivers')
@login_required
def drivers():
    if current_user.role != 'system_admin':
        flash('Admin only.', 'danger')
        return redirect(url_for('dashboard.index'))
    drvs = User.query.filter_by(role='driver').order_by(User.created_at.desc()).all()
    return render_template('admin/drivers.html', drivers=drvs)


@admin_bp.route('/drivers/<int:user_id>/verify', methods=['POST'])
@login_required
def verify_driver(user_id):
    if current_user.role != 'system_admin':
        flash('Admin only.', 'danger')
        return redirect(url_for('admin.drivers'))
    drv = User.query.get_or_404(user_id)
    drv.verified_driver = not drv.verified_driver
    db.session.commit()
    flash(f'Driver {drv.name} {"verified" if drv.verified_driver else "unverified"}.', 'success')
    return redirect(url_for('admin.drivers'))


# ─────────────────────────────────────────────────────────────────────────────
# FACILITY STAFF MANAGEMENT (for facility_admin role)
# ─────────────────────────────────────────────────────────────────────────────

def facility_admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.role not in ('facility_admin', 'system_admin'):
            flash('Facility admin access required.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/facility/staff')
@login_required
@facility_admin_required
def facility_staff():
    """Facility admin sees all staff in their facility."""
    if current_user.role == 'system_admin':
        # System admin can pick any facility
        fid = request.args.get('facility_id', type=int)
        facility = Facility.query.get(fid) if fid else None
        facilities = Facility.query.filter_by(active=True).order_by(Facility.name).all()
        staff = User.query.filter_by(facility_id=fid).order_by(User.role, User.name).all() if fid else []
    else:
        fid = current_user.facility_id
        facility = current_user.facility
        facilities = None
        staff = User.query.filter_by(facility_id=fid).order_by(User.role, User.name).all()

    return render_template('admin/facility_staff.html',
                           staff=staff, facility=facility,
                           facilities=facilities, selected_fid=fid)


@admin_bp.route('/facility/staff/add', methods=['GET', 'POST'])
@login_required
@facility_admin_required
def add_staff():
    """Add a new staff member to the facility."""
    facility = current_user.facility
    if current_user.role == 'system_admin':
        fid = request.args.get('facility_id', type=int) or request.form.get('facility_id', type=int)
        facility = Facility.query.get(fid) if fid else None
    else:
        fid = current_user.facility_id

    facilities = Facility.query.filter_by(active=True).order_by(Facility.name).all() \
        if current_user.role == 'system_admin' else None

    STAFF_ROLES = [
        ('staff', 'General Staff / Nurse'),
        ('pharmacist', 'Pharmacist'),
        ('facility_admin', 'Facility Administrator'),
        ('doctor', 'Doctor (requires UMDPC verification)'),
        ('supplier', 'Supplier / Procurement Officer'),
    ]

    if request.method == 'POST':
        fid = fid or request.form.get('facility_id', type=int)
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        role = request.form.get('role', 'staff')
        pw = request.form.get('password', '').strip()

        if not all([name, email, pw, fid]):
            flash('Name, email, password and facility are required.', 'danger')
            return redirect(request.url)

        if User.query.filter_by(email=email).first():
            flash(f'Email {email} is already registered.', 'danger')
            return redirect(request.url)

        u = User(
            name=name, email=email, phone=phone,
            role=role, facility_id=fid, active=True,
        )
        u.set_password(pw)

        # If adding a doctor, mark as needing UMDPC verification
        if role == 'doctor':
            u.verified_doctor = False
            u.umdpc_number = request.form.get('umdpc_number', '').strip()
            u.specialisation = request.form.get('specialisation', '').strip()

        db.session.add(u)
        db.session.commit()
        flash(f'{name} added as {dict(STAFF_ROLES).get(role, role)} successfully.', 'success')
        return redirect(url_for('admin.facility_staff'))

    return render_template('admin/add_staff.html',
                           facility=facility, facilities=facilities,
                           STAFF_ROLES=STAFF_ROLES, selected_fid=fid)


@admin_bp.route('/facility/staff/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@facility_admin_required
def edit_staff(user_id):
    u = User.query.get_or_404(user_id)
    # Ensure the facility admin can only edit staff in their own facility
    if current_user.role == 'facility_admin' and u.facility_id != current_user.facility_id:
        flash('You can only manage staff in your own facility.', 'danger')
        return redirect(url_for('admin.facility_staff'))

    STAFF_ROLES = [
        ('staff', 'General Staff / Nurse'),
        ('pharmacist', 'Pharmacist'),
        ('facility_admin', 'Facility Administrator'),
        ('doctor', 'Doctor'),
        ('supplier', 'Supplier / Procurement Officer'),
    ]

    if request.method == 'POST':
        u.name = request.form.get('name', u.name).strip()
        u.phone = request.form.get('phone', '').strip()
        u.role = request.form.get('role', u.role)
        u.active = request.form.get('active') == 'on'

        new_pw = request.form.get('new_password', '').strip()
        if new_pw:
            u.set_password(new_pw)

        if u.role == 'doctor':
            u.umdpc_number = request.form.get('umdpc_number', '').strip()
            u.specialisation = request.form.get('specialisation', '').strip()
            u.consultation_fee_ugx = float(request.form.get('fee', 0) or 0)

        db.session.commit()
        flash(f'{u.name} updated.', 'success')
        return redirect(url_for('admin.facility_staff'))

    return render_template('admin/edit_staff.html', member=u, STAFF_ROLES=STAFF_ROLES)


@admin_bp.route('/facility/staff/<int:user_id>/deactivate', methods=['POST'])
@login_required
@facility_admin_required
def deactivate_staff(user_id):
    u = User.query.get_or_404(user_id)
    if current_user.role == 'facility_admin' and u.facility_id != current_user.facility_id:
        flash('Not authorised.', 'danger')
        return redirect(url_for('admin.facility_staff'))
    if u.id == current_user.id:
        flash('You cannot deactivate your own account.', 'danger')
        return redirect(url_for('admin.facility_staff'))
    u.active = not u.active
    db.session.commit()
    flash(f'{u.name} {"activated" if u.active else "deactivated"}.', 'success')
    return redirect(url_for('admin.facility_staff'))


# ─────────────────────────────────────────────────────────────────────────────
# MEDICINE CATALOGUE — Add / Edit / Approve proposals
# ─────────────────────────────────────────────────────────────────────────────

MEDICINE_CATEGORIES = [
    'Antimalarial', 'Antibiotic', 'Antiviral', 'ARV', 'Anti-TB',
    'Analgesic', 'Antipyretic', 'Antifungal', 'Antiparasitic',
    'Antidiabetic', 'Antihypertensive', 'Anticonvulsant', 'Bronchodilator',
    'Corticosteroid', 'Electrolyte', 'Supplement / Vitamin', 'Vaccine',
    'Obstetric', 'Contraceptive', 'Dermatological', 'Ophthalmological',
    'Anaesthetic', 'Oxytocic', 'Antiseptic', 'Diagnostic', 'Other',
]

DOSAGE_FORMS = [
    'Tablet', 'Capsule', 'Syrup', 'Suspension', 'Solution',
    'Injection (IV)', 'Injection (IM)', 'Injection (SC)',
    'Inhaler', 'Cream / Ointment', 'Drops (Eye)', 'Drops (Ear)',
    'Suppository', 'Patch', 'Sachet', 'Lozenge', 'Gel', 'Spray',
]


@admin_bp.route('/medicines')
@login_required
def medicines():
    """Medicine catalogue — everyone can view; admins see pending proposals."""
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '')
    page = request.args.get('page', 1, type=int)

    query = Medicine.query
    if q:
        from sqlalchemy import or_
        query = query.filter(or_(
            Medicine.name.ilike(f'%{q}%'),
            Medicine.generic_name.ilike(f'%{q}%'),
            Medicine.brand_name.ilike(f'%{q}%'),
            Medicine.diseases.ilike(f'%{q}%'),
        ))
    if category:
        query = query.filter_by(category=category)

    medicines_list = query.order_by(Medicine.name).paginate(
        page=page, per_page=30, error_out=False
    )

    # Pending proposals (admin only)
    from app.models import MedicineProposal
    proposals = []
    if current_user.role == 'system_admin':
        proposals = MedicineProposal.query.filter_by(status='pending')\
                                          .order_by(MedicineProposal.created_at.desc()).all()

    return render_template('admin/medicines.html',
                           medicines=medicines_list,
                           proposals=proposals,
                           categories=MEDICINE_CATEGORIES,
                           selected_cat=category,
                           query=q)


@admin_bp.route('/medicines/propose', methods=['GET', 'POST'])
@login_required
def propose_medicine():
    """
    Any doctor, nurse, pharmacist, or supplier can propose a new medicine.
    Admin approves before it is added to the master catalogue.
    """
    ALLOWED = ('doctor', 'pharmacist', 'supplier', 'staff',
               'facility_admin', 'system_admin', 'district_officer')
    if current_user.role not in ALLOWED:
        flash('You do not have permission to propose medicines.', 'danger')
        return redirect(url_for('dashboard.index'))

    from app.models import MedicineProposal

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        generic = request.form.get('generic_name', '').strip()
        brand = request.form.get('brand_name', '').strip()
        cat = request.form.get('category', '').strip()
        form = request.form.get('dosage_form', '').strip()
        strength= request.form.get('strength', '').strip()
        unit = request.form.get('unit', '').strip()
        diseases= request.form.get('diseases', '').strip()
        desc = request.form.get('description', '').strip()
        nda_code= request.form.get('nda_code', '').strip()
        rx_req = request.form.get('prescription_required') == 'on'
        cold = request.form.get('requires_cold_chain') == 'on'
        critical= request.form.get('critical') == 'on'
        who_ess = request.form.get('who_essential') == 'on'
        controlled = request.form.get('controlled_drug') == 'on'

        if not name or not cat or not form:
            flash('Medicine name, category and dosage form are required.', 'danger')
            return redirect(request.url)

        # Check for duplicates
        existing = Medicine.query.filter(
            Medicine.name.ilike(name)
        ).first()
        if existing:
            flash(f'"{existing.name}" already exists in the catalogue.', 'warning')
            return redirect(url_for('admin.medicines'))

        # If system admin, add directly; otherwise create a proposal
        if current_user.role == 'system_admin':
            med = Medicine(
                name=name, generic_name=generic, brand_name=brand,
                category=cat, dosage_form=form, strength=strength,
                unit=unit, diseases=diseases, description=desc,
                nda_code=nda_code, prescription_required=rx_req,
                requires_cold_chain=cold, critical=critical,
                who_essential=who_ess, controlled_drug=controlled,
            )
            db.session.add(med)
            db.session.commit()
            flash(f'{name} added to the medicine catalogue.', 'success')
            return redirect(url_for('admin.medicines'))

        # Create proposal for review
        proposal = MedicineProposal(
            proposed_by = current_user.id,
            name = name,
            generic_name = generic,
            brand_name = brand,
            category = cat,
            dosage_form = form,
            strength = strength,
            unit = unit,
            diseases = diseases,
            description = desc,
            nda_code = nda_code,
            prescription_required = rx_req,
            requires_cold_chain = cold,
            critical = critical,
            who_essential = who_ess,
            controlled_drug = controlled,
            status = 'pending',
            proposer_note = request.form.get('proposer_note', '').strip(),
        )
        db.session.add(proposal)

        # Notify system admins
        admins = User.query.filter_by(role='system_admin', active=True).all()
        for admin_user in admins:
            db.session.add(Notification(
                recipient_user_id = admin_user.id,
                title = f'New medicine proposal: {name}',
                body = f'{current_user.name} ({current_user.role}) '
                                    f'proposed adding "{name}" to the catalogue.',
                notif_type = 'message',
            ))

        db.session.commit()
        flash(f'Your proposal for "{name}" has been submitted for admin review. '
              f'You will be notified once approved.', 'success')
        return redirect(url_for('admin.medicines'))

    return render_template('admin/propose_medicine.html',
                           categories=MEDICINE_CATEGORIES,
                           dosage_forms=DOSAGE_FORMS)


@admin_bp.route('/medicines/proposals/<int:proposal_id>/approve', methods=['POST'])
@login_required
def approve_medicine_proposal(proposal_id):
    if current_user.role != 'system_admin':
        flash('Admin only.', 'danger')
        return redirect(url_for('admin.medicines'))

    from app.models import MedicineProposal
    p = MedicineProposal.query.get_or_404(proposal_id)

    med = Medicine(
        name=p.name, generic_name=p.generic_name, brand_name=p.brand_name,
        category=p.category, dosage_form=p.dosage_form, strength=p.strength,
        unit=p.unit, diseases=p.diseases, description=p.description,
        nda_code=p.nda_code, prescription_required=p.prescription_required,
        requires_cold_chain=p.requires_cold_chain, critical=p.critical,
        who_essential=p.who_essential, controlled_drug=p.controlled_drug,
    )
    db.session.add(med)

    p.status = 'approved'
    p.reviewed_by = current_user.id
    p.reviewed_at = datetime.utcnow()
    p.review_note = request.form.get('review_note', '').strip()

    # Notify proposer
    db.session.add(Notification(
        recipient_user_id = p.proposed_by,
        title = f'Medicine proposal approved: {p.name}',
        body = f'Your proposal for "{p.name}" has been approved '
                            f'and added to the MedLink catalogue.',
        notif_type = 'message',
    ))

    db.session.commit()
    flash(f'"{p.name}" approved and added to the catalogue.', 'success')
    return redirect(url_for('admin.medicines'))


@admin_bp.route('/medicines/proposals/<int:proposal_id>/reject', methods=['POST'])
@login_required
def reject_medicine_proposal(proposal_id):
    if current_user.role != 'system_admin':
        flash('Admin only.', 'danger')
        return redirect(url_for('admin.medicines'))

    from app.models import MedicineProposal
    p = MedicineProposal.query.get_or_404(proposal_id)
    p.status = 'rejected'
    p.reviewed_by = current_user.id
    p.reviewed_at = datetime.utcnow()
    p.review_note = request.form.get('review_note', '').strip()

    db.session.add(Notification(
        recipient_user_id = p.proposed_by,
        title = f'Medicine proposal rejected: {p.name}',
        body = f'Your proposal for "{p.name}" was not approved.'
                            + (f' Reason: {p.review_note}' if p.review_note else ''),
        notif_type = 'message',
    ))
    db.session.commit()
    flash(f'Proposal for "{p.name}" rejected.', 'warning')
    return redirect(url_for('admin.medicines'))


@admin_bp.route('/medicines/<int:med_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_medicine(med_id):
    if current_user.role != 'system_admin':
        flash('Admin only.', 'danger')
        return redirect(url_for('admin.medicines'))

    med = Medicine.query.get_or_404(med_id)

    if request.method == 'POST':
        med.name = request.form.get('name', med.name).strip()
        med.generic_name = request.form.get('generic_name', '').strip()
        med.brand_name = request.form.get('brand_name', '').strip()
        med.category = request.form.get('category', '')
        med.dosage_form = request.form.get('dosage_form', '')
        med.strength = request.form.get('strength', '').strip()
        med.unit = request.form.get('unit', '').strip()
        med.diseases = request.form.get('diseases', '').strip()
        med.description = request.form.get('description', '').strip()
        med.nda_code = request.form.get('nda_code', '').strip()
        med.prescription_required= request.form.get('prescription_required') == 'on'
        med.requires_cold_chain = request.form.get('requires_cold_chain') == 'on'
        med.critical = request.form.get('critical') == 'on'
        med.who_essential = request.form.get('who_essential') == 'on'
        med.controlled_drug = request.form.get('controlled_drug') == 'on'
        db.session.commit()
        flash(f'{med.name} updated.', 'success')
        return redirect(url_for('admin.medicines'))

    return render_template('admin/edit_medicine.html',
                           med=med, categories=MEDICINE_CATEGORIES,
                           dosage_forms=DOSAGE_FORMS)


# ─────────────────────────────────────────────────────────────────────────────
# PENDING REGISTRATIONS (facilities, delivery companies, doctors)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/pending')
@login_required
def pending_registrations():
    from app.models import DeliveryCompany
    if current_user.role != 'system_admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    pending_facilities = Facility.query.filter_by(verified=False, active=True)\
        .order_by(Facility.created_at.desc()).all()
    pending_companies = DeliveryCompany.query.filter_by(verified=False, active=True)\
        .order_by(DeliveryCompany.created_at.desc()).all()
    pending_doctors = User.query.filter(
        User.role.in_(['doctor', 'nurse', 'pharmacist']),
        User.verified_doctor == False,
        User.active == True,
    ).order_by(User.created_at.desc()).all()

    return render_template('admin/pending_registrations.html',
                           pending_facilities = pending_facilities,
                           pending_companies = pending_companies,
                           pending_doctors = pending_doctors)


@admin_bp.route('/pending/facility/<int:fid>/approve', methods=['POST'])
@login_required
def approve_facility(fid):
    if current_user.role != 'system_admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    fac = Facility.query.get_or_404(fid)
    fac.verified = True
    db.session.commit()
    # Notify all admins of this facility
    for u in fac.users:
        db.session.add(Notification(
            recipient_user_id = u.id,
            title = 'Facility Verified',
            body = f'Your facility "{fac.name}" has been verified by the system admin. '
                                f'All features are now fully active.',
            notif_type = 'system',
        ))
    db.session.commit()
    flash(f'"{fac.name}" has been verified.', 'success')
    return redirect(url_for('admin.pending_registrations'))


@admin_bp.route('/pending/facility/<int:fid>/reject', methods=['POST'])
@login_required
def reject_facility(fid):
    if current_user.role != 'system_admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    fac = Facility.query.get_or_404(fid)
    reason = request.form.get('reason', 'No reason given.')
    for u in fac.users:
        db.session.add(Notification(
            recipient_user_id = u.id,
            title = 'Facility Registration Rejected',
            body = f'Your registration for "{fac.name}" was not approved. '
                                f'Reason: {reason}',
            notif_type = 'system',
        ))
    fac.active = False
    db.session.commit()
    flash(f'"{fac.name}" registration rejected.', 'warning')
    return redirect(url_for('admin.pending_registrations'))


@admin_bp.route('/pending/company/<int:cid>/approve', methods=['POST'])
@login_required
def approve_company(cid):
    from app.models import DeliveryCompany
    if current_user.role != 'system_admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    co = DeliveryCompany.query.get_or_404(cid)
    co.verified = True
    # Upgrade the manager's role
    manager = User.query.filter_by(delivery_company_id=co.id).first()
    if manager:
        manager.role = 'company_manager'
        db.session.add(Notification(
            recipient_user_id = manager.id,
            title = 'Delivery Company Approved',
            body = f'"{co.name}" has been verified. You can now receive transport '
                                f'requests and add drivers to your company.',
            notif_type = 'system',
        ))
    db.session.commit()
    flash(f'"{co.name}" approved and manager role upgraded.', 'success')
    return redirect(url_for('admin.pending_registrations'))


@admin_bp.route('/pending/company/<int:cid>/reject', methods=['POST'])
@login_required
def reject_company(cid):
    from app.models import DeliveryCompany
    if current_user.role != 'system_admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    co = DeliveryCompany.query.get_or_404(cid)
    reason = request.form.get('reason', 'No reason given.')
    manager = User.query.filter_by(delivery_company_id=co.id).first()
    if manager:
        db.session.add(Notification(
            recipient_user_id = manager.id,
            title = 'Delivery Company Registration Rejected',
            body = f'"{co.name}" was not approved. Reason: {reason}',
            notif_type = 'system',
        ))
    co.active = False
    db.session.commit()
    flash(f'"{co.name}" rejected.', 'warning')
    return redirect(url_for('admin.pending_registrations'))
