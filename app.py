import os
from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "zerotrust_secret_key")

# Render ও Supabase এর জন্য কানেকশন পুল অপ্টিমাইজেশন
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 25,
    'max_overflow': 15,
    'pool_recycle': 280,
    'pool_pre_ping': True
}

db = SQLAlchemy(app)

# ডাটাবেস স্কিমা
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

@app.context_processor
def inject_global_vars():
    if session.get('logged_in'):
        user = User.query.filter_by(username=session.get('username')).first()
        if user:
            return dict(global_balance=user.balance)
    return dict(global_balance=0.00)

@app.route('/')
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
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
        # এখানে এপিআই থেকে নম্বর নেওয়ার আসল লজিক বসবে, আপাতত ডেমো দেওয়া হলো
        allocated_number = "+88018XXXXXXXX"
        
        if user and user.balance >= 10.0:
            user.balance -= 10.0
            new_act = Activation(username=user.username, number=allocated_number, service=service, status="Waiting OTP")
            db.session.add(new_act)
            db.session.commit()
            return render_template('get_number.html', success=f"নম্বর রেডি: {allocated_number}")
        else:
            return render_template('get_number.html', error="পর্যাপ্ত ব্যালেন্স নেই বা ইউজার পাওয়া যায়নি!")
            
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
            return render_template('withdraw_page.html', success=f"{amount} টাকা উইথড্র রিকোয়েস্ট সাবমিট হয়েছে।")
        else:
            return render_template('withdraw_page.html', error="ব্যালেন্স কম অথবা ভুল অ্যামাউন্ট দিয়েছেন।")
            
    return render_template('withdraw_page.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000)
