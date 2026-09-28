"""
ARBPay Automated Buy Bot (v2.2 Updated)
=======================================
Optimized for the latest ARBPay multi-node architecture (paykuno / payduno clusters).
- Auto-handles the arbpay.me node dispatcher redirect
- Vue/Vant reactive v-model event simulation for seamless login
- Cloudflare bypass via undetected-chromedriver
- In-browser synchronous XHR injection for high-speed buy sniping
- Bank code auto-cycling on code 2005 rejections

Usage:
    python ARBPay_bot.py [--browser chrome|edge] [--headless]
                         [--min 100] [--max 5000] [--loops 0]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

import undetected_chromedriver as uc
from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService

ENTRY_URL = "https://arbpay.me"
FALLBACK_API_URLS = [
    "https://apiweb.apiarbpay.com",
    "https://apiweb.payapiar.com",
    "https://apiweb.asjoby.com",
    "https://apiweb.arbpay.me",
]
API_URL = FALLBACK_API_URLS[0]
CURRENT_NODE_URL = ""

PHONE_NUMBER = os.environ.get("PHONE_NUMBER", "")
PASSWORD     = os.environ.get("PASSWORD", "")

CLICK_INTERVAL  = 0.0
INPUT_SETTLE    = 0.1
SESSION_TIMEOUT = 35

BANK_CODES = [
    "supermoney", "paytm", "phonepe", "gpay", "mobikwik",
    "freeCharge", "airtel", "jio", "freo", "slice",
    "twid", "pop", "navi", "moneyView", "induspay",
]

RESET="\033[0m"; BOLD="\033[1m"; CYAN="\033[96m"; GREEN="\033[92m"
YELLOW="\033[93m"; RED="\033[91m"; GREY="\033[90m"; MAGENTA="\033[95m"

_api_driver      = None
_api_token       = ""
_api_device_code = ""
_api_member_id   = ""
_buylist_call_count = 0


def log(message, color=RESET):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{color}[{ts}] {message}{RESET}", flush=True)


def build_driver(browser, headless):
    log(f"Starting {browser} browser...", CYAN)
    args = [
        "--start-maximized", "--no-sandbox", "--disable-gpu",
        "--disable-dev-shm-usage", "--disable-notifications",
        "--disable-popup-blocking", "--disable-blink-features=AutomationControlled"
    ]
    if browser == "edge":
        opts = EdgeOptions()
        opts.add_experimental_option("detach", True)
        opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        if headless: opts.add_argument("--headless=new")
        for a in args: opts.add_argument(a)
        return webdriver.Edge(service=EdgeService(), options=opts)

    opts = uc.ChromeOptions()
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    if headless: opts.add_argument("--headless=new")
    for a in args: opts.add_argument(a)

    try:
        driver = uc.Chrome(options=opts, use_subprocess=True)
        log("Chrome browser initialized successfully.", GREEN)
        return driver
    except Exception as e:
        log(f"[WARN] Chrome start error ({e}), retrying with version_main=154...", YELLOW)
        try:
            return uc.Chrome(options=opts, version_main=154, use_subprocess=True)
        except Exception as e2:
            log(f"[WARN] Version 154 failed ({e2}), falling back to Edge...", RED)
            eo = EdgeOptions()
            eo.set_capability("goog:loggingPrefs", {"performance": "ALL"})
            if headless: eo.add_argument("--headless=new")
            for a in args: eo.add_argument(a)
            return webdriver.Edge(options=eo)


def wait_for_node_redirect(driver):
    """Wait for arbpay.me to finish node evaluation and redirect to active cluster."""
    global CURRENT_NODE_URL
    log("Waiting for node dispatcher to resolve active cluster...", CYAN)
    deadline = time.time() + 25
    while time.time() < deadline:
        cur = driver.current_url
        if "arbpay.me" not in cur and ("#" in cur or "pay" in cur):
            CURRENT_NODE_URL = cur.split("#")[0].rstrip("/")
            log(f"Resolved active cluster node: {CURRENT_NODE_URL}", MAGENTA)
            return True
        time.sleep(1)
    CURRENT_NODE_URL = driver.current_url.split("#")[0].rstrip("/")
    log(f"Using node URL: {CURRENT_NODE_URL}", GREY)
    return True


def login(driver):
    global CURRENT_NODE_URL
    if not PHONE_NUMBER or not PASSWORD:
        log("ERROR: PHONE_NUMBER and PASSWORD must be set in .env", RED)
        return False

    log(f"Navigating to {ENTRY_URL} ...", CYAN)
    driver.get(ENTRY_URL)
    wait_for_node_redirect(driver)

    # Ensure on login route
    if "#/login" not in driver.current_url:
        login_url = f"{CURRENT_NODE_URL}/#/login"
        log(f"Opening login route: {login_url}", CYAN)
        driver.get(login_url)
        time.sleep(2)

    try:
        # Dismiss overlays if any
        for sel in (".van-overlay", ".popup-close", "[class*='close']"):
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, sel):
                    if el.is_displayed():
                        el.click()
            except: pass

        # Locate phone & password inputs
        time.sleep(1.5)
        phone_input = None
        pwd_input   = None

        for inp in driver.find_elements(By.TAG_NAME, "input"):
            plh = (inp.get_attribute("placeholder") or "").lower()
            itype = (inp.get_attribute("type") or "").lower()
            if "phone" in plh:
                phone_input = inp
            elif "password" in plh or itype == "password":
                pwd_input = inp

        if not phone_input or not pwd_input:
            inps = driver.find_elements(By.TAG_NAME, "input")
            if len(inps) >= 2:
                phone_input, pwd_input = inps[0], inps[1]

        if not phone_input or not pwd_input:
            log("Could not locate phone or password input fields", RED)
            return False

        # Set values and dispatch Vue/React reactive events
        js_set = """
        function fillInput(el, val) {
            let lastVal = el.value;
            el.value = val;
            let ev = new Event('input', { bubbles: true });
            let tracker = el._valueTracker;
            if (tracker) tracker.setValue(lastVal);
            el.dispatchEvent(ev);
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }
        fillInput(arguments[0], arguments[1]);
        fillInput(arguments[2], arguments[3]);
        """
        driver.execute_script(js_set, phone_input, PHONE_NUMBER, pwd_input, PASSWORD)
        time.sleep(0.3)
        log("Credentials injected with reactive event dispatch.", GREY)

        # Submit login
        submit_btn = None
        for btn in driver.find_elements(By.TAG_NAME, "button"):
            txt = btn.text.strip().lower()
            if any(w in txt for w in ("log in", "login", "submit", "??")):
                submit_btn = btn
                break

        if submit_btn:
            driver.execute_script("arguments[0].click();", submit_btn)
        else:
            pwd_input.send_keys(Keys.RETURN)

        log("Login submitted — waiting for auth token...", CYAN)

        # Poll localStorage for token
        deadline = time.time() + SESSION_TIMEOUT
        while time.time() < deadline:
            try:
                ls = driver.execute_script(
                    "return Object.entries(window.localStorage).reduce((o,[k,v])=>{o[k]=v;return o},{});"
                )
                raw_tok = ls.get("token", "")
                if raw_tok:
                    val = json.loads(raw_tok).get("value", raw_tok) if raw_tok.startswith("{") else raw_tok
                    if val and len(val) > 10:
                        log("Auth token acquired from localStorage! ?", GREEN)
                        return True
            except: pass

            # Check if page redirected away from login
            if "#/login" not in driver.current_url and ("#/" in driver.current_url or "#/home" in driver.current_url):
                time.sleep(1)
                ls = driver.execute_script(
                    "return Object.entries(window.localStorage).reduce((o,[k,v])=>{o[k]=v;return o},{});"
                )
                if "token" in ls:
                    log("Session established successfully! ?", GREEN)
                    return True

            time.sleep(1)

        log("Session wait timed out. If captcha was shown, solve it manually.", YELLOW)
        return False

    except Exception as e:
        log(f"Login error: {e}", RED)
        return False


def build_api_session(driver):
    global _api_driver, _api_token, _api_device_code, _api_member_id, API_URL
    try:
        ls = driver.execute_script(
            "return Object.entries(window.localStorage).reduce((o,[k,v])=>{o[k]=v;return o},{});"
        )
    except Exception as e:
        log(f"localStorage read failed: {e}", RED)
        return False

    def _parse(key):
        raw = ls.get(key, "")
        if not raw: return ""
        if raw.startswith("{"):
            try: return json.loads(raw).get("value", raw)
            except: return raw
        return raw

    token       = _parse("token")
    device_code = _parse("deviceCode")
    member_id   = _parse("memberId")

    if not member_id:
        for k, v in ls.items():
            if ("member" in k.lower() or "userid" in k.lower()) and str(v).isdigit():
                member_id = str(v)
                break

    # Extract dynamic API URL from runtime-domains
    rd_raw = ls.get("runtime-domains:PRO") or ls.get("runtime-domains:pro")
    if rd_raw:
        try:
            rd = json.loads(rd_raw)
            live_api = rd.get("selections", {}).get("api", "")
            if live_api and live_api.startswith("http"):
                API_URL = live_api.rstrip("/")
                log(f"Dynamic API endpoint active: {API_URL}", MAGENTA)
        except: pass

    if not token:
        log("No token in localStorage", RED)
        return False

    _api_driver      = driver
    _api_token       = token
    _api_device_code = device_code
    _api_member_id   = member_id
    log(f"API session ready — Token ...{token[-12:]} | Member: {member_id or 'N/A'}", GREEN)
    return True


_XHR_JS = """
var xhr = new XMLHttpRequest();
xhr.open('POST', arguments[0], false);
xhr.setRequestHeader('Accept', 'application/json, text/plain, */*');
xhr.setRequestHeader('Content-Type', 'application/json');
xhr.setRequestHeader('authorization', 'Bearer ' + arguments[2]);
xhr.setRequestHeader('deviceCode', arguments[3]);
xhr.setRequestHeader('deviceId', '');
xhr.setRequestHeader('deviceType', '3');
xhr.setRequestHeader('language', '1');
xhr.setRequestHeader('page', arguments[4]);
if (arguments[5]) { xhr.setRequestHeader('memberId', String(arguments[5])); }
try {
    xhr.send(JSON.stringify(arguments[1]));
    return {ok: true, status: xhr.status, text: xhr.responseText};
} catch(e) {
    return {ok: false, status: 0, text: String(e)};
}
"""

def browser_fetch(path, body, page="Arb"):
    global _api_driver, _api_token, _api_device_code, _api_member_id, _buylist_call_count
    if not _api_driver: return {}
    for base in [API_URL] + [u for u in FALLBACK_API_URLS if u != API_URL]:
        try:
            r = _api_driver.execute_script(
                _XHR_JS, f"{base}{path}", body,
                _api_token, _api_device_code, page, _api_member_id
            )
            if not r: continue
            s = r.get("status", 0)
            if not r.get("ok") or s not in (200, 201): continue
            t = r.get("text", "")
            if not t: continue
            return json.loads(t)
        except Exception as e:
            if _buylist_call_count <= 1:
                log(f"[DEBUG] fetch {base}{path}: {e}", GREY)
    return {}


def _get_code(r):
    for k in ("code", "status", "resultCode", "bizCode"):
        if k in r: return int(r[k])
    return -1

def _get_msg(r):
    for k in ("msg", "message", "resultMsg", "info"):
        if k in r: return str(r[k])
    return str(r)

def _get_data(r):
    for k in ("data", "result", "body"):
        if k in r: return r[k]
    return r


def api_get_order_list(amin, amax):
    global _buylist_call_count
    _buylist_call_count += 1
    data = browser_fetch("/ar-wallet/buyCenter/buyList", {"orderType": 1, "pageNo": 1})
    if _buylist_call_count == 1:
        log(f"[DEBUG] buyList payload: {json.dumps(data)[:400]}", GREY)

    records = []
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        for tk in ("data", "result", "body", "response"):
            inner = data.get(tk)
            if inner is None: continue
            if isinstance(inner, list): records = inner; break
            if isinstance(inner, dict):
                for sk in ("records", "list", "rows", "data", "items", "content"):
                    v = inner.get(sk)
                    if v and isinstance(v, list): records = v; break
                if records: break

    return [o for o in records if amin <= float(o.get("amount", 0)) <= amax]


def api_before_buy(porder, amount, bank_code="", pay_type="3", order_type=1):
    pl = {"amount": amount, "platformOrder": porder, "payType": pay_type, "orderType": order_type}
    if pay_type == "3" and bank_code: pl["buyBankCode"] = bank_code
    return browser_fetch("/ar-wallet/buyCenter/beforeBuy", pl)


def api_buy(porder, amount, bank_code="paytm", kyc_id=0, pay_type="3", order_type=1):
    pl = {"amount": amount, "platformOrder": porder, "payType": pay_type, "orderType": order_type}
    if pay_type == "3" and bank_code:
        pl["buyBankCode"] = bank_code
        pl["buyerKycId"]  = kyc_id
    return browser_fetch("/ar-wallet/buyCenter/buy", pl)


def buy_loop(driver, amin, amax, max_loops):
    global _buylist_call_count
    bank_idx = 0
    success_count = 0
    idle_logged = False
    _buylist_call_count = 0

    log(f"Buy loop running -- target: Rs.{amin}-Rs.{amax} | limit={'Infinite' if max_loops == 0 else max_loops} orders", BOLD)

    while True:
        if max_loops > 0 and success_count >= max_loops:
            log(f"Goal reached ({max_loops} orders) -- finishing.", GREEN)
            break

        orders = api_get_order_list(amin, amax)
        if not orders:
            if not idle_logged:
                log("Scanning order book (waiting for orders in range)...", GREY)
                idle_logged = True
            time.sleep(CLICK_INTERVAL or 0.05)
            continue

        idle_logged = False
        log(f"Found {len(orders)} matching order(s)!", CYAN)

        for order in orders:
            porder = order.get("platformOrder") or order.get("orderId") or order.get("id", "")
            amount = float(order.get("amount", 0))
            otype  = int(order.get("orderType", 1))
            if not porder: continue

            bcode = BANK_CODES[bank_idx % len(BANK_CODES)]
            log(f"Sniping {porder} (Rs.{amount}) using [{bcode}] ...", CYAN)

            # 1. beforeBuy
            bb = api_before_buy(porder, amount, bcode, order_type=otype)
            bbc = _get_code(bb)
            if bbc not in (0, 200, 1):
                log(f"  beforeBuy skipped ({bbc}): {_get_msg(bb)}", YELLOW)
                bank_idx += 1
                continue

            # 2. buy
            kyc = _get_data(bb).get("buyerKycId", 0) if isinstance(_get_data(bb), dict) else 0
            br  = api_buy(porder, amount, bcode, kyc, order_type=otype)
            brc = _get_code(br)

            if brc == 2005:
                log(f"  Bank rejected (2005) -- switching bank from {bcode}", YELLOW)
                bank_idx += 1
                continue

            if brc in (0, 200, 1):
                success_count += 1
                mr = _get_data(br)
                if isinstance(mr, dict):
                    mr = mr.get("platformOrder") or mr.get("mrOrder") or porder
                else:
                    mr = porder
                log(f"  SUCCESS #{success_count} -- Order {mr} (Rs.{amount}) captured!", GREEN)

                # Open payment view
                try:
                    driver.get(f"{CURRENT_NODE_URL}/#/")
                except: pass
                time.sleep(1)

                if max_loops > 0 and success_count >= max_loops: break
            else:
                log(f"  Buy error ({brc}): {_get_msg(br)}", RED)
                bank_idx += 1

        time.sleep(CLICK_INTERVAL)


def main():
    p = argparse.ArgumentParser(description="ARBPay automated buy bot")
    p.add_argument("--browser",  default="chrome", choices=["chrome", "edge"])
    p.add_argument("--headless", action="store_true")
    p.add_argument("--min",      type=float, default=100)
    p.add_argument("--max",      type=float, default=5000)
    p.add_argument("--loops",    type=int,   default=0)
    args = p.parse_args()

    driver = build_driver(args.browser, args.headless)
    try:
        if not login(driver):
            driver.quit(); sys.exit(1)
        if not build_api_session(driver):
            driver.quit(); sys.exit(1)

        fails = 0
        while True:
            try:
                buy_loop(driver, args.min, args.max, args.loops)
                break
            except WebDriverException as e:
                log(f"WebDriver exception: {e}", RED)
                fails += 1
                if fails >= 3:
                    log("Exceeded maximum retries.", RED); break
                time.sleep(2)
                build_api_session(driver)
    except KeyboardInterrupt:
        log("Bot stopped by user.", YELLOW)
    finally:
        try:
            driver.quit()
        except: pass


if __name__ == "__main__":
    main()
