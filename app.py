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

import os, io
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont

# Canvas & layout
# --- VISUAL TUNING (bigger timings, smaller titles/routes, more spacing) ---
STAMP_SIZE = 12     # "Updated HH:MM" (slightly smaller)
NAME_SIZE  = 28     # stop names (smaller)
SVC_SIZE   = 24     # route numbers (smaller)
TIME_SIZE  = 30     # arrival lines (bigger)

COL_GAP       = 32  # more gap between A and B columns
SVC_COL       = 125 # route column width (was ~140). Smaller -> more room for times
LINE_GAP      = 8   # gap between the 3 vertical time lines
EXTRA_ROW_PAD = 12  # extra space under each route row
TITLE_GAP     = 8   # gap under stop titles

# Paths to your local Inter variable fonts (added to repo under fonts/)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INTER_VAR_PATH = os.path.join(BASE_DIR, "fonts", "Inter-VariableFont_opsz,wght.ttf")
INTER_VAR_ITALIC_PATH = os.path.join(BASE_DIR, "fonts", "Inter-Italic-VariableFont_opsz,wght.ttf")  # unused

def _load_fonts():
    """
    Load Inter variable font locally from repo. If missing, fall back to Pillow default.
    For 'bold', we simulate weight via stroke on draw().
    """
    try:
        f_name  = ImageFont.truetype(INTER_VAR_PATH, NAME_SIZE)
        f_svc   = ImageFont.truetype(INTER_VAR_PATH, SVC_SIZE)
        f_time  = ImageFont.truetype(INTER_VAR_PATH, TIME_SIZE)
        f_stamp = ImageFont.truetype(INTER_VAR_PATH, STAMP_SIZE)
        return f_name, f_svc, f_time, f_stamp, True  # True = using Inter
    except Exception as e:
        print("FONT WARNING (using default):", repr(e))
        f = ImageFont.load_default()
        return f, f, f, f, False

def _line_h(draw, font):
    l, t, r, b = draw.textbbox((0, 0), "Hg", font=font)
    return b - t

def _wrap(draw, text, font, max_w):
    words = (text or "").split()
    if not words: return []
    lines, cur = [], ""
    for w in words:
        test = w if not cur else cur + " " + w
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines

def _draw_text(d, x, y, s, font, *, bold=False):
    """
    Draw text; if bold=True, simulate bold with a 1px stroke (works well in 1-bit).
    """
    if bold:
        d.text((x, y), s, 0, font=font, stroke_width=1, stroke_fill=0)
    else:
        d.text((x, y), s, 0, font=font)

def _load_fonts_sizes(name_sz, svc_sz, time_sz, stamp_sz):
    """
    Load Inter (local variable TTF) at the given sizes; fall back to Pillow default if needed.
    """
    try:
        f_name  = ImageFont.truetype(INTER_VAR_PATH, name_sz)
        f_svc   = ImageFont.truetype(INTER_VAR_PATH, svc_sz)
        f_time  = ImageFont.truetype(INTER_VAR_PATH, time_sz)
        f_stamp = ImageFont.truetype(INTER_VAR_PATH, stamp_sz)
        return f_name, f_svc, f_time, f_stamp, True
    except Exception as e:
        print("FONT WARNING (dynamic sizes):", repr(e))
        f = ImageFont.load_default()
        return f, f, f, f, False
        
