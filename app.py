import os
from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# Render-এ SECRET_KEY না থাকলে এটি একটি ডিফল্ট কী ব্যবহার করবে
app.secret_key = os.getenv("SECRET_KEY", "zerotrust_secret_key_1000_users")

# Render ও Supabase/PostgreSQL-এর জন্য কানেকশন পুল অপ্টিমাইজেশন
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 25,          # একসাথে ২৫টি স্থায়ী কানেকশন খোলা থাকবে
    'max_overflow': 15,       # পিক আওয়ারে আরও ১৫টি কানেকশন ওভারফ্লো নিতে পারবে
    'pool_recycle': 280,      # কানেকশন ড্রপ হওয়া আটকাতে রি-সাইকেল টাইম
    'pool_pre_ping': True     # প্রতি রিকোয়েস্টে কানেকশন লাইভ আছে কি না চেক করবে
}

db = SQLAlchemy(app)

# ==================== ডাটাবেস মডেলসমূহ ====================

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    balance = db.Column(db.Float, default=0.0)
    is_admin = db.Column(db.Boolean, default=False)

class Activation(db.Model):
    __tablename__ = 'activations'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    number = db.Column(db.String(20), nullable=False)
    service = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default="Waiting OTP")
    otp = db.Column(db.String(20), nullable=True)

# ==================== গ্লোবাল কনটেক্সট প্রসেসর ====================

@app.context_processor
def inject_global_vars():
    """ইউজার লগইন থাকলে তার লাইভ ব্যালেন্স navbar বা base.html-এ দেখানোর জন্য"""
    if session.get('logged_in'):
        user = User.query.filter_by(username=session.get('username')).first()
        if user:
            return dict(global_balance=user.balance)
    return dict(global_balance=0.00)

# ==================== ইউজার রাউটসমূহ ====================

@app.route('/')
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    # ইউজারের সাম্প্রতিক ১০টি ওটিপি হিস্ট্রি ড্যাশবোর্ডে দেখানোর জন্য
    history = Activation.query.filter_by(username=session.get('username')).order_by(Activation.id.desc()).limit(10).all()
    return render_template('dashboard.html', history=history)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session['logged_in'] = True
            session['username'] = username
            session['is_admin'] = user.is_admin
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="ইউজারনেম বা পাসওয়ার্ড ভুল!")
    return render_template('login.html')

@app.route('/get_number_page', methods=['GET', 'POST'])
def get_number_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        service = request.form.get('service')
        server = request.form.get('server')
        
        user = User.query.filter_by(username=session.get('username')).first()
        
        # ওটিপি এপিআই কল করার ডেমো রেসপন্স (এখানে আপনার মূল API ইন্টিগ্রেশন বসবে)
        allocated_number = "+88018XXXXXXXX"
        otp_cost = 10.0  # একটি ওটিপির খরচ ১০ টাকা ধরে
        
        if user and user.balance >= otp_cost:
            user.balance -= otp_cost
            new_act = Activation(username=user.username, number=allocated_number, service=service, status="Waiting OTP")
            db.session.add(new_act)
            db.session.commit()
            return render_template('get_number.html', success=f"নম্বর রেডি: {allocated_number}")
        else:
            return render_template('get_number.html', error="পর্যাপ্ত ব্যালেন্স নেই!")
            
    return render_template('get_number.html')

@app.route('/console_page')
def console_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('console.html')

@app.route('/withdraw_page', methods=['GET', 'POST'])
def withdraw_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        method = request.form.get('method')
        amount = float(request.form.get('amount', 0))
        account_no = request.form.get('account')
        
        user = User.query.filter_by(username=session.get('username')).first()
        if user and user.balance >= amount and amount >= 100:
            user.balance -= amount
            db.session.commit()
            return render_template('withdraw_page.html', success=f"{amount} BDT উইথড্র রিকোয়েস্ট সফল হয়েছে।")
        else:
            return render_template('withdraw_page.html', error="ব্যালেন্স কম অথবা ভুল অ্যামাউন্ট দিয়েছেন (সর্বনিম্ন ১০০ BDT)।")
            
    return render_template('withdraw_page.html')

# ==================== অ্যাডমিন রাউট ====================

@app.route('/admin/panel', methods=['GET', 'POST'])
def admin_panel():
    # ইউজার লগইন না থাকলে বা অ্যাডমিন না হলে ড্যাশবোর্ডে পাঠিয়ে দেবে
    if not session.get('logged_in') or not session.get('is_admin'):
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        target_username = request.form.get('target_username')
        amount = float(request.form.get('amount', 0))
        action_type = request.form.get('action_type')
        
        user = User.query.filter_by(username=target_username).first()
        if user:
            if action_type == 'add':
                user.balance += amount
                msg = f"{target_username}-এর অ্যাকাউন্টে {amount} টাকা যোগ করা হয়েছে।"
            elif action_type == 'set':
                user.balance = amount
                msg = f"{target_username}-এর ব্যালেন্স {amount} টাকা নির্দিষ্ট করা হয়েছে।"
            db.session.commit()
            return render_template('admin_dashboard.html', success=msg)
        else:
            return render_template('admin_dashboard.html', error="এই ইউজারনেমটি ডাটাবেসে পাওয়া যায়নি!")
            
    return render_template('admin_dashboard.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ==================== অ্যাপ্লিকেশন স্টার্টার ====================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # টেবিলগুলো ডাটাবেসে না থাকলে অটোমেটিক তৈরি হবে
    app.run(host='0.0.0.0', port=5000)
