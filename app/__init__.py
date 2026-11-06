from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_cors import CORS
from flask_socketio import SocketIO
from dotenv import load_dotenv
import os

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
# Real-time channel used only for video-call signalling (app/sockets.py).
# 'threading' mode needs no extra server software; it matches the gunicorn
# gthread setup in the Procfile.
socketio = SocketIO()


def _database_url():
    """Read DATABASE_URL and make it SQLAlchemy/psycopg2 friendly.

    - Supabase/Heroku-style 'postgres://' is rewritten to 'postgresql://'
    - sslmode=require is added for remote Postgres hosts (Supabase needs SSL)
    - Falls back to local SQLite if DATABASE_URL is not set (local dev)
    """
    url = os.getenv('DATABASE_URL', '').strip()
    if not url:
        return 'sqlite:///medlink.db'
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    if url.startswith('postgresql://'):
        url = 'postgresql+psycopg2://' + url[len('postgresql://'):]
    if url.startswith('postgresql') and 'sslmode=' not in url:
        host = url.split('@')[-1].split('/')[0]
        if not any(h in host for h in ('localhost', '127.0.0.1')):
            url += ('&' if '?' in url else '?') + 'sslmode=require'
    return url

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-in-production')
    app.config['SQLALCHEMY_DATABASE_URI'] = _database_url()
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    # Pooler-friendly engine settings (Supabase pooler / PgBouncer drops idle
    # connections, so test each connection before use and recycle often).
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 280,
        'pool_size': int(os.getenv('DB_POOL_SIZE', '3')),
        'max_overflow': int(os.getenv('DB_MAX_OVERFLOW', '2')),
    } if not _database_url().startswith('sqlite') else {}

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    CORS(app)
    socketio.init_app(app, async_mode='threading', cors_allowed_origins='*')
    from app import sockets  # noqa: F401  (registers the video-call handlers)

    from app.routes.pages import pages_bp
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.inventory import inventory_bp
    from app.routes.search import search_bp
    from app.routes.orders import orders_bp
    from app.routes.alerts import alerts_bp
    from app.routes.admin import admin_bp
    from app.routes.api import api_bp
    from app.routes.notifications import notifications_bp
    from app.routes.analytics import analytics_bp
    from app.routes.telemedicine import tele_bp
    from app.routes.messaging import msg_bp
    from app.routes.supplier import supplier_bp
    from app.routes.delivery import delivery_bp
    from app.routes.payments import payments_bp
    from app.routes.ussd import ussd_bp
    from app.routes.verify import verify_bp
    from app.routes.maternal import maternal_bp
    from app.routes.mentalhealth import mh_bp
    from app.routes.blood import blood_bp
    from app.routes.vaccination import vax_bp
    from app.routes.hiv import hiv_bp

    for bp in [pages_bp, auth_bp, dashboard_bp, inventory_bp, search_bp,
               orders_bp, alerts_bp, admin_bp, api_bp,
               notifications_bp, analytics_bp,
               tele_bp, delivery_bp, payments_bp,
               msg_bp, supplier_bp, ussd_bp,
               verify_bp, maternal_bp, mh_bp,
               blood_bp, vax_bp, hiv_bp]:
        app.register_blueprint(bp)

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from datetime import datetime as _dt
        ctx = {'unread_notifications': 0, 'pending_appt_count': 0, 'unread_messages': 0, 'now': _dt.utcnow()}
        if current_user.is_authenticated:
            try:
                from app.models import Appointment, Message
                ctx['unread_messages'] = Message.query.filter_by(
                    recipient_id=current_user.id, is_read=False).count()
                if current_user.role in ('staff','facility_admin','system_admin','district_officer'):
                    from app.intelligence import get_unread_count
                    ctx['unread_notifications'] = get_unread_count(current_user)
                if current_user.role == 'doctor':
                    ctx['pending_appt_count'] = Appointment.query.filter_by(
                        doctor_id=current_user.id, status='pending').count()
            except Exception:
                pass
        return ctx

    with app.app_context():
        try:
            db.create_all()
        except Exception as e:  # e.g. another worker created the tables first
            db.session.rollback()
            print(f'[db] create_all warning: {e}')

    # Background thread: send SMS reminders 24h before appointments (checks every hour)
    if os.getenv('ENABLE_SCHEDULER', 'true').lower() == 'true':
        _start_reminder_scheduler(app)

    return app


def _start_reminder_scheduler(app):
    """Start a lightweight background thread to send appointment reminder SMS."""
    import threading, time as _time

    def _run():
        _time.sleep(30) # Wait for app to fully start before first run
        while True:
            try:
                with app.app_context():
                    from app.models import Appointment
                    from app.services.sms import send_appointment_reminder
                    from datetime import datetime, timedelta

                    # Find confirmed appointments 23–25 hours from now (window avoids duplicates)
                    now = datetime.utcnow()
                    win_from = now + timedelta(hours=23)
                    win_to = now + timedelta(hours=25)

                    upcoming = Appointment.query.filter(
                        Appointment.status == 'confirmed',
                        Appointment.slot_time >= win_from,
                        Appointment.slot_time <= win_to,
                        Appointment.reminder_sent == False,
                    ).all()

                    for appt in upcoming:
                        sent = send_appointment_reminder(appt)
                        if sent:
                            appt.reminder_sent = True
                    db.session.commit()

                    # ANC reminders for maternal health
                    from app.routes.maternal import send_anc_reminders
                    send_anc_reminders(app)

                    # Vaccination reminders
                    from app.routes.vaccination import send_vaccine_reminders
                    send_vaccine_reminders(app)

                    # ART refill reminders
                    from app.routes.hiv import send_art_reminders
                    send_art_reminders(app)
            except Exception as e:
                print(f'[reminder_scheduler] Error: {e}')
            _time.sleep(3600) # Check every hour

    t = threading.Thread(target=_run, daemon=True, name='reminder-scheduler')
    t.start()
