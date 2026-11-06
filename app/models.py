from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import math, uuid

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ─── GEOGRAPHY ───────────────────────────────────────────────────────────────

class District(db.Model):
    __tablename__ = 'districts'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    region = db.Column(db.String(100))
    lat = db.Column(db.Float) # district centroid for map
    lon = db.Column(db.Float)
    facilities = db.relationship('Facility', backref='district', lazy='dynamic')


class Facility(db.Model):
    __tablename__ = 'facilities'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    facility_type = db.Column(db.String(40), nullable=False)
    # government_clinic, private_clinic, pharmacy, drug_shop,
    # distributor, manufacturer, ngo_clinic, laboratory, insurance
    level = db.Column(db.String(30))
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=True)
    address = db.Column(db.String(255))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(150))
    website = db.Column(db.String(255))
    licence_no = db.Column(db.String(80))
    verified = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    # Supplier-specific
    is_supplier = db.Column(db.Boolean, default=False)
    supplier_type = db.Column(db.String(50)) # national, regional, international
    min_order_ugx = db.Column(db.Float, default=0)
    lead_time_days = db.Column(db.Integer, default=7)
    # Insurance-specific
    is_insurance = db.Column(db.Boolean, default=False)
    # Subscription tier (for SaaS revenue)
    subscription_tier = db.Column(db.String(20), default='free')
    # free, basic (100k/mo), professional (300k/mo), enterprise (custom)
    subscription_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    users = db.relationship('User', backref='facility', lazy=True)
    stock_items = db.relationship('StockItem', foreign_keys='StockItem.facility_id', backref='facility', lazy='dynamic')
    alerts = db.relationship('Alert', backref='facility', lazy=True)
    orders_placed = db.relationship('Order', foreign_keys='Order.buyer_facility_id',
                                       backref='buyer', lazy=True)
    orders_received = db.relationship('Order', foreign_keys='Order.seller_facility_id',
                                       backref='seller', lazy=True)
    appointments = db.relationship('Appointment', foreign_keys='Appointment.facility_id',
                                       backref='facility', lazy=True)

    def distance_km(self, lat, lon):
        if not self.latitude or not self.longitude: return 9999
        R = 6371
        dlat = math.radians(lat - self.latitude)
        dlon = math.radians(lon - self.longitude)
        a = (math.sin(dlat/2)**2 +
             math.cos(math.radians(self.latitude)) *
             math.cos(math.radians(lat)) * math.sin(dlon/2)**2)
        return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)), 1)

    def __repr__(self): return f'<Facility {self.name}>'


# ─── USERS ───────────────────────────────────────────────────────────────────

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(30), default='patient')
    # patient | doctor | pharmacist | supplier | driver | staff |
    # facility_admin | district_officer | system_admin | insurance_officer
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    phone = db.Column(db.String(30))
    national_id = db.Column(db.String(30)) # Uganda NIN
    date_of_birth = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(10))
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=True)
    address = db.Column(db.String(255))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    # Doctor fields
    umdpc_number = db.Column(db.String(80))
    specialisation = db.Column(db.String(100))
    languages = db.Column(db.String(200))
    consultation_fee_ugx = db.Column(db.Float, default=0.0)
    verified_doctor = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text)
    available_for_remote = db.Column(db.Boolean, default=True)

    # Driver fields
    vehicle_type = db.Column(db.String(50))
    plate_number = db.Column(db.String(30))
    has_cold_box = db.Column(db.Boolean, default=False)
    verified_driver = db.Column(db.Boolean, default=False)
    is_available = db.Column(db.Boolean, default=True)
    delivery_company_id = db.Column(db.Integer, db.ForeignKey('delivery_companies.id'), nullable=True)

    # Wallet
    wallet_balance_ugx = db.Column(db.Float, default=0.0)

    # Health record fields (patient)
    blood_type = db.Column(db.String(5))
    known_allergies = db.Column(db.Text)
    chronic_conditions= db.Column(db.Text)
    emergency_contact_name = db.Column(db.String(100))
    emergency_contact_phone = db.Column(db.String(30))
    insurance_number = db.Column(db.String(60))
    insurance_provider = db.Column(db.String(100))

    def set_password(self, pw): self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)
    def language_list(self):
        return [l.strip() for l in (self.languages or '').split(',') if l.strip()]

    home_district = db.relationship('District', foreign_keys=[district_id])

    def __repr__(self): return f'<User {self.email}>'


