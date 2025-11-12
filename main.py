import os
import sys
import re
import time
import requests
import datetime
import concurrent.futures
import socketio
import asyncio
import json
import pycountry
import threading
from bs4 import BeautifulSoup
from http.cookiejar import CookieJar
from requests.cookies import RequestsCookieJar
from urllib.parse import urlencode

# --- Telegram Bot Imports ---
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, ContextTypes, filters

# ==========================================================
# === UNIFIED CONFIGURATION
# ==========================================================
TELEGRAM_BOT_TOKEN = "8068434240:AAF2xLDW3YJQ95wwYcI5Ir_m4x636EEIsck"
TELEGRAM_CHAT_ID_INT = -1003175183012     # For the bot's filter (as an integer)
TELEGRAM_CHAT_ID_STR = "-1003175183012"    # For sending messages (as a string)

LIVE_URL = "https://www.orangecarrier.com/live/calls"
SOCKET_URL = "wss://orangecarrier.com:8443"
BASE_URL = "https://www.orangecarrier.com"
CREDS_FILE = 'creds.json'

# --- Conversation States for Bot ---
GET_TOKEN, GET_USER, GET_COOKIE = range(3)

# --- Global variable to hold the scraper's socket client ---
global_sio_client = None

# ==========================================================
# === AUTO-INSTALL LIBRARIES
# ==========================================================
def install():
    """Installs required libraries."""
    libs = ["requests", "socketio", "bs4", "pycountry", "python-telegram-bot"]
    for m in libs:
        try:
            if m == "bs4":
                __import__("bs4")
            elif m == "pycountry":
                __import__("pycountry")
            elif m == "python-telegram-bot":
                __import__("telegram")
            else:
                __import__(m)
        except ImportError:
            print(f"Installing {m}...")
            if m == "socketio":
                os.system(f"{sys.executable} -m pip install \"python-socketio[client]\"")
            elif m == "bs4":
                os.system(f"{sys.executable} -m pip install beautifulsoup4")
            elif m == "pycountry":
                os.system(f"{sys.executable} -m pip install pycountry")
            elif m == "python-telegram-bot":
                 os.system(f"{sys.executable} -m pip install python-telegram-bot")
            else:
                os.system(f"{sys.executable} -m pip install {m}")

# ==========================================================
# === SCRAPER FUNCTIONS (from fixedd.py)
# ==========================================================

def get_flag_emoji(country_name):
    """Generates a flag emoji from a country name."""
    try:
        country = pycountry.countries.search_fuzzy(country_name)[0]
        code = country.alpha_2
        return "".join(chr(0x1F1E6 + ord(char) - ord('A')) for char in code)
    except:
        return "🌍"

def load_credentials():
    """Loads credentials from the creds.json file."""
    print("[Scraper] Loading credentials from creds.json...")
    if not os.path.exists(CREDS_FILE):
        print(f"[Scraper] Error: `{CREDS_FILE}` not found.")
        print("[Scraper] Please send the /update command to the bot to create it.")
        return None, None, None
        
    try:
        with open(CREDS_FILE, 'r') as f:
            creds = json.load(f)
        
        token = creds.get('MANUAL_TOKEN')
        user = creds.get('MANUAL_USER')
        cookie = creds.get('MANUAL_COOKIE_STRING')
        
        if not token or not user or not cookie:
            print("[Scraper] Error: `creds.json` is incomplete. Please run /update on the bot again.")
            return None, None, None
            
        print("[Scraper] Credentials loaded successfully.")
        return token, user, cookie
        
    except Exception as e:
        print(f"[Scraper] Error reading `{CREDS_FILE}`: {e}")
        return None, None, None

def get_country_name(termination_string):
    """Extracts the country name from a termination string."""
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
    """Masks a number like '8551****649'."""
    try:
        if len(num) > 7:
            return f"{num[:4]}****{num[-3:]}"
        else:
            return f"{num[:1]}***{num[-1:]}"
    except:
        return num

