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

SITE_NAME = "특가레이더"
SITE_TAGLINE = "토스쇼핑 반값 이하만 골라 담는 곳"
DISCLOSURE = ("이 사이트는 토스쇼핑 쉐어링크 활동의 일환으로, "
              "이에 따른 일정액의 수수료를 제공받습니다. "
              "구매자가 부담하는 가격은 변하지 않습니다.")


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


def deadline_of(deal):
    """카운트다운에 쓸 마감 시각. 하루특가가 있으면 그쪽을 우선."""
    return deal.get("today_deal_end_at") or deal.get("campaign_end_at")


def card_html(deal):
    rate = deal.get("effective_rate")
    if rate is None:
        rate = deal.get("discount_rate") or 0
    price = deal.get("effective_price") or deal.get("display_price") or 0
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
          <img src="{thumb}" alt="" loading="lazy" decoding="async">
          <div class="card__rate"><b>{rate}</b><i>%</i></div>
        </div>
        <div class="card__body">
          <p class="card__name">{name}</p>
          <div class="card__badges">{''.join(badges)}</div>
          <div class="card__price">
            <span class="price">{won(price)}<em>원</em></span>
            <s class="was">{won(deal.get('original_price'))}원</s>
          </div>
          <div class="card__end" data-countdown></div>
        </div>
      </a>"""


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


def render(deals, generated_at):
    cards = "".join(card_html(d) for d in deals)
    n_all = len(deals)
    n70 = sum(1 for d in deals if (d.get("effective_rate") or 0) >= 70)
    n_low = sum(1 for d in deals if d.get("is_lowest_30d"))
    cat_chips = category_chips(deals)

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{SITE_NAME} — {SITE_TAGLINE}</title>
<meta name="description" content="토스쇼핑에서 50% 이상 할인되거나 30일 최저가인 상품만 자동으로 모읍니다. {generated_at} 기준 {n_all}개.">
<meta property="og:title" content="{SITE_NAME}">
<meta property="og:description" content="{SITE_TAGLINE} · {n_all}개 갱신됨">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=IBM+Plex+Mono:wght@500;700&display=swap" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" rel="stylesheet">
<style>
:root{{
  --bg:#0b0b0c; --panel:#141416; --line:#26262a;
  --ink:#f2f2ef; --dim:#8b8b93;
  --acid:#d8ff3e; --hot:#ff4a2b;
  --font-kr:"Pretendard Variable",Pretendard,sans-serif;
  --font-num:"IBM Plex Mono",monospace;
  --font-display:"Anton",var(--font-kr);
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{-webkit-text-size-adjust:100%}}
body{{
  background:var(--bg); color:var(--ink); font-family:var(--font-kr);
  font-size:15px; line-height:1.5; letter-spacing:-.01em;
  background-image:
    radial-gradient(900px 380px at 82% -8%, rgba(216,255,62,.09), transparent 62%),
    radial-gradient(700px 320px at 8% 0%, rgba(255,74,43,.07), transparent 60%);
  background-repeat:no-repeat;
}}
/* 미세한 그레인 — 평평한 검정을 피한다 */
body::before{{
  content:"";position:fixed;inset:0;pointer-events:none;z-index:9;opacity:.16;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='140' height='140'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3'/></filter><rect width='140' height='140' filter='url(%23n)' opacity='.5'/></svg>");
  mix-blend-mode:overlay;
}}
.wrap{{max-width:1180px;margin:0 auto;padding:0 16px}}

/* ── 헤더: 전광판 ── */
header{{padding:34px 0 18px;border-bottom:1px solid var(--line)}}
.brand{{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}}
.brand h1{{
  font-family:var(--font-display);font-size:clamp(34px,8vw,60px);
  letter-spacing:.02em;line-height:.92;text-transform:uppercase;
}}
.brand h1 span{{color:var(--acid)}}
.brand p{{color:var(--dim);font-size:13px}}
.stats{{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px;font-family:var(--font-num)}}
.stat{{
  border:1px solid var(--line);background:var(--panel);
  padding:7px 11px;font-size:12px;color:var(--dim);
}}
.stat b{{color:var(--acid);font-weight:700}}

/* ── 필터 ── */
.filterbar{{
  position:sticky;top:0;z-index:8;
  background:rgba(11,11,12,.94);backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line);
}}
.filters{{
  display:flex;gap:7px;overflow-x:auto;padding:12px 0 0;
  scrollbar-width:none;-webkit-overflow-scrolling:touch;
}}
.filters--cat{{padding:8px 0 12px;border-top:1px dashed #1f1f23;margin-top:10px}}
.filters::-webkit-scrollbar{{display:none}}
.chip__n{{opacity:.5;font-size:10px;margin-left:3px}}
.chip[aria-pressed="true"] .chip__n{{opacity:.6}}
.count{{
  font-family:var(--font-num);font-size:12px;color:var(--dim);
  padding:14px 0 0;
}}
.chip{{
  flex:0 0 auto;border:1px solid var(--line);background:transparent;color:var(--dim);
  font-family:var(--font-num);font-size:12px;font-weight:500;
  padding:8px 13px;cursor:pointer;white-space:nowrap;transition:.15s;
}}
.chip:hover{{color:var(--ink);border-color:#3a3a41}}
.chip[aria-pressed="true"]{{background:var(--acid);color:#0b0b0c;border-color:var(--acid);font-weight:700}}

/* ── 카드 ── */
.grid{{
  display:grid;gap:1px;background:var(--line);
  border:1px solid var(--line);margin:20px 0 40px;
  grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr));
}}
.card{{
  background:var(--bg);color:inherit;text-decoration:none;display:flex;flex-direction:column;
  transition:background .18s, transform .18s;
  animation:rise .5s both;
}}
.card:hover{{background:var(--panel)}}
/* display:flex 가 [hidden] 의 display:none 을 덮어쓰므로 명시적으로 눌러준다 */
.card[hidden]{{display:none}}
@media(hover:hover){{ .card:hover{{transform:translateY(-2px)}} }}
@keyframes rise{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:none}}}}
.card__media{{position:relative;aspect-ratio:1/1;overflow:hidden;background:#101012}}
.card__media img{{width:100%;height:100%;object-fit:cover;transition:transform .5s ease}}
.card:hover .card__media img{{transform:scale(1.05)}}
.card__rate{{
  position:absolute;left:0;bottom:0;background:var(--acid);color:#0b0b0c;
  font-family:var(--font-display);display:flex;align-items:baseline;
  padding:5px 10px 3px;letter-spacing:.01em;
}}
.card__rate b{{font-size:27px;line-height:1;font-weight:400}}
.card__rate i{{font-size:14px;font-style:normal;margin-left:1px}}
.card__body{{padding:12px 13px 14px;display:flex;flex-direction:column;gap:8px;flex:1}}
.card__name{{
  font-size:13px;line-height:1.42;color:#dcdcd8;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
}}
.card__badges{{display:flex;flex-wrap:wrap;gap:4px}}
.badge{{
  font-family:var(--font-num);font-size:10px;font-weight:500;
  border:1px solid var(--line);color:var(--dim);padding:2px 6px;
}}
.badge--low{{border-color:var(--acid);color:var(--acid)}}
.badge--quiet{{opacity:.65}}
.card__price{{margin-top:auto;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}}
.price{{font-family:var(--font-num);font-weight:700;font-size:21px;color:var(--ink)}}
.price em{{font-style:normal;font-size:12px;font-weight:500;margin-left:1px}}
.was{{font-family:var(--font-num);font-size:12px;color:#5f5f68}}
.card__end{{font-family:var(--font-num);font-size:11px;color:var(--dim);min-height:1em}}
.card__end.urgent{{color:var(--hot)}}

.empty{{padding:60px 0;text-align:center;color:var(--dim);font-family:var(--font-num);font-size:13px}}

footer{{border-top:1px solid var(--line);padding:24px 0 60px;color:var(--dim);font-size:12px}}
.disclosure{{
  border:1px solid var(--line);background:var(--panel);
  padding:12px 14px;margin-bottom:14px;line-height:1.6;
}}
@media(max-width:520px){{
  .grid{{grid-template-columns:repeat(2,1fr)}}
  .card__body{{padding:10px 10px 12px}}
  .price{{font-size:18px}}
}}
@media(prefers-reduced-motion:reduce){{ *{{animation:none!important;transition:none!important}} }}
</style>
</head>
<body>
<div class="wrap">

  <header>
    <div class="brand">
      <h1>특가<span>레이더</span></h1>
      <p>{SITE_TAGLINE}</p>
    </div>
    <div class="stats">
      <div class="stat">갱신 <b>{generated_at}</b></div>
      <div class="stat">전체 <b>{n_all}</b></div>
      <div class="stat">70%↑ <b>{n70}</b></div>
      <div class="stat">30일최저 <b>{n_low}</b></div>
    </div>
  </header>

  <div class="filterbar">
    <nav class="filters" id="filters" aria-label="할인율 필터">
      <button class="chip" data-f="all" aria-pressed="true">전체</button>
      <button class="chip" data-f="50" aria-pressed="false">50% 이상</button>
      <button class="chip" data-f="70" aria-pressed="false">70% 이상</button>
      <button class="chip" data-f="80" aria-pressed="false">80% 이상</button>
      <button class="chip" data-f="low" aria-pressed="false">30일 최저가</button>
      <button class="chip" data-f="today" aria-pressed="false">오늘 마감</button>
    </nav>
    <nav class="filters filters--cat" id="cats" aria-label="카테고리 필터">{cat_chips}</nav>
  </div>

  <p class="count" id="count"></p>
  <main class="grid" id="grid">{cards}</main>
  <p class="empty" id="empty" hidden>조건에 맞는 딜이 없어요.</p>

  <footer>
    <p class="disclosure">{DISCLOSURE}</p>
    <p>가격과 재고는 수시로 바뀝니다. 구매 전 토스쇼핑에서 다시 확인해주세요.</p>
  </footer>
</div>

<script>
(function(){{
  var grid=document.getElementById('grid'),
      cards=[].slice.call(grid.children),
      empty=document.getElementById('empty');

  // API 의 마감 시각은 타임존이 없는 경우가 있다. 없으면 KST 로 본다.
  function endMs(s){{
    if(!s) return NaN;
    return new Date(/[Z+]|-\\d\\d:\\d\\d$/.test(s) ? s : s+'+09:00').getTime();
  }}
  // 브라우저 시간대와 무관하게 '한국 기준 오늘'
  function kstToday(){{ return new Date(Date.now()+9*36e5).toISOString().slice(0,10); }}

  // 로드 시 계단식 등장 (초반 몇 개만 — 전부 지연시키면 느리게 느껴진다)
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
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "index.html").write_text(render(deals, generated_at), encoding="utf-8")
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")

    size = (OUT_DIR / "index.html").stat().st_size
    print(f"[+] docs/index.html 생성 · 딜 {len(deals)}개 · {size/1024:.0f}KB")


if __name__ == "__main__":
    main()
