"""브라우저에서 복사한 값에서 토큰만 뽑아 .env 에 넣는다.

토큰이 만료되면(collect.py 가 401 을 알려준다) 이렇게 갱신한다:

    1. 크롬에서 sharelink.toss.im 접속 (로그인 상태)
    2. F12 → Network → 아무 요청 우클릭 → Copy → Copy as cURL
    3. python settoken.py   실행 후 붙여넣고 Ctrl+Z 엔터 (윈도우)

cURL 전체를 붙여도 되고, 쿠키 문자열만 붙여도 되고,
TBIZAUTH 값만 붙여도 알아서 인식한다.
"""
import re
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


def main():
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        print("cURL 또는 쿠키 문자열을 붙여넣고 Ctrl+Z 엔터 (윈도우) / Ctrl+D (그 외):")
        text = sys.stdin.read()

    found = extract(text)
    if not found.get("TBIZAUTH"):
        sys.exit("[!] TBIZAUTH 를 찾지 못했습니다. 붙여넣은 내용을 확인해주세요.")

    merge_env(found)
    masked = found["TBIZAUTH"][:6] + "…" + found["TBIZAUTH"][-4:]
    print(f"[+] TBIZAUTH 갱신됨 ({masked})")
    if "TGSID" in found:
        print("[+] TGSID 갱신됨")
    print("→ python collect.py 로 확인하세요.")


if __name__ == "__main__":
    main()
