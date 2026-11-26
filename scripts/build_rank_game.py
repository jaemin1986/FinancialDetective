r"""추가 게임 "시총 순위를 맞춰라!" + 시총 순위 화면 데이터 → docs/rank.json (2026-11-20 추가)

실행: .\.venv\Scripts\python.exe scripts\build_rank_game.py
- data/market_cap.json(매일 갱신, 최신 기준일)에서 코스피·코스닥 각각 시가총액 상위 800개를 순위대로 저장한다.
- 보통주만(종목코드 끝자리 0). 우선주·코넥스·스팩은 뺀다.
- 전일(직전 거래일) 시가총액·순위도 함께 넣는다(시총 순위 화면의 전일 대비, 급변동 종목). 2026-11-23 추가
- 주가 등락률(chg)과 상장주식수 변화 배수(sh, 바뀐 회사만)도 넣는다. 2026-11-26 추가
  전일 원본은 data/raw/mcap/<basDt>.json 캐시를 쓰고, 없으면 공공데이터 API로 받는다(하루 약 4건).
- 종목마다 DART 최근 정기보고서 접수번호(게임 결과 화면 링크). 2026-11-23 추가
  출제 대상 회사는 받아 둔 재무 캐시(data/raw/fin)에서, 나머지(금융사 등)는 OpenDART 공시검색 list.json
  (샘플 data/samples/list_periodic_sample.json)으로 찾고 data/raw/latest_report/ 에 14일간 캐시한다.
- 문제(어떤 순위 5개를 낼지)는 화면이 이 목록에서 무작위로 만든다. 랭킹에 반영하지 않는 연습용.
- 공개된 시세·공시 정보라서 정답 인코딩은 하지 않는다.
"""
import re
import time
from datetime import date, datetime, timedelta

from build_quiz import latest_report
from common import ROOT, DATA, RAW, read_json, write_json, now_kst, dart_json
from fetch_market_cap import fetch_day, data_go_get, OP

OUT = ROOT / "docs" / "rank.json"
TOP = 800
REPORT_CACHE_DAYS = 14


def ranking(caps):
    """{시장: [(종목코드, {...}), ...] 시총 큰 순} — 보통주·스팩 제외."""
    out = {}
    for mkt in ("KOSPI", "KOSDAQ"):
        rows = [(k, v) for k, v in caps.items()
                if v["market"] == mkt and k.endswith("0") and "스팩" not in v["name"] and v["mcap"] > 0]
        rows.sort(key=lambda kv: -kv[1]["mcap"])
        out[mkt] = rows
    return out


def prev_caps(basdt):
    """직전 거래일 {종목코드: {mcap, market, name}}과 그 날짜. 캐시 우선, 없으면 API."""
    d = datetime.strptime(basdt, "%Y%m%d").date()
    for _ in range(10):
        d -= timedelta(days=1)
        bas = d.strftime("%Y%m%d")
        path = RAW / "mcap" / f"{bas}.json"
        if not path.exists():
            body = data_go_get(OP, {"basDt": bas, "numOfRows": 1, "pageNo": 1})
            if int(body.get("totalCount") or 0) == 0:
                continue          # 휴장일
        rows = fetch_day(bas)
        if not rows:
            continue
        return bas, day_caps(rows)
    return None, {}


def day_caps(rows):
    """원본 행 → {종목코드: {mcap, market, name, shares(상장주식수), chg(주가 등락률 %)}}"""
    caps = {}
    for r in rows:
        try:
            caps[r["srtnCd"]] = {"mcap": int(r["mrktTotAmt"]), "market": r["mrktCtg"], "name": r["itmsNm"],
                                 "shares": int(r["lstgStCnt"]), "chg": float(r["fltRt"])}
        except (KeyError, ValueError):
            continue
    return caps


def dart_report(corp_code, fins):
    """최근 정기보고서 {"rcept_no", "label"} 또는 None."""
    f = fins.get(corp_code)
    if f:
        rep = latest_report(corp_code, f)
        if rep:
            return rep
    path = RAW / "latest_report" / f"{corp_code}.json"
    if path.exists():
        c = read_json(path)
        if (date.today() - date.fromisoformat(c["checked"])).days < REPORT_CACHE_DAYS:
            return c["report"]
    end = date.today()
    d = dart_json("list.json", {"corp_code": corp_code, "bgn_de": (end - timedelta(days=400)).strftime("%Y%m%d"),
                                "end_de": end.strftime("%Y%m%d"), "pblntf_ty": "A", "page_count": "5"})
    time.sleep(0.2)
    rep = None
    for x in d.get("list") or []:   # 최신순
        if x.get("rcept_no"):
            label = re.sub(r"^\[[^\]]*\]", "", x.get("report_nm", "")).strip()   # [기재정정] 등 떼기
            rep = {"rcept_no": x["rcept_no"], "label": label}
            break
    write_json(path, {"checked": date.today().isoformat(), "report": rep})
    return rep


def main():
    mc = read_json(DATA / "market_cap.json")
    today = day_caps(fetch_day(mc["basDt"]))   # 상장주식수·주가 등락률(원본 캐시, 없으면 API 4건)
    cur = ranking(mc["caps"])
    prev_bas, pcaps = prev_caps(mc["basDt"])
    prev = ranking(pcaps)
    prev_rank = {mkt: {k: i + 1 for i, (k, _) in enumerate(rows)} for mkt, rows in prev.items()}

    cl = read_json(DATA / "corp_list.json")
    corp_of = {c["stock_code"]: c["corp_code"] for part in ("included", "excluded")
               for c in cl[part] if c.get("stock_code")}
    fins = read_json(DATA / "financials.json")

    markets, api_calls = {}, 0
    for mkt, rows in cur.items():
        lst = []
        for k, v in rows[:TOP]:
            item = {"name": v["name"], "mcap": v["mcap"]}
            if k in pcaps:
                item["prev_mcap"] = pcaps[k]["mcap"]
            if k in prev_rank[mkt]:
                item["prev_rank"] = prev_rank[mkt][k]
            t = today.get(k)
            if t:
                item["chg"] = t["chg"]                       # 주가 등락률(%)
                ps = (pcaps.get(k) or {}).get("shares")
                if ps and t["shares"] != ps:                 # 상장주식수 변화(증자·CB전환·합병·감자·분할 등)
                    item["sh"] = round(t["shares"] / ps, 3)
            cc = corp_of.get(k)
            if cc:
                had = (RAW / "latest_report" / f"{cc}.json").exists() or cc in fins
                rep = dart_report(cc, fins)
                api_calls += 0 if had else 1
                if rep:
                    item["dart"] = rep
            lst.append(item)
        markets[mkt] = lst
    write_json(OUT, {"generated_at": now_kst().isoformat(timespec="seconds"),
                     "basDt": mc["basDt"], "prevBasDt": prev_bas, "markets": markets})
    n_dart = sum(1 for v in markets.values() for x in v if "dart" in x)
    print(f"시총 순위: 기준일 {mc['basDt']} (전일 {prev_bas}) · " +
          " / ".join(f"{k} {len(v)}개" for k, v in markets.items()) +
          f" · DART 링크 {n_dart}개 (공시검색 새 호출 약 {api_calls}건) → docs/rank.json")


if __name__ == "__main__":
    main()
