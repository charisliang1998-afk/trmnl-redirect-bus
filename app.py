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

import math
from datetime import datetime, timezone, timedelta
from PIL import ImageFont, Image, ImageDraw

# Use Pillow's built-in bitmap font
_DEF_FONT = ImageFont.load_default()

# Scale factors for the default font (integers keep it crisp)
SCALE_STAMP = 2   # top-right "Updated HH:MM"
SCALE_NAME  = 3   # stop names
SCALE_SVC   = 3   # route numbers (left column)
SCALE_TIME  = 2   # vertical time lines

# Canvas + layout constants
W, H                          = 800, 480
PAD_L, PAD_R, PAD_T, PAD_B    = 20, 20, 22, 16
STAMP_PAD_TOP                 = 20
COL_GAP, ROW_GAP              = 24, 14
SVC_COL                       = 130      # fixed width so route numbers never hit times
LINE_GAP                      = 8        # gap between the 3 vertical time lines

def _line_h_base(draw):
    # Accurate base line height for the default font
    l, t, r, b = draw.textbbox((0, 0), "Hg", font=_DEF_FONT)
    return b - t

def _textlen_base(draw, text):
    return draw.textlength(text, font=_DEF_FONT)

def _textlen_scaled(draw, text, scale):
    return int(round(_textlen_base(draw, text) * scale))

def _line_h_scaled(draw, scale):
    return int(round(_line_h_base(draw) * scale))

def _wrap_lines_scaled(draw, text, scale, max_w):
    words = (text or "").split()
    if not words:
        return []
    lines, cur = [], ""
    while words:
        w = words.pop(0)
        test = w if not cur else cur + " " + w
        if _textlen_scaled(draw, test, scale) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def _draw_text_scaled(img, draw, x, y, text, scale):
    """Draw default-font text scaled up crisply (nearest-neighbor)."""
    if not text:
        return
    base_w = max(1, int(math.ceil(_textlen_base(draw, text))))
    base_h = max(1, _line_h_base(draw))
    # Render at base size into a small white image
    small = Image.new("L", (base_w, base_h), 255)
    d2 = ImageDraw.Draw(small)
    d2.text((0, 0), text, 0, font=_DEF_FONT)
    # Scale up
    big_w = max(1, int(round(base_w * scale)))
    big_h = max(1, int(round(base_h * scale)))
    big = small.resize((big_w, big_h), resample=Image.NEAREST)
    # Build mask from black text
    mask = big.point(lambda p: 255 if p < 128 else 0)
    # Paste black text onto the main canvas
    img.paste(0, (int(x), int(y)), mask)
    
