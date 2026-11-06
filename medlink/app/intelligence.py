"""
MedLink Intelligence Engine
============================
All the automated logic that connects the platform pieces:

  trigger_restock_suggestion() — called when stock hits zero/low
  notify_distributor() — called when alert has notify_distributor=True
  record_search_gap() — called when search returns 0 results
  check_expiry_alerts() — scheduled: scan for soon-to-expire stock
  send_notification() — central notification dispatcher
  get_unread_count() — quick badge counter for navbar
"""

from app import db
from app.models import (
    StockItem, Alert, Facility, Medicine, Notification,
    RestockSuggestion, SearchGap, Order, OrderItem, User
)
from datetime import datetime, timedelta, date
import uuid


# ─────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────

def send_notification(title, body, notif_type,
                      recipient_facility_id=None, recipient_user_id=None,
                      related_alert_id=None, related_order_id=None,
                      related_facility_id=None):
    """Create an in-app notification record."""
    n = Notification(
        recipient_facility_id=recipient_facility_id,
        recipient_user_id=recipient_user_id,
        title=title,
        body=body,
        notif_type=notif_type,
        related_alert_id=related_alert_id,
        related_order_id=related_order_id,
        related_facility_id=related_facility_id,
    )
    db.session.add(n)
    # Don't commit here — caller handles the transaction


def get_unread_count(user):
    """Return unread notification count for a user's notification bell."""
    q = Notification.query.filter_by(is_read=False)
    if user.role in ('system_admin', 'district_officer'):
        return q.count()
    if user.facility_id:
        return q.filter_by(recipient_facility_id=user.facility_id).count()
    return q.filter_by(recipient_user_id=user.id).count()


def get_notifications_for_user(user, limit=30):
    q = Notification.query.filter_by(is_read=False)
    if user.role in ('system_admin', 'district_officer'):
        pass # see all
    elif user.facility_id:
        q = q.filter_by(recipient_facility_id=user.facility_id)
    else:
        q = q.filter_by(recipient_user_id=user.id)
    return q.order_by(Notification.created_at.desc()).limit(limit).all()


# ─────────────────────────────────────────────
# AUTO-RESTOCK SUGGESTION
# ─────────────────────────────────────────────

def trigger_restock_suggestion(stock_item, alert=None):
    """
    When stock hits zero or critical level:
    1. Find the nearest distributor/manufacturer that has this medicine in stock.
    2. Create a RestockSuggestion record.
    3. Send notifications to the facility and to the distributor.
    """
    facility = stock_item.facility
    medicine = stock_item.medicine

    # Don't suggest if one already exists and is pending
    existing = RestockSuggestion.query.filter_by(
        facility_id=facility.id,
        medicine_id=medicine.id,
        status='pending'
    ).first()
    if existing:
        return existing

    # Find best supplier: distributor or manufacturer with stock, sorted by distance
    supplier_types = ['distributor', 'manufacturer']
    supplier_items = (
        StockItem.query
        .join(Facility)
        .filter(
            StockItem.medicine_id == medicine.id,
            StockItem.quantity > 50,
            Facility.facility_type.in_(supplier_types),
            Facility.active == True
        ).all()
    )

    best_supplier = None
    best_dist = 9999
    for si in supplier_items:
        sup = si.facility
        if facility.latitude and facility.longitude and sup.latitude and sup.longitude:
            d = facility.distance_km(sup.latitude, sup.longitude)
        else:
            d = 9999 if sup.country != 'Uganda' else 500
        if d < best_dist:
            best_dist = d
            best_supplier = sup

    # Suggested qty: 3× the minimum threshold
    suggested_qty = stock_item.minimum_threshold * 3

    suggestion = RestockSuggestion(
        facility_id=facility.id,
        medicine_id=medicine.id,
        suggested_supplier_id=best_supplier.id if best_supplier else None,
        suggested_qty=suggested_qty,
        reason=f'Stock reached {"zero" if stock_item.quantity == 0 else "minimum threshold"}',
        alert_id=alert.id if alert else None,
    )
    db.session.add(suggestion)

    # Notify the facility
    supplier_name = best_supplier.name if best_supplier else 'a supplier'
    send_notification(
        title=f'Restock suggested: {medicine.name}',
        body=(f'Your stock of {medicine.name} is critically low. '
              f'We suggest ordering {suggested_qty} {medicine.unit} from {supplier_name}. '
              f'Click to convert to an order.'),
        notif_type='restock_suggestion',
        recipient_facility_id=facility.id,
        related_alert_id=alert.id if alert else None,
        related_facility_id=best_supplier.id if best_supplier else None,
    )

    # Also notify the distributor
    if best_supplier:
        send_notification(
            title=f'Supply request: {medicine.name}',
            body=(f'{facility.name} needs {suggested_qty} {medicine.unit} of {medicine.name}. '
                  f'A formal order may follow shortly.'),
            notif_type='distributor_alert',
            recipient_facility_id=best_supplier.id,
            related_facility_id=facility.id,
        )

    # Notify district officers for critical medicines
    if medicine.critical:
        district_officers = User.query.filter_by(
            role='district_officer'
        ).all()
        for officer in district_officers:
            send_notification(
                title=f'Critical stockout: {medicine.name} at {facility.name}',
                body=(f'{facility.name} ({facility.facility_type.replace("_"," ")}) '
                      f'has run out of {medicine.name}, a critical medicine. '
                      f'Restock suggestion sent to {supplier_name}.'),
                notif_type='stockout',
                recipient_user_id=officer.id,
                related_alert_id=alert.id if alert else None,
                related_facility_id=facility.id,
            )

    return suggestion


