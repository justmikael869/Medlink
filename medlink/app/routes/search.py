from flask import Blueprint, render_template, request, jsonify
from app.models import Medicine, StockItem, Facility, SearchLog
from app import db
from sqlalchemy import or_

search_bp = Blueprint('search', __name__, url_prefix='/search')

@search_bp.route('/')
def index():
    return render_template('search/index.html')


@search_bp.route('/medicine')
def by_medicine():
    """Search for a medicine by name — returns nearby facilities that have it."""
    query = request.args.get('q', '').strip()
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    max_km = request.args.get('radius', type=float, default=50.0)

    results = []
    medicines_found = []

    if query:
        medicines_found = Medicine.query.filter(
            or_(Medicine.name.ilike(f'%{query}%'),
                Medicine.generic_name.ilike(f'%{query}%'),
                Medicine.brand_name.ilike(f'%{query}%'))
        ).all()

        med_ids = [m.id for m in medicines_found]
        if med_ids:
            items = (StockItem.query
                     .filter(StockItem.medicine_id.in_(med_ids),
                             StockItem.quantity > 0,
                             StockItem.is_available == True)
                     .all())

            seen = set()
            for item in items:
                fac = item.facility
                if not fac or not fac.active:
                    continue
                dist = fac.distance_km(lat, lon) if (lat and lon) else None
                if dist and dist > max_km:
                    continue
                key = (fac.id, item.medicine_id)
                if key not in seen:
                    seen.add(key)
                    results.append({
                        'facility': fac,
                        'medicine': item.medicine,
                        'quantity': item.quantity,
                        'unit_price': item.unit_price,
                        'distance_km': round(dist, 1) if dist else None,
                    })

        results.sort(key=lambda x: x['distance_km'] if x['distance_km'] is not None else 9999)

        # Log search + record gap if no results
        log = SearchLog(query=query, search_type='medicine',
                        user_lat=lat, user_lon=lon, results_found=len(results))
        db.session.add(log)
        if len(results) == 0:
            from app.intelligence import record_search_gap
            record_search_gap(query, 'medicine', lat, lon)
        db.session.commit()

    return render_template('search/results.html', query=query,
                           results=results, search_type='medicine',
                           lat=lat, lon=lon)


@search_bp.route('/disease')
def by_disease():
    """Search by disease name — returns medicines for it, then nearby facilities."""
    query = request.args.get('q', '').strip()
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    max_km = request.args.get('radius', type=float, default=50.0)

    results = []
    medicines_found = []

    if query:
        medicines_found = Medicine.query.filter(
            or_(Medicine.diseases.ilike(f'%{query}%'),
                Medicine.category.ilike(f'%{query}%'),
                Medicine.name.ilike(f'%{query}%'))
        ).all()

        med_ids = [m.id for m in medicines_found]
        if med_ids:
            items = (StockItem.query
                     .filter(StockItem.medicine_id.in_(med_ids),
                             StockItem.quantity > 0,
                             StockItem.is_available == True)
                     .all())

            seen = set()
            for item in items:
                fac = item.facility
                if not fac or not fac.active:
                    continue
                dist = fac.distance_km(lat, lon) if (lat and lon) else None
                if dist and dist > max_km:
                    continue
                key = fac.id
                if key not in seen:
                    seen.add(key)
                    results.append({
                        'facility': fac,
                        'medicines_available': [],
                        'distance_km': round(dist, 1) if dist else None,
                    })
                # Add medicine to this facility's list
                for r in results:
                    if r['facility'].id == fac.id:
                        r['medicines_available'].append({
                            'name': item.medicine.name,
                            'quantity': item.quantity,
                            'price': item.unit_price,
                        })
                        break

        results.sort(key=lambda x: x['distance_km'] if x['distance_km'] is not None else 9999)

        log = SearchLog(query=query, search_type='disease',
                        user_lat=lat, user_lon=lon, results_found=len(results))
        db.session.add(log)
        if len(results) == 0:
            from app.intelligence import record_search_gap
            record_search_gap(query, 'disease', lat, lon)
        db.session.commit()

    return render_template('search/results.html', query=query,
                           results=results, search_type='disease',
                           medicines_found=medicines_found,
                           lat=lat, lon=lon)


@search_bp.route('/api/medicine')
def api_medicine_search():
    """JSON endpoint for live search (used by the map)."""
    q = request.args.get('q', '').strip()
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)

    if not q:
        return jsonify([])

    medicines = Medicine.query.filter(
        Medicine.name.ilike(f'%{q}%')
    ).all()
    med_ids = [m.id for m in medicines]
    if not med_ids:
        return jsonify([])

    items = StockItem.query.filter(
        StockItem.medicine_id.in_(med_ids),
        StockItem.quantity > 0,
        StockItem.is_available == True
    ).all()

    out = []
    seen = set()
    for item in items:
        fac = item.facility
        if not fac or not fac.active or fac.id in seen:
            continue
        seen.add(fac.id)
        dist = fac.distance_km(lat, lon) if lat and lon else None
        out.append({
            'id': fac.id,
            'name': fac.name,
            'type': fac.facility_type,
            'address': fac.address,
            'phone': fac.phone,
            'lat': fac.latitude,
            'lon': fac.longitude,
            'distance_km': round(dist, 2) if dist else None,
            'medicine': item.medicine.name,
            'quantity': item.quantity,
            'price': item.unit_price,
        })

    out.sort(key=lambda x: x['distance_km'] if x['distance_km'] else 9999)
    return jsonify(out[:20])


@search_bp.route('/gaps/map')
def gap_map():
    from flask_login import login_required, current_user
    from flask import abort
    from app.models import SearchGap
    # Simple role check without decorator
    try:
        from flask_login import current_user as cu
        if not cu.is_authenticated:
            from flask import redirect, url_for
            return redirect(url_for('auth.login'))
        if cu.role not in ('system_admin', 'district_officer'):
            abort(403)
    except Exception:
        abort(403)
    gaps = SearchGap.query.order_by(SearchGap.count.desc()).limit(200).all()
    facilities = Facility.query.filter(
        Facility.latitude.isnot(None), Facility.longitude.isnot(None)
    ).all()
    return render_template('search/gap_map.html', gaps=gaps, facilities=facilities)
