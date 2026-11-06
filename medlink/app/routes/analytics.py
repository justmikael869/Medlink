from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
from app.models import (Alert, StockItem, Facility, Medicine,
                        SearchGap, Order, StockTransaction, District)
from app import db
from sqlalchemy import func, desc
from datetime import datetime, timedelta
from collections import defaultdict

analytics_bp = Blueprint('analytics', __name__, url_prefix='/analytics')


def analytics_required(f):
    from functools import wraps
    from flask import redirect, url_for, flash
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.role not in ('system_admin', 'district_officer'):
            flash('Analytics access requires district officer or admin role.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


@analytics_bp.route('/')
@login_required
@analytics_required
def index():
    # ── Top shortage medicines ──────────────────────────────
    top_shortage = (
        db.session.query(
            Medicine.name,
            func.count(Alert.id).label('alert_count')
        )
        .join(Alert, Alert.medicine_id == Medicine.id)
        .filter(Alert.status == 'open')
        .group_by(Medicine.id, Medicine.name)
        .order_by(desc('alert_count'))
        .limit(10).all()
    )

    # ── Top searched-but-not-found (gaps) ──────────────────
    top_gaps = (
        SearchGap.query
        .order_by(SearchGap.count.desc())
        .limit(10).all()
    )

    # ── Facilities with most open alerts ──────────────────
    top_facilities = (
        db.session.query(
            Facility.name,
            Facility.facility_type,
            func.count(Alert.id).label('alert_count')
        )
        .join(Alert, Alert.facility_id == Facility.id)
        .filter(Alert.status == 'open')
        .group_by(Facility.id, Facility.name, Facility.facility_type)
        .order_by(desc('alert_count'))
        .limit(10).all()
    )

    # ── Stock status summary ───────────────────────────────
    total_items = StockItem.query.count()
    out_of_stock = StockItem.query.filter(StockItem.quantity <= 0).count()
    low_stock = StockItem.query.filter(
        StockItem.quantity > 0,
        StockItem.quantity <= StockItem.minimum_threshold
    ).count()
    adequate = total_items - out_of_stock - low_stock

    # ── Alert trend (last 30 days) ─────────────────────────
    thirty_days = datetime.utcnow() - timedelta(days=30)
    alert_trend_raw = (
        db.session.query(
            func.date(Alert.created_at).label('day'),
            func.count(Alert.id).label('count')
        )
        .filter(Alert.created_at >= thirty_days)
        .group_by(func.date(Alert.created_at))
        .order_by('day')
        .all()
    )
    alert_trend = [{'day': str(r.day), 'count': r.count} for r in alert_trend_raw]

    # ── Order status summary ───────────────────────────────
    order_summary = (
        db.session.query(Order.status, func.count(Order.id))
        .group_by(Order.status).all()
    )
    order_summary = {s: c for s, c in order_summary}

    # ── Facilities map data ────────────────────────────────
    facilities_map = (
        Facility.query
        .filter(Facility.active == True, Facility.latitude != None)
        .all()
    )

    # ── Category stockout breakdown ───────────────────────
    cat_stockout = (
        db.session.query(
            Medicine.category,
            func.count(StockItem.id).label('out_count')
        )
        .join(StockItem, StockItem.medicine_id == Medicine.id)
        .filter(StockItem.quantity <= 0)
        .group_by(Medicine.category)
        .order_by(desc('out_count'))
        .all()
    )

    return render_template('analytics/index.html',
        top_shortage=top_shortage,
        top_gaps=top_gaps,
        top_facilities=top_facilities,
        total_items=total_items,
        out_of_stock=out_of_stock,
        low_stock=low_stock,
        adequate=adequate,
        alert_trend=alert_trend,
        order_summary=order_summary,
        facilities_map=facilities_map,
        cat_stockout=cat_stockout,
    )


@analytics_bp.route('/api/map-data')
@login_required
@analytics_required
def map_data():
    """JSON for the facilities shortage map."""
    facilities = Facility.query.filter(
        Facility.active == True,
        Facility.latitude != None
    ).all()

    result = []
    for f in facilities:
        open_alerts = Alert.query.filter_by(
            facility_id=f.id, status='open'
        ).count()
        critical = Alert.query.filter_by(
            facility_id=f.id, status='open', severity='critical'
        ).count()
        result.append({
            'id': f.id,
            'name': f.name,
            'type': f.facility_type,
            'lat': f.latitude,
            'lon': f.longitude,
            'open_alerts': open_alerts,
            'critical': critical,
            'district': f.district.name if f.district else f.country,
        })
    return jsonify(result)
