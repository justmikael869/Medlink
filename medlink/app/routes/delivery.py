from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import (DeliveryOrder, DeliveryCompany, User, Facility, Prescription,
                        Appointment, Payment, PaymentAudit, WalletTransaction,
                        Notification, Medicine, StockItem)
from datetime import datetime
import uuid

delivery_bp = Blueprint('delivery', __name__, url_prefix='/delivery')


# ── Request medicine delivery ─────────────────────────────────────────────────

@delivery_bp.route('/request-medicine/<int:prescription_id>', methods=['GET', 'POST'])
@login_required
def request_medicine(prescription_id):
    rx = Prescription.query.get_or_404(prescription_id)
    med = rx.medicine
    pharmacies = []
    if med:
        for item in StockItem.query.filter_by(medicine_id=med.id, is_available=True)\
                                   .filter(StockItem.quantity > 0).all():
            fac = item.facility
            if fac and fac.active:
                pharmacies.append({'facility': fac, 'price': item.unit_price,
                                   'stock': item.quantity})

    if request.method == 'POST':
        pharmacy_id = int(request.form.get('pharmacy_id'))
        delivery_address = request.form.get('delivery_address', '').strip()
        delivery_lat = request.form.get('delivery_lat', type=float)
        delivery_lon = request.form.get('delivery_lon', type=float)
        cold_needed = med.requires_cold_chain if med else False
        fee_ugx = 5000.0

        if (current_user.wallet_balance_ugx or 0) < fee_ugx:
            flash('Insufficient wallet balance. Please top up.', 'danger')
            return redirect(url_for('telemedicine.wallet'))

        pay = Payment(idempotency_key=uuid.uuid4().hex, amount_ugx=fee_ugx,
                      payment_type='delivery', status='held',
                      payer_id=current_user.id,
                      notes=f'Delivery of {rx.medicine_name}')
        pay.compute_fees()
        db.session.add(pay)
        db.session.flush()

        current_user.wallet_balance_ugx -= fee_ugx
        db.session.add(WalletTransaction(
            user_id=current_user.id, tx_type='deduct', amount_ugx=fee_ugx,
            balance_after=current_user.wallet_balance_ugx,
            reference=pay.reference, note='Medicine delivery fee', payment_id=pay.id))

        dorder = DeliveryOrder(
            delivery_type='medicine', patient_id=current_user.id,
            prescription_id=prescription_id, pharmacy_id=pharmacy_id,
            delivery_address=delivery_address, delivery_lat=delivery_lat,
            delivery_lon=delivery_lon, requires_cold_chain=cold_needed,
            status='pending', fee_ugx=fee_ugx, payment_id=pay.id)
        db.session.add(dorder)

        driver = _find_driver(cold_needed)
        if driver:
            dorder.driver_id = driver.id
            dorder.status = 'assigned'

        db.session.commit()
        flash(f'Delivery order {dorder.reference} placed!', 'success')
        return redirect(url_for('delivery.track', order_id=dorder.id))

    return render_template('delivery/request_medicine.html', prescription=rx,
                           pharmacies=pharmacies)


# ── Patient transport ─────────────────────────────────────────────────────────

