"""브라우저에서 복사한 값에서 토큰만 뽑아 .env 에 넣는다.

토큰이 만료되면(collect.py 가 401 을 알려준다) 이렇게 갱신한다:

    1. 웨일/크롬에서 sharelink.toss.im 접속 (로그인 상태)
    2. F12 → Application 탭 → 왼쪽 Cookies → https://sharelink.toss.im
    3. TBIZAUTH 행의 Value 를 더블클릭 → Ctrl+C
    4. python settoken.py   실행 후 붙여넣고 엔터

값만 붙여도 되고, cURL 전체나 쿠키 문자열을 붙여도 알아서 인식한다.
성공하면 GitHub 에 넣을 값을 클립보드에 자동 복사해준다.
"""
import re
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
ENV = ROOT / ".env"


def extract(text):
    found = {}
    for key in ("TBIZAUTH", "TGSID"):
        m = re.search(rf"{key}\s*=\s*([A-Za-z0-9\-_=]+)", text)
        if m:
            found[key] = m.group(1)
    # 값만 붙여넣은 경우 (base64 로 인코딩된 UUID 형태)
    if not found:
        s = text.strip().strip('"').strip("'")
        if re.fullmatch(r"[A-Za-z0-9\-_=]{20,}", s):
            found["TBIZAUTH"] = s
    return found


def merge_env(found):
    lines = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                lines[k.strip()] = v.strip()
    lines.update(found)
    ENV.write_text(
        "\n".join(f"{k}={v}" for k, v in lines.items()) + "\n", encoding="utf-8"
    )
    return lines


def copy_clipboard(text):
    try:
        subprocess.run("clip", input=text.encode("utf-16-le"), check=True, shell=True)
        return True
    except Exception:
        return False


def main():
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        print("TBIZAUTH 값(또는 cURL / 쿠키 문자열)을 붙여넣고 엔터:")
        text = sys.stdin.readline()
        if "=" not in text and len(text.strip()) < 20:
            # 값이 한 줄에 안 들어온 경우 나머지도 읽는다
            text += sys.stdin.read()

    found = extract(text)
    if not found.get("TBIZAUTH"):
        sys.exit("[!] TBIZAUTH 를 찾지 못했습니다. 붙여넣은 내용을 확인해주세요.")

    merge_env(found)
    tok = found["TBIZAUTH"]
    print(f"[+] .env 갱신됨 ({tok[:6]}…{tok[-4:]})")
    if "TGSID" in found:
        print("[+] TGSID 도 갱신됨")
    if copy_clipboard(tok):
        print("[+] GitHub 시크릿용 값을 클립보드에 복사했습니다 → Ctrl+V")
    print("\n── GitHub 시크릿(TBIZAUTH)에 넣을 값 ──")
    print(tok)
    print("─────────────────────────────────────")
    print("로컬 확인: python collect.py")


if __name__ == "__main__":
    main()
