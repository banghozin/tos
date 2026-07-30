"""GitHub 시크릿에 넣을 값(TBIZAUTH, TGSID)을 .env 에서 읽어 보여준다.
TBIZAUTH 는 클립보드에도 복사한다. (토큰새로받기.cmd / 시크릿값보기.cmd 에서 호출)
"""
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ENV = Path(__file__).parent / ".env"


def main():
    if not ENV.exists():
        print("  [!] .env 파일이 없습니다.")
        print("      토큰새로받기.cmd 를 먼저 실행해 값을 넣어주세요.")
        return

    vals = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(("TBIZAUTH", "TGSID")) and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()

    if not vals.get("TBIZAUTH"):
        print("  [!] .env 에서 TBIZAUTH 를 찾지 못했습니다.")
        return

    print("=" * 60)
    print("  GitHub 저장소 → Settings → Secrets and variables")
    print("  → Actions → New repository secret 에 아래를 등록하세요.")
    print("=" * 60)
    print()
    for name in ("TBIZAUTH", "TGSID"):
        if vals.get(name):
            print(f"  이름(Name)  : {name}")
            print(f"  값(Secret)  : {vals[name]}")
            print()

    try:
        subprocess.run("clip", input=vals["TBIZAUTH"].encode("utf-16-le"),
                       check=True, shell=True)
        print("  [+] TBIZAUTH 를 클립보드에 복사했습니다. (값칸에 Ctrl+V)")
    except Exception:
        pass
    print()


if __name__ == "__main__":
    main()
