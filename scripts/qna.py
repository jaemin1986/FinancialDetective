r""""무엇이든 물어보세요" 관리 (로컬 전용, service_role 키 사용) — 2026-11-24 추가

실행 예:
  .\.venv\Scripts\python.exe scripts\qna.py list            # 답변 대기 질문
  .\.venv\Scripts\python.exe scripts\qna.py list --all      # 전체(답변·숨김 포함)
  .\.venv\Scripts\python.exe scripts\qna.py answer 3 data\qna\3.json   # 답변 올리기(덮어쓰기)
  .\.venv\Scripts\python.exe scripts\qna.py hide 3          # 장난·스팸 숨기기 (unhide로 되돌림)

답변 파일(JSON) 형식 — 화면은 모든 글자를 그대로(HTML 없이) 표시한다:
  {"text": "설명 문단 (줄바꿈 가능)",
   "tables": [{"title": "표 제목", "columns": ["회사", "25.1~3Q", "26.1~3Q"],
               "align": ["l", "r", "r"], "rows": [["삼성SDI", "-14,232", "4,560"], ...]}],
   "note": "기준·출처 메모 (선택)"}
답변 원본은 data/qna/ 에 둔다(git 제외). 오늘·내일 퀴즈 정답과 관련된 질문에는 답하지 않는다.
"""
import argparse
import json
import sys

from common import read_json, supabase_rest, now_kst


def check(r):
    if r.status_code >= 400:
        sys.exit(f"Supabase 오류 (HTTP {r.status_code}): {r.text[:300]}")
    return r


def cmd_list(args):
    q = "questions?select=id,body,asked_at,answered_at,hidden&order=asked_at.asc"
    if not args.all:
        q += "&answer=is.null&hidden=is.false"
    rows = check(supabase_rest("GET", q)).json()
    if not rows:
        print("질문 없음")
    for r in rows:
        state = "숨김" if r["hidden"] else ("답변 완료" if r["answered_at"] else "대기")
        print(f"#{r['id']} [{state}] {r['asked_at'][:16].replace('T', ' ')}  {r['body']}")


def validate(ans):
    if not isinstance(ans, dict) or not isinstance(ans.get("text", ""), str):
        sys.exit("답변 형식 오류: {\"text\": ...} 객체여야 합니다")
    for t in ans.get("tables", []):
        cols = t.get("columns") or []
        for row in t.get("rows", []):
            if len(row) != len(cols):
                sys.exit(f"표 '{t.get('title', '')}' 열 개수 불일치: {row}")
    size = len(json.dumps(ans, ensure_ascii=False).encode("utf-8"))
    if size > 400_000:
        sys.exit(f"답변이 너무 큽니다({size:,} bytes). 표를 줄여 주세요")


def cmd_answer(args):
    ans = read_json(args.file)
    validate(ans)
    r = check(supabase_rest("PATCH", f"questions?id=eq.{args.id}",
                            json={"answer": ans, "answered_at": now_kst().isoformat()},
                            headers={"Prefer": "return=representation"}))
    if not r.json():
        sys.exit(f"#{args.id} 질문을 찾지 못함")
    print(f"#{args.id} 답변 올림")


def cmd_hide(args, hidden=True):
    r = check(supabase_rest("PATCH", f"questions?id=eq.{args.id}", json={"hidden": hidden},
                            headers={"Prefer": "return=representation"}))
    if not r.json():
        sys.exit(f"#{args.id} 질문을 찾지 못함")
    print(f"#{args.id} {'숨김' if hidden else '다시 보이게 함'}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("--all", action="store_true")
    p = sub.add_parser("answer"); p.add_argument("id", type=int); p.add_argument("file")
    p = sub.add_parser("hide"); p.add_argument("id", type=int)
    p = sub.add_parser("unhide"); p.add_argument("id", type=int)
    args = ap.parse_args()
    if args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "answer":
        cmd_answer(args)
    elif args.cmd == "hide":
        cmd_hide(args, True)
    else:
        cmd_hide(args, False)


if __name__ == "__main__":
    main()
