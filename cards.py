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
from build import DISCLOSURE, SITE_URL, SITE_NAME, fetch_section_products, won

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
HOT = (224, 48, 74)
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
    img_side = 520
    ix = (S - img_side) // 2
    iy = M + pill_h + 44
    d.rounded_rectangle([ix, iy, ix + img_side, iy + img_side], 32, fill=IMGBG)
    thumb = download_image(deal.get("thumbnail_url"))
    if thumb is not None:
        thumb = rounded(thumb.resize((img_side, img_side)), 32)
        card.paste(thumb, (ix, iy), thumb)

    # 할인율 · 가격 (이미지와 텍스트 사이 여백을 넉넉히)
    ty = iy + img_side + 96
    rate = deal.get("effective_rate")
    if rate is None:
        rate = deal.get("discount_rate") or 0
    price = deal.get("effective_price") or deal.get("display_price") or 0
    orig = deal.get("original_price")

    df = font(118, bold=True)
    d.text((M, ty), f"{rate}%", font=df, fill=HOT, anchor="lm")
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
    ny = ty + 104
    nf = font(42, bold=True)
    for line in wrap(d, deal.get("display_name") or "", nf, S - 2 * M, max_lines=2):
        d.text((M, ny), line, font=nf, fill=INK, anchor="lm")
        ny += 60

    # 하단 안내
    d.line([M, S - 96, S - M, S - 96], fill=LINE, width=2)
    ff = font(32, bold=True)
    d.text((M, S - 58), "프로필 링크에서 전체 특가 확인 · hotdeal.help",
           font=ff, fill=DIM, anchor="lm")
    return card


LINK_CAP = 4  # 스레드 본문은 링크 최대 4개까지. 초과분은 이름·가격만.


def _site_domain():
    if SITE_URL:
        return SITE_URL.replace("https://", "").replace("http://", "").rstrip("/")
    return "hotdeal.help"


def build_caption(deals):
    """스레드 '본문'. 상품별 개별 링크(최대 4개) + 고지문구.

    스레드는 본문 링크가 4개까지라, 사이트 전체 링크는 본문이 아니라
    '첫 댓글'(build_comment)에 단다. 고지문구는 링크가 없어 4개 제한과 무관하고,
    공정위 지침상 첫 화면에 노출돼야 하므로 본문에 유지한다.
    """
    lines = ["오늘의 토스쇼핑 특가 🔥", ""]
    for i, dl in enumerate(deals, 1):
        name = (dl.get("display_name") or "").strip()
        if len(name) > 20:
            name = name[:20] + "…"
        price = dl.get("effective_price") or dl.get("display_price") or 0
        pid = dl.get("product_id")
        lines.append(f"{i}. {name} {won(price)}원")
        if i <= LINK_CAP and pid:
            lines.append(f"{SITE_URL}/p/{pid}.html" if SITE_URL else f"p/{pid}.html")
    lines += ["", DISCLOSURE]
    return "\n".join(lines)


def build_comment():
    """게시 후 첫 댓글로 달 내용. 본문 링크 4개를 다 써서 전체 링크는 여기에 둔다."""
    return f"전체 특가 → {_site_domain()}"


def viewer_html(deals, caption, comment, generated_at):
    n = len(deals)
    imgs = "".join(
        f'<img class="c" src="{i}.jpg" alt="딜 카드 {i}" loading="lazy">' for i in range(1, n + 1)
    )
    cap_txt = caption.replace("&", "&amp;").replace("<", "&lt;")
    cmt_txt = comment.replace("&", "&amp;").replace("<", "&lt;")

    # 상품별 공유 링크(개별 페이지). 특정 상품 하나만 공유하고 싶을 때.
    link_rows = []
    for i, dl in enumerate(deals, 1):
        pid = dl.get("product_id")
        name = (dl.get("display_name") or "").replace("&", "&amp;").replace("<", "&lt;")
        if len(name) > 28:
            name = name[:28] + "…"
        url = f"{SITE_URL}/p/{pid}.html" if SITE_URL else f"../p/{pid}.html"
        link_rows.append(
            f'<div class="lk"><span class="lk__n">{i}. {name}</span>'
            f'<button class="lk__b" data-url="{url}">링크 복사</button></div>'
        )
    links = "".join(link_rows)

    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>딜 카드 공유 · {SITE_NAME}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0e1524;color:#eef2f8;font-family:"Malgun Gothic","맑은 고딕",system-ui,sans-serif;
  padding:18px;line-height:1.6;max-width:560px;margin:0 auto}}
