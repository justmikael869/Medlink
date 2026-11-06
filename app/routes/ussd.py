"""
MedLink Uganda — USSD / SMS / IVR Offline Access Layer
=======================================================

HOW IT WORKS FOR USERS WITHOUT SMARTPHONES:
  1. Patient dials *280# on any basic phone (MTN/Airtel/UTL)
  2. The telco sends a POST to /ussd/session with the dial string
  3. MedLink responds with a menu (max 182 chars per USSD frame)
  4. Patient navigates with number keys — no internet, no app needed

PRODUCTION INTEGRATION:
  - Africa's Talking USSD API (register at africastalking.com)
  - Add AT_USERNAME and AT_API_KEY to .env
  - Point your Africa's Talking USSD service callback to:
      https://yourdomain.com/ussd/session
  - SMS notifications use the same Africa's Talking SMS API

DEMO MODE:
  - POST /ussd/session with form fields: sessionId, phoneNumber,
    serviceCode, text — returns CON or END frames you can test manually
  - Web simulator at /ussd/simulator for live demo during the championship
"""

from flask import Blueprint, request, render_template, jsonify
from app import db
from app.models import (
    User, Facility, Medicine, StockItem, District,
    Appointment, Notification, WalletTransaction
)
from datetime import datetime
import uuid, os

ussd_bp = Blueprint('ussd', __name__, url_prefix='/ussd')


# ─────────────────────────────────────────────────────────────────────────────
# USSD SESSION HANDLER (Africa's Talking callback endpoint)
# ─────────────────────────────────────────────────────────────────────────────

