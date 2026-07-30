"""수집된 상품 중 특가를 걸러 보여준다.

사용법:
    python report.py                      # 할인율 50% 이상 (기본)
    python report.py --min-discount 70
    python report.py --lowest-only        # 30일 최저가만
    python report.py --drops              # 직전 수집 대비 가격이 내려간 것만
    python report.py --json               # 발행 파이프라인용 JSON 출력
"""
import argparse
import json
import sys

import db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def fetch_deals(conn, min_discount, lowest_only, include_sold_out):
    sql = """
        SELECT p.*, s.short_url
        FROM products p
        LEFT JOIN sharelinks s ON s.product_id = p.product_id
        WHERE 1=1
    """
    params = []
    if lowest_only:
        sql += " AND p.is_lowest_30d = 1"
    else:
        # 쿠폰 반영 할인율(effective_rate)을 우선 적용한다.
        sql += " AND (COALESCE(p.effective_rate, p.discount_rate) >= ? OR p.is_lowest_30d = 1)"
        params.append(min_discount)
    if not include_sold_out:
        sql += " AND p.is_sold_out = 0"
    sql += " ORDER BY COALESCE(p.effective_rate, p.discount_rate) DESC, p.effective_price ASC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def fetch_new(conn, min_discount):
    """마지막 수집에서 처음 나타난 상품. '새로 올라온 딜'."""
    last = conn.execute("SELECT MAX(observed_at) FROM observations").fetchone()[0]
    if not last:
        return []
    rows = conn.execute(
        """SELECT p.*, s.short_url
           FROM products p
           LEFT JOIN sharelinks s ON s.product_id = p.product_id
           WHERE p.first_seen_at = ?
             AND p.is_sold_out = 0
             AND (COALESCE(p.effective_rate, p.discount_rate) >= ? OR p.is_lowest_30d = 1)
           ORDER BY COALESCE(p.effective_rate, p.discount_rate) DESC""",
        (last, min_discount),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_drops(conn):
    """직전 관측 대비 판매가가 내려간 상품. 저쪽 사이트가 못 하는 부분."""
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT product_id, display_price, observed_at,
                   ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY observed_at DESC) AS rn
            FROM observations
        )
        SELECT p.*, s.short_url,
               cur.display_price AS now_price,
               prev.display_price AS prev_price
        FROM ranked cur
        JOIN ranked prev ON prev.product_id = cur.product_id AND prev.rn = 2
        JOIN products p  ON p.product_id = cur.product_id
        LEFT JOIN sharelinks s ON s.product_id = p.product_id
        WHERE cur.rn = 1
          AND cur.display_price < prev.display_price
        ORDER BY (prev.display_price - cur.display_price) * 1.0 / prev.display_price DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def won(n):
    return f"{n:,}원" if isinstance(n, int) else "-"


def clip(s, n):
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def print_table(deals, drops_mode=False):
    if not deals:
        print("조건에 맞는 상품이 없습니다.")
        return

    print(f"\n{'할인':>4}  {'실구매가':>10}  {'정가':>10}  {'최저':>4}  {'링크':>6}  상품명")
    print("-" * 100)
    for d in deals:
        lowest = "30일" if d.get("is_lowest_30d") else ""
        if d.get("short_url"):
            link = "있음"
        elif d.get("link_issuable"):
            link = "발급가능"
        else:
            link = "불가"
        r = d.get("effective_rate")
        if r is None:
            r = d.get("discount_rate")
        rate = f"{r}%" if r is not None else "-"
        price = d.get("effective_price") or d.get("display_price")
        print(f"{rate:>4}  {won(price):>10}  {won(d.get('original_price')):>10}  "
              f"{lowest:>4}  {link:>6}  {clip(d.get('display_name'), 45)}")
        notes = []
        if d.get("coupon_discount"):
            notes.append(f"쿠폰 {won(d['coupon_discount'])} 포함")
        # API 의 discountRate 가 두 가격으로 계산한 값과 다르면 표시해 둔다.
        if r is not None and d.get("discount_rate") not in (None, r):
            notes.append(f"API 표기 {d['discount_rate']}%")
        if notes:
            print(f"{'':>4}  ↳ {' · '.join(notes)}")
        if drops_mode:
            print(f"{'':>4}  ↓ 직전 {won(d.get('prev_price'))} → {won(d.get('now_price'))}")

    issued = sum(1 for d in deals if d.get("short_url"))
    issuable = sum(1 for d in deals if not d.get("short_url") and d.get("link_issuable"))
    print("-" * 100)
    print(f"총 {len(deals)}개 · 링크 보유 {issued}개 · 발급 필요 {issuable}개")
    if issuable:
        print("\n링크 미보유 상품 (쉐어링크에서 발급 후 links.py 로 등록):")
        for d in deals:
            if not d.get("short_url") and d.get("link_issuable"):
                print(f"  {d['product_id']}  {clip(d.get('display_name'), 55)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-discount", type=int, default=50)
    ap.add_argument("--lowest-only", action="store_true")
    ap.add_argument("--include-sold-out", action="store_true")
    ap.add_argument("--drops", action="store_true")
    ap.add_argument("--new", action="store_true", help="마지막 수집에서 새로 등장한 딜만")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    conn = db.connect()
    if args.drops:
        deals = fetch_drops(conn)
    elif args.new:
        deals = fetch_new(conn, args.min_discount)
    else:
        deals = fetch_deals(conn, args.min_discount, args.lowest_only, args.include_sold_out)
    conn.close()

    if args.json:
        print(json.dumps(deals, ensure_ascii=False, indent=2))
    else:
        print_table(deals, drops_mode=args.drops)


if __name__ == "__main__":
    main()