doctor_districts = db.Table('doctor_districts',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('district_id', db.Integer, db.ForeignKey('districts.id'), primary_key=True),
)


# ─── MEDICINES ───────────────────────────────────────────────────────────────

class Medicine(db.Model):
    __tablename__ = 'medicines'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    generic_name = db.Column(db.String(200))
    brand_name = db.Column(db.String(200))
    category = db.Column(db.String(80))
    dosage_form = db.Column(db.String(60))
    strength = db.Column(db.String(60))
    unit = db.Column(db.String(30))
    description = db.Column(db.Text)
    diseases = db.Column(db.String(500))
    critical = db.Column(db.Boolean, default=False)
    prescription_required= db.Column(db.Boolean, default=False)
    requires_cold_chain = db.Column(db.Boolean, default=False)
    controlled_drug = db.Column(db.Boolean, default=False)
    nda_code = db.Column(db.String(30)) # Uganda NDA registration code
    who_essential = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    stock_items = db.relationship('StockItem', backref='medicine', lazy=True)
    order_items = db.relationship('OrderItem', backref='medicine', lazy=True)

    def disease_list(self):
        return [d.strip() for d in (self.diseases or '').split(',') if d.strip()]



# ─── MEDICINE PROPOSALS ──────────────────────────────────────────────────────

class MedicineProposal(db.Model):
    """Any authorised user can propose a new medicine. Admin reviews and approves."""
    __tablename__ = 'medicine_proposals'
    id = db.Column(db.Integer, primary_key=True)
    proposed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    generic_name = db.Column(db.String(200))
    brand_name = db.Column(db.String(200))
    category = db.Column(db.String(80))
    dosage_form = db.Column(db.String(60))
    strength = db.Column(db.String(60))
    unit = db.Column(db.String(30))
    diseases = db.Column(db.String(500))
    description = db.Column(db.Text)
    nda_code = db.Column(db.String(30))
    prescription_required= db.Column(db.Boolean, default=False)
    requires_cold_chain = db.Column(db.Boolean, default=False)
    critical = db.Column(db.Boolean, default=False)
    who_essential = db.Column(db.Boolean, default=False)
    controlled_drug = db.Column(db.Boolean, default=False)
    proposer_note = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    # pending, approved, rejected
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    proposer = db.relationship('User', foreign_keys=[proposed_by], backref='medicine_proposals')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])


# ─── STOCK ───────────────────────────────────────────────────────────────────

class StockItem(db.Model):
    __tablename__ = 'stock_items'
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=False)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    unit_price = db.Column(db.Float, default=0.0)
    sell_price = db.Column(db.Float, default=0.0) # what facility charges patients
    minimum_threshold = db.Column(db.Integer, default=20)
    reorder_quantity = db.Column(db.Integer, default=100)
    expiry_date = db.Column(db.Date, nullable=True)
    batch_no = db.Column(db.String(60))
    supplier_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    is_available = db.Column(db.Boolean, default=True)

    transactions = db.relationship('StockTransaction', backref='stock_item', lazy=True)
    supplier = db.relationship('Facility', foreign_keys='StockItem.supplier_id', backref=db.backref('supplied_items', lazy='dynamic'))

    @property
    def status(self):
        if self.quantity <= 0: return 'out_of_stock'
        if self.quantity <= self.minimum_threshold: return 'low'
        return 'adequate'

    @property
    def days_to_expiry(self):
        if not self.expiry_date: return None
        return (self.expiry_date - datetime.utcnow().date()).days


