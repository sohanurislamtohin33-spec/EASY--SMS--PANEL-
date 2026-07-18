import os
from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkeyformyotppanel")

# ১০০০ ইউজারের ট্রাফিকের জন্য কানেকশন পুল অপ্টিমাইজেশন
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 20,
    'max_overflow': 10,
    'pool_recycle': 280,
    'pool_pre_ping': True
}

db = SQLAlchemy(app)

# গ্লোবাল ব্যালেন্স কনটেক্সট প্রসেসর
@app.context_processor
def inject_global_vars():
    if session.get('logged_in'):
        # এখানে আপনার ডাটাবেস থেকে ব্যালেন্স নেওয়ার লজিক থাকবে
        return dict(global_balance=150.00)
    return dict(global_balance=0.00)

@app.route('/')
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # সহজ ডেমো লগইন চেক (আপনার অরিজিনাল ডাটাবেস চেকিং কোড এখানে বসাবেন)
        if username == "admin" and password == "admin":
            session['logged_in'] = True
            session['username'] = username
            session['is_admin'] = True
            return redirect(url_for('dashboard'))
        else:
            session['logged_in'] = True
            session['username'] = username
            session['is_admin'] = False
            return redirect(url_for('dashboard'))
            
    return render_template('login.html')

@app.route('/get_number_page')
def get_number_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('get_number.html')

@app.route('/console_page')
def console_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('console.html')

@app.route('/withdraw_page')
def withdraw_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('withdraw_page.html')

@app.route('/admin/panel')
def admin_panel():
    if not session.get('logged_in') or not session.get('is_admin'):
        return redirect(url_for('dashboard'))
    return render_template('admin_dashboard.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
