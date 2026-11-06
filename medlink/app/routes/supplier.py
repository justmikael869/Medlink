from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.models import (Facility, Medicine, SupplierCatalogue, Order, OrderItem,
                        Notification, User, StockItem, Alert, RestockSuggestion)
from datetime import datetime, date
import uuid

supplier_bp = Blueprint('supplier', __name__, url_prefix='/supplier')


def _require_supplier():
    if current_user.role not in ('supplier','facility_admin','system_admin'):
        flash('Supplier access only.', 'danger')
        return False
    return True


@supplier_bp.route('/catalogue')
@login_required
def catalogue():
    """View supplier's own catalogue."""
    if not _require_supplier(): return redirect(url_for('dashboard.index'))
    fac = current_user.facility
    if not fac:
        flash('No facility linked to your account.', 'warning')
        return redirect(url_for('dashboard.index'))
    items = SupplierCatalogue.query.filter_by(supplier_id=fac.id).all()
    medicines = Medicine.query.order_by(Medicine.name).all()
    return render_template('supplier/catalogue.html', items=items,
                           medicines=medicines, facility=fac)


@supplier_bp.route('/catalogue/add', methods=['POST'])
@login_required
def add_to_catalogue():
    if not _require_supplier(): return redirect(url_for('dashboard.index'))
    fac = current_user.facility
    med_id = int(request.form.get('medicine_id'))
    price = float(request.form.get('unit_price_ugx', 0) or 0)
    min_qty = int(request.form.get('min_order_qty', 1) or 1)
    lead = int(request.form.get('lead_time_days', 7) or 7)

    existing = SupplierCatalogue.query.filter_by(
        supplier_id=fac.id, medicine_id=med_id).first()
    if existing:
        existing.unit_price_ugx = price
        existing.min_order_qty = min_qty
        existing.lead_time_days = lead
        existing.in_stock = True
    else:
        db.session.add(SupplierCatalogue(
            supplier_id=fac.id, medicine_id=med_id,
            unit_price_ugx=price, min_order_qty=min_qty,
            lead_time_days=lead, in_stock=True,
        ))
    db.session.commit()
    flash('Medicine added to catalogue.', 'success')
    return redirect(url_for('supplier.catalogue'))


@supplier_bp.route('/catalogue/<int:item_id>/toggle', methods=['POST'])
@login_required
def toggle_stock(item_id):
    if not _require_supplier(): return redirect(url_for('dashboard.index'))
    item = SupplierCatalogue.query.get_or_404(item_id)
    item.in_stock = not item.in_stock
    db.session.commit()
    flash(f'{"In stock" if item.in_stock else "Out of stock"} updated.', 'success')
    return redirect(url_for('supplier.catalogue'))


@supplier_bp.route('/orders')
@login_required
def orders():
    """Supplier sees orders placed TO their facility."""
    if not _require_supplier(): return redirect(url_for('dashboard.index'))
    fac = current_user.facility
    incoming = Order.query.filter_by(
        seller_facility_id=fac.id
    ).order_by(Order.created_at.desc()).all() if fac else []
    return render_template('supplier/orders.html', orders=incoming, facility=fac)


@supplier_bp.route('/orders/<int:order_id>/confirm', methods=['POST'])
@login_required
def confirm_order(order_id):
    if not _require_supplier(): return redirect(url_for('dashboard.index'))
    order = Order.query.get_or_404(order_id)
    order.status = 'confirmed'
    order.confirmed_by = current_user.id
    order.updated_at = datetime.utcnow()
    # Notify buyer
    buyer_fac = order.buyer
    if buyer_fac and buyer_fac.users:
        for u in buyer_fac.users:
            if u.role in ('facility_admin','staff'):
                db.session.add(Notification(
                    recipient_user_id=u.id,
                    title=f'Order {order.order_number} confirmed',
                    body=f'Your order has been confirmed by {current_user.facility.name}.'
                         f' Expected delivery: {order.expected_delivery}',
                    notif_type='payment',
                    related_order_id=order.id,
                ))
    db.session.commit()
    flash(f'Order {order.order_number} confirmed.', 'success')
    return redirect(url_for('supplier.orders'))


@supplier_bp.route('/orders/<int:order_id>/dispatch', methods=['POST'])
@login_required
def dispatch_order(order_id):
    if not _require_supplier(): return redirect(url_for('dashboard.index'))
    order = Order.query.get_or_404(order_id)
    order.status = 'dispatched'
    order.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f'Order {order.order_number} marked as dispatched.', 'success')
    return redirect(url_for('supplier.orders'))


