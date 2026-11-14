"""Phase 0: API 4종을 1건씩 호출해 응답을 data/samples/ 에 저장하고 필드명을 출력한다.

실행: .\\.venv\\Scripts\\python.exe scripts\\fetch_samples.py
- 키는 .env 에서 읽으며, 화면이나 파일에 키 값을 출력하지 않는다.
- corpCode.xml 원본(zip)은 data/raw/ 에 캐시하고, 샘플에는 일부만 저장한다.
"""
import io
import json
import os
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
SAMPLES = ROOT / "data" / "samples"
RAW.mkdir(parents=True, exist_ok=True)
SAMPLES.mkdir(parents=True, exist_ok=True)

load_dotenv(ROOT / ".env")
DART_KEY = os.getenv("DART_API_KEY", "").strip()
DATA_GO_KEY = os.getenv("DATA_GO_KR_API_KEY", "").strip()

SAMPLE_STOCK_CODE = "005930"  # 삼성전자 (샘플용)
SAMPLE_BSNS_YEAR = "2025"      # 최신 사업보고서 연도


def get(url, params):
    """요청 실패 시 URL(키 포함)이 출력되지 않도록 메시지를 정리한다."""
    try:
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        resp = getattr(e, "response", None)
        status = getattr(resp, "status_code", None)
        body = resp.text[:300] if resp is not None else ""
        sys.exit(f"[오류] {url} 호출 실패 (HTTP {status}, {type(e).__name__})\n  응답: {body}")
    finally:
        time.sleep(0.2)


def save_json(name, data):
    path = SAMPLES / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {path.relative_to(ROOT)}")


def corp_code():
    print("\n[1] OpenDART corpCode.xml")
    zpath = RAW / "corpCode.zip"
    if zpath.exists():
        print("  캐시 사용: data/raw/corpCode.zip")
        content = zpath.read_bytes()
    else:
        r = get("https://opendart.fss.or.kr/api/corpCode.xml", {"crtfc_key": DART_KEY})
        content = r.content
        if not content.startswith(b"PK"):
            sys.exit(f"[오류] zip이 아닌 응답: {content[:300].decode('utf-8', 'replace')}")
        zpath.write_bytes(content)
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names = z.namelist()
        xml_bytes = z.read(names[0])
    print(f"  zip 내부 파일: {names}")
    root = ET.fromstring(xml_bytes)
    items = list(root)
    print(f"  루트 태그: <{root.tag}>, 항목 수: {len(items)}")
    print(f"  항목 태그: <{items[0].tag}>, 필드: {[c.tag for c in items[0]]}")

    rows = [{c.tag: (c.text or "").strip() for c in it} for it in items]
    listed = [r for r in rows if r.get("stock_code")]
    target = next((r for r in rows if r.get("stock_code") == SAMPLE_STOCK_CODE), None)
    print(f"  stock_code 있는 회사 수: {len(listed)}")
    save_json("corpCode_sample.json", {
        "root_tag": root.tag,
        "item_tag": items[0].tag,
        "total": len(rows),
        "listed_count": len(listed),
        "first_3": rows[:3],
        "listed_first_3": listed[:3],
        "sample_target": target,
    })
    if not target:
        sys.exit(f"[오류] stock_code {SAMPLE_STOCK_CODE} 를 찾지 못함")
    return target


def company(corp):
    print("\n[2] OpenDART company.json")
    r = get("https://opendart.fss.or.kr/api/company.json",
            {"crtfc_key": DART_KEY, "corp_code": corp})
    data = r.json()
    print(f"  status={data.get('status')} message={data.get('message')}")
    print(f"  필드: {list(data.keys())}")
    save_json("company_sample.json", data)


def financials(corp):
    print("\n[3] OpenDART fnlttSinglAcntAll.json")
    r = get("https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json", {
        "crtfc_key": DART_KEY, "corp_code": corp, "bsns_year": SAMPLE_BSNS_YEAR,
        "reprt_code": "11011", "fs_div": "CFS",
    })
    data = r.json()
    print(f"  status={data.get('status')} message={data.get('message')}")
    print(f"  최상위 필드: {list(data.keys())}")
    lst = data.get("list") or []
    if lst:
        print(f"  list 항목 수: {len(lst)}, 항목 필드: {list(lst[0].keys())}")
        print(f"  sj_div 종류: {sorted({x.get('sj_div') for x in lst})}")
    save_json("fnlttSinglAcntAll_sample.json", data)


def stock_price():
    print("\n[4] 공공데이터포털 getStockPriceInfo")
    key = unquote(DATA_GO_KEY) if "%" in DATA_GO_KEY else DATA_GO_KEY
    # 2026-10 개편된 V2 주소 (옛 주소 /service/GetStockSecuritiesInfoService 는 키가 등록되지 않음)
    r = get("https://apis.data.go.kr/1160100/GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2", {
        "serviceKey": key, "resultType": "json", "numOfRows": 3, "pageNo": 1,
        "likeSrtnCd": SAMPLE_STOCK_CODE,
    })
    try:
        data = r.json()
    except ValueError:
        sys.exit(f"[오류] JSON이 아닌 응답: {r.text[:300]}")
    save_json("getStockPriceInfo_sample.json", data)
    body = data.get("response", {}).get("body", {})
    header = data.get("response", {}).get("header", {})
    print(f"  header: {header}")
    print(f"  body 필드: {list(body.keys())}")
    item = (body.get("items") or {}).get("item") or []
    if isinstance(item, dict):
        item = [item]
    if item:
        print(f"  item 필드: {list(item[0].keys())}")


def main():
    missing = [n for n, v in [("DART_API_KEY", DART_KEY), ("DATA_GO_KR_API_KEY", DATA_GO_KEY)] if not v]
    if missing:
        sys.exit(f"[오류] .env 에 값이 없음: {', '.join(missing)}")
    target = corp_code()
    company(target["corp_code"])
    financials(target["corp_code"])
    stock_price()
    print("\n완료. data/samples/ 를 확인하세요.")


if __name__ == "__main__":
    main()
