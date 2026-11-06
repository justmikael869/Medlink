"""
MedLink Uganda — Database Seed Script (PostgreSQL / any SQLAlchemy DB)
Creates tables if missing, then seeds demo data. Safe to re-run.

Usage:  python seed.py   (with DATABASE_URL set in your environment or .env)
"""
import os, sys

from app import create_app, db
app = create_app()

with app.app_context():
    db.create_all() # creates any tables that don't exist yet

    from app.models import (District, Facility, User, Medicine, StockItem,
                             StockTransaction, Alert, WalletTransaction)
    from datetime import datetime, date, timedelta
    import random

    # ── Districts ────────────────────────────────────────────────────────────
    if District.query.count() == 0:
        district_names = [
            'Kampala','Wakiso','Mukono','Jinja','Mbale','Gulu','Lira',
            'Mbarara','Masaka','Arua','Fort Portal','Soroti','Tororo',
            'Kabale','Hoima','Moroto','Adjumani','Apac','Bundibugyo','Iganga',
        ]
        for dn in district_names:
            db.session.add(District(name=dn, region='Central' if dn in
                ['Kampala','Wakiso','Mukono'] else 'Regional'))
        db.session.commit()
        print(f' {len(district_names)} districts')

    # ── Medicines ────────────────────────────────────────────────────────────
    if Medicine.query.count() == 0:
        meds = [
            # (name, generic, category, form, strength, unit, diseases, critical, rx_required, cold_chain)
            ('Coartem','Artemether/Lumefantrine','Antimalarial','Tablet','20/120mg','Tablet','Malaria',True,True,False),
            ('Quinine Sulfate','Quinine','Antimalarial','Tablet','300mg','Tablet','Malaria,Severe Malaria',True,True,False),
            ('Artesunate Injection','Artesunate','Antimalarial','Injection','60mg','Vial','Severe Malaria',True,True,True),
            ('Paracetamol','Paracetamol','Analgesic','Tablet','500mg','Tablet','Fever,Pain,Headache',False,False,False),
            ('Ibuprofen','Ibuprofen','Analgesic','Tablet','400mg','Tablet','Pain,Fever,Inflammation',False,False,False),
            ('Amoxicillin','Amoxicillin','Antibiotic','Capsule','500mg','Capsule','Bacterial Infections,Pneumonia',False,True,False),
            ('Cotrimoxazole','Sulfamethoxazole/Trimethoprim','Antibiotic','Tablet','480mg','Tablet','HIV/AIDS,UTI,Pneumonia',True,True,False),
            ('Ciprofloxacin','Ciprofloxacin','Antibiotic','Tablet','500mg','Tablet','Typhoid,UTI,Diarrhoea',False,True,False),
            ('Metronidazole','Metronidazole','Antibiotic','Tablet','400mg','Tablet','Amoebic Dysentery,Giardia',False,True,False),
            ('ORS Sachets','Oral Rehydration Salts','Electrolyte','Sachet','WHO formula','Sachet','Diarrhoea,Dehydration',True,False,False),
            ('Zinc Sulphate','Zinc Sulphate','Supplement','Tablet','20mg','Tablet','Diarrhoea,Malnutrition',False,False,False),
            ('Vitamin A','Retinol','Vitamin','Capsule','200000IU','Capsule','Malnutrition,Night Blindness',False,False,False),
            ('Iron & Folic Acid','Ferrous Sulphate/Folic Acid','Supplement','Tablet','200/0.4mg','Tablet','Anaemia,Pregnancy',False,False,False),
            ('Mebendazole','Mebendazole','Antiparasitic','Tablet','500mg','Tablet','Worm Infections',False,False,False),
            ('Fluconazole','Fluconazole','Antifungal','Capsule','150mg','Capsule','Fungal Infections,HIV/AIDS',False,True,False),
            ('Nevirapine','Nevirapine','ARV','Tablet','200mg','Tablet','HIV/AIDS',True,True,False),
            ('Efavirenz','Efavirenz','ARV','Tablet','600mg','Tablet','HIV/AIDS',True,True,False),
            ('Tenofovir/Lamivudine/Dolutegravir','TLD','ARV','Tablet','300/300/50mg','Tablet','HIV/AIDS',True,True,False),
            ('Isoniazid','Isoniazid','Anti-TB','Tablet','300mg','Tablet','Tuberculosis',True,True,False),
            ('Rifampicin','Rifampicin','Anti-TB','Capsule','450mg','Capsule','Tuberculosis',True,True,False),
            ('Metformin','Metformin','Antidiabetic','Tablet','500mg','Tablet','Diabetes',False,True,False),
            ('Glibenclamide','Glibenclamide','Antidiabetic','Tablet','5mg','Tablet','Diabetes',False,True,False),
            ('Insulin Regular','Insulin','Antidiabetic','Injection','100IU/ml','Vial','Diabetes',True,True,True),
            ('Amlodipine','Amlodipine','Antihypertensive','Tablet','5mg','Tablet','Hypertension',False,True,False),
            ('Enalapril','Enalapril','Antihypertensive','Tablet','10mg','Tablet','Hypertension,Heart Failure',False,True,False),
            ('Hydralazine','Hydralazine','Antihypertensive','Tablet','25mg','Tablet','Hypertension,Pre-eclampsia',True,True,False),
            ('Magnesium Sulphate','Magnesium Sulphate','Obstetric','Injection','50%','Ampoule','Pre-eclampsia,Eclampsia',True,True,False),
            ('Oxytocin','Oxytocin','Oxytocic','Injection','10IU/ml','Ampoule','Postpartum Haemorrhage,Labour',True,True,True),
            ('BCG Vaccine','BCG','Vaccine','Injection','0.05ml dose','Vial','Tuberculosis prevention',True,True,True),
            ('Measles Vaccine','Measles','Vaccine','Injection','0.5ml dose','Vial','Measles prevention',True,True,True),
            ('OPV','Oral Polio Vaccine','Vaccine','Oral','2 drops','Dose','Poliomyelitis prevention',True,True,True),
            ('Pentavalent Vaccine','DPT-HepB-Hib','Vaccine','Injection','0.5ml','Vial','DPT prevention',True,True,True),
            ('Rotavirus Vaccine','Rotavirus','Vaccine','Oral','1.5ml','Dose','Rotavirus Diarrhoea prevention',True,True,True),
            ('HPV Vaccine','HPV','Vaccine','Injection','0.5ml','Vial','Cervical Cancer prevention',True,True,True),
            ('Diazepam','Diazepam','Anticonvulsant','Injection','5mg/ml','Ampoule','Epilepsy,Seizures',True,True,False),
            ('Phenobarbital','Phenobarbital','Anticonvulsant','Tablet','30mg','Tablet','Epilepsy',False,True,False),
            ('Salbutamol Inhaler','Salbutamol','Bronchodilator','Inhaler','100mcg/dose','Inhaler','Asthma',False,True,False),
            ('Prednisolone','Prednisolone','Corticosteroid','Tablet','5mg','Tablet','Asthma,Inflammation,HIV/AIDS',False,True,False),
            ('Gentian Violet','Gentian Violet','Antiseptic','Solution','0.5%','Bottle','Oral Thrush,Skin Infections',False,False,False),
            ('Chlorhexidine Cord Care','Chlorhexidine','Antiseptic','Gel','7.1%','Tube','Newborn cord care',False,False,False),
        ]
        for m in meds:
            db.session.add(Medicine(
                name=m[0], generic_name=m[1], category=m[2],
                dosage_form=m[3], strength=m[4], unit=m[5],
                diseases=m[6], critical=m[7], prescription_required=m[8],
                requires_cold_chain=m[9],
            ))
        db.session.commit()
        print(f' {len(meds)} medicines ({sum(1 for m in meds if m[9])} cold-chain)')

    # ── Facilities ───────────────────────────────────────────────────────────
    if Facility.query.count() == 0:
        kampala = District.query.filter_by(name='Kampala').first()
        wakiso = District.query.filter_by(name='Wakiso').first()
        gulu = District.query.filter_by(name='Gulu').first()
        mbarara = District.query.filter_by(name='Mbarara').first()
        jinja = District.query.filter_by(name='Jinja').first()

        facilities_data = [
            ('Mulago National Referral Hospital','government_clinic','National',kampala,0.3476,32.5765,'+256414541884','info@mulago.go.ug'),
            ('Kampala Capital City Authority Clinic','government_clinic','HC IV',kampala,0.3136,32.5811,'+256414343940',None),
            ('Nsambya Hospital','private_clinic','Private Hospital',kampala,0.3025,32.5892,'+256414268333','info@nsambya.org'),
            ('Mengo Hospital','private_clinic','Private Hospital',kampala,0.3167,32.5578,'+256414270222','info@mengo.go.ug'),
            ('Kiswa Health Centre III','government_clinic','HC III',kampala,0.3367,32.6011,'+256700111001',None),
            ('MedPharm Pharmacy Kampala','pharmacy','Pharmacy',kampala,0.3185,32.5884,'+256700222001','medpharm@pharmacy.ug'),
            ('CarePoint Pharmacy','pharmacy','Pharmacy',wakiso,0.3601,32.6201,'+256700222002',None),
            ('Quality Chemicals Distributor','distributor','National',kampala,0.3089,32.5634,'+256414320000','info@qcl.ug'),
            ('Entebbe Hospital','government_clinic','HC IV',wakiso,0.0600,32.4600,'+256414320155',None),
            ('Victoria Pharmacy Entebbe','pharmacy','Pharmacy',wakiso,0.0649,32.4623,'+256700333001',None),
            ('Gulu Regional Referral Hospital','government_clinic','Regional',gulu,2.7747,32.2990,'+256471432054',None),
            ('Gulu Central Pharmacy','pharmacy','Pharmacy',gulu,2.7766,32.3052,'+256700444001',None),
            ('Mbarara Regional Referral Hospital','government_clinic','Regional',mbarara,-0.6075,30.6596,'+256485421301',None),
            ('Mbarara Pharmacy Plus','pharmacy','Pharmacy',mbarara,-0.6095,30.6601,'+256700555001',None),
            ('Jinja Regional Hospital','government_clinic','Regional',jinja,0.4244,33.2041,'+256434122201',None),
            ('Jinja Pharmacy','pharmacy','Pharmacy',jinja,0.4251,33.2055,'+256700666001',None),
            ('Rubaga Hospital','private_clinic','Private Hospital',kampala,0.3203,32.5511,'+256414272516','info@rubaga.go.ug'),
            ('HealthPlus Drug Shop Ntinda','drug_shop','Drug Shop',kampala,0.3478,32.6156,'+256700777001',None),
            ('Wandegeya HC II','government_clinic','HC II',kampala,0.3401,32.5678,'+256700888001',None),
            ('UVRI Research Institute','ngo_clinic','Research',kampala,0.3156,32.5890,'+256414320088','info@uvri.go.ug'),
            ('St. Mary\'s Hospital Lacor','ngo_clinic','Mission Hospital',gulu,2.7512,32.2845,'+256471432201','info@lacor.org'),
            ('Clarke International University Clinic','private_clinic','University',kampala,0.3267,32.5712,'+256700999001',None),
        ]
        for f in facilities_data:
            db.session.add(Facility(
                name=f[0], facility_type=f[1], level=f[2],
                district=f[3], latitude=f[4], longitude=f[5],
                phone=f[6], email=f[7], verified=True, active=True,
            ))
        db.session.commit()
        print(f' {len(facilities_data)} facilities')

    # ── Users ────────────────────────────────────────────────────────────────
    if User.query.count() == 0:
        mulago = Facility.query.filter(Facility.name.ilike('%Mulago%')).first()
        medpharm= Facility.query.filter(Facility.name.ilike('%MedPharm%')).first()
        gulu_h = Facility.query.filter(Facility.name.ilike('%Gulu Regional%')).first()

        users_data = [
            ('System Admin','admin@medlink.ug','admin123','system_admin',None,'+256700000001'),
            ('District Officer Kampala','district@medlink.ug','admin123','district_officer',None,'+256700000002'),
            ('Dr. John Mukasa','doctor@medlink.ug','admin123','facility_admin',mulago,'+256700000003'),
            ('Nurse Agnes','nurse@medlink.ug','admin123','staff',mulago,'+256700000004'),
            ('Pharm Joseph','pharm@medlink.ug','admin123','facility_admin',medpharm,'+256700000005'),
            ('Patient Demo','patient@medlink.ug','medlink123','patient',None,'+256700000006'),
        ]
        for name,email,pw,role,fac,phone in users_data:
            u = User(name=name, email=email, role=role,
                     facility=fac, phone=phone,
                     wallet_balance_ugx=100000.0 if role=='patient' else 0.0)
            u.set_password(pw)
            db.session.add(u)
        db.session.commit()
        print(f' {len(users_data)} base users')

    # ── Stock items ──────────────────────────────────────────────────────────
    if StockItem.query.count() == 0:
        medicines = Medicine.query.all()
        facilities = Facility.query.all()
        admin_user = User.query.filter_by(email='admin@medlink.ug').first()
        today = date.today()
        count = 0
        for fac in facilities:
            meds_sample = random.sample(medicines, min(len(medicines), random.randint(12,28)))
            for med in meds_sample:
                qty = random.randint(0, 500)
                si = StockItem(
                    facility=fac, medicine=med,
                    quantity=qty,
                    unit_price=round(random.uniform(500, 25000), -2),
                    minimum_threshold=random.randint(10, 50),
                    expiry_date=today + timedelta(days=random.randint(30, 730)),
                    batch_no=f'BN{random.randint(1000,9999)}',
                    is_available=True, updated_by=admin_user.id if admin_user else None,
                )
                db.session.add(si)
                count += 1
                if qty == 0 and fac and med.critical:
                    db.session.flush()
                    alert = Alert(
                        facility_id=fac.id, medicine_id=med.id,
                        raised_by=admin_user.id if admin_user else 1,
                        severity='critical' if med.critical else 'medium',
                        status='open', quantity_needed=random.randint(50,200),
                        note='Auto-generated: stock at zero', source='auto',
                    )
                    db.session.add(alert)
        db.session.commit()
        print(f' {count} stock items created')

    # ── Demo doctors ─────────────────────────────────────────────────────────
    if User.query.filter_by(role='doctor').count() == 0:
        doctors_data = [
            ('Dr Sarah Nakato','sarah@medlink.ug','+256701111001',
             'General Practice','UMDPC/2019/00041',30000,'English, Luganda',
             'GP with 8 years experience in Kampala. Specialist in malaria, typhoid and HIV management.'),
            ('Dr James Opio','james@medlink.ug','+256701111002',
             'Paediatrics','UMDPC/2020/00078',45000,'English, Acholi, Luo',
             'Paediatrician with 5 years at Gulu Regional Hospital. Expert in childhood malaria and nutrition.'),
            ('Dr Grace Atim','grace@medlink.ug','+256701111003',
             'Obstetrics & Gynaecology','UMDPC/2018/00052',50000,'English, Luganda, Ateso',
             'OB/GYN with extensive experience in maternal health and family planning.'),
            ('Dr Moses Sserwanga','moses@medlink.ug','+256701111004',
             'HIV/AIDS & Infectious Disease','UMDPC/2017/00031',35000,'English, Luganda',
             'Infectious disease specialist focused on HIV/AIDS management and TB treatment.'),
        ]
        for name,email,phone,spec,umdpc,fee,langs,bio in doctors_data:
            if not User.query.filter_by(email=email).first():
                u = User(name=name, email=email, phone=phone,
                         role='doctor', specialisation=spec,
                         umdpc_number=umdpc, consultation_fee_ugx=fee,
                         languages=langs, bio=bio,
                         verified_doctor=True, wallet_balance_ugx=0.0)
                u.set_password('doctor123')
                db.session.add(u)
        db.session.commit()
        print(f' {len(doctors_data)} demo doctors (password: doctor123)')

    # ── Demo drivers ─────────────────────────────────────────────────────────
    if User.query.filter_by(role='driver').count() == 0:
        drivers_data = [
            ('Ali Boda','ali@driver.ug','+256702222001','boda','UAA 231B',False),
            ('Hassan Van','hassan@driver.ug','+256702222002','van','UAB 444K',True),
        ]
        for name,email,phone,vtype,plate,cold in drivers_data:
            if not User.query.filter_by(email=email).first():
                u = User(name=name, email=email, phone=phone, role='driver',
                         vehicle_type=vtype, plate_number=plate,
                         has_cold_box=cold, verified_driver=True,
                         is_available=True, wallet_balance_ugx=0.0)
                u.set_password('driver123')
                db.session.add(u)
        db.session.commit()
        print(f' 2 demo drivers (password: driver123)')

    # ── Patient wallet top-up ────────────────────────────────────────────────
    patient = User.query.filter_by(email='patient@medlink.ug').first()
    if patient and (patient.wallet_balance_ugx or 0) == 0:
        patient.wallet_balance_ugx = 100000.0
        wt = WalletTransaction(
            user_id=patient.id, tx_type='topup',
            amount_ugx=100000, balance_after=100000,
            reference='SEED-TOPUP', note='Seed wallet top-up',
        )
        db.session.add(wt)
        db.session.commit()

    print("""
╔══════════════════════════════════════════════════════╗
║ MedLink Uganda — Ready! ║
╠══════════════════════════════════════════════════════╣
║ Run: flask run or python run.py ║
╠══════════════════════════════════════════════════════╣
║ Login credentials ║
║ ─────────────────────────────────────────────────── ║
║ admin@medlink.ug / admin123 (System Admin) ║
║ district@medlink.ug / admin123 (District Ofc) ║
║ doctor@medlink.ug / admin123 (Facility Admin)║
║ nurse@medlink.ug / admin123 (Staff) ║
║ pharm@medlink.ug / admin123 (Pharmacist) ║
║ patient@medlink.ug / medlink123 (Patient) ║
║ sarah@medlink.ug / doctor123 (Doctor) ║
║ ali@driver.ug / driver123 (Driver) ║
╚══════════════════════════════════════════════════════╝
""")

    # ── Demo delivery company ─────────────────────────────────────────────────
    from app.models import DeliveryCompany
    if DeliveryCompany.query.count() == 0:
        co = DeliveryCompany(
            name='SafeRide Medical Deliveries',
            contact_phone='+256702000001',
            contact_email='dispatch@saferide.ug',
            verified=True, active=True,
        )
        db.session.add(co)
        db.session.flush()

        # Link demo drivers to this company
        for email in ['ali@driver.ug','hassan@driver.ug']:
            drv = User.query.filter_by(email=email).first()
            if drv:
                drv.delivery_company_id = co.id
        db.session.commit()
        print(' Demo delivery company: SafeRide Medical Deliveries (verified)')


