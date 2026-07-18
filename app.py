from flask import Flask, render_template, request, jsonify, redirect, session, url_for
import requests
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import traceback
import time
from threading import Thread

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

# ==================== GLOBAL CENTRAL OTP POOL ====================
# প্রতি ৫ সেকেন্ডে ১০ প্যানেল থেকে আসা সমস্ত ওটিপি এবং কনসোল স্ট্রিম ডেটা এখানে জমা হবে।
CENTRAL_OTP_POOL = {} 
PROCESSED_ORDERS = set()  # একই ওটিপি দিয়ে যেন বারবার ব্যালেন্স অ্যাড না হয় (Bug Fix)

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

# ১০ টি প্যানেল ডাইনামিক কনফিগারেশন মডেল
class ProviderPanel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)        # যেমন: Mino 1, Other 2
    panel_type = db.Column(db.String(20), nullable=False)  # 'mino' অথবা 'other'
    api_url = db.Column(db.String(500), nullable=True)     # প্যানেলের বেস ইউআরএল বা ফুল ওটিপি এপিআই এন্ডপয়েন্ট
    api_token = db.Column(db.String(500), nullable=True)   # এপিআই কী/টোকেন
    number_range = db.Column(db.String(50), nullable=False, unique=True) # যেমন: '23274', '2556'
    is_active = db.Column(db.Boolean, default=True)

# অন্যান্য প্যানেলগুলোর জন্য ফাইল আপলোড করা নাম্বারের মডেল
class UploadedNumber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    panel_id = db.Column(db.Integer, db.ForeignKey('provider_panel.id'))
    phone_number = db.Column(db.String(20), nullable=False, unique=True)
    status = db.Column(db.String(20), default='available') # available, sold

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

@app.context_processor
def inject_user_balance():
    if 'logged_in' in session:
        user = User.query.filter_by(username=session['username']).first()
        if user:
            return dict(global_balance=user.balance)
    return dict(global_balance=0.00)

# ==================== CENTRALIZED BACKGROUND OTP POLLING (5 SECONDS) ====================

def fetch_otps_from_all_panels():
    """ব্যাকগ্রাউন্ড টাস্ক যা প্রতি ৫ সেকেন্ড পর পর সকল প্যানেল থেকে ওটিপি ডেটা এনে পুলে সিঙ্ক করবে"""
    while True:
        with app.app_context():
            try:
                active_panels = ProviderPanel.query.filter_by(is_active=True).all()
                for panel in active_panels:
                    if panel.api_url and panel.api_token:
                        # ওটিপি আনার এপিআই রিকোয়েস্ট (আপনার আগের স্ট্রাকচার অনুযায়ী /success_otp এন্ডপয়েন্ট)
                        url = f"{panel.api_url.rstrip('/')}/success_otp"
                        params = {"api_key": panel.api_token}
                        
                        try:
                            response = requests.get(url, params=params, timeout=4)
                            if response.status_code == 200:
                                json_data = response.json()
                                if json_data.get("status") == "success" and "data" in json_data:
                                    all_logs = json_data.get("data", [])
                                    for log in all_logs:
                                        num = str(log.get('number') or log.get('num') or log.get('range', '')).replace('+', '').strip()
                                        otp_code = log.get('otp')
                                        
                                        if num and otp_code:
                                            # সেন্ট্রাল পুলে ওটিপি পুশ করা
                                            CENTRAL_OTP_POOL[num] = {
                                                'otp': otp_code,
                                                'raw_data': log,
                                                'timestamp': time.time()
                                            }
                        except Exception as panel_err:
                            pass # কোনো প্যানেল অফলাইন বা রেসপন্স না দিলে স্কিপ করবে
            except Exception as e:
                print("Global OTP Polling Error:", str(e))
        time.sleep(5)

