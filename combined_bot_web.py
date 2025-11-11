import os
import sys
import re
import time
import requests
import datetime
import concurrent.futures
import socketio
import json
import pycountry
import threading
import psycopg2
import urllib.parse as urlparse
from bs4 import BeautifulSoup
from http.cookiejar import CookieJar
from requests.cookies import RequestsCookieJar
from urllib.parse import urlencode

# --- 1. IMPORT FLASK ---
from flask import Flask

# --- Telegram Bot Imports ---
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, ContextTypes, filters

# ==========================================================
# === UNIFIED CONFIGURATION (Loads from Render)
# ==========================================================
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
DATABASE_URL = os.environ.get('DATABASE_URL')
TELEGRAM_CHAT_ID_INT = -1003175183012
TELEGRAM_CHAT_ID_STR = "-1003175183012"

LIVE_URL = "https://www.orangecarrier.com/live/calls"
SOCKET_URL = "wss://orangecarrier.com:8443"
BASE_URL = "https://www.orangecarrier.com"

# --- Conversation States for Bot ---
GET_TOKEN, GET_USER, GET_COOKIE = range(3)

# --- Global variable to hold the scraper's socket client ---
global_sio_client = None

# ==========================================================
# === 2. FLASK WEB SERVER (Keep-Alive)
# ==========================================================
app = Flask(__name__)

@app.route('/')
def keep_alive():
    """
    A simple route that returns "I'm alive!" 
    This is the page that UptimeRobot will ping.
    """
    return "Bot and scraper are running."

def run_web_server():
    """
    Runs the Flask web server.
    Render will send traffic to this port.
    """
    # Gunicorn will handle the port binding, but we can run it
    # directly for local testing if needed.
    # We just need the 'app' object to be defined.
    # This function is now mostly for local testing.
    # Gunicorn will be the one running 'app' on Render.
    pass # Gunicorn handles this

# ==========================================================
# === DATABASE FUNCTIONS
# ==========================================================
def get_db_conn():
    """Establishes a connection to the Postgres database."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set.")
    url = urlparse.urlparse(DATABASE_URL)
    conn = psycopg2.connect(
        dbname=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port
    )
    return conn

def setup_database():
    """Run by the bot to create the credentials table if it doesn't exist."""
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS credentials (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[DB] Database table checked/created successfully.")
    except Exception as e:
        print(f"[DB] Setup Error: {e}. Make sure DATABASE_URL is set.")

# ==========================================================
# === SCRAPER FUNCTIONS (Modified for DB)
# ==========================================================
def load_credentials():
    print("[Scraper] Loading credentials from database...")
    if not DATABASE_URL:
        print("[Scraper] Error: DATABASE_URL environment variable not set.")
        return None, None, None
        
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM credentials")
        creds = dict(cur.fetchall())
        cur.close()
        conn.close()

        token = creds.get('MANUAL_TOKEN')
        user = creds.get('MANUAL_USER')
        cookie = creds.get('MANUAL_COOKIE_STRING')

        if not token or not user or not cookie:
            print("[Scraper] Error: Database is incomplete. Please run /update on the bot.")
            return None, None, None
            
        print("[Scraper] Credentials loaded successfully from DB.")
        return token, user, cookie
        
    except Exception as e:
        print(f"[Scraper] Error reading from DB: {e}")
        return None, None, None

# ... (All other scraper functions are the same) ...
# ... (get_flag_emoji, get_country_name, mask_number, etc.) ...
# ... (send_telegram_message, send_telegram_audio, download) ...
# ... (parse_cookie_string_to_jar, CallHandler class) ...
def get_flag_emoji(country_name):
    try:
        country = pycountry.countries.search_fuzzy(country_name)[0]
        code = country.alpha_2
        return "".join(chr(0x1F1E6 + ord(char) - ord('A')) for char in code)
    except:
        return "🌍"

def get_country_name(termination_string):
    try:
        parts = str(termination_string).split()
        country_parts = []
        for part in parts:
            if part.lower() == 'mobile' or part.isdigit():
                break
            country_parts.append(part.upper())
        country = ' '.join(country_parts)
        return country if country else "UNKNOWN"
    except:
        return "UNKNOWN"

def mask_number(num):
    try:
        if len(num) > 7:
            return f"{num[:4]}****{num[-3:]}"
        else:
            return f"{num[:1]}***{num[-1:]}"
    except:
        return num

def send_telegram_message(text_message):
    try:
        payload = {
            'chat_id': TELEGRAM_CHAT_ID_STR,
            'text': text_message,
            'parse_mode': 'HTML'
        }
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data=payload,
            timeout=10
        )
        if not r.ok:
            print(f"[Scraper] TG Message Failed: {r.text}")
    except Exception as e:
        print(f"[Scraper] TG Message Error: {e}")

