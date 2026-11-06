from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import StockItem, StockTransaction, Medicine, Facility, Alert
from datetime import datetime

inventory_bp = Blueprint('inventory', __name__, url_prefix='/inventory')

@inventory_bp.route('/')
@login_required
def index():
    fid = current_user.facility_id
    is_admin = current_user.role in ('system_admin', 'district_officer')
    sel_fid = request.args.get('facility_id', type=int)
    cat_filter = request.args.get('category', '')
    status_filter = request.args.get('status', '')

    if is_admin:
        facilities = Facility.query.filter_by(active=True).order_by(Facility.name).all()
        fid = sel_fid or fid
    else:
        facilities = None

    query = StockItem.query.filter_by(facility_id=fid)
    if cat_filter:
        query = query.join(Medicine).filter(Medicine.category == cat_filter)
    if status_filter == 'low':
        query = query.filter(StockItem.quantity > 0,
                             StockItem.quantity <= StockItem.minimum_threshold)
    elif status_filter == 'out':
        query = query.filter(StockItem.quantity <= 0)

    items = query.all()
    categories = db.session.query(Medicine.category).distinct().all()
    categories = [c[0] for c in categories if c[0]]

    # Chart data
    import json
    all_items = StockItem.query.filter_by(facility_id=fid).all() if fid else []
    out_count = sum(1 for i in all_items if i.quantity <= 0)
    low_count = sum(1 for i in all_items if 0 < i.quantity <= i.minimum_threshold)
    ok_count = len(all_items) - out_count - low_count

    # Top 8 medicines by quantity
    top8 = sorted(all_items, key=lambda x: x.quantity, reverse=True)[:8]
    top8_names = json.dumps([i.medicine.name[:14] for i in top8])
    top8_qtys = json.dumps([i.quantity for i in top8])

    # Category breakdown by item count
    cat_counts = {}
    for i in all_items:
        cat = i.medicine.category or 'Uncategorised'
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    return render_template('inventory/index.html', items=items,
                           facilities=facilities, selected_fid=fid,
                           categories=categories, cat_filter=cat_filter,
                           status_filter=status_filter,
                           stock_counts=json.dumps([ok_count, low_count, out_count]),
                           top8_names=top8_names, top8_qtys=top8_qtys,
                           cat_counts=json.dumps(cat_counts))


@inventory_bp.route('/update', methods=['GET', 'POST'])
@login_required
def update():
    fid = current_user.facility_id
    facility = Facility.query.get(fid)
    medicines = Medicine.query.order_by(Medicine.category, Medicine.name).all()

    if request.method == 'POST':
        from app.intelligence import trigger_restock_suggestion
        updated = 0
        for med in medicines:
            qty = request.form.get(f'qty_{med.id}')
            price = request.form.get(f'price_{med.id}')
            threshold = request.form.get(f'threshold_{med.id}')
            expiry = request.form.get(f'expiry_{med.id}')
            avail = request.form.get(f'avail_{med.id}')

            if qty is None or qty == '':
                continue

            item = StockItem.query.filter_by(facility_id=fid, medicine_id=med.id).first()
            old_qty = item.quantity if item else 0

            if not item:
                item = StockItem(facility_id=fid, medicine_id=med.id)
                db.session.add(item)

            new_qty = int(qty)
            item.quantity = new_qty
            if price: item.unit_price = float(price)
            if threshold: item.minimum_threshold = int(threshold)
            if expiry:
                item.expiry_date = datetime.strptime(expiry, '%Y-%m-%d').date()
            item.is_available = avail == 'on'
            item.updated_by = current_user.id
            item.last_updated = datetime.utcnow()

            change = new_qty - old_qty
            if change != 0:
                db.session.flush()
                tx = StockTransaction(
                    stock_item_id=item.id,
                    transaction_type='adjustment' if change > 0 else 'dispensed',
                    quantity_change=change,
                    quantity_after=new_qty,
                    performed_by=current_user.id
                )
                db.session.add(tx)

            # Auto-alert + restock suggestion
            alert = _check_and_raise_alert(item, med, fid)
            if alert and new_qty == 0:
                db.session.flush()
                trigger_restock_suggestion(item, alert)

            updated += 1

        db.session.commit()
        flash(f'Inventory updated. Auto-alerts and restock suggestions raised where needed.', 'success')
        return redirect(url_for('inventory.index'))

    existing = {i.medicine_id: i for i in StockItem.query.filter_by(facility_id=fid).all()}
    return render_template('inventory/update.html', medicines=medicines,
                           existing=existing, facility=facility)