class StockTransaction(db.Model):
    __tablename__ = 'stock_transactions'
    id = db.Column(db.Integer, primary_key=True)
    stock_item_id = db.Column(db.Integer, db.ForeignKey('stock_items.id'), nullable=False)
    transaction_type = db.Column(db.String(30))
    # received, dispensed, expired, adjustment, transferred, returned
    quantity_change = db.Column(db.Integer)
    quantity_after = db.Column(db.Integer)
    unit_price = db.Column(db.Float, default=0.0)
    batch_no = db.Column(db.String(60))
    reference = db.Column(db.String(60)) # order ref, delivery ref
    note = db.Column(db.String(255))
    performed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    dispensed_to = db.Column(db.String(120)) # patient name or ID at counter
    patient_ref = db.Column(db.String(60)) # optional patient ID / card number
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    performer = db.relationship('User', foreign_keys=[performed_by])


# ─── ALERTS ──────────────────────────────────────────────────────────────────

class Alert(db.Model):
    __tablename__ = 'alerts'
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=False)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False)
    raised_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    severity = db.Column(db.String(20), default='medium')
    status = db.Column(db.String(20), default='open')
    quantity_needed = db.Column(db.Integer)
    note = db.Column(db.Text)
    source = db.Column(db.String(20), default='manual')
    # manual, auto_threshold, auto_expiry, sms
    notify_district = db.Column(db.Boolean, default=False)
    notify_distributor = db.Column(db.Boolean, default=False)
    auto_reorder = db.Column(db.Boolean, default=False)
    resolved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolution_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    medicine = db.relationship('Medicine', foreign_keys=[medicine_id])
    reporter = db.relationship('User', foreign_keys=[raised_by])
    resolver = db.relationship('User', foreign_keys=[resolved_by])


# ─── SUPPLIER CATALOGUE ───────────────────────────────────────────────────────

class SupplierCatalogue(db.Model):
    """Medicines a supplier sells, with their price and lead time."""
    __tablename__ = 'supplier_catalogue'
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=False)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False)
    unit_price_ugx = db.Column(db.Float, nullable=False)
    min_order_qty = db.Column(db.Integer, default=1)
    lead_time_days = db.Column(db.Integer, default=7)
    in_stock = db.Column(db.Boolean, default=True)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    supplier = db.relationship('Facility', foreign_keys=[supplier_id])
    medicine = db.relationship('Medicine', foreign_keys=[medicine_id])


# ─── ORDERS ──────────────────────────────────────────────────────────────────

class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    buyer_facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=False)
    seller_facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    external_supplier = db.Column(db.String(200))
    order_number = db.Column(db.String(40), unique=True)
    status = db.Column(db.String(30), default='pending')
    # draft, pending, confirmed, dispatched, delivered, cancelled, disputed
    total_amount = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(10), default='UGX')
    delivery_address = db.Column(db.String(300))
    expected_delivery = db.Column(db.Date)
    actual_delivery = db.Column(db.Date)
    payment_method = db.Column(db.String(30)) # wallet, momo, credit, insurance
    payment_status = db.Column(db.String(20), default='unpaid')
    payment_ref = db.Column(db.String(60))
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    confirmed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = db.relationship('OrderItem', backref='order', lazy=True,
                                  cascade='all,delete-orphan')
    creator = db.relationship('User', foreign_keys=[created_by])
    confirmer = db.relationship('User', foreign_keys=[confirmed_by])


class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, default=0.0)
    total_price = db.Column(db.Float, default=0.0)
    received_qty= db.Column(db.Integer, default=0)


# ─── PAYMENTS & ESCROW ───────────────────────────────────────────────────────

