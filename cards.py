"""딜 카드 이미지 생성 — 스레드/인스타용 정사각(1080×1080) 카드 N장 + 캡션.

DB 상위 특가로 카드를 찍어내고(AI 아님, Pillow 렌더), 바로 올릴 캡션까지 만든다.
결과물은 docs/cards/ 에 떨어져서 hotdeal.help/cards/ 로 폰에서 바로 저장·복사할 수 있다.

사용법:
    python cards.py                 # 상위 4장
    python cards.py --count 6

한글 폰트: 로컬(맑은 고딕)·CI(나눔고딕)에서 자동 탐색. 둘 다 없으면 기본 폰트로 폴백.
"""
import argparse
import io
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import db
from build import DISCLOSURE, SITE_URL, SITE_NAME, fetch_deals, won

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "docs" / "cards"
KST = timezone(timedelta(hours=9))

# 캔버스 · 팔레트 (사이트 라이트 테마와 동일 계열)
S = 1080
BLUE = (47, 107, 255)
INK = (20, 27, 46)
DIM = (105, 113, 138)
LINE = (227, 233, 242)
HOT = (229, 72, 77)
BG = (255, 255, 255)
IMGBG = (240, 243, 248)
WHITE = (255, 255, 255)

# 한글 폰트 후보. 앞에서부터 존재하는 걸 쓴다.
BOLD_CANDIDATES = [
    r"C:\Windows\Fonts\malgunbd.ttf",                          # 맑은 고딕 Bold (Windows)
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",     # CI (apt fonts-nanum)
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]
REG_CANDIDATES = [
    r"C:\Windows\Fonts\malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]


def _find_font(candidates):
    for p in candidates:
        if Path(p).exists():
            return p
    return None


_BOLD = _find_font(BOLD_CANDIDATES)
_REG = _find_font(REG_CANDIDATES) or _BOLD


def font(size, bold=True):
    path = _BOLD if bold else _REG
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def fit(draw, text, f, max_w):
    """한 줄 폭을 넘으면 …로 자른다."""
    if draw.textlength(text, font=f) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=f) > max_w:
        text = text[:-1]
    return text + "…"


def wrap(draw, text, f, max_w, max_lines=2):
    """한글 기준 글자 단위 줄바꿈. 마지막 줄은 넘치면 …로 자른다."""
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=f) <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
            if len(lines) == max_lines - 1:
                break
    rest = text[sum(len(l) for l in lines):]
    lines.append(fit(draw, rest, f, max_w))
    return lines[:max_lines]


def download_image(url):
    """썸네일을 받아 정사각으로 center-crop 한다. 실패하면 None."""
    if not url:
        return None
    try:
        req = urllib.request.Request(
            url, headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as e:
        print(f"    [-] 이미지 실패: {e}")
        return None
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
    return img


def rounded(img, radius):
    """이미지에 둥근 모서리 알파 마스크를 씌운다."""
    img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0], img.size[1]], radius, fill=255)
    img.putalpha(mask)
    return img


def make_card(deal, rank):
    """정사각 카드 한 장을 그린다."""
    card = Image.new("RGB", (S, S), BG)
    d = ImageDraw.Draw(card)
    M = 64

    # 상단: TOP n 필 + 브랜드
    pill_w, pill_h = 176, 72
    d.rounded_rectangle([M, M, M + pill_w, M + pill_h], 36, fill=BLUE)
    rf = font(40, bold=True)
    rtxt = f"TOP {rank}"
    d.text((M + pill_w / 2, M + pill_h / 2), rtxt, font=rf, fill=WHITE, anchor="mm")
    bf = font(34, bold=True)
    d.text((S - M, M + pill_h / 2), "hotdeal.help", font=bf, fill=DIM, anchor="rm")

    # 상품 이미지 (둥근 모서리)
    img_side = 560
    ix = (S - img_side) // 2
    iy = M + pill_h + 40
    d.rounded_rectangle([ix, iy, ix + img_side, iy + img_side], 32, fill=IMGBG)
    thumb = download_image(deal.get("thumbnail_url"))
    if thumb is not None:
        thumb = rounded(thumb.resize((img_side, img_side)), 32)
        card.paste(thumb, (ix, iy), thumb)

    # 할인율 · 가격
    ty = iy + img_side + 44
    rate = deal.get("effective_rate")
    if rate is None:
        rate = deal.get("discount_rate") or 0
    price = deal.get("effective_price") or deal.get("display_price") or 0
    orig = deal.get("original_price")

    df = font(118, bold=True)
    d.text((M, ty), f"{rate}%", font=df, fill=BLUE, anchor="lm")
    rate_w = d.textlength(f"{rate}%", font=df)

    pf = font(72, bold=True)
    px = M + rate_w + 36
    d.text((px, ty - 22), f"{won(price)}원", font=pf, fill=INK, anchor="lm")
    if orig:
        of = font(38, bold=False)
        ow = f"정가 {won(orig)}원"
        d.text((px, ty + 34), ow, font=of, fill=DIM, anchor="lm")
        owid = d.textlength(ow, font=of)
        d.line([px, ty + 34, px + owid, ty + 34], fill=DIM, width=3)

    # 상품명 (최대 2줄)
    ny = ty + 96
    nf = font(42, bold=True)
    for line in wrap(d, deal.get("display_name") or "", nf, S - 2 * M, max_lines=2):
        d.text((M, ny), line, font=nf, fill=INK, anchor="lm")
        ny += 58

    # 하단 안내
    d.line([M, S - 96, S - M, S - 96], fill=LINE, width=2)
    ff = font(32, bold=True)
    d.text((M, S - 58), "프로필 링크에서 전체 특가 확인 · hotdeal.help",
           font=ff, fill=DIM, anchor="lm")
    return card