# ─────────────────────────────────────────────
# DISTRIBUTOR NOTIFICATION (manual alert trigger)
# ─────────────────────────────────────────────

def notify_distributor_of_alert(alert):
    """
    When a user raises an alert with notify_distributor=True,
    find the best distributor and notify them.
    """
    facility = alert.facility
    medicine = alert.medicine

    # Find distributors with this medicine
    supplier_items = (
        StockItem.query
        .join(Facility)
        .filter(
            StockItem.medicine_id == medicine.id,
            StockItem.quantity > 0,
            Facility.facility_type.in_(['distributor', 'manufacturer']),
            Facility.active == True,
            Facility.country == 'Uganda' # local first
        ).all()
    )

    notified = 0
    for si in supplier_items[:3]: # Notify up to 3 suppliers
        send_notification(
            title=f'Urgent supply needed: {medicine.name}',
            body=(f'{facility.name} ({facility.district.name if facility.district else facility.country}) '
                  f'urgently needs {alert.quantity_needed or "unspecified"} {medicine.unit} '
                  f'of {medicine.name}. Severity: {alert.severity}.'
                  + (f' Note: {alert.note}' if alert.note else '')),
            notif_type='distributor_alert',
            recipient_facility_id=si.facility_id,
            related_alert_id=alert.id,
            related_facility_id=facility.id,
        )
        notified += 1

    return notified


# ─────────────────────────────────────────────
# SEARCH GAP DETECTION
# ─────────────────────────────────────────────

def record_search_gap(query, search_type, lat=None, lon=None):
    """
    Called when a search returns 0 results.
    Logs the gap and notifies district officers if this query
    has been searched 3+ times with no results.
    """
    # Check if this gap already exists
    from sqlalchemy import func
    gap = SearchGap.query.filter(
        func.lower(SearchGap.search_query) == query.lower(),
        SearchGap.search_type == search_type
    ).first()

    if gap:
        gap.count += 1
        gap.last_searched = datetime.utcnow()
        if lat: gap.user_lat = lat
        if lon: gap.user_lon = lon
    else:
        gap = SearchGap(
            search_query=query,
            search_type=search_type,
            count=1,
            user_lat=lat,
            user_lon=lon,
        )
        db.session.add(gap)

    # Notify district officers after 3 failed searches for the same thing
    threshold = 3
    if gap.count >= threshold and not gap.district_notified:
        gap.district_notified = True
        officers = User.query.filter(
            User.role.in_(['district_officer', 'system_admin'])
        ).all()
        for officer in officers:
            send_notification(
                title=f'Supply gap detected: "{query}"',
                body=(f'"{query}" has been searched {gap.count} times '
                      f'with no results found nearby. '
                      f'This suggests a supply gap in the network. '
                      f'Consider alerting suppliers or adding stock.'),
                notif_type='search_gap',
                recipient_user_id=officer.id,
            )

    return gap