class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(60), unique=True, nullable=False,
                                 default=lambda: 'PAY-' + uuid.uuid4().hex[:10].upper())
    idempotency_key = db.Column(db.String(64), unique=True)
    amount_ugx = db.Column(db.Float, nullable=False)
    platform_fee_ugx = db.Column(db.Float, default=0.0)
    net_amount_ugx = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(10), default='UGX')
    status = db.Column(db.String(20), default='pending')
    # pending → held → released → refunded → failed
    payment_type = db.Column(db.String(30))
    # consultation, delivery, transport, subscription, wallet_topup, medicine_order
    payer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    payee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    payer_facility_id= db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    payee_facility_id= db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    gateway_ref = db.Column(db.String(120))
    gateway_response = db.Column(db.Text)
    mobile_number = db.Column(db.String(20))
    network = db.Column(db.String(20)) # MTN, AIRTEL
    notes = db.Column(db.String(300))
    auto_release_at = db.Column(db.DateTime, nullable=True) # escrow auto-release
    escrow_released_at = db.Column(db.DateTime, nullable=True)
    released_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    payer = db.relationship('User', foreign_keys=[payer_id])
    payee = db.relationship('User', foreign_keys=[payee_id])
    released_by = db.relationship('User', foreign_keys=[released_by_id])
    audit_trail = db.relationship('PaymentAudit', backref='payment', lazy=True,
                                  cascade='all,delete-orphan')

    PLATFORM_FEE_PCT = 0.10

    def compute_fees(self):
        self.platform_fee_ugx = round(self.amount_ugx * self.PLATFORM_FEE_PCT, 0)
        self.net_amount_ugx = self.amount_ugx - self.platform_fee_ugx


class PaymentAudit(db.Model):
    __tablename__ = 'payment_audits'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=False)
    event = db.Column(db.String(50))
    old_status = db.Column(db.String(20))
    new_status = db.Column(db.String(20))
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    note = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    actor = db.relationship('User', foreign_keys=[actor_id])


# ─── APPOINTMENTS & CONSULTATIONS ────────────────────────────────────────────

class Appointment(db.Model):
    __tablename__ = 'appointments'
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(30), unique=True, nullable=False,
                            default=lambda: 'APT-' + uuid.uuid4().hex[:6].upper())
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    appt_type = db.Column(db.String(20), default='in_person')
    # in_person, remote, emergency
    department = db.Column(db.String(100))
    slot_time = db.Column(db.DateTime, nullable=True)
    duration_minutes = db.Column(db.Integer, default=30)
    status = db.Column(db.String(20), default='pending')
    # pending, confirmed, in_progress, completed, cancelled, no_show
    priority = db.Column(db.String(20), default='normal') # normal, urgent, emergency
    chief_complaint = db.Column(db.Text)
    notes = db.Column(db.Text)
    qr_code = db.Column(db.String(100))
    video_room_url = db.Column(db.String(255))
    reminder_sent = db.Column(db.Boolean, default=False, nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=True)
    triage_id = db.Column(db.Integer, db.ForeignKey('triage_assessments.id'), nullable=True)
    referred_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # doctor referral
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = db.relationship('User', foreign_keys=[patient_id],
                                  backref='appointments_as_patient')
    doctor = db.relationship('User', foreign_keys=[doctor_id],
                                  backref='appointments_as_doctor')
    referrer = db.relationship('User', foreign_keys=[referred_by])
    payment = db.relationship('Payment', foreign_keys=[payment_id])
    consultation= db.relationship('Consultation', backref='appointment', uselist=False,
                                  cascade='all,delete-orphan')


class Consultation(db.Model):
    __tablename__ = 'consultations'
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointments.id'), nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    # Clinical record
    presenting_complaints= db.Column(db.Text)
    history_of_illness = db.Column(db.Text)
    examination_findings = db.Column(db.Text)
    investigations = db.Column(db.Text) # labs, imaging requested
    diagnosis = db.Column(db.Text)
    icd10_code = db.Column(db.String(20))
    management_plan = db.Column(db.Text)
    prescription_text = db.Column(db.Text)
    follow_up_date = db.Column(db.Date, nullable=True)
    follow_up_notes = db.Column(db.Text)
    doctor_notes = db.Column(db.Text) # private, not visible to patient
    # Referral
    referral_needed = db.Column(db.Boolean, default=False)
    referred_to_facility = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    referred_to_name = db.Column(db.String(200))
    referral_reason = db.Column(db.Text)
    # Confirmation
    patient_confirmed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    referred_facility = db.relationship('Facility', foreign_keys=[referred_to_facility])
    prescriptions = db.relationship('Prescription', backref='consultation', lazy=True,
                                        cascade='all,delete-orphan')


