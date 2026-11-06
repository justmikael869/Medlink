"""
MedLink SMS Service (Africa's Talking)
=======================================
Centralised SMS helper used by telemedicine, USSD, and any other module.

Set AT_USERNAME and AT_API_KEY in .env for live SMS.
Without credentials, all messages are logged to the console (demo mode).
"""
import os, logging

logger = logging.getLogger('medlink.sms')

AT_KEY = os.environ.get('AT_API_KEY', '')
AT_USERNAME = os.environ.get('AT_USERNAME', 'sandbox')
AT_ENABLED = bool(AT_KEY)


def send_sms(to: str, message: str) -> bool:
    """
    Send an SMS to a single phone number.
    Returns True if sent (or demo-logged), False on hard error.
    """
    if not to:
        return False

    # Normalise Ugandan numbers to international format
    to = _normalise_phone(to)

    if AT_ENABLED:
        try:
            import africastalking
            africastalking.initialize(AT_USERNAME, AT_KEY)
            sms = africastalking.SMS
            sms.send(message, [to], sender_id='MedLink')
            logger.info(f'[SMS] Sent to {to}')
            return True
        except Exception as e:
            logger.error(f'[SMS] Failed to {to}: {e}')
            return False
    else:
        # Demo / dev — just print so judges can see it in the console
        print(f'\n[SMS DEMO] ─────────────────────────')
        print(f' To : {to}')
        print(f' Msg: {message}')
        print(f'────────────────────────────────────\n')
        return True


def send_appointment_reminder(appointment) -> bool:
    """Send a 24-hour reminder SMS to the patient for a confirmed appointment."""
    patient = appointment.patient
    phone = patient.phone if patient else None
    if not phone:
        return False

    doctor_name = f'Dr. {appointment.doctor.name}' if appointment.doctor else 'your doctor'
    slot = appointment.slot_time
    time_str = slot.strftime('%A %d %b %Y at %I:%M %p') if slot else 'your scheduled time'
    appt_type = appointment.appt_type.replace('_', ' ').title()

    message = (
        f'MedLink Reminder: Your {appt_type} appointment with {doctor_name} '
        f'is on {time_str}. Ref: {appointment.reference}. '
        f'Reply HELP to {"+256800100066"} for assistance.'
    )
    return send_sms(phone, message)


def send_appointment_confirmed(appointment) -> bool:
    """Notify patient immediately when their appointment is confirmed."""
    patient = appointment.patient
    phone = patient.phone if patient else None
    if not phone:
        return False

    doctor_name = f'Dr. {appointment.doctor.name}' if appointment.doctor else 'your doctor'
    slot = appointment.slot_time
    time_str = slot.strftime('%d %b %Y at %I:%M %p') if slot else 'TBD'
    appt_type = appointment.appt_type.replace('_', ' ').title()

    msg = 'VIDEO CALL - ' if appointment.appt_type == 'remote' and appointment.video_room_url else ''

    message = (
        f'MedLink: {msg}Appointment CONFIRMED. '
        f'{appt_type} with {doctor_name} on {time_str}. '
        f'Ref: {appointment.reference}. '
        f'Visit medlink.ug to view details.'
    )
    return send_sms(phone, message)


def send_prescription_ready(appointment) -> bool:
    """Notify patient when their prescription is ready to download."""
    patient = appointment.patient
    phone = patient.phone if patient else None
    if not phone:
        return False

    message = (
        f'MedLink: Your prescription from {appointment.reference} is ready. '
        f'Log in to medlink.ug to download your prescription PDF and present it at any pharmacy.'
    )
    return send_sms(phone, message)


def _normalise_phone(phone: str) -> str:
    """Convert Ugandan numbers to +256 international format."""
    p = ''.join(c for c in phone if c.isdigit() or c == '+')
    if p.startswith('0') and len(p) == 10:
        p = '+256' + p[1:]
    elif p.startswith('256') and not p.startswith('+'):
        p = '+' + p
    return p
