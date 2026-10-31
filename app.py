"""
accountimagemaker - アカウント画像ランダム生成
================================================
アカウント用アイコン画像をランダムに生成する単一ファイル Flask アプリ。
seed を指定すると、同じスタイル・サイズで同じ画像が再現できる。

目次
----
1. 設定（スタイル・サイズ定義）
2. 色パレット生成（HSL ベース、背景と前景のコントラスト確保）
3. 画像生成（identicon / geometric / pixel）
4. 画面（HTML）とルーティング

依存は Flask と Pillow のみ。DB は使わず、画像はメモリ上でのみ扱う。
"""

from __future__ import annotations

import colorsys
import io
import os
import random

from flask import Flask, jsonify, render_template_string, request, send_file
from PIL import Image, ImageDraw

# ============================
# 1. 設定
# ============================

app = Flask(__name__)

STYLES = {
    "identicon": {"label": "Identicon（5×5ブロック）"},
    "geometric": {"label": "Geometric（幾何学模様）"},
    "pixel": {"label": "Pixel（ドット絵フェイス）"},
}
STYLE_ORDER = ["identicon", "geometric", "pixel"]
SIZES = [256, 512, 1024]
DEFAULT_STYLE = "identicon"
DEFAULT_SIZE = 512
CANDIDATE_COUNT = 6
SEED_MAX = 10**9


# ============================
# 2. 色パレット生成
# ============================


def _hsl_to_rgb(h: float, s: float, lightness: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, lightness, s)
    return (int(r * 255), int(g * 255), int(b * 255))


def make_palette(rng: random.Random) -> dict[str, tuple[int, int, int]]:
    """背景・前景・アクセントの3色を返す。

    背景は「明るい地＋濃い前景」か「暗い地＋明るい前景」のどちらかに寄せ、
    明度差でコントラストを構造的に確保する。
    """
    hue = rng.random()
    accent_shift = rng.choice([0.08, -0.08, 0.5])
    if rng.random() < 0.35:
        # 暗い背景
        bg = _hsl_to_rgb(hue, rng.uniform(0.25, 0.45), rng.uniform(0.08, 0.16))
        fg = _hsl_to_rgb(hue, rng.uniform(0.45, 0.70), rng.uniform(0.62, 0.80))
        accent = _hsl_to_rgb(
            hue + accent_shift, rng.uniform(0.50, 0.75), rng.uniform(0.55, 0.72)
        )
    else:
        # 明るい背景
        bg = _hsl_to_rgb(hue, rng.uniform(0.30, 0.55), rng.uniform(0.84, 0.92))
        fg = _hsl_to_rgb(hue, rng.uniform(0.50, 0.75), rng.uniform(0.22, 0.40))
        accent = _hsl_to_rgb(
            hue + accent_shift, rng.uniform(0.50, 0.80), rng.uniform(0.30, 0.48)
        )
    return {"bg": bg, "fg": fg, "accent": accent}


