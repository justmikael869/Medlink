# MedLink Uganda — Setup Guide (Windows)

## QUICK START (SQLite — works right now, no MySQL needed)

1. Open the medlink folder in your terminal (PowerShell or CMD)

2. Install packages:
   ```
   pip install -r requirements.txt
   ```

3. The `.env` file is already set to use SQLite. No changes needed.

4. Seed the database:
   ```
   python seed.py
   ```

5. Run the app:
   ```
   python run.py
   ```

6. Open your browser: **http://localhost:5000**

---

## LOGIN CREDENTIALS (all use password: medlink123)

| Email | Role | Access |
|-------|------|--------|
| admin@medlink.ug | System Admin | Everything |
| district@medlink.ug | District Officer | Analytics + all alerts |
| doctor@medlink.ug | Facility Admin | Mulago Hospital |
| nurse@medlink.ug | Staff | Mulago Hospital |
| pharm@medlink.ug | Pharmacy Admin | Kampala Pharmacy |
| patient@medlink.ug | Patient | Search only |

---

## UPGRADE TO MYSQL (when ready for production)

### Step 1: Install MySQL
- Download MySQL Community Server: https://dev.mysql.com/downloads/mysql/
- During install, set a root password (remember it)

### Step 2: Create the database
Open MySQL Command Line Client and run:
```sql
CREATE DATABASE medlink CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### Step 3: Update your .env file
Open the `.env` file and change it to:
```
SECRET_KEY=medlink-uganda-secret-2024-change-in-production
DATABASE_URL=mysql+pymysql://root:YOUR_PASSWORD_HERE@localhost/medlink
```
Replace `YOUR_PASSWORD_HERE` with your actual MySQL root password.

### Step 4: Re-run seed
```
python seed.py
python run.py
```

---

## COMMON ERRORS

**"No connection could be made" (WinError 10061)**
→ MySQL is not running. Either start MySQL service or use SQLite (see Quick Start above).

**"Module not found"**
→ Run: `pip install -r requirements.txt`

**"Address already in use"**
→ Port 5000 is busy. Change the port in run.py: `app.run(port=5001)`

**Blank page or template error**
→ Make sure you ran `python seed.py` before `python run.py`

---

## FILE STRUCTURE

```
medlink/
├── run.py ← START HERE
├── seed.py ← Run once to fill database
├── .env ← Database settings
├── requirements.txt
├── app/
│ ├── __init__.py ← App setup
│ ├── models.py ← All database tables
│ ├── intelligence.py ← Auto-alerts, restock, gap detection
│ ├── routes/ ← All page logic
│ ├── templates/ ← All HTML pages
│ └── static/css/ ← Stylesheet
```

---

## NEW DEMO ACCOUNTS (added)

| Email | Role | Try |
|-------|------|-----|
| doctor@medlink.ug | Doctor | Confirm appointments, complete consultations, generate referral PDFs |
| patient@medlink.ug | Patient | Full patient journey — book, verify medicine, maternal, mental health |

---

## NEW FEATURES — HOW TO DEMO

### Medicine Verification
1. Go to `/verify` (public, no login)
2. Type `UG-2024-CIP-001` → green verified result
3. Type `UG-2023-RCL-001` → recalled warning
4. Type `UG-2022-EXP-001` → expired warning
5. Type anything random → not found / counterfeit warning

### AI Symptom Checker
1. Log in as patient
2. Go to Telemedicine → Symptom Check
3. Type "I have had a fever, headache and chills for 3 days"
4. With ANTHROPIC_API_KEY set → Claude gives malaria-aware response
5. Without key → rule-based fallback (still works)

### Maternal Health
1. Log in as patient → click "Maternal Health" in nav
2. Register with any LMP date
3. See full 8-visit ANC schedule with dates
4. Try marking a visit complete

### Mental Health
1. Go to `/mental-health` (no login needed)
2. Try the PHQ-9 → get severity result + pathway to doctor
3. Try the chat → type "I have been feeling very anxious"
4. With ANTHROPIC_API_KEY → real Claude response
5. Type "I want to end my life" → crisis resources appear immediately

### Video Call
1. Log in as doctor, confirm a remote appointment
2. Log in as patient, open the appointment
3. "Join Call" button appears → opens the built-in video room (no key needed)
4. Both join: each sees the other. Test mute, camera, screen share and chat
   (use two different browsers or one normal + one private window)

### Prescription PDF
1. Doctor completes a consultation with prescriptions
2. Patient opens appointment → "Prescription PDF" button
3. Professional PDF downloads with NDA details

### Referral Letter
1. Doctor ticks "referral needed" when completing consultation
2. Patient/doctor sees "Referral Letter" button on appointment
3. Downloads a formal referral letter PDF

---

## API KEYS — WHAT EACH DOES

All features work without any API keys in demo mode:

| Key | Where to get | What it unlocks |
|-----|-------------|----------------|
| `ANTHROPIC_API_KEY` | console.anthropic.com | Real AI for symptom checker + mental health chat |
| `AT_USERNAME` + `AT_API_KEY` | africastalking.com | Real SMS reminders (otherwise prints to console) |
| `TURN_URLS` + `TURN_USERNAME` + `TURN_CREDENTIAL` | any TURN provider | Optional relay so video connects on restrictive mobile networks (video works without it on most networks) |
