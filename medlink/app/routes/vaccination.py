"""
MedLink Uganda — Childhood Vaccination Tracker
===============================================
Uganda EPI (Expanded Programme on Immunisation) schedule tracking
with SMS reminders for parents in local languages.

Uganda EPI schedule (Ministry of Health):
- Birth: BCG, OPV 0
- 6 weeks: OPV 1, DPT-HepB-Hib 1, PCV 1, Rota 1
- 10 weeks: OPV 2, DPT-HepB-Hib 2, PCV 2, Rota 2
- 14 weeks: OPV 3, DPT-HepB-Hib 3, PCV 3
- 9 months: Measles-Rubella 1, Vitamin A
- 18 months:Measles-Rubella 2, DPT booster, OPV 4

Uganda context:
- 22% of children miss at least one vaccine (UDHS 2022)
- Missed vaccines cause measles, whooping cough, meningitis outbreaks
- Main barriers: parents forget dates, long distances, stock-outs
- VHT (Village Health Team) workers are the primary trackers
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import ChildProfile, VaccineSchedule, Facility, District
from datetime import date, datetime, timedelta
import json

vax_bp = Blueprint('vaccination', __name__, url_prefix='/vaccination')

EPI_SCHEDULE = [
    {'name': 'BCG', 'dose': 1, 'days_after_birth': 0, 'description': 'Tuberculosis prevention — given at birth'},
    {'name': 'OPV', 'dose': 0, 'days_after_birth': 0, 'description': 'Oral Polio Vaccine — birth dose'},
    {'name': 'OPV', 'dose': 1, 'days_after_birth': 42, 'description': 'Oral Polio Vaccine — 1st dose (6 weeks)'},
    {'name': 'DPT-HepB-Hib', 'dose': 1, 'days_after_birth': 42, 'description': 'Diphtheria, Pertussis, Tetanus, Hepatitis B, Hib — 1st dose'},
    {'name': 'PCV', 'dose': 1, 'days_after_birth': 42, 'description': 'Pneumococcal — protects against meningitis & pneumonia'},
    {'name': 'Rotavirus', 'dose': 1, 'days_after_birth': 42, 'description': 'Protects against severe diarrhoea'},
    {'name': 'OPV', 'dose': 2, 'days_after_birth': 70, 'description': 'Oral Polio Vaccine — 2nd dose (10 weeks)'},
    {'name': 'DPT-HepB-Hib', 'dose': 2, 'days_after_birth': 70, 'description': 'DPT-HepB-Hib — 2nd dose'},
    {'name': 'PCV', 'dose': 2, 'days_after_birth': 70, 'description': 'Pneumococcal — 2nd dose'},
    {'name': 'Rotavirus', 'dose': 2, 'days_after_birth': 70, 'description': 'Rotavirus — 2nd dose'},
    {'name': 'OPV', 'dose': 3, 'days_after_birth': 98, 'description': 'Oral Polio Vaccine — 3rd dose (14 weeks)'},
    {'name': 'DPT-HepB-Hib', 'dose': 3, 'days_after_birth': 98, 'description': 'DPT-HepB-Hib — 3rd dose'},
    {'name': 'PCV', 'dose': 3, 'days_after_birth': 98, 'description': 'Pneumococcal — 3rd dose'},
    {'name': 'Measles-Rubella', 'dose': 1, 'days_after_birth': 274, 'description': 'Measles & Rubella — 1st dose (9 months)'},
    {'name': 'Vitamin A', 'dose': 1, 'days_after_birth': 274, 'description': 'Vitamin A supplementation (9 months)'},
    {'name': 'Measles-Rubella', 'dose': 2, 'days_after_birth': 548, 'description': 'Measles & Rubella booster (18 months)'},
    {'name': 'OPV', 'dose': 4, 'days_after_birth': 548, 'description': 'Oral Polio booster (18 months)'},
    {'name': 'DPT booster', 'dose': 4, 'days_after_birth': 548, 'description': 'DPT booster (18 months)'},
]

SMS_MESSAGES = {
    'English': {
        'reminder': 'MedLink: {child} is due for {vaccine} (dose {dose}) on {date}. Please visit {clinic} for vaccination. Missing vaccines can cause serious illness. ',
        'overdue': 'MedLink: {child} MISSED {vaccine} on {date}. Please visit {clinic} as soon as possible. This vaccine is still effective when given late.',
    },
    'Luganda': {
        'reminder': 'MedLink: {child} agenda okufumbirwa {vaccine} (ekifo {dose}) ku {date}. Genda {clinic}. Okugobera empikkulizo bivvuunira obuzibu obukalit. ',
        'overdue': 'MedLink: {child} YABULA {vaccine} ku {date}. Genda {clinic} mangu. Empikkulizo ensinga zisobola okufumbirwa nga zikyasinga.',
    },
    'Runyankole': {
        'reminder': 'MedLink: {child} akwetekwa okuhwa {vaccine} (eka {dose}) kuri {date}. Genda {clinic}. Okubura obuhwezi butera endwara enyima. ',
        'overdue': 'MedLink: {child} YAREKA {vaccine} kuri {date}. Genda {clinic} hanu. Obuhwezi bunaaza bworokera nawe eki.',
    },
}


@vax_bp.route('/')
@login_required
def index():
    children = ChildProfile.query.filter_by(parent_id=current_user.id).all()
    today = date.today()
    summary = []
    for child in children:
        vaccines = VaccineSchedule.query.filter_by(child_id=child.id).order_by(VaccineSchedule.due_date).all()
        next_vax = next((v for v in vaccines if not v.given and v.due_date >= today), None)
        overdue = [v for v in vaccines if not v.given and v.due_date < today]
        completed = [v for v in vaccines if v.given]
        age_days = (today - child.date_of_birth).days
        age_label = _age_label(age_days)
        summary.append({'child': child, 'vaccines': vaccines, 'next': next_vax,
                        'overdue': overdue, 'completed': completed,
                        'age_label': age_label, 'pct': int(len(completed)/len(vaccines)*100) if vaccines else 0})
    return render_template('vaccination/dashboard.html', summary=summary, today=today)


@vax_bp.route('/register', methods=['GET', 'POST'])
@login_required
def register_child():
    facilities = Facility.query.order_by(Facility.name).all()
    if request.method == 'POST':
        dob_str = request.form.get('date_of_birth', '')
        try:
            dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date of birth.', 'danger')
            return render_template('vaccination/register_child.html', facilities=facilities)

        child = ChildProfile(
            parent_id = current_user.id,
            name = request.form.get('name', '').strip(),
            date_of_birth = dob,
            gender = request.form.get('gender', ''),
            birth_weight_kg = request.form.get('birth_weight', type=float),
            facility_id = request.form.get('facility_id', type=int),
            preferred_language = request.form.get('language', 'English'),
        )
        db.session.add(child)
        db.session.flush()

        for entry in EPI_SCHEDULE:
            due = dob + timedelta(days=entry['days_after_birth'])
            db.session.add(VaccineSchedule(
                child_id = child.id,
                vaccine_name = entry['name'],
                dose_number = entry['dose'],
                due_date = due,
            ))

        db.session.commit()
        flash(f'{child.name}\'s vaccination schedule has been created with {len(EPI_SCHEDULE)} doses.', 'success')
        return redirect(url_for('vaccination.child_detail', child_id=child.id))

    return render_template('vaccination/register_child.html', facilities=facilities)


@vax_bp.route('/child/<int:child_id>')
@login_required
def child_detail(child_id):
    child = ChildProfile.query.get_or_404(child_id)
    if child.parent_id != current_user.id and current_user.role not in ('doctor','system_admin','district_officer'):
        flash('Not authorised.', 'danger')
        return redirect(url_for('vaccination.index'))
    vaccines = VaccineSchedule.query.filter_by(child_id=child.id).order_by(VaccineSchedule.due_date).all()
    today = date.today()
    age_days = (today - child.date_of_birth).days
    return render_template('vaccination/child_detail.html',
                           child=child, vaccines=vaccines, today=today,
                           age_label=_age_label(age_days))


@vax_bp.route('/vaccine/<int:vid>/given', methods=['POST'])
@login_required
def mark_given(vid):
    vax = VaccineSchedule.query.get_or_404(vid)
    child = ChildProfile.query.get(vax.child_id)
    if child.parent_id != current_user.id and current_user.role not in ('doctor','system_admin','staff'):
        flash('Not authorised.', 'danger')
        return redirect(url_for('vaccination.index'))
    vax.given = True
    vax.given_date = date.today()
    vax.batch_number = request.form.get('batch_number', '')
    vax.notes = request.form.get('notes', '')
    db.session.commit()
    flash(f'{vax.vaccine_name} dose {vax.dose_number} marked as given.', 'success')
    return redirect(url_for('vaccination.child_detail', child_id=child.id))


def send_vaccine_reminders(app):
    """Called hourly by scheduler — SMS parents 3 days before each vaccine."""
    with app.app_context():
        from app.services.sms import send_sms
        target = date.today() + timedelta(days=3)
        due_vaxes = VaccineSchedule.query.filter(
            VaccineSchedule.due_date == target,
            VaccineSchedule.given == False,
            VaccineSchedule.reminder_sent == False,
        ).all()
        for v in due_vaxes:
            child = v.child
            parent = child.parent
            if not parent or not parent.phone:
                continue
            lang = child.preferred_language if child.preferred_language in SMS_MESSAGES else 'English'
            clinic = child.facility.name if child.facility else 'your nearest health facility'
            msg = SMS_MESSAGES[lang]['reminder'].format(
                child = child.name,
                vaccine= v.vaccine_name,
                dose = v.dose_number,
                date = v.due_date.strftime('%d %b %Y'),
                clinic = clinic,
            )
            sent = send_sms(parent.phone, msg)
            if sent:
                v.reminder_sent = True
        db.session.commit()


def _age_label(days):
    if days < 7: return f'{days} day(s) old'
    if days < 30: return f'{days//7} week(s) old'
    if days < 365: return f'{days//30} month(s) old'
    return f'{days//365} year(s), {(days%365)//30} month(s) old'
