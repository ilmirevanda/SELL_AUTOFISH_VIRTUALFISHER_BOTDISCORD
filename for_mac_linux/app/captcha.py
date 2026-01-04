#------------------------ IMPORTS --------------------------#
from __future__ import annotations

from . import *
from .api_wrapper import DEFAULT_USER_AGENT
from .utils import debugger
from .menu import NotificationPriority
from threading import Thread
from time import sleep, time
from re import sub, search
import base64
import traceback
from datetime import datetime
from requests import get
from urllib.parse import urlparse

# Import 2Captcha library
try:
    from twocaptcha import TwoCaptcha
except ImportError:
    # Fallback if twocaptcha not found (should not happen if copied correctly)
    TwoCaptcha = None

#------------------------ CONSTANTS --------------------------#
MAX_CAPTCHA_REGENS = 1

#------------------------- CLASSES ---------------------------#
class UnkownCaptchaError(Exception):
    pass

@dataclass
class Captcha:
    '''Captcha class, detects and solves captchas.'''
    #Pointers
    menu: BaseMenu = field(repr=False)
    
    #Components
    api_key: str = field(repr=False)
    answers: list = field(default_factory=list)
    captcha_image: str = None
    captcha_text: str = None
    
    #Backend
    _word_list: list[str] = field(init=False, repr=False)
    _raw_answers: list[str] = field(default_factory=list)
    _max_timeout: int = field(default=120, repr=False)
    _captcha_length: int = 6
    
    #Counters
    regens: int = 0
    
    #Flags
    busy: bool = False
    detected: bool = False
    solving: bool = False
    regenerating: bool = False

    #OCR Settings (Kept for compatibility)
    is_overlay_required: bool = field(default=False, repr=False)
    detect_orientation: bool = field(default=True, repr=False)
    scale: bool = field(default=False, repr=False)
    language: str = field(default='eng', repr=False)
    
    def __post_init__(self) -> None:
        self._word_list = ['captcha', 'verify']
        if TwoCaptcha is None:
            self.menu.notify('[!] Library 2Captcha tidak ditemukan!', NotificationPriority.HIGH)
    
    @property
    def name(self) -> str:
        '''Returns the class name in the correct format.'''
        return f'{self.__class__.__name__}'
    
    def filter(self, value: str) -> str:
        '''Filters results form the API. Valid results -> only alphanum'''
        if value:
            ans = sub('[^a-zA-Z0-9]', '', value)
            return ans
        else:
            return None
    
    def _download_image(self, url: str) -> str:
        '''Downloads image and returns base64 string.'''
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Default referer simulating Discord click-through
            discord_referer = 'https://discord.com/'
            vf_referer = 'https://virtualfisher.com/'
            # For VF, try Discord referer first (hotlink allowance), then VF as fallback
            initial_referer = discord_referer
            headers = {
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Referer': initial_referer,
                'Origin': discord_referer.rstrip('/'),
                'Sec-Fetch-Dest': 'image',
                'Sec-Fetch-Mode': 'no-cors',
                'Sec-Fetch-Site': 'cross-site',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Connection': 'keep-alive'
            }
            if self.menu.config.user_agent:
                headers['User-Agent'] = self.menu.config.user_agent
            else:
                headers['User-Agent'] = DEFAULT_USER_AGENT
            
            # Use proxy if available in config
            proxies = {}
            if self.menu.config.proxy_ip and self.menu.config.proxy_port:
                proxy_str = f"http://{self.menu.config.proxy_ip}:{self.menu.config.proxy_port}"
                if self.menu.config.proxy_auth_user and self.menu.config.proxy_auth_password:
                    proxy_str = f"http://{self.menu.config.proxy_auth_user}:{self.menu.config.proxy_auth_password}@{self.menu.config.proxy_ip}:{self.menu.config.proxy_port}"
                proxies = {'http': proxy_str, 'https': proxy_str}

            response = get(url, headers=headers, proxies=proxies, timeout=30)
            if response.status_code == 200:
                return base64.b64encode(response.content).decode('utf-8')
            else:
                # Fallback: if Virtual Fisher denies with 403 using Discord referer, retry with VF referer
                if response.status_code == 403 and 'virtualfisher.com' in domain:
                    headers['Referer'] = vf_referer
                    headers['Origin'] = vf_referer.rstrip('/')
                    headers['Sec-Fetch-Site'] = 'same-origin'
                    retry = get(url, headers=headers, proxies=proxies, timeout=30)
                    if retry.status_code == 200:
                        return base64.b64encode(retry.content).decode('utf-8')
                    else:
                        debugger.log(f"Retry failed with status {retry.status_code} for URL: {url}", f'{self.name} - download error')
                else:
                    debugger.log(f"Download failed with status {response.status_code} for URL: {url}", f'{self.name} - download error')
        except Exception as e:
            debugger.log(e, f'{self.name} - download image error')
        return None

    def reset(self) -> None:
        '''Resets the captcha state.'''
        self.detected = False
        self.solving = False
        self.regenerating = False
        self.captcha_image = None
        self.captcha_text = None
        self.answers.clear()
        self.regens = 0
        self.busy = False

    def detect(self, event: dict) -> bool:
        '''Detects if the event contains a captcha.'''
        if not event:
            return False
        
        # Check for text-based captcha in content
        content = event.get('content', '')
        if content:
            # Regex modified to handle markdown characters (e.g. **Code**)
            match = search(r'Code:\s*[*`]*([a-zA-Z0-9]+)[*`]*', content)
            if match:
                self.captcha_text = match.group(1)
                self.detected = True
                return True
            # Keyword-based detection to catch info messages:
            # Example: "To continue, solve the captcha posted above with the /verify command."
            low = content.lower()
            if ('captcha' in low or '/verify' in low) and not self.captcha_text and not self.captcha_image:
                self.detected = True
                # Do NOT return here; continue scanning embeds/attachments to capture image payload

        # Check for text-based captcha in embeds
        if 'embeds' in event and event['embeds']:
            for embed in event['embeds']:
                # Check title for "Anti-bot" to ensure detection even if payload extraction fails
                title = embed.get('title', '')
                if 'Anti-bot' in title or 'Anti-bot' in embed.get('author', {}).get('name', ''):
                    self.detected = True
                    # Continue to try to extract text or image, but ensure detected is True

                # Check description
                desc = embed.get('description', '')
                if desc:
                    # Regex modified to handle markdown characters (e.g. **Code**)
                    match = search(r'Code:\s*[*`]*([a-zA-Z0-9]+)[*`]*', desc)
                    if match:
                        self.captcha_text = match.group(1)
                        self.detected = True
                        return True
                    
                    # Check for Virtual Fisher captcha URL in description
                    vf_url_match = search(r'(https?://virtualfisher\.com/bot/captcha\.php\S+)', desc)
                    if vf_url_match:
                        self.captcha_image = vf_url_match.group(1).rstrip(')>]') # remove closing brackets if markdown
                        self.detected = True
                        return True

                    # Keyword-based detection (embed description info message)
                    dlow = desc.lower()
                    if ('captcha' in dlow or '/verify' in dlow) and not self.captcha_text and not self.captcha_image:
                        self.detected = True
                        # Do NOT return here; keep scanning for image payload
                
                # Check fields
                if 'fields' in embed:
                    for field in embed.get('fields', []):
                        val = field.get('value', '')
                        # Regex modified to handle markdown characters (e.g. **Code**)
                        match = search(r'Code:\s*[*`]*([a-zA-Z0-9]+)[*`]*', val)
                        if match:
                            self.captcha_text = match.group(1)
                            self.detected = True
                            return True
                        
                        # Check for Virtual Fisher captcha URL in fields
                        vf_url_match = search(r'(https?://virtualfisher\.com/bot/captcha\.php\S+)', val)
                        if vf_url_match:
                            self.captcha_image = vf_url_match.group(1).rstrip(')>]')
                            self.detected = True
                            return True

                        # Keyword-based detection (embed field info)
                        vlow = val.lower()
                        if ('captcha' in vlow or '/verify' in vlow) and not self.captcha_text and not self.captcha_image:
                            self.detected = True
                            # Do NOT return here; keep scanning for image payload

        # Check for attachments (images)
        if 'attachments' in event and event['attachments']:
            for attachment in event['attachments']:
                # Check if it is an image
                if attachment.get('content_type', '').startswith('image/') or \
                   attachment.get('filename', '').lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                    # Filter out known non-captcha images (e.g., fisher_round.png used in donate/help messages)
                    if 'fisher_round.png' in attachment.get('filename', '').lower():
                        continue
                        
                    # Prefer proxy_url if available, as it is hosted by Discord
                    self.captcha_image = attachment.get('proxy_url', attachment.get('url'))
                    self.detected = True
                    return True

        # Check for embeds (images)
        if 'embeds' in event and event['embeds']:
            for embed in event['embeds']:
                # Check main image
                if 'image' in embed:
                    image_url = embed['image'].get('url', '')
                    image_proxy_url = embed['image'].get('proxy_url', '')
                    
                    # Filter out known non-captcha images
                    if 'fisher_round.png' in image_url or 'fisher_round.png' in image_proxy_url:
                        continue
                        
                    if image_proxy_url:
                         self.captcha_image = image_proxy_url
                         self.detected = True
                         return True
                    if image_url:
                        self.captcha_image = image_url
                        self.detected = True
                        return True
                
                # Check thumbnail as fallback
                if 'thumbnail' in embed:
                     thumb_url = embed['thumbnail'].get('url', '')
                     thumb_proxy_url = embed['thumbnail'].get('proxy_url', '')
                     
                     # Filter out known non-captcha images
                     if 'fisher_round.png' in thumb_url or 'fisher_round.png' in thumb_proxy_url:
                         continue

                     if thumb_proxy_url:
                         self.captcha_image = thumb_proxy_url
                         self.detected = True
                         return True
                     if thumb_url:
                         self.captcha_image = thumb_url
                         self.detected = True
                         return True

                # Check for Virtual Fisher captcha URL in description or fields if image is not explicit
                # Some embeds might hide the image URL in other fields or use a different structure
                # We specifically look for the virtualfisher.com captcha URL pattern
                if 'url' in embed and 'virtualfisher.com/bot/captcha.php' in embed['url']:
                     self.captcha_image = embed['url']
                     self.detected = True
                     return True
        
        # If we reached here and detection flag is set (from keywords), consider captcha detected
        # even if no payload was found (so dispatcher can trigger regen), but avoid returning False.
        return True if self.detected else False

    def request(self) -> None:
        '''Makes a request to the 2Captcha API and appends the result to the answers list.'''
        try:
            if not self.detected: 
                return None
                
            # Handle text-based captcha immediately
            if self.captcha_text:
                self.menu.notify(f'[*] Text Captcha terdeteksi: {self.captcha_text}', NotificationPriority.NORMAL)
                if self.captcha_text not in self.answers:
                    self.answers.append(self.captcha_text)
                self.solving = False
                return
                
            if not self.captcha_image:
                # No image payload available (likely only info message present),
                # stop solving so Dispatcher can trigger /verify regen.
                self.solving = False
                return None
            
            if TwoCaptcha is None:
                self.menu.notify('[!] Library 2Captcha tidak tersedia.', NotificationPriority.HIGH)
                self.solving = False
                return

            self.menu.notify(f'[*] Mengunduh gambar captcha...', NotificationPriority.NORMAL)
            b64_image = self._download_image(self.captcha_image)
            if not b64_image:
                self.menu.notify(f'[!] Gagal mengunduh gambar captcha.', NotificationPriority.HIGH)
                self.solving = False
                return

            self.menu.notify(f'[*] Mengirim ke 2Captcha...', NotificationPriority.NORMAL)
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    solver = TwoCaptcha(self.api_key, softId=5425)
                    # Use normal method for image captcha
                    # Passing base64 string directly
                    # regsense=1 tells 2Captcha to be case-sensitive
                    result = solver.normal(b64_image, regsense=1, numeric=0)
                    
                    # The library returns the code directly or throws exception
                    # Wait, solver.normal returns whatever solve() returns.
                    # solve() returns api_client.res_action() which returns 'request' field (the answer).
                    # So result IS the answer string.
                    
                    # However, looking at library code, if json=1 is used (default?), it returns dict?
                    # solver.py init: extendedResponse=None.
                    # api.py res_action: if json=1, returns resp['request'].
                    # So it returns the answer string.
                    
                    # But let's handle if it returns a dict just in case (some versions do)
                    if isinstance(result, dict) and 'code' in result:
                        answer = result['code']
                    elif isinstance(result, dict) and 'request' in result:
                        answer = result['request']
                    else:
                        answer = str(result)

                    self.menu.notify(f'[*] Captcha terpecahkan: {answer}', NotificationPriority.NORMAL)
                    
                    clean_answer = self.filter(answer)
                    if clean_answer:
                        if clean_answer not in self.answers:
                            self.answers.append(clean_answer)
                    else:
                        if answer not in self.answers:
                            self.answers.append(answer)
                    
                    self.solving = False
                    return # Success, exit function
                    
                except Exception as e:
                    # Print detailed error to console for debugging in EXE
                    error_msg = str(e)
                    print(f"\n[DEBUG] 2Captcha Error Details: {type(e).__name__}: {error_msg}")
                    
                    # Special handling for ERROR_BAD_DUPLICATES
                    if "ERROR_BAD_DUPLICATES" in error_msg:
                        self.menu.notify(f'[!] Gambar ambigu (Bad Duplicates), meminta gambar baru...', NotificationPriority.HIGH)
                        self.solving = False
                        return # Exit to trigger regen in main loop

                    if attempt < max_retries - 1:
                        self.menu.notify(f'[!] Error 2Captcha (Percobaan {attempt+1}/{max_retries}): {e}', NotificationPriority.NORMAL)
                        debugger.log(e, f'{self.name} - 2Captcha error attempt {attempt+1}')
                        sleep(2) # Wait a bit before retrying
                    else:
                        self.menu.notify(f'[!] Gagal 2Captcha setelah {max_retries} kali: {e}', NotificationPriority.HIGH)
                        debugger.log(e, f'{self.name} - 2Captcha library error final')
                        self.solving = False
        except Exception as e:
            debugger.log(e, f'{self.name} - request global catch')
            self.menu.notify(f'[!] Captcha Solver Thread Error: {e}', NotificationPriority.HIGH)
            self.solving = False
            try:
                with open('debug_exit.log', 'a') as f:
                    f.write(f"[{datetime.now()}] [ERROR] Captcha Solver Thread Crash: {e}\n{traceback.format_exc()}\n")
            except: pass

    def solve(self) -> None:
        '''Starts a thread to solve the captcha.'''
        self.solving = True
        Thread(target=self.request, daemon=True).start()
