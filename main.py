import os
import sys
import re
import time
import requests
import datetime
import concurrent.futures
import socketio
import json
import pycountry  # <-- 1. ADDED IMPORT
from bs4 import BeautifulSoup
from http.cookiejar import CookieJar
from requests.cookies import RequestsCookieJar
from urllib.parse import urlencode

# === CONFIG (No credentials here anymore) ===
TELEGRAM_BOT_TOKEN = "8068434240:AAF2xLDW3YJQ95wwYcI5Ir_m4x636EEIsck"
TELEGRAM_CHAT_ID = "-1003175183012"
LIVE_URL = "https://www.orangecarrier.com/live/calls"
SOCKET_URL = "wss://orangecarrier.com:8443"
BASE_URL = "https://www.orangecarrier.com"
CREDS_FILE = 'creds.json' # The file to read from

# --- (REMOVED COUNTRY_FLAGS dictionary) ---

# --- Auto-install libraries ---
def install():
    libs = ["requests", "socketio", "bs4", "pycountry"] # <-- 2. ADDED PYCOUNTRY
    for m in libs:
        try:
            if m == "bs4":
                __import__("bs4")
            elif m == "pycountry": # <-- 3. ADDED PYCOUNTRY CHECK
                __import__("pycountry")
            else:
                __import__(m)
        except ImportError:
            print(f"Installing {m}...")
            if m == "socketio":
                os.system(f"{sys.executable} -m pip install \"python-socketio[client]\"")
            elif m == "bs4":
                os.system(f"{sys.executable} -m pip install beautifulsoup4")
            elif m == "pycountry": # <-- 4. ADDED PYCOUNTRY INSTALL
                os.system(f"{sys.executable} -m pip install pycountry")
            else:
                os.system(f"{sys.executable} -m pip install {m}")
install()
# --- End Install ---

# === NEW HELPER: Get Flag Emoji ===
def get_flag_emoji(country_name):
    """Generates a flag emoji from a country name."""
    try:
        # Find the country by its name
        country = pycountry.countries.search_fuzzy(country_name)[0]
        # Get its 2-letter ISO code (e.g., "US")
        code = country.alpha_2
        # Convert the 2-letter code to flag emojis
        # (e.g., "U" -> 🇺, "S" -> 🇸)
        return "".join(chr(0x1F1E6 + ord(char) - ord('A')) for char in code)
    except:
        return "🌍" # Default to globe emoji if not found

# === NEW HELPER: Load Credentials ===
def load_credentials():
    """Loads credentials from the creds.json file."""
    print("Loading credentials from creds.json...")
    if not os.path.exists(CREDS_FILE):
        print(f"Error: `{CREDS_FILE}` not found.")
        print("Please run the `updater_bot.py` script and send it the /update command first.")
        return None, None, None
        
    try:
        with open(CREDS_FILE, 'r') as f:
            creds = json.load(f)
        
        token = creds.get('MANUAL_TOKEN')
        user = creds.get('MANUAL_USER')
        cookie = creds.get('MANUAL_COOKIE_STRING')
        
        if not token or not user or not cookie:
            print("Error: `creds.json` is incomplete. Please run /update on the bot again.")
            return None, None, None
            
        print("Credentials loaded successfully.")
        return token, user, cookie
        
    except Exception as e:
        print(f"Error reading `{CREDS_FILE}`: {e}")
        return None, None, None

# === NEW HELPER: Extract Country ===
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
        return country if country else "UNKNOWN" # Return UNKNOWN if empty
    except:
        return "UNKNOWN"

# === NEW HELPER: Mask Number ===
def mask_number(num):
    """Masks a number like '8551****649'."""
    try:
        if len(num) > 7:
            return f"{num[:4]}****{num[-3:]}"
        else:
            return f"{num[:1]}***{num[-1:]}" # Failsafe for short numbers
    except:
        return num

# === NEW HELPER: Send Text Message ===
def send_telegram_message(text_message):
    """Sends a plain text message to Telegram."""
    try:
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': text_message,
            'parse_mode': 'HTML' # Use HTML for emojis
        }
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data=payload,
            timeout=10
        )
        if not r.ok:
            print(f"TG Message Failed: {r.text}")
    except Exception as e:
        print(f"TG Message Error: {e}")

