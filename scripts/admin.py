"""관리자용 스크립트 (로컬 PC에서만 실행. .env의 Supabase Secret 키 사용)

사용법 (프로젝트 폴더에서):
  .venv\\Scripts\\python.exe scripts\\admin.py set-team-code          # 팀 코드 설정·변경 (입력은 화면에 안 보임)
  .venv\\Scripts\\python.exe scripts\\admin.py list                   # 참가자 목록
  .venv\\Scripts\\python.exe scripts\\admin.py reset-pin <닉네임>       # 임시 PIN 발급 (다음 로그인 때 변경 필수)
  .venv\\Scripts\\python.exe scripts\\admin.py rename <닉네임> <새닉네임>
  .venv\\Scripts\\python.exe scripts\\admin.py delete <닉네임>          # 참가자와 기록 삭제
  .venv\\Scripts\\python.exe scripts\\admin.py reset-scores --date 2026-11-14     # 그날 기록만 삭제
  .venv\\Scripts\\python.exe scripts\\admin.py reset-scores --nickname <닉네임>    # 한 사람의 모든 기록 삭제
  .venv\\Scripts\\python.exe scripts\\admin.py reset-scores --all                 # 모든 기록 삭제 (시즌 초기화)
  (점수 리셋은 닉네임·PIN은 그대로 두고 풀이 기록(plays)만 지운다. 되돌릴 수 없음)
"""
import argparse
import getpass
import sys

from common import supabase_rest, supabase_rpc

ERRORS = {
    "NOT_FOUND": "그런 닉네임이 없습니다",
    "TOO_SHORT": "팀 코드는 4자 이상이어야 합니다",
    "LENGTH": "닉네임은 2~10자여야 합니다",
    "CHARS": "닉네임은 한글·영문·숫자·밑줄(_)만 쓸 수 있습니다",
    "TAKEN": "이미 있는 닉네임입니다",
}


def done(res, ok_msg):
    if res.get("ok"):
        print(ok_msg)
    else:
        sys.exit("실패: " + ERRORS.get(res.get("error"), str(res.get("error"))))


def main():
    ap = argparse.ArgumentParser(description="FinancialDetective 관리")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("set-team-code")
    sub.add_parser("list")
    p = sub.add_parser("reset-pin"); p.add_argument("nickname")
    p = sub.add_parser("rename"); p.add_argument("nickname"); p.add_argument("new_nickname")
    p = sub.add_parser("delete"); p.add_argument("nickname")
    p = sub.add_parser("reset-scores")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--date", help="YYYY-MM-DD 그날 기록만")
    g.add_argument("--nickname", help="이 닉네임의 모든 기록")
    g.add_argument("--all", action="store_true", help="모든 사람의 모든 기록")
    a = ap.parse_args()

    if a.cmd == "set-team-code":
        code = getpass.getpass("새 팀 코드 (입력 내용은 화면에 표시되지 않음): ").strip()
        if code != getpass.getpass("한 번 더 입력: ").strip():
            sys.exit("두 입력이 다릅니다. 다시 실행해 주세요.")
        done(supabase_rpc("admin_set_team_code", {"code": code}),
             "팀 코드를 설정했습니다. (기존 참가자는 영향 없음, 새로 가입할 때부터 적용)")

    elif a.cmd == "list":
        r = supabase_rest("GET", "players?select=nickname,created_at,nickname_changed_at,must_change_pin,locked_until"
                                 "&order=created_at")
        r.raise_for_status()
        rows = r.json()
        print(f"참가자 {len(rows)}명")
        for x in rows:
            flags = []
            if x["must_change_pin"]:
                flags.append("임시PIN")
            if x["locked_until"]:
                flags.append("잠금기록")
            print(f"  {x['nickname']:<12} 가입 {x['created_at'][:10]}  {' '.join(flags)}")

    elif a.cmd == "reset-pin":
        res = supabase_rpc("admin_reset_pin", {"nickname": a.nickname})
        done(res, f"임시 PIN: {res.get('temp_pin')}  → 본인에게 전달하세요. 로그인하면 새 PIN으로 바꾸게 됩니다.")

    elif a.cmd == "rename":
        done(supabase_rpc("admin_rename", {"nickname": a.nickname, "new_nickname": a.new_nickname}),
             f"'{a.nickname}' → '{a.new_nickname}' 변경 완료 (기록은 그대로)")

    elif a.cmd == "delete":
        if input(f"'{a.nickname}'과 모든 기록을 삭제합니다. 계속하려면 y: ").strip().lower() != "y":
            sys.exit("취소했습니다.")
        done(supabase_rpc("admin_delete", {"nickname": a.nickname}), "삭제했습니다.")

    elif a.cmd == "reset-scores":
        if a.date:
            filt, what = f"quiz_date=eq.{a.date}", f"{a.date} 하루의 모든 사람 기록"
        elif a.nickname:
            r = supabase_rest("GET", f"players?nickname_lower=eq.{a.nickname.lower()}&select=id")
            if not r.json():
                sys.exit("실패: " + ERRORS["NOT_FOUND"])
            filt, what = f"player_id=eq.{r.json()[0]['id']}", f"'{a.nickname}'의 모든 기록"
        else:
            filt, what = "id=gt.0", "모든 사람의 모든 기록 (시즌 초기화)"
        n = len(supabase_rest("GET", f"plays?{filt}&select=id").json())
        if n == 0:
            sys.exit("지울 기록이 없습니다.")
        if input(f"{what} {n}건을 삭제합니다. 되돌릴 수 없습니다. 계속하려면 y: ").strip().lower() != "y":
            sys.exit("취소했습니다.")
        r = supabase_rest("DELETE", f"plays?{filt}")
        if r.status_code >= 300:
            sys.exit(f"실패 (HTTP {r.status_code}): {r.text[:200]}")
        print(f"{n}건 삭제했습니다. 닉네임·PIN은 그대로입니다.")


if __name__ == "__main__":
    main()