def draw_image(data):
    """
    800x480, 1-bit PNG with Inter + auto-fit:
      - A (left) and B (right) on top (≤3 routes each)
      - C full-width under the taller of A/B (2 routes side-by-side)
      - BIG timings, smaller names/routes, extra breathing space
      - SGT 'Updated HH:MM' top-right
      - Auto-scales down slightly if content would overflow
    """
    from datetime import datetime, timezone, timedelta
    img = Image.new("L", (W, H), 255)
    d   = ImageDraw.Draw(img)

    # Start from tuned sizes
    name_sz  = NAME_SIZE
    svc_sz   = SVC_SIZE
    time_sz  = TIME_SIZE
    stamp_sz = STAMP_SIZE
    line_gap = LINE_GAP

    # Measure pass (no drawing)
    def measure_total(f_name, f_svc, f_time, f_stamp, line_gap_now):
        stamp_h = _line_h(d, f_stamp)
        grid_y  = PAD_T + STAMP_PAD_TOP + stamp_h
        col_w   = (W - PAD_L - PAD_R - COL_GAP) // 2

        def measure_block(stop_obj, col_width):
            name = (stop_obj or {}).get("name") or (stop_obj or {}).get("code") or ""
            name_lines = _wrap(d, name, f_name, col_width)
            lh_name = _line_h(d, f_name)
            name_h  = len(name_lines)*lh_name + TITLE_GAP

            lh_time = _line_h(d, f_time)
            row_adv = 3*lh_time + 2*line_gap_now + EXTRA_ROW_PAD

            services = (stop_obj or {}).get("services") or []
            svc_rows = min(3, len(services))
            body_h   = svc_rows * row_adv
            return name_h + body_h

        A_h = measure_block(data.get("stop_a"), col_w)
        B_h = measure_block(data.get("stop_b"), col_w)

        C_y = grid_y + max(A_h, B_h) + 12
        C_w = W - PAD_L - PAD_R

        name_c = (data.get("stop_c") or {}).get("name") or (data.get("stop_c") or {}).get("code") or ""
        c_lines = _wrap(d, name_c, f_name, C_w)
        lh_name = _line_h(d, f_name)
        c_title_h = len(c_lines)*lh_name + TITLE_GAP

        lh_time = _line_h(d, f_time)
        row_adv = 3*lh_time + 2*line_gap_now + EXTRA_ROW_PAD

        servicesC = (data.get("stop_c") or {}).get("services") or []
        c_body_h  = row_adv if len(servicesC) >= 1 else 0

        total_bottom = C_y + c_title_h + c_body_h + PAD_B
        return total_bottom, grid_y, col_w, C_y, C_w

    # Try up to 4 shrink passes if needed
    for _ in range(4):
        f_name, f_svc, f_time, f_stamp, _ok = _load_fonts_sizes(name_sz, svc_sz, time_sz, stamp_sz)
        total_bottom, grid_y, col_w, C_y, C_w = measure_total(f_name, f_svc, f_time, f_stamp, line_gap)
        if total_bottom <= H:
            break
        avail = H - grid_y - PAD_B
        need  = total_bottom - grid_y - PAD_B
        scale = max(0.72, min(0.96, avail / max(need, 1)))
        name_sz  = max(22, int(name_sz  * scale))
        svc_sz   = max(20, int(svc_sz   * scale))
        time_sz  = max(22, int(time_sz  * scale))   # keep timings larger than titles
        stamp_sz = max(11, int(stamp_sz * scale))
        line_gap = max(6,  int(line_gap * scale))

    # Final draw with settled sizes
    f_name, f_svc, f_time, f_stamp, _ok = _load_fonts_sizes(name_sz, svc_sz, time_sz, stamp_sz)

    # 1) Stamp (SGT)
    sgt = timezone(timedelta(hours=8))
    now_hm = datetime.now(sgt).strftime("%H:%M")
    stamp  = f"Updated {now_hm}"
    stamp_h = _line_h(d, f_stamp)
    tx = W - PAD_R - d.textlength(stamp, font=f_stamp)
    ty = PAD_T
    _draw_text(d, tx, ty, stamp, f_stamp, bold=False)

    # 2) Columns A & B
    col_w = (W - PAD_L - PAD_R - COL_GAP) // 2
    A_x, A_y = PAD_L, (PAD_T + STAMP_PAD_TOP + stamp_h)
    B_x, B_y = PAD_L + col_w + COL_GAP, A_y

    def render_block(stop_obj, x0, y0, max_services=3, name_w=col_w):
        name = (stop_obj or {}).get("name") or (stop_obj or {}).get("code") or ""
        lines = _wrap(d, name, f_name, name_w)
        lh_name = _line_h(d, f_name)
        ny = y0
        for ln in lines:
            _draw_text(d, x0, ny, ln, f_name, bold=True)
            ny += lh_name
        ny += TITLE_GAP

        lh_time = _line_h(d, f_time)
        row_adv = 3*lh_time + 2*line_gap + EXTRA_ROW_PAD

        services = (stop_obj or {}).get("services") or []
        for s in services[:max_services]:
            _draw_text(d, x0, ny, str(s.get("no","?")), f_svc, bold=True)
            times_x = x0 + SVC_COL
            _draw_text(d, times_x, ny + 0*(lh_time + line_gap), f"{s.get('time1','--:--')} ({s.get('min1','—')}m)", f_time)
            _draw_text(d, times_x, ny + 1*(lh_time + line_gap), f"{s.get('time2','--:--')} ({s.get('min2','—')}m)", f_time)
            _draw_text(d, times_x, ny + 2*(lh_time + line_gap), f"{s.get('time3','--:--')} ({s.get('min3','—')}m)", f_time)
            ny += row_adv
        return ny

    bottom_A = render_block(data.get("stop_a"), A_x, A_y, max_services=3, name_w=col_w)
    bottom_B = render_block(data.get("stop_b"), B_x, B_y, max_services=3, name_w=col_w)

    # 3) Stop C (full width under the taller of A/B)
    C_x = PAD_L
    C_y = max(bottom_A, bottom_B) + 12
    C_w = W - PAD_L - PAD_R

    stop_c = data.get("stop_c") or {}
    name_c = stop_c.get("name") or stop_c.get("code") or ""
    c_lines = _wrap(d, name_c, f_name, C_w)
    lh_name = _line_h(d, f_name)
    ny = C_y
    for ln in c_lines:
        _draw_text(d, C_x, ny, ln, f_name, bold=True)
        ny += lh_name
    ny += TITLE_GAP

    servicesC = (stop_c.get("services") or [])[:2]
    lh_time   = _line_h(d, f_time)

    def render_c_service(svc, x0, y0):
        _draw_text(d, x0, y0, str(svc.get("no","?")), f_svc, bold=True)
        times_x = x0 + SVC_COL
        _draw_text(d, times_x, y0 + 0*(lh_time + line_gap), f"{svc.get('time1','--:--')} ({svc.get('min1','—')}m)", f_time)
        _draw_text(d, times_x, y0 + 1*(lh_time + line_gap), f"{svc.get('time2','--:--')} ({svc.get('min2','—')}m)", f_time)
        _draw_text(d, times_x, y0 + 2*(lh_time + line_gap), f"{svc.get('time3','--:--')} ({svc.get('min3','—')}m)", f_time)

    inner_gap = COL_GAP
    inner_w   = (C_w - inner_gap) // 2
    if len(servicesC) >= 1: render_c_service(servicesC[0], C_x, ny)
    if len(servicesC) >= 2: render_c_service(servicesC[1], C_x + inner_w + inner_gap, ny)

    # 4) 1-bit output
    img1 = img.convert("1", dither=Image.NONE)
    buf = io.BytesIO()
    img1.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf

