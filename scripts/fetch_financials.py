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
from fin_extract import extract, ANNUAL, QUARTER

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
            if data.get("status") != "013":  # 미제출(013)은 캐시하지 않고 다음 갱신 때 다시 확인
                write_json(path, data)
        if data.get("status") == "000" and data.get("list"):
            return fs, data
        if data.get("status") != "013":
            return None, data
    return None, None


# 분기·반기보고서: 3Q → 반기 → 1Q 순으로 최신 것. (보고서 코드, 누적 개월 수, 분기 이름)
QUARTER_REPORTS = [("11014", 9, "3Q"), ("11012", 6, "2Q"), ("11013", 3, "1Q")]
QUARTER_END = {3: "3.31", 6: "6.30", 9: "9.30"}
CUM_NAME = {3: "1Q", 6: "1~2Q", 9: "1~3Q"}


def fetch_quarter(corp_code, fs, annual_year):
    """사업보고서(annual_year)보다 새로운 최신 분기·반기보고서. 연간과 같은 연결/별도 기준으로만 받는다.
    없으면 None. 미제출(013)은 캐시하지 않는다(다음 갱신 때 다시 확인)."""
    this_year = now_kst().year
    for year in (this_year, this_year - 1):
        if year <= annual_year:
            continue
        for reprt, months, qname in QUARTER_REPORTS:
            path = RAW / "fin" / str(year) / f"{corp_code}_{fs}_{reprt}.json"
            if path.exists():
                data = read_json(path)
            else:
                data = dart_json("fnlttSinglAcntAll.json", {
                    "corp_code": corp_code, "bsns_year": str(year), "reprt_code": reprt, "fs_div": fs})
                if data.get("status") != "013":
                    write_json(path, data)
            if data.get("status") == "000" and data.get("list"):
                return year, reprt, months, qname, data
    return None


def quarter_entry(corp_code, fs, annual_year):
    got = fetch_quarter(corp_code, fs, annual_year)
    if not got:
        return None
    year, reprt, months, qname, data = got
    q = extract(data["list"], QUARTER)
    pl, cf = q["pl"], q["cf"]
    # 필수 항목(올해 누적 매출·영업이익·순이익, 분기말 자산·부채·자본)이 없으면 쓰지 않음
    if any(not pl.get(k) or pl[k][1] is None for k in ("revenue", "operating_income", "net_income"))             or any(not q["bs"].get(k) or q["bs"][k][0] is None for k in ("assets", "liabilities", "equity")):
        return None
    a, l, e = (q["bs"][k][0] for k in ("assets", "liabilities", "equity"))
    if abs(a - (l + e)) > 0.005 * abs(a) + 1e8:  # 분기말 자산 ≠ 부채+자본 (원본 불일치) → 연간만 표시
        return None
    yy = lambda y: str(y)[2:]
    return {
        "year": year, "reprt_code": reprt, "months": months,
        "label": f"{yy(year)}.{qname}", "period": f"1~{months}월 누적",
        "bs_date": f"{yy(year)}.{QUARTER_END[months]}",
        "cum_label": [f"{yy(year - 1)}.{CUM_NAME[months]}", f"{yy(year)}.{CUM_NAME[months]}"],
        "bs": q["bs"], "pl": pl, "cf": cf,   # pl·cf = [전년 동기 누적, 올해 누적], bs = [분기말]
    }


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
            "quarter": quarter_entry(c["corp_code"], fs, args.year),
        }
        if result[c["corp_code"]]["quarter"]:
            stats["최신 분기 있음"] += 1
        if i % 100 == 0:
            print(f"  {i:,}/{len(corps):,}", flush=True)

    write_json(OUT, result)
    write_json(REPORT, report, indent=1)
    print("결과:", dict(stats))
    print(f"저장: data/financials.json ({len(result):,}개), data/financials_report.json")


if __name__ == "__main__":
    main()