@supplier_bp.route('/browse')
def browse():
    """Facility staff browse all supplier catalogues to place orders."""
    search = request.args.get('q', '').strip()
    q = db.session.query(SupplierCatalogue)\
                  .join(Medicine, SupplierCatalogue.medicine_id == Medicine.id)\
                  .join(Facility, SupplierCatalogue.supplier_id == Facility.id)\
                  .filter(SupplierCatalogue.in_stock == True,
                          Facility.verified == True)
    if search:
        q = q.filter(Medicine.name.ilike(f'%{search}%'))
    items = q.order_by(Medicine.name).all()
    return render_template('supplier/browse.html', items=items, search=search)


@supplier_bp.route('/browse/order/<int:supplier_id>', methods=['GET', 'POST'])
@login_required
def place_order(supplier_id):
    """Facility places an order to a specific supplier."""
    supplier_fac = Facility.query.get_or_404(supplier_id)
    catalogue = SupplierCatalogue.query.filter_by(
        supplier_id=supplier_id, in_stock=True).all()
    buyer_fac = current_user.facility

    if request.method == 'POST':
        if not buyer_fac:
            flash('No facility linked to your account.', 'danger')
            return redirect(request.url)

        items_data = []
        for cat_item in catalogue:
            qty = int(request.form.get(f'qty_{cat_item.id}', 0) or 0)
            if qty > 0:
                items_data.append((cat_item, qty))

        if not items_data:
            flash('Select at least one medicine and quantity.', 'danger')
            return redirect(request.url)

        total = sum(c.unit_price_ugx * q for c, q in items_data)
        order_num = 'ORD-' + uuid.uuid4().hex[:8].upper()
        order = Order(
            buyer_facility_id=buyer_fac.id,
            seller_facility_id=supplier_id,
            order_number=order_num,
            status='pending',
            total_amount=total,
            created_by=current_user.id,
            notes=request.form.get('notes',''),
        )
        db.session.add(order)
        db.session.flush()
        for cat_item, qty in items_data:
            db.session.add(OrderItem(
                order_id=order.id,
                medicine_id=cat_item.medicine_id,
                quantity=qty,
                unit_price=cat_item.unit_price_ugx,
                total_price=cat_item.unit_price_ugx * qty,
            ))
        # Notify supplier
        for u in supplier_fac.users:
            if u.role in ('supplier','facility_admin'):
                db.session.add(Notification(
                    recipient_user_id=u.id,
                    title=f'New order from {buyer_fac.name}',
                    body=f'Order {order_num} — UGX {total:,.0f}. Please confirm.',
                    notif_type='payment',
                    related_order_id=order.id,
                ))
        db.session.commit()
        flash(f'Order {order_num} placed to {supplier_fac.name}.', 'success')
        return redirect(url_for('orders.detail', order_id=order.id))

    return render_template('supplier/place_order.html',
                           supplier=supplier_fac, catalogue=catalogue,
                           buyer=buyer_fac)


