from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models import (StockItem, Alert, Order, Appointment,
                        DeliveryOrder, Payment, WalletTransaction, User)
from datetime import datetime, timedelta
from sqlalchemy import func
import json

dashboard_bp = Blueprint('dashboard', __name__)

def _last_7_labels():
    return [(datetime.utcnow() - timedelta(days=i)).strftime('%d %b') for i in range(6,-1,-1)]

def _daily_counts(model, date_col, filter_kwargs, days=7):
    counts = []
    for i in range(days-1, -1, -1):
        d = datetime.utcnow() - timedelta(days=i)
        start = d.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        q = db.session.query(func.count(model.id)).filter(date_col >= start, date_col < end)
        for k, v in filter_kwargs.items():
            q = q.filter(getattr(model, k) == v)
        counts.append(q.scalar() or 0)
    return counts

@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
@login_required
def index():
    role = current_user.role
    labels = _last_7_labels()

    # ── PATIENT ──────────────────────────────────────────────────────────────
    if role == 'patient':
        upcoming = Appointment.query.filter_by(patient_id=current_user.id)\
            .filter(Appointment.status.in_(['pending','confirmed']))\
            .order_by(Appointment.slot_time).limit(3).all()

        recent_deliveries = DeliveryOrder.query.filter_by(patient_id=current_user.id)\
            .order_by(DeliveryOrder.created_at.desc()).limit(3).all()

        wallet_bal = current_user.wallet_balance_ugx or 0.0

        recent_tx = WalletTransaction.query.filter_by(user_id=current_user.id)\
            .order_by(WalletTransaction.created_at.desc()).limit(10).all()

        topup_data = _daily_counts(WalletTransaction, WalletTransaction.created_at,
                                   {'user_id': current_user.id, 'tx_type': 'topup'})
        spend_data = _daily_counts(WalletTransaction, WalletTransaction.created_at,
                                   {'user_id': current_user.id, 'tx_type': 'payment'})

        appt_statuses = dict(db.session.query(Appointment.status, func.count(Appointment.id))
            .filter_by(patient_id=current_user.id).group_by(Appointment.status).all())

        # New features: maternal profile + next ANC visit
        from app.models import MaternalProfile, ANCVisit
        from datetime import date
        maternal = MaternalProfile.query.filter_by(patient_id=current_user.id).first()
        next_anc = None
        if maternal:
            next_anc = ANCVisit.query.filter_by(
                profile_id=maternal.id, completed=False
            ).filter(ANCVisit.due_date >= date.today()).order_by(ANCVisit.due_date).first()

        return render_template('dashboard/patient.html',
            upcoming=upcoming, recent_deliveries=recent_deliveries,
            wallet_bal=wallet_bal, recent_tx=recent_tx,
            labels_7=json.dumps(labels),
            topup_data=json.dumps(topup_data),
            spend_data=json.dumps(spend_data),
            appt_statuses=json.dumps(appt_statuses),
            maternal=maternal, next_anc=next_anc,
        )

    # ── DOCTOR ───────────────────────────────────────────────────────────────
    elif role == 'doctor':
        pending = Appointment.query.filter_by(doctor_id=current_user.id, status='pending')\
            .order_by(Appointment.created_at.desc()).all()

        today = datetime.utcnow().replace(hour=0, minute=0, second=0)
        today_appts = Appointment.query.filter_by(doctor_id=current_user.id, status='confirmed')\
            .filter(Appointment.slot_time >= today,
                    Appointment.slot_time < today + timedelta(days=1)).all()

        total_consults = Appointment.query.filter_by(
            doctor_id=current_user.id, status='completed').count()

        wallet_bal = current_user.wallet_balance_ugx or 0.0
        held = db.session.query(func.sum(Payment.amount_ugx))\
            .filter_by(payee_id=current_user.id, status='held').scalar() or 0

        consult_trend = _daily_counts(Appointment, Appointment.created_at,
                                      {'doctor_id': current_user.id, 'status': 'completed'})

        type_breakdown = dict(db.session.query(Appointment.appt_type, func.count(Appointment.id))
            .filter_by(doctor_id=current_user.id).group_by(Appointment.appt_type).all())

        earnings_trend = []
        for i in range(6, -1, -1):
            d = datetime.utcnow() - timedelta(days=i)
            s = d.replace(hour=0,minute=0,second=0,microsecond=0)
            e = s + timedelta(days=1)
            amt = db.session.query(func.sum(Payment.net_amount_ugx))\
                .filter(Payment.payee_id==current_user.id, Payment.status=='released',
                        Payment.created_at>=s, Payment.created_at<e).scalar() or 0
            earnings_trend.append(float(amt))

        return render_template('dashboard/doctor.html',
            pending=pending, today_appts=today_appts,
            total_consults=total_consults, wallet_bal=wallet_bal, held=held,
            labels_7=json.dumps(labels),
            consult_trend=json.dumps(consult_trend),
            type_breakdown=json.dumps(type_breakdown),
            earnings_trend=json.dumps(earnings_trend),
        )

    # ── SUPPLIER ─────────────────────────────────────────────────────────────
    elif role == 'supplier':
        return redirect(url_for('supplier.distributor_dashboard'))

    # ── DRIVER ───────────────────────────────────────────────────────────────
    elif role == 'driver':
        return redirect(url_for('delivery.driver_dashboard'))

    # ── COMPANY MANAGER ──────────────────────────────────────────────────────
    elif role == 'company_manager':
        return redirect(url_for('delivery.company_dashboard'))

    # ── FACILITY STAFF / ADMIN ───────────────────────────────────────────────
    elif role in ('staff', 'facility_admin'):
        fid = current_user.facility_id
        items = StockItem.query.filter_by(facility_id=fid).all() if fid else []
        out_of_stock = sum(1 for i in items if i.quantity <= 0)
        low_stock = sum(1 for i in items if 0 < i.quantity <= i.minimum_threshold)
        ok_stock = len(items) - out_of_stock - low_stock
        open_alerts = Alert.query.filter_by(facility_id=fid, status='open').count() if fid else 0
        critical = Alert.query.filter_by(facility_id=fid, status='open', severity='critical').count() if fid else 0
        pending_orders = Order.query.filter_by(buyer_facility_id=fid, status='pending').count() if fid else 0

        today_appts = Appointment.query.filter_by(facility_id=fid)\
            .filter(Appointment.status.in_(['pending','confirmed']))\
            .order_by(Appointment.slot_time).limit(8).all() if fid else []

        recent_alerts = Alert.query.filter_by(facility_id=fid, status='open')\
            .order_by(Alert.created_at.desc()).limit(5).all() if fid else []

        from app.models import StockTransaction
        dispense_trend = []
        for i in range(6, -1, -1):
            d = datetime.utcnow() - timedelta(days=i)
            s = d.replace(hour=0,minute=0,second=0,microsecond=0)
            e = s + timedelta(days=1)
            count = db.session.query(func.count(StockTransaction.id))\
                .join(StockItem, StockTransaction.stock_item_id == StockItem.id)\
                .filter(StockItem.facility_id == fid,
                        StockTransaction.transaction_type == 'dispensed',
                        StockTransaction.created_at >= s,
                        StockTransaction.created_at < e).scalar() or 0 if fid else 0
            dispense_trend.append(count)

        top_items = sorted(items, key=lambda x: x.quantity, reverse=True)[:6]
        top_names = json.dumps([i.medicine.name[:16] for i in top_items])
        top_qtys = json.dumps([i.quantity for i in top_items])

        sev_counts = dict(db.session.query(Alert.severity, func.count(Alert.id))
            .filter_by(facility_id=fid, status='open').group_by(Alert.severity).all()) if fid else {}

        return render_template('dashboard/facility.html',
            out_of_stock=out_of_stock, low_stock=low_stock,
            open_alerts=open_alerts, critical=critical,
            pending_orders=pending_orders, today_appts=today_appts, recent_alerts=recent_alerts,
            labels_7=json.dumps(labels),
            stock_donut=json.dumps([ok_stock, low_stock, out_of_stock]),
            dispense_trend=json.dumps(dispense_trend),
            top_names=top_names, top_qtys=top_qtys,
            sev_counts=json.dumps(sev_counts),
        )

    # ── DISTRICT OFFICER ─────────────────────────────────────────────────────
    elif role == 'district_officer':
        total_alerts = Alert.query.filter_by(status='open').count()
        critical_alerts = Alert.query.filter_by(status='open', severity='critical').count()
        out_districts = db.session.query(StockItem.facility_id, func.count())\
            .filter(StockItem.quantity == 0).group_by(StockItem.facility_id).count()

        recent_alerts = Alert.query.filter_by(status='open')\
            .order_by(Alert.created_at.desc()).limit(8).all()

        from app.models import SearchGap
        top_gaps = SearchGap.query.order_by(SearchGap.count.desc()).limit(10).all()

        alert_trend = _daily_counts(Alert, Alert.created_at, {'status': 'open'})

        sev_breakdown = dict(db.session.query(Alert.severity, func.count(Alert.id))
            .filter_by(status='open').group_by(Alert.severity).all())

        from app.models import Facility
        fac_alerts = db.session.query(Alert.facility_id, func.count(Alert.id).label('cnt'))\
            .filter_by(status='open').group_by(Alert.facility_id)\
            .order_by(func.count(Alert.id).desc()).limit(5).all()
        fac_names_list = []
        fac_counts_list = []
        for fac_id, cnt in fac_alerts:
            f = Facility.query.get(fac_id)
            fac_names_list.append(f.name[:20] if f else str(fac_id))
            fac_counts_list.append(cnt)

        return render_template('dashboard/district.html',
            total_alerts=total_alerts, critical_alerts=critical_alerts,
            out_districts=out_districts, recent_alerts=recent_alerts, top_gaps=top_gaps,
            labels_7=json.dumps(labels),
            alert_trend=json.dumps(alert_trend),
            gap_labels=json.dumps([g.search_query[:18] for g in top_gaps]),
            gap_counts=json.dumps([g.count for g in top_gaps]),
            sev_breakdown=json.dumps(sev_breakdown),
            fac_names=json.dumps(fac_names_list),
            fac_counts=json.dumps(fac_counts_list),
        )

    # ── SYSTEM ADMIN ─────────────────────────────────────────────────────────
    elif role == 'system_admin':
        total_users = User.query.count()
        total_doctors = User.query.filter_by(role='doctor', verified_doctor=True).count()
        total_consults = Appointment.query.filter_by(status='completed').count()
        escrow_held = db.session.query(func.sum(Payment.amount_ugx))\
            .filter_by(status='held').scalar() or 0
        total_released = db.session.query(func.sum(Payment.net_amount_ugx))\
            .filter_by(status='released').scalar() or 0
        platform_revenue = db.session.query(func.sum(Payment.platform_fee_ugx))\
            .filter_by(status='released').scalar() or 0
        recent_payments = Payment.query.order_by(Payment.created_at.desc()).limit(8).all()
        pending_deliveries = DeliveryOrder.query\
            .filter(DeliveryOrder.status.notin_(['delivered','cancelled'])).count()
        open_alerts = Alert.query.filter_by(status='open').count()

        from app.models import SearchGap
        top_gaps = SearchGap.query.order_by(SearchGap.count.desc()).limit(6).all()

        rev_trend = []
        for i in range(6, -1, -1):
            d = datetime.utcnow() - timedelta(days=i)
            s = d.replace(hour=0,minute=0,second=0,microsecond=0)
            e = s + timedelta(days=1)
            amt = db.session.query(func.sum(Payment.platform_fee_ugx))\
                .filter(Payment.status=='released',
                        Payment.created_at>=s, Payment.created_at<e).scalar() or 0
            rev_trend.append(float(amt))

        user_trend = _daily_counts(User, User.created_at, {})
        consult_trend = _daily_counts(Appointment, Appointment.created_at, {'status': 'completed'})

        role_breakdown = dict(db.session.query(User.role, func.count(User.id))
            .group_by(User.role).all())

        pay_methods = dict(db.session.query(WalletTransaction.network, func.count(WalletTransaction.id))
            .filter_by(tx_type='topup').group_by(WalletTransaction.network).all())

        return render_template('dashboard/admin.html',
            total_users=total_users, total_doctors=total_doctors,
            total_consults=total_consults, escrow_held=escrow_held,
            total_released=total_released, platform_revenue=platform_revenue,
            recent_payments=recent_payments, pending_deliveries=pending_deliveries,
            open_alerts=open_alerts, top_gaps=top_gaps,
            labels_7=json.dumps(labels),
            rev_trend=json.dumps(rev_trend),
            user_trend=json.dumps(user_trend),
            consult_trend=json.dumps(consult_trend),
            role_breakdown=json.dumps(role_breakdown),
            pay_methods=json.dumps(pay_methods),
        )

    return redirect(url_for('auth.logout'))
