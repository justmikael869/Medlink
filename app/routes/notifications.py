from flask import Blueprint, render_template, redirect, url_for, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Notification, RestockSuggestion

notifications_bp = Blueprint('notifications', __name__, url_prefix='/notifications')


@notifications_bp.route('/')
@login_required
def index():
    from app.intelligence import get_notifications_for_user
    notifs = get_notifications_for_user(current_user, limit=50)

    # Mark all as read
    for n in notifs:
        n.is_read = True
    db.session.commit()

    # Also fetch restock suggestions for this facility
    suggestions = []
    if current_user.facility_id:
        suggestions = RestockSuggestion.query.filter_by(
            facility_id=current_user.facility_id,
            status='pending'
        ).order_by(RestockSuggestion.created_at.desc()).all()

    return render_template('notifications/index.html',
                           notifications=notifs, suggestions=suggestions)


@notifications_bp.route('/suggestions/<int:sid>/accept', methods=['POST'])
@login_required
def accept_suggestion(sid):
    from app.intelligence import accept_restock_suggestion
    order = accept_restock_suggestion(sid, current_user)
    if order:
        from flask import flash
        flash(f'Order {order.order_number} placed automatically!', 'success')
        return redirect(url_for('orders.detail', order_id=order.id))
    from flask import flash
    flash('Could not convert suggestion to order.', 'danger')
    return redirect(url_for('notifications.index'))


@notifications_bp.route('/suggestions/<int:sid>/dismiss', methods=['POST'])
@login_required
def dismiss_suggestion(sid):
    s = RestockSuggestion.query.get_or_404(sid)
    s.status = 'dismissed'
    db.session.commit()
    from flask import flash
    flash('Suggestion dismissed.', 'info')
    return redirect(url_for('notifications.index'))


@notifications_bp.route('/api/count')
@login_required
def count():
    from app.intelligence import get_unread_count
    return jsonify({'count': get_unread_count(current_user)})


@notifications_bp.route('/expiry-check', methods=['POST'])
@login_required
def run_expiry_check():
    """Manual trigger for expiry check (admins only). In production use a scheduler."""
    if current_user.role not in ('system_admin', 'district_officer'):
        return redirect(url_for('dashboard.index'))
    from app.intelligence import check_expiry_alerts
    raised = check_expiry_alerts(days_ahead=90)
    from flask import flash
    flash(f'Expiry check complete. {raised} new expiry alert(s) raised.', 'success')
    return redirect(url_for('notifications.index'))