# ─────────────────────────────────────────────────────────────────────────────
# DISTRIBUTOR DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@supplier_bp.route('/dashboard')
@login_required
def distributor_dashboard():
    if not _require_supplier(): return redirect(url_for('dashboard.index'))
    fac = current_user.facility
    if not fac:
        flash('No facility linked to your account. Contact your system administrator.', 'warning')
        return redirect(url_for('dashboard.index'))

    from sqlalchemy import func
    from app.models import Payment
    from datetime import datetime, timedelta
    import json

    total_orders = Order.query.filter_by(seller_facility_id=fac.id).count()
    pending_orders = Order.query.filter_by(seller_facility_id=fac.id, status='pending').count()
    confirmed_orders= Order.query.filter_by(seller_facility_id=fac.id, status='confirmed').count()
    dispatched = Order.query.filter_by(seller_facility_id=fac.id, status='dispatched').count()
    delivered = Order.query.filter_by(seller_facility_id=fac.id, status='delivered').count()

    revenue = db.session.query(func.sum(Order.total_amount))\
                        .filter_by(seller_facility_id=fac.id)\
                        .filter(Order.status.in_(['confirmed','dispatched','delivered']))\
                        .scalar() or 0.0

    recent_orders = Order.query.filter_by(seller_facility_id=fac.id)\
                         .order_by(Order.created_at.desc()).limit(10).all()

    catalogue_count = SupplierCatalogue.query.filter_by(supplier_id=fac.id).count()
    in_stock_count = SupplierCatalogue.query.filter_by(supplier_id=fac.id, in_stock=True).count()
    out_stock_count = catalogue_count - in_stock_count

    from app.models import DeliveryCompany, DeliveryOrder
    delivery_cos = DeliveryCompany.query.filter_by(verified=True, active=True).all()
    active_transports = DeliveryOrder.query.filter(
        DeliveryOrder.company_id.in_([c.id for c in delivery_cos]),
        DeliveryOrder.status.notin_(['delivered','cancelled'])
    ).count() if delivery_cos else 0

    # Order trend last 7 days
    labels_7 = [(datetime.utcnow()-timedelta(days=i)).strftime('%d %b') for i in range(6,-1,-1)]
    order_trend = []
    rev_trend = []
    for i in range(6, -1, -1):
        d = datetime.utcnow() - timedelta(days=i)
        s = d.replace(hour=0,minute=0,second=0,microsecond=0)
        e = s + timedelta(days=1)
        oc = Order.query.filter_by(seller_facility_id=fac.id)\
                  .filter(Order.created_at>=s, Order.created_at<e).count()
        ra = db.session.query(func.sum(Order.total_amount))\
                       .filter_by(seller_facility_id=fac.id)\
                       .filter(Order.status.in_(['confirmed','dispatched','delivered']),
                               Order.created_at>=s, Order.created_at<e).scalar() or 0
        order_trend.append(oc)
        rev_trend.append(float(ra))

    # Order status donut
    order_status_data = json.dumps({
        'Pending': pending_orders, 'Confirmed': confirmed_orders,
        'Dispatched': dispatched, 'Delivered': delivered,
    })

    return render_template('supplier/dashboard.html',
        facility=fac,
        total_orders=total_orders, pending_orders=pending_orders,
        confirmed_orders=confirmed_orders, dispatched=dispatched,
        revenue=revenue, recent_orders=recent_orders,
        catalogue_count=catalogue_count, in_stock_count=in_stock_count,
        out_stock_count=out_stock_count, delivery_cos=delivery_cos,
        active_transports=active_transports,
        labels_7=json.dumps(labels_7),
        order_trend=json.dumps(order_trend),
        rev_trend=json.dumps(rev_trend),
        order_status_data=order_status_data,
    )


# ─────────────────────────────────────────────────────────────────────────────
# DELIVERY TRANSPORT REQUESTS (distributor → delivery company)
# ─────────────────────────────────────────────────────────────────────────────

