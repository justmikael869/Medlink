from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import login_required, current_user
from app import db
from app.models import (User, Facility, District, Appointment, Consultation,
                        Prescription, Medicine, Payment, PaymentAudit,
                        TriageAssessment, Notification, WalletTransaction,
                        DeliveryCompany)
from datetime import datetime, timedelta
import uuid, json

tele_bp = Blueprint('telemedicine', __name__, url_prefix='/telemedicine')

SPECIALISATIONS = [
    'General Practice', 'Paediatrics', 'Obstetrics & Gynaecology',
    'Internal Medicine', 'Surgery', 'Dermatology', 'Psychiatry & Mental Health',
    'Ophthalmology', 'ENT', 'Orthopaedics', 'Cardiology',
    'HIV/AIDS & Infectious Disease', 'Nutrition & Dietetics',
]

# ── Triage ────────────────────────────────────────────────────────────────────

@tele_bp.route('/triage', methods=['GET', 'POST'])
def triage():
    if request.method == 'POST':
        symptoms = request.form.get('symptoms', '').strip()
        duration = request.form.get('duration', '')
        sev_self = request.form.get('severity_self', 'mild')
        fever = request.form.get('fever') == 'yes'
        breathing = request.form.get('breathing') == 'yes'
        chest_pain = request.form.get('chest_pain') == 'yes'
        pregnancy = request.form.get('pregnancy') == 'yes'
        child = request.form.get('child') == 'yes'

        from app.services.ai_triage import assess_symptoms
        result = assess_symptoms(symptoms, duration, sev_self,
                                 fever, breathing, chest_pain, pregnancy, child)

        severity = result['severity']
        rec = result['recommendation']
        spec = result['specialisation']
        red_flags = result.get('red_flags', [])
        home_care = result.get('home_care')
        ai_powered = result.get('ai_powered', False)

        t = TriageAssessment(
            patient_id=current_user.id if current_user.is_authenticated else None,
            symptoms_text=symptoms,
            answers_json=json.dumps({'symptoms': symptoms, 'duration': duration,
                'self_severity': sev_self, 'fever': fever, 'breathing': breathing,
                'chest_pain': chest_pain, 'pregnancy': pregnancy, 'child': child,
                'ai_powered': ai_powered}),
            severity=severity, recommendation=rec, suggested_specialisation=spec,
        )
        db.session.add(t)
        db.session.commit()
        return render_template('telemedicine/triage_result.html',
                               severity=severity, recommendation=rec,
                               specialisation=spec, triage_id=t.id,
                               red_flags=red_flags, home_care=home_care,
                               ai_powered=ai_powered)
    return render_template('telemedicine/triage.html')


def _suggest_spec(s):
    s = s.lower()
    if any(w in s for w in ['rash','skin','itch','acne']): return 'Dermatology'
    if any(w in s for w in ['eye','vision','blind']): return 'Ophthalmology'
    if any(w in s for w in ['sad','depress','anxious','mental']): return 'Psychiatry & Mental Health'
    if any(w in s for w in ['child','baby','infant','toddler']): return 'Paediatrics'
    if any(w in s for w in ['pregnan','menstrual','period','womb']):return 'Obstetrics & Gynaecology'
    if any(w in s for w in ['hiv','aids','tb','malaria']): return 'HIV/AIDS & Infectious Disease'
    return 'General Practice'


# ── Doctor directory ──────────────────────────────────────────────────────────

@tele_bp.route('/doctors')
def doctor_list():
    spec = request.args.get('spec', '')
    district_id = request.args.get('district_id', type=int)

    q = User.query.filter_by(role='doctor', active=True, verified_doctor=True)
    if spec:
        q = q.filter(User.specialisation.ilike(f'%{spec}%'))
    doctors = q.all()

    if district_id:
        from app.models import doctor_districts
        filtered = []
        for d in doctors:
            rows = db.session.execute(
                doctor_districts.select().where(
                    doctor_districts.c.user_id == d.id,
                    doctor_districts.c.district_id == district_id
                )
            ).fetchall()
            if rows:
                filtered.append(d)
        doctors = filtered

    districts = District.query.order_by(District.name).all()
    return render_template('telemedicine/doctors.html',
                           doctors=doctors, specialisations=SPECIALISATIONS,
                           districts=districts, selected_spec=spec,
                           selected_district=district_id)


# ── Institution directory ─────────────────────────────────────────────────────

@tele_bp.route('/institutions')
def institution_list():
    district_id = request.args.get('district_id', type=int)
    facility_type = request.args.get('ftype', '')
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)

    q = Facility.query.filter_by(active=True, verified=True)
    if district_id:
        q = q.filter_by(district_id=district_id)
    if facility_type:
        q = q.filter_by(facility_type=facility_type)
    institutions = q.all()

    # Sort by distance if GPS provided
    if lat and lon:
        institutions.sort(key=lambda f: f.distance_km(lat, lon))

    districts = District.query.order_by(District.name).all()
    return render_template('telemedicine/institutions.html',
                           institutions=institutions, districts=districts,
                           selected_district=district_id,
                           selected_ftype=facility_type,
                           lat=lat, lon=lon)


