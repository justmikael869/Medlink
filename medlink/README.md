# MedLink Uganda 
### *Connecting Ugandans to medicine, doctors, and health — wherever they are*

> **National Health Innovation Competition Entry**

---

## The Problem

Uganda faces a triple crisis in healthcare access:

- **Medicine deserts** — rural patients travel hours to find a medicine that may be out of stock
- **Counterfeit drugs** — WHO estimates 1 in 10 medicines in sub-Saharan Africa is fake or substandard
- **Doctor shortage** — 1 doctor per 25,000 people; 1 psychiatrist per 1.5 million; maternal mortality at 336 per 100,000 live births
- **No connected system** — pharmacies, clinics, patients, and district health officers operate in silos

MedLink Uganda closes these gaps in one integrated platform.

---

## What MedLink Does

### Medicine Search & Discovery
- Search by medicine name or disease — find the nearest facility with stock
- Real-time inventory across pharmacies, clinics, and hospitals
- **Price comparison** across pharmacies — saves patients from overpaying
- **Live Leaflet map** with GPS — shows distance and price in popups
- Best-price marker highlighted in green

### Medicine Verification *(first in Uganda)*
- Type or scan a batch number — know in 2 seconds if your medicine is genuine
- Results: Verified | ⏰ Expired | Recalled | Not Found
- NDA approval number, manufacturer, expiry date, cold chain flag
- Public API endpoint for pharmacies and USSD integration
- No login required — anyone can verify

### Telemedicine
- Book in-person or remote consultations with verified doctors
- **Video call embedded** via Daily.co — no app needed, works in browser
- **AI symptom checker** powered by Claude — Uganda-aware (malaria, typhoid, TB, sickle cell)
- Prescription PDF download — take to any pharmacy
- **Referral letter PDF** generation — closes the referral loop
- Patient health record — blood type, allergies, chronic conditions visible to doctors

### Maternal Health *(closes Uganda's ANC gap)*
- Register with LMP → EDD calculated → 8-visit ANC schedule auto-generated (WHO 2016)
- Overdue visit alerts on dashboard
- Postnatal schedule (4 PNC visits) after birth
- SMS reminders in **English, Luganda, or Runyankole** — 3 days before each visit
- Risk factor tracking: HIV/PMTCT, diabetes, hypertension, sickle cell
- Danger signs panel + emergency numbers

### Mental Health *(fills Uganda's biggest gap)*
- **Completely anonymous** — no name, no login required
- **PHQ-9 depression screen** — clinically validated, 9 questions, 2 minutes
- **GAD-7 anxiety screen** — 7 questions
- **AI-powered support chat** — Claude Haiku, Uganda-context-aware, crisis keyword detection
- Crisis resources permanent: Befrienders Uganda 0800 212 121
- Pathway to book a psychiatrist directly from results

### USSD Offline Access *(works on any phone)*
- Full medicine search, appointment booking, prescription check via USSD
- Africa's Talking integration
- Works on feature phones with no internet — critical for rural Uganda

### Supply Chain
- Supplier-to-facility medicine ordering
- Delivery tracking with driver assignment
- Escrow payment model with audit trail
- Auto-restock alerts when stock falls below threshold

### Intelligence & Analytics
- Search gap detection — district officer alerted when medicine is searched but not found
- Expiry alerts — facilities warned 30/60/90 days before expiry
- District-level dashboards for health officers
- Cold chain temperature logging

---

## Who Uses MedLink

| Role | What they do |
|------|-------------|
| **Patient** | Search medicine, book doctors, verify medicine, maternal tracker, mental health |
| **Doctor** | Manage appointments, write prescriptions, issue referrals, video consult |
| **Pharmacist** | Manage stock, fill prescriptions, register medicine batches |
| **Supplier** | Receive orders, manage inventory, track deliveries |
| **Driver** | Accept and complete deliveries |
| **District Officer** | Monitor stock gaps, receive alerts, view analytics |
| **System Admin** | Full platform management |

---

## Technical Architecture

```
MedLink Uganda
├── Backend: Flask 3.0, Python 3.13
├── Database: SQLite (dev) / MySQL (production)
├── ORM: SQLAlchemy + Flask-SQLAlchemy  
├── Auth: Flask-Login
├── AI: Anthropic Claude Haiku (symptom checker + mental health chat)
├── Video: Daily.co (embedded iframe, no app required)
├── SMS: Africa's Talking (reminders + USSD)
├── PDF: ReportLab (prescriptions + referral letters)
├── Maps: Leaflet.js + OpenStreetMap (free, no API key)
├── Charts: Chart.js
├── UI: Tabler Icons, custom CSS design system
└── Background: Threading scheduler (appointment + ANC reminders)
```

**31 database models · 161 routes · 98 templates · 19 blueprints**

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up environment (edit .env with your API keys — all optional)
# ANTHROPIC_API_KEY for AI features
# AT_API_KEY for SMS
# DAILY_API_KEY for video calls

# 3. Seed the database with demo data
python seed.py

# 4. Run
python run.py

# 5. Open http://localhost:5000
```

### Demo Accounts (password: `medlink123`)

| Email | Role |
|-------|------|
| `admin@medlink.ug` | System Admin |
| `patient@medlink.ug` | Patient |
| `doctor@medlink.ug` | Doctor |
| `pharm@medlink.ug` | Pharmacist |
| `district@medlink.ug` | District Officer |

### Demo Medicine Verification Batches
| Batch Number | Result |
|-------------|--------|
| `UG-2024-CIP-001` | Verified |
| `UG-2022-EXP-001` | ⏰ Expired |
| `UG-2023-RCL-001` | Recalled |
| `FAKE-BATCH-999` | Not found |

---

## What Makes MedLink Different

| Feature | MedLink | mPharma (Ghana) | M-TIBA (Kenya) | Existing Uganda solutions |
|---------|---------|-----------------|----------------|--------------------------|
| Medicine search + map | | | | |
| Medicine verification | | | | |
| Telemedicine + video | | | | |
| Maternal health tracker | | | Partial | |
| Mental health (anonymous) | | | | |
| USSD (feature phone) | | | | |
| Local languages (SMS) | Luganda, Runyankole | | Swahili only | |
| AI symptom checker | Uganda-aware | | | |
| Built for Uganda | | | | |

---

## Impact Potential

- **4.7 million** Ugandans live more than 5km from a health facility
- **336** maternal deaths per 100,000 live births — most preventable with ANC
- **<100** psychiatrists for 48 million people
- **1 in 10** medicines substandard or counterfeit
- **70%** of Ugandans have a mobile phone — MedLink works on all of them (USSD)

---

*Built with for Uganda · MedLink Uganda 2024*
