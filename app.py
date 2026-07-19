import time
import requests
import threading
from flask import Flask, jsonify, request, render_template, session, redirect, url_for

app = Flask(__name__)
app.secret_key = 'super-secret-key-for-easy-sms-panel' # সেশন সিকিউরিটির জন্য কি

# --- ডাটাবেজ কনফিগারেশন (Supabase) ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://postgres.satwojizxqoivvprimxy:easy-sms-panel.onrender.com@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres?sslmode=require'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy(app)

# --- ডাটাবেজ মডেলসমূহ ---
class UploadedNumber(db.Model):
    __tablename__ = 'uploaded_numbers'
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='available') # available, sold

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    balance = db.Column(db.Float, default=0.00)

# --- গ্লোবাল মেমোরি ক্যাশ (৫ মিনিটের ওটিপি লাইভ পুল) ---
LIVE_OTP_POOL = []
POOL_LOCK = threading.Lock()

# ৩টি নির্দিষ্ট প্যানেলের কনফিগারেশন
PROVIDERS = [
    {
        "type": "mino",
        "url": "https://mino-sms-panel.xyz/success_otp",
        "api_key": "mino_live_d90eba7078a418fa056c2c16f7facbba"
    },
    {
        "type": "crapi",
        "url": "http://147.135.212.197/crapi/had/viewstats",
        "api_key": "Qk5TQUZBUzSHg3h9ZFKWSGqEa3SDcnZjh4aUf0dxV2FEUo9TZGFyVg=="
    },
    {
        "type": "crapi",
        "url": "http://147.135.212.197/crapi/st/viewstats",
        "api_key": "Qk9QQkZBUzRriFaEcmeNeYmMmWB2d4thfVCEcl9VgIRWc41SZ2Fsiw=="
    }
]

def parse_otp_data(provider_type, raw_json):
    extracted = []
    current_ts = time.time()
    try:
        if provider_type == "mino":
            items = raw_json if isinstance(raw_json, list) else raw_json.get('data', [])
            for item in items:
                extracted.append({
                    "range": item.get("number") or item.get("phone"),
                    "service": item.get("app") or item.get("service") or "SMS",
                    "message": item.get("sms") or item.get("message") or item.get("otp"),
                    "country": "BD",
                    "timestamp": current_ts
                })
        
        elif provider_type == "crapi":
            items = raw_json if isinstance(raw_json, list) else raw_json.get('logs', [])
            for item in items:
                extracted.append({
                    "range": item.get("phone") or item.get("number"),
                    "service": item.get("service") or item.get("app_name") or "CRAPI",
                    "message": item.get("message") or item.get("text") or item.get("otp"),
                    "country": item.get("country") or "Global",
                    "timestamp": current_ts
                })
    except Exception as e:
        print(f"Parsing error for {provider_type}: {e}")
    return extracted

def bg_otp_fetcher():
    global LIVE_OTP_POOL
    while True:
        new_otps = []
        for provider in PROVIDERS:
            try:
                headers = {
                    "Authorization": f"Bearer {provider['api_key']}",
                    "API-KEY": provider['api_key'],
                    "Content-Type": "application/json"
                }
                response = requests.get(provider['url'], headers=headers, timeout=4)
                if response.status_code == 200:
                    parsed = parse_otp_data(provider['type'], response.json())
                    new_otps.extend(parsed)
            except Exception:
                pass
        
        with POOL_LOCK:
            cutoff_time = time.time() - 300
            updated_pool = [otp for otp in LIVE_OTP_POOL if otp['timestamp'] > cutoff_time]
            
            existing_msgs = {o['message'] for o in updated_pool}
            for o in new_otps:
                if o['message'] and o['message'] not in existing_msgs:
                    updated_pool.insert(0, o)
                    existing_msgs.add(o['message'])
            
            LIVE_OTP_POOL = updated_pool
            
        time.sleep(5)

# ব্যাকগ্রাউন্ড থ্রেড অটো-স্টার্ট
fetch_thread = threading.Thread(target=bg_otp_fetcher, daemon=True)
fetch_thread.start()