def send_telegram_message(text_message):
    """Sends a plain text message to Telegram."""
    try:
        payload = {
            'chat_id': TELEGRAM_CHAT_ID_STR, # Use string version
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
    """Sends the audio file with the new caption format and thumbnail."""
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
            "chat_id": TELEGRAM_CHAT_ID_STR, # Use string version
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
            "accept": "*/*",
            "accept-language": "en-US,en;q:0.9",
            "range": "bytes:0-",
            "sec-fetch-dest": "audio",
            "sec-fetch-mode": "no-cors",
            "sec-fetch-site": "same-origin",
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

# --- THIS IS THE FIX ---
def delayed_download(delay_seconds, url, cli, dur, country, cookie_jar):
    """
    Waits for a few seconds before calling the main download function
    to allow the server to process the full audio file.
    """
    try:
        print(f"[Scraper] Call ended. Waiting {delay_seconds}s for server processing...")
        time.sleep(delay_seconds)
        print(f"[Scraper] Waited {delay_seconds}s. Starting download for {cli}.")
        # Now call the original download function
        download(url, cli, dur, country, cookie_jar)
    except Exception as e:
        print(f"[Scraper] Error in delayed_download: {e}")
# --- END FIX ---

def parse_cookie_string_to_jar(cookie_string):
    cookie_jar = RequestsCookieJar()
    if not cookie_string:
        return cookie_jar

    for cookie_pair in cookie_string.split('; '):
        if '=' in cookie_pair:
            name, value = cookie_pair.split('=', 1)
            cookie_jar.set(
                name.strip(), 
                value.strip(), 
                domain=".orangecarrier.com", 
                path="/"
            )
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
                        
                        self.active_calls[uuid] = {
                            'did': did,
                            'country': country,
                            'duration': duration
                        }
                        
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
                        
                        # --- THIS IS THE FIX ---
                        # Call the delay function instead of downloading directly
                        self.executor.submit(
                            delayed_download,  # <-- Call the new delay function
                            15,                # <-- Add a 15-second delay
                            download_url, 
                            did, 
                            last_duration,
                            country,
                            self.http_session.cookies
                        )
                        # --- END FIX ---
                        
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
# === BOT FUNCTIONS (from update.py)
# ==========================================================

async def start_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the credential update conversation."""
    await update.message.reply_text(
        "OK, starting credential update.\n\n"
        "1. Please send me the new `token`."
    )
    return GET_TOKEN

async def get_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the token and asks for the user."""
    context.user_data['token'] = update.message.text.strip()
    await update.message.reply_text(
        "Token received.\n\n"
        "2. Now, please send me the `user` ID."
    )
    return GET_USER

async def get_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the user and asks for the cookie."""
    context.user_data['user'] = update.message.text.strip()
    await update.message.reply_text(
        "User ID received.\n\n"
        "3. Finally, please paste the entire new `cookie` string."
    )
    return GET_COOKIE

async def get_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves all credentials to file and tells scraper to restart."""
    global global_sio_client
    
    context.user_data['cookie'] = update.message.text.strip()
    
    creds = {
        'MANUAL_TOKEN': context.user_data['token'],
        'MANUAL_USER': context.user_data['user'],
        'MANUAL_COOKIE_STRING': context.user_data['cookie']
    }
    
    try:
        with open(CREDS_FILE, 'w') as f:
            json.dump(creds, f, indent=4)
        
        await update.message.reply_text(
            "✅ **Success!** Credentials saved.\n\n"
            "🔄 **Telling scraper to restart...**"
        )
        print(f"[{datetime.datetime.now()}] [Bot] Credentials updated successfully.")
        
        if global_sio_client and global_sio_client.connected:
            print("[Bot] Scraper is connected. Sending disconnect signal...")
            await global_sio_client.disconnect() # Use await for async disconnect
            await update.message.reply_text("🚀 Scraper signaled to restart.")
        else:
            print("[Bot] Scraper was not connected. It will load new creds on its next try.")
            await update.message.reply_text("Scraper was not running, but will use new credentials on its next start.")
        
    except Exception as e:
        await update.message.reply_text(f"❌ **Error!**\nCould not save credentials: {e}")
        print(f"[Bot] Error saving credentials: {e}")
        
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current update operation."""
    await update.message.reply_text("Update cancelled.")
    context.user_data.clear()
    return ConversationHandler.END

# ==========================================================
# === MAIN EXECUTION LOGIC (Using Asyncio and Threading)
# ==========================================================

async def run_scraper_async():
    """
    This function runs the scraper in a continuous loop.
    It's designed to be run in its own thread.
    """
    global global_sio_client

    # Create a new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
    http_session = requests.Session()
    handler = CallHandler(http_session, executor)

    while True:
        MANUAL_TOKEN, MANUAL_USER, MANUAL_COOKIE_STRING = load_credentials()
        
        if not MANUAL_TOKEN:
            print("[Scraper] Credentials not found. Waiting 30 seconds...")
            time.sleep(30)
            continue

        print("[Scraper] Using manually provided credentials.")
        
        query_params_dict = {
            "token": MANUAL_TOKEN,
            "user": MANUAL_USER,
            "EIO": 3, 
        }
        
        full_socket_url = f"{SOCKET_URL}?{urlencode(query_params_dict)}"
        
        http_session.cookies = parse_cookie_string_to_jar(MANUAL_COOKIE_STRING)
        http_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
        })
        
        print("[Scraper] Session and tokens loaded.")
        
        sio = socketio.AsyncClient(reconnection_attempts=10, reconnection_delay=5)
        global_sio_client = sio 
        
        @sio.event
        async def connect():
            print(f"\n[Scraper] Successfully connected!")

        @sio.event
        async def connect_error(data):
            print(f"[Scraper] Connection failed: {data}")
            print("[Scraper] This may be due to an expired or invalid TOKEN, USER, or COOKIE.")

        @sio.event
        async def disconnect():
            print("[Scraper] Disconnected from WebSocket.")

        sio.on('call', handler.on_call_event)

        try:
            print(f"[Scraper] Connecting to {SOCKET_URL}...")
            await sio.connect(
                full_socket_url,
                transports=['websocket']
            )
            await sio.wait() 
            
        except socketio.exceptions.ConnectionError as e:
            print(f"[Scraper] Failed to connect: {e}")
        except Exception as e:
            print(f"[Scraper] An error occurred: {e}")
        finally:
            print("[Scraper] Cleaning up session for restart...")
            global_sio_client = None 
            print("[Scraper] Loop restarting in 5 seconds...")
            await asyncio.sleep(5) # Use await for async sleep

if __name__ == '__main__':
    print("Running auto-installer...")
    install()
    print("Installer finished.")

    # --- START THE SCRAPER IN A BACKGROUND THREAD ---
    print("Starting scraper thread...")
    # We must use asyncio.to_thread to run an async function in a new thread
    # But run_scraper_async creates its own loop, so a simple Thread is better.
    scraper_thread = threading.Thread(target=lambda: asyncio.run(run_scraper_async()), daemon=True)
    scraper_thread.start()

    # --- START THE BOT IN THE MAIN THREAD ---
    print("Starting Updater Bot in main thread...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    user_filter = filters.Chat(chat_id=TELEGRAM_CHAT_ID_INT) # Use integer ID

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

    print(f"Bot is running. Send /update from chat ID {TELEGRAM_CHAT_ID_INT} to begin.")
    application.run_polling()