# ব্যাকগ্রাউন্ড প্রসেস চালু করা
polling_thread = Thread(target=fetch_otps_from_all_panels, daemon=True)
polling_thread.start()

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
        "yesterday_otps": 0, "today_numbers": 0, "today_success": 0, "yesterday_numbers": 0, "yesterday_success": 0
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
    return render_template('withdraw_page.html', balance=user.balance if user else 0.00)

@app.route('/admin/panel')
@admin_required
def admin_panel():
    users = User.query.all()
    withdraws = WithdrawRequest.query.order_by(WithdrawRequest.id.desc()).all()
    settings = SystemSettings.query.first()
    panels = ProviderPanel.query.all()
    return render_template('admin_dashboard.html', users=users, withdraws=withdraws, settings=settings, panels=panels)

# ==================== DYNAMIC MULTI-PANEL ROUTING API ====================

@app.route('/api/buy_number', methods=['POST'])
@login_required
def buy_number():
    data = request.json
    rid = data.get('rid') # ফ্রন্টএন্ড থেকে আসা রেঞ্জ ইনপুট (যেমন: 23274 বা 2556)
    
    if not rid:
        return jsonify({"status": "error", "message": "রেঞ্জ প্রদান করা বাধ্যতামূলক!"})
        
    requested_range = str(rid).strip()
    
    # ইনপুট করা রেঞ্জের সাথে ডাটাবেজের প্যানেল রেঞ্জ ম্যাচ করা
    panel = ProviderPanel.query.filter_by(number_range=requested_range, is_active=True).first()
    if not panel:
        return jsonify({"status": "error", "message": "এই রেঞ্জের কোনো প্যানেল অ্যাক্টিভ নেই!"})
        
    # ১. মিনো প্যানেল টাইপ হলে (API ভিত্তিক)
    if panel.panel_type == 'mino':
        url = f"{panel.api_url.rstrip('/')}/getnumber"
        params = {"api_key": panel.api_token, "rid": requested_range, "national_format": 0, "remove_plus": 0}
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return jsonify(response.json())
            return jsonify({"status": "error", "message": f"প্যানেল সার্ভার রেসপন্স করেনি: {response.status_code}"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})

    # ২. অন্যান্য প্যানেল টাইপ হলে (ডাটাবেজ ফাইল আপলোড ভিত্তিক এবং ২-৪ ডিজিট সাপোর্ট)
    elif panel.panel_type == 'other':
        # প্রদত্ত রেঞ্জ স্টার্ট বিশিষ্ট যেকোনো এভেইলেবল নাম্বার খোঁজা হচ্ছে
        db_number = UploadedNumber.query.filter(
            UploadedNumber.panel_id == panel.id,
            UploadedNumber.phone_number.like(f"{requested_range}%"),
            UploadedNumber.status == 'available'
        ).first()
        
        if db_number:
            db_number.status = 'sold'
            db.session.commit()
            # মিনো প্যানেলের জেসন ফরম্যাট অনুকরণ করে রিটার্ন করা হচ্ছে
            return jsonify({
                "status": "success",
                "number": db_number.phone_number,
                "id": f"db_{db_number.id}"
            })
        else:
            return jsonify({"status": "error", "message": "ডাটাবেজে এই রেঞ্জের কোনো নাম্বার খালি নেই!"})

# ==================== CENTRALIZED OTP CHECK API ====================