@inventory_bp.route('/dispensing-counter', methods=['GET', 'POST'])
@login_required
def dispensing_counter():
    """Dedicated counter-dispensing page for facility staff, nurses, pharmacists, doctors."""
    from app.intelligence import trigger_restock_suggestion

    allowed = ('staff', 'facility_admin', 'system_admin', 'doctor', 'nurse', 'pharmacist')
    if current_user.role not in allowed:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    facility_id = current_user.facility_id

    # ── POST: process dispense ──────────────────────────────────────────────
    if request.method == 'POST':
        stock_id = request.form.get('stock_id', type=int)
        qty = request.form.get('quantity', type=int, default=1)
        dispensed_to = request.form.get('dispensed_to', '').strip()
        patient_ref = request.form.get('patient_ref', '').strip()
        note = request.form.get('note', '').strip()

        if not stock_id or not qty or qty < 1:
            flash('Please select a medicine and enter a valid quantity.', 'danger')
            return redirect(url_for('inventory.dispensing_counter'))

        if not dispensed_to:
            flash('Patient name is required.', 'danger')
            return redirect(url_for('inventory.dispensing_counter'))

        item = StockItem.query.get_or_404(stock_id)
        if item.facility_id != facility_id and current_user.role != 'system_admin':
            flash('That item does not belong to your facility.', 'danger')
            return redirect(url_for('inventory.dispensing_counter'))

        if item.quantity < qty:
            flash(f'Insufficient stock. Only {item.quantity} units available.', 'danger')
            return redirect(url_for('inventory.dispensing_counter'))

        item.quantity -= qty
        item.last_updated = datetime.utcnow()

        tx = StockTransaction(
            stock_item_id = item.id,
            transaction_type = 'dispensed',
            quantity_change = -qty,
            quantity_after = item.quantity,
            note = note or None,
            performed_by = current_user.id,
            dispensed_to = dispensed_to,
            patient_ref = patient_ref or None,
        )
        db.session.add(tx)

        alert = _check_and_raise_alert(item, item.medicine, facility_id)
        if alert and item.quantity == 0:
            db.session.flush()
            trigger_restock_suggestion(item, alert)

        db.session.commit()
        flash(
            f'Dispensed {qty} × {item.medicine.name} to {dispensed_to}. '
            f'Remaining stock: {item.quantity} {item.medicine.unit}.',
            'success'
        )
        return redirect(url_for('inventory.dispensing_counter'))

    # ── GET: render the counter page ────────────────────────────────────────
    search_q = request.args.get('q', '').strip()
    stock_items = []
    if search_q:
        stock_items = (
            StockItem.query
            .join(Medicine)
            .filter(
                StockItem.facility_id == facility_id,
                StockItem.quantity > 0,
                db.or_(
                    Medicine.name.ilike(f'%{search_q}%'),
                    Medicine.generic_name.ilike(f'%{search_q}%'),
                    Medicine.brand_name.ilike(f'%{search_q}%'),
                )
            )
            .order_by(Medicine.name)
            .all()
        )

    # Recent dispense history for this facility (last 30 records)
    recent_txns = (
        StockTransaction.query
        .join(StockItem)
        .filter(
            StockItem.facility_id == facility_id,
            StockTransaction.transaction_type == 'dispensed',
            StockTransaction.dispensed_to.isnot(None),
        )
        .order_by(StockTransaction.created_at.desc())
        .limit(30)
        .all()
    )

    return render_template(
        'inventory/dispensing_counter.html',
        stock_items = stock_items,
        recent_txns = recent_txns,
        search_q = search_q,
    )