def send_telegram_audio(file, num, country, duration_str):
    audio_f = None
    thumb_f = None
    try:
        masked = mask_number(num)
        local_time = datetime.datetime.now().strftime('%I:%M:%S %p')
        flag = get_flag_emoji(country)
        caption = f"""🔥 NEW CALL {country} {flag} RECEIVED ✨
🌍 Country: {country} {flag}
📞 Number: {masked}
⏰ Time: {local_time}
"""
        file_title = os.path.basename(file) 
        try:
            duration_int = int(duration_str)
        except:
            duration_int = 0
        data = {
            "chat_id": TELEGRAM_CHAT_ID_STR, 
            "caption": caption,
            "title": file_title,
            "duration": duration_int
        }
        files_payload = {}
        audio_f = open(file, "rb")
        files_payload["audio"] = audio_f
        try:
            thumb_f = open("thumbnail.png", "rb") 
            files_payload["thumbnail"] = thumb_f
            print("[Scraper] Attaching thumbnail.png...")
        except FileNotFoundError:
            print("[Scraper] thumbnail.png not found, sending audio without it.")
        except Exception as e:
            print(f"[Scraper] Error attaching thumbnail: {e}")
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendAudio",
            data=data,
            files=files_payload,
            timeout=30
        )
        print("[Scraper] Telegram: Audio Sent" if r.ok else f"TG Audio Failed: {r.text}")
    except Exception as e:
        print("[Scraper] TG Audio Error:", e)
    finally:
        if audio_f:
            audio_f.close()
        if thumb_f:
            thumb_f.close()
        try: 
            os.remove(file)
        except: 
            pass

def download(url, cli, dur, country, cookie_jar):
    try:
        s = requests.Session()
        s.cookies.update(cookie_jar)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
            "Referer": "https://www.orangecarrier.com/live/calls",
            "accept": "*/*", "accept-language": "en-US,en;q=0.9", "range": "bytes:0-",
            "sec-fetch-dest": "audio", "sec-fetch-mode": "no-cors", "sec-fetch-site": "same-origin",
        }
        s.headers.update(headers)
        print(f"[Scraper] Downloading audio for {cli} from {url}")
        with s.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            content_type = r.headers.get('Content-Type', 'audio/mpeg').lower()
            extension = ".mp3"
            if 'wav' in content_type: extension = ".wav"
            elif 'ogg' in content_type: extension = ".ogg"
            elif 'aac' in content_type: extension = ".aac"
            fn = f"rec_{cli}_{int(time.time())}{extension}"
            print(f"[Scraper] Saving as: {fn} (Content-Type: {content_type})")
            with open(fn, "wb") as f:
                for c in r.iter_content(8192): 
                    f.write(c)
        send_telegram_audio(fn, cli, country, dur)
    except Exception as e:
        print(f"[Scraper] Download failed: {e}")

def parse_cookie_string_to_jar(cookie_string):
    cookie_jar = RequestsCookieJar()
    if not cookie_string:
        return cookie_jar
    for cookie_pair in cookie_string.split('; '):
        if '=' in cookie_pair:
            name, value = cookie_pair.split('=', 1)
            cookie_jar.set(name.strip(), value.strip(), domain=".orangecarrier.com", path="/")
    return cookie_jar

