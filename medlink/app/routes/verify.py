"""
MedLink Uganda — Medicine Authenticity Verification
====================================================
Patients, pharmacists, and doctors can verify a medicine's batch number
to confirm it is genuine, not expired, and not recalled.

In production: integrate with NDA Uganda's batch registry API.
In demo mode: batches are seeded from supplier manifests in MedLink's own database.
"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import current_user
from app import db
from app.models import MedicineBatch, MedicineVerification, Medicine
from datetime import date

verify_bp = Blueprint('verify', __name__, url_prefix='/verify')


@verify_bp.route('/', methods=['GET', 'POST'])
def index():
    result = None
    batch_no = ''
    if request.method == 'POST':
        batch_no = request.form.get('batch_number', '').strip().upper()
        lat = request.form.get('lat', type=float)
        lon = request.form.get('lon', type=float)
        if batch_no:
            result = _verify(batch_no, lat, lon)
    return render_template('verify/index.html', result=result, batch_no=batch_no)


@verify_bp.route('/api', methods=['POST'])
def api_verify():
    """JSON endpoint — used for QR scanner and USSD integration."""
    data = request.get_json(force=True) or {}
    batch_no = (data.get('batch_number') or '').strip().upper()
    lat = data.get('lat')
    lon = data.get('lon')
    if not batch_no:
        return jsonify({'error': 'batch_number required'}), 400
    result = _verify(batch_no, lat, lon)
    return jsonify(result)


@verify_bp.route('/admin/batches')
def batch_list():
    """Admin/pharmacist view of the batch registry."""
    from flask_login import login_required
    if not current_user.is_authenticated or current_user.role not in (
        'pharmacist', 'facility_admin', 'system_admin', 'district_officer', 'staff'
    ):
        return redirect(url_for('verify.index'))
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '')
    q = request.args.get('q', '')
    query = MedicineBatch.query
    if status: query = query.filter_by(status=status)
    if q: query = query.filter(MedicineBatch.batch_number.ilike(f'%{q}%'))
    batches = query.order_by(MedicineBatch.created_at.desc()).paginate(page=page, per_page=30)
    return render_template('verify/batch_list.html', batches=batches, status=status, q=q)


@verify_bp.route('/admin/batches/new', methods=['GET', 'POST'])
def add_batch():
    """Pharmacist / admin registers a new verified batch."""
    from flask_login import login_required
    if not current_user.is_authenticated or current_user.role not in (
        'pharmacist', 'facility_admin', 'system_admin', 'staff'
    ):
        flash('Not authorised.', 'danger')
        return redirect(url_for('verify.index'))

    medicines = Medicine.query.order_by(Medicine.name).all()
    if request.method == 'POST':
        batch_no = request.form.get('batch_number', '').strip().upper()
        if not batch_no:
            flash('Batch number is required.', 'danger')
            return render_template('verify/add_batch.html', medicines=medicines)

        existing = MedicineBatch.query.filter_by(batch_number=batch_no).first()
        if existing:
            flash(f'Batch {batch_no} is already registered.', 'warning')
            return redirect(url_for('verify.batch_list'))

        from datetime import datetime
        def parse_date(s):
            try: return datetime.strptime(s, '%Y-%m-%d').date() if s else None
            except: return None

        batch = MedicineBatch(
            batch_number = batch_no,
            medicine_id = int(request.form.get('medicine_id')),
            manufacturer = request.form.get('manufacturer', ''),
            manufacture_date = parse_date(request.form.get('manufacture_date')),
            expiry_date = parse_date(request.form.get('expiry_date')),
            country_of_origin= request.form.get('country', ''),
            nda_approval_no = request.form.get('nda_approval', ''),
            status = 'active',
            registered_by = current_user.id,
        )
        db.session.add(batch)
        db.session.commit()
        flash(f'Batch {batch_no} registered successfully.', 'success')
        return redirect(url_for('verify.batch_list'))

    return render_template('verify/add_batch.html', medicines=medicines)


@verify_bp.route('/admin/batches/<int:bid>/recall', methods=['POST'])
def recall_batch(bid):
    if not current_user.is_authenticated or current_user.role not in ('system_admin', 'district_officer'):
        flash('Not authorised.', 'danger')
        return redirect(url_for('verify.batch_list'))
    batch = MedicineBatch.query.get_or_404(bid)
    batch.status = 'recalled'
    batch.recall_reason = request.form.get('reason', 'Recalled by authority')
    db.session.commit()
    flash(f'Batch {batch.batch_number} marked as RECALLED.', 'warning')
    return redirect(url_for('verify.batch_list'))


def _verify(batch_no: str, lat=None, lon=None) -> dict:
    """Core verification logic. Returns a result dict."""
    batch = MedicineBatch.query.filter_by(batch_number=batch_no).first()

    user_id = current_user.id if current_user.is_authenticated else None
    facility_id = current_user.facility_id if current_user.is_authenticated else None

    if not batch:
        result = {
            'status': 'not_found',
            'batch': batch_no,
            'medicine': None,
            'message': (
                'This batch number was not found in the MedLink / NDA registry. '
                'This medicine may be counterfeit, unregistered, or imported without NDA approval. '
                'Do NOT dispense or consume. Report to NDA Uganda: 0800 200 680.'
            ),
            'color': 'danger',
            'icon': 'ti-alert-octagon',
        }
        _log(batch_no, None, 'not_found', user_id, facility_id, lat, lon)
        return result

    today = date.today()

    if batch.status == 'recalled':
        result = {
            'status': 'recalled',
            'batch': batch_no,
            'medicine': batch.medicine.name,
            'manufacturer': batch.manufacturer,
            'message': (
                f'RECALLED — this batch has been recalled. Reason: {batch.recall_reason or "See NDA notice"}. '
                f'Do NOT use. Return to supplier or destroy safely.'
            ),
            'color': 'danger',
            'icon': 'ti-ban',
        }
        _log(batch_no, batch.medicine_id, 'recalled', user_id, facility_id, lat, lon)
        return result

    if batch.expiry_date and batch.expiry_date < today:
        result = {
            'status': 'expired',
            'batch': batch_no,
            'medicine': batch.medicine.name,
            'manufacturer': batch.manufacturer,
            'expiry': batch.expiry_date.strftime('%d %b %Y'),
            'message': (
                f'This medicine expired on {batch.expiry_date.strftime("%d %b %Y")}. '
                'Expired medicines must not be dispensed or consumed. Return to supplier.'
            ),
            'color': 'warning',
            'icon': 'ti-clock-x',
        }
        _log(batch_no, batch.medicine_id, 'expired', user_id, facility_id, lat, lon)
        return result

    # All good
    days_left = (batch.expiry_date - today).days if batch.expiry_date else None
    result = {
        'status': 'verified',
        'batch': batch_no,
        'medicine': batch.medicine.name,
        'generic': batch.medicine.generic_name or '',
        'manufacturer': batch.manufacturer or 'Unknown',
        'country': batch.country_of_origin or '',
        'nda_approval': batch.nda_approval_no or 'N/A',
        'manufacture_date':batch.manufacture_date.strftime('%d %b %Y') if batch.manufacture_date else '—',
        'expiry': batch.expiry_date.strftime('%d %b %Y') if batch.expiry_date else '—',
        'days_left': days_left,
        'prescription_req':batch.medicine.prescription_required,
        'cold_chain': batch.medicine.requires_cold_chain,
        'message': 'This medicine is genuine and registered with the NDA Uganda.',
        'color': 'success',
        'icon': 'ti-circle-check',
    }
    _log(batch_no, batch.medicine_id, 'verified', user_id, facility_id, lat, lon)
    return result


def _log(batch_no, medicine_id, result_status, user_id, facility_id, lat, lon):
    db.session.add(MedicineVerification(
        batch_number = batch_no,
        medicine_id = medicine_id,
        result = result_status,
        checked_by = user_id,
        facility_id = facility_id,
        user_lat = lat,
        user_lon = lon,
    ))
    db.session.commit()


@verify_bp.route('/api/stats')
def api_stats():
    from sqlalchemy import func
    total = MedicineVerification.query.count()
    verified = MedicineVerification.query.filter_by(result='verified').count()
    issues = total - verified
    return jsonify({'total': total, 'verified': verified, 'issues': issues})
