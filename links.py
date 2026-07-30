"""쉐어링크 캐시 관리.

쉐어링크는 상품당 영구 고정이므로, 한 번 발급한 링크는 계속 재사용한다.
발급 API를 아직 못 찾았으므로 지금은 수동으로 등록한다.

사용법:
    python links.py add 724138873 https://toss.im/_m/TEReaiHz
    python links.py import links.txt      # 한 줄에 "상품ID 링크"
    python links.py list
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

KST = timezone(timedelta(hours=9))


def now():
    return datetime.now(KST).isoformat()


def cmd_add(conn, product_id, url):
    if not url.startswith("https://toss.im/_m/"):
        print(f"[!] 쉐어링크 형식이 아닙니다: {url}")
        print("    일반 공유 링크로는 수익이 발생하지 않습니다. 확인해주세요.")
        return
    db.put_sharelink(conn, int(product_id), url, now())
    conn.commit()
    print(f"[+] {product_id} → {url}")


def cmd_import(conn, path):
    added = 0
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            print(f"[!] {lineno}행 형식 오류: {line}")
            continue
        pid, url = parts
        if not url.startswith("https://toss.im/_m/"):
            print(f"[!] {lineno}행 쉐어링크 아님: {url}")
            continue
        db.put_sharelink(conn, int(pid), url, now())
        added += 1
    conn.commit()
    print(f"[+] {added}개 등록 완료")


def cmd_list(conn):
    rows = conn.execute(
        """SELECT s.product_id, s.short_url, p.display_name, p.discount_rate
           FROM sharelinks s LEFT JOIN products p ON p.product_id = s.product_id
           ORDER BY s.issued_at DESC"""
    ).fetchall()
    if not rows:
        print("등록된 링크가 없습니다.")
        return
    for r in rows:
        name = (r["display_name"] or "")[:40]
        rate = f"{r['discount_rate']}%" if r["discount_rate"] is not None else "  -"
        print(f"{r['product_id']:>12}  {rate:>4}  {r['short_url']:<32}  {name}")
    print(f"\n총 {len(rows)}개")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    conn = db.connect()
    cmd = sys.argv[1]
    if cmd == "add" and len(sys.argv) == 4:
        cmd_add(conn, sys.argv[2], sys.argv[3])
    elif cmd == "import" and len(sys.argv) == 3:
        cmd_import(conn, sys.argv[2])
    elif cmd == "list":
        cmd_list(conn)
    else:
        print(__doc__)
    conn.close()


if __name__ == "__main__":
    main()
