"""
Video consultation signalling (WebRTC over Socket.IO).

Ported from the Liwec project's sockets.py. The server only relays
"signalling" messages (offers, answers, network candidates). The audio and
video themselves flow directly between the two browsers, so no paid video
service or API key is needed.

Differences from Liwec, because a consultation is always exactly two people:
  * The room is the appointment, and only that appointment's patient and
    doctor may enter it (checked on every event, not just on page load).
  * No waiting-room approval step: nobody else is allowed in anyway, so the
    first person simply waits until the other arrives.
  * Recording, reactions, hand-raise and call time limits are left out.
"""
from flask import request
from flask_login import current_user
from flask_socketio import join_room, emit

from app import socketio
from app.models import Appointment

# sid -> {"appt_id": int, "user_id": int, "name": str, "is_doctor": bool}
# In-memory on purpose: gunicorn runs a single worker (see Procfile), and a
# call only lives as long as its two browser tabs anyway.
CONNECTED = {}


def _room(appt_id):
    return f'appt-{appt_id}'


def _authorised_appointment(appt_id):
    """Return the Appointment if the current user may be in its video room."""
    if not current_user.is_authenticated:
        return None
    try:
        appt = Appointment.query.get(int(appt_id))
    except (TypeError, ValueError):
        return None
    if not appt or appt.appt_type != 'remote':
        return None
    if appt.status not in ('confirmed', 'in_progress'):
        return None
    if current_user.id not in (appt.patient_id, appt.doctor_id):
        return None
    return appt


def _display_name(appt):
    if appt.doctor_id == current_user.id:
        return f'Dr. {current_user.name}'
    return current_user.name


def _my_info():
    return CONNECTED.get(request.sid)


@socketio.on('join')
def handle_join(data):
    appt = _authorised_appointment((data or {}).get('appt_id'))
    if not appt:
        emit('join_denied', {})
        return

    sid = request.sid
    room = _room(appt.id)

    # Same person opened the room twice (second tab, or a page refresh whose
    # old connection hasn't timed out yet): the newest connection wins.
    for old_sid, info in list(CONNECTED.items()):
        if (old_sid != sid and info['appt_id'] == appt.id
                and info['user_id'] == current_user.id):
            CONNECTED.pop(old_sid, None)
            emit('replaced', {}, to=old_sid)
            emit('peer_left', {'sid': old_sid}, to=room)

    existing = [
        {'sid': s, 'name': i['name'], 'is_doctor': i['is_doctor']}
        for s, i in CONNECTED.items()
        if i['appt_id'] == appt.id and s != sid
    ]

    is_doctor = appt.doctor_id == current_user.id
    CONNECTED[sid] = {
        'appt_id': appt.id,
        'user_id': current_user.id,
        'name': _display_name(appt),
        'is_doctor': is_doctor,
    }
    join_room(room)

    # The newcomer calls everyone already present (see medlink_video.js).
    emit('existing_peers', {'peers': existing})
    emit('peer_joined',
         {'sid': sid, 'name': CONNECTED[sid]['name'], 'is_doctor': is_doctor},
         to=room, include_self=False)


@socketio.on('signal')
def handle_signal(data):
    """Relay an offer / answer / candidate to one other person in the room."""
    me = _my_info()
    target = (data or {}).get('target')
    other = CONNECTED.get(target)
    # Only relay inside the sender's own appointment room.
    if not me or not other or other['appt_id'] != me['appt_id']:
        return
    emit('signal', {'sender': request.sid, 'signal': data.get('signal')}, to=target)


@socketio.on('chat_message')
def handle_chat(data):
    me = _my_info()
    if not me:
        return
    text = str((data or {}).get('message', '')).strip()[:2000]
    if not text:
        return
    emit('chat_message', {'sid': request.sid, 'name': me['name'], 'message': text},
         to=_room(me['appt_id']))


@socketio.on('media_state')
def handle_media_state(data):
    """Mic / camera on-off, so the other side can show a muted or
    camera-off indicator (WebRTC itself doesn't announce that)."""
    me = _my_info()
    if not me:
        return
    data = data or {}
    emit('media_state',
         {'sid': request.sid, 'audio': bool(data.get('audio')),
          'video': bool(data.get('video'))},
         to=_room(me['appt_id']), include_self=False)


@socketio.on('screen_share')
def handle_screen_share(data):
    me = _my_info()
    if not me:
        return
    emit('screen_share',
         {'sid': request.sid, 'sharing': bool((data or {}).get('sharing'))},
         to=_room(me['appt_id']), include_self=False)


@socketio.on('leave')
def handle_leave():
    _drop(request.sid)


@socketio.on('disconnect')
def handle_disconnect():
    _drop(request.sid)


def _drop(sid):
    info = CONNECTED.pop(sid, None)
    if info:
        emit('peer_left', {'sid': sid}, to=_room(info['appt_id']))