# ===========================================================================

# Optional: quick diag endpoint to confirm fonts are present
@app.get("/version")
def version():
    return {
        "inter_var_present": os.path.exists(INTER_VAR_PATH),
        "stamp_size": STAMP_SIZE, "name_size": NAME_SIZE,
        "svc_size": SVC_SIZE, "time_size": TIME_SIZE,
        "svc_col": SVC_COL
    }, 200
    
# ===========================================================================

# --- tiny diagnostics so you can confirm it's active ------------------------
# Optional: quick diag endpoint to confirm fonts are present
@app.get("/fontinfo")
def fontinfo():
    import os
    return {
        "inter_var_present": os.path.exists(INTER_VAR_PATH),
        "font_path": INTER_VAR_PATH,
        "stamp_size": STAMP_SIZE, "name_size": NAME_SIZE,
        "svc_size": SVC_SIZE, "time_size": TIME_SIZE,
        "svc_col": SVC_COL
    }, 200

@app.get("/fontsample.png")
def fontsample():
    img = Image.new("L", (800, 120), 255)
    d   = ImageDraw.Draw(img)
    f_name, f_svc, f_time, f_stamp = _load_fonts()
    d.text((10, 10),  "Stop Name (Bold) — Inter", 0, font=f_name)
    d.text((10, 50),  "307 | 15:32 (6m) • 15:48 (22m) • 16:03 (37m)", 0, font=f_time)
    d.text((10, 90),  "Updated 12:34", 0, font=f_stamp)
    out = io.BytesIO(); img.convert("1").save(out, "PNG"); out.seek(0)
    return send_file(out, mimetype="image/png")
    
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

@app.get("/redirect")
def redirect_json():
    try:
        # minute-rolling filename in Singapore time
        from datetime import datetime, timezone, timedelta
        sgt = timezone(timedelta(hours=8))
        tick = datetime.now(sgt).strftime("%Y%m%d%H%M")

        # stops (fall back to your defaults if not supplied)
        a = (request.args.get("stop_a") or DEFAULT_A).strip()
        b = (request.args.get("stop_b") or DEFAULT_B).strip()
        c = (request.args.get("stop_c") or DEFAULT_C).strip()

        # absolute image URL (no url_for needed)
        root = request.url_root.rstrip("/")
        img_url = f"{root}/image.png?stop_a={a}&stop_b={b}&stop_c={c}&t={tick}"

        return jsonify({
            "filename": f"bus-{tick}",
            "url": img_url,
            "refresh_rate": 60
        }), 200
    except Exception as e:
        # helpful log and safe JSON
        print("redirect error:", repr(e))
        return jsonify({"error": "redirect-failed", "detail": str(e)}), 500