@ussd_bp.route('/session', methods=['POST'])
def ussd_session():
    """
    Africa's Talking USSD gateway posts here on every keypress.
    Response must start with CON (continue menu) or END (close session).
    Max 182 characters per frame.
    """
    session_id = request.form.get('sessionId', '')
    phone = request.form.get('phoneNumber', '').replace('+256', '0')
    service_code = request.form.get('serviceCode', '*280#')
    text = request.form.get('text', '') # full dial string e.g. "1*2*3"

    # Parse navigation path
    parts = [p for p in text.split('*') if p] if text else []
    level = len(parts)

    # ── Level 0: Main menu ──────────────────────────────────────────────────
    if level == 0:
        return ussd(
            "CON Welcome to MedLink Uganda\n"
            "1. Find nearest medicine\n"
            "2. Book a doctor\n"
            "3. My appointments\n"
            "4. Check wallet balance\n"
            "5. Report medicine shortage\n"
            "6. Emergency contacts"
        )

    choice_1 = parts[0] if level >= 1 else ''

    # ── 1: Find nearest medicine ────────────────────────────────────────────
    if choice_1 == '1':
        if level == 1:
            return ussd("CON Find Medicine\nType medicine name:")

        med_name = parts[1] if level >= 2 else ''

        if level == 2:
            # Search for the medicine — explicit join to avoid ambiguous FK
            results = (
                db.session.query(StockItem)
                .join(Medicine, StockItem.medicine_id == Medicine.id)
                .join(Facility, StockItem.facility_id == Facility.id)
                .filter(
                    Medicine.name.ilike(f'%{med_name}%'),
                    StockItem.quantity > 0,
                    Facility.verified == True,
                )
                .order_by(StockItem.quantity.desc())
                .limit(5)
                .all()
            )
            if not results:
                return ussd(
                    f"END No stock found for '{med_name}'.\n"
                    "A shortage alert has been logged.\n"
                    "Dial *280# again to search."
                )
            # Build response list
            lines = [f"CON Results for {med_name}:"]
            for i, item in enumerate(results[:4], 1):
                dist = item.facility.district.name if item.facility.district else 'Unknown'
                lines.append(f"{i}. {item.facility.name[:20]} - {dist} ({item.quantity} units)")
            lines.append("0. Back")
            return ussd('\n'.join(lines))

    # ── 2: Book a doctor ────────────────────────────────────────────────────
    elif choice_1 == '2':
        if level == 1:
            # List available doctors
            doctors = User.query.filter_by(
                role='doctor', verified_doctor=True, active=True
            ).limit(6).all()
            if not doctors:
                return ussd("END No doctors available right now.\nDial *280# to try again.")
            lines = ["CON Choose a Doctor:"]
            for i, doc in enumerate(doctors, 1):
                spec = (doc.specialisation or 'General')[:15]
                fee = int(doc.consultation_fee_ugx or 0)
                lines.append(f"{i}. Dr {doc.name.split()[0]} ({spec}) UGX {fee:,}")
            return ussd('\n'.join(lines))

        if level == 2:
            doctors = User.query.filter_by(
                role='doctor', verified_doctor=True, active=True
            ).limit(6).all()
            try:
                doc = doctors[int(parts[1]) - 1]
            except (IndexError, ValueError):
                return ussd("END Invalid choice. Dial *280# to try again.")

            return ussd(
                f"CON Book Dr {doc.name}\n"
                f"Fee: UGX {int(doc.consultation_fee_ugx or 0):,}\n"
                "1. Confirm booking\n"
                "2. Cancel"
            )

        if level == 3 and parts[2] == '1':
            doctors = User.query.filter_by(
                role='doctor', verified_doctor=True, active=True
            ).limit(6).all()
            try:
                doc = doctors[int(parts[1]) - 1]
            except (IndexError, ValueError):
                return ussd("END Error. Dial *280# to try again.")

            # Find or create patient user by phone
            patient = User.query.filter_by(phone=f'+256{phone.lstrip("0")}').first()
            if not patient:
                patient = User.query.filter_by(phone=phone).first()

            if patient:
                appt = Appointment(
                    patient_id = patient.id,
                    doctor_id = doc.id,
                    appt_type = 'in_person',
                    status = 'pending',
                    reason = 'Booked via USSD *280#',
                    scheduled_at= datetime.utcnow(),
                )
                db.session.add(appt)
                # Notify doctor
                db.session.add(Notification(
                    recipient_user_id = doc.id,
                    title = 'New USSD Appointment',
                    body = f'Patient {phone} booked via *280# USSD',
                    notif_type = 'appointment',
                ))
                db.session.commit()
                # Send SMS confirmation (Africa's Talking in production)
                _send_sms(
                    f'+256{phone.lstrip("0")}',
                    f'MedLink: Your appointment with Dr {doc.name} is confirmed. '
                    f'Reference: APT-{appt.id}. Call 0800-MEDLINK for help.'
                )
                return ussd(
                    f"END Appointment booked!\n"
                    f"Dr {doc.name.split()[0]}\n"
                    f"Ref: APT-{appt.id}\n"
                    "SMS confirmation sent."
                )
            else:
                return ussd(
                    "END Phone not registered.\n"
                    "Visit medlink.ug to create\n"
                    "an account, then try again."
                )

    # ── 3: My appointments ──────────────────────────────────────────────────
    elif choice_1 == '3':
        patient = _find_user_by_phone(phone)
        if not patient:
            return ussd("END No account found for this number.\nVisit medlink.ug to register.")
        appts = Appointment.query.filter_by(
            patient_id=patient.id, status='confirmed'
        ).order_by(Appointment.scheduled_at).limit(3).all()
        if not appts:
            return ussd("END No upcoming appointments.\nDial *280# to book one.")
        lines = ["END Your appointments:"]
        for a in appts:
            doc = a.doctor.name.split()[0] if a.doctor else '?'
            date = a.scheduled_at.strftime('%d %b') if a.scheduled_at else 'TBD'
            lines.append(f"Dr {doc} — {date}")
        return ussd('\n'.join(lines))

    # ── 4: Wallet balance ───────────────────────────────────────────────────
    elif choice_1 == '4':
        patient = _find_user_by_phone(phone)
        if not patient:
            return ussd("END No account found.\nVisit medlink.ug to register.")
        bal = int(patient.wallet_balance_ugx or 0)
        return ussd(
            f"END MedLink Wallet Balance:\n"
            f"UGX {bal:,}\n"
            f"Account: {patient.name}\n"
            "To top up, dial *165# (MTN MoMo)\nor *185# (Airtel Money)"
        )

    # ── 5: Report shortage ──────────────────────────────────────────────────
    elif choice_1 == '5':
        if level == 1:
            return ussd("CON Report Medicine Shortage\nType medicine name:")
        if level == 2:
            med_name = parts[1]
            from app.models import SearchGap
            gap = SearchGap(
                search_query = med_name,
                search_type = 'medicine',
            )
            db.session.add(gap)
            db.session.commit()
            return ussd(
                f"END Shortage of '{med_name}' reported.\n"
                "The district health officer\nhas been notified.\nThank you."
            )

    # ── 6: Emergency contacts ───────────────────────────────────────────────
    elif choice_1 == '6':
        return ussd(
            "END Emergency Contacts Uganda:\n"
            "Ambulance: 0800-211-911\n"
            "Police: 999\n"
            "Red Cross: 0414-258-701\n"
            "MedLink Help: 0800-MEDLINK"
        )

    return ussd("END Invalid option.\nDial *280# to start again.")


# ─────────────────────────────────────────────────────────────────────────────
# SMS WEBHOOK (Africa's Talking inbound SMS)
# ─────────────────────────────────────────────────────────────────────────────