h1{{font-size:19px;margin-bottom:4px}}
p.sub{{color:#9aa5be;font-size:13px;margin-bottom:16px}}
.share{{width:100%;padding:17px;border:none;border-radius:14px;background:#4b83ff;color:#fff;
  font:inherit;font-weight:800;font-size:17px;cursor:pointer;margin-bottom:8px}}
.share:active{{transform:scale(.99)}}
.share small{{display:block;font-weight:600;font-size:12px;opacity:.85;margin-top:2px}}
.cards{{display:flex;flex-direction:column;gap:12px;margin:16px 0 4px}}
.c{{width:100%;border-radius:14px;border:1px solid #26314a}}
h2{{font-size:15px;margin:22px 0 8px}}
textarea{{width:100%;height:190px;background:#161f31;color:#eef2f8;border:1px solid #26314a;
  border-radius:12px;padding:12px;font:inherit;font-size:14px;resize:vertical}}
button.copy{{margin-top:10px;width:100%;padding:13px;border:none;border-radius:12px;background:#26314a;
  color:#eef2f8;font:inherit;font-weight:700;font-size:15px;cursor:pointer}}
.lk{{display:flex;align-items:center;gap:8px;padding:9px 0;border-top:1px solid #26314a}}
.lk:first-child{{border-top:none}}
.lk__n{{flex:1;min-width:0;font-size:13.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.lk__b{{flex:0 0 auto;padding:8px 12px;border:1px solid #3a4a6a;border-radius:9px;
  background:transparent;color:#9db4ff;font:inherit;font-size:12.5px;font-weight:700;cursor:pointer}}
.tip{{color:#9aa5be;font-size:12.5px;margin-top:16px;line-height:1.7}}
</style></head>
<body>
<h1>🔥 오늘의 딜 카드뉴스</h1>
<p class="sub">{generated_at} 기준 · 버튼 하나로 스레드에 공유</p>

<button class="share" id="share">📤 카드 {n}장 + 본문 한 번에 공유
<small>스레드·인스타 등 선택 → 사진 자동 첨부 · 본문은 자동 복사됨</small></button>

<div class="cards">{imgs}</div>

<h2>① 본문 (붙여넣기)</h2>
<textarea id="cap" readonly>{cap_txt}</textarea>
<button class="copy" id="copy">본문 복사하기</button>

<h2>② 댓글 (게시 후 첫 댓글로)</h2>
<textarea id="cmt" readonly style="height:70px">{cmt_txt}</textarea>
<button class="copy" id="copycmt">댓글 복사하기</button>

<h2>상품별 링크 (하나만 공유할 때)</h2>
{links}

<p class="tip">📱 <b>순서</b>: 맨 위 <b>공유</b> 버튼 → 스레드 선택 → 사진 첨부됨 → <b>본문 붙여넣기</b> → 게시.
게시 후 <b>댓글 복사하기</b> → 그 글의 <b>첫 댓글</b>로 붙여넣기.<br>
(스레드 본문은 링크가 4개까지라, 사이트 전체 링크는 댓글로 답니다.)<br>
공유가 안 되는 기기면: 카드 이미지를 길게 눌러 저장 → 본문·댓글 복사 → 스레드에 올리기.</p>

<script>
var N={n};
function flash(btn,msg){{ var o=btn.textContent; btn.textContent=msg;
  setTimeout(function(){{ btn.textContent=o; }},1500); }}

// 본문/댓글 복사
function bindCopy(btnId, taId){{
  document.getElementById(btnId).addEventListener('click',function(){{
    var t=document.getElementById(taId); t.select();
    var self=this;
    if(navigator.clipboard){{ navigator.clipboard.writeText(t.value).then(function(){{flash(self,'복사됨 ✓');}}); }}
    else {{ try{{document.execCommand('copy');}}catch(e){{}} flash(self,'복사됨 ✓'); }}
  }});
}}
bindCopy('copy','cap');
bindCopy('copycmt','cmt');

// 상품별 링크 복사
[].forEach.call(document.querySelectorAll('.lk__b'),function(b){{
  b.addEventListener('click',function(){{
    var u=b.dataset.url;
    if(navigator.clipboard){{ navigator.clipboard.writeText(u).then(function(){{flash(b,'복사됨 ✓');}}); }}
    else {{ flash(b,u); }}
  }});
}});

// 한 방 공유 (Web Share). 카드 이미지들을 파일로 첨부 + 멘트는 클립보드에 복사.
document.getElementById('share').addEventListener('click',async function(){{
  var cap=document.getElementById('cap').value;
  try{{ await navigator.clipboard.writeText(cap); }}catch(e){{}}
  try{{
    var files=[];
    for(var i=1;i<=N;i++){{
      var r=await fetch(i+'.jpg'); var b=await r.blob();
      files.push(new File([b],'deal'+i+'.jpg',{{type:'image/jpeg'}}));
    }}
    if(navigator.canShare && navigator.canShare({{files:files}})){{
      await navigator.share({{files:files, text:cap}});
      return;
    }}
  }}catch(e){{ if(e && e.name==='AbortError') return; }}
  alert('이 기기는 바로 공유가 안 돼요. 멘트는 복사해뒀으니, 카드 이미지를 길게 눌러 저장한 뒤 스레드에 올려주세요.');
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
    # '오늘의 특가'니까 하루특가(TODAY_DEAL)에서, 할인율 높은 순으로 뽑는다.
    deals = fetch_section_products(conn, "TODAY_DEAL", 60, by_rank=False)
    conn.close()
    # 썸네일 있는 것만, 상위 count개
    deals = [d for d in deals if d.get("thumbnail_url")][: args.count]
    if not deals:
        print("[!] 카드로 만들 하루특가가 없습니다. collect.py → issue.py 를 먼저 도세요.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for i, deal in enumerate(deals, 1):
        card = make_card(deal, i)
        # JPEG(q90). 상품사진이라 화질 손실 거의 없고 용량은 PNG의 1/5 수준 → 저장소 절약.
        card.save(OUT_DIR / f"{i}.jpg", "JPEG", quality=90, optimize=True)
        print(f"    [+] cards/{i}.jpg · TOP{i} · {deal.get('display_name','')[:24]}")

    caption = build_caption(deals)
    comment = build_comment()
    (OUT_DIR / "caption.txt").write_text(caption, encoding="utf-8")
    (OUT_DIR / "comment.txt").write_text(comment, encoding="utf-8")

    generated_at = datetime.now(KST).strftime("%m/%d %H:%M")
    (OUT_DIR / "index.html").write_text(
        viewer_html(deals, caption, comment, generated_at), encoding="utf-8"
    )

    print(f"[+] 카드 {len(deals)}장 + 캡션 생성 · docs/cards/")
    if SITE_URL:
        print(f"    폰에서 열기: {SITE_URL}/cards/")


if __name__ == "__main__":
    main()
