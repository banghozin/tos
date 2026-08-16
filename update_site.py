"""원클릭 사이트 갱신 — 반드시 한국 IP(내 PC)에서 실행.

수집 → 발급 → 사이트생성 → 카드 → 깃푸시 를 한 번에 처리한다.
더블클릭용 '사이트갱신.cmd' 가 이 파일을 부른다.

왜 내 PC 에서 도는가:
    토스가 외국 IP(GitHub Actions 등) 접근을 2차인증(TWO_FACTOR_REQUIRED)으로 막는다.
    한국 IP 인 내 PC 에서는 저장된 토큰으로 정상 동작한다.
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


def step(desc, cmd, check=True):
    print(f"\n{'=' * 48}\n▶ {desc}\n{'=' * 48}")
    code = subprocess.run(cmd, cwd=str(ROOT)).returncode
    if check and code != 0:
        raise SystemExit(code)
    return code


def git(*args, check=True):
    return step(f"git {' '.join(args)}", ["git", *args], check=check)


def main():
    py = sys.executable

    # 0) 원격 최신 반영(충돌 시 내 로컬 우선)
    git("fetch", "origin", check=False)
    git("merge", "-X", "ours", "origin/main", "-m", "merge before update", check=False)

    # 1) 수집 — 0개면 collect.py 가 실패로 종료(토큰 만료/2차인증)
    try:
        step("토스에서 특가 수집", [py, "collect.py"])
    except SystemExit:
        print("\n[!] 수집 실패 — 토큰이 만료됐거나 2차인증이 필요할 수 있어요.")
        print("    '토큰새로받기.cmd' 로 토큰을 새로 넣은 뒤 다시 실행하세요.")
        raise

    # 2) 발급 → 3) 사이트 → 4) 카드
    step("쉐어링크 발급(새 상품만)", [py, "issue.py", "--limit", "80"])
    step("사이트 생성", [py, "build.py"])
    step("딜 카드 생성", [py, "cards.py"])

    # 5) 커밋 & 푸시 (바뀐 게 있을 때만)
    git("add", "-A")
    has_change = subprocess.run(
        ["git", "diff", "--staged", "--quiet"], cwd=str(ROOT)
    ).returncode != 0
    if has_change:
        stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        git("commit", "-m", f"딜 갱신 {stamp}")
        git("push", "origin", "main")
        print("\n[완료] 사이트 갱신됨 — 1~2분 뒤 https://hotdeal.help 에 반영됩니다.")
    else:
        print("\n[완료] 수집은 정상이나 바뀐 내용이 없어 커밋은 생략했습니다.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code:
            print(f"\n[중단] 문제가 생겨 멈췄습니다 (코드 {e.code}). 위 메시지를 확인하세요.")
        raise
