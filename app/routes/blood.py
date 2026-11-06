"""
MedLink Uganda — Blood Bank & Donation Module
==============================================
Real-time blood availability across Uganda's facilities.
Donor registration with SMS alerts when their blood type is urgently needed.

Uganda context:
- Uganda needs ~340,000 units/year; only ~260,000 collected (UBTS 2022)
- O+ is the most needed (50% of Ugandan population)
- Post-partum haemorrhage + surgical emergencies are leading causes
- Uganda Blood Transfusion Service (UBTS): 0800 190 190 (toll-free)
- A donor must be 16–65 years, ≥50kg, and not donated in last 3 months
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import BloodBank, BloodDonor, BloodRequest, Facility, District, User
from datetime import date, datetime, timedelta
import json

blood_bp = Blueprint('blood', __name__, url_prefix='/blood')

BLOOD_TYPES = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']

COMPATIBILITY = {
    'A+': ['A+', 'AB+'],
    'A-': ['A+', 'A-', 'AB+', 'AB-'],
    'B+': ['B+', 'AB+'],
    'B-': ['B+', 'B-', 'AB+', 'AB-'],
    'AB+': ['AB+'],
    'AB-': ['AB+', 'AB-'],
    'O+': ['A+', 'B+', 'AB+', 'O+'],
    'O-': ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'], # universal donor
}

SMS_MESSAGES = {
    'English': (
        'MedLink URGENT: {facility} needs {units} unit(s) of {blood_type} blood. '
        'You are a registered donor of this type. Please call {facility_phone} or '
        'visit the blood bank now. Lives depend on you. Thank you. '
    ),
    'Luganda': (
        'MedLink MAANGU: {facility} bagenda {units} unit(s) ey\'omusaayi gw\'oluganda {blood_type}. '
        'Oli omuweeza w\'omusaayi. Yita {facility_phone} oba genda ku blood bank kaakano. '
        'Abantu baagala obuyambi bwo. Webale. '
    ),
    'Runyankole': (
        'MedLink OKUGIRA OMURI: {facility} bagira {units} unit(s) z\'omushaija {blood_type}. '
        'Uri mugumiire w\'omushaija. Tura {facility_phone} oba genda ku blood bank hanu. '
        'Abantu bakurikire obuyambi bwawe. Webale. '
    ),
}


@blood_bp.route('/')
def index():
    """Public blood availability map and search."""
    blood_type = request.args.get('type', '')
    district = request.args.get('district', '')

    query = BloodBank.query.filter(BloodBank.units_available > 0)
    if blood_type:
        query = query.filter_by(blood_type=blood_type)

    stocks = query.order_by(BloodBank.is_urgent.desc(),
                            BloodBank.units_available.desc()).all()

    # Group by facility
    facilities_map = {}
    for s in stocks:
        fid = s.facility_id
        if fid not in facilities_map:
            facilities_map[fid] = {'facility': s.facility, 'stocks': []}
        facilities_map[fid]['stocks'].append(s)

    # Summary totals by blood type
    totals = {}
    for bt in BLOOD_TYPES:
        total = db.session.query(
            db.func.sum(BloodBank.units_available)
        ).filter_by(blood_type=bt).scalar() or 0
        totals[bt] = int(total)

    districts = District.query.order_by(District.name).all()
    urgent = BloodBank.query.filter_by(is_urgent=True).all()

    return render_template('blood/index.html',
                           facilities_map=facilities_map, totals=totals,
                           blood_types=BLOOD_TYPES, selected_type=blood_type,
                           districts=districts, urgent=urgent,
                           compatibility=COMPATIBILITY)


@blood_bp.route('/request', methods=['GET', 'POST'])
def request_blood():
    """Patient or doctor submits an urgent blood request."""
    facilities = Facility.query.order_by(Facility.name).all()

    if request.method == 'POST':
        blood_type = request.form.get('blood_type', '')
        units = int(request.form.get('units', 1) or 1)
        urgency = request.form.get('urgency', 'urgent')
        reason = request.form.get('reason', '')
        facility_id = request.form.get('facility_id', type=int)

        req = BloodRequest(
            patient_id = current_user.id if current_user.is_authenticated else None,
            requester_id = current_user.id if current_user.is_authenticated else None,
            facility_id = facility_id,
            blood_type = blood_type,
            units_needed = units,
            urgency = urgency,
            reason = reason,
            status = 'open',
        )
        db.session.add(req)
        db.session.flush()

        # Alert matching donors in same district
        sms_count = _alert_donors(blood_type, facility_id, units, req.id)
        req.sms_sent_count = sms_count
        db.session.commit()

        flash(f'Blood request submitted. {sms_count} registered donor(s) notified by SMS.', 'success')
        return redirect(url_for('blood.request_detail', req_id=req.id))

    return render_template('blood/request_blood.html',
                           facilities=facilities, blood_types=BLOOD_TYPES)


@blood_bp.route('/request/<int:req_id>')
def request_detail(req_id):
    req = BloodRequest.query.get_or_404(req_id)
    # Find facilities with matching or compatible blood in stock
    compatible_types = COMPATIBILITY.get(req.blood_type, [req.blood_type])
    available = BloodBank.query.filter(
        BloodBank.blood_type.in_(compatible_types),
        BloodBank.units_available > 0,
    ).order_by(BloodBank.units_available.desc()).all()
    return render_template('blood/request_detail.html', req=req, available=available,
                           compatible_types=compatible_types)


@blood_bp.route('/donate', methods=['GET', 'POST'])
def register_donor():
    """Register as a blood donor."""
    districts = District.query.order_by(District.name).all()

    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        btype = request.form.get('blood_type', '')
        name = request.form.get('name', '').strip()

        if not phone or not btype or not name:
            flash('Name, phone and blood type are required.', 'danger')
            return render_template('blood/register_donor.html',
                                   districts=districts, blood_types=BLOOD_TYPES)

        existing = BloodDonor.query.filter_by(phone=phone).first()
        if existing:
            flash('This phone number is already registered as a donor.', 'info')
            return redirect(url_for('blood.donor_profile', donor_id=existing.id))

        donor = BloodDonor(
            user_id = current_user.id if current_user.is_authenticated else None,
            name = name,
            phone = phone,
            blood_type = btype,
            district_id = request.form.get('district_id', type=int),
            preferred_language = request.form.get('language', 'English'),
            is_active = True,
        )
        db.session.add(donor)
        db.session.commit()
        flash(f'Thank you {name}! You are registered as a {btype} donor. We\'ll SMS you when your blood type is urgently needed.', 'success')
        return redirect(url_for('blood.donor_profile', donor_id=donor.id))

    return render_template('blood/register_donor.html',
                           districts=districts, blood_types=BLOOD_TYPES)


@blood_bp.route('/donor/<int:donor_id>')
def donor_profile(donor_id):
    donor = BloodDonor.query.get_or_404(donor_id)
    # Can donate if not donated in last 90 days
    can_donate = True
    days_since = None
    if donor.last_donated:
        days_since = (date.today() - donor.last_donated).days
        can_donate = days_since >= 90
    return render_template('blood/donor_profile.html',
                           donor=donor, can_donate=can_donate, days_since=days_since)


@blood_bp.route('/update-stock', methods=['GET', 'POST'])
@login_required
def update_stock():
    """Lab staff / facility admin updates blood stock levels."""
    if current_user.role not in ('staff', 'facility_admin', 'system_admin', 'district_officer'):
        flash('Not authorised.', 'danger')
        return redirect(url_for('blood.index'))

    facility_id = current_user.facility_id
    if not facility_id:
        flash('You must be assigned to a facility to update stock.', 'warning')
        return redirect(url_for('blood.index'))

    if request.method == 'POST':
        for bt in BLOOD_TYPES:
            units = request.form.get(f'units_{bt}', 0, type=int)
            is_urgent = units < 3

            stock = BloodBank.query.filter_by(
                facility_id=facility_id, blood_type=bt
            ).first()
            if stock:
                stock.units_available = units
                stock.is_urgent = is_urgent
                stock.updated_by = current_user.id
            else:
                db.session.add(BloodBank(
                    facility_id = facility_id,
                    blood_type = bt,
                    units_available = units,
                    is_urgent = is_urgent,
                    updated_by = current_user.id,
                ))
        db.session.commit()
        flash('Blood stock updated successfully.', 'success')
        return redirect(url_for('blood.index'))

    # Current stock for this facility
    current_stock = {s.blood_type: s for s in
                     BloodBank.query.filter_by(facility_id=facility_id).all()}
    return render_template('blood/update_stock.html',
                           blood_types=BLOOD_TYPES, current_stock=current_stock,
                           facility=Facility.query.get(facility_id))


@blood_bp.route('/api/availability')
def api_availability():
    """JSON endpoint for map integration."""
    blood_type = request.args.get('type', '')
    query = BloodBank.query.filter(BloodBank.units_available > 0)
    if blood_type:
        query = query.filter_by(blood_type=blood_type)
    stocks = query.all()
    results = []
    seen = set()
    for s in stocks:
        f = s.facility
        if not f or not f.latitude or not f.longitude:
            continue
        key = (f.id, s.blood_type)
        if key in seen:
            continue
        seen.add(key)
        results.append({
            'facility': f.name,
            'address': f.address or '',
            'phone': f.phone or '',
            'lat': f.latitude,
            'lon': f.longitude,
            'blood_type':s.blood_type,
            'units': s.units_available,
            'urgent': s.is_urgent,
        })
    return jsonify(results)


def _alert_donors(blood_type, facility_id, units_needed, req_id):
    """SMS all active donors of a compatible blood type in the region."""
    from app.services.sms import send_sms
    compatible = [blood_type] # only exact match for safety
    # O- donors can donate to anyone — alert them for emergency
    if blood_type not in ('O-', 'O+'):
        compatible.append('O-')

    donors = BloodDonor.query.filter(
        BloodDonor.blood_type.in_(compatible),
        BloodDonor.is_active == True,
    ).all()

    facility = Facility.query.get(facility_id) if facility_id else None
    facility_name = facility.name if facility else 'a hospital near you'
    facility_phone = facility.phone if facility else 'the hospital'

    count = 0
    for donor in donors:
        # Don't alert if donated < 90 days ago
        if donor.last_donated and (date.today() - donor.last_donated).days < 90:
            continue
        lang = donor.preferred_language if donor.preferred_language in SMS_MESSAGES else 'English'
        msg = SMS_MESSAGES[lang].format(
            facility = facility_name,
            facility_phone = facility_phone,
            blood_type = blood_type,
            units = units_needed,
        )
        sent = send_sms(donor.phone, msg)
        if sent:
            count += 1
    return count