# ── Book appointment ──────────────────────────────────────────────────────────
# Shared booking for both doctor (remote/in-person) and institution (in-person)

@tele_bp.route('/book-doctor/<int:doctor_id>', methods=['GET', 'POST'])
@login_required
def book_doctor(doctor_id):
    doctor = User.query.filter_by(id=doctor_id, role='doctor').first_or_404()
    return _handle_booking(request, doctor=doctor, facility=None)


@tele_bp.route('/book-institution/<int:facility_id>', methods=['GET', 'POST'])
@login_required
def book_institution(facility_id):
    facility = Facility.query.get_or_404(facility_id)
    return _handle_booking(request, doctor=None, facility=facility)


def _handle_booking(req, doctor=None, facility=None):
    if req.method == 'POST':
        appt_type = req.form.get('appt_type', 'in_person')
        slot_str = req.form.get('slot_time', '')
        notes = req.form.get('notes', '')
        dept = req.form.get('department', '')

        slot_time = None
        if slot_str:
            try:
                slot_time = datetime.strptime(slot_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('Invalid date/time format.', 'danger')
                return redirect(req.url)

        fee = (doctor.consultation_fee_ugx or 0) if doctor else 0

        payment = None
        if fee > 0 and doctor:
            if (current_user.wallet_balance_ugx or 0) < fee:
                flash('Insufficient wallet balance. Please top up your Health Wallet first.', 'danger')
                return redirect(url_for('telemedicine.wallet'))
            payment = Payment(
                idempotency_key=uuid.uuid4().hex,
                amount_ugx=fee,
                payment_type='consultation',
                status='held',
                payer_id=current_user.id,
                payee_id=doctor.id,
                notes=f'Consultation with Dr {doctor.name}',
            )
            payment.compute_fees()
            db.session.add(payment)
            db.session.flush()

            current_user.wallet_balance_ugx -= fee
            wt = WalletTransaction(
                user_id=current_user.id, tx_type='deduct',
                amount_ugx=fee,
                balance_after=current_user.wallet_balance_ugx,
                reference=payment.reference,
                note=f'Consultation — Dr {doctor.name}',
                payment_id=payment.id,
            )
            db.session.add(wt)
            db.session.add(PaymentAudit(
                payment_id=payment.id, event='created',
                old_status=None, new_status='held',
                actor_id=current_user.id,
                note=f'Booked consultation with Dr {doctor.name}',
            ))

        full_notes = notes
        if dept:
            full_notes = f'Department: {dept}\n{notes}'.strip()

        appt = Appointment(
            patient_id=current_user.id,
            doctor_id=doctor.id if doctor else None,
            facility_id=facility.id if facility else (doctor.facility_id if doctor else None),
            appt_type=appt_type,
            slot_time=slot_time,
            notes=full_notes,
            status='pending',
            payment_id=payment.id if payment else None,
        )
        db.session.add(appt)
        db.session.flush()
        appt.qr_code = appt.reference

        # Notify doctor or facility
        if doctor:
            db.session.add(Notification(
                recipient_user_id=doctor.id,
                title=f'New appointment from {current_user.name}',
                body=f'{"Remote" if appt_type=="remote" else "In-person"} — '
                     f'{slot_time.strftime("%d %b %Y %H:%M") if slot_time else "TBD"}',
                notif_type='appointment',
                related_appointment_id=appt.id,
            ))
        elif facility and facility.users:
            # Notify first facility admin
            fac_admin = next((u for u in facility.users if u.role in ('facility_admin','staff')), None)
            if fac_admin:
                db.session.add(Notification(
                    recipient_user_id=fac_admin.id,
                    title=f'New appointment: {current_user.name}',
                    body=f'Patient booked an in-person appointment'
                         f'{" for " + slot_time.strftime("%d %b %Y %H:%M") if slot_time else ""}.'
                         + (f' Dept: {dept}' if dept else ''),
                    notif_type='appointment',
                    related_appointment_id=appt.id,
                ))

        db.session.commit()
        flash(f'Appointment {appt.reference} booked successfully! '
              + (f'Fee of UGX {fee:,.0f} held in escrow.' if fee > 0 else
                 'Awaiting confirmation from the facility.'), 'success')
        return redirect(url_for('telemedicine.my_appointments'))

    # GET — build slot options
    slots = []
    now = datetime.utcnow()
    for day_offset in range(1, 8):
        day = now + timedelta(days=day_offset)
        for hour in range(8, 17):
            slots.append(day.replace(hour=hour, minute=0, second=0, microsecond=0))

    if doctor:
        return render_template('telemedicine/book_doctor.html',
                               doctor=doctor, slots=slots)
    else:
        return render_template('telemedicine/book_institution.html',
                               facility=facility, slots=slots)


# Keep old /book/<id> URL working (backward compat)
@tele_bp.route('/book/<int:doctor_id>', methods=['GET', 'POST'])
@login_required
def book(doctor_id):
    return book_doctor(doctor_id)


# ── Appointments ──────────────────────────────────────────────────────────────

@tele_bp.route('/appointments')
@login_required
def my_appointments():
    if current_user.role == 'doctor':
        appts = Appointment.query.filter_by(doctor_id=current_user.id)\
                                 .order_by(Appointment.created_at.desc()).all()
        title = 'My Patients'
    elif current_user.role in ('system_admin', 'district_officer'):
        appts = Appointment.query.order_by(Appointment.created_at.desc()).all()
        title = 'All Appointments'
    elif current_user.facility_id:
        appts = Appointment.query.filter_by(facility_id=current_user.facility_id)\
                                 .order_by(Appointment.created_at.desc()).all()
        title = 'Facility Appointments'
    else:
        appts = Appointment.query.filter_by(patient_id=current_user.id)\
                                 .order_by(Appointment.created_at.desc()).all()
        title = 'My Appointments'
    return render_template('telemedicine/appointments.html', appts=appts, title=title)


@tele_bp.route('/appointments/<int:appt_id>')
@login_required
def appointment_detail(appt_id):
    appt = Appointment.query.get_or_404(appt_id)
    return render_template('telemedicine/appt_detail.html', appt=appt)


@tele_bp.route('/appointments/<int:appt_id>/video')
@login_required
def video_room(appt_id):
    """The live video consultation page. Only this appointment's patient
    and doctor may open it."""
    appt = Appointment.query.get_or_404(appt_id)
    if current_user.id not in (appt.patient_id, appt.doctor_id):
        abort(403)
    if appt.appt_type != 'remote' or appt.status not in ('confirmed', 'in_progress'):
        flash('The video room opens once a remote appointment is confirmed.', 'warning')
        return redirect(url_for('telemedicine.appointment_detail', appt_id=appt.id))
    from app.services.video import get_ice_servers
    return render_template('telemedicine/video_room.html', appt=appt,
                           is_doctor=(current_user.id == appt.doctor_id),
                           ice_servers=get_ice_servers())


@tele_bp.route('/appointments/<int:appt_id>/confirm', methods=['POST'])
@login_required
def confirm_appointment(appt_id):
    appt = Appointment.query.get_or_404(appt_id)
    appt.status = 'confirmed'
    appt.updated_at = datetime.utcnow()

    # Video room for remote consultations (built-in WebRTC, see services/video.py)
    video_note = ''
    if appt.appt_type == 'remote':
        from app.services.video import create_consultation_room
        room = create_consultation_room(appt)
        appt.video_room_url = room['room_url']
        video_note = ' Video room is ready.'

    db.session.add(Notification(
        recipient_user_id=appt.patient_id,
        title='Appointment ' + appt.reference + ' confirmed',
        body='Your appointment has been confirmed'
             + (' for ' + appt.slot_time.strftime('%d %b %Y at %H:%M') + '.' if appt.slot_time else '.')
             + video_note,
        notif_type='appointment', related_appointment_id=appt.id,
    ))
    db.session.commit()

    # SMS confirmation to patient
    from app.services.sms import send_appointment_confirmed
    send_appointment_confirmed(appt)

    flash('Appointment confirmed. Patient has been notified.' + video_note, 'success')
    return redirect(url_for('telemedicine.appointment_detail', appt_id=appt_id))


@tele_bp.route('/appointments/<int:appt_id>/complete', methods=['GET', 'POST'])
@login_required
def complete_consultation(appt_id):
    appt = Appointment.query.get_or_404(appt_id)
    medicines = Medicine.query.order_by(Medicine.name).all()

    if request.method == 'POST':
        consult = appt.consultation or Consultation(appointment_id=appt.id)
        consult.started_at = appt.slot_time or datetime.utcnow()
        consult.ended_at = datetime.utcnow()
        consult.symptoms = request.form.get('symptoms', '')
        consult.diagnosis = request.form.get('diagnosis', '')
        consult.prescription_text = request.form.get('prescription_text', '')
        consult.doctor_notes = request.form.get('doctor_notes', '')
        # Follow-up date
        fud = request.form.get('follow_up_date', '')
        if fud:
            from datetime import datetime as _dt
            try: consult.follow_up_date = _dt.strptime(fud, '%Y-%m-%d')
            except ValueError: pass
        # Referral
        consult.referral_needed = request.form.get('referral_needed') == 'yes'
        consult.referral_reason = request.form.get('referral_reason', '')
        if consult.referral_needed:
            consult.referred_to_name = request.form.get('referred_to_name', '')

        if not appt.consultation:
            db.session.add(consult)
        db.session.flush()

        for mid, dos, frq, dur, pn in zip(
            request.form.getlist('med_id[]'),
            request.form.getlist('dosage[]'),
            request.form.getlist('frequency[]'),
            request.form.getlist('duration_days[]'),
            request.form.getlist('p_notes[]'),
        ):
            if mid:
                med = Medicine.query.get(int(mid)) if mid.isdigit() else None
                db.session.add(Prescription(
                    consultation_id=consult.id,
                    medicine_id=int(mid) if mid.isdigit() else None,
                    medicine_name=med.name if med else mid,
                    dosage=dos, frequency=frq,
                    duration_days=int(dur) if dur.isdigit() else None,
                    notes=pn,
                ))

        appt.status = 'completed'
        appt.updated_at = datetime.utcnow()
        db.session.add(Notification(
            recipient_user_id=appt.patient_id,
            title='Consultation complete — please confirm',
            body='Your doctor has completed the consultation and issued a prescription. '
                 'Please confirm to release payment.',
            notif_type='consultation_complete', related_appointment_id=appt.id,
        ))
        db.session.commit()

        # SMS: tell patient prescription is ready to download
        from app.services.sms import send_prescription_ready
        send_prescription_ready(appt)

        flash('Consultation completed. Patient notified to confirm.', 'success')
        return redirect(url_for('telemedicine.appointment_detail', appt_id=appt_id))

    return render_template('telemedicine/complete_consultation.html',
                           appt=appt, medicines=medicines)


@tele_bp.route('/appointments/<int:appt_id>/patient_confirm', methods=['POST'])
@login_required
def patient_confirm(appt_id):
    appt = Appointment.query.get_or_404(appt_id)
    if appt.patient_id != current_user.id:
        flash('Not authorised.', 'danger')
        return redirect(url_for('telemedicine.my_appointments'))

    if appt.consultation:
        appt.consultation.patient_confirmed_at = datetime.utcnow()

    if appt.payment and appt.payment.status == 'held':
        pay = appt.payment
        pay.status = 'released'
        pay.escrow_released_at = datetime.utcnow()
        pay.released_by_id = current_user.id

        doc = appt.doctor
        if doc:
            doc.wallet_balance_ugx = (doc.wallet_balance_ugx or 0) + pay.net_amount_ugx
            db.session.add(WalletTransaction(
                user_id=doc.id, tx_type='topup',
                amount_ugx=pay.net_amount_ugx,
                balance_after=doc.wallet_balance_ugx,
                reference=pay.reference,
                note=f'Consultation from {current_user.name}',
                payment_id=pay.id,
            ))
        db.session.add(PaymentAudit(
            payment_id=pay.id, event='released',
            old_status='held', new_status='released',
            actor_id=current_user.id, note='Patient confirmed',
        ))

    db.session.commit()
    flash('Thank you! Payment released to your doctor.', 'success')
    return redirect(url_for('telemedicine.my_appointments'))


# ── QR Check-in ───────────────────────────────────────────────────────────────

@tele_bp.route('/checkin', methods=['GET', 'POST'])
@login_required
def checkin():
    appt = None
    if request.method == 'POST':
        ref = request.form.get('qr_code', '').strip().upper()
        appt = Appointment.query.filter_by(qr_code=ref).first()
        if not appt:
            flash(f'No appointment found for code: {ref}', 'danger')
        else:
            appt.status = 'confirmed'
            appt.updated_at = datetime.utcnow()
            db.session.commit()
            flash(f'Patient {appt.patient.name} checked in for {appt.reference}.', 'success')
    return render_template('telemedicine/checkin.html', appt=appt)


# ── Health Wallet ─────────────────────────────────────────────────────────────

@tele_bp.route('/wallet')
@login_required
def wallet():
    txs = WalletTransaction.query.filter_by(user_id=current_user.id)\
                                  .order_by(WalletTransaction.created_at.desc()).limit(30).all()
    return render_template('telemedicine/wallet.html',
                           balance=current_user.wallet_balance_ugx or 0.0,
                           txs=txs)


@tele_bp.route('/wallet/topup', methods=['POST'])
@login_required
def wallet_topup():
    """
    Handles MTN MoMo, Airtel Money, PayPal, Visa/Mastercard top-ups.

    DEMO MODE (no API keys set):
      — Credits the wallet immediately and records the transaction.

    PRODUCTION (API keys in .env):
      MTN / Airtel → Flutterwave Uganda mobile money API
      PayPal → PayPal Orders v2 API (PAYPAL_CLIENT_ID / PAYPAL_SECRET)
      Card → Flutterwave card charge (FLUTTERWAVE_SECRET_KEY)

    To go live you will need:
      - Flutterwave account → https://dashboard.flutterwave.com (MTN, Airtel, Card)
      - PayPal Developer account → https://developer.paypal.com (PayPal)
      Register your business, get live API keys, add them to .env, and
      replace the demo block below with the real API calls.
    """
    amount = float(request.form.get('amount', 0) or 0)
    method = request.form.get('method', 'mtn_momo')
    phone = request.form.get('phone', '').strip()
    paypal_email = request.form.get('paypal_email', '').strip()
    card_name = request.form.get('card_name', '').strip()
    card_last4 = request.form.get('card_number', '').replace(' ','').strip()[-4:]

    if amount < 1000:
        flash('Minimum top-up is UGX 1,000.', 'danger')
        return redirect(url_for('telemedicine.wallet'))

    # ── Label + validation per method ────────────────────────────────────────
    if method in ('mtn_momo', 'airtel_money'):
        if not phone:
            flash('Please enter your mobile money number.', 'danger')
            return redirect(url_for('telemedicine.wallet'))
        network_label = 'MTN MoMo' if method == 'mtn_momo' else 'Airtel Money'
        note = f'{network_label} top-up · {phone}'
        extra = phone

    elif method == 'paypal':
        if not paypal_email:
            flash('Please enter your PayPal email address.', 'danger')
            return redirect(url_for('telemedicine.wallet'))
        # Convert UGX → USD at approx rate for display (PayPal charges in USD)
        usd_amount = round(amount / 3750, 2)
        network_label = 'PayPal'
        note = f'PayPal top-up · {paypal_email} · ~USD {usd_amount:,.2f}'
        extra = paypal_email

    elif method in ('visa', 'mastercard'):
        if not card_last4:
            flash('Please enter your card number.', 'danger')
            return redirect(url_for('telemedicine.wallet'))
        brand = 'Visa' if method == 'visa' else 'Mastercard'
        network_label = f'{brand} card'
        note = f'{brand} card top-up · **** {card_last4}'
        extra = f'**** {card_last4}'

    else:
        flash('Unknown payment method.', 'danger')
        return redirect(url_for('telemedicine.wallet'))

    # ── DEMO: credit immediately ──────────────────────────────────────────────
    # In production: call the relevant API, redirect to confirmation / webhook
    import os
    is_live = bool(
        os.environ.get('FLUTTERWAVE_SECRET_KEY') or
        os.environ.get('PAYPAL_CLIENT_ID')
    )

    if is_live:
        # TODO: initiate real payment and redirect to gateway
        flash('Live payment gateway not yet configured. Contact the system admin.', 'warning')
        return redirect(url_for('telemedicine.wallet'))

    ref = f'ML-{uuid.uuid4().hex[:8].upper()}'
    current_user.wallet_balance_ugx = (current_user.wallet_balance_ugx or 0) + amount
    if phone and not current_user.phone:
        current_user.phone = phone

    db.session.add(WalletTransaction(
        user_id = current_user.id,
        tx_type = 'topup',
        amount_ugx = amount,
        balance_after= current_user.wallet_balance_ugx,
        reference = ref,
        network = method,
        note = note,
    ))
    db.session.commit()

    flash(
        f'UGX {amount:,.0f} added via {network_label}. '
        f'Reference: {ref}',
        'success'
    )
    return redirect(url_for('telemedicine.wallet'))


# ── Doctor self-registration ──────────────────────────────────────────────────

@tele_bp.route('/register-doctor', methods=['GET', 'POST'])
@login_required
def register_doctor():
    districts = District.query.order_by(District.name).all()
    if request.method == 'POST':
        current_user.role = 'doctor'
        current_user.umdpc_number = request.form.get('umdpc_number', '').strip()
        current_user.specialisation = request.form.get('specialisation', '')
        current_user.languages = request.form.get('languages', '')
        current_user.consultation_fee_ugx = float(request.form.get('fee', 0) or 0)
        current_user.bio = request.form.get('bio', '')
        current_user.verified_doctor = False

        from app.models import doctor_districts
        db.session.execute(
            doctor_districts.delete().where(doctor_districts.c.user_id == current_user.id)
        )
        for did in request.form.getlist('district_ids'):
            db.session.execute(
                doctor_districts.insert().values(user_id=current_user.id, district_id=int(did))
            )
        db.session.commit()
        flash('Doctor profile submitted. Admin will verify your UMDPC number shortly.', 'info')
        return redirect(url_for('telemedicine.my_appointments'))
    return render_template('telemedicine/register_doctor.html',
                           districts=districts, specialisations=SPECIALISATIONS)


@tele_bp.route('/my-prescriptions')
@login_required
def my_prescriptions():
    from app.models import Consultation, Prescription
    # Get all consultations for this patient
    consults = db.session.query(Consultation)\
        .join(Appointment, Consultation.appointment_id == Appointment.id)\
        .filter(Appointment.patient_id == current_user.id)\
        .order_by(Consultation.created_at.desc()).all()
    return render_template('telemedicine/my_prescriptions.html', consults=consults)


@tele_bp.route('/consultation-history')
@login_required
def consultation_history():
    if current_user.role != 'doctor':
        return redirect(url_for('telemedicine.my_appointments'))
    appts = Appointment.query.filter_by(
        doctor_id=current_user.id, status='completed'
    ).order_by(Appointment.created_at.desc()).all()
    return render_template('telemedicine/consultation_history.html', appts=appts)


@tele_bp.route('/doctor-profile', methods=['GET', 'POST'])
@login_required
def doctor_profile():
    if current_user.role != 'doctor':
        return redirect(url_for('dashboard.index'))
    districts = District.query.order_by(District.name).all()
    if request.method == 'POST':
        current_user.specialisation = request.form.get('specialisation', '')
        current_user.languages = request.form.get('languages', '')
        current_user.consultation_fee_ugx = float(request.form.get('fee', 0) or 0)
        current_user.bio = request.form.get('bio', '')
        current_user.phone = request.form.get('phone', '')
        db.session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('telemedicine.doctor_profile'))
    return render_template('telemedicine/doctor_profile.html',
                           districts=districts, specialisations=SPECIALISATIONS)


