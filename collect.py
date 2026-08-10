"""토스쇼핑 쉐어링크 큐레이션 API에서 특가 상품을 수집해 SQLite에 적재한다.

사용법:
    python collect.py                 # 기본 surface 전부 수집
    python collect.py BEST_RANKING    # 특정 surface만
"""
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import db

for _stream in (sys.stdout, sys.stderr):  # 윈도우 cp949 콘솔에서 한글 깨짐 방지
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

BASE = "https://sharelink.toss.im/api-public/v3/shopping/sharelink/curation-sections"
ROOT = Path(__file__).parent
SNAPSHOT_DIR = ROOT / "snapshots"
KST = timezone(timedelta(hours=9))

# 실측으로 확인된 유효값은 이 둘뿐. 나머지는 전부 400.
# HOME 은 BEST_RANKING 의 부분집합(TODAY_DEAL, BEST_SELLING)이라 기본값에서 뺐다.
DEFAULT_SURFACES = ["BEST_RANKING"]

# 목록 엔드포인트에서 size 는 무시된다(섹션별 개수 고정).
# 실제 전량 수집은 섹션별 items 엔드포인트로 한다.
PAGE_SIZE = 100
SECTION_PAGE_SIZE = 30       # items 엔드포인트의 상한. 30 초과를 넣어도 30개만 온다.
MAX_PAGES_PER_SECTION = 20   # 폭주 방지 (최대 600개/섹션)
REQUEST_DELAY = 1.0          # 초. 서버에 부담 주지 않도록.


def load_env(path=ROOT / ".env"):
    if not path.exists():
        sys.exit(f"[!] {path} 가 없습니다. .env.example 을 복사해 값을 채워주세요.")
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    if not env.get("TBIZAUTH"):
        sys.exit("[!] .env 에 TBIZAUTH 값이 비어 있습니다.")
    return env


def fetch(surface, env, size=PAGE_SIZE):
    return request_json(f"{BASE}?surface={surface}&size={size}", env)


