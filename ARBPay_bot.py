"""
ARBPay Automated Buy Bot
========================
Logs into ARBPay, extracts auth session from localStorage, then runs a
high-speed buy loop via in-browser XHR -- inheriting all cookies/session
so Cloudflare never sees raw Python requests.

Usage:
    python ARBPay_bot.py [--browser chrome|edge] [--headless]
                         [--min 100] [--max 5000] [--loops 0]

Credentials are read from a .env file in the same directory:
    PHONE_NUMBER=your_phone
    PASSWORD=your_password
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

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
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


SITE_URL = "https://arbpay.me"
API_URLS = [
    "https://apiweb.apiarbpay.com",
    "https://apiweb.payapiar.com",
    "https://apiweb.asjoby.com",
    "https://apiweb.arbpay.me",
]
API_URL = API_URLS[0]

PHONE_NUMBER = os.environ.get("PHONE_NUMBER", "")
PASSWORD     = os.environ.get("PASSWORD", "")

CLICK_INTERVAL  = 0.0
POPUP_PAUSE     = 0.1
INPUT_SETTLE    = 0.05
LOGIN_SETTLE    = 0.5
SESSION_TIMEOUT = 30

BANK_CODES = [
    "supermoney","paytm","phonepe","gpay","mobikwik",
    "freeCharge","airtel","jio","freo","slice",
    "twid","pop","navi","moneyView","induspay",
]

RESET="\033[0m"; BOLD="\033[1m"; CYAN="\033[96m"; GREEN="\033[92m"
YELLOW="\033[93m"; RED="\033[91m"; GREY="\033[90m"; MAGENTA="\033[95m"

_api_driver=None; _api_token=""; _api_device_code=""; _api_member_id=""
_buylist_call_count=0


def log(message, color=RESET):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{color}[{ts}] {message}{RESET}", flush=True)


def build_driver(browser, headless):
    log(f"Starting {browser} browser ...", CYAN)
    args = ["--start-maximized","--no-sandbox","--disable-gpu",
            "--disable-dev-shm-usage","--disable-notifications",
            "--disable-popup-blocking","--disable-blink-features=AutomationControlled"]
    if browser == "edge":
        opts = EdgeOptions()
        opts.add_experimental_option("detach", True)
        opts.set_capability("goog:loggingPrefs", {"performance":"ALL"})
        if headless: opts.add_argument("--headless=new")
        for a in args: opts.add_argument(a)
        return webdriver.Edge(service=EdgeService(), options=opts)
    opts = uc.ChromeOptions()
    opts.set_capability("goog:loggingPrefs", {"performance":"ALL"})
    if headless: opts.add_argument("--headless=new")
    for a in args: opts.add_argument(a)
    for ver in (None, 151, 150):
        try:
            kw = {"options":opts,"use_subprocess":True}
            if ver: kw["version_main"]=ver
            d = uc.Chrome(**kw)
            log(f"Chrome started (ver={ver or 'auto'})", GREEN)
            return d
        except Exception as e:
            log(f"[WARN] {e}", YELLOW)
    log("Falling back to Edge", YELLOW)
    eo=EdgeOptions(); eo.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    if headless: eo.add_argument("--headless=new")
    for a in args: eo.add_argument(a)
    return webdriver.Edge(options=eo)


def enable_cdp_network(driver):
    try: driver.execute_cdp_cmd("Network.enable", {})
    except: pass


def login(driver):
    if not PHONE_NUMBER or not PASSWORD:
        log("ERROR: PHONE_NUMBER and PASSWORD must be set in .env", RED); return False
    log(f"Opening {SITE_URL}", CYAN)
    driver.get(SITE_URL); time.sleep(2)
    try:
        for sel in (".van-overlay",".popup-close","[class*='close']"):
            try:
                b=driver.find_element(By.CSS_SELECTOR,sel)
                if b.is_displayed(): b.click(); time.sleep(POPUP_PAUSE)
            except: pass
        driver.get(f"{SITE_URL}/#/login"); time.sleep(1.5)
        phone_el=None
        for sel in ["input[type='tel']","input[placeholder*='phone']",
                    "input[placeholder*='Phone']","input[name='phone']",".van-field__control"]:
            try:
                els=driver.find_elements(By.CSS_SELECTOR,sel)
                if els: phone_el=els[0]; break
            except: pass
        if not phone_el: log("Phone input not found",RED); return False
        phone_el.clear(); phone_el.send_keys(PHONE_NUMBER); time.sleep(INPUT_SETTLE)
        pwd_el=None
        for sel in ["input[type='password']","input[placeholder*='password']",
                    "input[placeholder*='Password']","input[name='password']"]:
            try:
                els=driver.find_elements(By.CSS_SELECTOR,sel)
                if els: pwd_el=els[0]; break
            except: pass
        if not pwd_el: log("Password input not found",RED); return False
        pwd_el.clear(); pwd_el.send_keys(PASSWORD); time.sleep(INPUT_SETTLE)
        submitted=False
        for sel in ["button[type='submit']",".login-btn","button.van-button--primary",".van-button--block","button"]:
            try:
                for btn in driver.find_elements(By.CSS_SELECTOR,sel):
                    if any(w in btn.text.lower() for w in ("login","sign","log in","submit")):
                        btn.click(); submitted=True; break
            except: pass
            if submitted: break
        if not submitted: pwd_el.send_keys(Keys.RETURN)
        time.sleep(LOGIN_SETTLE); log("Login submitted -- waiting for session ...", CYAN)
        deadline=time.time()+SESSION_TIMEOUT
        while time.time()<deadline:
            try:
                raw=driver.execute_script("return window.localStorage.getItem('token');")
                if raw:
                    p=json.loads(raw) if raw.startswith("{") else {}
                    tok=p.get("value",raw) if p else raw
                    if tok and len(tok)>10: log("Token found ?", GREEN); return True
            except: pass
            time.sleep(0.5)
        log("Timed out waiting for token", RED); return False
    except Exception as e:
        log(f"Login error: {e}", RED); return False


def build_api_session(driver):
    global _api_driver,_api_token,_api_device_code,_api_member_id,API_URL
    try:
        ls=driver.execute_script(
            "return Object.entries(window.localStorage).reduce((o,[k,v])=>{o[k]=v;return o},{});")
    except Exception as e:
        log(f"localStorage read failed: {e}", RED); return False
    def _p(key):
        raw=ls.get(key,"")
        if not raw: return ""
        if raw.startswith("{"):
            try: return json.loads(raw).get("value",raw)
            except: return raw
        return raw
    token=_p("token"); device_code=_p("deviceCode"); member_id=_p("memberId")
    if not member_id:
        for k,v in ls.items():
            if ("member" in k.lower() or "userid" in k.lower()) and str(v).isdigit():
                member_id=str(v); break
    rd_raw=ls.get("runtime-domains:PRO") or ls.get("runtime-domains:pro")
    if rd_raw:
        try:
            rd=json.loads(rd_raw); live=rd.get("selections",{}).get("api","")
            if live and live.startswith("http"):
                API_URL=live.rstrip("/"); log(f"Dynamic API: {API_URL}", MAGENTA)
        except: pass
    if not token: log("No token in localStorage", RED); return False
    _api_driver=driver; _api_token=token; _api_device_code=device_code; _api_member_id=member_id
    log(f"Session ready -- token=...{token[-12:]} | memberId={member_id or 'N/A'}", GREEN)
    return True


_XHR_JS="""
var xhr=new XMLHttpRequest();
xhr.open('POST',arguments[0],false);
xhr.setRequestHeader('Accept','application/json, text/plain, */*');
xhr.setRequestHeader('Content-Type','application/json');
xhr.setRequestHeader('authorization','Bearer '+arguments[2]);
xhr.setRequestHeader('deviceCode',arguments[3]);
xhr.setRequestHeader('deviceId','');
xhr.setRequestHeader('deviceType','3');
xhr.setRequestHeader('language','1');
xhr.setRequestHeader('page',arguments[4]);
if(arguments[5]){xhr.setRequestHeader('memberId',String(arguments[5]));}
try{xhr.send(JSON.stringify(arguments[1]));return{ok:true,status:xhr.status,text:xhr.responseText};}
catch(e){return{ok:false,status:0,text:String(e)};}
"""


def browser_fetch(path, body, page="Arb"):
    global _api_driver,_api_token,_api_device_code,_api_member_id,_buylist_call_count
    if not _api_driver: return {}
    for base in [API_URL]+[u for u in API_URLS if u!=API_URL]:
        try:
            r=_api_driver.execute_script(_XHR_JS,f"{base}{path}",body,
                                          _api_token,_api_device_code,page,_api_member_id)
            if not r: continue
            s=r.get("status",0)
            if not r.get("ok") or s not in (200,201): continue
            t=r.get("text","")
            if not t: continue
            return json.loads(t)
        except Exception as e:
            if _buylist_call_count<=1: log(f"[DEBUG] fetch {base}{path}: {e}", GREY)
    return {}


def _get_code(r): 
    for k in ("code","status","resultCode","bizCode"):
        if k in r: return int(r[k])
    return -1

def _get_msg(r):
    for k in ("msg","message","resultMsg","info"):
        if k in r: return str(r[k])
    return str(r)

def _get_data(r):
    for k in ("data","result","body"):
        if k in r: return r[k]
    return r


def api_get_order_list(amin, amax):
    global _buylist_call_count
    _buylist_call_count+=1
    data=browser_fetch("/ar-wallet/buyCenter/buyList",{"orderType":1,"pageNo":1})
    if _buylist_call_count==1: log(f"[DEBUG] buyList: {json.dumps(data)[:500]}", GREY)
    records=[]
    if isinstance(data,list): records=data
    elif isinstance(data,dict):
        for tk in ("data","result","body","response"):
            inner=data.get(tk)
            if inner is None: continue
            if isinstance(inner,list): records=inner; break
            if isinstance(inner,dict):
                for sk in ("records","list","rows","data","items","content"):
                    v=inner.get(sk)
                    if v and isinstance(v,list): records=v; break
                if records: break
    return [o for o in records if amin<=float(o.get("amount",0))<=amax]


def api_before_buy(porder, amount, bank_code="", pay_type="3", order_type=1):
    pl={"amount":amount,"platformOrder":porder,"payType":pay_type,"orderType":order_type}
    if pay_type=="3" and bank_code: pl["buyBankCode"]=bank_code
    return browser_fetch("/ar-wallet/buyCenter/beforeBuy", pl)


def api_buy(porder, amount, bank_code="paytm", kyc_id=0, pay_type="3", order_type=1):
    pl={"amount":amount,"platformOrder":porder,"payType":pay_type,"orderType":order_type}
    if pay_type=="3" and bank_code: pl["buyBankCode"]=bank_code; pl["buyerKycId"]=kyc_id
    return browser_fetch("/ar-wallet/buyCenter/buy", pl)


def api_get_qr(mr_order):
    return browser_fetch("/ar-wallet/buyCenter/getPaymentPageDataEncryption",{"platformOrder":mr_order})


def buy_loop(driver, amin, amax, max_loops):
    global _buylist_call_count
    bank_idx=0; success_count=0; idle_logged=False
    _buylist_call_count=0
    log(f"Buy loop started -- range Rs.{amin}-Rs.{amax} | target={'inf' if max_loops==0 else max_loops} buys", BOLD)
    while True:
        if max_loops>0 and success_count>=max_loops:
            log(f"Reached {max_loops} successful buys -- stopping.", GREEN); break
        orders=api_get_order_list(amin,amax)
        if not orders:
            if not idle_logged: log("No orders in range -- watching...", GREY); idle_logged=True
            time.sleep(CLICK_INTERVAL or 0.05); continue
        idle_logged=False
        log(f"Found {len(orders)} order(s)", CYAN)
        for order in orders:
            porder=order.get("platformOrder") or order.get("orderId") or order.get("id","")
            amount=float(order.get("amount",0))
            otype=int(order.get("orderType",1))
            if not porder: continue
            bcode=BANK_CODES[bank_idx%len(BANK_CODES)]
            log(f"Trying {porder} Rs.{amount} [{bcode}]", CYAN)
            bb=api_before_buy(porder,amount,bcode,order_type=otype)
            bbc=_get_code(bb)
            if bbc not in (0,200,1):
                log(f"  beforeBuy rejected ({bbc}): {_get_msg(bb)}", YELLOW); bank_idx+=1; continue
            kyc=_get_data(bb).get("buyerKycId",0) if isinstance(_get_data(bb),dict) else 0
            br=api_buy(porder,amount,bcode,kyc,order_type=otype)
            brc=_get_code(br)
            if brc==2005:
                log(f"  buy rejected 2005 -- cycling from {bcode}", YELLOW); bank_idx+=1; continue
            if brc in (0,200,1):
                success_count+=1
                mr=_get_data(br)
                if isinstance(mr,dict): mr=mr.get("platformOrder") or mr.get("mrOrder") or porder
                else: mr=porder
                log(f"  SUCCESS #{success_count} -- order {mr} Rs.{amount}", GREEN)
                driver.get(f"{SITE_URL}/#/"); time.sleep(1)
                if max_loops>0 and success_count>=max_loops: break
            else:
                log(f"  buy failed ({brc}): {_get_msg(br)}", RED); bank_idx+=1
        time.sleep(CLICK_INTERVAL)


def main():
    p=argparse.ArgumentParser(description="ARBPay automated buy bot")
    p.add_argument("--browser",default="chrome",choices=["chrome","edge"])
    p.add_argument("--headless",action="store_true")
    p.add_argument("--min",type=float,default=100)
    p.add_argument("--max",type=float,default=5000)
    p.add_argument("--loops",type=int,default=0)
    args=p.parse_args()
    driver=build_driver(args.browser,args.headless)
    enable_cdp_network(driver)
    try:
        if not login(driver): driver.quit(); sys.exit(1)
        if not build_api_session(driver): driver.quit(); sys.exit(1)
        fails=0
        while True:
            try: buy_loop(driver,args.min,args.max,args.loops); break
            except WebDriverException as e:
                log(f"WebDriver error: {e}",RED); fails+=1
                if fails>=3: log("Too many failures",RED); break
                time.sleep(2); build_api_session(driver)
    except KeyboardInterrupt: log("Interrupted",YELLOW)
    finally:
        try: driver.quit()
        except: pass

if __name__=="__main__": main()