@app.route('/api/check_otp', methods=['POST'])
@login_required
def check_otp():
    data = request.json
    target_number = str(data.get('number')).replace('+', '').strip()
    
    # ১. সেন্ট্রাল পুল (যেখানে প্রতি ৫ সেকেন্ডে ওটিপি জমা হচ্ছে) সেখানে নাম্বার চেক করা
    matched_otps = []
    for num, info in list(CENTRAL_OTP_POOL.items()):
        if target_number in num or num in target_number:
            matched_otps.append(info['raw_data'])
            
            # ২. ডাবল-ব্যালেন্স অ্যাড হওয়া প্রতিরোধ লজিক (Bug Fix)
            order_key = f"{session['username']}_{target_number}_{info['otp']}"
            if order_key not in PROCESSED_ORDERS:
                user = User.query.filter_by(username=session['username']).first()
                if user:
                    current_rate = SystemSettings.query.first().otp_rate
                    user.balance += current_rate
                    user.total_otps += 1
                    db.session.commit()
                    PROCESSED_ORDERS.add(order_key)
            break # ওটিপি পেয়ে গেলে লুপ থেকে বের হওয়া
            
    if matched_otps:
        return jsonify({"status": "success", "data": matched_otps})
        
    return jsonify({"status": "success", "data": []})

# ==================== LIVE CONSOLE STREAMING (5 SECONDS DATA) ====================

@app.route('/api/console_stream')
@login_required
def console_stream():
    current_time = time.time()
    live_feeds = []
    
    # ৫ সেকেন্ড পর পর সেন্ট্রাল পুলে জমা হওয়া সমস্ত ওটিপি কনসোলে রেন্ডার করা হবে
    for num, info in list(CENTRAL_OTP_POOL.items()):
        # ১৫ মিনিটের পুরোনো ওটিপি ক্যাশ মেমোরি থেকে ক্লিন করা
        if current_time - info['timestamp'] > 900:
            CENTRAL_OTP_POOL.pop(num, None)
            continue
            
        live_feeds.append(info['raw_data'])
        
    return jsonify({"status": "success", "data": live_feeds})

# ==================== ADMIN CONTROL API ROUTES ====================

# ডাইনামিক প্যানেল অ্যাড এবং এপিআই/টোকেন/রেঞ্জ কনফিগারেশন চেঞ্জ রুট
@app.route('/admin/manage_panel', methods=['POST'])
@admin_required
def manage_panel():
    panel_id = request.form.get('panel_id')
    name = request.form.get('name').strip()
    panel_type = request.form.get('panel_type')
    api_url = request.form.get('api_url').strip()
    api_token = request.form.get('api_token').strip()
    number_range = request.form.get('number_range').strip()
    
    if panel_id:
        panel = ProviderPanel.query.get(panel_id)
        if panel:
            panel.name = name
            panel.panel_type = panel_type
            panel.api_url = api_url
            panel.api_token = api_token
            panel.number_range = number_range
    else:
        if ProviderPanel.query.filter_by(number_range=number_range).first():
            return "এই রেঞ্জটি ইতিমধ্যে অন্য প্যানেলে ব্যবহৃত হয়েছে!", 400
        new_panel = ProviderPanel(name=name, panel_type=panel_type, api_url=api_url, api_token=api_token, number_range=number_range)
        db.session.add(new_panel)
        
    db.session.commit()
    return redirect(url_for('admin_panel'))

# ফাইল আপলোডের মাধ্যমে অন্যান্য প্যানেলের ডাটাবেজে নাম্বার পুশ করার রুট
@app.route('/admin/upload_numbers', methods=['POST'])
@admin_required
def upload_numbers():
    panel_id = request.form.get('panel_id')
    file = request.files.get('number_file')
    
    if not file or not panel_id:
        return "ফাইল এবং প্যানেল আইডি নির্বাচন করা বাধ্যতামূলক!", 400
        
    content = file.read().decode('utf-8')
    numbers = [num.strip() for num in content.split('\n') if num.strip()]
    
    added_count = 0
    for num in numbers:
        clean_num = num.replace('+', '').strip()
        exists = UploadedNumber.query.filter_by(phone_number=clean_num).first()
        if not exists:
            new_num = UploadedNumber(panel_id=panel_id, phone_number=clean_num, status='available')
            db.session.add(new_num)
            added_count += 1
            
    db.session.commit()
    return redirect(url_for('admin_panel'))

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

if __name__ == '__main__':
    app.run(debug=True)
