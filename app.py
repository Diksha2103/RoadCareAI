"""
RoadCare AI - Main Flask Application
Citizen complaint system + Admin dashboard.

Configuration is read from environment variables (see .env.example).
"""

import os
import json
import random
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, UnidentifiedImageError

try:  # python-dotenv is optional; real environment variables always work
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ─── App Configuration ───────────────────────────────────────────────────────
app = Flask(__name__)

_secret_key = os.environ.get('SECRET_KEY')
if not _secret_key:
    raise RuntimeError(
        "SECRET_KEY is not set. Copy .env.example to .env and set a long random value."
    )
app.config['SECRET_KEY'] = _secret_key
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///roadcare.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['REPAIR_UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads', 'repairs')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_IMAGE_FORMATS = {'PNG', 'JPEG', 'GIF', 'WEBP'}

db = SQLAlchemy(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['REPAIR_UPLOAD_FOLDER'], exist_ok=True)


def utcnow():
    """Naive UTC timestamp (avoids the deprecated datetime.utcnow())."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _from_json(value):
    try:
        return json.loads(value)
    except Exception:
        return []


# ─── Jinja2 Utilities ─────────────────────────────────────────────────────────
app.jinja_env.globals['enumerate'] = enumerate
app.jinja_env.globals['now'] = datetime.now
app.jinja_env.filters['from_json'] = _from_json

# ─── Departments (configurable list) ─────────────────────────────────────────
DEPARTMENTS = [
    "Municipal Corporation",
    "Public Works Department",
    "Local Road Maintenance Team",
    "National Highway Authority",
    "State Road Transport Department",
    "Urban Development Authority",
]

DAMAGE_TYPES = ["Pothole", "Crack", "Subsidence", "Erosion", "Waterlogging", "Broken Road Edge"]
SEVERITY_LEVELS = ["Low", "Medium", "High", "Critical"]
STATUS_FLOW = [
    "Submitted",
    "Under Verification",
    "Verified",
    "Assigned",
    "Repair In Progress",
    "Resolved",
    "Closed",
]

# ─── Database Models ──────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='citizen')  # 'citizen' or 'admin'
    full_name = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=utcnow)
    complaints = db.relationship('Complaint', backref='reporter', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Complaint(db.Model):
    __tablename__ = 'complaints'
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # Reporter info (for anonymous reports)
    reporter_name = db.Column(db.String(120))
    reporter_email = db.Column(db.String(120))
    reporter_phone = db.Column(db.String(20))

    # Location
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    address = db.Column(db.String(500))
    landmark = db.Column(db.String(200))

    # Damage details
    damage_type = db.Column(db.String(50))
    severity = db.Column(db.String(20))
    description = db.Column(db.Text)
    image_path = db.Column(db.String(300))

    # AI prediction
    ai_damage_type = db.Column(db.String(50))
    ai_severity = db.Column(db.String(20))
    ai_confidence = db.Column(db.Float)
    ai_details = db.Column(db.Text)  # JSON string

    # Admin fields
    status = db.Column(db.String(50), default='Submitted')
    assigned_department = db.Column(db.String(100))
    admin_remarks = db.Column(db.Text)
    verified_at = db.Column(db.DateTime)
    assigned_at = db.Column(db.DateTime)
    resolved_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    repair_updates = db.relationship('RepairUpdate', backref='complaint', lazy=True, order_by='RepairUpdate.created_at')


class RepairUpdate(db.Model):
    __tablename__ = 'repair_updates'
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaints.id'), nullable=False)
    status = db.Column(db.String(50))
    remarks = db.Column(db.Text)
    image_path = db.Column(db.String(300))
    update_date = db.Column(db.DateTime, default=utcnow)
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=utcnow)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_image(file, folder, url_prefix, name_prefix=''):
    """
    Validate and save an uploaded image.
    Checks the extension AND that the content really is an image (via Pillow).
    Returns the relative static path (e.g. 'uploads/xyz.png') or None.
    """
    if not file or not file.filename or not allowed_file(file.filename):
        return None
    try:
        with Image.open(file.stream) as img:
            if img.format not in ALLOWED_IMAGE_FORMATS:
                return None
    except (UnidentifiedImageError, OSError):
        return None
    finally:
        file.stream.seek(0)

    stamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    filename = secure_filename(f"{name_prefix}{stamp}_{file.filename}")
    file.save(os.path.join(folder, filename))
    return f"{url_prefix}/{filename}"


def generate_complaint_id():
    prefix = "RC"
    year = datetime.now().year
    number = Complaint.query.count() + 1
    candidate = f"{prefix}{year}{number:05d}"
    # Guard against collisions (e.g. after deletions)
    while Complaint.query.filter_by(complaint_id=candidate).first():
        number += 1
        candidate = f"{prefix}{year}{number:05d}"
    return candidate


def mock_ai_predict(image_path, user_damage_type=None, user_severity=None):
    """
    SIMULATED prediction for demo purposes. Not a trained model.
    Replace this function with a real computer-vision model to get real results.
    """
    damage_types = DAMAGE_TYPES
    severities = SEVERITY_LEVELS

    # Simulate prediction (slightly biased toward user input if provided)
    if user_damage_type and user_damage_type in damage_types:
        predicted_type = user_damage_type if random.random() > 0.2 else random.choice(damage_types)
    else:
        predicted_type = random.choice(damage_types)

    if user_severity and user_severity in severities:
        predicted_severity = user_severity if random.random() > 0.3 else random.choice(severities)
    else:
        predicted_severity = random.choice(severities)

    confidence = round(random.uniform(0.70, 0.98), 2)

    details = {
        "model": "mock-predictor (simulated)",
        "predicted_type": predicted_type,
        "predicted_severity": predicted_severity,
        "confidence": confidence,
        "type_probabilities": {t: round(random.uniform(0.01, 0.3), 2) for t in damage_types},
        "severity_probabilities": {s: round(random.uniform(0.05, 0.5), 2) for s in severities},
        "analysis_time_ms": random.randint(120, 450),
        "road_condition_score": round(random.uniform(2.0, 8.5), 1),
    }
    details["type_probabilities"][predicted_type] = round(confidence, 2)
    details["severity_probabilities"][predicted_severity] = round(confidence * 0.9, 2)

    return predicted_type, predicted_severity, confidence, json.dumps(details)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('admin_login'))
        if session.get('role') != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    if 'user_id' in session:
        return db.session.get(User, session['user_id'])
    return None


def get_or_404(model, pk):
    obj = db.session.get(model, pk)
    if obj is None:
        from flask import abort
        abort(404)
    return obj


# ─── Citizen Routes ───────────────────────────────────────────────────────────

@app.route('/')
def home():
    user = get_current_user()
    stats = {
        'total': Complaint.query.count(),
        'resolved': Complaint.query.filter_by(status='Resolved').count(),
        'in_progress': Complaint.query.filter_by(status='Repair In Progress').count(),
    }
    recent = Complaint.query.order_by(Complaint.created_at.desc()).limit(5).all()
    return render_template('index.html', user=user, stats=stats, recent=recent)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()

        if not username or not email or len(password) < 8:
            flash('Username, email and a password of at least 8 characters are required.', 'danger')
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('register'))

        user = User(username=username, email=email, full_name=full_name, phone=phone)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            if user.role == 'admin':
                flash('Please use the admin login portal.', 'warning')
                return redirect(url_for('admin_login'))
            session.clear()
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash(f'Welcome back, {user.full_name or user.username}!', 'success')
            return redirect(url_for('home'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))


@app.route('/report', methods=['GET', 'POST'])
def report():
    user = get_current_user()
    if request.method == 'POST':
        reporter_name = request.form.get('reporter_name', '').strip()
        reporter_email = request.form.get('reporter_email', '').strip()
        reporter_phone = request.form.get('reporter_phone', '').strip()
        latitude = request.form.get('latitude')
        longitude = request.form.get('longitude')
        address = request.form.get('address', '').strip()
        landmark = request.form.get('landmark', '').strip()
        damage_type = request.form.get('damage_type', '')
        severity = request.form.get('severity', '')
        description = request.form.get('description', '').strip()

        # Handle image upload (validated)
        image_path = None
        if 'image' in request.files:
            image_path = save_uploaded_image(
                request.files['image'], app.config['UPLOAD_FOLDER'], 'uploads'
            )

        # AI Prediction (simulated)
        ai_type, ai_severity, ai_confidence, ai_details = mock_ai_predict(
            image_path, damage_type, severity
        )

        # Parse coordinates safely
        lat, lng = None, None
        try:
            if latitude and str(latitude).strip():
                lat = float(str(latitude).strip())
        except (ValueError, TypeError):
            lat = None
        try:
            if longitude and str(longitude).strip():
                lng = float(str(longitude).strip())
        except (ValueError, TypeError):
            lng = None

        complaint = Complaint(
            complaint_id=generate_complaint_id(),
            user_id=user.id if user else None,
            reporter_name=reporter_name if not user else (user.full_name or user.username),
            reporter_email=reporter_email if not user else user.email,
            reporter_phone=reporter_phone if not user else user.phone,
            latitude=lat,
            longitude=lng,
            address=address,
            landmark=landmark,
            damage_type=damage_type,
            severity=severity,
            description=description,
            image_path=image_path,
            ai_damage_type=ai_type,
            ai_severity=ai_severity,
            ai_confidence=ai_confidence,
            ai_details=ai_details,
            status='Submitted',
        )
        db.session.add(complaint)
        db.session.commit()
        flash(f'Complaint submitted successfully! Your ID: {complaint.complaint_id}', 'success')
        return redirect(url_for('track', complaint_id=complaint.complaint_id))

    return render_template('report.html', user=user, damage_types=DAMAGE_TYPES, severities=SEVERITY_LEVELS)


@app.route('/track')
def track():
    user = get_current_user()
    complaint_id = request.args.get('complaint_id', '').strip()
    complaint = None
    if complaint_id:
        complaint = Complaint.query.filter_by(complaint_id=complaint_id).first()
        if not complaint:
            flash(f'No complaint found with ID: {complaint_id}', 'warning')
    return render_template('track.html', user=user, complaint=complaint, complaint_id=complaint_id)


@app.route('/my-complaints')
@login_required
def my_complaints():
    user = get_current_user()
    complaints = Complaint.query.filter_by(user_id=user.id).order_by(Complaint.created_at.desc()).all()
    return render_template('my_complaints.html', user=user, complaints=complaints)


# ─── Admin Routes ─────────────────────────────────────────────────────────────

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username, role='admin').first()
        if user and user.check_password(password):
            session.clear()
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = 'admin'
            flash(f'Welcome, Admin {user.full_name or user.username}!', 'success')
            return redirect(url_for('admin_dashboard'))
        flash('Invalid admin credentials.', 'danger')
    return render_template('admin/login.html')


@app.route('/admin/logout')
def admin_logout():
    session.clear()
    flash('Admin logged out.', 'info')
    return redirect(url_for('admin_login'))


@app.route('/admin')
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    user = get_current_user()
    stats = {
        'total': Complaint.query.count(),
        'submitted': Complaint.query.filter_by(status='Submitted').count(),
        'under_verification': Complaint.query.filter_by(status='Under Verification').count(),
        'verified': Complaint.query.filter_by(status='Verified').count(),
        'assigned': Complaint.query.filter_by(status='Assigned').count(),
        'in_progress': Complaint.query.filter_by(status='Repair In Progress').count(),
        'resolved': Complaint.query.filter_by(status='Resolved').count(),
        'closed': Complaint.query.filter_by(status='Closed').count(),
        'pending': Complaint.query.filter(
            Complaint.status.in_(['Submitted', 'Under Verification'])
        ).count(),
    }

    damage_dist = {dt: Complaint.query.filter_by(damage_type=dt).count() for dt in DAMAGE_TYPES}
    severity_dist = {s: Complaint.query.filter_by(severity=s).count() for s in SEVERITY_LEVELS}
    status_dist = {s: Complaint.query.filter_by(status=s).count() for s in STATUS_FLOW}

    # Monthly trends (last 6 months)
    monthly_data = []
    for i in range(5, -1, -1):
        month_start = (utcnow().replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1)
        count = Complaint.query.filter(
            Complaint.created_at >= month_start,
            Complaint.created_at < month_end
        ).count()
        monthly_data.append({
            'month': month_start.strftime('%b %Y'),
            'count': count
        })

    recent = Complaint.query.order_by(Complaint.created_at.desc()).limit(10).all()

    return render_template(
        'admin/dashboard.html',
        user=user,
        stats=stats,
        damage_dist=json.dumps(damage_dist),
        severity_dist=json.dumps(severity_dist),
        status_dist=json.dumps(status_dist),
        monthly_data=json.dumps(monthly_data),
        recent=recent,
        departments=DEPARTMENTS,
    )


@app.route('/admin/complaints')
@admin_required
def admin_complaints():
    user = get_current_user()
    search_id = request.args.get('search_id', '').strip()
    filter_severity = request.args.get('severity', '')
    filter_damage = request.args.get('damage_type', '')
    filter_status = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)

    query = Complaint.query
    if search_id:
        query = query.filter(Complaint.complaint_id.ilike(f'%{search_id}%'))
    if filter_severity:
        query = query.filter_by(severity=filter_severity)
    if filter_damage:
        query = query.filter_by(damage_type=filter_damage)
    if filter_status:
        query = query.filter_by(status=filter_status)

    complaints = query.order_by(Complaint.created_at.desc()).paginate(page=page, per_page=15)
    return render_template(
        'admin/complaints.html',
        user=user,
        complaints=complaints,
        damage_types=DAMAGE_TYPES,
        severities=SEVERITY_LEVELS,
        statuses=STATUS_FLOW,
        departments=DEPARTMENTS,
        filters={'search_id': search_id, 'severity': filter_severity,
                 'damage_type': filter_damage, 'status': filter_status},
    )


@app.route('/admin/complaints/<int:complaint_pk>')
@admin_required
def admin_complaint_detail(complaint_pk):
    user = get_current_user()
    complaint = get_or_404(Complaint, complaint_pk)
    ai_details = {}
    if complaint.ai_details:
        try:
            ai_details = json.loads(complaint.ai_details)
        except Exception:
            pass
    return render_template(
        'admin/complaint_detail.html',
        user=user,
        complaint=complaint,
        ai_details=ai_details,
        departments=DEPARTMENTS,
        statuses=STATUS_FLOW,
    )


@app.route('/admin/complaints/<int:complaint_pk>/update', methods=['POST'])
@admin_required
def admin_update_complaint(complaint_pk):
    complaint = get_or_404(Complaint, complaint_pk)
    action = request.form.get('action', '')
    remarks = request.form.get('remarks', '').strip()

    if action == 'verify':
        complaint.status = 'Verified'
        complaint.verified_at = utcnow()
        if remarks:
            complaint.admin_remarks = remarks
        flash('Complaint verified successfully.', 'success')

    elif action == 'reject':
        complaint.status = 'Closed'
        if remarks:
            complaint.admin_remarks = remarks
        flash('Complaint rejected and closed.', 'warning')

    elif action == 'assign':
        department = request.form.get('department', '')
        if department in DEPARTMENTS:
            complaint.assigned_department = department
            complaint.status = 'Assigned'
            complaint.assigned_at = utcnow()
            if remarks:
                complaint.admin_remarks = remarks
            flash(f'Complaint assigned to {department}.', 'success')
        else:
            flash('Please select a valid department.', 'danger')

    elif action == 'update_status':
        new_status = request.form.get('status', '')
        if new_status in STATUS_FLOW:
            complaint.status = new_status
            if new_status == 'Resolved':
                complaint.resolved_at = utcnow()
            if remarks:
                complaint.admin_remarks = remarks
            flash(f'Status updated to {new_status}.', 'success')

    elif action == 'add_remarks':
        complaint.admin_remarks = remarks
        flash('Remarks updated.', 'success')

    complaint.updated_at = utcnow()
    db.session.commit()
    return redirect(url_for('admin_complaint_detail', complaint_pk=complaint_pk))


@app.route('/admin/complaints/<int:complaint_pk>/repair-update', methods=['POST'])
@admin_required
def admin_add_repair_update(complaint_pk):
    complaint = get_or_404(Complaint, complaint_pk)
    status = request.form.get('status', '')
    remarks = request.form.get('remarks', '').strip()
    update_date_str = request.form.get('update_date', '')

    image_path = None
    if 'repair_image' in request.files:
        image_path = save_uploaded_image(
            request.files['repair_image'],
            app.config['REPAIR_UPLOAD_FOLDER'],
            'uploads/repairs',
            name_prefix='repair_',
        )

    try:
        update_date = datetime.strptime(update_date_str, '%Y-%m-%d') if update_date_str else utcnow()
    except ValueError:
        update_date = utcnow()

    repair_update = RepairUpdate(
        complaint_id=complaint.id,
        status=status or complaint.status,
        remarks=remarks,
        image_path=image_path,
        update_date=update_date,
        created_by=session.get('username', 'admin'),
    )
    db.session.add(repair_update)

    if status and status in STATUS_FLOW:
        complaint.status = status
        if status == 'Resolved':
            complaint.resolved_at = utcnow()

    complaint.updated_at = utcnow()
    db.session.commit()
    flash('Repair update added successfully.', 'success')
    return redirect(url_for('admin_complaint_detail', complaint_pk=complaint_pk))


@app.route('/admin/map')
@admin_required
def admin_map():
    user = get_current_user()
    complaints = Complaint.query.filter(
        Complaint.latitude.isnot(None),
        Complaint.longitude.isnot(None)
    ).all()
    complaints_data = [{
        'id': c.id,
        'complaint_id': c.complaint_id,
        'lat': c.latitude,
        'lng': c.longitude,
        'address': c.address,
        'damage_type': c.damage_type,
        'severity': c.severity,
        'status': c.status,
    } for c in complaints]
    return render_template('admin/map.html', user=user, complaints_data=json.dumps(complaints_data))


# ─── API Endpoints ────────────────────────────────────────────────────────────

@app.route('/api/complaint/<complaint_id>')
def api_complaint_status(complaint_id):
    complaint = Complaint.query.filter_by(complaint_id=complaint_id).first()
    if not complaint:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({
        'complaint_id': complaint.complaint_id,
        'status': complaint.status,
        'damage_type': complaint.damage_type,
        'severity': complaint.severity,
        'created_at': complaint.created_at.isoformat(),
        'updated_at': complaint.updated_at.isoformat() if complaint.updated_at else None,
        'assigned_department': complaint.assigned_department,
        'admin_remarks': complaint.admin_remarks,
        'repair_updates': [{
            'status': u.status,
            'remarks': u.remarks,
            'image_path': u.image_path,
            'update_date': u.update_date.strftime('%Y-%m-%d') if u.update_date else None,
            'created_by': u.created_by
        } for u in complaint.repair_updates]
    })


@app.route('/api/admin/stats')
@admin_required
def api_admin_stats():
    stats = {
        'total': Complaint.query.count(),
        'by_status': {s: Complaint.query.filter_by(status=s).count() for s in STATUS_FLOW},
        'by_severity': {s: Complaint.query.filter_by(severity=s).count() for s in SEVERITY_LEVELS},
        'by_damage': {d: Complaint.query.filter_by(damage_type=d).count() for d in DAMAGE_TYPES},
    }
    return jsonify(stats)


# ─── Database Initialization ──────────────────────────────────────────────────

def seed_database():
    """
    Create the admin account from environment variables, and (optionally)
    demo data when SEED_DEMO_DATA=1.
    """
    admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
    admin_password = os.environ.get('ADMIN_PASSWORD')

    if admin_password:
        if not User.query.filter_by(username=admin_username).first():
            admin = User(
                username=admin_username,
                email='admin@example.com',
                full_name='System Administrator',
                role='admin',
            )
            admin.set_password(admin_password)
            db.session.add(admin)
            print(f"[setup] Admin account '{admin_username}' created.")
    elif not User.query.filter_by(role='admin').first():
        print("[setup] WARNING: no admin exists. Set ADMIN_PASSWORD in .env and restart.")

    demo_password = os.environ.get('DEMO_PASSWORD')
    if os.environ.get('SEED_DEMO_DATA') == '1' and demo_password:
        if not User.query.filter_by(username='citizen1').first():
            citizen = User(
                username='citizen1',
                email='citizen@example.com',
                full_name='Demo Citizen',
                phone='0000000000',
                role='citizen',
            )
            citizen.set_password(demo_password)
            db.session.add(citizen)
            db.session.flush()

            sample_locations = [
                (28.6139, 77.2090, "Connaught Place, New Delhi"),
                (28.5355, 77.3910, "Sector 18, Noida"),
                (28.4595, 77.0266, "DLF Cyber City, Gurugram"),
                (28.7041, 77.1025, "Rohini, New Delhi"),
                (28.6304, 77.2177, "India Gate, New Delhi"),
            ]
            statuses = STATUS_FLOW[:5]
            year = datetime.now().year
            for i, (lat, lng, addr) in enumerate(sample_locations):
                dt = random.choice(DAMAGE_TYPES)
                sev = random.choice(SEVERITY_LEVELS)
                ai_type, ai_sev, ai_conf, ai_det = mock_ai_predict(None, dt, sev)
                db.session.add(Complaint(
                    complaint_id=f"RC{year}{i+1:05d}",
                    user_id=citizen.id,
                    reporter_name='Demo Citizen',
                    reporter_email='citizen@example.com',
                    reporter_phone='0000000000',
                    latitude=lat,
                    longitude=lng,
                    address=addr,
                    damage_type=dt,
                    severity=sev,
                    description=f"Sample road damage complaint #{i+1}.",
                    ai_damage_type=ai_type,
                    ai_severity=ai_sev,
                    ai_confidence=ai_conf,
                    ai_details=ai_det,
                    status=statuses[i % len(statuses)],
                    assigned_department=DEPARTMENTS[i % len(DEPARTMENTS)] if i > 1 else None,
                ))

    db.session.commit()


def init_app_data():
    with app.app_context():
        db.create_all()
        seed_database()


# Initialise on import so `flask run` and WSGI servers also get a ready database.
init_app_data()


if __name__ == '__main__':
    app.run(
        host=os.environ.get('FLASK_HOST', '127.0.0.1'),
        port=int(os.environ.get('PORT', 5000)),
        debug=os.environ.get('FLASK_DEBUG') == '1',
    )