class Prescription(db.Model):
    __tablename__ = 'prescriptions'
    id = db.Column(db.Integer, primary_key=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultations.id'), nullable=False)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=True)
    medicine_name = db.Column(db.String(200))
    dosage = db.Column(db.String(100))
    frequency = db.Column(db.String(100))
    duration_days = db.Column(db.Integer)
    route = db.Column(db.String(50)) # oral, IV, topical, inhaled
    instructions = db.Column(db.String(300)) # with food, avoid alcohol, etc.
    quantity_to_dispense = db.Column(db.Integer)
    dispensed = db.Column(db.Boolean, default=False)
    dispensed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    dispensed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    medicine = db.relationship('Medicine', foreign_keys=[medicine_id])
    dispenser = db.relationship('User', foreign_keys=[dispensed_by])


# ─── TRIAGE ──────────────────────────────────────────────────────────────────

class TriageAssessment(db.Model):
    __tablename__ = 'triage_assessments'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    patient_age = db.Column(db.Integer)
    patient_gender = db.Column(db.String(10))
    symptoms_text = db.Column(db.Text)
    answers_json = db.Column(db.Text)
    severity = db.Column(db.String(20))
    recommendation = db.Column(db.Text)
    suggested_specialisation = db.Column(db.String(100))
    suggested_facility_type = db.Column(db.String(50))
    led_to_appointment_id = db.Column(db.Integer, db.ForeignKey('appointments.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ─── DELIVERY ────────────────────────────────────────────────────────────────

class DeliveryCompany(db.Model):
    __tablename__ = 'delivery_companies'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    contact_phone = db.Column(db.String(30))
    contact_email = db.Column(db.String(150))
    verified = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    coverage_districts = db.Column(db.Text) # JSON list of district names
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    drivers = db.relationship('User', backref='delivery_company',
                              foreign_keys='User.delivery_company_id', lazy=True)


class DeliveryOrder(db.Model):
    __tablename__ = 'delivery_orders'
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(30), unique=True, nullable=False,
                                 default=lambda: 'DEL-' + uuid.uuid4().hex[:6].upper())
    delivery_type = db.Column(db.String(20)) # medicine, patient_transport
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    prescription_id = db.Column(db.Integer, db.ForeignKey('prescriptions.id'), nullable=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointments.id'), nullable=True)
    pharmacy_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    destination_facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    pickup_address = db.Column(db.String(300))
    delivery_address = db.Column(db.String(300))
    pickup_lat = db.Column(db.Float)
    pickup_lon = db.Column(db.Float)
    delivery_lat = db.Column(db.Float)
    delivery_lon = db.Column(db.Float)
    driver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    company_id = db.Column(db.Integer, db.ForeignKey('delivery_companies.id'), nullable=True)
    requires_cold_chain = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(30), default='pending')
    # pending, assigned, picked_up, en_route, delivered, failed, cancelled
    fee_ugx = db.Column(db.Float, default=0.0)
    distance_km = db.Column(db.Float)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=True)
    driver_notes = db.Column(db.Text)
    estimated_minutes= db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = db.relationship('User', foreign_keys=[patient_id])
    driver = db.relationship('User', foreign_keys=[driver_id])
    pharmacy = db.relationship('Facility', foreign_keys=[pharmacy_id])
    destination = db.relationship('Facility', foreign_keys=[destination_facility_id])
    payment = db.relationship('Payment', foreign_keys=[payment_id])
    company = db.relationship('DeliveryCompany', foreign_keys=[company_id])


# ─── WALLET ──────────────────────────────────────────────────────────────────

class WalletTransaction(db.Model):
    __tablename__ = 'wallet_transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    tx_type = db.Column(db.String(30))
    # topup, deduct, refund, escrow_hold, escrow_release, payout
    amount_ugx = db.Column(db.Float, nullable=False)
    balance_after = db.Column(db.Float, nullable=False)
    reference = db.Column(db.String(60))
    mobile_number = db.Column(db.String(20))
    network = db.Column(db.String(20))
    note = db.Column(db.String(300))
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
    payment = db.relationship('Payment', foreign_keys=[payment_id])


# ─── MESSAGING ───────────────────────────────────────────────────────────────

class Message(db.Model):
    """In-platform secure messaging between any two users."""
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject = db.Column(db.String(200))
    body = db.Column(db.Text, nullable=False)
    msg_type = db.Column(db.String(30), default='general')
    # general, consultation, referral, supplier_enquiry, prescription_query
    related_appointment_id = db.Column(db.Integer, db.ForeignKey('appointments.id'), nullable=True)
    related_order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    recipient = db.relationship('User', foreign_keys=[recipient_id], backref='received_messages')


# ─── NOTIFICATIONS ───────────────────────────────────────────────────────────

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    recipient_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    recipient_facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    notif_type = db.Column(db.String(40))
    # appointment, consultation_complete, stock_alert, payment, delivery, message, referral
    related_alert_id = db.Column(db.Integer, db.ForeignKey('alerts.id'), nullable=True)
    related_order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True)
    related_appointment_id = db.Column(db.Integer, db.ForeignKey('appointments.id'), nullable=True)
    related_payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=True)
    related_message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    recipient_user = db.relationship('User', foreign_keys=[recipient_user_id])
    recipient_facility = db.relationship('Facility', foreign_keys=[recipient_facility_id])


