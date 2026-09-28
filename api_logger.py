"""
ARBPay API Logger
=================
Intercepts and live-logs every API call made during a real browser session.
Uses Chrome DevTools Protocol (CDP) Network events to capture all
requests and responses in real time.

Run this FIRST to discover current API endpoints, headers, and payloads
before running the main bot.

Usage:
    python api_logger.py [--browser chrome|edge] [--headless] [--filter arbpay]
    python api_logger.py --filter apiarbpay  # focus on API calls only

Output:
    Prints colour-coded logs to console + saves to api_logs_<datetime>.txt
"""

import argparse
import json
import os
import threading
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
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService

SITE_URL    = "https://arbpay.me"
LOG_FILE    = f"api_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
PHONE_NUMBER = os.environ.get("PHONE_NUMBER", "")
PASSWORD     = os.environ.get("PASSWORD", "")

RESET="\033[0m"; BOLD="\033[1m"; CYAN="\033[96m"; GREEN="\033[92m"
YELLOW="\033[93m"; RED="\033[91m"; GREY="\033[90m"; BLUE="\033[94m"
MAGENTA="\033[95m"

_log_lock = threading.Lock()
_log_file = open(LOG_FILE, "w", encoding="utf-8")

def log(msg, color=RESET, prefix=""):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{ts}] {prefix}{msg}"
    with _log_lock:
        print(f"{color}{line}{RESET}", flush=True)
        _log_file.write(line + "\n"); _log_file.flush()

_pending: dict = {}
_req_lock = threading.Lock()
_filter_kw = ""

def _should_log(url):
    if not _filter_kw: return True
    return _filter_kw.lower() in url.lower()

def _on_request(params):
    req_id  = params.get("requestId","")
    req     = params.get("request",{})
    url     = req.get("url","")
    method  = req.get("method","GET")
    headers = req.get("headers",{})
    body    = req.get("postData","")
    with _req_lock:
        _pending[req_id] = {"url":url,"method":method,"headers":headers,"body":body,"ts":datetime.now()}
    if _should_log(url):
        path = url
        log(f">> {method} {path}", CYAN, "REQ  ")
        if body:
            try: log(f"   Body: {json.dumps(json.loads(body), ensure_ascii=False)}", BLUE)
            except: log(f"   Body: {body[:300]}", BLUE)
        for k,v in headers.items():
            if k.lower() in ("authorization","devicecode","memberid","devicetype","page","language"):
                log(f"   {k}: {v}", GREY)

def _on_response(params):
    req_id   = params.get("requestId","")
    response = params.get("response",{})
    url      = response.get("url","")
    status   = response.get("status",0)
    mime     = response.get("mimeType","")
    if not _should_log(url): return
    color = GREEN if 200<=status<300 else (YELLOW if status<500 else RED)
    log(f"<< {status} {url} [{mime}]", color, "RES  ")
    with _req_lock:
        if req_id in _pending:
            _pending[req_id]["status"]=status

def _on_response_body(driver, req_id):
    """Try to fetch and log response body via CDP."""
    try:
        r = driver.execute_cdp_cmd("Network.getResponseBody",{"requestId":req_id})
        body = r.get("body","")
        if body:
            try:
                parsed = json.loads(body)
                log(f"   ResponseBody: {json.dumps(parsed, ensure_ascii=False)[:800]}", MAGENTA, "BODY ")
            except:
                log(f"   ResponseBody: {body[:400]}", GREY, "BODY ")
    except: pass

def dump_local_storage(driver):
    """Dump all localStorage keys — critical for seeing token/deviceCode structure."""
    try:
        ls = driver.execute_script(
            "return Object.entries(window.localStorage).reduce((o,[k,v])=>{o[k]=v;return o},{});")
        log("=== localStorage dump ===", BOLD)
        for k,v in ls.items():
            log(f"  {k} = {v[:200]}", CYAN)
    except Exception as e:
        log(f"Could not dump localStorage: {e}", RED)

def build_driver(browser, headless):
    args=["--start-maximized","--no-sandbox","--disable-gpu",
          "--disable-dev-shm-usage","--disable-notifications",
          "--disable-blink-features=AutomationControlled"]
    if browser=="edge":
        opts=EdgeOptions()
        opts.set_capability("goog:loggingPrefs",{"performance":"ALL"})
        if headless: opts.add_argument("--headless=new")
        for a in args: opts.add_argument(a)
        return webdriver.Edge(service=EdgeService(),options=opts)
    opts=uc.ChromeOptions()
    opts.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    if headless: opts.add_argument("--headless=new")
    for a in args: opts.add_argument(a)
    for ver in (None,151,150):
        try:
            kw={"options":opts,"use_subprocess":True}
            if ver: kw["version_main"]=ver
            return uc.Chrome(**kw)
        except: pass
    eo=EdgeOptions()
    eo.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    if headless: eo.add_argument("--headless=new")
    for a in args: eo.add_argument(a)
    return webdriver.Edge(options=eo)

def main():
    global _filter_kw
    p=argparse.ArgumentParser(description="ARBPay API Logger")
    p.add_argument("--browser",default="chrome",choices=["chrome","edge"])
    p.add_argument("--headless",action="store_true")
    p.add_argument("--filter",default="arbpay",help="Only log URLs containing this string")
    args=p.parse_args()
    _filter_kw=args.filter

    driver=build_driver(args.browser,args.headless)

    try:
        driver.execute_cdp_cmd("Network.enable",{})

        # Hook CDP events
        driver.add_cdp_listener("Network.requestWillBeSent", _on_request)
        driver.add_cdp_listener("Network.responseReceived",  _on_response)

        log(f"Opening {SITE_URL} -- log all API calls. Press Ctrl+C to stop.", BOLD)
        log(f"Logs saved to: {LOG_FILE}", GREEN)
        driver.get(SITE_URL)
        time.sleep(2)

        # Dump localStorage now (before login)
        log("=== Pre-login localStorage ===", BOLD)
        dump_local_storage(driver)

        log(f"Log into ARBPay in the browser window manually (or auto-fill below)", YELLOW)
        log(f"Bot will watch network calls for 5 minutes then dump localStorage again", YELLOW)

        for i in range(300):  # watch for 5 minutes
            time.sleep(1)
            if i % 30 == 29:
                log(f"Still watching... ({i+1}s elapsed)", GREY)
                dump_local_storage(driver)

        log("=== Final localStorage dump ===", BOLD)
        dump_local_storage(driver)
        log(f"Done. All logs saved to {LOG_FILE}", GREEN)

    except KeyboardInterrupt:
        log("Interrupted -- saving logs...", YELLOW)
        dump_local_storage(driver)
        log(f"Logs saved to {LOG_FILE}", GREEN)
    finally:
        try: _log_file.close()
        except: pass
        try: driver.quit()
        except: pass

if __name__=="__main__": main()