def request_json(url, env):
    cookie = f"TBIZAUTH={env['TBIZAUTH']}"
    if env.get("TGSID"):
        cookie += f"; TGSID={env['TGSID']}"
    req = urllib.request.Request(
        url,
        headers={
            "accept": "*/*",
            "accept-language": "ko-KR,ko;q=0.9",
            "accept-encoding": "gzip",
            "cookie": cookie,
            "referer": "https://sharelink.toss.im/links/best-ranking",
            "user-agent": env.get("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def effective(display_price, original_price, coupon):
    """실구매가와 두 가격으로 직접 계산한 할인율.

    couponDiscountAmount 는 이미 displayPrice 에 반영돼 있다(빼면 안 된다).
    쿠폰 있는 상품 13건 중 11건에서 discountRate 가
    (originalPrice - displayPrice) / originalPrice 와 정확히 일치함을 확인했다.
    나머지 2건은 API 의 discountRate 가 더 높게 나오는데, 표시하는 두 가격과
    앞뒤가 맞도록 여기서는 가격 기준으로 계산한 값을 쓴다.
    """
    if display_price is None:
        return None, None
    if not original_price:
        return display_price, None
    # 토스의 discountRate 는 내림이다. 반올림하면 1% 어긋난다.
    return display_price, (original_price - display_price) * 100 // original_price


def parse_items(payload, surface):
    """API 응답을 평평한 dict 리스트로 변환. 필드가 없어도 죽지 않게 방어적으로."""
    rows = []
    sections = (payload.get("success") or {}).get("sections") or []
    for section in sections:
        section_code = section.get("sectionCode")
        for item in section.get("items") or []:
            taca = item.get("taca") or {}
            pv = taca.get("productView") or {}
            ctx = taca.get("displayContext") or {}
            tag = taca.get("tagMeta") or {}
            avail = item.get("linkIssueAvailability") or {}
            today = item.get("todayDeal") or {}
            cats = (taca.get("extraAttributes") or {}).get("categories") or []

            # TODAY_DEAL 외의 섹션은 item.productId 가 null 이고
            # 실제 값은 taca.productView.productId 에만 들어있다.
            product_id = pv.get("productId") or item.get("productId")
            if not product_id:
                continue

            eff_price, eff_rate = effective(
                pv.get("displayPrice"), pv.get("originalPrice"),
                pv.get("couponDiscountAmount"),
            )

            rows.append({
                "product_id": product_id,
                "taca_id": pv.get("tacaId"),
                "taca_item_id": pv.get("tacaItemId"),
                "stock_id": pv.get("stockId"),
                "display_name": pv.get("displayName"),
                "merchant_id": pv.get("merchantId"),
                "thumbnail_url": pv.get("thumbnailUrl"),
                "original_price": pv.get("originalPrice"),
                "display_price": pv.get("displayPrice"),
                "discount_rate": pv.get("discountRate"),
                "coupon_discount": pv.get("couponDiscountAmount"),
                "effective_price": eff_price,
                "effective_rate": eff_rate,
                "is_lowest_30d": int(bool(ctx.get("isLowestPriceIn30Days"))),
                "link_issuable": int(bool(avail.get("available"))),
                "link_issue_reason": avail.get("reason"),
                "is_sold_out": int(bool(pv.get("isSoldOut"))),
                "status": pv.get("status"),
                "review_score": pv.get("reviewScore"),
                "review_count": pv.get("reviewCount"),
                "page_view_count": ctx.get("pageViewCount"),
                "campaign_end_at": tag.get("campaignEndAt"),
                "today_deal_end_at": today.get("endAt"),
                "category_ids": ",".join(str(c.get("id")) for c in cats),
                "category_l1": next((c.get("id") for c in cats if c.get("level") == 1), None),
                "surface": surface,
                "section_code": section_code,
                "rank": item.get("rank"),
            })

    meta = []
    for s in sections:
        paging = s.get("paging") or {}
        meta.append({
            "code": s.get("sectionCode"),
            "name": s.get("displayName"),
            "count": len(s.get("items") or []),
            "total": paging.get("totalCount"),
            "next_cursor": paging.get("nextCursor"),
        })
    return rows, meta


def parse_section_items(section, surface):
    """items 엔드포인트 응답(섹션 하나)을 행 리스트로 변환한다."""
    payload = {"success": {"sections": [section]}}
    rows, _ = parse_items(payload, surface)
    return rows


def fetch_section(section_code, surface, env, tab_code=None):
    """한 섹션을 nextCursor 로 끝까지 순회한다. (rows, 총개수) 반환.

    GET curation-sections/{sectionCode}/items?size=30&nextCursor=N
    size 는 30 이 상한이고, 마지막 페이지에서 nextCursor 가 null 이 된다.
    """
    rows, seen, cursor, total, pages = [], set(), None, None, 0
    while True:
        url = f"{BASE}/{section_code}/items?size={SECTION_PAGE_SIZE}"
        if tab_code:
            url += f"&tabCode={tab_code}"
        if cursor is not None:
            # 커서에 '30|31' 처럼 파이프가 들어온다. 인코딩하지 않으면 400.
            url += f"&nextCursor={urllib.parse.quote(str(cursor), safe='')}"
        try:
            payload = request_json(url, env)
        except Exception as e:
            print(f"    [-] {section_code}: {e}")
            break
        section = (payload.get("success") or {})
        if not section.get("items"):
            break
        paging = section.get("paging") or {}
        total = paging.get("totalCount", total)
        for row in parse_section_items(section, surface):
            if row["product_id"] in seen:
                continue
            seen.add(row["product_id"])
            rows.append(row)
        pages += 1
        cursor = paging.get("nextCursor")
        if not cursor or pages >= MAX_PAGES_PER_SECTION:
            break
        time.sleep(REQUEST_DELAY)
    return rows, total


def main():
    env = load_env()
    surfaces = sys.argv[1:] or DEFAULT_SURFACES
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    now = datetime.now(KST)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    observed_at = now.isoformat()

    conn = db.connect()

    # 분기별 보관. 이번 분기 시작(1/1·4/1·7/1·10/1) 이전의 관측 이력은 지운다.
    # 다음 분기로 넘어가면 지난 분기 데이터가 비워져 가격 그래프가 초기화된다.
    q_start_month = ((now.month - 1) // 3) * 3 + 1
    quarter_start = now.replace(
        month=q_start_month, day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    pruned = db.prune_observations_before(conn, quarter_start)
    if pruned:
        print(f"[+] 지난 분기 관측 {pruned}개 정리 · 이번 분기({quarter_start[:10]}~) 데이터만 유지")

    total = 0

    for i, surface in enumerate(surfaces):
        if i:
            time.sleep(REQUEST_DELAY)
        try:
            payload = fetch(surface, env)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                sys.exit("[!] 401 Unauthorized — TBIZAUTH 가 만료됐습니다. "
                         "브라우저에서 다시 로그인해 쿠키를 갱신하세요.")
            print(f"[-] {surface}: HTTP {e.code} — 건너뜁니다")
            continue
        except Exception as e:
            print(f"[-] {surface}: {e} — 건너뜁니다")
            continue

        if payload.get("resultType") != "SUCCESS":
            print(f"[-] {surface}: resultType={payload.get('resultType')} — 건너뜁니다")
            continue

        (SNAPSHOT_DIR / f"{stamp}_{surface}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        _, meta = parse_items(payload, surface)
        print(f"[+] {surface}: 섹션 {len(meta)}개 발견")

        # CATEGORY_BEST 섹션의 탭이 대분류 이름표다. 사이트 카테고리 필터에 쓴다.
        for s in (payload.get("success") or {}).get("sections") or []:
            if s.get("tabs"):
                db.put_categories(conn, s["tabs"])
        conn.commit()

        # 섹션마다 items 엔드포인트로 전량 순회한다.
        # 같은 상품이 여러 섹션에 서로 다른 가격으로 등장하므로,
        # 상품당 한 번만, 가장 싼 가격으로 적재한다.
        # (그러지 않으면 같은 시각의 관측이 중복돼 --drops 가 거짓 하락을 잡는다.)
        best = {}
        for m in meta:
            time.sleep(REQUEST_DELAY)
            rows, sec_total = fetch_section(m["code"], surface, env)
            for row in rows:
                cur = best.get(row["product_id"])
                if cur is None or (row["display_price"] or 0) < (cur["display_price"] or 0):
                    best[row["product_id"]] = row
            got = f"{len(rows)}/{sec_total}" if sec_total else str(len(rows))
            print(f"    {m['code']:<16} {got:>8}  {m['name'] or ''}")

        for row in best.values():
            db.upsert_product(conn, row, observed_at)
        conn.commit()
        total += len(best)

    conn.close()

    # 0개면 조용히 넘어가지 않는다. 예전엔 그대로 진행돼서 build 가 옛 데이터에
    # 새 시각만 찍어 커밋 → "갱신됐는데 상품은 그대로"인 착시가 생겼다.
    # 여기서 실패로 끝내야 이후 단계(발급/build/커밋)가 안 돌아 사이트는 마지막
    # 정상본을 유지하고, GitHub 이 실패 알림 메일을 보낸다.
    if total == 0:
        sys.exit("[!] 수집된 상품이 0개입니다 — TBIZAUTH 토큰 만료(응답 resultType=FAIL) 가능성이 큽니다.\n"
                 "    브라우저에서 쿠키를 다시 복사해 GitHub Secret 'TBIZAUTH' 를 갱신하세요. (배포 중단)")

    print(f"\n총 {total}개 적재 완료 · 스냅샷: snapshots/{stamp}_*.json")
    print("→ python report.py 로 특가를 확인하세요.")


if __name__ == "__main__":
    main()
