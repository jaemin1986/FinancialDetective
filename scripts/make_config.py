"""docs/config.js 생성 — 브라우저용 Supabase 주소 + 공개(publishable/anon) 키만 넣는다.

  .venv\\Scripts\\python.exe scripts\\make_config.py

비밀(secret/service_role) 키가 실수로 들어가지 않도록 키 형식을 검사한다.
"""
import base64
import json
import os
import sys

from common import ROOT


def is_public_key(k):
    if k.startswith("sb_publishable_"):
        return True
    if k.startswith("eyJ"):  # 옛 JWT 형식: role이 anon이어야 함
        try:
            payload = k.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            return json.loads(base64.urlsafe_b64decode(payload)).get("role") == "anon"
        except Exception:
            return False
    return False


def main():
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not url.startswith("https://") or not key:
        sys.exit("오류: .env에 SUPABASE_URL / SUPABASE_ANON_KEY가 필요합니다.")
    if not is_public_key(key) or key == os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip():
        sys.exit("오류: SUPABASE_ANON_KEY가 공개용 키가 아닙니다. (sb_publishable_... 이어야 함) 중단합니다.")
    out = ROOT / "docs" / "config.js"
    out.write_text(
        "// 브라우저용 Supabase 설정 — 공개(publishable) 키만. 비밀 키는 절대 넣지 않는다.\n"
        "// 모든 테이블은 RLS로 막혀 있고, 이 키로는 정해진 RPC 함수만 실행할 수 있다.\n"
        f"window.FD_CONFIG = {json.dumps({'SUPABASE_URL': url, 'SUPABASE_ANON_KEY': key})};\n",
        encoding="utf-8")
    print(f"저장: {out.relative_to(ROOT)} (공개 키 확인됨)")


if __name__ == "__main__":
    main()
