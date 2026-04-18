import requests
import asyncio
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# ------------------ কনফিগারেশন ------------------
BOT_TOKEN = "8590972749:AAFkOzTeDbp6uxjLHV03y-iZjKcj2CBg2Fk"
API_URL = "http://147.135.212.197/crapi/st/viewstats"
PANEL_TOKEN = "RFdUREJBUzR9T4dVc49ndmFra1NYV5CIhpGVcnaOYmqHhJZXfYGJSQ=="

# ------------------ ফাংশন: ডাটা সংগ্রহ ------------------
def get_unique_numbers():
    try:
        # "records": "100" দিয়ে ১০০টি ডাটা কল করা হচ্ছে
        params = {"token": PANEL_TOKEN, "records": "100"} 
        response = requests.get(API_URL, params=params, timeout=25)
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, list):
            # set() ব্যবহার করে ডুপ্লিকেট নাম্বার বাদ দেওয়া হচ্ছে
            unique_numbers = []
            seen = set()
            
            for entry in data:
                if len(entry) > 1:
                    phone = entry[1].strip()
                    if phone not in seen:
                        unique_numbers.append(phone)
                        seen.add(phone)
            
            return unique_numbers
        return []
    except Exception as e:
        print(f"❌ API fetch failed: {e}")
        return None

# ------------------ বট হ্যান্ডলার ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📥 Get 100 Unique Numbers", callback_data="get_file")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "✨ **প্যানেল নাম্বার এক্সপোর্টার**\n\nনিচের বাটনে ক্লিক করলে প্যানেলের শেষ ১০০টি ডাটা থেকে ইউনিক নাম্বারগুলোর ফাইল পাবেন।",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "get_file":
        await query.edit_message_text("🔄 প্যানেল থেকে ১০০টি ইউনিক নাম্বার প্রসেস করা হচ্ছে...")
        
        numbers = get_unique_numbers()
        
        if numbers is None:
            await query.edit_message_text("❌ সার্ভার রেসপন্স করছে না। প্যানেল বা ইন্টারনেট চেক করুন।")
            return
            
        if not numbers:
            await query.edit_message_text("⚠️ প্যানেলে কোনো নাম্বার পাওয়া যায়নি।")
            return

        # ফাইল কন্টেন্ট তৈরি
        file_content = "\n".join(numbers)
        file_obj = io.BytesIO(file_content.encode('utf-8'))
        file_obj.name = "unique_100_numbers.txt"
        
        try:
            await query.message.reply_document(
                document=file_obj,
                caption=(
                    f"✅ **ফাইল তৈরি সম্পন্ন!**\n\n"
                    f"📊 সংগৃহীত রেকর্ড: ১০০টি\n"
                    f"🎯 ইউনিক নাম্বার পাওয়া গেছে: {len(numbers)}টি\n"
                    f"🚫 ডুপ্লিকেট বাদ দেওয়া হয়েছে: {100 - len(numbers)}টি"
                ),
                parse_mode="Markdown"
            )
            await query.edit_message_text("✅ ফাইল পাঠানো হয়েছে।")
        except Exception as e:
            await query.edit_message_text(f"❌ এরর: {e}")

# ------------------ রান ------------------
if __name__ == "__main__":
    print("🤖 Bot is running with 100 records limit...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()
