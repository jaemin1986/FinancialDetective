"""재무제표(사업보고서) 수집 → 화면용 항목 추출(fin_extract) → data/financials.json

실행 예:
  .\\.venv\\Scripts\\python.exe scripts\\fetch_financials.py --limit 50      # 무작위 50개 테스트
  .\\.venv\\Scripts\\python.exe scripts\\fetch_financials.py                 # 전체
- 연결(CFS) 우선, 없으면(status=013) 별도(OFS)로 재시도.
- 응답 원본은 data/raw/fin/<연도>/ 에 캐시하고 다시 호출하지 않는다.
  → 추출 규칙(fin_extract.py)만 바꿨을 때 다시 실행해도 API 호출은 0건.
- 금액은 원 단위 정수로 저장한다.
"""
import argparse
import random
from collections import Counter

from common import RAW, DATA, dart_json, read_json, write_json, now_kst
from fin_extract import extract, ANNUAL

CORP_LIST = DATA / "corp_list.json"
OUT = DATA / "financials.json"
REPORT = DATA / "financials_report.json"

REQUIRED = {"pl": ["revenue", "operating_income", "net_income"],
            "bs": ["assets", "liabilities", "equity"],
            "cf": ["operating_cf"]}


def default_year():
    """사업보고서는 결산 후 3월 말까지 제출 → 4월부터는 작년 보고서가 최신."""
    t = now_kst()
    return t.year - 1 if t.month >= 4 else t.year - 2


def fetch(corp_code, year, reprt_code="11011"):
    """CFS → OFS 순으로 시도. (fs_div, data) 반환. 둘 다 없으면 (None, None)."""
    for fs in ("CFS", "OFS"):
        suffix = "" if reprt_code == "11011" else f"_{reprt_code}"
        path = RAW / "fin" / str(year) / f"{corp_code}_{fs}{suffix}.json"
        if path.exists():
            data = read_json(path)
        else:
            data = dart_json("fnlttSinglAcntAll.json", {
                "corp_code": corp_code, "bsns_year": str(year),
                "reprt_code": reprt_code, "fs_div": fs,
            })
            write_json(path, data)
        if data.get("status") == "000" and data.get("list"):
            return fs, data
        if data.get("status") != "013":
            return None, data
    return None, None


def missing_required(e):
    return [k for part, keys in REQUIRED.items() for k in keys
            if not e[part].get(k) or any(v is None for v in e[part][k])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="무작위 N개만 (테스트용)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--year", type=int, default=default_year())
    args = ap.parse_args()

    corps = read_json(CORP_LIST)["included"]
    if args.limit:
        corps = random.Random(args.seed).sample(corps, min(args.limit, len(corps)))
    print(f"사업연도 {args.year}, 대상 {len(corps):,}개")

    result = {}
    report = {"no_report": [], "error": [], "missing": [], "bs_detail_mismatch": []}
    stats = Counter()
    for i, c in enumerate(corps, 1):
        fs, data = fetch(c["corp_code"], args.year)
        if fs is None:
            if data is None:
                stats["사업보고서 없음"] += 1
                report["no_report"].append(c["corp_name"])
            else:
                stats[f"오류 status={data.get('status')}"] += 1
                report["error"].append({"corp": c["corp_name"], "status": data.get("status"),
                                        "message": data.get("message")})
            continue
        e = extract(data["list"], ANNUAL)
        missing = missing_required(e)
        stats[fs] += 1
        if missing:
            stats["필수 항목 누락"] += 1
            report["missing"].append({"corp": c["corp_name"], "corp_code": c["corp_code"],
                                      "induty_code": c["induty_code"], "fs_div": fs, "missing": missing})
        if not e["bs_detail_ok"]:
            stats["재무상태표 세부 불일치"] += 1
            report["bs_detail_mismatch"].append(c["corp_name"])
        result[c["corp_code"]] = {
            "corp_name": c["corp_name"],
            "bsns_year": args.year,
            "years": [args.year - 2, args.year - 1, args.year],
            "fs_div": fs,
            "pl_source": e["pl_source"],
            "annual": {"bs": e["bs"], "pl": e["pl"], "cf": e["cf"]},
            "gross_profit_computed": e.get("gross_profit_computed", False),
            "bs_detail_ok": e["bs_detail_ok"],
            "complete": not missing,
        }
        if i % 100 == 0:
            print(f"  {i:,}/{len(corps):,}", flush=True)

    write_json(OUT, result)
    write_json(REPORT, report, indent=1)
    print("결과:", dict(stats))
    print(f"저장: data/financials.json ({len(result):,}개), data/financials_report.json")


if __name__ == "__main__":
    main()
