from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.models import Order, OrderItem, Medicine, Facility
from datetime import datetime
import uuid

orders_bp = Blueprint('orders', __name__, url_prefix='/orders')

EXTERNAL_SUPPLIERS = [
    'National Medical Stores (NMS) - Uganda',
    'JICC Pharmaceuticals - China',
    'Guangzhou Pharma Co. - China',
    'Sino Biopharmaceutical - China',
    'Sun Pharmaceutical - India',
    'Cipla Ltd - India',
    'Strides Shasun - India',
    'Aspen Pharmacare - South Africa',
    'Laborex Uganda',
    'Other (specify in notes)',
]

@orders_bp.route('/')
@login_required
def index():
    fid = current_user.facility_id
    is_admin = current_user.role in ('system_admin', 'district_officer')

    if is_admin:
        orders = Order.query.order_by(Order.created_at.desc()).all()
    else:
        orders = Order.query.filter_by(buyer_facility_id=fid)\
                            .order_by(Order.created_at.desc()).all()

    # Also show incoming orders if this facility is a supplier/distributor
    incoming = Order.query.filter_by(seller_facility_id=fid)\
                          .order_by(Order.created_at.desc()).all() if fid else []

    return render_template('orders/index.html', orders=orders, incoming=incoming)


@orders_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    medicines = Medicine.query.order_by(Medicine.category, Medicine.name).all()
    suppliers = Facility.query.filter(
        Facility.facility_type.in_(['distributor', 'manufacturer'])
    ).filter_by(active=True).order_by(Facility.name).all()

    if request.method == 'POST':
        supplier_type = request.form.get('supplier_type', 'external')
        seller_fid = request.form.get('seller_facility_id')
        ext_supplier = request.form.get('external_supplier', '')

        order = Order(
            buyer_facility_id = current_user.facility_id,
            seller_facility_id = int(seller_fid) if seller_fid else None,
            external_supplier = ext_supplier if supplier_type == 'external' else None,
            order_number = 'ORD-' + uuid.uuid4().hex[:8].upper(),
            status = 'pending',
            currency = request.form.get('currency', 'UGX'),
            delivery_address = request.form.get('delivery_address', ''),
            notes = request.form.get('notes', ''),
            created_by = current_user.id,
        )
        if request.form.get('expected_delivery'):
            order.expected_delivery = datetime.strptime(
                request.form.get('expected_delivery'), '%Y-%m-%d').date()

        db.session.add(order)
        db.session.flush()

        total = 0.0
        for med in medicines:
            qty = request.form.get(f'qty_{med.id}')
            price = request.form.get(f'price_{med.id}', '0')
            if qty and int(qty) > 0:
                unit_price = float(price or 0)
                total_price = int(qty) * unit_price
                total += total_price
                oi = OrderItem(
                    order_id=order.id,
                    medicine_id=med.id,
                    quantity=int(qty),
                    unit_price=unit_price,
                    total_price=total_price,
                )
                db.session.add(oi)

        order.total_amount = total
        db.session.commit()
        flash(f'Order {order.order_number} placed successfully!', 'success')
        return redirect(url_for('orders.detail', order_id=order.id))

    return render_template('orders/new.html', medicines=medicines,
                           suppliers=suppliers,
                           external_suppliers=EXTERNAL_SUPPLIERS)


@orders_bp.route('/<int:order_id>')
@login_required
def detail(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('orders/detail.html', order=order)


@orders_bp.route('/<int:order_id>/status', methods=['POST'])
@login_required
def update_status(order_id):
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get('status')
    allowed = ['pending','confirmed','processing','shipped','delivered','cancelled']
    if new_status in allowed:
        order.status = new_status
        order.updated_at = datetime.utcnow()

        # When delivered, auto-update stock
        if new_status == 'delivered':
            for oi in order.items:
                stock = StockItem.query.filter_by(
                    facility_id=order.buyer_facility_id,
                    medicine_id=oi.medicine_id
                ).first()
                if not stock:
                    stock = StockItem(
                        facility_id=order.buyer_facility_id,
                        medicine_id=oi.medicine_id
                    )
                    db.session.add(stock)
                stock.quantity += oi.quantity
                stock.last_updated = datetime.utcnow()
                from app.models import StockTransaction
                tx = StockTransaction(
                    stock_item_id=stock.id,
                    transaction_type='received',
                    quantity_change=oi.quantity,
                    quantity_after=stock.quantity,
                    note=f'From order {order.order_number}',
                    performed_by=current_user.id
                )
                db.session.add(tx)
        db.session.commit()
        flash(f'Order status updated to {new_status}.', 'success')
    return redirect(url_for('orders.detail', order_id=order_id))