@tele_bp.route('/health-record', methods=['GET', 'POST'])
@login_required
def health_record():
    if current_user.role != 'patient':
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        current_user.blood_type = request.form.get('blood_type', '')
        current_user.known_allergies = request.form.get('known_allergies', '')
        current_user.chronic_conditions = request.form.get('chronic_conditions', '')
        current_user.emergency_contact_name = request.form.get('emergency_contact_name', '')
        current_user.emergency_contact_phone = request.form.get('emergency_contact_phone', '')
        current_user.insurance_number = request.form.get('insurance_number', '')
        current_user.insurance_provider = request.form.get('insurance_provider', '')
        current_user.phone = request.form.get('phone', '')
        current_user.gender = request.form.get('gender', '')
        db.session.commit()
        flash('Health record updated.', 'success')
        return redirect(url_for('telemedicine.health_record'))

    # Gather recent appointments and prescriptions for the record summary
    recent_appts = Appointment.query.filter_by(
        patient_id=current_user.id
    ).order_by(Appointment.created_at.desc()).limit(5).all()

    all_rx = []
    for appt in Appointment.query.filter_by(patient_id=current_user.id, status='completed').all():
        if appt.consultation and appt.consultation.prescriptions:
            for rx in appt.consultation.prescriptions:
                all_rx.append({'rx': rx, 'appt': appt})
    all_rx = sorted(all_rx, key=lambda x: x['appt'].created_at, reverse=True)[:10]

    return render_template('telemedicine/health_record.html',
                           recent_appts=recent_appts, all_rx=all_rx)