@delivery_bp.route('/request-transport/<int:appt_id>', methods=['GET', 'POST'])
@login_required
def request_transport(appt_id):
    appt = Appointment.query.get_or_404(appt_id)
    if appt.patient_id != current_user.id:
        flash('Not authorised.', 'danger')
        return redirect(url_for('telemedicine.my_appointments'))

    if request.method == 'POST':
        pickup_address = request.form.get('pickup_address', '').strip()
        pickup_lat = request.form.get('pickup_lat', type=float)
        pickup_lon = request.form.get('pickup_lon', type=float)
        fee_ugx = 8000.0

        if (current_user.wallet_balance_ugx or 0) < fee_ugx:
            flash('Insufficient wallet balance.', 'danger')
            return redirect(url_for('telemedicine.wallet'))

        pay = Payment(idempotency_key=uuid.uuid4().hex, amount_ugx=fee_ugx,
                      payment_type='transport', status='held',
                      payer_id=current_user.id,
                      notes=f'Transport to {appt.reference}')
        pay.compute_fees()
        db.session.add(pay)
        db.session.flush()

        current_user.wallet_balance_ugx -= fee_ugx
        db.session.add(WalletTransaction(
            user_id=current_user.id, tx_type='deduct', amount_ugx=fee_ugx,
            balance_after=current_user.wallet_balance_ugx,
            reference=pay.reference, note='Transport to appointment', payment_id=pay.id))

        dest = appt.facility
        dorder = DeliveryOrder(
            delivery_type='patient_transport', patient_id=current_user.id,
            appointment_id=appt_id,
            destination_facility_id=dest.id if dest else None,
            pickup_address=pickup_address, pickup_lat=pickup_lat, pickup_lon=pickup_lon,
            delivery_address=dest.address if dest else '',
            delivery_lat=dest.latitude if dest else None,
            delivery_lon=dest.longitude if dest else None,
            requires_cold_chain=False, status='pending',
            fee_ugx=fee_ugx, payment_id=pay.id)
        db.session.add(dorder)

        driver = _find_driver(False)
        if driver:
            dorder.driver_id = driver.id
            dorder.status = 'assigned'

        db.session.commit()
        flash(f'Transport order {dorder.reference} placed!', 'success')
        return redirect(url_for('delivery.track', order_id=dorder.id))

    return render_template('delivery/request_transport.html', appt=appt)


# ── Tracking ──────────────────────────────────────────────────────────────────

@delivery_bp.route('/track/<int:order_id>')
@login_required
def track(order_id):
    dorder = DeliveryOrder.query.get_or_404(order_id)
    return render_template('delivery/track.html', dorder=dorder)


# ── Driver dashboard ──────────────────────────────────────────────────────────

@delivery_bp.route('/driver')
@login_required
def driver_dashboard():
    if current_user.role != 'driver':
        flash('Driver access only.', 'danger')
        return redirect(url_for('dashboard.index'))
    orders = DeliveryOrder.query.filter_by(driver_id=current_user.id)\
                                 .order_by(DeliveryOrder.created_at.desc()).limit(20).all()
    # Pending orders this driver's company can see (or all pending if no company)
    if current_user.delivery_company_id:
        pending = DeliveryOrder.query.filter_by(
            status='pending', driver_id=None,
            company_id=current_user.delivery_company_id).all()
    else:
        pending = [] # unaffiliated drivers cannot self-assign

    return render_template('delivery/driver_dashboard.html',
                           orders=orders, pending=pending)


@delivery_bp.route('/driver/update/<int:order_id>', methods=['POST'])
@login_required
def update_status(order_id):
    dorder = DeliveryOrder.query.get_or_404(order_id)
    if dorder.driver_id != current_user.id:
        flash('Not your order.', 'danger')
        return redirect(url_for('delivery.driver_dashboard'))

    new_status = request.form.get('status')
    if new_status not in ['assigned','picked_up','en_route','delivered','cancelled']:
        flash('Invalid status.', 'danger')
        return redirect(url_for('delivery.driver_dashboard'))

    dorder.status = new_status
    dorder.updated_at = datetime.utcnow()

    if new_status == 'delivered':
        _release_delivery_escrow(dorder)
        if dorder.patient_id:
            db.session.add(Notification(
                recipient_user_id=dorder.patient_id,
                title='Your delivery has arrived!',
                body=f'Order {dorder.reference} has been delivered.',
                notif_type='delivery'))

    db.session.commit()
    flash(f'Status updated to {new_status}.', 'success')
    return redirect(url_for('delivery.driver_dashboard'))


# ── Company management ────────────────────────────────────────────────────────

@delivery_bp.route('/companies')
@login_required
def company_list():
    """Public list of verified delivery companies."""
    companies = DeliveryCompany.query.filter_by(verified=True, active=True).all()
    return render_template('delivery/companies.html', companies=companies)


