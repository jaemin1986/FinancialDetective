"""오늘의 문제 정답을 Supabase answers 테이블에 저장한다 (service_role 키 사용).

  .venv\\Scripts\\python.exe scripts\\upload_daily.py                 # 내일(KST) 문제
  .venv\\Scripts\\python.exe scripts\\upload_daily.py --date 2026-11-15

입력: data/answers/<날짜>.json (build_quiz.py가 만든 정답 파일, git 제외)
이미 같은 날짜가 올라가 있으면 덮어쓴다. 단, 그날 누군가 이미 풀기 시작했으면
정답이 바뀌면 안 되므로 중단한다(--force로만 덮어씀).
"""
import argparse
import sys
from datetime import date, timedelta

from common import DATA, quiz_today, read_json, supabase_rest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (기본: 내일 KST)")
    ap.add_argument("--force", action="store_true", help="이미 푼 사람이 있어도 덮어쓰기")
    a = ap.parse_args()
    qdate = date.fromisoformat(a.date) if a.date else quiz_today() + timedelta(days=1)

    path = DATA / "answers" / f"{qdate}.json"
    if not path.exists():
        sys.exit(f"정답 파일이 없습니다: {path} (먼저 build_quiz.py --date {qdate})")
    ans = read_json(path)

    played = supabase_rest("GET", f"plays?quiz_date=eq.{qdate}&select=id&limit=1").json()
    if played and not a.force:
        sys.exit(f"{qdate} 문제는 이미 푼 사람이 있어서 덮어쓰지 않습니다 (--force로 강제).")

    b = ans["basDt"]
    bas_dt = f"{b[:4]}-{b[4:6]}-{b[6:8]}"
    qs = ans["questions"] if "questions" in ans else [ans]   # 옛 1문제 형식도 지원
    rows = [{"quiz_date": str(qdate), "qn": n, "answer_index": q["answer_index"], "mcap": q["mcap"],
             "bas_dt": bas_dt, "corp_name": q["corp_name"], "reveal": q["reveal"],
             "question": q.get("question")} for n, q in enumerate(qs)]
    # 그날 정답을 통째로 바꾼다 (문제 수가 달라졌을 수도 있으므로 지우고 넣기)
    d = supabase_rest("DELETE", f"answers?quiz_date=eq.{qdate}")
    if d.status_code >= 300:
        sys.exit(f"기존 정답 삭제 실패 (HTTP {d.status_code}): {d.text[:300]}")
    r = supabase_rest("POST", "answers", json=rows, headers={"Prefer": "return=minimal"})
    if r.status_code >= 300:
        sys.exit(f"업로드 실패 (HTTP {r.status_code}): {r.text[:300]}")
    print(f"{qdate} 정답 업로드 완료 ({len(rows)}문제, 시총 기준일 {bas_dt})")

if __name__ == "__main__":
    main()