def _lerp_color(
    c1: tuple[int, int, int], c2: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


# ============================
# 3. 画像生成
# ============================


def _draw_identicon(
    rng: random.Random, palette: dict, size: int
) -> Image.Image:
    """5×5 左右対称ブロック（GitHub の identicon 風）。"""
    cells = 5
    unit = 40
    img = Image.new("RGB", (cells * unit, cells * unit), palette["bg"])
    draw = ImageDraw.Draw(img)
    half = (cells + 1) // 2
    for y in range(cells):
        for x in range(half):
            if rng.random() < 0.52:
                color = (
                    palette["accent"] if rng.random() < 0.22 else palette["fg"]
                )
                for xx in {x, cells - 1 - x}:
                    draw.rectangle(
                        [xx * unit, y * unit, (xx + 1) * unit - 1, (y + 1) * unit - 1],
                        fill=color,
                    )
    return img.resize((size, size), Image.NEAREST)


def _draw_geometric(
    rng: random.Random, palette: dict, size: int
) -> Image.Image:
    """グラデーション背景＋ランダムな円・三角形・線。2倍で描いて縮小する。"""
    ss = 2
    w = size * ss
    top = _lerp_color(palette["bg"], palette["accent"], 0.35)
    bottom = palette["bg"]
    img = Image.new("RGB", (w, w), bottom)
    draw = ImageDraw.Draw(img)
    for yy in range(w):
        draw.line([(0, yy), (w, yy)], fill=_lerp_color(top, bottom, yy / max(w - 1, 1)))

    overlay = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)

    def rgba(color: tuple[int, int, int], alpha: int) -> tuple[int, int, int, int]:
        return (color[0], color[1], color[2], alpha)

    # 円（塗り・輪郭の両方あり）
    for _ in range(rng.randint(3, 6)):
        cx, cy = rng.uniform(0, w), rng.uniform(0, w)
        r = rng.uniform(0.07, 0.34) * w
        color = palette["fg"] if rng.random() < 0.6 else palette["accent"]
        if rng.random() < 0.35:
            od.ellipse(
                [cx - r, cy - r, cx + r, cy + r],
                outline=rgba(color, rng.randint(140, 220)),
                width=max(2, int(w * 0.012)),
            )
        else:
            od.ellipse(
                [cx - r, cy - r, cx + r, cy + r], fill=rgba(color, rng.randint(70, 170))
            )
    # 三角形
    for _ in range(rng.randint(1, 3)):
        pts = [(rng.uniform(0, w), rng.uniform(0, w)) for _ in range(3)]
        color = palette["accent"] if rng.random() < 0.5 else palette["fg"]
        od.polygon(pts, fill=rgba(color, rng.randint(60, 150)))
    # 線
    for _ in range(rng.randint(2, 4)):
        x1, y1 = rng.uniform(0, w), rng.uniform(0, w)
        x2, y2 = rng.uniform(0, w), rng.uniform(0, w)
        color = palette["fg"] if rng.random() < 0.5 else palette["accent"]
        od.line(
            [(x1, y1), (x2, y2)],
            fill=rgba(color, rng.randint(120, 210)),
            width=max(2, int(w * rng.uniform(0.006, 0.02))),
        )

    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    return img.resize((size, size), Image.LANCZOS)


