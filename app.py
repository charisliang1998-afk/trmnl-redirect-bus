# ==== CONFIG ===============================================================
# You can paste EITHER:
#  - the full Apps Script /exec URL, e.g. "https://script.google.com/macros/s/AKfycb.../exec"
#  - OR just the Deployment ID, e.g. "AKfycb..."
# You can also set this as an env var named GAS_DEPLOYMENT in Render.
GAS_DEPLOYMENT = "https://script.google.com/macros/s/AKfycbyJwiSxqW-AjsTxrqNFCZA_0tp8bwqAjRDOXai0a9fcAiEhi3QV8_LGbQRtR_X7QYsR/exec"

# Default bus stops (can be overridden via query string)
DEFAULT_A, DEFAULT_B, DEFAULT_C = "45379", "45489", "45371"
# ==========================================================================

from flask import Flask, request, jsonify, send_file
import os, io, time, requests
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

# ---- GAS helpers ----------------------------------------------------------
def gas_base_url():
    # Prefer env var if set in Render dashboard
    val = (os.getenv("GAS_DEPLOYMENT") or GAS_DEPLOYMENT or "").strip()
    if not val:
        return ""
    if val.startswith("http"):
        return val.split("?")[0]  # strip any old query string
    return f"https://script.google.com/macros/s/{val}/exec"

def fetch_bus(stopa, stopb, stopc, timeout_sec=5):
    url = gas_base_url()
    if not url:
        return _empty_payload(stopa, stopb, stopc)
    try:
        r = requests.get(url, params={"stop_a": stopa, "stop_b": stopb, "stop_c": stopc}, timeout=timeout_sec)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("GAS fetch failed:", repr(e))
        return _empty_payload(stopa, stopb, stopc)

def _empty_payload(a, b, c):
    return {
        "stop_a": {"name": f"{a}", "code": a, "services": []},
        "stop_b": {"name": f"{b}", "code": b, "services": []},
        "stop_c": {"name": f"{c}", "code": c, "services": []},
    }

import os
from PIL import Image, ImageDraw, ImageFont

# Absolute paths to your Inter variable fonts
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_REG_PATH   = os.path.join(BASE_DIR, "fonts", "Inter-VariableFont_opsz,wght.ttf")
# We’ll stick to the regular face for clarity on e-ink; italic is available if you want.
FONT_ITALIC_PATH= os.path.join(BASE_DIR, "fonts", "Inter-Italic-VariableFont_opsz,wght.ttf")

# Font sizes tuned for 800x480 e-ink
STAMP_SIZE = 14      # "Updated HH:MM"
NAME_SIZE  = 34      # Stop name
SVC_SIZE   = 32      # Route number (left column)
TIME_SIZE  = 28      # Each vertical time line

# Spacing & geometry (px)
W, H                 = 800, 480
PAD_L, PAD_R, PAD_T, PAD_B = 20, 20, 22, 16
STAMP_PAD_TOP        = 20
COL_GAP              = 24
ROW_GAP              = 14
SVC_COL              = 130     # wider fixed route column to fit 4-char labels (e.g., 971E)
LINE_GAP             = 6
ROW_ADV              = 78      # vertical distance between route rows

def _load_fonts():
    """
    Load Inter variable font for all text. If not found, fall back to Pillow’s default.
    """
    try:
        font_name  = ImageFont.truetype(FONT_REG_PATH, NAME_SIZE)
        font_svc   = ImageFont.truetype(FONT_REG_PATH, SVC_SIZE)
        font_time  = ImageFont.truetype(FONT_REG_PATH, TIME_SIZE)
        font_stamp = ImageFont.truetype(FONT_REG_PATH, STAMP_SIZE)
        return font_name, font_svc, font_time, font_stamp
    except Exception:
        f = ImageFont.load_default()
        return f, f, f, f
        
