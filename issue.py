"""수집된 특가 상품의 쉐어링크를 자동 발급하고 캐시에 저장한다.

쉐어링크는 상품당 영구 고정이라, 한 번 발급하면 계속 재사용한다.
이미 캐시에 있는 상품은 건너뛴다.

사용법:
    python issue.py                    # 할인 50%+ 또는 30일 최저가 중 링크 없는 것 전부
    python issue.py --min-discount 70
    python issue.py --limit 20
    python issue.py --dry-run          # 발급 없이 대상만 확인
"""
import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

import collect
import db

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

ISSUE_URL = "https://sharelink.toss.im/api-public/v3/shopping/sharelink/link/issue"
KST = timezone(timedelta(hours=9))
DELAY = 1.0


def issue_link(taca_item_id, env):
    """POST /link/issue → (shortUrl, originUrl). 실패하면 (None, 사유)."""
    body = json.dumps({"tacaItemId": taca_item_id}).encode()
    req = urllib.request.Request(ISSUE_URL, data=body, method="POST", headers={
        "accept": "*/*",
        "content-type": "application/json",
        "accept-encoding": "gzip",
        "cookie": f"TBIZAUTH={env['TBIZAUTH']}"
                  + (f"; TGSID={env['TGSID']}" if env.get("TGSID") else ""),
        "referer": "https://sharelink.toss.im/links/best-ranking",
        "user-agent": env.get("USER_AGENT", "Mozilla/5.0"),
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        payload = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            sys.exit("[!] 401 Unauthorized — TBIZAUTH 가 만료됐습니다. "
                     "python settoken.py 로 갱신하세요.")
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, str(e)

    if payload.get("resultType") != "SUCCESS":
        return None, (payload.get("error") or {}).get("reason") or "알 수 없는 오류"
    s = payload.get("success") or {}
    return s.get("shortUrl"), s.get("originUrl")


def targets(conn, min_discount, limit):
    sql = """
        SELECT p.product_id, p.taca_item_id, p.display_name,
               p.effective_rate, p.effective_price
        FROM products p
        LEFT JOIN sharelinks s ON s.product_id = p.product_id
        WHERE s.product_id IS NULL
          AND p.link_issuable = 1
          AND p.taca_item_id IS NOT NULL
          AND p.is_sold_out = 0
          AND (COALESCE(p.effective_rate, p.discount_rate) >= ? OR p.is_lowest_30d = 1
               OR p.product_id IN (SELECT product_id FROM section_items
                                    WHERE section_code IN ('TODAY_DEAL', 'BEST_SELLING')))
        ORDER BY COALESCE(p.effective_rate, p.discount_rate) DESC
    """
    params = [min_discount]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-discount", type=int, default=50)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env = collect.load_env()
    conn = db.connect()
    rows = targets(conn, args.min_discount, args.limit)

    if not rows:
        print("발급할 대상이 없습니다. (전부 발급됨이거나 수집이 먼저 필요)")
        return

    print(f"대상 {len(rows)}개" + (" — dry-run, 발급하지 않음" if args.dry_run else ""))
    ok = fail = 0
    for i, r in enumerate(rows):
        name = (r["display_name"] or "")[:42]
        if args.dry_run:
            print(f"  {r['effective_rate']:>3}%  {name}")
            continue
        if i:
            time.sleep(DELAY)
        short, origin = issue_link(r["taca_item_id"], env)
        if not short:
            fail += 1
            print(f"  [-] {name} — {origin}")
            continue
        db.put_sharelink(conn, r["product_id"], short,
                         datetime.now(KST).isoformat(), origin)
        conn.commit()
        ok += 1
        print(f"  [+] {r['effective_rate']:>3}%  {short}  {name}")

    conn.close()
    if not args.dry_run:
        print(f"\n발급 완료 {ok}개" + (f" · 실패 {fail}개" if fail else ""))


if __name__ == "__main__":
    main()
