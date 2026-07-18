from flask import Flask, render_template, request, jsonify, redirect, session, url_for
import requests
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.pool import NullPool
from datetime import datetime
import traceback
import os

app = Flask(__name__)

# সেশন সিকিউরিটি কি (Render এনভায়রনমেন্ট ভ্যারিয়েবল থেকে নেওয়ার চেষ্টা করবে, না থাকলে ডিফল্ট)
app.secret_key = os.getenv("SECRET_KEY", "mino_sms_panel_secure_static_key_2026")

# Supabase Connection Pooler URI
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://postgres.thpumuorrqfbqwyjxkkw:A1%40rtbc0066@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres?sslmode=require'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# সার্ভারলেস ও ট্রানজেকশন মোডের জন্য কানেকশন ম্যানেজমেন্ট
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "poolclass": NullPool,
    "pool_pre_ping": True,
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

class ManualNumber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(30), unique=True, nullable=False)
    number_range = db.Column(db.String(20), nullable=False)
    is_sold = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ==================== SAFE DATABASE INITIALIZATION ====================
# ট্রানজেকশন মোডে ক্র্যাশ এড়াতে ট্রাই-ক্যাচ ব্লক এবং সেফ ইনিশিয়ালাইজেশন
with app.app_context():
    try:
        db.create_all()
        
        # ডিফল্ট সেটিংস চেক ও ইনসার্ট
        settings = SystemSettings.query.first()
        if not settings:
            db.session.add(SystemSettings(otp_rate=0.50))
            db.session.commit()
            
        # ডিফল্ট অ্যাডমিন চেক ও ইনসার্ট
        admin_user = User.query.filter_by(username="admin").first()
        if not admin_user:
            db.session.add(User(username="admin", password="admin123", is_admin=True))
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print("Database initialization skipped or handled safely:", str(e))

# রিকোয়েস্ট শেষে কানেকশন রিলিজ করার ক্লিনিং লজিক
@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()

# ERROR TRACKER
@app.errorhandler(500)
def internal_server_error(e):
    return f"<h3>Internal Server Error (Detailed Log):</h3><pre>{traceback.format_exc()}</pre>", 500

# ==================== CONFIG & DECORATORS ====================

API_BASE = "https://mino-sms-panel.xyz"
PANEL_TOKEN = "mino_live_d90eba7078a418fa056c2c16f7facbba"

PANEL_2_URL = "http://147.135.212.197/crapi/had/viewstats"
PANEL_2_TOKEN = "Qk5TQUZBUzSHg3h9ZFKWSGqEa3SDcnZjh4aUf0dxV2FEUo9TZGFyVg=="

PANEL_3_URL = "http://147.135.212.197/crapi/st/viewstats"
PANEL_3_TOKEN = "Qk9QQkZBUzRriFaEcmeNeYmMmWB2d4thfVCEcl9VgIRWc41SZ2Fsiw=="

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

# ডাটাবেস কুয়েরি কমিয়ে সেশন থেকে ব্যালেন্স ইনজেক্ট করার অপ্টিমাইজড মেথড
@app.context_processor
def inject_user_balance():
    if 'logged_in' in session and 'user_balance' in session:
        return dict(global_balance=session['user_balance'])
    return dict(global_balance=0.00)

# ==================== AUTH & PAGE ROUTES ====================

@app.route('/')
def home():
    if 'logged_in' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        try:
            user = User.query.filter_by(username=username, password=password).first()
            if user:
                session['logged_in'] = True
                session['username'] = user.username
                session['is_admin'] = user.is_admin
                session['user_balance'] = user.balance  # সেশনে ব্যালেন্স স্টোর
                session['total_otps'] = user.total_otps
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

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        settings = SystemSettings.query.first()
        current_otp_rate = settings.otp_rate if settings else 0.50
    except Exception:
        current_otp_rate = 0.50
        
    user_data = {
        "balance": session.get('user_balance', 0.00),
        "today_otps": session.get('total_otps', 0),
        "yesterday_otps": 0, "today_numbers": 0, "today_success": 0,
        "yesterday_numbers": 0, "yesterday_success": 0
    }
    return render_template('dashboard.html', user_data=user_data, otp_rate=current_otp_rate, chart_labels=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], chart_data=[0,0,0,0,0,0,0])

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
    return render_template('withdraw_page.html', balance=session.get('user_balance', 0.00))

@app.route('/admin/panel')
@admin_required
def admin_panel():
    users = User.query.all()
    withdraws = WithdrawRequest.query.order_by(WithdrawRequest.id.desc()).all()
    settings = SystemSettings.query.first()
    total_manual_stock = ManualNumber.query.filter_by(is_sold=False).count()
    return render_template('admin_dashboard.html', users=users, withdraws=withdraws, settings=settings, total_manual_stock=total_manual_stock)