# ─── SEARCH INTELLIGENCE ─────────────────────────────────────────────────────

class SearchLog(db.Model):
    __tablename__ = 'search_logs'
    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.String(300))
    search_type = db.Column(db.String(20))
    user_lat = db.Column(db.Float)
    user_lon = db.Column(db.Float)
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=True)
    results_found = db.Column(db.Integer)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SearchGap(db.Model):
    __tablename__ = 'search_gaps'
    id = db.Column(db.Integer, primary_key=True)
    search_query = db.Column(db.String(300), nullable=False)
    search_type = db.Column(db.String(20))
    count = db.Column(db.Integer, default=1)
    user_lat = db.Column(db.Float)
    user_lon = db.Column(db.Float)
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=True)
    district_notified = db.Column(db.Boolean, default=False)
    last_searched = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    district = db.relationship('District', foreign_keys=[district_id])


# ─── MISC ────────────────────────────────────────────────────────────────────

class SMSLog(db.Model):
    __tablename__ = 'sms_logs'
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(20))
    message = db.Column(db.Text)
    direction = db.Column(db.String(10), default='outbound') # inbound, outbound
    status = db.Column(db.String(20)) # sent, delivered, failed
    alert_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class RestockSuggestion(db.Model):
    __tablename__ = 'restock_suggestions'
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=False)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False)
    suggested_supplier_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    suggested_qty = db.Column(db.Integer)
    suggested_price_ugx = db.Column(db.Float)
    reason = db.Column(db.String(200))
    status = db.Column(db.String(20), default='pending')
    # pending, ordered, dismissed
    alert_id = db.Column(db.Integer, db.ForeignKey('alerts.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    facility = db.relationship('Facility', foreign_keys=[facility_id])
    medicine = db.relationship('Medicine', foreign_keys=[medicine_id])
    supplier = db.relationship('Facility', foreign_keys=[suggested_supplier_id])


# ─── MEDICINE VERIFICATION ───────────────────────────────────────────────────

class MedicineVerification(db.Model):
    """Batch-number / QR verification log — tracks every check made."""
    __tablename__ = 'medicine_verifications'
    id = db.Column(db.Integer, primary_key=True)
    batch_number = db.Column(db.String(100), nullable=False)
    nda_code = db.Column(db.String(60))
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=True)
    result = db.Column(db.String(20)) # verified, not_found, expired, recalled
    checked_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    user_lat = db.Column(db.Float)
    user_lon = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    medicine = db.relationship('Medicine', foreign_keys=[medicine_id])
    checker = db.relationship('User', foreign_keys=[checked_by])
    facility = db.relationship('Facility', foreign_keys=[facility_id])


class MedicineBatch(db.Model):
    """Authoritative batch registry — populated from NDA data / supplier manifests."""
    __tablename__ = 'medicine_batches'
    id = db.Column(db.Integer, primary_key=True)
    batch_number = db.Column(db.String(100), nullable=False, unique=True, index=True)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False)
    manufacturer = db.Column(db.String(200))
    manufacture_date= db.Column(db.Date, nullable=True)
    expiry_date = db.Column(db.Date, nullable=True)
    country_of_origin = db.Column(db.String(100))
    nda_approval_no = db.Column(db.String(60))
    status = db.Column(db.String(20), default='active')
    # active | expired | recalled | quarantine
    recall_reason = db.Column(db.Text)
    registered_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    medicine = db.relationship('Medicine', foreign_keys=[medicine_id])


