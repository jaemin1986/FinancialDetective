"""최근 영업일 전 종목 시가총액 → data/market_cap.json

실행: .\\.venv\\Scripts\\python.exe scripts\\fetch_market_cap.py [--date YYYYMMDD]
- 날짜를 안 주면 API에 올라온 가장 최근 기준일(basDt)을 쓴다. (영업일 다음 날 오후 1시 이후 갱신)
- 응답 원본은 data/raw/mcap/<basDt>.json 에 캐시한다.
- 금액은 원 단위 정수.
"""
import argparse

from common import RAW, DATA, data_go_get, read_json, write_json, now_kst

OP = "getStockPriceInfo_V2"
OUT = DATA / "market_cap.json"
PAGE = 1000
PROBE_CODE = "005930"  # 최신 기준일 확인용(거래가 끊기지 않는 종목)


def items_of(body):
    item = (body.get("items") or {}).get("item") or []
    return [item] if isinstance(item, dict) else item


def latest_basdt():
    body = data_go_get(OP, {"likeSrtnCd": PROBE_CODE, "numOfRows": 1, "pageNo": 1})
    items = items_of(body)
    if not items:
        raise SystemExit("[오류] 최신 기준일을 찾지 못함")
    return items[0]["basDt"]


def fetch_day(basdt):
    path = RAW / "mcap" / f"{basdt}.json"
    if path.exists():
        return read_json(path)
    rows, page, total = [], 1, None
    while total is None or len(rows) < total:
        body = data_go_get(OP, {"basDt": basdt, "numOfRows": PAGE, "pageNo": page})
        total = int(body.get("totalCount") or 0)
        got = items_of(body)
        print(f"  page {page}: {len(got)}건 (누적 {len(rows) + len(got)}/{total})", flush=True)
        if not got:
            break
        rows += got
        page += 1
    write_json(path, rows)
    return rows


def year_end_caps(year):
    """그해 마지막 거래일의 전 종목 시가총액 {"basDt", "caps": {종목코드: 원}}.
    12/31부터 하루씩 거슬러 올라가 데이터가 있는 첫날을 쓴다. 결과는 data/raw/mcap_ye/<연도>.json 에 캐시
    (매일 정리하는 data/raw/mcap/ 와 분리)."""
    from datetime import date, timedelta
    path = RAW / "mcap_ye" / f"{year}.json"
    if path.exists():
        return read_json(path)
    d = date(year, 12, 31)
    for _ in range(10):
        bas = d.strftime("%Y%m%d")
        body = data_go_get(OP, {"basDt": bas, "numOfRows": 1, "pageNo": 1})
        if int(body.get("totalCount") or 0) > 0:
            break
        d -= timedelta(days=1)
    else:
        raise SystemExit(f"[오류] {year}년 마지막 거래일을 찾지 못함")
    rows, page, total = [], 1, None
    while total is None or len(rows) < total:
        body = data_go_get(OP, {"basDt": bas, "numOfRows": PAGE, "pageNo": page})
        total = int(body.get("totalCount") or 0)
        got = items_of(body)
        if not got:
            break
        rows += got
        page += 1
    caps = {}
    for r in rows:
        try:
            caps[r["srtnCd"]] = int(r["mrktTotAmt"])
        except (KeyError, ValueError):
            continue
    out = {"basDt": bas, "caps": caps}
    write_json(path, out)
    print(f"{year}년 마지막 거래일 {bas}: {len(caps):,}종목")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="기준일 YYYYMMDD (기본: 최신)")
    args = ap.parse_args()

    basdt = args.date or latest_basdt()
    print(f"기준일 {basdt}")
    rows = fetch_day(basdt)

    caps = {}
    for r in rows:
        try:
            caps[r["srtnCd"]] = {"mcap": int(r["mrktTotAmt"]), "market": r["mrktCtg"], "name": r["itmsNm"]}
        except (KeyError, ValueError):
            continue

    corps = read_json(DATA / "corp_list.json")["included"]
    missing = [c["corp_name"] for c in corps if c["stock_code"] not in caps]
    print(f"전 종목 {len(caps):,}개 / 출제 대상 {len(corps):,}개 중 시총 없음 {len(missing)}개")
    if missing:
        print("  예:", missing[:10])

    write_json(OUT, {"basDt": basdt, "fetched_at": now_kst().isoformat(timespec="seconds"), "caps": caps})
    print(f"저장: data/market_cap.json")


if __name__ == "__main__":
    main()
