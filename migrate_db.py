"""
MedLink Database Migration — run this once on any existing database.
Safe to run multiple times. Does not delete any data.
"""
import sqlite3, os, sys

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'medlink.db')

def col(cur, table): 
    cur.execute(f"PRAGMA table_info({table})")
    return {r[1] for r in cur.fetchall()}

def tbl(cur, table):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None

def add(cur, conn, table, column, typedef, default=None):
    if not tbl(cur, table): return
    if column in col(cur, table): return
    sql = f"ALTER TABLE {table} ADD COLUMN {column} {typedef}"
    if default is not None: sql += f" DEFAULT {default}"
    cur.execute(sql); conn.commit()
    print(f" + {table}.{column}")

def create(cur, conn, table, ddl):
    if tbl(cur, table): return
    cur.execute(ddl); conn.commit()
    print(f" + table: {table}")

if not os.path.exists(DB_PATH):
    print("No existing database found — db.create_all() will handle it.")
    sys.exit(0)

print(f"Migrating: {DB_PATH}")
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# ── users ──────────────────────────────────────────────────────────────────
for c, t, d in [
    ('umdpc_number','VARCHAR(80)',None),
    ('specialisation','VARCHAR(100)',None),
    ('languages','VARCHAR(200)',None),
    ('consultation_fee_ugx','FLOAT',0),
    ('verified_doctor','BOOLEAN',0),
    ('bio','TEXT',None),
    ('available_for_remote','BOOLEAN',1),
    ('vehicle_type','VARCHAR(50)',None),
    ('plate_number','VARCHAR(30)',None),
    ('has_cold_box','BOOLEAN',0),
    ('verified_driver','BOOLEAN',0),
    ('is_available','BOOLEAN',1),
    ('delivery_company_id','INTEGER',None),
    ('wallet_balance_ugx','FLOAT',0),
    ('national_id','VARCHAR(30)',None),
    ('date_of_birth','DATE',None),
    ('gender','VARCHAR(10)',None),
    ('district_id','INTEGER',None),
    ('address','VARCHAR(255)',None),
    ('blood_type','VARCHAR(5)',None),
    ('known_allergies','TEXT',None),
    ('chronic_conditions','TEXT',None),
    ('emergency_contact_name','VARCHAR(100)',None),
    ('emergency_contact_phone','VARCHAR(30)',None),
    ('insurance_number','VARCHAR(60)',None),
    ('insurance_provider','VARCHAR(100)',None),
]:
    add(cur, conn, 'users', c, t, d)

# ── facilities ─────────────────────────────────────────────────────────────
for c, t, d in [
    ('is_supplier','BOOLEAN',0),
    ('supplier_type','VARCHAR(50)',None),
    ('min_order_ugx','FLOAT',0),
    ('lead_time_days','INTEGER',7),
    ('is_insurance','BOOLEAN',0),
    ('subscription_tier','VARCHAR(20)','\'free\''),
    ('subscription_until','DATETIME',None),
    ('lat','FLOAT',None),
    ('lon','FLOAT',None),
]:
    add(cur, conn, 'facilities', c, t, d)

# ── districts ──────────────────────────────────────────────────────────────
for c, t, d in [('lat','FLOAT',None),('lon','FLOAT',None)]:
    add(cur, conn, 'districts', c, t, d)

# ── medicines ──────────────────────────────────────────────────────────────
for c, t, d in [
    ('requires_cold_chain','BOOLEAN',0),
    ('controlled_drug','BOOLEAN',0),
    ('nda_code','VARCHAR(30)',None),
    ('who_essential','BOOLEAN',0),
]:
    add(cur, conn, 'medicines', c, t, d)

# ── stock_items ────────────────────────────────────────────────────────────
for c, t, d in [
    ('sell_price','FLOAT',0),
    ('reorder_quantity','INTEGER',100),
    ('supplier_id','INTEGER',None),
]:
    add(cur, conn, 'stock_items', c, t, d)

# ── stock_transactions ─────────────────────────────────────────────────────
for c, t, d in [
    ('unit_price','FLOAT',0),
    ('batch_no','VARCHAR(60)',None),
    ('reference','VARCHAR(60)',None),
    ('dispensed_to','VARCHAR(120)',None),
    ('patient_ref','VARCHAR(60)',None),
]:
    add(cur, conn, 'stock_transactions', c, t, d)

# ── orders ─────────────────────────────────────────────────────────────────
for c, t, d in [
    ('actual_delivery','DATE',None),
    ('payment_method','VARCHAR(30)',None),
    ('payment_status','VARCHAR(20)','\'unpaid\''),
    ('payment_ref','VARCHAR(60)',None),
    ('confirmed_by','INTEGER',None),
]:
    add(cur, conn, 'orders', c, t, d)

# ── order_items ────────────────────────────────────────────────────────────
add(cur, conn, 'order_items', 'received_qty', 'INTEGER', 0)

# ── payments ───────────────────────────────────────────────────────────────
for c, t, d in [
    ('payer_facility_id','INTEGER',None),
    ('payee_facility_id','INTEGER',None),
    ('mobile_number','VARCHAR(20)',None),
    ('network','VARCHAR(20)',None),
    ('auto_release_at','DATETIME',None),
]:
    add(cur, conn, 'payments', c, t, d)

