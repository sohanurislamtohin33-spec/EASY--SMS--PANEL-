from flask import Flask, render_template, request, jsonify, redirect, session, url_for
import requests
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import traceback

app = Flask(__name__)

# 🔐 সেশন সিকিউরিটি কি
app.secret_key = "mino_sms_panel_secure_static_key_2026"

# 🗄️ Supabase Connection Pooler (Session Mode)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://postgres.thpumuorrqfbqwyjxkkw:A1%40rtbc0066@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 🛠️ সার্ভারলেস কানেকশন অপটিমাইজেশন
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 280,
}

db = SQLAlchemy(app)

# ==================== DATABASE MODELS ====================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(50), nullable=False)
    balance = db.Column(db.Float, default=0.00)
    total_otps = db.Column(db.Integer, default=0)
    is_admin = db.Column(db.Boolean, default=False)

class WithdrawRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    bkash_number = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='Pending')
    date = db.Column(db.DateTime, default=datetime.utcnow)

class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    otp_rate = db.Column(db.Float, default=0.50)

# ==================== MANDATORY DATABASE INITIALIZATION ====================

with app.app_context():
    try:
        db.create_all()
        if not SystemSettings.query.first():
            db.session.add(SystemSettings(otp_rate=0.50))
            db.session.commit()
        if not User.query.filter_by(username="admin").first():
            db.session.add(User(username="admin", password="admin123", is_admin=True))
            db.session.commit()
    except Exception as e:
        print("Database initialization error:", str(e))

# 🛠️ ERROR TRACKER
@app.errorhandler(500)
def internal_server_error(e):
    return f"<h3>Internal Server Error (Detailed Log):</h3><pre>{traceback.format_exc()}</pre>", 500

# ==================== CONFIG & DECORATORS ====================

API_BASE = "https://mino-sms-panel.xyz"
PANEL_TOKEN = "mino_live_d90eba7078a418fa056c2c16f7facbba"

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session.get('is_admin'):
            return "অ্যাক্সেস ডিনাইড! আপনি অ্যাডমিন নন।", 403
        return f(*args, **kwargs)
    return decorated_function

# Context Processor যাতে base.html ফাইলের টপ বারে রিয়েল-টাইম ব্যালেন্স শো করে
@app.context_processor
def inject_user_balance():
    if 'logged_in' in session:
        user = User.query.filter_by(username=session['username']).first()
        if user:
            return dict(global_balance=user.balance)
    return dict(global_balance=0.00)

# ==================== AUTH ROUTES ====================

@app.route('/')
def home():
    if 'logged_in' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        
        try:
            user = User.query.filter_by(username=username, password=password).first()
            if user:
                session['logged_in'] = True
                session['username'] = user.username
                session['is_admin'] = user.is_admin
                return redirect(url_for('dashboard'))
            else:
                error = "ভুল ইউজারনেম অথবা পাসওয়ার্ড!"
        except Exception as e:
            db.session.rollback()
            raise e
            
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ==================== PAGE ROUTES ====================

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.filter_by(username=session['username']).first()
    settings = SystemSettings.query.first()
    current_otp_rate = settings.otp_rate if settings else 0.50

    user_data = {
        "balance": user.balance if user else 0.00,
        "today_otps": user.total_otps if user else 0,
        "yesterday_otps": 0,
        "today_numbers": 0,
        "today_success": 0,
        "yesterday_numbers": 0,
        "yesterday_success": 0
    }
    
    chart_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    chart_data = [0, 0, 0, 0, 0, 0, 0]

    return render_template('dashboard.html', user_data=user_data, otp_rate=current_otp_rate, chart_labels=chart_labels, chart_data=chart_data)

@app.route('/get_number_page')
@login_required
def get_number_page():
    return render_template('get_number.html')

@app.route('/console_page')
@login_required
def console_page():
    return render_template('console.html')

@app.route('/withdraw_page')
@login_required
def withdraw_page():
    user = User.query.filter_by(username=session['username']).first()
    user_balance = user.balance if user else 0.00
    return render_template('withdraw_page.html', balance=user_balance)

@app.route('/admin/panel')
@admin_required
def admin_panel():
    users = User.query.all()
    withdraws = WithdrawRequest.query.order_by(WithdrawRequest.id.desc()).all()
    settings = SystemSettings.query.first()
    return render_template('admin_dashboard.html', users=users, withdraws=withdraws, settings=settings)

