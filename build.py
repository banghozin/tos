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


def load_google_verify():
    """구글 서치콘솔 'HTML 태그' 인증 토큰을 구글인증.txt 에서 읽는다.

    서치콘솔에서 준 <meta name="google-site-verification" content="여기값">
    의 '여기값'만 파일에 한 줄 넣으면 모든 페이지 <head> 에 자동 삽입된다.
    """
    f = ROOT / "구글인증.txt"
    if not f.exists():
        return ""
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            # 혹시 메타태그 전체를 붙여넣어도 content 값만 뽑아낸다
            m = re.search(r'content=["\']?([A-Za-z0-9_\-]+)', line)
            return m.group(1) if m else line
    return ""


SITE_URL = load_site_url()
GOOGLE_VERIFY = load_google_verify()
SITE_NAME = "특가레이더"
SITE_TAGLINE = "토스쇼핑 반값 이하 핫딜만 골라 담는 곳"
# 검색 유입을 노리는 핵심 키워드. 제목·설명·본문에 자연스럽게 녹인다.
SEO_KEYWORDS = ("핫딜, 핫딜모음, 핫딜 사이트, 핫딜 정보, 오늘의 핫딜, 특가, 특가모음, "
                "반값 특가, 최저가, 토스쇼핑, 토스 특가, 할인 정보, 오늘의 특가")
# 공정위 지침에 따른 경제적 이해관계 고지. 지정된 문구를 그대로 쓴다.
DISCLOSURE = "✱ 이 포스팅은 토스쇼핑 쉐어링크 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."

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
    url = html.escape(deal.get("short_url") or "")
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
      <a class="card" href="{url}" target="_blank" rel="nofollow sponsored noopener"
         data-rate="{rate}" data-low="{int(lowest)}" data-end="{html.escape(end or '')}"
         data-cat="{deal.get('category_l1') or ''}">
        <div class="card__media">
          <img src="{thumb}" alt="{name}" loading="lazy" decoding="async">
          <div class="card__rate"><b>{rate}</b><i>%</i></div>
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
        url = html.escape(d.get("short_url") or "")
        rows.append(f"""
        <a class="pop" href="{url}" target="_blank" rel="nofollow sponsored noopener">
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


def render(deals, generated_at):
    cards = "".join(card_html(d) for d in deals)
    popular = popular_html(deals)
    n_all = len(deals)
    n70 = sum(1 for d in deals if (d.get("effective_rate") or 0) >= 70)
    n_low = sum(1 for d in deals if d.get("is_lowest_30d"))
    cat_chips = category_chips(deals)
    canonical, jsonld = seo_head(deals)
    gverify = (f'<meta name="google-site-verification" content="{GOOGLE_VERIFY}">\n'
               if GOOGLE_VERIFY else "")

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
{jsonld}<style>
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
    conn.close()

    if not deals:
        print("[!] 실을 딜이 없습니다. collect.py → issue.py 를 먼저 돌리세요.")
        print("    (쉐어링크가 발급된 상품만 사이트에 실립니다)")
        return

    generated_at = datetime.now(KST).strftime("%m/%d %H:%M")
    now_iso = datetime.now(KST).strftime("%Y-%m-%d")
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "index.html").write_text(render(deals, generated_at), encoding="utf-8")
    (OUT_DIR / "favicon.svg").write_text(FAVICON_SVG, encoding="utf-8")
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")

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
    print(f"    favicon.svg · robots.txt · {'sitemap.xml · ' if SITE_URL else ''}주소: {where}")


if __name__ == "__main__":
    main()