@tele_bp.route('/prescriptions/<int:appt_id>/pdf')
@login_required
def prescription_pdf(appt_id):
    """Generate a downloadable prescription PDF for a completed appointment."""
    appt = Appointment.query.get_or_404(appt_id)

    # Only patient or the prescribing doctor can download
    if current_user.id not in (appt.patient_id, appt.doctor_id) and current_user.role != 'system_admin':
        flash('Not authorised.', 'danger')
        return redirect(url_for('telemedicine.appointment_detail', appt_id=appt_id))

    if not appt.consultation or not appt.consultation.prescriptions:
        flash('No prescription found for this appointment.', 'warning')
        return redirect(url_for('telemedicine.appointment_detail', appt_id=appt_id))

    from io import BytesIO
    from flask import make_response
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    primary_blue = colors.HexColor('#0f4c81')
    light_bg = colors.HexColor('#f0f7ff')

    title_style = ParagraphStyle('Title', parent=styles['Normal'], fontSize=20, textColor=primary_blue, spaceAfter=2, fontName='Helvetica-Bold', alignment=TA_CENTER)
    sub_style = ParagraphStyle('Sub', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#6b7280'), spaceAfter=8, alignment=TA_CENTER)
    label_style = ParagraphStyle('Label', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#6b7280'), spaceBefore=4)
    value_style = ParagraphStyle('Value', parent=styles['Normal'], fontSize=11, textColor=colors.black, spaceAfter=2, fontName='Helvetica-Bold')
    normal_style = ParagraphStyle('Normal2',parent=styles['Normal'], fontSize=10, spaceAfter=4)
    small_style = ParagraphStyle('Small', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#9ca3af'), alignment=TA_CENTER)

    doc_body = []

    # Header
    doc_body.append(Paragraph('MedLink Uganda', title_style))
    doc_body.append(Paragraph('Official Prescription', sub_style))
    doc_body.append(HRFlowable(width='100%', thickness=2, color=primary_blue, spaceAfter=12))

    # Doctor + patient info
    doc = appt.doctor
    consult = appt.consultation
    patient = appt.patient

    info_data = [
        ['PRESCRIBING DOCTOR', '', 'PATIENT', ''],
        [
            Paragraph(f'Dr. {doc.name if doc else "Unknown"}', value_style),
            '',
            Paragraph(patient.name, value_style),
            '',
        ],
        [
            Paragraph(f'UMDPC: {doc.umdpc_number or "N/A"}' if doc else 'N/A', normal_style),
            '',
            Paragraph(f'DOB: {patient.date_of_birth.strftime("%d %b %Y") if patient.date_of_birth else "N/A"}', normal_style),
            '',
        ],
        [
            Paragraph(f'Specialisation: {doc.specialisation or "General Practice"}' if doc else '', normal_style),
            '',
            Paragraph(f'Blood Type: {patient.blood_type or "N/A"}', normal_style),
            '',
        ],
    ]
    info_table = Table(info_data, colWidths=[8*cm, 0.5*cm, 8*cm, 0.5*cm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,0), light_bg),
        ('BACKGROUND', (2,0), (2,0), light_bg),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#6b7280')),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))
    doc_body.append(info_table)
    doc_body.append(Spacer(1, 10))

    # Appointment info
    doc_body.append(Paragraph(f'Appointment: <b>{appt.reference}</b> · Date: <b>{appt.slot_time.strftime("%d %B %Y") if appt.slot_time else appt.created_at.strftime("%d %B %Y")}</b> · Type: <b>{appt.appt_type.replace("_"," ").title()}</b>', normal_style))
    doc_body.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#e5e7eb'), spaceBefore=8, spaceAfter=8))

    # Diagnosis
    if consult.diagnosis:
        doc_body.append(Paragraph('DIAGNOSIS', ParagraphStyle('DLabel', parent=label_style, textColor=primary_blue, fontName='Helvetica-Bold')))
        doc_body.append(Paragraph(consult.diagnosis, normal_style))
        doc_body.append(Spacer(1, 6))

    # Prescribed medicines table
    doc_body.append(Paragraph('PRESCRIBED MEDICINES', ParagraphStyle('RxLabel', parent=label_style, textColor=primary_blue, fontName='Helvetica-Bold')))
    doc_body.append(Spacer(1, 4))

    rx_rows = [['Medicine', 'Dosage', 'Frequency', 'Duration', 'Instructions']]
    for rx in consult.prescriptions:
        rx_rows.append([
            Paragraph(rx.medicine_name or '—', normal_style),
            rx.dosage or '—',
            rx.frequency or '—',
            f'{rx.duration_days} days' if rx.duration_days else '—',
            rx.instructions or '—',
        ])

    rx_table = Table(rx_rows, colWidths=[5*cm, 2.5*cm, 3*cm, 2*cm, 4*cm])
    rx_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), primary_blue),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('FONTSIZE', (0,1), (-1,-1), 9),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, light_bg]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e5e7eb')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING',(0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
    ]))
    doc_body.append(rx_table)
    doc_body.append(Spacer(1, 12))

    # Follow-up
    if consult.follow_up_date:
        doc_body.append(Paragraph(f'Follow-up date: <b>{consult.follow_up_date.strftime("%d %B %Y")}</b>', normal_style))

    doc_body.append(Spacer(1, 20))
    doc_body.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#e5e7eb'), spaceAfter=8))

    # Doctor signature line
    sig_data = [['_______________________________', '', '_______________________________'],
                ['Doctor\'s Signature', '', 'Date']]
    sig_table = Table(sig_data, colWidths=[7*cm, 3*cm, 7*cm])
    sig_table.setStyle(TableStyle([
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('TEXTCOLOR', (0,1), (-1,1), colors.HexColor('#6b7280')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
    ]))
    doc_body.append(sig_table)
    doc_body.append(Spacer(1, 16))
    doc_body.append(Paragraph('This prescription was issued via MedLink Uganda · www.medlink.ug · Generated ' + datetime.utcnow().strftime('%d %b %Y'), small_style))

    # Build
    from reportlab.platypus import SimpleDocTemplate as RLDoc
    real_doc = RLDoc(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    real_doc.build(doc_body)

    buf.seek(0)
    response = make_response(buf.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=prescription_{appt.reference}.pdf'
    return response


@tele_bp.route('/referral/<int:appt_id>/pdf')
@login_required
def referral_letter_pdf(appt_id):
    """Generate a printable referral letter PDF."""
    appt = Appointment.query.get_or_404(appt_id)
    if current_user.id not in (appt.patient_id, appt.doctor_id) and current_user.role != 'system_admin':
        flash('Not authorised.', 'danger')
        return redirect(url_for('telemedicine.appointment_detail', appt_id=appt_id))

    consult = appt.consultation
    if not consult or not consult.referral_needed:
        flash('No referral on this appointment.', 'warning')
        return redirect(url_for('telemedicine.appointment_detail', appt_id=appt_id))

    from io import BytesIO
    from flask import make_response
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

    buf = BytesIO()
    styles = getSampleStyleSheet()
    primary = colors.HexColor('#0f4c81')
    light = colors.HexColor('#f0f7ff')

    title_s = ParagraphStyle('T', fontSize=16, textColor=primary, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=4)
    sub_s = ParagraphStyle('S', fontSize=10, textColor=colors.HexColor('#6b7280'), alignment=TA_CENTER, spaceAfter=6)
    head_s = ParagraphStyle('H', fontSize=10, textColor=colors.HexColor('#6b7280'), fontName='Helvetica', spaceBefore=12, spaceAfter=2)
    body_s = ParagraphStyle('B', fontSize=11, textColor=colors.black, spaceAfter=6, leading=16)
    bold_s = ParagraphStyle('Bo', fontSize=11, textColor=colors.black, fontName='Helvetica-Bold', spaceAfter=4)
    justify_s= ParagraphStyle('J', fontSize=11, textColor=colors.black, spaceAfter=8, leading=16, alignment=TA_JUSTIFY)
    small_s = ParagraphStyle('Sm', fontSize=8, textColor=colors.HexColor('#9ca3af'), alignment=TA_CENTER)

    content = []
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2.5*cm, rightMargin=2.5*cm, topMargin=2*cm, bottomMargin=2*cm)

    content.append(Paragraph('MedLink Uganda', title_s))
    content.append(Paragraph('MEDICAL REFERRAL LETTER', ParagraphStyle('RT', fontSize=13, textColor=colors.HexColor('#374151'), fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=4)))
    content.append(Paragraph(f'Date: {datetime.utcnow().strftime("%d %B %Y")} · Ref: {appt.reference}', sub_s))
    content.append(HRFlowable(width='100%', thickness=2, color=primary, spaceAfter=14))

    # To/From
    dr = appt.doctor
    to_facility = consult.referred_to_name or (consult.referred_facility.name if consult.referred_facility else 'Specialist Facility')
    content.append(Paragraph('TO:', head_s))
    content.append(Paragraph(f'The Receiving Clinician / Specialist<br/><b>{to_facility}</b>', body_s))
    content.append(Paragraph('FROM:', head_s))
    content.append(Paragraph(f'<b>Dr. {dr.name}</b><br/>{dr.specialisation or "General Practice"} · UMDPC: {dr.umdpc_number or "N/A"}' if dr else 'MedLink Uganda Telemedicine', body_s))

    content.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#e5e7eb'), spaceBefore=8, spaceAfter=10))

    # Patient details
    content.append(Paragraph('PATIENT DETAILS', ParagraphStyle('PH', fontSize=9, textColor=colors.HexColor('#6b7280'), fontName='Helvetica', spaceAfter=6)))
    p = appt.patient
    patient_rows = [
        ['Full name', p.name, 'Blood type', p.blood_type or 'Unknown'],
        ['Date of birth', p.date_of_birth.strftime('%d %b %Y') if p.date_of_birth else 'N/A', 'Gender', p.gender.title() if p.gender else 'N/A'],
        ['Phone', p.phone or 'N/A', 'Insurance', f'{p.insurance_provider or "—"} {p.insurance_number or ""}'],
    ]
    if p.known_allergies:
        patient_rows.append(['Known allergies', p.known_allergies, '', ''])
    if p.chronic_conditions:
        patient_rows.append(['Chronic conditions', p.chronic_conditions, '', ''])

    pt = Table(patient_rows, colWidths=[3.5*cm, 6*cm, 3*cm, 4*cm])
    pt.setStyle(TableStyle([
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor('#6b7280')),
        ('TEXTCOLOR', (2,0), (2,-1), colors.HexColor('#6b7280')),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica'),
        ('FONTNAME', (2,0), (2,-1), 'Helvetica'),
        ('FONTNAME', (1,0), (1,-1), 'Helvetica-Bold'),
        ('FONTNAME', (3,0), (3,-1), 'Helvetica-Bold'),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, light]),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#e5e7eb')),
    ]))
    content.append(pt)
    content.append(Spacer(1, 12))

    # Clinical section
    if consult.diagnosis:
        content.append(Paragraph('DIAGNOSIS', head_s))
        content.append(Paragraph(consult.diagnosis, bold_s))

    content.append(Paragraph('REASON FOR REFERRAL', head_s))
    content.append(Paragraph(consult.referral_reason or 'Further specialist assessment required.', justify_s))

    if consult.prescription_text:
        content.append(Paragraph('CURRENT TREATMENT', head_s))
        content.append(Paragraph(consult.prescription_text, justify_s))

    content.append(Spacer(1, 20))
    content.append(Paragraph(
        'I would be grateful for your specialist assessment and management of this patient. '
        'Please do not hesitate to contact me for any further information.',
        justify_s
    ))

    content.append(Spacer(1, 24))
    content.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#e5e7eb'), spaceAfter=8))

    # Signature
    sig_data = [['_______________________________', '', '_______________________________'],
                [f'Dr. {dr.name}' if dr else 'Clinician', '', 'Date']]
    sig_table = Table(sig_data, colWidths=[7*cm, 3*cm, 7*cm])
    sig_table.setStyle(TableStyle([
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('TEXTCOLOR', (0,1), (-1,1), colors.HexColor('#6b7280')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
    ]))
    content.append(sig_table)
    content.append(Spacer(1, 14))
    content.append(Paragraph(f'Issued via MedLink Uganda · medlink.ug · {datetime.utcnow().strftime("%d %b %Y %H:%M")} UTC', small_s))

    doc.build(content)
    buf.seek(0)
    resp = make_response(buf.read())
    resp.headers['Content-Type'] = 'application/pdf'
    resp.headers['Content-Disposition'] = f'attachment; filename=referral_{appt.reference}.pdf'
    return resp