# ==================== SMART NUMBER API ROUTE ====================

@app.route('/api/buy_number', methods=['POST'])
@login_required
def buy_number():
    data = request.json or {}
    rid = str(data.get('rid', '')).strip()
    
    if 'X' in rid.upper() or len(rid) > 4:
        url = f"{API_BASE}/getnumber"
        params = {"api_key": PANEL_TOKEN, "rid": rid, "national_format": 0, "remove_plus": 0}
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return jsonify(response.json())
            return jsonify({"status": "error", "message": f"Server error: {response.status_code}"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
    
    else:
        local_number = ManualNumber.query.filter_by(number_range=rid, is_sold=False).first()
        if local_number:
            local_number.is_sold = True
            db.session.commit()
            return jsonify({
                "status": "success",
                "number": local_number.number,
                "id": f"manual_{local_number.id}",
                "range": local_number.number_range
            })
        else:
            return jsonify({"status": "error", "message": f"{rid} রেঞ্জের কোনো নাম্বার এখন স্টকে নেই!"})

# ==================== SMART ALL-PANEL OTP CHECKER ====================

@app.route('/api/check_otp', methods=['POST'])
@login_required
def check_otp():
    data = request.json or {}
    target_number = str(data.get('number', '')).replace('+', '').strip()
    
    panels = [
        {"url": f"{API_BASE}/success_otp", "params": {"api_key": PANEL_TOKEN}},
        {"url": PANEL_2_URL, "params": {"api_key": PANEL_2_TOKEN}},
        {"url": PANEL_3_URL, "params": {"api_key": PANEL_3_TOKEN}}
    ]
    
    matched_otps = []
    
    try:
        for panel in panels:
            try:
                response = requests.get(panel["url"], params=panel["params"], timeout=6)
                if response.status_code == 200:
                    json_data = response.json()
                    if json_data.get("status") == "success" and "data" in json_data:
                        all_logs = json_data.get("data", [])
                        for log in all_logs:
                            log_num = str(log.get('number') or log.get('num') or log.get('range', '')).replace('+', '').strip()
                            if target_number in log_num or log_num in target_number:
                                matched_otps.append(log)
                        if matched_otps:
                            break
            except Exception:
                continue
        
        if matched_otps:
            user = User.query.filter_by(username=session['username']).first()
            if user:
                sys_settings = SystemSettings.query.first()
                current_rate = sys_settings.otp_rate if sys_settings else 0.50
                user.balance += current_rate
                user.total_otps += 1
                db.session.commit()
                
                # রিয়েল-টাইম সেশন ডাটা আপডেট
                session['user_balance'] = user.balance
                session['total_otps'] = user.total_otps
            return jsonify({"status": "success", "data": matched_otps})
            
        return jsonify({"status": "success", "data": []})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e), "data": []})

# ==================== THREE-PANEL MERGED CONSOLE STREAM ====================

@app.route('/api/console_stream')
@login_required
def console_stream():
    combined_data = []
    panels = [
        {"url": f"{API_BASE}/console", "params": {"api_key": PANEL_TOKEN}},
        {"url": PANEL_2_URL, "params": {"api_key": PANEL_2_TOKEN}},
        {"url": PANEL_3_URL, "params": {"api_key": PANEL_3_TOKEN}}
    ]
    for panel in panels:
        try:
            res = requests.get(panel["url"], params=panel["params"], timeout=5)
            if res.status_code == 200:
                json_res = res.json()
                if json_res.get("status") == "success":
                    combined_data.extend(json_res.get("data", []))
        except Exception:
            continue
    return jsonify({"status": "success", "data": combined_data})

# ==================== ADMIN CONTROL & BULK UPLOAD ====================

@app.route('/admin/add_bulk_numbers', methods=['POST'])
@admin_required
def add_bulk_numbers():
    raw_numbers = request.form.get('numbers', '').strip()
    number_range = request.form.get('range', '').strip()
    
    if not raw_numbers or not number_range:
        return redirect(url_for('admin_panel'))
        
    raw_clean = raw_numbers.replace('\r', '').replace(',', '\n')
    processed_list = list(set([num.strip().replace(" ", "") for num in raw_clean.split('\n') if num.strip()]))
    
    if not processed_list:
        return redirect(url_for('admin_panel'))
        
    try:
        existing_records = ManualNumber.query.filter(ManualNumber.number.in_(processed_list)).all()
        existing_numbers = set([rec.number for rec in existing_records])
        
        new_numbers_mappings = []
        for num in processed_list:
            if num not in existing_numbers:
                new_numbers_mappings.append({
                    "number": num,
                    "number_range": number_range,
                    "is_sold": False,
                    "created_at": datetime.utcnow()
                })
                
        if new_numbers_mappings:
            db.session.bulk_insert_mappings(ManualNumber, new_numbers_mappings)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e
    return redirect(url_for('admin_panel'))

