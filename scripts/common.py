"""스크립트 공통 모듈: 경로, .env 로드, OpenDART 호출(대기·캐시·오류 처리)."""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DATA = ROOT / "data"

load_dotenv(ROOT / ".env")

KST = timezone(timedelta(hours=9))  # 한국은 서머타임이 없어 고정 +9로 충분
DART_BASE = "https://opendart.fss.or.kr/api"
SLEEP = 0.2

# OpenDART 공식 문서의 상태 코드 중, 계속 진행하면 안 되는 것들
DART_FATAL = {
    "010": "등록되지 않은 키",
    "011": "사용할 수 없는 키",
    "012": "접근할 수 없는 IP",
    "020": "요청 제한 초과(일일 한도)",
    "021": "조회 가능한 회사 개수 초과",
    "100": "필드의 부적절한 값",
    "101": "부적절한 접근",
    "800": "시스템 점검 중",
    "901": "개인정보 보유기간 만료 키",
}


def now_kst():
    return datetime.now(KST)


DAY_START_HOUR = 3  # 오늘의 문제 하루 경계: 새벽 3시 KST (Supabase private.kst_today와 같아야 함)


def quiz_today():
    """오늘의 문제 날짜 (03:00~다음날 02:59가 하루)."""
    return (now_kst() - timedelta(hours=DAY_START_HOUR)).date()


def dart_key():
    key = os.getenv("DART_API_KEY", "").strip()
    if not key:
        sys.exit("[오류] .env 에 DART_API_KEY 가 없습니다.")
    return key


def dart_get(endpoint, params, retries=3):
    """OpenDART 호출. 실패 메시지에 키가 포함된 URL이 나오지 않게 정리한다."""
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(f"{DART_BASE}/{endpoint}",
                             params={"crtfc_key": dart_key(), **params}, timeout=60)
            time.sleep(SLEEP)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            time.sleep(SLEEP)
            resp = getattr(e, "response", None)
            last = f"HTTP {getattr(resp, 'status_code', None)}, {type(e).__name__}"
            time.sleep(2 * (attempt + 1))
    sys.exit(f"[오류] {endpoint} 호출 실패 ({last})")


def dart_json(endpoint, params):
    data = dart_get(endpoint, params).json()
    status = data.get("status")
    if status in DART_FATAL:
        sys.exit(f"[중단] OpenDART status={status} ({DART_FATAL[status]}): {data.get('message')}")
    return data


DATA_GO_BASE = "https://apis.data.go.kr/1160100/GetStockSecuritiesInfoService_V2"


def data_go_key():
    from urllib.parse import unquote
    key = os.getenv("DATA_GO_KR_API_KEY", "").strip()
    if not key:
        sys.exit("[오류] .env 에 DATA_GO_KR_API_KEY 가 없습니다.")
    return unquote(key) if "%" in key else key  # Encoding 키가 들어와도 처리


def data_go_get(operation, params, retries=3):
    """공공데이터포털 주식시세 API 호출 → response.body 반환. 키가 오류 메시지에 나오지 않게 한다."""
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(f"{DATA_GO_BASE}/{operation}",
                             params={"serviceKey": data_go_key(), "resultType": "json", **params}, timeout=60)
            time.sleep(SLEEP)
            if r.status_code != 200:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
            else:
                resp = r.json().get("response", {})
                code = resp.get("header", {}).get("resultCode")
                if code == "00":
                    return resp.get("body", {})
                last = f"resultCode={code} {resp.get('header', {}).get('resultMsg')}"
        except (requests.RequestException, ValueError) as e:
            last = type(e).__name__
        time.sleep(2 * (attempt + 1))
    sys.exit(f"[오류] {operation} 호출 실패 ({last})")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data, indent=None, compact=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    seps = (",", ":") if compact else None
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent, separators=seps), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- Supabase
def supabase_rpc(fn, params=None, role="service"):
    """Supabase RPC 함수 호출. role="service"면 SUPABASE_SERVICE_ROLE_KEY(비밀),
    "anon"이면 SUPABASE_ANON_KEY(공개)를 쓴다. 응답(JSON)을 그대로 돌려준다."""
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY" if role == "service" else "SUPABASE_ANON_KEY", "").strip()
    if not url or not key:
        sys.exit("오류: .env에 SUPABASE_URL / 키가 없습니다.")
    r = requests.post(f"{url}/rest/v1/rpc/{fn}", json=params or {},
                      headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Supabase {fn} 실패 (HTTP {r.status_code}): {r.text[:300]}")
    return r.json()


def supabase_rest(method, path, role="service", **kw):
    """테이블 직접 접근(REST). 관리·업로드 스크립트에서 service 키로만 쓴다."""
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY" if role == "service" else "SUPABASE_ANON_KEY", "").strip()
    headers = {"apikey": key, "Authorization": f"Bearer {key}", **kw.pop("headers", {})}
    return requests.request(method, f"{url}/rest/v1/{path}", headers=headers, timeout=30, **kw)