@delivery_bp.route('/companies/register', methods=['GET', 'POST'])
@login_required
def register_company():
    """A company representative registers their company."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        if not name:
            flash('Company name is required.', 'danger')
            return redirect(request.url)
        co = DeliveryCompany(name=name, contact_phone=phone,
                             contact_email=email, verified=False, active=True)
        db.session.add(co)
        db.session.flush()
        # Associate registrant as first driver under this company
        current_user.delivery_company_id = co.id
        db.session.commit()
        flash(f'Company "{name}" registered and pending admin verification. '
              'You can now invite drivers.', 'success')
        return redirect(url_for('delivery.company_detail', company_id=co.id))
    return render_template('delivery/register_company.html')


@delivery_bp.route('/companies/<int:company_id>')
@login_required
def company_detail(company_id):
    co = DeliveryCompany.query.get_or_404(company_id)
    drivers = User.query.filter_by(delivery_company_id=company_id, role='driver').all()
    orders = DeliveryOrder.query.filter_by(company_id=company_id)\
                                 .order_by(DeliveryOrder.created_at.desc()).limit(30).all()
    return render_template('delivery/company_detail.html',
                           company=co, drivers=drivers, orders=orders)


@delivery_bp.route('/companies/<int:company_id>/join', methods=['POST'])
@login_required
def join_company(company_id):
    """Driver requests to join a company."""
    co = DeliveryCompany.query.get_or_404(company_id)
    if not co.verified:
        flash('This company is not yet verified by MedLink.', 'warning')
        return redirect(url_for('delivery.company_list'))
    if current_user.role != 'driver':
        flash('Only registered drivers can join companies.', 'danger')
        return redirect(url_for('delivery.company_list'))
    current_user.delivery_company_id = company_id
    db.session.commit()
    flash(f'You have joined {co.name}.', 'success')
    return redirect(url_for('delivery.company_detail', company_id=company_id))


# ── Admin views ───────────────────────────────────────────────────────────────

@delivery_bp.route('/admin')
@login_required
def admin_view():
    if current_user.role not in ('system_admin', 'district_officer'):
        flash('Admin access only.', 'danger')
        return redirect(url_for('dashboard.index'))
    orders = DeliveryOrder.query.order_by(DeliveryOrder.created_at.desc()).limit(50).all()
    companies = DeliveryCompany.query.all()
    return render_template('delivery/admin.html', orders=orders, companies=companies)


@delivery_bp.route('/admin/companies/<int:company_id>/verify', methods=['POST'])
@login_required
def verify_company(company_id):
    if current_user.role != 'system_admin':
        flash('Admin only.', 'danger')
        return redirect(url_for('delivery.admin_view'))
    co = DeliveryCompany.query.get_or_404(company_id)
    co.verified = not co.verified
    db.session.commit()
    flash(f'Company "{co.name}" {"verified" if co.verified else "unverified"}.', 'success')
    return redirect(url_for('delivery.admin_view'))


# ── Payment helpers ───────────────────────────────────────────────────────────

def _release_delivery_escrow(dorder):
    if not dorder.payment or dorder.payment.status != 'held':
        return
    pay = dorder.payment
    pay.status = 'released'
    pay.escrow_released_at = datetime.utcnow()

    # Pay the company if assigned, otherwise the driver directly
    payee_id = None
    if dorder.company_id:
        # Company gets paid — company then pays drivers via their own payroll
        co = DeliveryCompany.query.get(dorder.company_id)
        # For now credit the driver who did the work; company accounting tracked separately
        payee_id = dorder.driver_id
    else:
        payee_id = dorder.driver_id

    if payee_id:
        payee = User.query.get(payee_id)
        if payee:
            payee.wallet_balance_ugx = (payee.wallet_balance_ugx or 0) + pay.net_amount_ugx
            db.session.add(WalletTransaction(
                user_id=payee.id, tx_type='topup',
                amount_ugx=pay.net_amount_ugx,
                balance_after=payee.wallet_balance_ugx,
                reference=pay.reference, note='Delivery payout',
                payment_id=pay.id))
    db.session.add(PaymentAudit(
        payment_id=pay.id, event='released',
        old_status='held', new_status='released',
        actor_id=dorder.driver_id, note='Delivery confirmed'))


def _find_driver(needs_cold_chain: bool):
    """Find an available verified driver, preferring company drivers."""
    q = User.query.filter_by(role='driver', active=True,
                              verified_driver=True, is_available=True)
    if needs_cold_chain:
        q = q.filter_by(has_cold_box=True)
    # Prefer drivers in a verified company
    company_driver = q.filter(User.delivery_company_id.isnot(None)).first()
    return company_driver or q.first()


@delivery_bp.route('/my-deliveries')
@login_required
def my_deliveries():
    orders = DeliveryOrder.query.filter_by(patient_id=current_user.id)\
                                .order_by(DeliveryOrder.created_at.desc()).all()
    return render_template('delivery/my_deliveries.html', orders=orders)


@delivery_bp.route('/driver/history')
@login_required
def driver_history():
    if current_user.role != 'driver':
        from flask import abort
        abort(403)
    orders = DeliveryOrder.query.filter_by(
        driver_id=current_user.id, status='delivered'
    ).order_by(DeliveryOrder.updated_at.desc()).all()
    return render_template('delivery/driver_history.html', orders=orders)


# ─────────────────────────────────────────────────────────────────────────────
# DELIVERY COMPANY MANAGER DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@delivery_bp.route('/company/dashboard')
@login_required
def company_dashboard():
    """Full company operations view for the manager."""
    if current_user.role not in ('driver','company_manager') or not current_user.delivery_company_id:
        flash('Company manager access only.', 'danger')
        return redirect(url_for('dashboard.index'))

    co_id = current_user.delivery_company_id
    co = DeliveryCompany.query.get_or_404(co_id)

    all_orders = DeliveryOrder.query.filter_by(company_id=co_id)\
                                    .order_by(DeliveryOrder.created_at.desc()).all()
    pending = [o for o in all_orders if o.status == 'pending']
    active = [o for o in all_orders if o.status in ('assigned','picked_up','en_route')]
    completed = [o for o in all_orders if o.status == 'delivered']

    drivers = User.query.filter_by(
        delivery_company_id=co_id, role='driver', active=True).all()

    from sqlalchemy import func
    from datetime import datetime, timedelta
    import json

    revenue = db.session.query(func.sum(DeliveryOrder.fee_ugx))\
                        .filter_by(company_id=co_id, status='delivered').scalar() or 0.0

    cold_drivers = [d for d in drivers if d.has_cold_box]

    # Delivery trend last 7 days
    labels_7 = [(datetime.utcnow()-timedelta(days=i)).strftime('%d %b') for i in range(6,-1,-1)]
    delivery_trend = []
    rev_trend = []
    for i in range(6, -1, -1):
        d = datetime.utcnow() - timedelta(days=i)
        s = d.replace(hour=0,minute=0,second=0,microsecond=0)
        e = s + timedelta(days=1)
        dc = DeliveryOrder.query.filter_by(company_id=co_id, status='delivered')\
                                .filter(DeliveryOrder.updated_at>=s,
                                        DeliveryOrder.updated_at<e).count()
        ra = db.session.query(func.sum(DeliveryOrder.fee_ugx))\
                       .filter_by(company_id=co_id, status='delivered')\
                       .filter(DeliveryOrder.updated_at>=s,
                               DeliveryOrder.updated_at<e).scalar() or 0
        delivery_trend.append(dc)
        rev_trend.append(float(ra))

    # Driver performance — deliveries per driver
    driver_names = [d.name.split()[0] for d in drivers]
    driver_counts = [
        DeliveryOrder.query.filter_by(driver_id=d.id, status='delivered').count()
        for d in drivers
    ]

    # Order status breakdown
    status_counts = {
        'Pending': len(pending),
        'Active': len(active),
        'Delivered': len(completed),
        'Cancelled': DeliveryOrder.query.filter_by(company_id=co_id, status='cancelled').count(),
    }

    return render_template('delivery/company_dashboard.html',
        company=co, pending=pending, active=active,
        completed=completed, all_orders=all_orders,
        drivers=drivers, cold_drivers=cold_drivers, revenue=revenue,
        labels_7=json.dumps(labels_7),
        delivery_trend=json.dumps(delivery_trend),
        rev_trend=json.dumps(rev_trend),
        driver_names=json.dumps(driver_names),
        driver_counts=json.dumps(driver_counts),
        status_counts=json.dumps(status_counts),
    )


@delivery_bp.route('/company/orders/<int:order_id>/assign', methods=['POST'])
@login_required
def company_assign_driver(order_id):
    """Manager assigns a specific driver to an order."""
    if current_user.role != 'driver' or not current_user.delivery_company_id:
        flash('Not authorised.', 'danger')
        return redirect(url_for('dashboard.index'))

    dorder = DeliveryOrder.query.get_or_404(order_id)
    driver_id = int(request.form.get('driver_id', 0))
    driver = User.query.get(driver_id)

    if not driver:
        flash('Driver not found.', 'danger')
        return redirect(url_for('delivery.company_dashboard'))

    if dorder.requires_cold_chain and not driver.has_cold_box:
        flash(f'{driver.name} does not have a certified cold box. '
              'Select a cold-chain capable driver.', 'danger')
        return redirect(url_for('delivery.company_dashboard'))

    dorder.driver_id = driver_id
    dorder.status = 'assigned'
    dorder.updated_at= datetime.utcnow()

    # Notify driver
    db.session.add(Notification(
        recipient_user_id = driver_id,
        title = f'Delivery assigned: {dorder.reference}',
        body = f'You have been assigned delivery {dorder.reference}. '
                            f'Deliver to: {dorder.delivery_address}.'
                            + (' Requires cold chain.' if dorder.requires_cold_chain else ''),
        notif_type = 'delivery',
    ))

    # Notify patient if one exists
    if dorder.patient_id and dorder.patient_id != driver_id:
        db.session.add(Notification(
            recipient_user_id = dorder.patient_id,
            title = 'Your delivery has been assigned a driver',
            body = f'Driver {driver.name} ({driver.phone or ""}) '
                                f'has been assigned your delivery {dorder.reference}.',
            notif_type = 'delivery',
        ))

    db.session.commit()
    flash(f'{driver.name} assigned to order {dorder.reference}.', 'success')
    return redirect(url_for('delivery.company_dashboard'))


@delivery_bp.route('/company/orders/<int:order_id>/unassign', methods=['POST'])
@login_required
def company_unassign_driver(order_id):
    """Manager removes a driver from an order (before pickup)."""
    if current_user.role != 'driver' or not current_user.delivery_company_id:
        flash('Not authorised.', 'danger')
        return redirect(url_for('dashboard.index'))

    dorder = DeliveryOrder.query.get_or_404(order_id)
    if dorder.status in ('picked_up', 'en_route', 'delivered'):
        flash('Cannot unassign a driver after pickup.', 'danger')
        return redirect(url_for('delivery.company_dashboard'))

    dorder.driver_id = None
    dorder.status = 'pending'
    dorder.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f'Driver unassigned from {dorder.reference}.', 'success')
    return redirect(url_for('delivery.company_dashboard'))


@delivery_bp.route('/company/drivers')
@login_required
def company_drivers():
    """Manager sees all drivers and their current status."""
    if current_user.role != 'driver' or not current_user.delivery_company_id:
        flash('Not authorised.', 'danger')
        return redirect(url_for('dashboard.index'))

    co_id = current_user.delivery_company_id
    co = DeliveryCompany.query.get_or_404(co_id)
    drivers = User.query.filter_by(
        delivery_company_id=co_id, role='driver'
    ).order_by(User.name).all()

    # For each driver get their active delivery count
    driver_stats = {}
    for d in drivers:
        active = DeliveryOrder.query.filter_by(
            driver_id=d.id
        ).filter(DeliveryOrder.status.in_(['assigned','picked_up','en_route'])).count()
        completed = DeliveryOrder.query.filter_by(
            driver_id=d.id, status='delivered').count()
        driver_stats[d.id] = {'active': active, 'completed': completed}

    return render_template('delivery/company_drivers.html',
                           company=co, drivers=drivers, driver_stats=driver_stats)


@delivery_bp.route('/company/drivers/<int:user_id>/toggle-availability', methods=['POST'])
@login_required
def toggle_driver_availability(user_id):
    """Manager toggles a driver's availability."""
    if current_user.role != 'driver' or not current_user.delivery_company_id:
        flash('Not authorised.', 'danger')
        return redirect(url_for('dashboard.index'))

    driver = User.query.get_or_404(user_id)
    if driver.delivery_company_id != current_user.delivery_company_id:
        flash('Not authorised.', 'danger')
        return redirect(url_for('delivery.company_dashboard'))

    driver.is_available = not driver.is_available
    db.session.commit()
    flash(f'{driver.name} marked as {"Available" if driver.is_available else "Unavailable"}.', 'success')
    return redirect(url_for('delivery.company_drivers'))