@app.route('/admin/upload_number_file', methods=['POST'])
@admin_required
def upload_number_file():
    number_range = request.form.get('range', '').strip()
    file = request.files.get('file')
    
    if not number_range or not file or file.filename == '':
        return "রেঞ্জ এবং ফাইল দুটোই আবশ্যক!", 400
        
    if file and file.filename.endswith('.txt'):
        content = file.read().decode('utf-8')
        processed_list = list(set([num.strip().replace(" ", "") for num in content.replace('\r', '').split('\n') if num.strip()]))
        
        if not processed_list:
            return redirect(url_for('admin_panel'))
            
        try:
            existing_records = ManualNumber.query.filter(ManualNumber.number.in_(processed_list)).all()
            existing_numbers = set([rec.number for rec in existing_records])
            
            new_numbers_mappings = []
            for num in processed_list:
                if num not in existing_numbers:
                    new_numbers_mappings.append({
                        "number": num,
                        "number_range": number_range,
                        "is_sold": False,
                        "created_at": datetime.utcnow()
                    })
                    
            if new_numbers_mappings:
                db.session.bulk_insert_mappings(ManualNumber, new_numbers_mappings)
                db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise e
        return redirect(url_for('admin_panel'))
    else:
        return "শুধুমাত্র .txt ফাইল আপলোড করুন!", 400

@app.route('/admin/delete_numbers_by_range', methods=['POST'])
@admin_required
def delete_numbers_by_range():
    number_range = request.form.get('range', '').strip()
    if not number_range:
        return redirect(url_for('admin_panel'))
    try:
        ManualNumber.query.filter_by(number_range=number_range, is_sold=False).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_user', methods=['POST'])
@admin_required
def add_user():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    try:
        if User.query.filter_by(username=username).first():
            return jsonify({"status": "error", "message": "এই ইউজারনেম ইতিমধ্যে আছে!"})
        db.session.add(User(username=username, password=password))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_user/<int:user_id>')
@admin_required
def delete_user(user_id):
    try:
        user = User.query.get(user_id)
        if user and not user.is_admin:
            db.session.delete(user)
            db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('admin_panel'))

@app.route('/admin/update_rate', methods=['POST'])
@admin_required
def update_rate():
    try:
        settings = SystemSettings.query.first()
        if settings:
            settings.otp_rate = float(request.form.get('otp_rate', 0.50))
            db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('admin_panel'))

@app.route('/admin/modify_balance', methods=['POST'])
@admin_required
def modify_balance():
    try:
        user = User.query.get(int(request.form.get('user_id')))
        if user:
            user.balance += float(request.form.get('amount', 0))
            db.session.commit()
            # লাইভ সিঙ্ক করার জন্য সেশন আপডেট
            if session.get('username') == user.username:
                session['user_balance'] = user.balance
    except Exception:
        db.session.rollback()
    return redirect(url_for('admin_panel'))

@app.route('/admin/approve_withdraw/<int:req_id>')
@admin_required
def approve_withdraw(req_id):
    try:
        req = WithdrawRequest.query.get(req_id)
        if req:
            req.status = 'Approved'
            db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('admin_panel'))

@app.route('/api/withdraw', methods=['POST'])
@login_required
def user_withdraw():
    data = request.json or {}
    bkash_num = data.get('bkash_number')
    amount = float(data.get('amount', 0))
    
    try:
        user = User.query.filter_by(username=session['username']).first()
        if not user:
            return jsonify({"status": "error", "message": "ইউজার পাওয়া যায়নি!"})
            
        if amount < 20:
            return jsonify({"status": "error", "message": "সর্বনিম্ন ২০ টাকা উইথড্র করতে পারবেন!"})
        if user.balance < amount:
            return jsonify({"status": "error", "message": "আপনার অ্যাকাউন্টে পর্যাপ্ত ব্যালেন্স নেই!"})
            
        user.balance -= amount
        db.session.add(WithdrawRequest(username=user.username, amount=amount, bkash_number=bkash_num))
        db.session.commit()
        session['user_balance'] = user.balance  # সেশন ব্যালেন্স সিঙ্ক
        return jsonify({"status": "success", "message": "উইথড্র রিকোয়েস্ট অ্যাডমিন প্যানেলে পাঠানো হয়েছে! ✅"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    # লোকালে রান করার জন্য
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