# --- রাউটস ও এপিআই এন্ডপয়েন্টসমূহ ---

@app.route('/')
def home():
    """ড্যাশবোর্ড রাউট: chart_labels ও user_data সংক্রান্ত এরর হ্যান্ডেল করা হয়েছে"""
    user_id = session.get('user_id')
    user_data = None
    
    if user_id:
        try:
            user_data = User.query.get(user_id)
        except Exception:
            pass

    # সেশন বা ডাটাবেজ রেকর্ড না থাকলে ডামি ডেটা দিয়ে ক্র্যাশ প্রতিরোধ
    if not user_data:
        user_data = {
            "username": "Guest User",
            "balance": 0.00
        }
        
    # ড্যাশবোর্ডের গ্রাফের জন্য ডিফল্ট লেবেল পাঠানো হচ্ছে যাতে tojson এনকোডার ক্র্যাশ না করে
    default_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        
    return render_template('dashboard.html', user_data=user_data, chart_labels=default_labels)

@app.route('/console')
def console_page():
    return render_template('console.html')

@app.route('/api/console_stream', methods=['GET'])
def console_stream():
    with POOL_LOCK:
        return jsonify({
            "status": "success",
            "data": LIVE_OTP_POOL
        })

@app.route('/api/buy_number', methods=['POST'])
def buy_number():
    req_data = request.get_json() or {}
    range_code = str(req_data.get("rid", "")).strip()

    if not range_code:
        return jsonify({"status": "error", "message": "Range code is required"}), 400

    # লজিক ১: ৫ বা তার বেশি ডিজিটের বড় রেঞ্জ (যেমন: 22467XXX) -> Mino Panel
    if len(range_code) >= 5:
        try:
            mino_url = "https://mino-sms-panel.xyz/api/get_number" 
            headers = {"Authorization": "Bearer mino_live_d90eba7078a418fa056c2c16f7facbba"}
            
            response = requests.post(mino_url, json={"range": range_code}, headers=headers, timeout=5)
            if response.status_code == 200:
                res_json = response.json()
                return jsonify({
                    "status": "success",
                    "source": "mino_panel",
                    "number": res_json.get("number"),
                    "order_id": res_json.get("order_id")
                })
        except Exception as e:
            return jsonify({"status": "error", "message": f"Mino Panel error: {str(e)}"}), 500

    # লজিক ২: ২, ৩ বা ৪ ডিজিটের ছোট রেঞ্জ (যেমন: 251) -> Local Supabase DB
    elif len(range_code) in [2, 3, 4]:
        try:
            number_record = UploadedNumber.query.filter(
                UploadedNumber.status == 'available',
                UploadedNumber.number.like(f"{range_code}%")
            ).first()

            if number_record:
                number_record.status = 'sold'
                db.session.commit()
                
                return jsonify({
                    "status": "success",
                    "source": "local_database",
                    "number": number_record.number,
                    "order_id": f"DB-{number_record.id}"
                })
            else:
                return jsonify({"status": "error", "message": "এই রেঞ্জের কোনো নাম্বার ডাটাবেজে খালি নেই!"}), 404
        except Exception as e:
            return jsonify({"status": "error", "message": f"Database Error: {str(e)}"}), 500

    else:
        return jsonify({"status": "error", "message": "অকার্যকর রেঞ্জ ফরম্যাট!"}), 400

@app.route('/api/check_otp', methods=['POST'])
def check_otp():
    req_data = request.get_json() or {}
    target_number = req_data.get("number")
    
    if not target_number:
        return jsonify({"status": "error", "message": "Missing number"}), 400
        
    target_clean = "".join(filter(str.isdigit, str(target_number)))
    
    with POOL_LOCK:
        for otp in LIVE_OTP_POOL:
            otp_num_clean = "".join(filter(str.isdigit, str(otp['range'])))
            if target_clean in otp_num_clean or otp_num_clean in target_clean:
                return jsonify({
                    "status": "success",
                    "otp": otp['message'],
                    "service": otp['service']
                })
                
    return jsonify({"status": "pending", "message": "Waiting for OTP..."})

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
