# ==== CONFIG (you can paste either the deployment ID or the full /exec URL) ====
GAS_DEPLOYMENT = "https://script.google.com/macros/s/AKfycbyJwiSxqW-AjsTxrqNFCZA_0tp8bwqAjRDOXai0a9fcAiEhi3QV8_LGbQRtR_X7QYsR/exec"
DEFAULT_A, DEFAULT_B, DEFAULT_C = "45379", "45489", "45371"
# ==============================================================================

from flask import Flask, request, jsonify, send_file
import io, time, requests
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

def gas_base_url():
    # If you pasted the full URL, use it; otherwise compose from ID
    if GAS_DEPLOYMENT.startswith("http"):
        return GAS_DEPLOYMENT.split("?")[0]  # strip any old query
    return f"https://script.google.com/macros/s/{GAS_DEPLOYMENT}/exec"

def fetch_bus(stopa, stopb, stopc, timeout_sec=5):
    try:
        r = requests.get(
            gas_base_url(),
            params={"stop_a": stopa, "stop_b": stopb, "stop_c": stopc},
            timeout=timeout_sec,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        # helpful to see in Render logs
        print("GAS fetch failed:", repr(e))
        return {
            "stop_a": {"name": f"{stopa}", "code": stopa, "services": []},
            "stop_b": {"name": f"{stopb}", "code": stopb, "services": []},
            "stop_c": {"name": f"{stopc}", "code": stopc, "services": []},
        }

@app.get("/")
def home():
    return "OK", 200

@app.get("/healthz")
def healthz():
    return jsonify(status="ok"), 200

# NEW: raw probe so we can see what's really coming back from GAS
@app.get("/probe")
def probe():
    a = (request.args.get("stop_a") or DEFAULT_A).strip()
    b = (request.args.get("stop_b") or DEFAULT_B).strip()
    c = (request.args.get("stop_c") or DEFAULT_C).strip()
    try:
        r = requests.get(gas_base_url(), params={"stop_a": a, "stop_b": b, "stop_c": c}, timeout=8)
        body = r.text[:500]
        return jsonify({
            "status": r.status_code,
            "content_type": r.headers.get("content-type"),
            "sample": body,
            "url": r.url
        }), 200
    except Exception as e:
        return jsonify({"error": repr(e)}), 500

# ----------------- no edits below this line -----------------
from flask import Flask, request, jsonify, send_file
import io, time, requests
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
GAS_URL = f"https://script.google.com/macros/s/{GAS_DEPLOYMENT_ID}/exec"

from flask import jsonify, request

@app.get("/debug")
def debug():
    a = (request.args.get("stop_a") or DEFAULT_A).strip()
    b = (request.args.get("stop_b") or DEFAULT_B).strip()
    c = (request.args.get("stop_c") or DEFAULT_C).strip()
    return jsonify(fetch_bus(a, b, c, timeout_sec=8))

def fetch_bus(stopa, stopb, stopc):
    try:
        r = requests.get(GAS_URL, params={"stop_a": stopa, "stop_b": stopb, "stop_c": stopc}, timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {
            "stop_a": {"name": f"{stopa}", "code": stopa, "services": []},
            "stop_b": {"name": f"{stopb}", "code": stopb, "services": []},
            "stop_c": {"name": f"{stopc}", "code": stopc, "services": []},
        }

def draw_image(data):
    W, H = 800, 480
    # Draw in grayscale first for nicer text, then convert to 1-bit
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    try:
        font_big = ImageFont.load_default()
        font_med = ImageFont.load_default()
        font_small = ImageFont.load_default()
    except Exception:
        font_big = font_med = font_small = ImageFont.load_default()

    def text(x, y, s, f): d.text((x, y), s, 0, font=f)

    # header (top-right time)
    now_hm = time.strftime("%H:%M")
    text(W-10 - d.textlength(f"Updated {now_hm}", font_small), 6, f"Updated {now_hm}", font_small)

    # simple layout: A (left), B (right), C (two columns full width)
    blocks = [
        ("stop_a", 20, 30, 370),
        ("stop_b", 420, 30, 370),
        ("stop_c", 20, 250, 760)
    ]

    for key, x0, y0, w in blocks:
        stop = data.get(key, {})
        name = stop.get("name") or stop.get("code") or key.upper()
        text(x0, y0, name, font_big)
        y = y0 + 28
        for s in (stop.get("services") or [])[:3]:
            # route number column
            text(x0, y, str(s.get("no","?")), font_med)
            # three vertical times
            line_x = x0 + 90
            t1 = f"{s.get('time1','--:--')} ({s.get('min1','—')}m)"
            t2 = f"{s.get('time2','--:--')} ({s.get('min2','—')}m)"
            t3 = f"{s.get('time3','--:--')} ({s.get('min3','—')}m)"
            text(line_x, y,     t1, font_med)
            text(line_x, y+22,  t2, font_med)
            text(line_x, y+44,  t3, font_med)
            y += 72

    # convert to 1-bit, hard-threshold
    img1 = img.convert("1")
    buf = io.BytesIO()
    img1.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf

@app.get("/image.png")
def image_png():
    a = (request.args.get("stop_a") or DEFAULT_A).strip()
    b = (request.args.get("stop_b") or DEFAULT_B).strip()
    c = (request.args.get("stop_c") or DEFAULT_C).strip()
    data = fetch_bus(a, b, c, timeout_sec=8)
    
@app.get("/redirect")
def redirect_json():
    # Fast JSON that tells TRMNL what image to fetch next and when to wake again
    a = (request.args.get("stop_a") or DEFAULT_A).strip()
    b = (request.args.get("stop_b") or DEFAULT_B).strip()
    c = (request.args.get("stop_c") or DEFAULT_C).strip()
    # “filename” changes once per minute to avoid flicker inside the same minute
    minute_bucket = int(time.time() // 60)
    img_url = f"{request.url_root.rstrip('/')}/image.png?stop_a={a}&stop_b={b}&stop_c={c}&t={minute_bucket}"
    return jsonify({
        "filename": f"bus-{minute_bucket}",
        "url": img_url,
        "refresh_rate": 60  # 1 minute
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
