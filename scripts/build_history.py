r"""출제 히스토리 → docs/history.json (첫 화면 "출제 히스토리" 버튼용, 2026-11-19 추가)

실행: .\.venv\Scripts\python.exe scripts\build_history.py
- Supabase answers(오늘의 문제)에서 **달력 기준(자정) 어제까지** 날짜만 센다 (2026-11-28 사용자 결정).
  밤 작업은 보통 자정~새벽 2시에 돌기 때문에, 하루의 경계(새벽 3시) 대신 자정을 기준으로 해서
  방금 끝난 날의 문제를 바로 넣는다. 자정 전에 돌면 그날 문제는 넣지 않는다(아직 푸는 중).
- 보기(하루 3문제 × 4개)에 나올 때마다 그 회사 +1. 그중 정답이었던 횟수도 함께 센다.
- 시가총액은 data/market_cap.json의 최신 기준일 시가총액(원).
- 회사마다 보기에 나온 날짜(on)도 담아 화면에서 날짜별 열에 O로 표시한다.
- 지난 날짜의 보기 이름만 담기므로 공개 파일로 둬도 오늘 정답과는 무관하다.
"""
from collections import Counter

from build_quiz import clean_name, latest_report
from common import DATA, ROOT, read_json, write_json, supabase_rest, now_kst

OUT = ROOT / "docs" / "history.json"


def main():
    today = now_kst().date()   # 자정 기준 달력 날짜 (quiz_today()의 새벽 3시 경계가 아님)
    rows = supabase_rest("GET", f"answers?select=quiz_date,qn,corp_name,reveal&quiz_date=lt.{today}").json()
    shown, answered, days = Counter(), Counter(), set()
    on = {}  # 회사 → 보기에 나온 날짜 집합 (날짜별 O 표시용)
    for a in rows:
        days.add(a["quiz_date"])
        answered[a["corp_name"]] += 1
        for o in a["reveal"] or []:
            shown[o["name"]] += 1
            on.setdefault(o["name"], set()).add(a["quiz_date"])

    corps = {clean_name(c["corp_name"]): c for c in read_json(DATA / "corp_list.json")["included"]}
    mc = read_json(DATA / "market_cap.json")
    caps = mc["caps"]
    fins = read_json(DATA / "financials.json")
    # 출제 가능 회사 수(보기 후보): 12월 결산 + 시총 있음 + 재무 데이터 완비 (build_quiz와 같은 기준)
    universe = sum(1 for c in corps.values()
                   if c.get("acc_mt") == "12" and (caps.get(c["stock_code"]) or {}).get("mcap", 0) > 0
                   and (fins.get(c["corp_code"]) or {}).get("complete"))

    items = []
    for name, n in shown.items():
        c = corps.get(name)
        cap = caps.get(c["stock_code"]) if c else None
        item = {"name": name, "market": (cap or {}).get("market", ""),
                "count": n, "answer": answered.get(name, 0),
                "mcap": (cap or {}).get("mcap"), "on": sorted(on[name])}
        f = fins.get(c["corp_code"]) if c else None
        rep = latest_report(c["corp_code"], f) if f else None   # DART 최근 보고서 링크 (2026-11-28)
        if rep:
            item["dart"] = rep
        items.append(item)
    items.sort(key=lambda x: (-x["count"], -x["answer"], x["name"]))
    write_json(OUT, {
        "generated_at": now_kst().isoformat(timespec="seconds"),
        "through": str(max(days)) if days else None, "days": len(days),
        "dates": sorted(days),  # 화면에서 날짜 열(오래된 날 → 최근)
        "questions": len(rows), "options": sum(shown.values()),
        "universe": universe, "basDt": mc["basDt"], "items": items,
    })
    print(f"출제 히스토리: {len(days)}일 · {len(rows)}문제 · 보기 {sum(shown.values())}개 · 종목 {len(items)}개 → docs/history.json")


if __name__ == "__main__":
    main()