class CallHandler:
    def __init__(self, http_session, executor):
        self.http_session = http_session
        self.executor = executor
        self.detected_uuids = set()
        self.active_calls = {}
    def on_call_event(self, data):
        try:
            calls_data = data.get('calls', {})
            page_list = calls_data.get('calls', [])
            ended_calls_list = calls_data.get('end', []) 
            all_current_uuids_on_page = set()
            for call_list_on_page in page_list: 
                if isinstance(call_list_on_page, dict):
                    call_iterable = call_list_on_page.values()
                else:
                    call_iterable = call_list_on_page
                for call in call_iterable:
                    uuid = call.get('uuid')
                    if not uuid: continue
                    all_current_uuids_on_page.add(uuid)
                    status = call.get('status')
                    try:
                        duration = int(call.get('duration', '0'))
                    except ValueError:
                        duration = 0
                    if (status == 'up' and uuid not in self.detected_uuids):
                        self.detected_uuids.add(uuid)
                        did = call.get('cid_num', 'Unknown')
                        termination = call.get('termination', 'UNKNOWN')
                        country = get_country_name(termination)
                        self.active_calls[uuid] = {'did': did, 'country': country, 'duration': duration}
                        masked_num = mask_number(did)
                        flag = get_flag_emoji(country)
                        print(f"[Scraper] --- New Call Detected (at {duration}s) ---")
                        print(f"[Scraper]   CLI/DID: {did} | UUID: {uuid}")
                        text_message = f"🔥 NEW CALL {country} {flag} DETECTED ✨\n📞 Number: {masked_num}\n⏳ Waiting for Call 📞"
                        self.executor.submit(send_telegram_message, text_message)
                    elif (status == 'up' and uuid in self.active_calls):
                        self.active_calls[uuid]['duration'] = duration
            if ended_calls_list:
                for call_data in ended_calls_list:
                    uuid = call_data.get('uuid')
                    if uuid in self.active_calls:
                        call_info = self.active_calls.pop(uuid)
                        did = call_info['did']
                        country = call_info['country']
                        last_duration = str(call_data.get('duration', call_info['duration']))
                        print(f"[Scraper] --- Call Ended. Submitting Download ---")
                        print(f"[Scraper]   CLI/DID: {did} | UUID: {uuid} | Duration: {last_duration}")
                        download_url = f"{BASE_URL}/live/calls/sound?did={did}&uuid={uuid}"
                        self.executor.submit(
                            download, download_url, did, last_duration,
                            country, self.http_session.cookies
                        )
                        if uuid in self.detected_uuids:
                            self.detected_uuids.remove(uuid)
            active_uuids_to_prune = set(self.active_calls.keys()) - all_current_uuids_on_page
            for uuid in active_uuids_to_prune:
                print(f"[Scraper] Pruning stale call (no 'end' event): {uuid}")
                self.active_calls.pop(uuid)
                if uuid in self.detected_uuids:
                    self.detected_uuids.remove(uuid)
        except Exception as e:
            print(f"[Scraper] Error in on_call_event: {e}")
            print(f"[Scraper] Data: {str(data)[:200]}...")

# ==========================================================
# === BOT FUNCTIONS (Modified for DB)
# ==========================================================
async def start_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "OK, starting credential update.\n\n"
        "1. Please send me the new `token`."
    )
    return GET_TOKEN

async def get_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['token'] = update.message.text.strip()
    await update.message.reply_text(
        "Token received.\n\n"
        "2. Now, please send me the `user` ID."
    )
    return GET_USER

async def get_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['user'] = update.message.text.strip()
    await update.message.reply_text(
        "User ID received.\n\n"
        "3. Finally, please paste the entire new `cookie` string."
    )
    return GET_COOKIE

