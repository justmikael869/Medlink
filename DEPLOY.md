# Deploying MedLink Uganda on Render + Supabase (PostgreSQL)

## 1. Get your Supabase pooler string
Supabase dashboard > your project > **Connect** > **Connection string** > choose **Session pooler** (port 5432).
It looks like:
`postgresql://postgres.PROJECTREF:YOUR-PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres`
(If your password has special characters like @ # / : , URL-encode them, e.g. @ -> %40.)

## 2. Create the tables + demo data (one time, from your Windows PC)
```
cd C:\path\to\medlink
pip install -r requirements.txt
set DATABASE_URL=postgresql://postgres.PROJECTREF:YOUR-PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres
python seed.py
```
(PowerShell: `$env:DATABASE_URL="..."`.) Skip `seed.py` if you want an empty database; the app
creates the tables itself on first start.

## 3. Push to GitHub
Put the contents of the `medlink` folder at the root of a repo (Procfile and render.yaml must be at the root).
`.env` is git-ignored, so your secrets never get uploaded.

## 4. Create the service on Render
New > **Blueprint** > pick the repo (reads render.yaml). When asked, fill in:
- `DATABASE_URL` = your Supabase pooler string
- `APP_URL` = your Render URL (e.g. https://medlink-uganda.onrender.com)
- Optional keys (ANTHROPIC_API_KEY, ...) can stay blank: the app runs in demo mode.

Or create a normal Web Service by hand: Build `pip install -r requirements.txt`,
Start `gunicorn run:app --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT`.

## Notes
- Keep **1 worker**: the app runs a background reminder thread, and more workers would send duplicate SMS reminders.
- `db.create_all()` only creates missing tables; it does not alter existing ones. If you change a model later, add the column in the Supabase SQL editor.
- `migrate_db.py` is the old SQLite-only migration script and is not used on Postgres.
- Demo accounts have well-known passwords (see seed output). Change or delete them before real use.
