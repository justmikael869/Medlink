"""
Video consultation service: built-in WebRTC, no third-party video account.

The call itself is set up in app/sockets.py (signalling) and
app/static/js/medlink_video.js (browser side). This module only provides:

  * create_consultation_room(appointment): the address of the appointment's
    video room, saved on the appointment when the doctor confirms it.
  * get_ice_servers(): the network-helper servers the browsers use to find
    each other.

Optional environment variables (all can stay unset):
  TURN_URLS        comma-separated, e.g. "turn:relay.example.com:443?transport=tcp"
  TURN_USERNAME
  TURN_CREDENTIAL

Without TURN, calls connect directly between the two browsers using free
public STUN servers. That works on most home and office networks, but some
mobile networks block direct connections. A TURN relay fixes that; see the
note in README.md.
"""
import os

from flask import url_for

DEFAULT_STUN = [
    'stun:stun.l.google.com:19302',
    'stun:stun.cloudflare.com:3478',
]


def get_ice_servers() -> list:
    servers = [{'urls': DEFAULT_STUN}]
    turn_urls = [u.strip() for u in os.getenv('TURN_URLS', '').split(',') if u.strip()]
    if turn_urls:
        servers.append({
            'urls': turn_urls,
            'username': os.getenv('TURN_USERNAME', '').strip(),
            'credential': os.getenv('TURN_CREDENTIAL', '').strip(),
        })
    return servers


def create_consultation_room(appointment) -> dict:
    """Return the room address for a remote appointment.

    Nothing is created on any outside service: the room "exists" as soon as
    the appointment is confirmed, and only the appointment's patient and
    doctor are allowed into it. Must be called inside a request.
    """
    return {
        'room_url': url_for('telemedicine.video_room', appt_id=appointment.id),
        'name': f'medlink-{appointment.reference.lower()}',
        'simulation': False,
    }
