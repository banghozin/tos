"""딸깍 카드 발행 — 현재 딜 상위 5개로 카드+멘트를 만들어 사이트에 올린다.

전체 수집 없이 빠르게 돈다(현재 deals.db 기준). 그래서 하루에 여러 번 카드만
새로 올리고 싶을 때 쓴다. 최신 딜로 새로 뽑고 싶으면 먼저 '사이트갱신.cmd' 를 돌린다.

'카드만들기.cmd' 가 이 파일을 부른다. 반드시 한국 IP(내 PC)에서 실행.
"""
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
KST = timezone(timedelta(hours=9))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")


def sh(cmd, check=True):
    print("\n▶", " ".join(cmd))
    code = subprocess.run(cmd, cwd=str(ROOT)).returncode
    if check and code != 0:
        raise SystemExit(code)
    return code


def main():
    py = sys.executable
    # 원격 최신 반영(충돌 시 로컬 우선)
    sh(["git", "fetch", "origin"], check=False)
    sh(["git", "merge", "-X", "ours", "origin/main", "-m", "merge before cards"], check=False)

    # 카드 5장 + 멘트 생성
    sh([py, "cards.py"])

    # docs/cards/ 만 커밋·푸시 → Vercel 이 hotdeal.help/cards/ 배포
    sh(["git", "add", "docs/cards"])
    changed = subprocess.run(
        ["git", "diff", "--staged", "--quiet"], cwd=str(ROOT)
    ).returncode != 0
    if changed:
        stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        sh(["git", "commit", "-m", f"카드 갱신 {stamp}"])
        sh(["git", "push", "origin", "main"])
        print("\n[완료] 카드 5장 발행됨 → https://hotdeal.help/cards/ (1~2분 뒤 반영)")
        print("       폰에서 그 주소 열고 [공유] 버튼으로 스레드에 올리세요.")
    else:
        print("\n[완료] 바뀐 카드가 없어 그대로입니다. (이미 최신)")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code:
            print(f"\n[중단] 문제가 생겨 멈췄습니다 (코드 {e.code}). 위 메시지를 확인하세요.")
        raise