@inventory_bp.route('/dispense', methods=['POST'])
@login_required
def dispense():
    from app.intelligence import trigger_restock_suggestion
    stock_id = request.form.get('stock_id', type=int)
    qty = request.form.get('quantity', type=int, default=1)
    note = request.form.get('note', '')

    item = StockItem.query.get_or_404(stock_id)
    if item.facility_id != current_user.facility_id and \
       current_user.role not in ('system_admin',):
        flash('Unauthorized.', 'danger')
        return redirect(url_for('inventory.index'))

    if item.quantity < qty:
        flash(f'Not enough stock. Available: {item.quantity}', 'danger')
        return redirect(url_for('inventory.index'))

    item.quantity -= qty
    item.last_updated = datetime.utcnow()

    tx = StockTransaction(
        stock_item_id=item.id,
        transaction_type='dispensed',
        quantity_change=-qty,
        quantity_after=item.quantity,
        note=note,
        performed_by=current_user.id
    )
    db.session.add(tx)

    alert = _check_and_raise_alert(item, item.medicine, item.facility_id)
    if alert and item.quantity == 0:
        db.session.flush()
        trigger_restock_suggestion(item, alert)

    db.session.commit()
    flash(f'Dispensed {qty} × {item.medicine.name}. Remaining: {item.quantity}.', 'success')
    return redirect(url_for('inventory.index'))


def _check_and_raise_alert(item, med, facility_id):
    existing = Alert.query.filter_by(
        facility_id=facility_id, medicine_id=med.id, status='open'
    ).filter(Alert.source != 'expiry').first()

    if item.quantity <= 0:
        if not existing:
            a = Alert(facility_id=facility_id, medicine_id=med.id,
                      raised_by=1, severity='critical', source='auto',
                      note='Auto-raised: stock reached zero')
            db.session.add(a)
            db.session.flush()
            return a
    elif item.quantity <= item.minimum_threshold:
        if not existing:
            a = Alert(facility_id=facility_id, medicine_id=med.id,
                      raised_by=1, severity='medium', source='auto',
                      note=f'Auto-raised: below minimum ({item.minimum_threshold})')
            db.session.add(a)
            db.session.flush()
            return a
    return None


# ─────────────────────────────────────────────────────────────────────────────
# DOCTOR-FACING: dispense from prescription + search availability
# ─────────────────────────────────────────────────────────────────────────────

