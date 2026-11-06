"""
Payment service — wraps Flutterwave Uganda API.
Set FLUTTERWAVE_SECRET_KEY in .env for live mode.
Without the key the service runs in simulation mode (demo/championship).
"""
import os, uuid, hmac, hashlib, json
import urllib.request, urllib.error

FLW_SECRET = os.getenv('FLUTTERWAVE_SECRET_KEY', '')
FLW_BASE_URL = 'https://api.flutterwave.com/v3'
SIMULATION = not FLW_SECRET


def _post(endpoint, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        FLW_BASE_URL + endpoint, data=data,
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {FLW_SECRET}'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


def initiate_momo_topup(amount_ugx, phone, network, tx_ref, name):
    """
    Initiate Uganda Mobile Money charge via Flutterwave.
    network: 'mtn_momo' | 'airtel_money'
    Returns: {success, flw_ref, message, simulation}
    """
    if SIMULATION:
        return {
            'success': True,
            'flw_ref': 'SIM-' + uuid.uuid4().hex[:8].upper(),
            'message': f'Demo mode: UGX {amount_ugx:,.0f} credited from {phone}. '
                       f'In production this triggers a real {network.replace("_"," ").title()} prompt.',
            'simulation': True,
        }
    net_map = {'mtn_momo': 'MTN', 'airtel_money': 'AIRTEL'}
    result = _post('/charges?type=mobile_money_uganda', {
        'phone_number': phone,
        'network': net_map.get(network, 'MTN'),
        'amount': amount_ugx,
        'currency': 'UGX',
        'email': 'topup@medlink.ug',
        'fullname': name,
        'tx_ref': tx_ref,
        'redirect_url': os.getenv('APP_URL', 'http://localhost:5000') + '/payments/webhook',
    })
    if result.get('status') == 'success':
        return {'success': True,
                'flw_ref': result['data'].get('flw_ref', ''),
                'message': f'Approve the payment prompt sent to {phone}.',
                'simulation': False}
    return {'success': False, 'flw_ref': '',
            'message': result.get('message', 'Payment initiation failed.'),
            'simulation': False}


def verify_payment(flw_ref):
    if SIMULATION:
        return {'success': True, 'status': 'successful', 'simulation': True}
    result = _post(f'/transactions/verify_by_reference?tx_ref={flw_ref}', {})
    if result.get('status') == 'success':
        return {'success': result['data'].get('status') == 'successful',
                'status': result['data'].get('status', ''),
                'amount': result['data'].get('amount', 0),
                'simulation': False}
    return {'success': False, 'status': 'failed', 'simulation': False}


def verify_webhook_signature(payload_bytes, signature):
    if SIMULATION:
        return True
    secret = os.getenv('FLUTTERWAVE_WEBHOOK_SECRET', FLW_SECRET)
    expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