# ---- Image drawing (800x480, 1-bit) --------------------------------------
def draw_image(data):
    """
    Render 800x480, 1-bit PNG with:
      - Stop A (left) + Stop B (right) on top
      - Stop C full-width at bottom (two side-by-side routes)
      - Vertical times (3 lines) per route
      - Top-right "Updated HH:MM"
      - Fixed-width route column so numbers don’t bleed into times
    """
    import time as _t

    img = Image.new("L", (W, H), 255)  # grayscale first (crisper text), then convert to 1-bit
    d   = ImageDraw.Draw(img)
    font_name, font_svc, font_time, font_stamp = _load_fonts()

    def text(x, y, s, f): d.text((x, y), s, 0, font=f)

    # 1) Timestamp (top-right)
    now_hm = _t.strftime("%H:%M")
    stamp  = f"Updated {now_hm}"
    tx     = W - PAD_R - d.textlength(stamp, font_stamp)
    ty     = PAD_T
    text(tx, ty, stamp, font_stamp)

    # 2) Coordinates for A/B/C (mirrors your private plugin layout)
    grid_y  = PAD_T + STAMP_PAD_TOP
    col_w   = (W - PAD_L - PAD_R - COL_GAP) // 2
    A_x     = PAD_L
    B_x     = PAD_L + col_w + COL_GAP
    A_y = B_y = grid_y

    C_x     = PAD_L
    C_y     = 250  # tuned to fit cleanly with big text
    C_w     = W - PAD_L - PAD_R

    # ----- helper: draw a stop block (name + up to 3 services with 3 vertical times) -----
    def draw_stop_block(stop_obj, x0, y0, max_services=3):
        name = (stop_obj or {}).get("name") or (stop_obj or {}).get("code") or ""
        text(x0, y0, name, font_name)
        y = y0 + NAME_SIZE

        services = (stop_obj or {}).get("services") or []
        for s in services[:max_services]:
            # left fixed column: route number
            svc = str(s.get("no", "?"))
            text(x0, y, svc, font_svc)

            # right flexible column: 3 vertical times
            times_x = x0 + SVC_COL
            t1 = f"{s.get('time1','--:--')} ({s.get('min1','—')}m)"
            t2 = f"{s.get('time2','--:--')} ({s.get('min2','—')}m)"
            t3 = f"{s.get('time3','--:--')} ({s.get('min3','—')}m)"
            text(times_x, y + 0,                        t1, font_time)
            text(times_x, y + TIME_SIZE + LINE_GAP,     t2, font_time)
            text(times_x, y + 2*(TIME_SIZE + LINE_GAP), t3, font_time)

            y += ROW_ADV

    # Top: Stop A + Stop B (3 routes each)
    draw_stop_block(data.get("stop_a"), A_x, A_y, max_services=3)
    draw_stop_block(data.get("stop_b"), B_x, B_y, max_services=3)

    # Bottom: Stop C name + two inner columns (2 routes, each with 3 vertical times)
    stop_c = data.get("stop_c") or {}
    name_c = stop_c.get("name") or stop_c.get("code") or ""
    text(C_x, C_y, name_c, font_name)

    inner_gap = COL_GAP
    inner_w   = (C_w - inner_gap) // 2
    servicesC = (stop_c.get("services") or [])[:2]

    # Left inner route
    if len(servicesC) >= 1:
        s = servicesC[0]
        y = C_y + NAME_SIZE
        text(C_x, y, str(s.get("no","?")), font_svc)
        times_x = C_x + SVC_COL
        t1 = f"{s.get('time1','--:--')} ({s.get('min1','—')}m)"
        t2 = f"{s.get('time2','--:--')} ({s.get('min2','—')}m)"
        t3 = f"{s.get('time3','--:--')} ({s.get('min3','—')}m)"
        text(times_x, y + 0,                        t1, font_time)
        text(times_x, y + TIME_SIZE + LINE_GAP,     t2, font_time)
        text(times_x, y + 2*(TIME_SIZE + LINE_GAP), t3, font_time)

    # Right inner route
    if len(servicesC) >= 2:
        s = servicesC[1]
        xR = C_x + inner_w + inner_gap
        y  = C_y + NAME_SIZE
        text(xR, y, str(s.get("no","?")), font_svc)
        times_x = xR + SVC_COL
        t1 = f"{s.get('time1','--:--')} ({s.get('min1','—')}m)"
        t2 = f"{s.get('time2','--:--')} ({s.get('min2','—')}m)"
        t3 = f"{s.get('time3','--:--')} ({s.get('min3','—')}m)"
        text(times_x, y + 0,                        t1, font_time)
        text(times_x, y + TIME_SIZE + LINE_GAP,     t2, font_time)
        text(times_x, y + 2*(TIME_SIZE + LINE_GAP), t3, font_time)

    # Convert to crisp 1-bit (no dithering)
    img1 = img.convert("1", dither=Image.NONE)
    buf = io.BytesIO()
    img1.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf

# ---- Routes ---------------------------------------------------------------
@app.get("/")
def home():
    return "OK", 200

@app.get("/healthz")
def healthz():
    return jsonify(status="ok"), 200

# Raw probe of GAS response (for debugging)
@app.get("/probe")
def probe():
    a = (request.args.get("stop_a") or DEFAULT_A).strip()
    b = (request.args.get("stop_b") or DEFAULT_B).strip()
    c = (request.args.get("stop_c") or DEFAULT_C).strip()
    url = gas_base_url()
    if not url:
        return jsonify({"error": "GAS_DEPLOYMENT not set"}), 500
    try:
        r = requests.get(url, params={"stop_a": a, "stop_b": b, "stop_c": c}, timeout=8)
        body = r.text[:500]
        return jsonify({
            "status": r.status_code,
            "content_type": r.headers.get("content-type"),
            "sample": body,
            "url": r.url
        }), 200
    except Exception as e:
        return jsonify({"error": repr(e)}), 500

# Parsed view of the data our app will use (for debugging)
@app.get("/debug")
def debug():
    a = (request.args.get("stop_a") or DEFAULT_A).strip()
    b = (request.args.get("stop_b") or DEFAULT_B).strip()
    c = (request.args.get("stop_c") or DEFAULT_C).strip()
    return jsonify(fetch_bus(a, b, c, timeout_sec=8))

# The 800x480 1-bit PNG image
@app.get("/image.png")
def image_png():
    a = (request.args.get("stop_a") or DEFAULT_A).strip()
    b = (request.args.get("stop_b") or DEFAULT_B).strip()
    c = (request.args.get("stop_c") or DEFAULT_C).strip()
    data = fetch_bus(a, b, c, timeout_sec=8)  # image can wait a little longer
    png = draw_image(data)
    return send_file(png, mimetype="image/png")

# Fast JSON for TRMNL Redirect plugin (keep this quick; no GAS call here)
@app.get("/redirect")
def redirect_json():
    a = (request.args.get("stop_a") or DEFAULT_A).strip()
    b = (request.args.get("stop_b") or DEFAULT_B).strip()
    c = (request.args.get("stop_c") or DEFAULT_C).strip()
    minute_bucket = int(time.time() // 60)
    root = request.url_root.rstrip("/")
    img_url = f"{root}/image.png?stop_a={a}&stop_b={b}&stop_c={c}&t={minute_bucket}"
    return jsonify({
        "filename": f"bus-{minute_bucket}",
        "url": img_url,
        "refresh_rate": 60
    })
