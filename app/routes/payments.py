from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Payment, PaymentAudit, WalletTransaction, User
from datetime import datetime

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')


@payments_bp.route('/')
@login_required
def index():
    if current_user.role in ('system_admin',):
        payments = Payment.query.order_by(Payment.created_at.desc()).limit(100).all()
    else:
        payments = Payment.query.filter(
            (Payment.payer_id == current_user.id) | (Payment.payee_id == current_user.id)
        ).order_by(Payment.created_at.desc()).all()
    return render_template('payments/index.html', payments=payments)


@payments_bp.route('/<int:pay_id>')
@login_required
def detail(pay_id):
    pay = Payment.query.get_or_404(pay_id)
    return render_template('payments/detail.html', pay=pay)


@payments_bp.route('/<int:pay_id>/release', methods=['POST'])
@login_required
def manual_release(pay_id):
    """Admin-only manual escrow release."""
    if current_user.role != 'system_admin':
        flash('Admin only.', 'danger')
        return redirect(url_for('payments.detail', pay_id=pay_id))
    pay = Payment.query.get_or_404(pay_id)
    if pay.status != 'held':
        flash('Payment is not in escrow.', 'warning')
        return redirect(url_for('payments.detail', pay_id=pay_id))

    pay.status = 'released'
    pay.escrow_released_at = datetime.utcnow()
    pay.released_by_id = current_user.id

    if pay.payee_id:
        payee = User.query.get(pay.payee_id)
        if payee:
            payee.wallet_balance_ugx = (payee.wallet_balance_ugx or 0) + pay.net_amount_ugx
            wt = WalletTransaction(
                user_id=payee.id, tx_type='topup',
                amount_ugx=pay.net_amount_ugx,
                balance_after=payee.wallet_balance_ugx,
                reference=pay.reference, note='Admin manual release',
                payment_id=pay.id,
            )
            db.session.add(wt)

    audit = PaymentAudit(
        payment_id=pay.id, event='released',
        old_status='held', new_status='released',
        actor_id=current_user.id, note='Admin manual release',
    )
    db.session.add(audit)
    db.session.commit()
    flash('Payment released to payee wallet.', 'success')
    return redirect(url_for('payments.detail', pay_id=pay_id))


@payments_bp.route('/audit')
@login_required
def audit_log():
    if current_user.role != 'system_admin':
        flash('Admin only.', 'danger')
        return redirect(url_for('dashboard.index'))
    audits = PaymentAudit.query.order_by(PaymentAudit.created_at.desc()).limit(200).all()
    return render_template('payments/audit.html', audits=audits)


# ── Webhook stub (Flutterwave / Pesapal) ─────────────────────────────────────

@payments_bp.route('/webhook', methods=['POST'])
def webhook():
    """
    Production: verify HMAC-SHA256 signature from gateway.
    For demo this just logs incoming payloads.
    """
    import hmac, hashlib, os
    secret = os.getenv('PAYMENT_WEBHOOK_SECRET', 'demo-secret')
    sig = request.headers.get('verif-hash') or request.headers.get('x-flutterwave-signature', '')
    expected = hmac.new(secret.encode(), request.data, hashlib.sha256).hexdigest()
    if sig and sig != expected:
        return jsonify({'status': 'invalid signature'}), 401

    data = request.get_json(silent=True) or {}
    ref = data.get('data', {}).get('tx_ref') or data.get('txRef', '')
    status = data.get('data', {}).get('status') or data.get('status', '')

    if ref and status == 'successful':
        pay = Payment.query.filter_by(reference=ref).first()
        if pay and pay.status == 'pending':
            pay.status = 'held'
            pay.gateway_response = str(data)
            audit = PaymentAudit(
                payment_id=pay.id, event='payment_received',
                old_status='pending', new_status='held',
                note='Webhook confirmation from gateway',
            )
            db.session.add(audit)
            db.session.commit()

    return jsonify({'status': 'ok'})