@ussd_bp.route('/sms/incoming', methods=['POST'])
def sms_incoming():
    """
    Africa's Talking sends inbound SMS here.
    Patients can text keywords to a shortcode e.g. 8080.

    Keywords:
      FIND [medicine] → nearest stock
      BOOK [doctor name] → initiate booking
      BAL → wallet balance
      HELP → instructions
    """
    from_number = request.form.get('from', '')
    message = (request.form.get('text') or '').strip().upper()
    parts = message.split(None, 1)
    keyword = parts[0] if parts else ''
    body = parts[1] if len(parts) > 1 else ''

    if keyword == 'HELP' or not keyword:
        reply = (
            "MedLink Uganda SMS Help:\n"
            "FIND [medicine] - find nearest stock\n"
            "BOOK [doctor] - book appointment\n"
            "BAL - check wallet\n"
            "Or dial *280# from any phone"
        )
    elif keyword == 'FIND':
        if not body:
            reply = "Please text: FIND [medicine name]\nExample: FIND Paracetamol"
        else:
            items = (
                db.session.query(StockItem)
                .join(Medicine, StockItem.medicine_id == Medicine.id)
                .join(Facility, StockItem.facility_id == Facility.id)
                .filter(Medicine.name.ilike(f'%{body}%'), StockItem.quantity > 0)
                .limit(3).all()
            )
            if not items:
                reply = f"No stock found for {body}. Try another name or dial *280#"
            else:
                lines = [f"MedLink: {body} available at:"]
                for it in items:
                    dist = it.facility.district.name if it.facility.district else ''
                    lines.append(f"- {it.facility.name}, {dist} ({it.quantity} units)")
                reply = '\n'.join(lines)

    elif keyword == 'BAL':
        user = _find_user_by_phone(from_number)
        if user:
            reply = f"MedLink Wallet: UGX {int(user.wallet_balance_ugx or 0):,} - {user.name}"
        else:
            reply = "No MedLink account found. Register at medlink.ug"

    elif keyword == 'BOOK':
        reply = (
            f"To book with a doctor, dial *280# from your phone "
            f"and choose option 2. Or visit medlink.ug"
        )
    else:
        reply = "Unknown command. Text HELP for instructions or dial *280#"

    # Send SMS reply (Africa's Talking in production, log in demo)
    _send_sms(from_number, reply)
    return '', 200


# ─────────────────────────────────────────────────────────────────────────────
# USSD SIMULATOR (for live demo at the championship)
# ─────────────────────────────────────────────────────────────────────────────

@ussd_bp.route('/simulator')
def ussd_simulator():
    """Interactive USSD phone simulator — for championship demo."""
    return render_template('ussd/simulator.html')


@ussd_bp.route('/simulator/send', methods=['POST'])
def ussd_simulator_send():
    """Simulator calls this with each keypress."""
    data = request.get_json() or {}
    session_id = data.get('sessionId', f'SIM-{uuid.uuid4().hex[:8]}')
    phone = data.get('phone', '+256700000000')
    text = data.get('text', '')

    from flask import current_app
    with current_app.test_request_context(
        '/ussd/session', method='POST',
        data={
            'sessionId': session_id,
            'phoneNumber': phone,
            'serviceCode': '*280#',
            'text': text,
        },
        content_type='application/x-www-form-urlencoded'
    ):
        # Push app context so db queries work
        response_obj = ussd_session()
        response_text = response_obj.get_data(as_text=True)

    return jsonify({'response': response_text})


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def ussd(text):
    """Return a plain-text USSD response."""
    from flask import Response
    return Response(text, mimetype='text/plain')


def _find_user_by_phone(phone):
    """Find a user by phone in various formats."""
    normalized = phone.lstrip('+').lstrip('256').lstrip('0')
    return (
        User.query.filter(
            db.or_(
                User.phone == phone,
                User.phone == f'+256{normalized}',
                User.phone == f'0{normalized}',
            )
        ).first()
    )


def _send_sms(to, message):
    """
    Send an SMS via Africa's Talking.
    In demo mode (no AT_API_KEY), logs to console.
    In production: pip install africastalking, set AT_USERNAME + AT_API_KEY in .env
    """
    at_key = os.environ.get('AT_API_KEY')
    at_username = os.environ.get('AT_USERNAME', 'sandbox')

    if at_key:
        try:
            import africastalking
            africastalking.initialize(at_username, at_key)
            sms = africastalking.SMS
            sms.send(message, [to], sender_id='MedLink')
        except Exception as e:
            print(f'[SMS] Failed to send to {to}: {e}')
    else:
        # Demo: just log it
        print(f'[SMS DEMO] To: {to}\n{message}\n')