# ---- Image drawing (800x480, 1-bit) --------------------------------------
def draw_image(data):
    """
    800x480, 1-bit PNG using ONLY the default Pillow font (scaled up crisply):
      • A (left) + B (right) on top, names wrap within their columns
      • C spans full width underneath the taller of A/B (two inner columns)
      • Fixed route-number column; three vertical time lines per route
      • 'Updated HH:MM' in Singapore time (UTC+8) at top-right
    """
    img = Image.new("L", (W, H), 255)
    d   = ImageDraw.Draw(img)

    # ---------- 1) Stamp (SG time) ----------
    sgt = timezone(timedelta(hours=8))
    now_hm = datetime.now(sgt).strftime("%H:%M")
    stamp  = f"Updated {now_hm}"
    stamp_h = _line_h_scaled(d, SCALE_STAMP)
    tx = W - PAD_R - _textlen_scaled(d, stamp, SCALE_STAMP)
    ty = PAD_T
    _draw_text_scaled(img, d, tx, ty, stamp, SCALE_STAMP)

    grid_y = PAD_T + STAMP_PAD_TOP + stamp_h

    # ---------- 2) Column geometry ----------
    col_w = (W - PAD_L - PAD_R - COL_GAP) // 2
    A_x, A_y = PAD_L, grid_y
    B_x, B_y = PAD_L + col_w + COL_GAP, grid_y

    # ---------- 3) Draw A & B with wrapped titles ----------
    def draw_stop_block(stop_obj, x0, y0, max_services=3, name_scale=SCALE_NAME):
        name = (stop_obj or {}).get("name") or (stop_obj or {}).get("code") or ""
        lines = _wrap_lines_scaled(d, name, name_scale, col_w)
        lh_name = _line_h_scaled(d, name_scale)
        ny = y0
        for ln in lines:
            _draw_text_scaled(img, d, x0, ny, ln, name_scale)
            ny += lh_name
        ny += 6  # small gap under name

        lh_time = _line_h_scaled(d, SCALE_TIME)
        services = (stop_obj or {}).get("services") or []
        for s in services[:max_services]:
            # route number (fixed column)
            _draw_text_scaled(img, d, x0, ny, str(s.get("no","?")), SCALE_SVC)
            # three vertical times
            times_x = x0 + SVC_COL
            t1 = f"{s.get('time1','--:--')} ({s.get('min1','—')}m)"
            t2 = f"{s.get('time2','--:--')} ({s.get('min2','—')}m)"
            t3 = f"{s.get('time3','--:--')} ({s.get('min3','—')}m)"
            _draw_text_scaled(img, d, times_x, ny + 0*(lh_time + LINE_GAP), t1, SCALE_TIME)
            _draw_text_scaled(img, d, times_x, ny + 1*(lh_time + LINE_GAP), t2, SCALE_TIME)
            _draw_text_scaled(img, d, times_x, ny + 2*(lh_time + LINE_GAP), t3, SCALE_TIME)
            # advance to next service row
            row_adv = 3*lh_time + 2*LINE_GAP + 8
            ny += row_adv
        return ny

    bottom_A = draw_stop_block(data.get("stop_a"), A_x, A_y, max_services=3)
    bottom_B = draw_stop_block(data.get("stop_b"), B_x, B_y, max_services=3)

    # ---------- 4) Draw C below the taller of A/B ----------
    C_x = PAD_L
    C_y = max(bottom_A, bottom_B) + 12
    C_w = W - PAD_L - PAD_R

    # C title (wrap to full width)
    stop_c = data.get("stop_c") or {}
    name_c = stop_c.get("name") or stop_c.get("code") or ""
    c_lines = _wrap_lines_scaled(d, name_c, SCALE_NAME, C_w)
    lh_name = _line_h_scaled(d, SCALE_NAME)
    ny = C_y
    for ln in c_lines:
        _draw_text_scaled(img, d, C_x, ny, ln, SCALE_NAME)
        ny += lh_name
    ny += 6

    # two inner columns (first two services from C)
    inner_gap = COL_GAP
    inner_w   = (C_w - inner_gap) // 2
    servicesC = (stop_c.get("services") or [])[:2]
    lh_time   = _line_h_scaled(d, SCALE_TIME)

    def draw_service(svc, x0, y0):
        _draw_text_scaled(img, d, x0, y0, str(svc.get("no","?")), SCALE_SVC)
        times_x = x0 + SVC_COL
        t1 = f"{svc.get('time1','--:--')} ({svc.get('min1','—')}m)"
        t2 = f"{svc.get('time2','--:--')} ({svc.get('min2','—')}m)"
        t3 = f"{svc.get('time3','--:--')} ({svc.get('min3','—')}m)"
        _draw_text_scaled(img, d, times_x, y0 + 0*(lh_time + LINE_GAP), t1, SCALE_TIME)
        _draw_text_scaled(img, d, times_x, y0 + 1*(lh_time + LINE_GAP), t2, SCALE_TIME)
        _draw_text_scaled(img, d, times_x, y0 + 2*(lh_time + LINE_GAP), t3, SCALE_TIME)

    if len(servicesC) >= 1:
        draw_service(servicesC[0], C_x, ny)
    if len(servicesC) >= 2:
        draw_service(servicesC[1], C_x + inner_w + inner_gap, ny)

    # ---------- 5) Convert to crisp 1-bit ----------
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
