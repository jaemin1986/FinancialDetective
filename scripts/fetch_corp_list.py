"""상장사 목록 + 기업개황(시장구분·업종) 수집 → 제외 필터 적용 → data/corp_list.json

실행: .\\.venv\\Scripts\\python.exe scripts\\fetch_corp_list.py [--refresh-corpcode]
- corpCode.zip 과 기업개황 응답은 data/raw/ 에 캐시하고, 이미 받은 회사는 다시 호출하지 않는다.
- 중간에 멈춰도 다시 실행하면 이어서 진행한다.
"""
import argparse
import io
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter

from common import RAW, DATA, dart_get, dart_json, read_json, write_json, now_kst

CORPCODE_ZIP = RAW / "corpCode.zip"
COMPANY_DIR = RAW / "company"
OUT = DATA / "corp_list.json"

MARKETS = {"Y": "유가증권", "K": "코스닥"}
FINANCE_KSIC = ("64", "65", "66")   # 한국표준산업분류 K: 금융 및 보험업
# 일반 지주회사와 금융회사가 섞여 있는 업종코드 → 이름으로 판단
#   '649'(3자리): 효성·HDC·쿠쿠홀딩스 등 지주사와 벤처캐피탈·카드사가 함께 있음
#   '64992'(지주회사): LG·SK 등과 KB금융지주·신한금융지주가 함께 있음
AMBIGUOUS_KSIC = ("649", "64992")
FINANCE_WORDS = ("금융", "인베스트", "투자", "벤처", "파트너스", "캐피탈", "카드", "증권", "은행", "보험")
REIT_WORDS = ("리츠", "REIT", "부동산투자회사")


def load_corp_codes(refresh):
    if refresh or not CORPCODE_ZIP.exists():
        content = dart_get("corpCode.xml", {}).content
        if not content.startswith(b"PK"):
            raise SystemExit(f"[오류] zip이 아닌 응답: {content[:200]!r}")
        CORPCODE_ZIP.write_bytes(content)
    with zipfile.ZipFile(CORPCODE_ZIP) as z:
        root = ET.fromstring(z.read(z.namelist()[0]))
    return [{c.tag: (c.text or "").strip() for c in item} for item in root]


def fetch_company(corp_code):
    path = COMPANY_DIR / f"{corp_code}.json"
    if path.exists():
        return read_json(path), False
    data = dart_json("company.json", {"corp_code": corp_code})
    write_json(path, data)
    return data, True


def exclusion_reason(c):
    name = c["corp_name"]
    ksic = c["induty_code"]
    if c["corp_cls"] not in MARKETS:
        return f"시장구분 {c['corp_cls'] or '없음'}"
    if "스팩" in name or "기업인수목적" in name:
        return "스팩"
    if any(w in name.upper() for w in REIT_WORDS):
        return "리츠"
    if not c["stock_code"].endswith("0"):
        return "우선주 의심(종목코드 끝자리)"
    if ksic.startswith(FINANCE_KSIC):
        if ksic == AMBIGUOUS_KSIC[0] or ksic.startswith(AMBIGUOUS_KSIC[1]):
            return "금융업(지주·기타금융 중 이름 기준)" if any(w in name for w in FINANCE_WORDS) else None
        return "금융업"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-corpcode", action="store_true", help="corpCode.zip 다시 받기")
    args = ap.parse_args()

    rows = load_corp_codes(args.refresh_corpcode)
    listed = [r for r in rows if r.get("stock_code")]
    print(f"전체 {len(rows):,}개 중 종목코드 있는 회사 {len(listed):,}개")

    companies, called, errors = [], 0, Counter()
    for i, r in enumerate(listed, 1):
        data, was_called = fetch_company(r["corp_code"])
        called += was_called
        if data.get("status") != "000":
            errors[data.get("status")] += 1
            continue
        companies.append({
            "corp_code": r["corp_code"],
            "corp_name": data.get("corp_name") or r["corp_name"],
            "stock_code": data.get("stock_code") or r["stock_code"],
            "corp_cls": data.get("corp_cls", ""),
            "induty_code": data.get("induty_code", ""),
            "acc_mt": data.get("acc_mt", ""),
        })
        if i % 200 == 0:
            print(f"  {i:,}/{len(listed):,} 처리 (이번 실행 API 호출 {called:,}건)", flush=True)
    print(f"기업개황 완료: 이번 실행 API 호출 {called:,}건, 오류 {dict(errors) or '없음'}")

    print("시장구분 분포:", dict(Counter(c["corp_cls"] for c in companies)))

    included, excluded = [], []
    for c in companies:
        reason = exclusion_reason(c)
        (excluded if reason else included).append({**c, **({"reason": reason} if reason else {})})

    print(f"출제 대상 {len(included):,}개 / 제외 {len(excluded):,}개")
    for reason, n in Counter(e["reason"] for e in excluded).most_common():
        print(f"  제외 - {reason}: {n:,}")
    print("대상 시장 분포:", {MARKETS[k]: v for k, v in Counter(c["corp_cls"] for c in included).items()})

    write_json(OUT, {
        "generated_at": now_kst().isoformat(timespec="seconds"),
        "included": included,
        "excluded": excluded,
    }, indent=1)
    print(f"저장: {OUT.relative_to(DATA.parent)}")


if __name__ == "__main__":
    main()
