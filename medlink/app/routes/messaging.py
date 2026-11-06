from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.models import Message, User, Appointment, Order, Notification, Facility
from datetime import datetime

msg_bp = Blueprint('messaging', __name__, url_prefix='/messages')


def _notify(recipient_id, title, body, msg_id=None):
    db.session.add(Notification(
        recipient_user_id=recipient_id,
        title=title, body=body,
        notif_type='message',
        related_message_id=msg_id,
    ))


@msg_bp.route('/')
@login_required
def inbox():
    messages = Message.query.filter_by(
        recipient_id=current_user.id
    ).order_by(Message.created_at.desc()).all()
    unread = sum(1 for m in messages if not m.is_read)
    return render_template('messaging/inbox.html',
                           messages=messages, unread=unread)


@msg_bp.route('/sent')
@login_required
def sent():
    messages = Message.query.filter_by(
        sender_id=current_user.id
    ).order_by(Message.created_at.desc()).all()
    return render_template('messaging/sent.html', messages=messages)


@msg_bp.route('/compose', methods=['GET', 'POST'])
@login_required
def compose():
    # Pre-fill recipient if provided
    recipient_id = request.args.get('to', type=int)
    appt_id = request.args.get('appt', type=int)
    order_id = request.args.get('order', type=int)
    msg_type = request.args.get('type', 'general')

    recipient = User.query.get(recipient_id) if recipient_id else None
    appt = Appointment.query.get(appt_id) if appt_id else None
    order_obj = Order.query.get(order_id) if order_id else None

    # Build recipient options based on role
    if current_user.role == 'patient':
        # Can message their doctors and pharmacists
        candidates = User.query.filter(
            User.role.in_(['doctor','pharmacist','staff']),
            User.active == True
        ).all()
    elif current_user.role == 'doctor':
        # Can message patients, pharmacists, suppliers, other doctors
        candidates = User.query.filter(
            User.role.in_(['patient','pharmacist','supplier','doctor','staff']),
            User.active == True
        ).all()
    elif current_user.role in ('pharmacist', 'staff', 'facility_admin'):
        # Can message doctors, suppliers, patients, drivers
        candidates = User.query.filter(
            User.role.in_(['doctor','supplier','patient','driver','system_admin']),
            User.active == True
        ).all()
    elif current_user.role == 'supplier':
        # Can message pharmacists, facility admins
        candidates = User.query.filter(
            User.role.in_(['pharmacist','facility_admin','staff','system_admin']),
            User.active == True
        ).all()
    elif current_user.role == 'system_admin':
        candidates = User.query.filter(User.active == True).all()
    else:
        candidates = []

    if request.method == 'POST':
        to_id = int(request.form.get('recipient_id', 0))
        subject = request.form.get('subject', '').strip()
        body = request.form.get('body', '').strip()
        mtype = request.form.get('msg_type', 'general')
        a_id = request.form.get('appointment_id', type=int)
        o_id = request.form.get('order_id', type=int)

        if not to_id or not body:
            flash('Recipient and message body are required.', 'danger')
            return redirect(request.url)

        rec = User.query.get(to_id)
        if not rec:
            flash('Recipient not found.', 'danger')
            return redirect(request.url)

        m = Message(
            sender_id=current_user.id,
            recipient_id=to_id,
            subject=subject or f'Message from {current_user.name}',
            body=body,
            msg_type=mtype,
            related_appointment_id=a_id,
            related_order_id=o_id,
        )
        db.session.add(m)
        db.session.flush()

        _notify(to_id,
                f'New message from {current_user.name}',
                subject or body[:80],
                msg_id=m.id)
        db.session.commit()
        flash(f'Message sent to {rec.name}.', 'success')
        return redirect(url_for('messaging.inbox'))

    return render_template('messaging/compose.html',
                           candidates=candidates, recipient=recipient,
                           appt=appt, order_obj=order_obj,
                           prefill_type=msg_type)


@msg_bp.route('/<int:msg_id>')
@login_required
def view(msg_id):
    m = Message.query.get_or_404(msg_id)
    if m.recipient_id != current_user.id and m.sender_id != current_user.id:
        flash('Not authorised.', 'danger')
        return redirect(url_for('messaging.inbox'))
    if m.recipient_id == current_user.id and not m.is_read:
        m.is_read = True
        m.read_at = datetime.utcnow()
        db.session.commit()
    return render_template('messaging/view.html', message=m)


@msg_bp.route('/<int:msg_id>/reply', methods=['POST'])
@login_required
def reply(msg_id):
    orig = Message.query.get_or_404(msg_id)
    body = request.form.get('body', '').strip()
    if not body:
        flash('Reply cannot be empty.', 'danger')
        return redirect(url_for('messaging.view', msg_id=msg_id))

    to_id = orig.sender_id if orig.recipient_id == current_user.id else orig.recipient_id
    m = Message(
        sender_id=current_user.id,
        recipient_id=to_id,
        subject='Re: ' + (orig.subject or ''),
        body=body,
        msg_type=orig.msg_type,
        related_appointment_id=orig.related_appointment_id,
        related_order_id=orig.related_order_id,
    )
    db.session.add(m)
    db.session.flush()
    _notify(to_id, f'Reply from {current_user.name}',
            body[:80], msg_id=m.id)
    db.session.commit()
    flash('Reply sent.', 'success')
    return redirect(url_for('messaging.view', msg_id=msg_id))
