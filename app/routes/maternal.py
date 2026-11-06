"""
MedLink Uganda — Maternal Health Module
========================================
Pregnancy tracker, ANC visit scheduler, postnatal follow-up,
and SMS reminders in local languages.

Uganda context:
- Maternal mortality ratio ~336 per 100,000 live births (UDHS 2022)
- Ministry of Health recommends minimum 8 ANC visits (WHO 2016 model)
- Uganda's most common causes of maternal death:
  haemorrhage, eclampsia, sepsis, obstructed labour, unsafe abortion
- PMTCT (HIV Prevention of Mother-to-Child Transmission) is critical
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import MaternalProfile, ANCVisit, User, Facility, District, Appointment
from datetime import date, datetime, timedelta
import json

maternal_bp = Blueprint('maternal', __name__, url_prefix='/maternal')

# ── ANC schedule per Uganda MoH / WHO 2016 model ─────────────────────────────
ANC_SCHEDULE = [
    {'number': 1, 'label': '1st ANC — Booking visit', 'weeks_from_lmp': 8, 'description': 'Confirm pregnancy, blood tests, HIV test, start folic acid & iron'},
    {'number': 2, 'label': '2nd ANC', 'weeks_from_lmp': 20, 'description': 'Ultrasound scan, malaria prophylaxis (SP), syphilis test'},
    {'number': 3, 'label': '3rd ANC', 'weeks_from_lmp': 26, 'description': 'Blood pressure, urine test, foetal position check'},
    {'number': 4, 'label': '4th ANC', 'weeks_from_lmp': 30, 'description': 'Growth monitoring, birth preparedness planning'},
    {'number': 5, 'label': '5th ANC', 'weeks_from_lmp': 34, 'description': 'Repeat blood pressure, HIV retest, review birth plan'},
    {'number': 6, 'label': '6th ANC', 'weeks_from_lmp': 36, 'description': 'Group B strep screening, presentation check'},
    {'number': 7, 'label': '7th ANC', 'weeks_from_lmp': 38, 'description': 'Pre-delivery assessment'},
    {'number': 8, 'label': '8th ANC — Pre-delivery', 'weeks_from_lmp': 40, 'description': 'Final assessment, confirm facility delivery plan'},
]

POSTNATAL_SCHEDULE = [
    {'number': 9, 'label': 'PNC 1 — Within 24 hours of birth', 'days_after_delivery': 1, 'description': 'Immediate postnatal check, breastfeeding support, mother and baby vitals'},
    {'number': 10, 'label': 'PNC 2 — Day 3', 'days_after_delivery': 3, 'description': 'Danger sign screening, cord care, immunisation start (BCG, Polio 0)'},
    {'number': 11, 'label': 'PNC 3 — Week 1 (Day 7)', 'days_after_delivery': 7, 'description': 'Mental health screen (postnatal depression), feeding assessment'},
    {'number': 12, 'label': 'PNC 4 — Week 6', 'days_after_delivery': 42, 'description': 'Final postnatal review, family planning counselling, baby 6-week immunisation'},
]

SMS_MESSAGES = {
    'English': {
        'anc_reminder': 'MedLink Reminder: Your {label} appointment is due on {date}. Please visit {clinic} or book online at medlink.ug. Your health and your baby\'s health matter. ',
        'missed_anc': 'MedLink: You missed your {label} appointment on {date}. Please book urgently at medlink.ug or call your nearest clinic. Missing ANC visits increases risks for you and your baby.',
        'pnc_reminder': 'MedLink: Your {label} postnatal check is due {date}. Visit {clinic} to check on you and your baby. Early problems are easier to treat. ',
    },
    'Luganda': {
        'anc_reminder': 'MedLink: Okulabibwa okuddako kwa {label} kuliko ku {date}. Genda {clinic} oba kozesa medlink.ug okufubirwa. Obulamu bwo n\'obw\'omwana wo bwa maanyi. ',
        'missed_anc': 'MedLink: Wabula okulabibwa kwa {label} ku {date}. Wulikira abasawo mangu ku medlink.ug. Obutabulabibwa buvuunirira obuzibu.',
        'pnc_reminder': 'MedLink: Okulabibwa okuddako okusooka oluvannyuma lw\'okuzyalwa kwa {label} kuliko {date}. Genda {clinic}. ',
    },
    'Runyankole': {
        'anc_reminder': 'MedLink: Obugyenyi bwawe bwa {label} burikuganirwa kuri {date}. Genda {clinic} oba kozesa medlink.ug. Obuzima bwawe n\'obw\'omwana wawe bwagira. ',
        'missed_anc': 'MedLink: Owetekire obugyenyi bwa {label} kuri {date}. Baaza edocita mangu kuri medlink.ug.',
        'pnc_reminder': 'MedLink: Obugyenyi bwawe okurikuza okuzara bwa {label} burikuganirwa {date}. Genda {clinic}. ',
    },
}


@maternal_bp.route('/')
@login_required
def index():
    profile = MaternalProfile.query.filter_by(patient_id=current_user.id).first()
    if not profile:
        return redirect(url_for('maternal.register'))
    visits = ANCVisit.query.filter_by(profile_id=profile.id).order_by(ANCVisit.visit_number).all()
    today = date.today()
    next_visit = next((v for v in visits if not v.completed and v.due_date >= today), None)
    overdue = [v for v in visits if not v.completed and v.due_date < today]
    completed = [v for v in visits if v.completed]
    weeks_preg = _weeks_pregnant(profile)
    days_to_edd = (profile.edd - today).days if profile.edd else None
    return render_template('maternal/dashboard.html',
                           profile=profile, visits=visits, today=today,
                           next_visit=next_visit, overdue=overdue,
                           completed=completed, weeks_preg=weeks_preg,
                           days_to_edd=days_to_edd)


@maternal_bp.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    existing = MaternalProfile.query.filter_by(patient_id=current_user.id).first()
    if existing:
        return redirect(url_for('maternal.index'))
    facilities = Facility.query.filter(
        Facility.facility_type.in_(['government_clinic','private_clinic','ngo_clinic'])
    ).order_by(Facility.name).all()

    if request.method == 'POST':
        lmp_str = request.form.get('lmp_date', '')
        try:
            lmp = datetime.strptime(lmp_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Please enter a valid Last Menstrual Period date.', 'danger')
            return render_template('maternal/register.html', facilities=facilities)

        edd = lmp + timedelta(weeks=40)
        profile = MaternalProfile(
            patient_id = current_user.id,
            lmp_date = lmp,
            edd = edd,
            gravida = int(request.form.get('gravida', 1) or 1),
            parity = int(request.form.get('parity', 0) or 0),
            hiv_status = request.form.get('hiv_status', 'unknown'),
            diabetes = request.form.get('diabetes') == 'yes',
            hypertension = request.form.get('hypertension') == 'yes',
            sickle_cell = request.form.get('sickle_cell') == 'yes',
            preferred_language = request.form.get('language', 'English'),
            facility_id = int(request.form.get('facility_id')) if request.form.get('facility_id') else None,
            status = 'pregnant',
        )
        db.session.add(profile)
        db.session.flush()

        # Generate ANC visit schedule
        for entry in ANC_SCHEDULE:
            due = lmp + timedelta(weeks=entry['weeks_from_lmp'])
            db.session.add(ANCVisit(
                profile_id = profile.id,
                visit_number = entry['number'],
                visit_label = entry['label'],
                due_date = due,
            ))

        db.session.commit()
        flash('Maternal health profile created! Your ANC schedule has been set up.', 'success')
        return redirect(url_for('maternal.index'))

    return render_template('maternal/register.html', facilities=facilities)


@maternal_bp.route('/visits/<int:vid>/complete', methods=['POST'])
@login_required
def complete_visit(vid):
    visit = ANCVisit.query.get_or_404(vid)
    profile = MaternalProfile.query.get(visit.profile_id)
    if profile.patient_id != current_user.id and current_user.role not in ('doctor','system_admin'):
        flash('Not authorised.', 'danger')
        return redirect(url_for('maternal.index'))
    visit.completed = True
    visit.completed_date = date.today()
    visit.notes = request.form.get('notes', '')
    db.session.commit()
    flash(f'{visit.visit_label} marked as completed.', 'success')
    return redirect(url_for('maternal.index'))


@maternal_bp.route('/delivery', methods=['GET', 'POST'])
@login_required
def record_delivery():
    """Record the birth and switch to postnatal schedule."""
    profile = MaternalProfile.query.filter_by(patient_id=current_user.id).first_or_404()
    if request.method == 'POST':
        del_str = request.form.get('delivery_date', '')
        try:
            del_date = datetime.strptime(del_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date.', 'danger')
            return redirect(url_for('maternal.record_delivery'))

        profile.delivery_date = del_date
        profile.status = 'postnatal'

        # Add postnatal visit schedule
        for entry in POSTNATAL_SCHEDULE:
            due = del_date + timedelta(days=entry['days_after_delivery'])
            existing = ANCVisit.query.filter_by(
                profile_id=profile.id, visit_number=entry['number']
            ).first()
            if not existing:
                db.session.add(ANCVisit(
                    profile_id = profile.id,
                    visit_number = entry['number'],
                    visit_label = entry['label'],
                    due_date = due,
                ))
        db.session.commit()
        flash('Delivery recorded. Postnatal visit schedule created.', 'success')
        return redirect(url_for('maternal.index'))
    return render_template('maternal/record_delivery.html', profile=profile)


@maternal_bp.route('/api/schedule')
@login_required
def api_schedule():
    profile = MaternalProfile.query.filter_by(patient_id=current_user.id).first()
    if not profile:
        return jsonify({'error': 'No maternal profile'}), 404
    visits = ANCVisit.query.filter_by(profile_id=profile.id).order_by(ANCVisit.visit_number).all()
    return jsonify([{
        'id': v.id,
        'number': v.visit_number,
        'label': v.visit_label,
        'due_date': v.due_date.isoformat(),
        'completed': v.completed,
        'overdue': not v.completed and v.due_date < date.today(),
    } for v in visits])


# ── Reminder scheduler helper (called from __init__.py scheduler) ────────────
def send_anc_reminders(app):
    """Send SMS reminders for ANC visits due in 3 days. Called by the scheduler."""
    with app.app_context():
        from app.services.sms import send_sms
        target_date = date.today() + timedelta(days=3)
        visits = ANCVisit.query.filter(
            ANCVisit.due_date == target_date,
            ANCVisit.completed == False,
            ANCVisit.reminder_sent == False,
        ).all()
        for v in visits:
            profile = v.profile
            patient = profile.patient
            if not patient or not patient.phone:
                continue
            lang = profile.preferred_language if profile.preferred_language in SMS_MESSAGES else 'English'
            clinic = profile.facility.name if profile.facility else 'your nearest clinic'
            key = 'anc_reminder' if v.visit_number <= 8 else 'pnc_reminder'
            msg = SMS_MESSAGES[lang][key].format(
                label = v.visit_label,
                date = v.due_date.strftime('%d %b %Y'),
                clinic = clinic,
            )
            sent = send_sms(patient.phone, msg)
            if sent:
                v.reminder_sent = True
        db.session.commit()


def _weeks_pregnant(profile):
    if not profile.lmp_date or profile.status != 'pregnant':
        return None
    return min(int((date.today() - profile.lmp_date).days / 7), 42)
