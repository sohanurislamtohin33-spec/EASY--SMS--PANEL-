import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import redis
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(24))

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_size": 20,
    "max_overflow": 10,
    "pool_timeout": 30,
    "pool_recycle": 1800
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    balance = db.Column(db.Float, default=0.0)
    api_key = db.Column(db.String(100), unique=True, nullable=False)

class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    otp_rate = db.Column(db.Float, default=10.0)
    panels_json = db.Column(db.Text, default="[]")

class ManualNumber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False)
    operator = db.Column(db.String(20), nullable=False)
    is_sold = db.Column(db.Boolean, default=False)

class WithdrawRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    bkash_number = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default="Pending")

# Auth Middleware
def login_required(f):
    def wrapper(*args, **kwargs):
        if 'username' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password')
        if username == "admin" and password == "adminpassword":
            session['username'] = 'admin'
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['username'] = user.username
            session['is_admin'] = False
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Invalid username or password")
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.filter_by(username=session['username']).first()
    return render_template('dashboard.html', balance=user.balance, api_key=user.api_key)

@app.route('/get_number')
@login_required
def get_number_page():
    user = User.query.filter_by(username=session['username']).first()
    return render_template('get_number.html', api_key=user.api_key)

@app.route('/console')
@login_required
def console_page():
    return render_template('console.html')

@app.route('/withdraw_page')
@login_required
def withdraw_page():
    return render_template('withdraw_page.html')

@app.route('/withdraw', methods=['POST'])
@login_required
def user_withdraw():
    amount = float(request.form.get('amount', 0))
    bkash = request.form.get('bkash').strip()
    user = User.query.filter_by(username=session['username']).first()
    if user and user.balance >= amount > 0:
        user.balance -= amount
        db.session.add(WithdrawRequest(username=user.username, amount=amount, bkash_number=bkash))
        db.session.commit()
    return redirect(url_for('dashboard'))

# Admin Control Actions
@app.route('/admin')
@login_required
def admin_dashboard():
    if not session.get('is_admin'): return redirect(url_for('login'))
    return render_template('admin_dashboard.html', users=User.query.all(), stock_count=ManualNumber.query.filter_by(is_sold=False).count())

@app.route('/admin/create_user', methods=['POST'])
@login_required
def admin_create_user():
    if not session.get('is_admin'): return redirect(url_for('login'))
    uname = request.form.get('new_username').strip()
    pwd = request.form.get('new_password')
    if uname and not User.query.filter_by(username=uname).first():
        db.session.add(User(username=uname, password=generate_password_hash(pwd), api_key=secrets.token_hex(16)))
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/update_balance', methods=['POST'])
@login_required
def admin_update_balance():
    if not session.get('is_admin'): return redirect(url_for('login'))
    uname = request.form.get('target_username').strip()
    amount = float(request.form.get('amount', 0))
    user = User.query.filter_by(username=uname).first()
    if user:
        user.balance += amount
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/upload_numbers', methods=['POST'])
@login_required
def admin_upload_numbers():
    if not session.get('is_admin'): return redirect(url_for('login'))
    operator = request.form.get('operator')
    file = request.files.get('file')
    if file:
        content = file.read().decode('utf-8')
        for line in content.splitlines():
            num = line.strip()
            if num and not ManualNumber.query.filter_by(number=num).first():
                db.session.add(ManualNumber(number=num, operator=operator))
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

# High Speed Core API Endpoints
@app.route('/api/v1/buy_number', methods=['POST'])
def buy_number():
    data = request.json or {}
    user = User.query.filter_by(api_key=data.get('api_key')).first()
    settings = SystemSettings.query.first()
    rate = settings.otp_rate if settings else 10.0
    if not user or user.balance < rate:
        return jsonify({"status": "error", "message": "Insufficient balance"}), 400
    num_obj = ManualNumber.query.filter(ManualNumber.number.like(f"{data.get('range')}%"), ManualNumber.is_sold == False).first()
    if not num_obj:
        return jsonify({"status": "error", "message": "Stock empty"}), 404
    num_obj.is_sold = True
    user.balance -= rate
    db.session.commit()
    r.setex(f"track:{num_obj.number}", 300, "waiting")
    return jsonify({"status": "success", "number": num_obj.number, "current_balance": user.balance})

@app.route('/api/check_otp', methods=['POST'])
def check_otp():
    number = (request.json or {}).get('number')
    otp_data = r.get(f"otp:{number}")
    if otp_data: return jsonify({"status": "success", "data": [{"otp": otp_data}]})
    if not r.get(f"track:{number}"): return jsonify({"status": "expired"})
    return jsonify({"status": "success", "data": []})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not SystemSettings.query.first():
            db.session.add(SystemSettings())
            db.session.commit()
    app.run(host='0.0.0.0', port=5000, debug=False)