def build_caption(deals):
    """스레드용 캡션. 500자 이내 + 태그 1개 + 고지문구."""
    lines = ["오늘의 토스쇼핑 특가 🔥", ""]
    for i, dl in enumerate(deals, 1):
        name = (dl.get("display_name") or "").strip()
        if len(name) > 18:
            name = name[:18] + "…"
        rate = dl.get("effective_rate")
        if rate is None:
            rate = dl.get("discount_rate") or 0
        lines.append(f"{i}. {name} {rate}%")
    lines += ["", "전체 특가 → hotdeal.help", DISCLOSURE, "#핫딜"]
    cap = "\n".join(lines)
    # 스레드 500자 제한 안전장치
    if len(cap) > 490:
        cap = cap[:487] + "…"
    return cap


def viewer_html(n, caption, generated_at):
    imgs = "".join(
        f'<img class="c" src="{i}.jpg" alt="딜 카드 {i}" loading="lazy">' for i in range(1, n + 1)
    )
    cap_attr = caption.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    cap_txt = caption.replace("&", "&amp;").replace("<", "&lt;")
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>딜 카드 · {SITE_NAME}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0e1524;color:#eef2f8;font-family:"Malgun Gothic","맑은 고딕",system-ui,sans-serif;
  padding:18px;line-height:1.6;max-width:560px;margin:0 auto}}
h1{{font-size:19px;margin-bottom:4px}}
p.sub{{color:#9aa5be;font-size:13px;margin-bottom:16px}}
.cards{{display:flex;flex-direction:column;gap:12px;margin-bottom:22px}}
.c{{width:100%;border-radius:14px;border:1px solid #26314a}}
h2{{font-size:15px;margin:18px 0 8px}}
textarea{{width:100%;height:200px;background:#161f31;color:#eef2f8;border:1px solid #26314a;
  border-radius:12px;padding:12px;font:inherit;font-size:14px;resize:vertical}}
button{{margin-top:10px;width:100%;padding:14px;border:none;border-radius:12px;background:#4b83ff;
  color:#fff;font:inherit;font-weight:800;font-size:16px;cursor:pointer}}
button:active{{transform:scale(.99)}}
.tip{{color:#9aa5be;font-size:12.5px;margin-top:14px}}
</style></head>
<body>
<h1>🔥 오늘의 딜 카드</h1>
<p class="sub">{generated_at} 기준 · 스레드/인스타에 올리세요</p>
<div class="cards">{imgs}</div>
<h2>캡션 (복사해서 붙여넣기)</h2>
<textarea id="cap" readonly>{cap_txt}</textarea>
<button id="copy" data-cap="{cap_attr}">캡션 복사하기</button>
<p class="tip">① 카드 이미지를 길게 눌러 저장 → ② 캡션 복사 → ③ 스레드에 사진 4장 + 캡션 올리기</p>
<script>
document.getElementById('copy').addEventListener('click',function(){{
  var t=document.getElementById('cap'); t.select();
  var ok=function(){{ this.textContent='복사됨 ✓'; }}.bind(this);
  if(navigator.clipboard){{ navigator.clipboard.writeText(t.value).then(ok,ok); }}
  else {{ try{{document.execCommand('copy');}}catch(e){{}} ok(); }}
}});
</script>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=4)
    ap.add_argument("--min-discount", type=int, default=50)
    args = ap.parse_args()

    conn = db.connect()
    deals = fetch_deals(conn, args.min_discount, 200)
    conn.close()
    # 썸네일 있는 것만, 상위 count개
    deals = [d for d in deals if d.get("thumbnail_url")][: args.count]
    if not deals:
        print("[!] 카드로 만들 딜이 없습니다. collect.py → issue.py 를 먼저 도세요.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for i, deal in enumerate(deals, 1):
        card = make_card(deal, i)
        # JPEG(q90). 상품사진이라 화질 손실 거의 없고 용량은 PNG의 1/5 수준 → 저장소 절약.
        card.save(OUT_DIR / f"{i}.jpg", "JPEG", quality=90, optimize=True)
        print(f"    [+] cards/{i}.jpg · TOP{i} · {deal.get('display_name','')[:24]}")

    caption = build_caption(deals)
    (OUT_DIR / "caption.txt").write_text(caption, encoding="utf-8")

    generated_at = datetime.now(KST).strftime("%m/%d %H:%M")
    (OUT_DIR / "index.html").write_text(
        viewer_html(len(deals), caption, generated_at), encoding="utf-8"
    )

    print(f"[+] 카드 {len(deals)}장 + 캡션 생성 · docs/cards/")
    if SITE_URL:
        print(f"    폰에서 열기: {SITE_URL}/cards/")


if __name__ == "__main__":
    main()