# ─── MATERNAL HEALTH ─────────────────────────────────────────────────────────

class MaternalProfile(db.Model):
    """Pregnancy and postnatal tracking for a patient."""
    __tablename__ = 'maternal_profiles'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    status = db.Column(db.String(20), default='pregnant')
    # pregnant | postnatal | completed
    lmp_date = db.Column(db.Date, nullable=True) # Last Menstrual Period
    edd = db.Column(db.Date, nullable=True) # Estimated Delivery Date
    delivery_date = db.Column(db.Date, nullable=True)
    gravida = db.Column(db.Integer, default=1) # number of pregnancies
    parity = db.Column(db.Integer, default=0) # number of live births
    hiv_status = db.Column(db.String(20)) # positive | negative | unknown
    diabetes = db.Column(db.Boolean, default=False)
    hypertension = db.Column(db.Boolean, default=False)
    sickle_cell = db.Column(db.Boolean, default=False)
    preferred_language = db.Column(db.String(40), default='English')
    nearest_clinic = db.Column(db.String(200))
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = db.relationship('User', foreign_keys=[patient_id], backref='maternal_profile')
    facility = db.relationship('Facility', foreign_keys=[facility_id])
    anc_visits = db.relationship('ANCVisit', backref='profile', cascade='all,delete-orphan')


class ANCVisit(db.Model):
    """Antenatal care (ANC) visit schedule and completion record."""
    __tablename__ = 'anc_visits'
    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey('maternal_profiles.id'), nullable=False)
    visit_number = db.Column(db.Integer) # 1, 2, 3, 4 (WHO recommends 8+ but Uganda uses 4 as minimum)
    visit_label = db.Column(db.String(60)) # e.g. "First ANC Visit (≤12 weeks)"
    due_date = db.Column(db.Date, nullable=False)
    completed_date = db.Column(db.Date, nullable=True)
    completed = db.Column(db.Boolean, default=False)
    reminder_sent = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointments.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ─── MENTAL HEALTH ───────────────────────────────────────────────────────────

class MentalHealthSession(db.Model):
    """Anonymous mental health support chat session."""
    __tablename__ = 'mental_health_sessions'
    id = db.Column(db.Integer, primary_key=True)
    session_token = db.Column(db.String(64), unique=True, nullable=False,
                              default=lambda: uuid.uuid4().hex)
    # Deliberately not requiring user_id — anonymous sessions allowed
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # PHQ-9 score fields (0–27)
    phq9_score = db.Column(db.Integer, nullable=True)
    phq9_answers = db.Column(db.Text) # JSON array of 9 answers (0-3 each)
    phq9_severity = db.Column(db.String(20)) # minimal, mild, moderate, moderately_severe, severe
    # GAD-7 score fields (0–21)
    gad7_score = db.Column(db.Integer, nullable=True)
    gad7_answers = db.Column(db.Text)
    gad7_severity = db.Column(db.String(20)) # minimal, mild, moderate, severe
    # Crisis flag
    crisis_flagged = db.Column(db.Boolean, default=False)
    # Chat
    chat_history = db.Column(db.Text) # JSON array of {role, content, ts}
    status = db.Column(db.String(20), default='active') # active | closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])


# ─── BLOOD BANK ──────────────────────────────────────────────────────────────

class BloodBank(db.Model):
    """Blood availability at a facility — updated by lab staff."""
    __tablename__ = 'blood_banks'
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=False)
    blood_type = db.Column(db.String(5), nullable=False) # A+, A-, B+, B-, AB+, AB-, O+, O-
    units_available = db.Column(db.Integer, default=0)
    is_urgent = db.Column(db.Boolean, default=False) # critically low flag
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    facility = db.relationship('Facility', foreign_keys=[facility_id], backref='blood_bank')
    updater = db.relationship('User', foreign_keys=[updated_by])