# === TELEGRAM AUDIO (with Thumbnail) ===
def send_telegram_audio(file, num, country, duration_str):
    """Sends the audio file with the new caption format and thumbnail."""
    audio_f = None  # Initialize file handles
    thumb_f = None  #
    try:
        masked = mask_number(num)
        local_time = datetime.datetime.now().strftime('%I:%M:%S %p')
        flag = get_flag_emoji(country) # <-- 5. USE AUTO-FLAG
        
        # New caption format
        caption = f"""🔥 NEW CALL {country} {flag} RECEIVED ✨
🌍 Country: {country} {flag}
📞 Number: {masked}
⏰ Time: {local_time}
"""
        
        # Get the bare filename (e.g., "rec_...mp3")
        file_title = os.path.basename(file) 
        
        # Convert duration string to integer
        try:
            duration_int = int(duration_str)
        except:
            duration_int = 0 # Default if conversion fails
        
        # Create the data payload with 'title' and 'duration'
        data = {
            "chat_id": TELEGRAM_CHAT_ID, 
            "caption": caption,
            "title": file_title,     # <--- Add unique title
            "duration": duration_int # <--- Add duration
        }
        
        # --- Attach Audio and Thumbnail ---
        files_payload = {}
        
        # Open the audio file
        audio_f = open(file, "rb")
        files_payload["audio"] = audio_f
        
        # Try to open and add the thumbnail
        try:
            # This is the line that looks for your image
            thumb_f = open("thumbnail.png", "rb") 
            files_payload["thumbnail"] = thumb_f
            print("Attaching thumbnail.png...")
        except FileNotFoundError:
            # This is what is happening to you right now
            print("thumbnail.png not found, sending audio without it.")
        except Exception as e:
            print(f"Error attaching thumbnail: {e}")
        # --- End Thumbnail ---

        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendAudio",
            data=data,
            files=files_payload, # <-- Use the new files payload
            timeout=30
        )
        print("Telegram: Audio Sent" if r.ok else f"TG Audio Failed: {r.text}")

    except Exception as e:
        print("TG Audio Error:", e)
    finally:
        # --- CLEANUP ---
        # Ensure all opened files are closed
        if audio_f:
            audio_f.close()
        if thumb_f:
            thumb_f.close()
        # Delete the audio file after sending
        try: 
            os.remove(file)
        except: 
            pass

# === DOWNLOAD ===
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

        print(f"Downloading audio for {cli} from {url}")
        
        with s.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            content_type = r.headers.get('Content-Type', 'audio/mpeg').lower()
            extension = ".mp3"
            if 'wav' in content_type: extension = ".wav"
            elif 'ogg' in content_type: extension = ".ogg"
            elif 'aac' in content_type: extension = ".aac"

            fn = f"rec_{cli}_{int(time.time())}{extension}"
            print(f"Saving as: {fn} (Content-Type: {content_type})")
            
            with open(fn, "wb") as f:
                for c in r.iter_content(8192): 
                    f.write(c)
        
        # Call the new audio sender function, passing duration
        send_telegram_audio(fn, cli, country, dur)
        
    except Exception as e:
        print(f"Download failed: {e}")

# === HELPER: Parse Cookie String ===
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

