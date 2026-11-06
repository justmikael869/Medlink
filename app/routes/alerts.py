from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.models import Alert, Medicine, Facility
from datetime import datetime

alerts_bp = Blueprint('alerts', __name__, url_prefix='/alerts')

@alerts_bp.route('/')
@login_required
def index():
    fid = current_user.facility_id
    is_adm = current_user.role in ('system_admin', 'district_officer')
    status = request.args.get('status', 'open')
    sev = request.args.get('severity', '')
    src = request.args.get('source', '')

    q = Alert.query if is_adm else Alert.query.filter_by(facility_id=fid)
    if status: q = q.filter_by(status=status)
    if sev: q = q.filter_by(severity=sev)
    if src: q = q.filter_by(source=src)
    alerts = q.order_by(Alert.created_at.desc()).all()

    # Chart data — severity breakdown for current filter scope
    import json
    from sqlalchemy import func
    from datetime import datetime, timedelta

    base_q = Alert.query if is_adm else Alert.query.filter_by(facility_id=fid)
    sev_counts = dict(base_q.filter_by(status='open')
        .with_entities(Alert.severity, func.count(Alert.id))
        .group_by(Alert.severity).all())

    status_counts = dict(
        (Alert.query if is_adm else Alert.query.filter_by(facility_id=fid))
        .with_entities(Alert.status, func.count(Alert.id))
        .group_by(Alert.status).all()
    )

    # Alert trend last 14 days
    labels_14 = [(datetime.utcnow()-timedelta(days=i)).strftime('%d %b') for i in range(13,-1,-1)]
    trend_14 = []
    for i in range(13, -1, -1):
        d = datetime.utcnow() - timedelta(days=i)
        s = d.replace(hour=0,minute=0,second=0,microsecond=0)
        e = s + timedelta(days=1)
        qbase = Alert.query if is_adm else Alert.query.filter_by(facility_id=fid)
        trend_14.append(qbase.filter(Alert.created_at>=s, Alert.created_at<e).count())

    return render_template('alerts/index.html', alerts=alerts,
                           status_filter=status, sev_filter=sev, src_filter=src,
                           sev_counts=json.dumps(sev_counts),
                           status_counts=json.dumps(status_counts),
                           labels_14=json.dumps(labels_14),
                           trend_14=json.dumps(trend_14))


@alerts_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    medicines = Medicine.query.order_by(Medicine.name).all()
    facilities = Facility.query.filter_by(active=True).all() \
        if current_user.role in ('system_admin','district_officer') else None

    if request.method == 'POST':
        from app.intelligence import notify_distributor_of_alert, trigger_restock_suggestion
        fid = int(request.form.get('facility_id') or current_user.facility_id)
        notify_dist = 'notify_distributor' in request.form
        notify_gov = 'notify_district' in request.form

        a = Alert(
            facility_id = fid,
            medicine_id = int(request.form.get('medicine_id')),
            raised_by = current_user.id,
            severity = request.form.get('severity','medium'),
            quantity_needed = int(request.form.get('quantity_needed') or 0) or None,
            note = request.form.get('note','').strip(),
            source = 'manual',
            notify_district = notify_gov,
            notify_distributor = notify_dist,
        )
        db.session.add(a)
        db.session.flush()

        if notify_dist:
            count = notify_distributor_of_alert(a)
            flash(f'Alert raised. {count} distributor(s) notified.', 'success')
        else:
            flash('Alert raised.', 'success')

        # Also trigger restock suggestion if critical
        if a.severity == 'critical':
            from app.models import StockItem
            stock = StockItem.query.filter_by(
                facility_id=fid, medicine_id=a.medicine_id
            ).first()
            if stock:
                trigger_restock_suggestion(stock, a)

        db.session.commit()
        return redirect(url_for('alerts.index'))

    return render_template('alerts/new.html', medicines=medicines, facilities=facilities)


@alerts_bp.route('/<int:aid>/resolve', methods=['GET','POST'])
@login_required
def resolve(aid):
    alert = Alert.query.get_or_404(aid)
    if request.method == 'POST':
        alert.status = 'resolved'
        alert.resolved_by = current_user.id
        alert.resolved_at = datetime.utcnow()
        alert.resolution_note = request.form.get('note','')
        db.session.commit()
        flash('Alert resolved.', 'success')
        return redirect(url_for('alerts.index'))
    return render_template('alerts/resolve.html', alert=alert)


@alerts_bp.route('/<int:aid>/acknowledge', methods=['POST'])
@login_required
def acknowledge(aid):
    a = Alert.query.get_or_404(aid)
    a.status = 'acknowledged'
    db.session.commit()
    flash('Alert acknowledged.', 'info')
    return redirect(url_for('alerts.index'))