# ── appointments ───────────────────────────────────────────────────────────
for c, t, d in [
    ('department','VARCHAR(100)',None),
    ('duration_minutes','INTEGER',30),
    ('priority','VARCHAR(20)','\'normal\''),
    ('chief_complaint','TEXT',None),
    ('video_room_url','VARCHAR(255)',None),
    ('triage_id','INTEGER',None),
    ('referred_by','INTEGER',None),
]:
    add(cur, conn, 'appointments', c, t, d)

# ── consultations ──────────────────────────────────────────────────────────
for c, t, d in [
    ('presenting_complaints','TEXT',None),
    ('history_of_illness','TEXT',None),
    ('examination_findings','TEXT',None),
    ('investigations','TEXT',None),
    ('icd10_code','VARCHAR(20)',None),
    ('management_plan','TEXT',None),
    ('follow_up_date','DATE',None),
    ('follow_up_notes','TEXT',None),
    ('referral_needed','BOOLEAN',0),
    ('referred_to_facility','INTEGER',None),
    ('referral_reason','TEXT',None),
]:
    add(cur, conn, 'consultations', c, t, d)

# ── prescriptions ──────────────────────────────────────────────────────────
for c, t, d in [
    ('route','VARCHAR(50)',None),
    ('instructions','VARCHAR(300)',None),
    ('quantity_to_dispense','INTEGER',None),
    ('dispensed','BOOLEAN',0),
    ('dispensed_by','INTEGER',None),
    ('dispensed_at','DATETIME',None),
]:
    add(cur, conn, 'prescriptions', c, t, d)

# ── triage_assessments ─────────────────────────────────────────────────────
for c, t, d in [
    ('patient_age','INTEGER',None),
    ('patient_gender','VARCHAR(10)',None),
    ('suggested_facility_type','VARCHAR(50)',None),
]:
    add(cur, conn, 'triage_assessments', c, t, d)

# ── notifications ──────────────────────────────────────────────────────────
for c, t, d in [
    ('recipient_user_id','INTEGER',None),
    ('notif_type','VARCHAR(40)',None),
    ('related_appointment_id','INTEGER',None),
    ('related_payment_id','INTEGER',None),
    ('related_message_id','INTEGER',None),
]:
    add(cur, conn, 'notifications', c, t, d)

# ── delivery_companies ─────────────────────────────────────────────────────
add(cur, conn, 'delivery_companies', 'coverage_districts', 'TEXT', None)

# ── delivery_orders ────────────────────────────────────────────────────────
for c, t, d in [
    ('distance_km','FLOAT',None),
    ('driver_notes','TEXT',None),
]:
    add(cur, conn, 'delivery_orders', c, t, d)

# ── search_logs ────────────────────────────────────────────────────────────
for c, t, d in [
    ('district_id','INTEGER',None),
    ('user_id','INTEGER',None),
]:
    add(cur, conn, 'search_logs', c, t, d)

# ── search_gaps ────────────────────────────────────────────────────────────
add(cur, conn, 'search_gaps', 'district_id', 'INTEGER', None)

# ── sms_logs ───────────────────────────────────────────────────────────────
for c, t, d in [
    ('direction','VARCHAR(10)','\'outbound\''),
    ('status','VARCHAR(20)',None),
]:
    add(cur, conn, 'sms_logs', c, t, d)

# ── wallet_transactions ────────────────────────────────────────────────────
for c, t, d in [
    ('mobile_number','VARCHAR(20)',None),
    ('network','VARCHAR(20)',None),
]:
    add(cur, conn, 'wallet_transactions', c, t, d)

# ── NEW TABLES ─────────────────────────────────────────────────────────────
create(cur, conn, 'supplier_catalogue', """
CREATE TABLE supplier_catalogue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES facilities(id),
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_price_ugx FLOAT NOT NULL,
    min_order_qty INTEGER DEFAULT 1,
    lead_time_days INTEGER DEFAULT 7,
    in_stock BOOLEAN DEFAULT 1,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
)""")

create(cur, conn, 'messages', """
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL REFERENCES users(id),
    recipient_id INTEGER NOT NULL REFERENCES users(id),
    subject VARCHAR(200),
    body TEXT NOT NULL,
    msg_type VARCHAR(30) DEFAULT 'general',
    related_appointment_id INTEGER REFERENCES appointments(id),
    related_order_id INTEGER REFERENCES orders(id),
    is_read BOOLEAN DEFAULT 0,
    read_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)""")

create(cur, conn, 'doctor_districts', """
CREATE TABLE doctor_districts (
    user_id INTEGER NOT NULL REFERENCES users(id),
    district_id INTEGER NOT NULL REFERENCES districts(id),
    PRIMARY KEY (user_id, district_id)
)""")

# ── extra columns missed in earlier migrations
add(cur, conn, 'alerts', 'auto_reorder', 'BOOLEAN', 0)
add(cur, conn, 'restock_suggestions', 'suggested_price_ugx', 'FLOAT', None)

# ── cold chain flag on existing medicines ──────────────────────────────────
for kw in ['BCG','Measles','OPV','Pentavalent','Rotavirus','HPV',
           'Oxytocin','Insulin','Artesunate Inj','Vaccine']:
    cur.execute("UPDATE medicines SET requires_cold_chain=1 WHERE name LIKE ?", (f'%{kw}%',))
conn.commit()

# ── mark distributor facilities as suppliers ───────────────────────────────
cur.execute("UPDATE facilities SET is_supplier=1 WHERE facility_type='distributor'")
cur.execute("UPDATE facilities SET is_supplier=1 WHERE facility_type='manufacturer'")
conn.commit()

conn.close()
print("\nMigration complete.")
