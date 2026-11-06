"""
MedLink Uganda — HIV/ART Retention in Care Module
==================================================
Private, anonymous ART refill reminders and viral load tracking.
The biggest challenge in Uganda's HIV response is not diagnosis —
it is keeping people on treatment (retention in care).

Uganda context:
- 1.4 million PLHIV (people living with HIV)
- 1.2 million on ART (antiretroviral therapy)
- 78% viral suppression — target is 95%
- Missed ART refills lead to viral rebound, drug resistance, onward transmission
- Stigma is extreme — module is fully private by design
- PEPFAR/TASO/Baylor Uganda are key implementing partners
- Standard regimen: TDF/3TC/DTG (Tenofovir/Lamivudine/Dolutegravir)
- Refill intervals: 30 days (new patients), 90 days (stable patients)
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import current_user
from app import db
from app.models import HIVProfile, ARTRefill, Facility, District
from datetime import date, datetime, timedelta
import json, uuid

hiv_bp = Blueprint('hiv', __name__, url_prefix='/hiv-care')

SMS_MESSAGES = {
    'English': {
        'refill_reminder': (
            'MedLink: Your ART refill is due on {date} at {facility}. '
            'Please collect your medicines on time. Missing doses risks your health and your family. '
            'Ref: {ref}. If you have moved, call {facility_phone}.'
        ),
        'missed_refill': (
            'MedLink: You missed your ART refill on {date}. '
            'Please visit {facility} TODAY for your medicines. '
            'It is never too late to restart. Your health matters.'
        ),
    },
    'Luganda': {
        'refill_reminder': (
            'MedLink: Edwaliiro lyo lya ART lija ku {date} ku {facility}. '
            'Nziza ojje otwale eddawa lyo nga buli kiseera. Okuzizimira ebigere bivvuunira obulamu bwo.'
        ),
        'missed_refill': (
            'MedLink: Wabula okutwala eddawa lyo ku {date}. '
            'Genda {facility} LEERO. Teyalikirizibwa okuzzaayo. Obulamu bwo bwa maanyi.'
        ),
    },
    'Runyankole': {
        'refill_reminder': (
            'MedLink: Eigyendererwa ryawe rya ART rikwetekwa kuri {date} kuri {facility}. '
            'Nzija oteire obushaho bwawe mu kiseera. Okubenga obugyenyi bugira endwara.'
        ),
        'missed_refill': (
            'MedLink: Warega okwetegeka kuri {date}. '
            'Genda {facility} HANO. Tikirugaho ogaruka. Obuzima bwawe bwagira.'
        ),
    },
}

REGIMENS = [
    'TDF/3TC/DTG', 'TDF/3TC/EFV', 'AZT/3TC/NVP', 'AZT/3TC/EFV',
    'ABC/3TC/DTG', 'LPV/r + TDF/3TC', 'Other',
]


@hiv_bp.route('/')
def index():
    """Landing page — privacy-focused, no login required to start."""
    tok = session.get('hiv_token')
    profile = None
    if tok:
        profile = HIVProfile.query.filter_by(
            id=tok if isinstance(tok, int) else None
        ).first()
        if current_user.is_authenticated:
            profile = HIVProfile.query.filter_by(user_id=current_user.id).first()
    elif current_user.is_authenticated:
        profile = HIVProfile.query.filter_by(user_id=current_user.id).first()

    return render_template('hiv/index.html', profile=profile)


@hiv_bp.route('/register', methods=['GET', 'POST'])
def register():
    facilities = Facility.query.order_by(Facility.name).all()

    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        if not phone:
            flash('A phone number is required for refill reminders.', 'danger')
            return render_template('hiv/register.html', facilities=facilities, regimens=REGIMENS)

        art_start_str = request.form.get('art_start_date', '')
        art_start = None
        if art_start_str:
            try: art_start = datetime.strptime(art_start_str, '%Y-%m-%d').date()
            except: pass

        profile = HIVProfile(
            user_id = current_user.id if current_user.is_authenticated else None,
            phone = phone,
            art_number = request.form.get('art_number', '').strip(),
            facility_id = request.form.get('facility_id', type=int),
            art_start_date = art_start,
            current_regimen = request.form.get('regimen', ''),
            on_tb_treatment = request.form.get('tb') == 'yes',
            pregnant = request.form.get('pregnant') == 'yes',
            preferred_language = request.form.get('language', 'English'),
            status = 'active',
        )
        db.session.add(profile)
        db.session.flush()

        # Schedule first refill
        days_supply = int(request.form.get('days_supply', 30) or 30)
        last_refill_str = request.form.get('last_refill_date', '')
        try:
            last = datetime.strptime(last_refill_str, '%Y-%m-%d').date()
        except:
            last = date.today()

        next_due = last + timedelta(days=days_supply)
        db.session.add(ARTRefill(
            profile_id = profile.id,
            due_date = next_due,
            days_supply = days_supply,
            facility_id = profile.facility_id,
        ))
        db.session.commit()

        session['hiv_profile_id'] = profile.id
        flash('ART reminders set up. You will receive an SMS 3 days before each refill.', 'success')
        return redirect(url_for('hiv.dashboard', profile_id=profile.id))

    return render_template('hiv/register.html', facilities=facilities, regimens=REGIMENS)


@hiv_bp.route('/dashboard/<int:profile_id>')
def dashboard(profile_id):
    profile = HIVProfile.query.get_or_404(profile_id)
    # Privacy: only owner or admin
    if (current_user.is_authenticated and current_user.id != profile.user_id
            and current_user.role not in ('system_admin', 'doctor')):
        if session.get('hiv_profile_id') != profile_id:
            flash('Not authorised.', 'danger')
            return redirect(url_for('hiv.index'))

    refills = ARTRefill.query.filter_by(profile_id=profile_id).order_by(ARTRefill.due_date).all()
    today = date.today()
    next_ref = next((r for r in refills if not r.collected and r.due_date >= today), None)
    overdue = [r for r in refills if not r.collected and r.due_date < today]
    done = [r for r in refills if r.collected]

    return render_template('hiv/dashboard.html',
                           profile=profile, refills=refills,
                           next_ref=next_ref, overdue=overdue, done=done, today=today)


@hiv_bp.route('/refill/<int:rid>/collected', methods=['POST'])
def mark_collected(rid):
    refill = ARTRefill.query.get_or_404(rid)
    profile = HIVProfile.query.get(refill.profile_id)

    if session.get('hiv_profile_id') != profile.id:
        if not current_user.is_authenticated or (current_user.id != profile.user_id
                and current_user.role not in ('system_admin', 'doctor', 'staff')):
            flash('Not authorised.', 'danger')
            return redirect(url_for('hiv.index'))

    refill.collected = True
    refill.collected_date = date.today()
    refill.notes = request.form.get('notes', '')

    # Schedule next refill
    days_supply = refill.days_supply or 30
    next_due = date.today() + timedelta(days=days_supply)
    db.session.add(ARTRefill(
        profile_id = profile.id,
        due_date = next_due,
        days_supply = days_supply,
        facility_id = refill.facility_id,
    ))
    db.session.commit()
    flash(f'Refill marked as collected. Next refill scheduled for {next_due.strftime("%d %b %Y")}.', 'success')
    return redirect(url_for('hiv.dashboard', profile_id=profile.id))


@hiv_bp.route('/update-labs/<int:profile_id>', methods=['POST'])
def update_labs(profile_id):
    profile = HIVProfile.query.get_or_404(profile_id)
    vl_str = request.form.get('viral_load', '')
    cd4_str = request.form.get('cd4_count', '')
    vl_date_str = request.form.get('test_date', '')

    try:
        if vl_str: profile.viral_load = float(vl_str)
        if cd4_str: profile.cd4_count = int(cd4_str)
        if vl_date_str:
            profile.viral_load_date = datetime.strptime(vl_date_str, '%Y-%m-%d').date()
            profile.cd4_date = profile.viral_load_date
    except ValueError:
        flash('Invalid lab values.', 'danger')
        return redirect(url_for('hiv.dashboard', profile_id=profile_id))

    db.session.commit()
    flash('Lab results updated.', 'success')
    return redirect(url_for('hiv.dashboard', profile_id=profile_id))


def send_art_reminders(app):
    """Called by scheduler — SMS patients 3 days before ART refill."""
    with app.app_context():
        from app.services.sms import send_sms
        target = date.today() + timedelta(days=3)
        refills = ARTRefill.query.filter(
            ARTRefill.due_date == target,
            ARTRefill.collected == False,
            ARTRefill.reminder_sent == False,
        ).all()
        for r in refills:
            profile = r.profile
            phone = profile.phone
            if not phone:
                continue
            lang = profile.preferred_language if profile.preferred_language in SMS_MESSAGES else 'English'
            facility = r.facility or profile.facility
            msg = SMS_MESSAGES[lang]['refill_reminder'].format(
                date = r.due_date.strftime('%d %b %Y'),
                facility = facility.name if facility else 'your ART clinic',
                facility_phone= facility.phone if facility else '',
                ref = profile.art_number or 'N/A',
            )
            sent = send_sms(phone, msg)
            if sent:
                r.reminder_sent = True
        db.session.commit()