class BloodDonor(db.Model):
    """Registered blood donors — notified when their type is urgently needed."""
    __tablename__ = 'blood_donors'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    blood_type = db.Column(db.String(5), nullable=False)
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=True)
    last_donated = db.Column(db.Date, nullable=True)
    total_donations = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    preferred_language = db.Column(db.String(40), default='English')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
    district = db.relationship('District', foreign_keys=[district_id])


class BloodRequest(db.Model):
    """Urgent blood request from a patient or doctor."""
    __tablename__ = 'blood_requests'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    blood_type = db.Column(db.String(5), nullable=False)
    units_needed = db.Column(db.Integer, default=1)
    urgency = db.Column(db.String(20), default='urgent') # routine | urgent | emergency
    reason = db.Column(db.String(200))
    status = db.Column(db.String(20), default='open') # open | fulfilled | cancelled
    sms_sent_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    fulfilled_at = db.Column(db.DateTime, nullable=True)

    patient = db.relationship('User', foreign_keys=[patient_id])
    requester = db.relationship('User', foreign_keys=[requester_id])
    facility = db.relationship('Facility', foreign_keys=[facility_id])


# ─── VACCINATION TRACKER ──────────────────────────────────────────────────────

class ChildProfile(db.Model):
    """Child registered for EPI vaccination tracking."""
    __tablename__ = 'child_profiles'
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(10))
    birth_weight_kg = db.Column(db.Float, nullable=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    preferred_language = db.Column(db.String(40), default='English')
    nin = db.Column(db.String(20)) # National ID if registered
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    parent = db.relationship('User', foreign_keys=[parent_id], backref='children')
    facility = db.relationship('Facility', foreign_keys=[facility_id])
    vaccines = db.relationship('VaccineSchedule', backref='child', cascade='all,delete-orphan')


class VaccineSchedule(db.Model):
    """Individual vaccine dose scheduled for a child."""
    __tablename__ = 'vaccine_schedules'
    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey('child_profiles.id'), nullable=False)
    vaccine_name = db.Column(db.String(80), nullable=False)
    dose_number = db.Column(db.Integer, default=1)
    due_date = db.Column(db.Date, nullable=False)
    given_date = db.Column(db.Date, nullable=True)
    given = db.Column(db.Boolean, default=False)
    given_at_facility = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    batch_number = db.Column(db.String(60))
    reminder_sent = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ─── HIV / ART MANAGEMENT ────────────────────────────────────────────────────

class HIVProfile(db.Model):
    """HIV care profile — fully private, separate from general health record."""
    __tablename__ = 'hiv_profiles'
    id = db.Column(db.Integer, primary_key=True)
    # Deliberately nullable — anonymous registration allowed
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    art_number = db.Column(db.String(40)) # facility ART registration number
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    art_start_date = db.Column(db.Date, nullable=True)
    current_regimen = db.Column(db.String(120)) # e.g. TDF/3TC/DTG
    viral_load = db.Column(db.Float, nullable=True) # copies/mL
    viral_load_date = db.Column(db.Date, nullable=True)
    cd4_count = db.Column(db.Integer, nullable=True)
    cd4_date = db.Column(db.Date, nullable=True)
    on_tb_treatment = db.Column(db.Boolean, default=False)
    pregnant = db.Column(db.Boolean, default=False)
    preferred_language = db.Column(db.String(40), default='English')
    phone = db.Column(db.String(20)) # may differ from account phone for privacy
    status = db.Column(db.String(20), default='active') # active | transferred | lost
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
    facility = db.relationship('Facility', foreign_keys=[facility_id])
    refills = db.relationship('ARTRefill', backref='profile', cascade='all,delete-orphan')


class ARTRefill(db.Model):
    """ART drug refill appointment — the core retention-in-care challenge."""
    __tablename__ = 'art_refills'
    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey('hiv_profiles.id'), nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    collected_date = db.Column(db.Date, nullable=True)
    collected = db.Column(db.Boolean, default=False)
    days_supply = db.Column(db.Integer, default=30) # 30 or 90 day supply
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    reminder_sent = db.Column(db.Boolean, default=False)
    missed = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