# ─────────────────────────────────────────────
# EXPIRY ALERTS
# ─────────────────────────────────────────────

def check_expiry_alerts(days_ahead=90):
    """
    Scan all stock items for medicines expiring within `days_ahead` days.
    Creates alerts and notifications for each.
    Should be called daily (via a scheduler or manual trigger).
    Returns count of new alerts raised.
    """
    cutoff = date.today() + timedelta(days=days_ahead)
    soon_expiring = (
        StockItem.query
        .filter(
            StockItem.expiry_date != None,
            StockItem.expiry_date <= cutoff,
            StockItem.expiry_date >= date.today(),
            StockItem.quantity > 0,
        ).all()
    )

    raised = 0
    for item in soon_expiring:
        days_left = (item.expiry_date - date.today()).days

        # Skip if we already have an open expiry alert for this item
        existing = Alert.query.filter_by(
            facility_id=item.facility_id,
            medicine_id=item.medicine_id,
            status='open',
            source='expiry'
        ).first()
        if existing:
            continue

        severity = 'critical' if days_left <= 30 else 'medium' if days_left <= 60 else 'low'

        alert = Alert(
            facility_id=item.facility_id,
            medicine_id=item.medicine_id,
            raised_by=1, # system user
            severity=severity,
            source='expiry',
            note=f'Expiring in {days_left} days ({item.expiry_date}). Qty: {item.quantity} {item.medicine.unit}.',
        )
        db.session.add(alert)
        db.session.flush()

        send_notification(
            title=f'Expiry alert: {item.medicine.name}',
            body=(f'{item.quantity} {item.medicine.unit} of {item.medicine.name} '
                  f'at {item.facility.name} expires in {days_left} days '
                  f'({item.expiry_date}). Consider redistributing or returning to supplier.'),
            notif_type='expiry',
            recipient_facility_id=item.facility_id,
            related_alert_id=alert.id,
        )
        raised += 1

    db.session.commit()
    return raised


# ─────────────────────────────────────────────
# CONVERT RESTOCK SUGGESTION → ORDER
# ─────────────────────────────────────────────

def accept_restock_suggestion(suggestion_id, user):
    """Convert a restock suggestion into a real order automatically."""
    suggestion = RestockSuggestion.query.get(suggestion_id)
    if not suggestion or suggestion.status != 'pending':
        return None

    order = Order(
        buyer_facility_id = suggestion.facility_id,
        seller_facility_id = suggestion.suggested_supplier_id,
        external_supplier = None,
        order_number = 'ORD-AUTO-' + uuid.uuid4().hex[:6].upper(),
        status = 'pending',
        currency = 'UGX',
        notes = f'Auto-generated from restock suggestion #{suggestion.id}. Reason: {suggestion.reason}',
        created_by = user.id,
    )
    db.session.add(order)
    db.session.flush()

    oi = OrderItem(
        order_id = order.id,
        medicine_id = suggestion.medicine_id,
        quantity = suggestion.suggested_qty,
        unit_price = 0.0,
        total_price = 0.0,
    )
    db.session.add(oi)

    suggestion.status = 'accepted'

    # Notify both sides
    send_notification(
        title=f'Order placed: {suggestion.medicine.name}',
        body=f'Order {order.order_number} placed for {suggestion.suggested_qty} {suggestion.medicine.unit}.',
        notif_type='order_update',
        recipient_facility_id=suggestion.facility_id,
        related_order_id=order.id,
    )
    if suggestion.suggested_supplier_id:
        send_notification(
            title=f'New order received: {suggestion.medicine.name}',
            body=f'{suggestion.facility.name} placed order {order.order_number} for {suggestion.suggested_qty} {suggestion.medicine.unit}.',
            notif_type='order_update',
            recipient_facility_id=suggestion.suggested_supplier_id,
            related_order_id=order.id,
        )

    db.session.commit()
    return order