@inventory_bp.route('/prescription-dispense/<int:prescription_id>', methods=['GET', 'POST'])
@login_required
def prescription_dispense(prescription_id):
    """
    Doctor or pharmacist records that medicines on a prescription were dispensed.
    Decrements stock at the doctor's facility (or chosen pharmacy).
    """
    from app.models import Prescription, Consultation, Appointment, Notification
    from sqlalchemy import or_

    rx = Prescription.query.get_or_404(prescription_id)
    consult = rx.consultation
    appt = consult.appointment if consult else None

    # Authorisation: doctor on the case, pharmacist at the facility, or admin
    allowed = (
        current_user.role == 'system_admin' or
        current_user.role == 'pharmacist' or
        (current_user.role == 'doctor' and appt and appt.doctor_id == current_user.id) or
        (current_user.facility_id and current_user.facility_id == (appt.facility_id if appt else None))
    )
    if not allowed:
        flash('Not authorised to dispense this prescription.', 'danger')
        return redirect(url_for('dashboard.index'))

    # Find which facilities have this medicine in stock
    fid = current_user.facility_id
    stock_at_facility = None
    if fid and rx.medicine_id:
        stock_at_facility = StockItem.query.filter_by(
            facility_id=fid, medicine_id=rx.medicine_id
        ).first()

    if request.method == 'POST':
        actual_qty = int(request.form.get('actual_qty', 0) or 0)
        dispense_fid = int(request.form.get('dispense_facility_id', fid or 0))
        note = request.form.get('note', '').strip()

        if actual_qty <= 0:
            flash('Quantity must be greater than zero.', 'danger')
            return redirect(request.url)

        stock = StockItem.query.filter_by(
            facility_id=dispense_fid, medicine_id=rx.medicine_id
        ).first() if rx.medicine_id else None

        if stock:
            if stock.quantity < actual_qty:
                flash(f'Insufficient stock. Only {stock.quantity} available.', 'danger')
                return redirect(request.url)

            stock.quantity -= actual_qty
            stock.last_updated = datetime.utcnow()

            db.session.add(StockTransaction(
                stock_item_id = stock.id,
                transaction_type = 'dispensed',
                quantity_change = -actual_qty,
                quantity_after = stock.quantity,
                reference = f'RX-{prescription_id}',
                note = note or f'Dispensed for prescription #{prescription_id}',
                performed_by = current_user.id,
            ))

            # Auto-alert if now low
            _check_and_raise_alert(stock, rx.medicine, dispense_fid)

        # Mark prescription as dispensed
        rx.dispensed = True
        rx.dispensed_by = current_user.id
        rx.dispensed_at = datetime.utcnow()

        # Notify patient
        if appt and appt.patient_id:
            db.session.add(Notification(
                recipient_user_id = appt.patient_id,
                title = 'Your prescription has been dispensed',
                body = f'{rx.medicine_name} — {actual_qty} units dispensed'
                                    + (f' at {Facility.query.get(dispense_fid).name}' if Facility.query.get(dispense_fid) else '')
                                    + '.',
                notif_type = 'appointment',
                related_appointment_id = appt.id,
            ))

        db.session.commit()
        flash(f'Dispensed {actual_qty} × {rx.medicine_name}. Stock updated.', 'success')
        return redirect(url_for('telemedicine.appointment_detail',
                                appt_id=appt.id if appt else 0))

    # Facilities that stock this medicine — for the "dispense from" dropdown
    alternatives = []
    if rx.medicine_id:
        alt_items = StockItem.query.filter_by(medicine_id=rx.medicine_id)\
                                   .filter(StockItem.quantity > 0).all()
        for i in alt_items:
            if i.facility and i.facility.active:
                alternatives.append(i)

    return render_template('inventory/prescription_dispense.html',
                           rx=rx, consult=consult, appt=appt,
                           stock_at_facility=stock_at_facility,
                           alternatives=alternatives,
                           current_facility_id=fid)


@inventory_bp.route('/medicine-availability')
@login_required
def medicine_availability():
    """
    Doctor/pharmacist searches what is available across the system
    before issuing or recording a prescription.
    Returns JSON for AJAX or a rendered page.
    """
    from app.models import Medicine as Med
    from sqlalchemy import or_

    q = request.args.get('q', '').strip()
    fid = request.args.get('facility_id', type=int) or current_user.facility_id
    fmt = request.args.get('format', 'html') # html | json

    results = []
    if q:
        meds = Med.query.filter(
            or_(Med.name.ilike(f'%{q}%'),
                Med.generic_name.ilike(f'%{q}%'),
                Med.brand_name.ilike(f'%{q}%'))
        ).all()

        med_ids = [m.id for m in meds]
        if med_ids:
            # Search own facility first, then all
            items = StockItem.query\
                .filter(StockItem.medicine_id.in_(med_ids),
                        StockItem.is_available == True)\
                .all()

            for item in items:
                fac = item.facility
                if not fac or not fac.active: continue
                results.append({
                    'medicine_id': item.medicine_id,
                    'medicine_name': item.medicine.name,
                    'generic_name': item.medicine.generic_name or '',
                    'dosage_form': item.medicine.dosage_form or '',
                    'strength': item.medicine.strength or '',
                    'facility_id': fac.id,
                    'facility_name': fac.name,
                    'facility_type': fac.facility_type,
                    'quantity': item.quantity,
                    'status': item.status,
                    'sell_price': item.sell_price or item.unit_price,
                    'cold_chain': item.medicine.requires_cold_chain,
                    'at_own_facility': fac.id == fid,
                })

        # Sort: own facility first, then by quantity desc
        results.sort(key=lambda x: (0 if x['at_own_facility'] else 1, -x['quantity']))

    if fmt == 'json':
        return jsonify(results)

    medicines_all = Med.query.order_by(Med.category, Med.name).all()
    return render_template('inventory/medicine_availability.html',
                           results=results, query=q,
                           medicines_all=medicines_all)
