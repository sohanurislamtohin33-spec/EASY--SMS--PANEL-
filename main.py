import requests
import time
import asyncio
import re
from datetime import datetime
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

# ------------------ সেটিংস ------------------
API_URL = "http://147.135.212.197/crapi/st/viewstats"
TOKEN = "RFdUREJBUzR9T4dVc49ndmFra1NYV5CIhpGVcnaOYmqHhJZXfYGJSQ=="
params = {"token": TOKEN, "records": ""}

TELEGRAM_BOT_TOKEN = "8705619806:AAEAZiddvEkpAbNHJzo6mheN6RS0MeZDwCQ"
TELEGRAM_GROUP_ID = -1003909406425

bot = Bot(token=TELEGRAM_BOT_TOKEN)

def fetch_sms():
    try:
        response = requests.get(API_URL, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"❌ API fetch failed: {e}")
        return []

def parse_timestamp(ts_str):
    try:
        return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except:
        return None

async def main():
    last_seen_time = None
    print("🚀 OTP Auto Forwarder Full Version Started...")

    while True:
        entries = fetch_sms()
        if not entries:
            await asyncio.sleep(30)
            continue

        new_entries = []
        if last_seen_time is None:
            # প্রথমবার চালু হলে লেটেস্ট ৫টি মেসেজ দেখাবে
            new_entries = entries[:5]
            if new_entries:
                last_seen_time = parse_timestamp(new_entries[0][3])
        else:
            for entry in entries:
                ts = parse_timestamp(entry[3])
                if ts and ts > last_seen_time:
                    new_entries.append(entry)

        if new_entries:
            latest_ts = parse_timestamp(new_entries[0][3])
            if latest_ts:
                last_seen_time = latest_ts
            print(f"🔥 Found {len(new_entries)} new OTP(s)")

        for entry in new_entries[::-1]:
            app       = entry[0].strip()
            phone     = entry[1].strip()
            full_msg  = entry[2].strip()
            timestamp = entry[3]

            # ==========================================
            # 🛡️ উন্নত ওটিপি ফিল্টার লজিক (PRO)
            # ==========================================
            otp = "N/A"
            
            # ১. হোয়াটসঅ্যাপের হাইফেন যুক্ত কোড (যেমন: 385-872)
            ws_match = re.search(r'(\d{3}-\d{3})', full_msg)
            
            # ২. ৪ থেকে ৮ ডিজিটের শুধু সংখ্যা (যেমন ইমো: 4336)
            num_match = re.search(r'\b(\d{4,8})\b', full_msg)
            
            # ৩. আলফানিউমেরিক কোড (ইমো স্পেশাল - যেমন: 3013nDO)
            # এটি 'WhatsApp' বা 'dengan' এর মতো শব্দগুলোকে বাদ দিবে
            alpha_match = re.search(r'\b([A-Z0-9]{4,10})\b', full_msg, re.IGNORECASE)

            if ws_match:
                otp = ws_match.group(1)
            elif num_match:
                otp = num_match.group(1)
            elif alpha_match:
                candidate = alpha_match.group(1)
                bad_words = ['whatsapp', 'dengan', 'kode', 'anda', 'akun', 'untuk', 'message']
                if candidate.lower() not in bad_words:
                    otp = candidate
            # ==========================================

            masked_phone = phone[:5] + "**" + phone[-5:] if len(phone) >= 10 else phone
            
            text = (
                f"<b>✉️ New {app} OTP Received</b>\n\n"
                f"🕒 <b>Time:</b> <code>{timestamp}</code>\n"
                f"📱 <b>Service:</b> <code>{app}</code>\n"
                f"📞 <b>Number:</b> <code>{masked_phone}</code>\n"
                f"🔑 <b>OTP:</b> <code>{otp}</code>\n\n"
                f"📝 <b>Full Message:</b>\n<i>{full_msg}</i>\n"
                f"──────────────────────────────"
            )

            # বাটন ও কিবোর্ড
            keyboard = [[InlineKeyboardButton("Main Channel", url="https://t.me/+0stz6v7z56I4Y2Y1")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                await bot.send_message(
                    chat_id=TELEGRAM_GROUP_ID,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
                print(f"✅ Sent: {app} | OTP: {otp}")
            except Exception as e:
                print(f"❌ Telegram Error: {e}")

        # ৩০ সেকেন্ড পর পর চেক করবে
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
