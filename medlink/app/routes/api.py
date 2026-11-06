from flask import Blueprint, jsonify, request
from app.models import Medicine, StockItem, Facility
from app import db

api_bp = Blueprint('api', __name__, url_prefix='/api/v1')

@api_bp.route('/medicines')
def medicines():
    ms = Medicine.query.order_by(Medicine.name).all()
    return jsonify([{
        'id': m.id, 'name': m.name, 'generic_name': m.generic_name,
        'category': m.category, 'dosage_form': m.dosage_form,
        'strength': m.strength, 'unit': m.unit, 'diseases': m.disease_list(),
        'critical': m.critical,
    } for m in ms])

@api_bp.route('/search')
def search():
    q = request.args.get('q', '').strip()
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    radius = request.args.get('radius', type=float, default=50)
    search_type = request.args.get('type', 'medicine') # medicine or disease

    if not q:
        return jsonify({'error': 'Query required'}), 400

    from sqlalchemy import or_
    if search_type == 'disease':
        meds = Medicine.query.filter(
            or_(Medicine.diseases.ilike(f'%{q}%'),
                Medicine.category.ilike(f'%{q}%'))
        ).all()
    else:
        meds = Medicine.query.filter(
            or_(Medicine.name.ilike(f'%{q}%'),
                Medicine.generic_name.ilike(f'%{q}%'))
        ).all()

    med_ids = [m.id for m in meds]
    if not med_ids:
        return jsonify({'results': [], 'count': 0})

    items = StockItem.query.filter(
        StockItem.medicine_id.in_(med_ids),
        StockItem.quantity > 0,
        StockItem.is_available == True
    ).all()

    results = []
    seen = set()
    for item in items:
        fac = item.facility
        if not fac or not fac.active:
            continue
        dist = fac.distance_km(lat, lon) if lat and lon else None
        if dist and dist > radius:
            continue
        if fac.id not in seen:
            seen.add(fac.id)
            results.append({
                'facility_id': fac.id,
                'facility_name': fac.name,
                'facility_type': fac.facility_type,
                'address': fac.address,
                'phone': fac.phone,
                'lat': fac.latitude,
                'lon': fac.longitude,
                'distance_km': round(dist, 2) if dist else None,
                'medicines': []
            })
        for r in results:
            if r['facility_id'] == fac.id:
                r['medicines'].append({
                    'id': item.medicine_id,
                    'name': item.medicine.name,
                    'quantity': item.quantity,
                    'price_ugx': item.unit_price,
                })

    results.sort(key=lambda x: x['distance_km'] if x['distance_km'] else 9999)
    return jsonify({'results': results, 'count': len(results), 'query': q})


@api_bp.route('/facilities/<int:fid>/stock')
def facility_stock(fid):
    fac = Facility.query.get_or_404(fid)
    items = StockItem.query.filter_by(facility_id=fid, is_available=True).all()
    return jsonify({
        'facility': fac.name,
        'type': fac.facility_type,
        'stock': [{
            'medicine': i.medicine.name,
            'quantity': i.quantity,
            'status': i.status,
            'price_ugx': i.unit_price,
        } for i in items if i.quantity > 0]
    })
