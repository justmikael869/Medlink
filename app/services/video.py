"""
Video consultation service — uses Daily.co free tier.
Set DAILY_API_KEY in .env for real rooms.
Without the key returns a simulated meeting link.
"""
import os, uuid, json
import urllib.request

DAILY_BASE = 'https://api.daily.co/v1'


def _key():
    return os.getenv('DAILY_API_KEY', '').strip()


def _simulation():
    return not _key()


def create_consultation_room(appointment_ref: str) -> dict:
    """
    Create a Daily.co video room for a consultation.
    Returns: {room_url, name, simulation}
    """
    if _simulation():
        # No DAILY_API_KEY set: this link will NOT open a real room.
        room_name = f'medlink-{appointment_ref.lower()}'
        return {
            'room_url': f'https://medlink-demo.daily.co/{room_name}',
            'name': room_name,
            'simulation': True,
            'note': 'Demo mode — sign up at daily.co and set DAILY_API_KEY for private rooms.',
        }

    room_name = f'medlink-{appointment_ref.lower()}-{uuid.uuid4().hex[:6]}'
    payload = json.dumps({
        'name': room_name,
        'privacy': 'public',
        'properties': {
            'exp': int(__import__('time').time()) + 86400, # 24h expiry
            'max_participants': 2,
            'enable_recording': False,
        },
    }).encode()
    req = urllib.request.Request(
        DAILY_BASE + '/rooms',
        data=payload,
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {_key()}'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            return {
                'room_url': data.get('url', ''),
                'name': room_name,
                'simulation': False,
            }
    except Exception as e:
        return {'room_url': '', 'name': '', 'simulation': False, 'error': str(e)}


def create_patient_token(room_name: str, patient_name: str) -> str:
    """Create a short-lived Daily.co token for the patient."""
    if _simulation():
        return ''
    payload = json.dumps({
        'properties': {
            'room_name': room_name,
            'is_owner': False,
            'user_name': patient_name,
            'exp': int(__import__('time').time()) + 7200,
        }
    }).encode()
    req = urllib.request.Request(
        DAILY_BASE + '/meeting-tokens',
        data=payload,
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {_key()}'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get('token', '')
    except Exception:
        return ''