# ── Create all demo accounts (distributor, manager, drivers) ─────────────────
print("\nCreating demo accounts...")
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'create_demo_accounts.py')).read())

# ── Seed medicine batches for verification demo ───────────────────────────────
with app.app_context():
    from app.models import MedicineBatch, Medicine
    from datetime import date, timedelta
    import random

    if MedicineBatch.query.count() == 0:
        print('\nSeeding medicine batches for verification demo...')
        meds = Medicine.query.limit(20).all()
        if meds:
            manufacturers = [
                ('Cipla Ltd', 'India'), ('Pfizer Inc', 'USA'),
                ('Kampala Pharmaceutical Industries', 'Uganda'),
                ('GSK', 'UK'), ('Roche', 'Switzerland'),
                ('Aspen Pharmacare', 'South Africa'), ('Strides Shasun', 'India'),
            ]
            today = date.today()
            batches = []
            for i, med in enumerate(meds):
                mfr, country = manufacturers[i % len(manufacturers)]
                batches.append(MedicineBatch(
                    batch_number = f'UG-{2024+i%2}-{mfr[:3].upper()}-{i+1:03d}',
                    medicine_id = med.id,
                    manufacturer = mfr,
                    country_of_origin = country,
                    manufacture_date = today - timedelta(days=random.randint(60, 365)),
                    expiry_date = today + timedelta(days=random.randint(90, 730)),
                    nda_approval_no = f'NDA/2024/MED{i+1:04d}',
                    status = 'active',
                ))
            # One expired batch
            batches.append(MedicineBatch(
                batch_number = 'UG-2022-EXP-001',
                medicine_id = meds[0].id,
                manufacturer = 'Old Pharma Ltd',
                country_of_origin = 'India',
                expiry_date = today - timedelta(days=180),
                nda_approval_no = 'NDA/2022/EXP001',
                status = 'active',
            ))
            # One recalled batch
            if len(meds) > 1:
                batches.append(MedicineBatch(
                    batch_number = 'UG-2023-RCL-001',
                    medicine_id = meds[1].id,
                    manufacturer = 'Recall Pharma',
                    country_of_origin = 'Unknown',
                    expiry_date = today + timedelta(days=200),
                    nda_approval_no = 'NDA/2023/RCL001',
                    status = 'recalled',
                    recall_reason = 'Substandard active ingredient detected by NDA quality lab. Do not use.',
                ))
            for b in batches:
                db.session.add(b)
            db.session.commit()
            print(f' {len(batches)} medicine batches seeded (including 1 expired, 1 recalled)')
            print(' Demo verify: type batch number starting with UG-2024- to get verified result')
            print(' Demo expired: UG-2022-EXP-001')
            print(' Demo recalled: UG-2023-RCL-001')
            print(' Demo not found: type any random string')
