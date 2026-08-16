"""DB에서 특가를 뽑아 정적 사이트(docs/index.html)를 생성한다.

쉐어링크가 발급된 상품만 싣는다. 링크가 없으면 수익이 발생하지 않으므로
사이트에 올릴 이유가 없다.

사용법:
    python build.py
    python build.py --min-discount 40 --limit 300
"""
import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import db

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "docs"
KST = timezone(timedelta(hours=9))


def load_site_url():
    """배포 주소를 사이트주소.txt 에서 읽는다. (canonical/sitemap/OG 용)

    도메인을 사거나 바꾸면 이 파일 한 줄만 고치면 된다.
    비어 있으면 상대경로로 동작하고 sitemap 은 만들지 않는다.
    """
    f = ROOT / "사이트주소.txt"
    if not f.exists():
        return ""
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line.rstrip("/")
    return ""


def load_verify(filename):
    """검색엔진 'HTML 태그' 인증 토큰을 파일에서 읽는다.

    콘솔에서 준 <meta name="..." content="여기값"> 의 '여기값'만
    파일에 한 줄 넣으면 모든 페이지 <head> 에 자동 삽입된다.
    메타태그를 통째로 붙여넣어도 content 값만 뽑아낸다.
    """
    f = ROOT / filename
    if not f.exists():
        return ""
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            m = re.search(r'content=["\']?([A-Za-z0-9_\-]+)', line)
            return m.group(1) if m else line
    return ""


SITE_URL = load_site_url()
GOOGLE_VERIFY = load_verify("구글인증.txt")
NAVER_VERIFY = load_verify("네이버인증.txt")
SITE_NAME = "특가레이더"
SITE_TAGLINE = "토스쇼핑 반값 이하 핫딜만 골라 담는 곳"
# 검색 유입을 노리는 핵심 키워드. 제목·설명·본문에 자연스럽게 녹인다.
SEO_KEYWORDS = ("핫딜, 핫딜모음, 핫딜 사이트, 핫딜 정보, 오늘의 핫딜, 특가, 특가모음, "
                "반값 특가, 최저가, 토스쇼핑, 토스 특가, 할인 정보, 오늘의 특가")
# 공정위 지침에 따른 경제적 이해관계 고지. 토스가 요구하는 핵심 문구는 유지하되,
# 블로그 글이 아니라 사이트이므로 '이 포스팅은' → '이 사이트는' 으로 맞춘다.
DISCLOSURE = "✱ 이 사이트는 토스쇼핑 쉐어링크 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."

# GoatCounter 방문자 분석. 화면엔 안 보이고 운영자만 대시보드에서 봄:
# https://whrlaos.goatcounter.com  (내 접속 제외는 대시보드 Settings 에서 설정)
ANALYTICS = ('<script data-goatcounter="https://whrlaos.goatcounter.com/count" '
             'async src="//gc.zgo.at/count.js"></script>')

# 라디에이더 + 불꽃 파비콘 (파란 배경, 흰 레이더 링, 중앙 불꽃 블립)
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="#2f6bff"/>'
    '<g fill="none" stroke="#ffffff" stroke-opacity=".5" stroke-width="2.4">'
    '<circle cx="32" cy="35" r="9"/><circle cx="32" cy="35" r="17"/>'
    '<circle cx="32" cy="35" r="25"/></g>'
    '<path d="M32 35 L32 10 A25 25 0 0 1 55 24 Z" fill="#ffffff" fill-opacity=".18"/>'
    '<path d="M32 21c5 4 7.5 8 7.5 12.2A7.5 7.5 0 0 1 24.5 33c0-3 1.8-5.8 4-7.8'
    'c.2 2 1 3 2.2 3.2c1.2-2 .3-5.2 1.3-7.4z" fill="#ffffff"/></svg>'
)