# ==================== USER API ROUTES ====================

@app.route('/api/buy_number', methods=['POST'])
@login_required
def buy_number():
    data = request.json
    rid = data.get('rid')
    
    url = f"{API_BASE}/getnumber"
    params = {"api_key": PANEL_TOKEN, "rid": rid, "national_format": 0, "remove_plus": 0}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return jsonify(response.json())
        return jsonify({"status": "error", "message": f"Server error: {response.status_code}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/check_otp', methods=['POST'])
@login_required
def check_otp():
    data = request.json
    target_number = str(data.get('number')).replace('+', '').strip()
    
    url = f"{API_BASE}/success_otp"
    params = {"api_key": PANEL_TOKEN}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            json_data = response.json()
            
            if json_data.get("status") == "success" and "data" in json_data:
                all_logs = json_data.get("data", [])
                matched_otps = []
                
                for log in all_logs:
                    log_num = str(log.get('number') or log.get('num') or log.get('range', '')).replace('+', '').strip()
                    if target_number in log_num or log_num in target_number:
                        matched_otps.append(log)
                
                if matched_otps:
                    user = User.query.filter_by(username=session['username']).first()
                    if user:
                        current_rate = SystemSettings.query.first().otp_rate
                        user.balance += current_rate
                        user.total_otps += 1
                        db.session.commit()
                
                return jsonify({"status": "success", "data": matched_otps})
            return jsonify({"status": "success", "data": []})
        return jsonify({"status": "error", "data": []})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "data": []})

@app.route('/api/withdraw', methods=['POST'])
@login_required
def user_withdraw():
    data = request.json
    bkash_num = data.get('bkash_number')
    amount = float(data.get('amount', 0))
    
    user = User.query.filter_by(username=session['username']).first()
    
    if amount < 20:
        return jsonify({"status": "error", "message": "সর্বনিম্ন ২০ টাকা উইথড্র করতে পারবেন!"})
    if user.balance < amount:
        return jsonify({"status": "error", "message": "আপনার অ্যাকাউন্টে পর্যাপ্ত ব্যালেন্স নেই!"})
        
    user.balance -= amount
    new_request = WithdrawRequest(username=user.username, amount=amount, bkash_number=bkash_num)
    db.session.add(new_request)
    db.session.commit()
    
    return jsonify({"status": "success", "message": "উইথড্র রিকোয়েস্ট অ্যাডমিন প্যানেলে পাঠানো হয়েছে! ✅"})

# ==================== ADMIN CONTROL API ROUTES ====================

@app.route('/admin/add_user', methods=['POST'])
@admin_required
def add_user():
    username = request.form.get('username').strip()
    password = request.form.get('password').strip()
    
    if User.query.filter_by(username=username).first():
        return jsonify({"status": "error", "message": "এই ইউজারনেম ইতিমধ্যে আছে!"})
        
    new_user = User(username=username, password=password)
    db.session.add(new_user)
    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_user/<int:user_id>')
@admin_required
def delete_user(user_id):
    user = User.query.get(user_id)
    if user and not user.is_admin:
        db.session.delete(user)
        db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/update_rate', methods=['POST'])
@admin_required
def update_rate():
    new_rate = float(request.form.get('otp_rate', 0.50))
    settings = SystemSettings.query.first()
    settings.otp_rate = new_rate
    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/modify_balance', methods=['POST'])
@admin_required
def modify_balance():
    user_id = int(request.form.get('user_id'))
    amount = float(request.form.get('amount'))
    
    user = User.query.get(user_id)
    if user:
        user.balance += amount
        db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/approve_withdraw/<int:req_id>')
@admin_required
def approve_withdraw(req_id):
    req = WithdrawRequest.query.get(req_id)
    if req:
        req.status = 'Approved'
        db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/api/console_stream')
@login_required
def console_stream():
    url = f"{API_BASE}/console"
    params = {"api_key": PANEL_TOKEN}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            json_data = response.json()
            if json_data.get("status") == "success":
                return jsonify({"status": "success", "data": json_data.get("data", [])})
        return jsonify({"status": "error", "data": []})
    except Exception as e:
        return jsonify({"status": "error", "data": []})
