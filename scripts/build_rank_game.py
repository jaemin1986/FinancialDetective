r"""추가 게임 "시총 순위를 맞춰라!" 데이터 → docs/rank.json (2026-11-20 추가)

실행: .\.venv\Scripts\python.exe scripts\build_rank_game.py
- data/market_cap.json(매일 갱신, 최신 기준일)에서 코스피·코스닥 각각 시가총액 상위 800개를 순위대로 저장한다.
- 보통주만(종목코드 끝자리 0). 우선주·코넥스·스팩은 뺀다.
- 문제(어떤 순위 10개를 낼지)는 화면이 이 목록에서 무작위로 만든다. 랭킹에 반영하지 않는 연습용.
- 공개된 시세 정보라서 정답 인코딩은 하지 않는다.
"""
from common import ROOT, DATA, read_json, write_json, now_kst

OUT = ROOT / "docs" / "rank.json"
TOP = 800


def main():
    mc = read_json(DATA / "market_cap.json")
    markets = {}
    for mkt in ("KOSPI", "KOSDAQ"):
        rows = [v for k, v in mc["caps"].items()
                if v["market"] == mkt and k.endswith("0") and "스팩" not in v["name"] and v["mcap"] > 0]
        rows.sort(key=lambda v: -v["mcap"])
        markets[mkt] = [{"name": v["name"], "mcap": v["mcap"]} for v in rows[:TOP]]
    write_json(OUT, {"generated_at": now_kst().isoformat(timespec="seconds"),
                     "basDt": mc["basDt"], "markets": markets})
    print(f"시총 순위 게임: 기준일 {mc['basDt']} · " +
          " / ".join(f"{k} {len(v)}개" for k, v in markets.items()) + " → docs/rank.json")


if __name__ == "__main__":
    main()
