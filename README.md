# RoadCare AI

A Flask web application for reporting and tracking road damage. Citizens submit complaints with photos and GPS location; administrators verify, assign, and track repairs through a dashboard.

> **Note:** The "AI" damage prediction is a **simulated placeholder** (`mock_ai_predict` in `app.py`) used for demonstration. It is not a trained model, and is designed to be swapped for a real computer-vision model.

## Features

**Citizen portal**
- Registration and login
- Report damage with photo, address, landmark and GPS coordinates
- Track complaint status by ID, with a status timeline and repair updates
- "My Complaints" history

**Admin dashboard**
- Metrics and charts (damage type, severity, status, monthly trend)
- Filter and search complaints (severity, damage type, status, ID)
- Verify, reject, assign to a department, update status, add remarks
- Add repair updates with photo and date
- Interactive complaint map
- JSON APIs: `/api/complaint/<id>` and `/api/admin/stats`

## Tech stack

Python, Flask, Flask-SQLAlchemy, SQLite, Pillow, Jinja2 templates.

## Getting started

```bash
git clone https://github.com/<your-username>/roadcare-ai.git
cd roadcare-ai
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Create your configuration:

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

Edit `.env` and set:

- `SECRET_KEY`: generate one with `python -c "import secrets; print(secrets.token_hex(32))"`
- `ADMIN_PASSWORD`: the password for the admin account (created on first run)

Then run:

```bash
python app.py
```

- Citizen portal: http://127.0.0.1:5000
- Admin login: http://127.0.0.1:5000/admin/login

Optional: set `SEED_DEMO_DATA=1` and `DEMO_PASSWORD=...` in `.env` to create a demo citizen and sample complaints.

## Running the tests

Start the app (with `SEED_DEMO_DATA=0`), then in another terminal:

```bash
python tests/test_phase5.py
```

The tests log in with `ADMIN_USERNAME` / `ADMIN_PASSWORD` from your `.env`. This is an end-to-end script that talks to the running server and creates test data, so use a throwaway database.

## Project structure

```
app.py               Flask app, models, routes
templates/           Jinja2 templates (citizen + admin)
static/              CSS, JS, uploads (uploaded files are git-ignored)
tests/               End-to-end test script
.env.example         Configuration template
requirements.txt     Python dependencies
```

## Roadmap

- Replace the mock predictor with a real trained model
- CSRF protection on forms
- Database migrations (Flask-Migrate) and PostgreSQL support
- Email/SMS notifications on status change