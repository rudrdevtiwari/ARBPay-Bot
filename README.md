# ARBPay Bot

> **For educational / research purposes only.**
> Using automated bots may violate ARBPay's Terms of Service. Use at your own risk.

Automated buy bot for the [ARBPay](https://arbpay.me) platform.
Captures auth tokens from a live browser session and runs a high-speed buy loop
against the ARBPay API — bypassing Cloudflare via `undetected-chromedriver`.

---

## Repository Structure

```
ARBPay-Bot/
+-- ARBPay_bot.py        # Main buy bot (Chrome / Edge)
+-- api_logger.py        # Live API call logger (CDP-based)
+-- requirements.txt     # Python dependencies
+-- .env.example         # Credentials template
+-- .gitignore
+-- README.md
```

---

## Setup

```bash
# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS / Linux

# Install dependencies
pip install -r requirements.txt

# Set credentials
copy .env.example .env       # Windows
cp .env.example .env         # macOS / Linux
# Then edit .env and fill in PHONE_NUMBER and PASSWORD
```

---

## Usage

### 1. Run the API Logger first (recommended)

Use this to discover the current live API structure and any changes to endpoints or headers.

```bash
python api_logger.py
python api_logger.py --filter apiarbpay   # filter to API calls only
```

Log into ARBPay in the browser window. The logger captures all network traffic
and dumps `localStorage` (where the session token lives) to the console and a log file.

---

### 2. Run the main bot

```bash
# Basic (Chrome, visible window)
python ARBPay_bot.py

# With options
python ARBPay_bot.py --browser edge --headless --min 100 --max 2000 --loops 5
```

| Flag        | Default   | Description                              |
|-------------|-----------|------------------------------------------|
| `--browser` | `chrome`  | `chrome` or `edge`                       |
| `--headless`| off       | Run without a visible browser window     |
| `--min`     | `100`     | Minimum order amount to target (?)       |
| `--max`     | `5000`    | Maximum order amount to target (?)       |
| `--loops`   | `0`       | Max successful buys; `0` = infinite      |

---

## How It Works

```
1. Launch Chrome (undetected-chromedriver) ? bypass Cloudflare detection
2. Auto-fill login using PHONE_NUMBER + PASSWORD from .env
3. Wait for token to appear in localStorage
4. Extract: token, deviceCode, memberId, live API host (runtime-domains:PRO)
5. Enter tight buy loop:
       buyList  ? filter orders in [--min, --max] range
       beforeBuy ? reserve slot
       buy       ? confirm (cycle bank codes on code 2005 rejection)
6. On success ? reload page to show QR payment screen
```

### Bank Code Cycling

When the server returns rejection code `2005`, the bot automatically cycles through:
```
supermoney ? paytm ? phonepe ? gpay ? mobikwik ? freeCharge ?
airtel ? jio ? freo ? slice ? twid ? pop ? navi ? moneyView ? induspay
```

### API Endpoints Used

| Method | Path                                               | Purpose          |
|--------|----------------------------------------------------|------------------|
| POST   | `/ar-wallet/buyCenter/buyList`                     | Fetch orders     |
| POST   | `/ar-wallet/buyCenter/beforeBuy`                   | Reserve slot     |
| POST   | `/ar-wallet/buyCenter/buy`                         | Confirm purchase |
| POST   | `/ar-wallet/buyCenter/getPaymentPageDataEncryption`| QR/payment data  |

### Request Headers

```
authorization: Bearer <token>
deviceCode:    <deviceCode>
memberId:      <memberId>
deviceType:    3
language:      1
page:          Arb
```

---

## Cloudflare Bypass Strategy

All API calls are executed **inside** the Chrome browser via synchronous `XMLHttpRequest`
(injected via Selenium `execute_script`). This means:

- The requests inherit all browser cookies and TLS fingerprint
- Cloudflare sees a real Chrome session, not Python `requests`
- No need for proxies or CAPTCHA solvers

---

## Disclaimer

This project is provided for **educational and research purposes only**.
The author is not responsible for any misuse or violations of third-party Terms of Service.
