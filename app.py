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

import os, io, requests
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont

# Canvas + layout
W, H                          = 800, 480
PAD_L, PAD_R, PAD_T, PAD_B    = 20, 20, 22, 16
STAMP_PAD_TOP                 = 20
COL_GAP, ROW_GAP              = 24, 14
SVC_COL                       = 130     # route-number column width (bump to 140 if needed)
LINE_GAP                      = 6

# Font sizes tuned for 800x480 e-ink
STAMP_SIZE = 13               # "Updated HH:MM"
NAME_SIZE  = 34               # stop names
SVC_SIZE   = 30               # route numbers
TIME_SIZE  = 26               # each vertical time line

# --------- fonts (download once to /tmp so you don't have to upload) -------
TMP_DIR = "/tmp/fonts"
os.makedirs(TMP_DIR, exist_ok=True)
REG_PATH  = os.path.join(TMP_DIR, "DejaVuSans.ttf")
BOLD_PATH = os.path.join(TMP_DIR, "DejaVuSans-Bold.ttf")

REG_URL  = os.getenv("FONT_URL_REG",
    "https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf/DejaVuSans.ttf")
BOLD_URL = os.getenv("FONT_URL_BOLD",
    "https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf/DejaVuSans-Bold.ttf")

def _ensure_fonts():
    for path, url in [(REG_PATH, REG_URL), (BOLD_PATH, BOLD_URL)]:
        if not os.path.exists(path):
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            with open(path, "wb") as f:
                f.write(r.content)

def _load_fonts():
    try:
        _ensure_fonts()
        f_name  = ImageFont.truetype(BOLD_PATH, NAME_SIZE)
        f_svc   = ImageFont.truetype(BOLD_PATH, SVC_SIZE)
        f_time  = ImageFont.truetype(REG_PATH,  TIME_SIZE)
        f_stamp = ImageFont.truetype(REG_PATH,  STAMP_SIZE)
        return f_name, f_svc, f_time, f_stamp
    except Exception:
        # hard fallback (shouldn't happen)
        f = ImageFont.load_default()
        return f, f, f, f

def _line_h(draw, font):
    l, t, r, b = draw.textbbox((0, 0), "Hg", font=font)
    return b - t

def _wrap_lines(draw, text, font, max_w):
    words = (text or "").split()
    if not words:
        return []
    lines, cur = [], ""
    for w in words:
        test = w if not cur else cur + " " + w
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines
    
# ---- Image drawing (800x480, 1-bit) --------------------------------------
def draw_image(data):
    """800x480, 1-bit PNG with clean TTF text, SGT timestamp, wrapped names, no overlap."""
    img = Image.new("L", (W, H), 255)
    d   = ImageDraw.Draw(img)
    f_name, f_svc, f_time, f_stamp = _load_fonts()

    def text(x, y, s, f): d.text((x, y), s, 0, font=f)

    # 1) Top-right stamp in Singapore time
    sgt = timezone(timedelta(hours=8))
    now_hm = datetime.now(sgt).strftime("%H:%M")
    stamp  = f"Updated {now_hm}"
    stamp_h = _line_h(d, f_stamp)
    tx = W - PAD_R - d.textlength(stamp, font=f_stamp)
    ty = PAD_T
    text(tx, ty, stamp, f_stamp)

    grid_y = PAD_T + STAMP_PAD_TOP + stamp_h

    # 2) Two columns (A left, B right)
    col_w = (W - PAD_L - PAD_R - COL_GAP) // 2
    A_x, A_y = PAD_L, grid_y
    B_x, B_y = PAD_L + col_w + COL_GAP, grid_y

    # Draw a stop block and return its bottom y
    def draw_stop_block(stop_obj, x0, y0, max_services=3, name_width=col_w):
        name = (stop_obj or {}).get("name") or (stop_obj or {}).get("code") or ""
        lines = _wrap_lines(d, name, f_name, name_width)
        lh_name = _line_h(d, f_name)
        ny = y0
        for ln in lines:
            text(x0, ny, ln, f_name)
            ny += lh_name
        ny += 6  # small gap under name

        lh_time = _line_h(d, f_time)
        # advance per service row (3 time lines + gaps + padding)
        row_adv = 3*lh_time + 2*LINE_GAP + 8

        services = (stop_obj or {}).get("services") or []
        for s in services[:max_services]:
            # route number (fixed column)
            text(x0, ny, str(s.get("no","?")), f_svc)
            # three vertical times
            times_x = x0 + SVC_COL
            t1 = f"{s.get('time1','--:--')} ({s.get('min1','—')}m)"
            t2 = f"{s.get('time2','--:--')} ({s.get('min2','—')}m)"
            t3 = f"{s.get('time3','--:--')} ({s.get('min3','—')}m)"
            text(times_x, ny + 0*(lh_time + LINE_GAP), t1, f_time)
            text(times_x, ny + 1*(lh_time + LINE_GAP), t2, f_time)
            text(times_x, ny + 2*(lh_time + LINE_GAP), t3, f_time)
            ny += row_adv
        return ny

    bottom_A = draw_stop_block(data.get("stop_a"), A_x, A_y, max_services=3, name_width=col_w)
    bottom_B = draw_stop_block(data.get("stop_b"), B_x, B_y, max_services=3, name_width=col_w)

    # 3) Stop C below the taller of A/B, with two inner columns (first two routes)
    C_x = PAD_L
    C_y = max(bottom_A, bottom_B) + 12
    C_w = W - PAD_L - PAD_R

    stop_c = data.get("stop_c") or {}
    name_c = stop_c.get("name") or stop_c.get("code") or ""
    c_lines = _wrap_lines(d, name_c, f_name, C_w)
    lh_name = _line_h(d, f_name)
    ny = C_y
    for ln in c_lines:
        text(C_x, ny, ln, f_name)
        ny += lh_name
    ny += 6

    inner_gap = COL_GAP
    inner_w   = (C_w - inner_gap) // 2
    servicesC = (stop_c.get("services") or [])[:2]
    lh_time   = _line_h(d, f_time)

    def draw_service(svc, x0, y0):
        text(x0, y0, str(svc.get("no","?")), f_svc)
        times_x = x0 + SVC_COL
        t1 = f"{svc.get('time1','--:--')} ({svc.get('min1','—')}m)"
        t2 = f"{svc.get('time2','--:--')} ({svc.get('min2','—')}m)"
        t3 = f"{svc.get('time3','--:--')} ({svc.get('min3','—')}m)"
        text(times_x, y0 + 0*(lh_time + LINE_GAP), t1, f_time)
        text(times_x, y0 + 1*(lh_time + LINE_GAP), t2, f_time)
        text(times_x, y0 + 2*(lh_time + LINE_GAP), t3, f_time)

    if len(servicesC) >= 1:
        draw_service(servicesC[0], C_x, ny)
    if len(servicesC) >= 2:
        draw_service(servicesC[1], C_x + inner_w + inner_gap, ny)

    # 4) Convert to crisp 1-bit
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