def fetch_deals(conn, min_discount, limit):
    rows = conn.execute(
        """
        SELECT p.*, s.short_url, c.name AS category_name
        FROM products p
        JOIN sharelinks s ON s.product_id = p.product_id
        LEFT JOIN categories c ON c.category_id = p.category_l1
        WHERE p.is_sold_out = 0
          AND (COALESCE(p.effective_rate, p.discount_rate) >= ? OR p.is_lowest_30d = 1)
        ORDER BY COALESCE(p.effective_rate, p.discount_rate) DESC,
                 p.effective_price ASC
        LIMIT ?
        """,
        (min_discount, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_section_products(conn, section_code, limit, by_rank=True):
    """특정 섹션(TODAY_DEAL/BEST_SELLING 등)의 상품을 가져온다. 링크 있는 것만.

    by_rank=True  → 토스 섹션 랭킹 순(베스트랭킹용)
    by_rank=False → 할인율 높은 순(하루특가 카드용)
    """
    order = "si.rank ASC" if by_rank else "COALESCE(p.effective_rate, p.discount_rate) DESC"
    rows = conn.execute(
        f"""
        SELECT p.*, s.short_url, c.name AS category_name, si.rank AS section_rank
        FROM section_items si
        JOIN products p    ON p.product_id = si.product_id
        JOIN sharelinks s  ON s.product_id = p.product_id
        LEFT JOIN categories c ON c.category_id = p.category_l1
        WHERE si.section_code = ? AND p.is_sold_out = 0
        ORDER BY {order}, p.effective_price ASC
        LIMIT ?
        """,
        (section_code, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def pp_url(deal):
    """개별 상품 페이지 경로(사이트 내부 상대링크). index.html 과 같은 폴더 기준."""
    return f"p/{deal.get('product_id')}.html"


def won(n):
    return f"{n:,}" if isinstance(n, int) else "-"


def rate_of(deal):
    r = deal.get("effective_rate")
    if r is None:
        r = deal.get("discount_rate") or 0
    return r


def price_of(deal):
    return deal.get("effective_price") or deal.get("display_price") or 0


def deadline_of(deal):
    """카운트다운에 쓸 마감 시각. 하루특가가 있으면 그쪽을 우선."""
    return deal.get("today_deal_end_at") or deal.get("campaign_end_at")


def card_html(deal):
    rate = rate_of(deal)
    name = html.escape(deal.get("display_name") or "")
    thumb = html.escape(deal.get("thumbnail_url") or "")
    purl = html.escape(pp_url(deal))  # 이제 카드는 토스가 아니라 개별 페이지로 (그래프 노출)
    lowest = bool(deal.get("is_lowest_30d"))
    end = deadline_of(deal)

    badges = []
    if lowest:
        badges.append('<span class="badge badge--low">30일 최저가</span>')
    if deal.get("coupon_discount"):
        badges.append(f'<span class="badge">쿠폰 {won(deal["coupon_discount"])}원 포함</span>')
    if deal.get("review_count"):
        badges.append(
            f'<span class="badge badge--quiet">★ {deal.get("review_score")} '
            f'({won(deal["review_count"])})</span>'
        )

    return f"""
      <a class="card" href="{purl}" target="_blank" rel="noopener"
         data-rate="{rate}" data-low="{int(lowest)}" data-end="{html.escape(end or '')}"
         data-cat="{deal.get('category_l1') or ''}" data-id="{deal.get('product_id')}">
        <div class="card__media">
          <img src="{thumb}" alt="{name}" loading="lazy" decoding="async">
          <div class="card__rate"><b>{rate}</b><i>%</i></div>
          <span class="card__share" role="button" tabindex="0" aria-label="공유 링크 복사" data-share>🔗</span>
        </div>
        <div class="card__body">
          <p class="card__name">{name}</p>
          <div class="card__badges">{''.join(badges)}</div>
          <div class="card__price">
            <span class="price">{won(price_of(deal))}<em>원</em></span>
            <s class="was">{won(deal.get('original_price'))}원</s>
          </div>
          <div class="card__end" data-countdown></div>
        </div>
      </a>"""


def popular_html(deals, k=8):
    """조회수(page_view_count) 상위 상품을 '지금 인기'로 뽑는다."""
    ranked = sorted(
        (d for d in deals if isinstance(d.get("page_view_count"), int)),
        key=lambda d: d["page_view_count"], reverse=True,
    )[:k]
    if not ranked:
        return ""
    rows = []
    for i, d in enumerate(ranked, 1):
        name = html.escape(d.get("display_name") or "")
        thumb = html.escape(d.get("thumbnail_url") or "")
        url = html.escape(pp_url(d))
        rows.append(f"""
        <a class="pop" href="{url}" target="_blank" rel="noopener">
          <span class="pop__rank">{i}</span>
          <img src="{thumb}" alt="{name}" loading="lazy">
          <span class="pop__info">
            <span class="pop__name">{name}</span>
            <span class="pop__price"><b>{rate_of(d)}%</b> {won(price_of(d))}원</span>
          </span>
        </a>""")
    return f"""
      <aside class="popular" aria-label="지금 인기 특가">
        <h2>🔥 지금 인기 특가</h2>
        <p class="popular__note">토스쇼핑에서 많이 본 상품 순</p>
        <div class="popular__list">{''.join(rows)}</div>
      </aside>"""


def today_deal_html(items):
    """하루특가 가로 캐러셀. 데스크톱 3개 노출 + 화살표, 모바일 터치 스크롤.
    기존 .filterrow/.filters/.arrow 구조를 재사용해 화살표 JS를 그대로 쓴다."""
    if not items:
        return ""
    cards = []
    for d in items:
        name = html.escape(d.get("display_name") or "")
        thumb = html.escape(d.get("thumbnail_url") or "")
        purl = html.escape(pp_url(d))
        low = '<span class="badge badge--low">30일 최저가</span>' if d.get("is_lowest_30d") else ""
        cards.append(f"""
          <a class="dealcard" href="{purl}" target="_blank" rel="noopener">
            <div class="dealcard__media">
              <img src="{thumb}" alt="{name}" loading="lazy">
              <div class="dealcard__rate"><b>{rate_of(d)}</b><i>%</i></div>
            </div>
            <p class="dealcard__name">{name}</p>
            <div class="dealcard__price"><span class="price">{won(price_of(d))}<em>원</em></span></div>
            <div class="dealcard__badges">{low}</div>
          </a>""")
    return f"""
      <section class="dealsec" aria-label="오늘의 하루특가">
        <h2 class="sec-h">🔥 오늘의 하루특가 <span class="sec-h__note">오늘만 이 가격</span></h2>
        <div class="filterrow dealrow">
          <button class="arrow arrow--l" data-dir="-1" tabindex="-1" aria-label="왼쪽으로">‹</button>
          <div class="filters filters--deal">{''.join(cards)}</div>
          <button class="arrow arrow--r" data-dir="1" tabindex="-1" aria-label="오른쪽으로">›</button>
        </div>
      </section>"""


def best_ranking_html(items):
    """베스트랭킹(BEST_SELLING) 번호 매긴 목록."""
    if not items:
        return ""
    rows = []
    for i, d in enumerate(items, 1):
        name = html.escape(d.get("display_name") or "")
        thumb = html.escape(d.get("thumbnail_url") or "")
        purl = html.escape(pp_url(d))
        badges = []
        if d.get("is_lowest_30d"):
            badges.append('<span class="badge badge--low">30일 최저가</span>')
        if d.get("review_count"):
            badges.append(
                f'<span class="badge badge--quiet">★ {d.get("review_score")} '
                f'({won(d["review_count"])})</span>'
            )
        orig = d.get("original_price")
        was = f'<s class="was">{won(orig)}원</s>' if orig else ""
        rows.append(f"""
        <li><a class="rankrow" href="{purl}" target="_blank" rel="noopener">
          <span class="rankrow__no">{i}</span>
          <img src="{thumb}" alt="{name}" loading="lazy">
          <span class="rankrow__info">
            <span class="rankrow__name">{name}</span>
            <span class="rankrow__badges">{''.join(badges)}</span>
            <span class="rankrow__price"><b>{rate_of(d)}%</b> {won(price_of(d))}원 {was}</span>
          </span>
        </a></li>""")
    return f"""
      <section class="bestrank" aria-label="지금 많이 팔리는 BEST">
        <h2 class="sec-h">지금 많이 팔리는 <span class="sec-h__hl">BEST</span></h2>
        <ol class="rank-list">{''.join(rows)}</ol>
      </section>"""


def category_chips(deals):
    """실제로 딜이 있는 카테고리만, 많은 순으로 칩을 만든다."""
    counts = {}
    for d in deals:
        cid, name = d.get("category_l1"), d.get("category_name")
        if cid and name:
            counts.setdefault((cid, name), 0)
            counts[(cid, name)] += 1
    ordered = sorted(counts.items(), key=lambda kv: -kv[1])
    chips = ['<button class="chip" data-c="all" aria-pressed="true">전체 카테고리</button>']
    for (cid, name), n in ordered:
        chips.append(
            f'<button class="chip" data-c="{cid}" aria-pressed="false">'
            f'{html.escape(name)} <span class="chip__n">{n}</span></button>'
        )
    return "".join(chips)


def seo_head(deals):
    """canonical 링크와 JSON-LD 구조화 데이터를 만든다. SITE_URL 없으면 canonical 생략."""
    canonical = f'<link rel="canonical" href="{SITE_URL}/">\n' if SITE_URL else ""
    if SITE_URL:
        canonical += f'<meta property="og:url" content="{SITE_URL}/">\n'
        canonical += f'<meta property="og:image" content="{SITE_URL}/og.png">\n'

    items = []
    for i, d in enumerate(deals[:30], 1):
        name = json.dumps(d.get("display_name") or "", ensure_ascii=False)
        url = json.dumps(d.get("short_url") or "", ensure_ascii=False)
        items.append(f'{{"@type":"ListItem","position":{i},"name":{name},"url":{url}}}')
    website = {"@context": "https://schema.org", "@type": "WebSite",
               "name": SITE_NAME, "description": SITE_TAGLINE}
    if SITE_URL:
        website["url"] = SITE_URL + "/"
    ld = (
        f'<script type="application/ld+json">{json.dumps(website, ensure_ascii=False)}</script>\n'
        f'<script type="application/ld+json">'
        f'{{"@context":"https://schema.org","@type":"ItemList",'
        f'"name":"토스쇼핑 핫딜 특가 모음","numberOfItems":{len(deals)},'
        f'"itemListElement":[{",".join(items)}]}}</script>\n'
    )
    return canonical, ld


# 개별 상품 페이지에서 첫 페인트 전에 테마를 적용하는 인라인 스크립트(깜빡임 방지).
THEME_INIT = ("<script>try{var t=localStorage.getItem('theme');"
              "if(t)document.documentElement.dataset.theme=t;}catch(e){}</script>")

# 개별 상품 페이지 전용 스타일. 메인과 같은 팔레트/폰트를 쓴다.
DETAIL_CSS = """
:root{
  --bg:#eef2f8; --panel:#ffffff; --line:#e3e9f2; --ink:#141b2e; --dim:#69718a;
  --blue:#2f6bff; --blue-ink:#1b4fd8; --blue-soft:#eaf1ff;
  --hot:#e5484d; --ok:#0a9d6e; --shadow:rgba(20,27,46,.10); --imgbg:#f0f3f8;
  --font:"Malgun Gothic","맑은 고딕","Apple SD Gothic Neo",system-ui,-apple-system,sans-serif;
}
:root[data-theme="dark"]{
  --bg:#0e1524; --panel:#161f31; --line:#26314a; --ink:#eef2f8; --dim:#9aa5be;
  --blue:#4b83ff; --blue-ink:#6b9bff; --blue-soft:#18233c;
  --hot:#ff6b6f; --ok:#2fd39a; --shadow:rgba(0,0,0,.35); --imgbg:#0f1728;
}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0e1524; --panel:#161f31; --line:#26314a; --ink:#eef2f8; --dim:#9aa5be;
  --blue:#4b83ff; --blue-ink:#6b9bff; --blue-soft:#18233c;
  --hot:#ff6b6f; --ok:#2fd39a; --shadow:rgba(0,0,0,.35); --imgbg:#0f1728;
}}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{background:var(--bg);color:var(--ink);font-family:var(--font);font-size:15px;
  line-height:1.5;letter-spacing:-.01em;overflow-x:hidden;-webkit-tap-highlight-color:transparent}
a{color:inherit}
.wrap{max-width:560px;margin:0 auto;
  padding-left:max(16px,env(safe-area-inset-left));padding-right:max(16px,env(safe-area-inset-right))}
.top{display:flex;align-items:center;gap:9px;padding:18px 0 6px}
.top__home{display:flex;align-items:center;gap:7px;text-decoration:none;font-weight:800;font-size:16px}
.top__home img{width:28px;height:28px;border-radius:8px}
.top__home span{color:var(--blue)}
.theme-btn{margin-left:auto;width:38px;height:38px;border-radius:50%;
  border:1px solid var(--line);background:var(--panel);color:var(--ink);
  font-size:17px;line-height:1;cursor:pointer;transition:.15s}
.theme-btn:hover{border-color:var(--blue);color:var(--blue)}
.hero{background:var(--imgbg);border:1px solid var(--line);border-radius:16px;
  overflow:hidden;position:relative;margin-top:8px;aspect-ratio:1/1}
.hero img{width:100%;height:100%;object-fit:cover}
.hero__rate{position:absolute;left:12px;top:12px;background:var(--blue);color:#fff;
  display:flex;align-items:baseline;padding:6px 12px;border-radius:10px;font-weight:800;
  box-shadow:0 3px 10px rgba(47,107,255,.35)}
.hero__rate b{font-size:24px;line-height:1}
.hero__rate i{font-size:12px;font-style:normal;margin-left:1px}
.pname{font-size:18px;line-height:1.45;font-weight:700;margin:16px 0 10px}
.badges{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:12px}
.badge{font-size:12px;font-weight:700;border-radius:7px;border:1px solid var(--line);
  color:var(--dim);padding:4px 9px}
.badge--low{border-color:var(--ok);color:var(--ok);background:color-mix(in srgb,var(--ok) 12%,transparent)}
.pricebox{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;
  padding:14px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.pricebox .price{font-weight:800;font-size:30px;color:var(--ink)}
.pricebox .price em{font-style:normal;font-size:15px;font-weight:700;margin-left:2px}
.pricebox .was{font-size:15px;color:#9aa2b5;text-decoration:line-through}
/* 가격 변동 그래프 */
.chart-wrap{border:1px solid var(--line);background:var(--panel);border-radius:14px;
  padding:14px 14px 10px;margin:16px 0}
.chart-wrap h2{font-size:14px;font-weight:800;margin-bottom:2px}
.chart-note,.chart-empty{font-size:12px;color:var(--dim);margin-bottom:8px}
.chart-empty{margin-bottom:0;padding:6px 0}
.chart{width:100%;height:auto;display:block;overflow:visible}
.chart-area{fill:color-mix(in srgb,var(--blue) 12%,transparent);stroke:none}
.chart-line{fill:none;stroke:var(--blue);stroke-width:2.4;stroke-linejoin:round;stroke-linecap:round}
.chart-cur{fill:var(--blue);stroke:var(--panel);stroke-width:2}
.chart-min{fill:var(--ok);stroke:var(--panel);stroke-width:2}
.chart-lbl{fill:var(--dim);font-size:11px;font-weight:700}
.chart-min-lbl{fill:var(--ok);font-size:11px;font-weight:800}
/* 고지 문구 + 구매 버튼 */
.disclosure{border:1px solid var(--blue);border-left-width:4px;background:var(--blue-soft);
  color:var(--ink);font-size:13.5px;font-weight:600;border-radius:10px;
  padding:13px 15px;margin:16px 0 10px;line-height:1.6}
.buy{display:flex;align-items:center;justify-content:center;gap:6px;background:var(--blue);
  color:#fff;font-weight:800;font-size:17px;padding:16px;border-radius:12px;
  text-decoration:none;box-shadow:0 8px 22px rgba(47,107,255,.35)}
.buy:active{transform:scale(.99)}
.note{font-size:12px;color:var(--dim);text-align:center;margin-top:10px;line-height:1.6}
footer{border-top:1px solid var(--line);margin-top:22px;padding:18px 0 60px;
  color:var(--dim);font-size:12px;line-height:1.7}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""


def fetch_price_history(conn, product_id, cap=400):
    """observations 에 쌓인 실구매가 이력을 시간순으로 가져온다(최근 cap개).

    관측은 collect.py 에서 분기 단위로 보관하므로(하루 4회 × ~90일 ≈ 360개) cap 400 이면
    이번 분기 전체가 그래프에 담긴다. 정적 SVG 라 점이 수백 개여도 렌더 부하는 없다.
    """
    rows = conn.execute(
        """SELECT observed_at, effective_price FROM observations
           WHERE product_id=? AND effective_price IS NOT NULL
           ORDER BY observed_at""",
        (product_id,),
    ).fetchall()
    hist = [(r["observed_at"], r["effective_price"]) for r in rows]
    return hist[-cap:]


def price_chart_svg(history):
    """가격 이력을 정적 SVG 꺾은선으로 그린다. 관측점이 2개 미만이면 ''(그래프 생략)."""
    pts = [(t, p) for t, p in history if isinstance(p, int)]
    if len(pts) < 2:
        return ""
    prices = [p for _, p in pts]
    lo, hi = min(prices), max(prices)
    n = len(pts)
    W, H = 600, 200
    padL, padR, padT, padB = 10, 22, 20, 26
    span = (hi - lo) or 1

    def X(i):
        return padL + (W - padL - padR) * (i / (n - 1))

    def Y(p):
        return padT + (H - padT - padB) * (1 - (p - lo) / span)

    line = " ".join(f"{X(i):.1f},{Y(p):.1f}" for i, (_, p) in enumerate(pts))
    area = f"{X(0):.1f},{H-padB:.1f} " + line + f" {X(n-1):.1f},{H-padB:.1f}"
    cur_i, cur_p = n - 1, prices[-1]
    min_i = min(range(n), key=lambda i: prices[i])

    def lbl_date(t):
        s = str(t)
        return s[5:10].replace("-", ".") if len(s) >= 10 else ""

    d0, d1 = lbl_date(pts[0][0]), lbl_date(pts[-1][0])
    return (
        f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="가격 변동 그래프">'
        f'<polyline class="chart-area" points="{area}"/>'
        f'<polyline class="chart-line" points="{line}"/>'
        f'<circle class="chart-min" cx="{X(min_i):.1f}" cy="{Y(prices[min_i]):.1f}" r="4"/>'
        f'<circle class="chart-cur" cx="{X(cur_i):.1f}" cy="{Y(cur_p):.1f}" r="4.5"/>'
        f'<text class="chart-lbl" x="{X(0):.0f}" y="13">최고 {won(hi)}원</text>'
        f'<text class="chart-min-lbl" x="{X(min_i):.1f}" y="{Y(prices[min_i])-8:.1f}" '
        f'text-anchor="middle">최저 {won(lo)}</text>'
        f'<text class="chart-lbl" x="{X(0):.0f}" y="{H-8}">{d0}</text>'
        f'<text class="chart-lbl" x="{W-padR:.0f}" y="{H-8}" text-anchor="end">{d1}</text>'
        f'</svg>'
    )


def product_page_html(deal, chart_svg):
    """상품 하나짜리 공유용 페이지. 검색엔 태우지 않는다(noindex)."""
    pid = deal.get("product_id")
    name = html.escape(deal.get("display_name") or "")
    thumb = html.escape(deal.get("thumbnail_url") or "")
    buy = html.escape(deal.get("short_url") or "")
    rate = rate_of(deal)
    price = price_of(deal)
    orig = deal.get("original_price")
    lowest = bool(deal.get("is_lowest_30d"))

    icon = f"{SITE_URL}/favicon.svg" if SITE_URL else "../favicon.svg"
    home = f"{SITE_URL}/" if SITE_URL else "../index.html"
    page_url = f"{SITE_URL}/p/{pid}.html" if SITE_URL else ""
    ogurl = f'<meta property="og:url" content="{page_url}">\n' if page_url else ""
    title = f"{name} · {rate}% {won(price)}원 | {SITE_NAME}"
    desc = f"{rate}% 할인 · {won(price)}원" + (f" · 정가 {won(orig)}원" if orig else "")

    badges = []
    if lowest:
        badges.append('<span class="badge badge--low">30일 최저가</span>')
    if deal.get("coupon_discount"):
        badges.append(f'<span class="badge">쿠폰 {won(deal["coupon_discount"])}원 포함</span>')
    if deal.get("review_count"):
        badges.append(f'<span class="badge">★ {deal.get("review_score")} ({won(deal["review_count"])})</span>')
    badge_html = f'<div class="badges">{"".join(badges)}</div>' if badges else ""

    if chart_svg:
        chart_block = (
            '<div class="chart-wrap"><h2>📉 가격 변동</h2>'
            '<p class="chart-note">특가레이더가 수집할 때마다 기록한 실구매가예요.</p>'
            f'{chart_svg}</div>'
        )
    else:
        chart_block = (
            '<div class="chart-wrap"><h2>📉 가격 변동</h2>'
            '<p class="chart-empty">가격 추적을 막 시작했어요. 갱신이 쌓이면 변동 그래프가 나타납니다.</p></div>'
        )

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#2f6bff" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0e1524" media="(prefers-color-scheme: dark)">
<meta name="format-detection" content="telephone=no">
<meta name="robots" content="noindex,follow">
{THEME_INIT}
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="icon" href="{icon}" type="image/svg+xml">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:title" content="{name}">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{thumb}">
{ogurl}<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{name}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{thumb}">
{ANALYTICS}
<style>{DETAIL_CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <a class="top__home" href="{home}">
      <img src="{icon}" alt="" width="28" height="28">특가<span>레이더</span>
    </a>
    <button class="theme-btn" id="themeBtn" aria-label="라이트/다크 전환">🌙</button>
  </div>

  <div class="hero">
    <img src="{thumb}" alt="{name}" decoding="async">
    <div class="hero__rate"><b>{rate}</b><i>%</i></div>
  </div>

  <h1 class="pname">{name}</h1>
  {badge_html}
  <div class="pricebox">
    <span class="price">{won(price)}<em>원</em></span>
    <span class="was">{won(orig)}원</span>
  </div>

  {chart_block}

  <p class="disclosure">{DISCLOSURE}</p>
  <a class="buy" href="{buy}" target="_blank" rel="nofollow sponsored noopener">토스에서 구매하기 →</a>
  <p class="note">가격과 재고는 수시로 바뀝니다. 결제 화면에서 최종 가격을 다시 확인해 주세요.</p>

  <footer>
    <p>{DISCLOSURE}</p>
    <p>ⓒ {SITE_NAME} · 토스쇼핑 쉐어링크</p>
  </footer>
</div>

<script>
(function(){{
  var b=document.getElementById('themeBtn');
  function cur(){{var t=document.documentElement.dataset.theme;
    return t||(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');}}
  function ico(){{b.textContent=cur()==='dark'?'☀️':'🌙';}}
  ico();
  b.addEventListener('click',function(){{
    var n=cur()==='dark'?'light':'dark';
    document.documentElement.dataset.theme=n;
    try{{localStorage.setItem('theme',n);}}catch(e){{}}
    ico();
  }});
}})();
</script>
</body>
</html>
"""


def render(deals, today_deals, best_ranking, generated_at):
    cards = "".join(card_html(d) for d in deals)
    popular = popular_html(deals)
    today_html = today_deal_html(today_deals)
    best_html = best_ranking_html(best_ranking)
    n_all = len(deals)
    n70 = sum(1 for d in deals if (d.get("effective_rate") or 0) >= 70)
    n_low = sum(1 for d in deals if d.get("is_lowest_30d"))
    cat_chips = category_chips(deals)
    canonical, jsonld = seo_head(deals)
    gverify = ""
    if GOOGLE_VERIFY:
        gverify += f'<meta name="google-site-verification" content="{GOOGLE_VERIFY}">\n'
    if NAVER_VERIFY:
        gverify += f'<meta name="naver-site-verification" content="{NAVER_VERIFY}">\n'

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#2f6bff" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0e1524" media="(prefers-color-scheme: dark)">
<meta name="format-detection" content="telephone=no">
<script>try{{var t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
<title>핫딜 모음 · 토스쇼핑 반값 특가 | {SITE_NAME}</title>
<meta name="description" content="핫딜 모음 사이트 {SITE_NAME}. 토스쇼핑에서 50% 이상 할인되거나 30일 최저가인 상품만 자동으로 모아 보여줍니다. {generated_at} 기준 {n_all}개 특가 업데이트.">
<meta name="keywords" content="{SEO_KEYWORDS}">
{gverify}<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="favicon.svg">
{canonical}<meta property="og:type" content="website">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:title" content="핫딜 모음 · 토스쇼핑 반값 특가 | {SITE_NAME}">
<meta property="og:description" content="토스쇼핑 50% 이상 할인 · 30일 최저가 {n_all}개 · {generated_at} 갱신">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="핫딜 모음 · 토스쇼핑 반값 특가 | {SITE_NAME}">
<meta name="twitter:description" content="토스쇼핑 반값 이하 핫딜 특가 {n_all}개를 자동으로 모읍니다.">
{jsonld}{ANALYTICS}
<style>
:root{{
  --bg:#eef2f8; --panel:#ffffff; --line:#e3e9f2;
  --ink:#141b2e; --dim:#69718a;
  --blue:#2f6bff; --blue-ink:#1b4fd8; --blue-soft:#eaf1ff;
  --hot:#e5484d; --ok:#0a9d6e; --shadow:rgba(20,27,46,.10); --imgbg:#f0f3f8;
  --font:"Malgun Gothic","맑은 고딕","Apple SD Gothic Neo",system-ui,-apple-system,sans-serif;
}}
/* 다크 팔레트: 토글(data-theme) 또는 시스템 설정을 따른다 */
:root[data-theme="dark"]{{
  --bg:#0e1524; --panel:#161f31; --line:#26314a;
  --ink:#eef2f8; --dim:#9aa5be;
  --blue:#4b83ff; --blue-ink:#6b9bff; --blue-soft:#18233c;
  --hot:#ff6b6f; --ok:#2fd39a; --shadow:rgba(0,0,0,.35); --imgbg:#0f1728;
}}
@media(prefers-color-scheme:dark){{
  :root:not([data-theme="light"]){{
    --bg:#0e1524; --panel:#161f31; --line:#26314a;
    --ink:#eef2f8; --dim:#9aa5be;
    --blue:#4b83ff; --blue-ink:#6b9bff; --blue-soft:#18233c;
    --hot:#ff6b6f; --ok:#2fd39a; --shadow:rgba(0,0,0,.35); --imgbg:#0f1728;
  }}
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{-webkit-text-size-adjust:100%;scroll-behavior:smooth}}
body{{
  background:var(--bg); color:var(--ink); font-family:var(--font);
  font-size:15px; line-height:1.5; letter-spacing:-.01em;
  overflow-x:hidden; -webkit-tap-highlight-color:transparent;
}}
a{{color:inherit}}
.wrap{{
  max-width:1200px; margin:0 auto;
  padding-left:max(16px,env(safe-area-inset-left));
  padding-right:max(16px,env(safe-area-inset-right));
}}

/* ── 헤더 ── */
header{{padding:26px 0 16px}}
.brand{{display:flex;align-items:center;gap:11px}}
.theme-btn{{
  margin-left:auto;flex:0 0 auto;width:40px;height:40px;border-radius:50%;
  border:1px solid var(--line);background:var(--panel);color:var(--ink);
  font-size:18px;line-height:1;cursor:pointer;transition:.15s;
}}
.theme-btn:hover{{border-color:var(--blue);color:var(--blue)}}
.brand__mark{{width:38px;height:38px;border-radius:10px;flex:0 0 auto;box-shadow:0 4px 12px rgba(47,107,255,.28)}}
.brand h1{{font-size:clamp(22px,5vw,30px);font-weight:800;letter-spacing:-.02em}}
.brand h1 span{{color:var(--blue)}}
.intro{{margin-top:10px;color:var(--dim);font-size:14px;line-height:1.6;max-width:640px}}
.stats{{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}}
.stat{{
  border:1px solid var(--line);background:var(--panel);border-radius:10px;
  padding:8px 12px;font-size:12.5px;color:var(--dim);font-weight:600;
}}
.stat b{{color:var(--blue);font-weight:800}}

/* ── 필터 ── */
.filterbar{{
  position:sticky;top:0;z-index:8;margin-top:14px;
  background:color-mix(in srgb, var(--bg) 92%, transparent);backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line);
}}
.filterrow{{position:relative}}
.filterrow--cat{{border-top:1px dashed var(--line);margin-top:10px}}
.filters{{display:flex;gap:7px;overflow-x:auto;padding:12px 0;scrollbar-width:none;-webkit-overflow-scrolling:touch}}
.filters::-webkit-scrollbar{{display:none}}
/* 좌우 화살표 (PC에서 넘칠 때만) */
.arrow{{
  position:absolute;top:0;bottom:0;width:36px;border:none;cursor:pointer;z-index:2;
  display:none;align-items:center;justify-content:center;
  color:var(--ink);font-size:20px;font-weight:800;
}}
.arrow--l{{left:0;background:linear-gradient(90deg,var(--bg) 60%,transparent)}}
.arrow--r{{right:0;background:linear-gradient(270deg,var(--bg) 60%,transparent)}}
.filterrow.of-l .arrow--l,
.filterrow.of-r .arrow--r{{display:flex}}
.chip{{
  flex:0 0 auto;border:1px solid var(--line);background:var(--panel);color:var(--dim);
  font-family:inherit;font-size:13px;font-weight:700;border-radius:999px;
  padding:9px 15px;cursor:pointer;white-space:nowrap;transition:.15s;
}}
.chip:hover{{color:var(--ink);border-color:#c6d2e6}}
.chip[aria-pressed="true"]{{background:var(--blue);color:#fff;border-color:var(--blue)}}
.chip__n{{opacity:.55;font-size:11px;margin-left:3px;font-weight:600}}
.count{{font-size:13px;color:var(--dim);font-weight:600;padding:14px 0 0}}

/* ── 레이아웃: 본문 + 인기 사이드 ──
   1fr 대신 minmax(0,1fr) 로 트랙이 내부 콘텐츠 너비만큼 부풀지 않게 한다.
   min-width:0 이 없으면 가로 스크롤 목록이 트랙을 밀어 화면이 넓어진다. */
.layout{{display:grid;grid-template-columns:minmax(0,1fr) 296px;gap:20px;align-items:start;margin:14px 0 40px}}
.layout>main{{min-width:0}}
.grid{{min-width:0}}

/* ── 인기 사이드 ── */
.popular{{
  position:sticky;top:118px;background:var(--panel);
  border:1px solid var(--line);border-radius:16px;padding:16px 16px 6px;
  box-shadow:0 2px 10px var(--shadow);
}}
.popular h2{{font-size:15px;font-weight:800}}
.popular__note{{font-size:11.5px;color:var(--dim);margin:3px 0 10px}}
.popular__list{{display:flex;flex-direction:column}}
.pop{{display:flex;align-items:center;gap:10px;padding:10px 0;border-top:1px solid var(--line);text-decoration:none}}
.pop:first-child{{border-top:none}}
.pop__rank{{
  flex:0 0 auto;width:20px;text-align:center;font-weight:800;font-size:14px;color:var(--blue);
}}
.pop img{{width:46px;height:46px;border-radius:9px;object-fit:cover;flex:0 0 auto;background:var(--imgbg)}}
.pop__info{{display:flex;flex-direction:column;gap:2px;min-width:0}}
.pop__name{{font-size:12.5px;line-height:1.35;color:var(--ink);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
.pop__price{{font-size:12.5px;color:var(--dim);font-weight:600}}
.pop__price b{{color:var(--hot);font-weight:800;margin-right:3px}}

/* ── 카드 그리드 ── */
.grid{{
  display:grid;gap:12px;
  grid-template-columns:repeat(auto-fill,minmax(min(100%,220px),1fr));
}}
.card{{
  background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden;
  text-decoration:none;display:flex;flex-direction:column;
  transition:box-shadow .18s, transform .18s, border-color .18s; animation:rise .5s both;
}}
.card:hover{{box-shadow:0 10px 26px var(--shadow);border-color:color-mix(in srgb,var(--blue) 35%,var(--line))}}
.card[hidden]{{display:none}}
@media(hover:hover){{ .card:hover{{transform:translateY(-3px)}} }}
@keyframes rise{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:none}}}}
.card__media{{position:relative;aspect-ratio:1/1;overflow:hidden;background:var(--imgbg)}}
.card__media img{{width:100%;height:100%;object-fit:cover;transition:transform .5s ease}}
.card:hover .card__media img{{transform:scale(1.05)}}
.card__rate{{
  position:absolute;left:10px;top:10px;background:var(--blue);color:#fff;
  display:flex;align-items:baseline;padding:4px 9px;border-radius:9px;font-weight:800;
  box-shadow:0 3px 10px rgba(47,107,255,.35);
}}
.card__rate b{{font-size:19px;line-height:1;font-weight:800}}
.card__rate i{{font-size:11px;font-style:normal;margin-left:1px}}
.card__share{{
  position:absolute;right:8px;top:8px;width:30px;height:30px;border-radius:50%;z-index:2;
  display:flex;align-items:center;justify-content:center;font-size:13px;line-height:1;
  background:color-mix(in srgb,var(--panel) 82%,transparent);border:1px solid var(--line);
  -webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px);cursor:pointer;transition:.15s;
}}
.card__share:hover{{border-color:var(--blue);color:var(--blue)}}
.card__share.copied{{background:var(--ok);color:#fff;border-color:var(--ok)}}
.card__body{{padding:12px 13px 14px;display:flex;flex-direction:column;gap:8px;flex:1}}
.card__name{{
  font-size:13.5px;line-height:1.42;color:var(--ink);font-weight:500;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
}}
.card__badges{{display:flex;flex-wrap:wrap;gap:4px}}
.badge{{
  font-size:11px;font-weight:700;border-radius:6px;
  border:1px solid var(--line);color:var(--dim);padding:3px 7px;
}}
.badge--low{{border-color:var(--ok);color:var(--ok);background:color-mix(in srgb,var(--ok) 12%,transparent)}}
.badge--quiet{{color:var(--dim);font-weight:600}}
.card__price{{margin-top:auto;display:flex;align-items:baseline;gap:7px;flex-wrap:wrap}}
.price{{font-weight:800;font-size:21px;color:var(--ink)}}
.price em{{font-style:normal;font-size:12px;font-weight:600;margin-left:1px}}
.was{{font-size:12.5px;color:#9aa2b5}}
.card__end{{font-size:11.5px;color:var(--dim);font-weight:600;min-height:1em}}
.card__end.urgent{{color:var(--hot);font-weight:700}}

.empty{{padding:60px 0;text-align:center;color:var(--dim);font-size:14px}}

/* ── 상단 섹션: 하루특가 캐러셀 + 베스트랭킹 ── */
.sec-h{{font-size:17px;font-weight:800;letter-spacing:-.02em;margin:22px 0 10px}}
.sec-h__note{{font-size:12px;font-weight:600;color:var(--dim);margin-left:4px}}
.sec-h__hl{{color:var(--blue)}}
/* 하루특가 카드(가로 스크롤 아이템). .filters--deal 은 기존 .filters 스트립 재사용 */
.filters--deal{{gap:10px;align-items:stretch}}
.dealcard{{
  flex:0 0 calc((100% - 20px)/3); min-width:0; text-decoration:none;
  background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden;
  display:flex;flex-direction:column;transition:box-shadow .18s,border-color .18s;
}}
.dealcard:hover{{box-shadow:0 8px 20px var(--shadow);border-color:color-mix(in srgb,var(--blue) 35%,var(--line))}}
.dealcard__media{{position:relative;aspect-ratio:1/1;background:var(--imgbg)}}
.dealcard__media img{{width:100%;height:100%;object-fit:cover}}
.dealcard__rate{{position:absolute;left:8px;top:8px;background:var(--blue);color:#fff;
  display:flex;align-items:baseline;padding:3px 8px;border-radius:8px;font-weight:800;
  box-shadow:0 3px 10px rgba(47,107,255,.35)}}
.dealcard__rate b{{font-size:16px;line-height:1}}
.dealcard__rate i{{font-size:10px;font-style:normal;margin-left:1px}}
.dealcard__name{{font-size:12.5px;line-height:1.35;color:var(--ink);padding:8px 10px 0;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:2.7em}}
.dealcard__price{{padding:2px 10px 0}}
.dealcard__price .price{{font-weight:800;font-size:17px;color:var(--ink)}}
.dealcard__price .price em{{font-style:normal;font-size:11px;font-weight:600;margin-left:1px}}
.dealcard__badges{{padding:6px 10px 10px;display:flex;flex-wrap:wrap;gap:4px;margin-top:auto}}
/* 베스트랭킹 목록 (2열) */
.bestrank{{margin-bottom:6px}}
.rank-list{{list-style:none;display:grid;grid-template-columns:1fr 1fr;gap:0 20px}}
.rankrow{{display:flex;align-items:center;gap:11px;padding:9px 0;text-decoration:none;border-top:1px solid var(--line)}}
.rankrow__no{{flex:0 0 auto;width:22px;text-align:center;font-weight:800;font-size:16px;color:var(--blue)}}
.rankrow img{{width:52px;height:52px;border-radius:10px;object-fit:cover;flex:0 0 auto;background:var(--imgbg)}}
.rankrow__info{{display:flex;flex-direction:column;gap:3px;min-width:0}}
.rankrow__name{{font-size:13px;line-height:1.35;color:var(--ink);
  display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden}}
.rankrow__badges{{display:flex;flex-wrap:wrap;gap:4px}}
.rankrow__price{{font-size:12.5px;color:var(--dim);font-weight:600}}
.rankrow__price b{{color:var(--hot);font-weight:800;margin-right:3px}}
.rankrow__price .was{{font-size:11px;color:#9aa2b5;margin-left:4px}}
@media(max-width:720px){{
  .rank-list{{grid-template-columns:1fr}}
  .dealcard{{flex:0 0 44%}}
}}

/* ── 맨 위로 버튼 ── */
.totop{{
  position:fixed;right:16px;bottom:max(16px,env(safe-area-inset-bottom));
  width:50px;height:50px;border-radius:50%;border:none;cursor:pointer;
  background:var(--blue);color:#fff;font-size:22px;line-height:50px;
  box-shadow:0 8px 22px rgba(47,107,255,.45);
  opacity:0;transform:translateY(12px);pointer-events:none;transition:.25s;z-index:20;
}}
.totop.show{{opacity:1;transform:none;pointer-events:auto}}
.totop:active{{transform:scale(.92)}}

footer{{border-top:1px solid var(--line);padding:24px 0 90px;color:var(--dim);font-size:12.5px}}
.disclosure{{
  border:1px solid var(--blue);border-left-width:4px;background:var(--blue-soft);
  color:var(--ink);font-size:14px;font-weight:600;border-radius:10px;
  padding:14px 16px;margin-bottom:14px;line-height:1.6;
}}

/* ── 태블릿: 인기 패널을 위로 가로 스크롤, 화살표 숨김(터치 스크롤) ── */
@media(max-width:900px){{
  .arrow{{display:none!important}}
  /* 세로 1열로 쌓되, 트랙이 내부 가로 콘텐츠에 밀려 넓어지지 않게 minmax(0,1fr) */
  .layout{{grid-template-columns:minmax(0,1fr);gap:16px}}
  .popular{{position:static;order:-1;padding:12px;min-width:0;max-width:100%}}
  .popular h2{{font-size:14px}}
  .popular__list{{flex-direction:row;overflow-x:auto;gap:8px;scrollbar-width:none;max-width:100%}}
  .popular__list::-webkit-scrollbar{{display:none}}
  .pop{{flex:0 0 190px;border-top:none;border:1px solid var(--line);border-radius:11px;padding:8px}}
  .pop:first-child{{border:1px solid var(--line)}}
}}

/* ── 폰: 카드 밀도를 높여 목록이 덜 비대하게 ── */
@media(max-width:560px){{
  body{{font-size:13.5px}}
  .grid{{grid-template-columns:repeat(2,1fr);gap:8px}}
  .card{{border-radius:12px}}
  .card__rate{{left:7px;top:7px;padding:3px 7px;border-radius:7px}}
  .card__rate b{{font-size:15px}}
  .card__rate i{{font-size:10px}}
  .card__body{{padding:9px 10px 10px;gap:5px}}
  .card__name{{font-size:12px;line-height:1.36}}
  .card__badges{{gap:3px}}
  .badge{{font-size:10px;padding:2px 5px}}
  .badge--quiet{{display:none}}
  .price{{font-size:16px}}
  .price em{{font-size:11px}}
  .was{{font-size:11px}}
  .card__end{{font-size:10.5px}}
  .stat{{padding:7px 10px;font-size:12px}}
  .intro{{font-size:13px}}
}}
@media(max-width:360px){{
  .grid{{gap:7px}}
  .card__body{{padding:8px}}
}}
@media(prefers-reduced-motion:reduce){{ *{{animation:none!important;transition:none!important;scroll-behavior:auto!important}} }}
</style>
</head>
<body>
<div class="wrap">

  <header>
    <div class="brand">
      <img class="brand__mark" src="favicon.svg" alt="" width="38" height="38">
      <h1>특가<span>레이더</span></h1>
      <button class="theme-btn" id="themeBtn" aria-label="라이트/다크 전환">🌙</button>
    </div>
    <p class="intro">
      토스쇼핑 <b>핫딜</b>을 자동으로 모으는 <b>핫딜 모음 사이트</b>예요.
      50% 이상 할인되거나 30일 최저가인 상품만 골라, 하루에도 여러 번 새로 갱신합니다.
    </p>
    <div class="stats">
      <div class="stat">갱신 <b>{generated_at}</b></div>
      <div class="stat">전체 <b>{n_all}</b></div>
      <div class="stat">70%↑ <b>{n70}</b></div>
      <div class="stat">30일최저 <b>{n_low}</b></div>
    </div>
  </header>

  {today_html}
  {best_html}

  <div class="filterbar">
    <div class="filterrow">
      <button class="arrow arrow--l" data-dir="-1" tabindex="-1" aria-label="왼쪽으로">‹</button>
      <nav class="filters" id="filters" aria-label="할인율 필터">
        <button class="chip" data-f="all" aria-pressed="true">전체</button>
        <button class="chip" data-f="50" aria-pressed="false">50% 이상</button>
        <button class="chip" data-f="70" aria-pressed="false">70% 이상</button>
        <button class="chip" data-f="80" aria-pressed="false">80% 이상</button>
        <button class="chip" data-f="low" aria-pressed="false">30일 최저가</button>
        <button class="chip" data-f="today" aria-pressed="false">오늘 마감</button>
      </nav>
      <button class="arrow arrow--r" data-dir="1" tabindex="-1" aria-label="오른쪽으로">›</button>
    </div>
    <div class="filterrow filterrow--cat">
      <button class="arrow arrow--l" data-dir="-1" tabindex="-1" aria-label="왼쪽으로">‹</button>
      <nav class="filters filters--cat" id="cats" aria-label="카테고리 필터">{cat_chips}</nav>
      <button class="arrow arrow--r" data-dir="1" tabindex="-1" aria-label="오른쪽으로">›</button>
    </div>
  </div>

  <p class="count" id="count"></p>

  <div class="layout">
    <main>
      <div class="grid" id="grid">{cards}</div>
      <p class="empty" id="empty" hidden>조건에 맞는 딜이 없어요.</p>
    </main>
    {popular}
  </div>

  <footer>
    <p class="disclosure">{DISCLOSURE}</p>
    <p>가격과 재고는 수시로 바뀝니다. 구매 전 토스쇼핑에서 다시 확인해주세요.</p>
  </footer>
</div>

<button class="totop" id="totop" aria-label="맨 위로">↑</button>

<script>
(function(){{
  var grid=document.getElementById('grid'),
      cards=[].slice.call(grid.children),
      empty=document.getElementById('empty');

  function endMs(s){{
    if(!s) return NaN;
    return new Date(/[Z+]|-\\d\\d:\\d\\d$/.test(s) ? s : s+'+09:00').getTime();
  }}
  function kstToday(){{ return new Date(Date.now()+9*36e5).toISOString().slice(0,10); }}

  cards.slice(0,12).forEach(function(c,i){{ c.style.animationDelay=(i*28)+'ms'; }});

  var fRate='all', fCat='all', countEl=document.getElementById('count');
  function apply(){{
    var today=kstToday(), shown=0;
    cards.forEach(function(c){{
      var rate=+c.dataset.rate, low=c.dataset.low==='1', end=c.dataset.end, ok;
      if(fRate==='all') ok=true;
      else if(fRate==='low') ok=low;
      else if(fRate==='today') ok=!!end && end.slice(0,10)===today;
      else ok=rate>=+fRate;
      if(ok && fCat!=='all') ok=c.dataset.cat===fCat;
      c.hidden=!ok; if(ok) shown++;
    }});
    empty.hidden=shown>0;
    countEl.textContent=shown+'개';
  }}
  function bind(id, set){{
    document.getElementById(id).addEventListener('click', function(e){{
      var btn=e.target.closest('.chip'); if(!btn) return;
      [].forEach.call(this.children,function(b){{ b.setAttribute('aria-pressed', b===btn); }});
      set(btn); apply();
    }});
  }}
  bind('filters', function(b){{ fRate=b.dataset.f; }});
  bind('cats',    function(b){{ fCat =b.dataset.c; }});
  apply();

  // 카드 공유 버튼: 개별 상품 페이지 링크를 클립보드에 복사 (토스 이동은 막는다)
  function copyShare(s){{
    var card=s.closest('.card'); if(!card) return;
    var link=location.origin+'/p/'+card.dataset.id+'.html';
    function done(){{ s.classList.add('copied'); s.textContent='✓';
      setTimeout(function(){{ s.classList.remove('copied'); s.textContent='🔗'; }}, 1200); }}
    if(navigator.clipboard && navigator.clipboard.writeText){{
      navigator.clipboard.writeText(link).then(done, done);
    }} else {{
      var t=document.createElement('textarea'); t.value=link;
      t.style.position='fixed'; t.style.opacity='0'; document.body.appendChild(t);
      t.focus(); t.select();
      try{{ document.execCommand('copy'); }}catch(e){{}}
      document.body.removeChild(t); done();
    }}
  }}
  grid.addEventListener('click', function(e){{
    var s=e.target.closest('[data-share]'); if(!s) return;
    e.preventDefault(); e.stopPropagation(); copyShare(s);
  }});
  grid.addEventListener('keydown', function(e){{
    var s=e.target.closest('[data-share]'); if(!s) return;
    if(e.key==='Enter'||e.key===' '){{ e.preventDefault(); e.stopPropagation(); copyShare(s); }}
  }});

  // 마감 카운트다운
  function tick(){{
    var now=Date.now();
    cards.forEach(function(c){{
      var end=c.dataset.end; if(!end) return;
      var el=c.querySelector('[data-countdown]'), left=endMs(end)-now;
      if(isNaN(left)) return;
      if(left<=0){{ el.textContent='마감됨'; el.classList.add('urgent'); return; }}
      var h=Math.floor(left/36e5), m=Math.floor(left%36e5/6e4), d=Math.floor(h/24);
      el.textContent = d>=1 ? (d+'일 남음') : (h+'시간 '+m+'분 남음');
      el.classList.toggle('urgent', h<6);
    }});
  }}
  tick(); setInterval(tick, 30000);

  // 맨 위로 버튼
  var totop=document.getElementById('totop');
  function onScroll(){{ totop.classList.toggle('show', window.scrollY>500); }}
  window.addEventListener('scroll', onScroll, {{passive:true}}); onScroll();
  totop.addEventListener('click', function(){{
    window.scrollTo({{top:0, behavior:'smooth'}});
  }});

  // 다크/라이트 토글
  var themeBtn=document.getElementById('themeBtn');
  function curTheme(){{
    var t=document.documentElement.dataset.theme;
    if(t) return t;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }}
  function setIcon(){{ themeBtn.textContent = curTheme()==='dark' ? '☀️' : '🌙'; }}
  setIcon();
  themeBtn.addEventListener('click', function(){{
    var next = curTheme()==='dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try{{ localStorage.setItem('theme', next); }}catch(e){{}}
    setIcon();
  }});

  // 필터 좌우 화살표 (PC에서 넘칠 때)
  [].forEach.call(document.querySelectorAll('.filterrow'), function(row){{
    var strip=row.querySelector('.filters');
    function upd(){{
      row.classList.toggle('of-l', strip.scrollLeft > 4);
      row.classList.toggle('of-r', strip.scrollLeft < strip.scrollWidth - strip.clientWidth - 4);
    }}
    strip.addEventListener('scroll', upd, {{passive:true}});
    window.addEventListener('resize', upd);
    [].forEach.call(row.querySelectorAll('.arrow'), function(a){{
      a.addEventListener('click', function(){{
        strip.scrollBy({{left:(+a.dataset.dir)*strip.clientWidth*0.8, behavior:'smooth'}});
      }});
    }});
    upd();
  }});
}})();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-discount", type=int, default=50)
    ap.add_argument("--limit", type=int, default=400)
    args = ap.parse_args()

    conn = db.connect()
    deals = fetch_deals(conn, args.min_discount, args.limit)
    # 상단 섹션: 하루특가(랭크순 최대 24) + 베스트랭킹(랭크순 15)
    today_deals = fetch_section_products(conn, "TODAY_DEAL", 24, by_rank=True)
    best_ranking = fetch_section_products(conn, "BEST_SELLING", 15, by_rank=True)

    if not deals:
        conn.close()
        print("[!] 실을 딜이 없습니다. collect.py → issue.py 를 먼저 돌리세요.")
        print("    (쉐어링크가 발급된 상품만 사이트에 실립니다)")
        return

    generated_at = datetime.now(KST).strftime("%m/%d %H:%M")
    now_iso = datetime.now(KST).strftime("%Y-%m-%d")
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "index.html").write_text(
        render(deals, today_deals, best_ranking, generated_at), encoding="utf-8"
    )
    (OUT_DIR / "favicon.svg").write_text(FAVICON_SVG, encoding="utf-8")
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")

    # 개별 상품 페이지(공유용). 검색엔 안 태우고(noindex) sitemap 에도 안 넣는다.
    # 메인 그리드 + 하루특가 + 베스트랭킹에 나오는 모든 상품에 대해 생성(합집합).
    pdir = OUT_DIR / "p"
    pdir.mkdir(exist_ok=True)
    page_products = {}
    for d in deals + today_deals + best_ranking:
        pid = d.get("product_id")
        if pid is not None:
            page_products.setdefault(pid, d)
    current_ids = set()
    for pid, d in page_products.items():
        current_ids.add(str(pid))
        chart = price_chart_svg(fetch_price_history(conn, pid))
        (pdir / f"{pid}.html").write_text(product_page_html(d, chart), encoding="utf-8")
    # 더 이상 노출되지 않는(품절·기준 미달) 상품 페이지는 삭제한다.
    removed = 0
    for f in pdir.glob("*.html"):
        if f.stem not in current_ids:
            f.unlink()
            removed += 1
    conn.close()

    robots = "User-agent: *\nAllow: /\n"
    if SITE_URL:
        robots += f"Sitemap: {SITE_URL}/sitemap.xml\n"
    (OUT_DIR / "robots.txt").write_text(robots, encoding="utf-8")

    if SITE_URL:
        (OUT_DIR / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"  <url><loc>{SITE_URL}/</loc><lastmod>{now_iso}</lastmod>"
            "<changefreq>hourly</changefreq><priority>1.0</priority></url>\n"
            "</urlset>\n",
            encoding="utf-8",
        )

    size = (OUT_DIR / "index.html").stat().st_size
    where = SITE_URL or "(사이트주소.txt 비어있음 — 상대경로)"
    print(f"[+] docs/index.html 생성 · 딜 {len(deals)}개 · {size/1024:.0f}KB")
    print(f"[+] docs/p/ 개별 페이지 {len(current_ids)}개" + (f" (오래된 {removed}개 삭제)" if removed else ""))
    print(f"    favicon.svg · robots.txt · {'sitemap.xml · ' if SITE_URL else ''}주소: {where}")


if __name__ == "__main__":
    main()