@supplier_bp.route('/transport/request', methods=['GET', 'POST'])
@login_required
def request_transport():
    """
    Distributor requests transport for a confirmed order.
    Options: pick a specific company, or broadcast to all (open tender).
    """
    if not _require_supplier(): return redirect(url_for('dashboard.index'))
    fac = current_user.facility
    if not fac:
        flash('Your account is not linked to a facility. Please contact the system admin.', 'danger')
        return redirect(url_for('supplier.distributor_dashboard'))

    from app.models import DeliveryCompany, DeliveryOrder

    delivery_cos = DeliveryCompany.query.filter_by(verified=True, active=True).all()
    pending_dispatch = Order.query\
        .filter_by(seller_facility_id=fac.id, status='confirmed')\
        .order_by(Order.created_at.desc()).all()

    if request.method == 'POST':
        order_id = int(request.form.get('order_id', 0) or 0)
        assign_mode = request.form.get('assign_mode', 'specific') # specific | open
        company_id = int(request.form.get('company_id', 0) or 0) if assign_mode == 'specific' else None
        pickup_addr = request.form.get('pickup_address', '').strip() or fac.address or ''
        delivery_addr = request.form.get('delivery_address', '').strip()
        notes = request.form.get('notes', '').strip()
        cold_chain = request.form.get('cold_chain') == 'on'

        if not order_id or not delivery_addr:
            flash('Please select an order and provide a delivery address.', 'danger')
            return redirect(request.url)
        if assign_mode == 'specific' and not company_id:
            flash('Please select a delivery company or choose open broadcast.', 'danger')
            return redirect(request.url)

        order = Order.query.get(order_id)
        if not order:
            flash('Order not found.', 'danger')
            return redirect(request.url)

        co = DeliveryCompany.query.get(company_id) if company_id else None

        dorder = DeliveryOrder(
            delivery_type = 'medicine',
            pharmacy_id = fac.id,
            delivery_address = delivery_addr,
            pickup_address = pickup_addr,
            pickup_lat = fac.latitude,
            pickup_lon = fac.longitude,
            company_id = company_id, # None = open broadcast
            requires_cold_chain = cold_chain,
            status = 'pending',
            fee_ugx = 0.0,
            driver_notes = notes,
        )
        db.session.add(dorder)
        db.session.flush()
        order.status = 'dispatched'

        # Notify: specific company or ALL verified companies
        target_cos = [co] if co else delivery_cos
        from app.models import Message
        for target in target_cos:
            drivers = User.query.filter_by(
                delivery_company_id=target.id, role='driver', active=True).all()
            for driver in drivers:
                db.session.add(Notification(
                    recipient_user_id = driver.id,
                    title = f'New transport request from {fac.name}',
                    body = f'Order {order.order_number} needs transport to '
                                        f'{delivery_addr}.'
                                        + (' Requires cold chain.' if cold_chain else ''),
                    notif_type = 'delivery',
                ))
            contact = User.query.filter_by(delivery_company_id=target.id).first()
            if contact:
                db.session.add(Message(
                    sender_id = current_user.id,
                    recipient_id = contact.id,
                    subject = f'Transport Request — Order {order.order_number}',
                    body = (
                        f'Dear {target.name},\n\n'
                        f'We require transport for Order {order.order_number}.\n'
                        + ('This is an OPEN TENDER — first company to confirm gets the job.\n\n'
                           if assign_mode == 'open' else '\n')
                        + f'Pickup: {pickup_addr}\n'
                          f'Delivery: {delivery_addr}\n'
                        + ('Cold chain required: Yes\n' if cold_chain else '')
                        + (f'\nNotes: {notes}' if notes else '')
                        + f'\n\nDelivery Reference: {dorder.reference}\n\n'
                          f'Regards,\n{current_user.name}\n{fac.name}'
                    ),
                    msg_type = 'general',
                    related_order_id = order.id,
                ))

        db.session.commit()
        if assign_mode == 'open':
            flash(f'Transport request {dorder.reference} broadcast to all '
                  f'{len(target_cos)} delivery companies. First to respond gets the job.', 'success')
        else:
            flash(f'Transport request {dorder.reference} sent to {co.name}.', 'success')
        return redirect(url_for('supplier.distributor_dashboard'))

    return render_template('supplier/request_transport.html',
                           facility=fac,
                           delivery_cos=delivery_cos,
                           pending_dispatch=pending_dispatch)


@supplier_bp.route('/transport/history')
@login_required
def transport_history():
    """All transport orders initiated by this distributor."""
    if not _require_supplier(): return redirect(url_for('dashboard.index'))
    fac = current_user.facility
    from app.models import DeliveryOrder
    if not fac:
        transports = []
    else:
        transports = DeliveryOrder.query\
            .filter_by(pharmacy_id=fac.id)\
            .order_by(DeliveryOrder.created_at.desc()).all()
    return render_template('supplier/transport_history.html',
                           transports=transports, facility=fac)


# ─────────────────────────────────────────────────────────────────────────────
# COMPARE PRICES ACROSS ALL SUPPLIERS FOR A MEDICINE
# ─────────────────────────────────────────────────────────────────────────────

@supplier_bp.route('/compare')
def compare_prices():
    """Anyone can compare prices for a medicine across all verified suppliers."""
    med_id = request.args.get('medicine_id', type=int)
    search = request.args.get('q', '').strip()

    medicines = Medicine.query.order_by(Medicine.name).all()
    entries = []
    selected_medicine = None

    if med_id:
        selected_medicine = Medicine.query.get(med_id)
        entries = (
            db.session.query(SupplierCatalogue)
            .join(Facility, SupplierCatalogue.supplier_id == Facility.id)
            .filter(
                SupplierCatalogue.medicine_id == med_id,
                Facility.verified == True,
                SupplierCatalogue.in_stock == True,
            )
            .order_by(SupplierCatalogue.unit_price_ugx)
            .all()
        )
    elif search:
        medicines = Medicine.query.filter(
            db.or_(
                Medicine.name.ilike(f'%{search}%'),
                Medicine.generic_name.ilike(f'%{search}%'),
            )
        ).order_by(Medicine.name).all()

    return render_template(
        'supplier/compare.html',
        medicines = medicines,
        entries = entries,
        selected_medicine = selected_medicine,
        search = search,
    )