# === HANDLE LIVE CALL DATA ===
class CallHandler:
    def __init__(self, http_session, executor):
        self.http_session = http_session
        self.executor = executor
        self.detected_uuids = set()
        self.active_calls = {} # <-- Stores info for active calls

    def on_call_event(self, data):
        try:
            calls_data = data.get('calls', {})
            page_list = calls_data.get('calls', [])
            
            # 'end' key contains a LIST, not a dictionary
            ended_calls_list = calls_data.get('end', []) 
            
            all_current_uuids_on_page = set() # For pruning

            # --- 1. Process ACTIVE calls (for detection and updates) ---
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

                    # --- New Call Detection ---
                    if (status == 'up' and uuid not in self.detected_uuids):
                        self.detected_uuids.add(uuid)
                        
                        did = call.get('cid_num', 'Unknown')
                        termination = call.get('termination', 'UNKNOWN')
                        country = get_country_name(termination)
                        
                        # Store this call's info
                        self.active_calls[uuid] = {
                            'did': did,
                            'country': country,
                            'duration': duration
                        }
                        
                        # Send "DETECTED" message
                        masked_num = mask_number(did)
                        flag = get_flag_emoji(country) # <-- 6. USE AUTO-FLAG
                        print(f"--- New Call Detected (at {duration}s) ---")
                        print(f"  CLI/DID: {did} | UUID: {uuid}")
                        text_message = f"🔥 NEW CALL {country} {flag} DETECTED ✨\n📞 Number: {masked_num}\n⏳ Waiting for Call 📞"
                        self.executor.submit(send_telegram_message, text_message)
                    
                    # --- Update duration for existing calls ---
                    elif (status == 'up' and uuid in self.active_calls):
                        self.active_calls[uuid]['duration'] = duration
                        
            # --- 2. Process ENDED calls (for download) ---
            if ended_calls_list:
                for call_data in ended_calls_list: # <-- Loop over the LIST
                    uuid = call_data.get('uuid')
                    
                    # Check if this is a call we were tracking
                    if uuid in self.active_calls:
                        
                        # Retrieve the call info and remove it from active tracking
                        call_info = self.active_calls.pop(uuid)
                        
                        did = call_info['did']
                        country = call_info['country']
                        # Use the final duration from the 'end' message if available
                        last_duration = str(call_data.get('duration', call_info['duration']))

                        print(f"--- Call Ended. Submitting Download ---")
                        print(f"  CLI/DID: {did} | UUID: {uuid} | Duration: {last_duration}")
                        
                        download_url = f"{BASE_URL}/live/calls/sound?did={did}&uuid={uuid}"
                        
                        self.executor.submit(
                            download, 
                            download_url, 
                            did, 
                            last_duration, # Send the final duration
                            country,
                            self.http_session.cookies
                        )
                        
                        # Also remove from detected set
                        if uuid in self.detected_uuids:
                            self.detected_uuids.remove(uuid)

            # --- 3. Pruning ---
            # Remove any calls from our tracking that vanished from the active list
            active_uuids_to_prune = set(self.active_calls.keys()) - all_current_uuids_on_page
            for uuid in active_uuids_to_prune:
                print(f"Pruning stale call (no 'end' event): {uuid}")
                self.active_calls.pop(uuid)
                if uuid in self.detected_uuids:
                    self.detected_uuids.remove(uuid)

        except Exception as e:
            print(f"Error in on_call_event: {e}")
            print(f"Data: {str(data)[:200]}...")

# === MAIN FUNCTION ===
def main():
    # --- Step 1: Load Manual Credentials ---
    MANUAL_TOKEN, MANUAL_USER, MANUAL_COOKIE_STRING = load_credentials()
    if not MANUAL_TOKEN:
        # Error message was already printed by load_credentials()
        return

    print("Using manually provided credentials.")
    
    query_params_dict = {
        "token": MANUAL_TOKEN,
        "user": MANUAL_USER,
        "EIO": 3, 
    }
    
    full_socket_url = f"{SOCKET_URL}?{urlencode(query_params_dict)}"
    
    http_session = requests.Session()
    http_session.cookies = parse_cookie_string_to_jar(MANUAL_COOKIE_STRING)
    http_session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    })
    
    print("Session and tokens loaded.")

    # --- Step 2: Setup Threading and Socket.IO ---
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
    handler = CallHandler(http_session, executor)
    sio = socketio.Client(reconnection_attempts=10, reconnection_delay=5)

    # --- Define Socket.IO event handlers ---
    @sio.event
    def connect():
        print(f"\nSuccessfully connected!")

    @sio.event
    def connect_error(data):
        print(f"Connection failed: {data}")
        print("This may be due to an expired or invalid TOKEN, USER, or COOKIE.")
        print("Please send /update to the updater_bot.py to provide new credentials.")

    @sio.event
    def disconnect():
        print("Disconnected from WebSocket.")

    # Main event listener
    sio.on('call', handler.on_call_event)

    # --- Step 3: Connect and Wait ---
    try:
        print(f"Connecting to {SOCKET_URL}...")
        sio.connect(
            full_socket_url,
            transports=['websocket']
        )
        sio.wait() 
        
    except socketio.exceptions.ConnectionError as e:
        print(f"Failed to connect: {e}")
        print("This may be due to an expired or invalid TOKEN, USER, or COOKIE.")
        print("Please send /update to the updater_bot.py to provide new credentials.")
    except KeyboardInterrupt:
        print("Script interrupted by user.")
    finally:
        print("Shutting down...")
        executor.shutdown(wait=True)
        sio.disconnect()
        http_session.close()
        print("Done.")

if __name__ == "__main__":
    main()
