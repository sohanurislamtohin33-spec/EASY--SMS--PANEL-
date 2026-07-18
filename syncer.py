import time
import requests
import redis
import json
from psycopg2.pool import SimpleConnectionPool
import os
from dotenv import load_dotenv

load_dotenv()

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Supabase এর সাথে থ্রেড-সেফ কানেকশন পুল
db_url = os.getenv("DATABASE_URL").replace("postgresql+psycopg2://", "postgres://")
pool = SimpleConnectionPool(1, 10, dsn=db_url)

def fetch_active_panels():
    conn = pool.getconn()
    cur = conn.cursor()
    cur.execute("SELECT panels_json FROM system_settings LIMIT 1;")
    row = cur.fetchone()
    cur.close()
    pool.putconn(conn)
    return json.loads(row[0]) if row and row[0] else []

def main_sync_loop():
    print("🚀 Background OTP Syncer actively listening on Redis queue...")
    while True:
        try:
            active_keys = r.keys("track:*")
            if not active_keys:
                time.sleep(2)
                continue
                
            panels = fetch_active_panels()
            
            for key in active_keys:
                number = key.split(":")[1]
                
                # এখানে আপনার ১০টি থার্ড পার্টি ওটিপি প্রোভাইডারের এপিআই লুপ সেট করতে পারবেন
                for panel in panels:
                    # উদাহরণ:
                    # otp = check_external_api(panel, number)
                    # if otp:
                    #     r.setex(f"otp:{number}", 120, otp)
                    #     r.delete(f"track:{number}")
                    pass
                    
            time.sleep(1)
        except Exception as e:
            print(f"Error in syncer engine: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main_sync_loop()