def _draw_pixel(rng: random.Random, palette: dict, size: int) -> Image.Image:
    """16×16 ドット絵の簡易フェイス。目・口の配置がランダムに変わる。"""
    grid = 16
    unit = 10
    img = Image.new("RGB", (grid * unit, grid * unit), palette["bg"])
    draw = ImageDraw.Draw(img)

    def px(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < grid and 0 <= y < grid:
            draw.rectangle(
                [x * unit, y * unit, (x + 1) * unit - 1, (y + 1) * unit - 1],
                fill=color,
            )

    dark = (34, 32, 44)
    face = palette["fg"]

    # 顔の輪郭（楕円状にセルを置く）
    cx, cy = 7.5, 8.0
    rx = rng.uniform(5.2, 6.0)
    ry = rng.uniform(5.8, 6.6)
    for y in range(grid):
        for x in range(grid):
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                px(x, y, face)

    # おまけパーツ（耳／アンテナ／なし）
    deco = rng.choice(["ears", "antenna", "none"])
    if deco == "ears":
        for dx, dy in [(2, 1), (3, 1), (3, 2), (12, 1), (13, 1), (12, 2)]:
            px(dx, dy, face)
    elif deco == "antenna":
        for dy in range(0, 3):
            px(8, dy, face)
        px(8, 0, palette["accent"])

    # 目（位置・高さ・ウインクがランダム）
    eye_y = rng.choice([6, 7])
    eye_h = rng.choice([1, 2])
    wink = rng.random() < 0.18
    for dy in range(eye_h):
        px(5, eye_y + dy, dark)
        if not wink:
            px(10, eye_y + dy, dark)
    if wink:
        px(10, eye_y, dark)

    # 口（形がランダム）
    mouth_y = rng.choice([10, 11])
    mouth = rng.choice(["smile", "flat", "open", "small"])
    if mouth == "smile":
        for dx, dy in [(6, 0), (9, 0), (7, 1), (8, 1)]:
            px(dx, mouth_y + dy, dark)
    elif mouth == "flat":
        for dx in range(6, 10):
            px(dx, mouth_y, dark)
    elif mouth == "open":
        for dx, dy in [(7, 0), (8, 0), (7, 1), (8, 1)]:
            px(dx, mouth_y + dy, palette["accent"])
    else:  # small
        for dx in (7, 8):
            px(dx, mouth_y, dark)

    # ほっぺ
    if rng.random() < 0.6:
        px(3, 9, palette["accent"])
        px(12, 9, palette["accent"])

    return img.resize((size, size), Image.NEAREST)


_GENERATORS = {
    "identicon": _draw_identicon,
    "geometric": _draw_geometric,
    "pixel": _draw_pixel,
}


def generate_image(seed: int, style: str, size: int) -> bytes:
    """seed と style から決定的に画像を生成し、PNG バイト列を返す。

    サイズは見た目の解像度だけに影響し、模様そのものは seed+style で決まる。
    """
    rng = random.Random((seed & 0xFFFFFFFF) * 31 + STYLE_ORDER.index(style))
    palette = make_palette(rng)
    img = _GENERATORS[style](rng, palette, size)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ============================
# 4. 画面（HTML）とルーティング
# ============================

INDEX_HTML = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>accountimagemaker（アカウント画像ランダム生成）</title>
<style>
  body { font-family: sans-serif; margin: 2rem auto; max-width: 880px; padding: 0 1rem; }
  .grid { display: flex; flex-wrap: wrap; gap: 1rem; }
  .card { text-align: center; }
  .card img { width: 160px; height: 160px; border: 1px solid #ccc; border-radius: 12px; }
  .seed { font-size: 0.8rem; color: #555; }
  label { margin-right: 1rem; }
</style>
</head>
<body>
<h1>アカウント画像ランダム生成</h1>
<p>スタイルとサイズを選んで候補を生成します。各候補は seed で再現できます。</p>
<form method="get" action="/">
  <label>スタイル
    <select name="style">
      {% for key in style_order %}
      <option value="{{ key }}" {% if key == style %}selected{% endif %}>{{ styles[key].label }}</option>
      {% endfor %}
    </select>
  </label>
  <label>サイズ
    <select name="size">
      {% for s in sizes %}
      <option value="{{ s }}" {% if s == size %}selected{% endif %}>{{ s }}×{{ s }}</option>
      {% endfor %}
    </select>
  </label>
  <button type="submit">候補を生成</button>
</form>
<div class="grid">
  {% for seed in candidates %}
  <div class="card">
    <img src="/img?seed={{ seed }}&style={{ style }}&size={{ size }}" alt="候補 {{ loop.index }}">
    <div class="seed">seed: {{ seed }}</div>
    <a href="/img?seed={{ seed }}&style={{ style }}&size={{ size }}&download=1">ダウンロード</a>
  </div>
  {% endfor %}
</div>
</body>
</html>
"""


def _parse_img_params():
    """ /img のパラメータを検証する。(params, error_response) を返す。"""
    style = request.args.get("style", DEFAULT_STYLE)
    if style not in STYLES:
        return None, (f"unknown style: {style}", 400)

    size_raw = request.args.get("size", str(DEFAULT_SIZE))
    try:
        size = int(size_raw)
    except (TypeError, ValueError):
        return None, ("size must be an integer", 400)
    if size not in SIZES:
        return None, (f"size must be one of {SIZES}", 400)

    seed_raw = request.args.get("seed")
    if seed_raw is None:
        seed = random.SystemRandom().randrange(0, SEED_MAX)
    else:
        try:
            seed = int(seed_raw)
        except (TypeError, ValueError):
            return None, ("seed must be an integer", 400)

    return (seed, style, size), None


@app.route("/", methods=["GET"])
def index():
    style = request.args.get("style", DEFAULT_STYLE)
    if style not in STYLES:
        style = DEFAULT_STYLE
    try:
        size = int(request.args.get("size", DEFAULT_SIZE))
    except (TypeError, ValueError):
        size = DEFAULT_SIZE
    if size not in SIZES:
        size = DEFAULT_SIZE
    sysrand = random.SystemRandom()
    candidates = [sysrand.randrange(0, SEED_MAX) for _ in range(CANDIDATE_COUNT)]
    return render_template_string(
        INDEX_HTML,
        styles=STYLES,
        style_order=STYLE_ORDER,
        sizes=SIZES,
        style=style,
        size=size,
        candidates=candidates,
    )


@app.route("/img", methods=["GET"])
def img():
    params, error = _parse_img_params()
    if error is not None:
        return error
    seed, style, size = params
    data = generate_image(seed, style, size)
    response = send_file(io.BytesIO(data), mimetype="image/png")
    if request.args.get("download") == "1":
        response.headers["Content-Disposition"] = (
            f'attachment; filename="accountimage-{style}-{seed}.png"'
        )
    return response


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
