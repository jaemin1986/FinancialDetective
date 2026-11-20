"""GitHub Actions가 매일 실행하는 작업 (로컬에서도 같은 순서로 실행 가능)

  python scripts/daily_job.py [--refresh-financials]

1) 데이터가 없으면(캐시가 비었으면) 상장사 목록·재무제표 수집 (DART 수천 건, 첫 실행만 오래 걸림)
   + 보고서 시즌(3~5월·8월·11월)의 월요일에는 재무제표 갱신: 새 분기·반기·사업보고서만 호출하고
     받은 것은 캐시하므로 보통 수십~수백 건 (2026-11-15 결정)
2) 최근 영업일 시가총액 수집 (공공데이터 4건)
3) 내일 문제 생성 + 연습 풀 생성 → 내일 문제를 Supabase에 업로드
4) 혹시 오늘 문제가 서버에 없으면(전날 실패 등) 오늘 문제도 만들어 업로드
5) 출제 히스토리(docs/history.json) 갱신
6) 시총 순위 게임 데이터(docs/rank.json) 갱신
"""
import argparse
import subprocess
import sys
from datetime import timedelta

from common import DATA, quiz_today, supabase_rest, now_kst, read_json

PY = sys.executable
SEASON_MONTHS = {3, 4, 5, 8, 11}  # 사업보고서(3월)·1Q(5월)·반기(8월)·3Q(11월) 제출 시즌


def run(*args):
    print(f"\n$ {' '.join(args)}", flush=True)
    subprocess.run([PY, *args], check=True)


def on_server(d):
    return bool(supabase_rest("GET", f"answers?quiz_date=eq.{d}&select=qn").json())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-financials", action="store_true", help="상장사 목록·재무제표 다시 수집")
    a = ap.parse_args()

    fin_path = DATA / "financials.json"
    if a.refresh_financials or not fin_path.exists():
        run("scripts/fetch_corp_list.py", *(["--refresh-corpcode"] if a.refresh_financials else []))
        run("scripts/fetch_financials.py")
    else:
        t = now_kst()
        season_monday = t.month in SEASON_MONTHS and t.weekday() == 0
        no_quarter_field = not any("quarter" in v for v in read_json(fin_path).values())  # 분기 기능 첫 반영
        if season_monday or no_quarter_field:
            print("재무제표 갱신 (보고서 시즌 주간 갱신 또는 분기 데이터 첫 수집)")
            run("scripts/fetch_financials.py")
    run("scripts/fetch_market_cap.py")

    today = quiz_today()
    tomorrow = today + timedelta(days=1)
    if not on_server(today):
        print(f"{today} 문제가 서버에 없어서 지금 만듭니다")
        run("scripts/build_quiz.py", "--date", str(today))
        run("scripts/upload_daily.py", "--date", str(today))
    # 내일 문제(이미 있으면 그대로) + 연습 풀. 연습 풀은 마지막에 만들어야 오늘·내일 회사가 모두 빠진다
    run("scripts/build_quiz.py", "--date", str(tomorrow))
    if not on_server(tomorrow):
        run("scripts/upload_daily.py", "--date", str(tomorrow))
    else:
        print(f"{tomorrow} 문제는 이미 서버에 있음")
    run("scripts/build_history.py")  # 첫 화면 "출제 히스토리" (어제까지)
    run("scripts/build_rank_game.py")  # 추가 게임 "시총 순위를 맞춰라!" (최신 시총)


if __name__ == "__main__":
    main()