async def get_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    global global_sio_client
    context.user_data['cookie'] = update.message.text.strip()
    
    if not DATABASE_URL:
        await update.message.reply_text("❌ **Error!**\n`DATABASE_URL` is not set. Bot cannot save credentials.")
        return ConversationHandler.END

    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO credentials (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """, ('MANUAL_TOKEN', context.user_data['token']))
        cur.execute("""
            INSERT INTO credentials (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """, ('MANUAL_USER', context.user_data['user']))
        cur.execute("""
            INSERT INTO credentials (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """, ('MANUAL_COOKIE_STRING', context.user_data['cookie']))
        conn.commit()
        cur.close()
        conn.close()
        
        await update.message.reply_text(
            "✅ **Success!** Credentials saved to DB.\n\n"
            "🔄 **Telling scraper to restart...**"
        )
        print(f"[{datetime.datetime.now()}] [Bot] Credentials updated in DB.")
        
        if global_sio_client and global_sio_client.connected:
            print("[Bot] Scraper is connected. Sending disconnect signal...")
            global_sio_client.disconnect()
            await update.message.reply_text("🚀 Scraper signaled to restart.")
        else:
            print("[Bot] Scraper was not connected. It will load new creds on its next try.")
            await update.message.reply_text("Scraper was not running, but will use new credentials on its next start.")
        
    except Exception as e:
        await update.message.reply_text(f"❌ **Error!**\nCould not save to database: {e}")
        print(f"[Bot] Error saving to DB: {e}")
        
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Update cancelled.")
    context.user_data.clear()
    return ConversationHandler.END

# ==========================================================
# === MAIN EXECUTION LOGIC (3 Threads)
# ==========================================================

def run_scraper_loop():
    """
    This function runs the scraper in a continuous loop.
    It will automatically restart if disconnected.
    """
    global global_sio_client

    while True:
        MANUAL_TOKEN, MANUAL_USER, MANUAL_COOKIE_STRING = load_credentials()
        
        if not MANUAL_TOKEN:
            print("[Scraper] Credentials not found. Waiting 30 seconds...")
            time.sleep(30)
            continue

        print("[Scraper] Using manually provided credentials from DB.")
        
        query_params_dict = {
            "token": MANUAL_TOKEN, "user": MANUAL_USER, "EIO": 3, 
        }
        full_socket_url = f"{SOCKET_URL}?{urlencode(query_params_dict)}"
        
        http_session = requests.Session()
        http_session.cookies = parse_cookie_string_to_jar(MANUAL_COOKIE_STRING)
        http_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
        })
        
        print("[Scraper] Session and tokens loaded.")
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
        handler = CallHandler(http_session, executor)
        
        sio = socketio.Client(reconnection_attempts=10, reconnection_delay=5)
        global_sio_client = sio 
        
        @sio.event
        def connect():
            print(f"\n[Scraper] Successfully connected!")
        @sio.event
        def connect_error(data):
            print(f"[Scraper] Connection failed: {data}")
        @sio.event
        def disconnect():
            print("[Scraper] Disconnected from WebSocket.")

        sio.on('call', handler.on_call_event)

        try:
            print(f"[Scraper] Connecting to {SOCKET_URL}...")
            sio.connect(full_socket_url, transports=['websocket'])
            sio.wait() 
        except socketio.exceptions.ConnectionError as e:
            print(f"[Scraper] Failed to connect: {e}")
        except Exception as e:
            print(f"[Scraper] An error occurred: {e}")
        finally:
            print("[Scraper] Cleaning up session...")
            executor.shutdown(wait=False, cancel_futures=True)
            http_session.close()
            global_sio_client = None
            print("[Sccraper] Loop restarting in 5 seconds...")
            time.sleep(5)

def run_bot_polling():
    """
    This function runs the Telegram bot in a loop.
    """
    print("[Bot] Starting Updater Bot...")
    if not TELEGRAM_BOT_TOKEN:
        print("[Bot] Error: TELEGRAM_BOT_TOKEN environment variable not set.")
        return
    if not DATABASE_URL:
        print("[Bot] Error: DATABASE_URL environment variable not set.")
        return

    # Make sure the database table exists
    setup_database()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    user_filter = filters.Chat(chat_id=TELEGRAM_CHAT_ID_INT)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('update', start_update, filters=user_filter)],
        states={
            GET_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, get_token)],
            GET_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, get_user)],
            GET_COOKIE: [MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, get_cookie)],
        },
        fallbacks=[CommandHandler('cancel', cancel, filters=user_filter)],
    )
    application.add_handler(conv_handler)
    print(f"[Bot] Bot is running. Send /update from chat ID {TELEGRAM_CHAT_ID_INT} to begin.")
    application.run_polling(stop_signals=None)

# ==========================================================
# === 3. SCRIPT STARTUP
# ==========================================================
# This part runs ONLY when Gunicorn starts the server.
# It will start the bot and scraper in background threads.

if __name__ != '__main__':
    print("[Main] Gunicorn is loading this file.")
    print("[Main] Starting scraper thread...")
    scraper_thread = threading.Thread(target=run_scraper_loop, daemon=True)
    scraper_thread.start()
    
    print("[Main] Starting bot thread...")
    bot_thread = threading.Thread(target=run_bot_polling, daemon=True)
    bot_thread.start()

# When you run `gunicorn combined_bot_web:app`, Gunicorn imports this file.
# 1. It finds the `app = Flask(__name__)` object.
# 2. Because it's an import, `__name__` is NOT `__main__`.
# 3. The `if __name__ != '__main__':` block executes.
# 4. The scraper and bot threads are started.
# 5. Gunicorn then starts the Flask web server (the `app` object).
#
# All three parts (Web, Bot, Scraper) are now running in one service.
