"""Supabase 백엔드 테스트 (보안 + 닉네임 + 게임 로직). 끝나면 테스트 데이터를 모두 지운다.

  .venv\\Scripts\\python.exe -X utf8 scripts\\test_backend.py

- 오늘(KST) 진짜 문제가 있으면 잠시 백업해 두고 테스트용 3문제로 바꿨다가, 끝나면 되돌린다.
- 팀 코드는 테스트용 임시 코드로 잠시 바꿨다가, 끝나면 원래 값(해시)으로 되돌린다.
"""
import secrets

from common import quiz_today, supabase_rest, supabase_rpc

TABLES = ["config", "banned_words", "players", "sessions", "signup_tokens", "attempts", "answers", "plays"]
NICKS = ["가짜A", "가짜B", "가짜C", "가짜D"]
# 테스트용 3문제: (정답 보기, 시총 원)
TEST_QS = [(2, 123_400_000_000), (0, 5_000_000_000_000), (3, 30_000_000_000)]
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  ({detail})" if detail and not cond else ""))


def anon(fn, **p):
    return supabase_rpc(fn, p, role="anon")


def section(t):
    print(f"\n■ {t}")


def play(tok, company_choices, guesses):
    """한 문제 풀기: 회사 선택들 → 시총 입력들. 마지막 응답을 돌려준다."""
    r = None
    for c in company_choices:
        r = anon("submit_company", token=tok, choice=c)
    for g in guesses:
        r = anon("submit_guess", token=tok, amount_eok=g)
    return r


def main():
    today = quiz_today().isoformat()
    backup = supabase_rest("GET", f"answers?quiz_date=eq.{today}&select=*").json()
    # 실제 팀 코드는 암호화된 값(해시)만 백업했다가 그대로 되돌린다 (원래 코드는 몰라도 됨)
    code_backup = supabase_rest("GET", "config?key=eq.team_code_hash&select=key,value").json()
    code = None

    def cleanup():
        for n in NICKS + ["새이름B"]:
            supabase_rest("DELETE", f"players?nickname_lower=eq.{n.lower()}")
        supabase_rest("DELETE", f"answers?quiz_date=eq.{today}")
        if backup:
            for row in backup:
                row.pop("created_at", None)
            supabase_rest("POST", "answers", json=backup)
        supabase_rest("DELETE", "attempts?key=neq.__none__")
        supabase_rest("DELETE", "config?key=eq.team_code_hash")
        if code_backup:
            supabase_rest("POST", "config", json=code_backup)

    for n in NICKS + ["새이름B"]:
        supabase_rest("DELETE", f"players?nickname_lower=eq.{n.lower()}")

    # ------------------------------------------------------------ 1. 보안
    section("1. 보안: 공개(anon) 키로 테이블 직접 접근 → 모두 거부되어야 함")
    for t in TABLES:
        g = supabase_rest("GET", f"{t}?select=*&limit=1", role="anon")
        i = supabase_rest("POST", t, role="anon", json={})
        check(f"{t:<14} 읽기 거부 {g.status_code} / 쓰기 거부 {i.status_code}",
              g.status_code in (401, 403, 404) and i.status_code in (401, 403, 404))
    for fn in ["admin_set_team_code", "admin_reset_pin", "admin_delete"]:
        try:
            anon(fn, code="xxxx") if fn == "admin_set_team_code" else anon(fn, nickname="가짜A")
            check(f"anon으로 {fn} 실행 거부", False, "실행됨")
        except RuntimeError as e:
            check(f"anon으로 {fn} 실행 거부", "HTTP 40" in str(e))
    try:
        anon("kst_today")
        check("내부 함수(private) 외부 노출 안 됨", False)
    except RuntimeError as e:
        check("내부 함수(private) 외부 노출 안 됨", "HTTP 404" in str(e))

    # ------------------------------------------------------------ 준비: 팀 코드, 테스트 문제 3개
    code = "t" + secrets.token_hex(6)
    supabase_rpc("admin_set_team_code", {"code": code})
    supabase_rest("DELETE", f"answers?quiz_date=eq.{today}")
    supabase_rest("POST", "answers", json=[
        {"quiz_date": today, "qn": n, "answer_index": a, "mcap": m, "bas_dt": today,
         "corp_name": f"테스트회사{n + 1}", "reveal": [{"name": "보기"}],
         "question": {"statement": {"years": [2025], "sections": []}, "options": [f"Q{n + 1}보기{k}" for k in range(4)]}}
        for n, (a, m) in enumerate(TEST_QS)])

    try:
        # -------------------------------------------------------- 2. 가입·닉네임
        section("2. 가입·닉네임 규칙")
        r = anon("verify_team_code", team_code="wrong")
        check("틀린 팀 코드 → WRONG_CODE", r.get("error") == "WRONG_CODE")
        for nick, err in [("가", "LENGTH"), ("가나다라마바사아자차카", "LENGTH"), ("a b", "CHARS"),
                          ("이모지😀", "CHARS"), ("SuperAdmin", "BANNED"), ("관리자님", "BANNED")]:
            r = anon("check_nickname", nickname=nick)
            check(f"'{nick}' → {err}", r.get("error") == err, r)
        tokens = {}
        for n in NICKS:
            st = anon("verify_team_code", team_code=code)["signup_token"]
            r = anon("register_player", signup_token=st, nickname=n, pin="1234")
            tokens[n] = r.get("token")
        check("가짜 참가자 4명 가입", all(tokens.values()))
        r = anon("check_nickname", nickname="가짜a")
        check("대소문자 다른 중복('가짜a') → TAKEN", r.get("error") == "TAKEN", r)
        st = anon("verify_team_code", team_code=code)["signup_token"]
        r = anon("register_player", signup_token=st, nickname="가짜E", pin="12a4")
        check("PIN 형식 오류 → PIN_FORMAT", r.get("error") == "PIN_FORMAT", r)
        r = anon("register_player", signup_token="가짜토큰", nickname="가짜E", pin="1234")
        check("가입 토큰 없이 가입 → SIGNUP_EXPIRED", r.get("error") == "SIGNUP_EXPIRED", r)

        section("3. 로그인·잠금·PIN")
        r = anon("login", nickname="가짜a", pin="1234")
        check("대소문자 무시 로그인", r.get("ok"), r)
        for _ in range(5):
            r = anon("login", nickname="가짜D", pin="0000")
        r = anon("login", nickname="가짜D", pin="1234")
        check("PIN 5회 틀린 뒤 맞는 PIN도 → LOCKED", r.get("error") == "LOCKED", r)
        supabase_rest("PATCH", "players?nickname_lower=eq.가짜d", json={"locked_until": None})
        r = supabase_rpc("admin_reset_pin", {"nickname": "가짜C"})
        temp = r.get("temp_pin")
        r = anon("whoami", token=tokens["가짜C"])
        check("PIN 재설정하면 기존 세션 만료", r.get("error") == "SESSION_EXPIRED", r)
        r = anon("login", nickname="가짜C", pin=temp)
        check("임시 PIN 로그인 → must_change_pin", r.get("must_change_pin") is True, r)
        tokens["가짜C"] = r["token"]
        r = anon("start_daily", token=tokens["가짜C"])
        check("PIN 바꾸기 전 오늘의 문제 → PIN_CHANGE_REQUIRED", r.get("error") == "PIN_CHANGE_REQUIRED", r)
        r = anon("change_pin", token=tokens["가짜C"], old_pin=temp, new_pin="5678")
        check("PIN 변경", r.get("ok"), r)

        section("4. 닉네임 변경 30일 제한")
        r = anon("change_nickname", token=tokens["가짜B"], new_nickname="새이름B")
        check("첫 변경 OK", r.get("ok"), r)
        r = anon("change_nickname", token=tokens["가짜B"], new_nickname="또바꿈B")
        check("바로 또 변경 → TOO_SOON", r.get("error") == "TOO_SOON", r)

        # -------------------------------------------------------- 5. 게임 로직 (하루 3문제)
        section("5. 게임 로직 (하루 3문제, 순서대로)")
        A, B, C, D = (tokens[n] for n in NICKS)
        r = anon("submit_company", token=A, choice=2)
        check("시작 전 제출 → NOT_STARTED", r.get("error") == "NOT_STARTED", r)
        r = anon("start_daily", token=A)
        cur = r.get("current") or {}
        check("시작: 1번 문제, 총 3문제", cur.get("qn") == 0 and r.get("total") == 3, r)
        check("시작: 1번 문제의 재무표·보기를 서버가 내려줌",
              (cur.get("question") or {}).get("options", [""])[0] == "Q1보기0", cur.get("question"))
        check("시작 상태에 정답 정보 없음", not any(k in cur for k in ("answer_index", "mcap", "reveal", "corp_name")), cur)
        r = anon("submit_guess", token=A, amount_eok=1234)
        check("회사 단계 전 시총 제출 → COMPANY_NOT_DONE", r.get("error") == "COMPANY_NOT_DONE", r)
        r = anon("submit_company", token=A, choice=2)
        check("A Q1 회사 1번째 정답 → 회사명 공개", r.get("correct") and r.get("corp_name") == "테스트회사1", r)
        r = anon("submit_company", token=A, choice=1)
        check("A Q1 회사 다시 제출 → COMPANY_DONE", r.get("error") == "COMPANY_DONE", r)
        r = anon("submit_guess", token=A, amount_eok=1240)
        check("A Q1 시총 오차 0.5% → 110점, reveal 공개", r.get("score") == 110 and r.get("reveal"), r)
        r = anon("submit_guess", token=A, amount_eok=1234)
        check("A Q1 끝난 뒤 제출 → NOT_STARTED (다음 문제는 열어야 시작)", r.get("error") == "NOT_STARTED", r)
        r = anon("start_daily", token=A)
        check("다음 문제 열기 → 2번, 1번 결과 포함", (r.get("current") or {}).get("qn") == 1
              and len(r.get("finished", [])) == 1, r)
        play(A, [0], [50000])
        anon("start_daily", token=A)
        r = play(A, [3], [300])
        check("A Q3 끝 → 110점", r.get("score") == 110, r)
        r = anon("start_daily", token=A)
        check("A 3문제 완료 → all_done, 결과 3개", r.get("all_done") and len(r.get("finished", [])) == 3
              and r.get("current") is None, {k: r.get(k) for k in ("all_done", "current")})

        anon("start_daily", token=B)
        r = anon("submit_company", token=B, choice=0)
        check("B Q1 회사 1번째 오답 → 회사명 비공개", r.get("correct") is False and "corp_name" not in r, r)
        r = anon("submit_company", token=B, choice=0)
        check("B 같은 보기 다시 → BAD_CHOICE", r.get("error") == "BAD_CHOICE", r)
        r = play(B, [2], [500, 1295])
        check("B Q1: 회사 2번째 + 시총 2번째(4.9%) → 68점", r.get("score") == 68, r)
        anon("start_daily", token=B)
        r = play(B, [1, 2], [60000, 52000])
        check("B Q2: 회사 실패 + 시총 2번째(4%) → 48점", r.get("score") == 48, r)
        anon("start_daily", token=B)
        play(B, [3], [300])

        anon("start_daily", token=D)
        play(D, [3, 2], [3000, 1148])          # Q1 오차 7% → 68
        anon("start_daily", token=D)
        play(D, [1, 2], [60000, 52000])        # 48
        anon("start_daily", token=D)
        play(D, [3], [300])                    # 110

        anon("start_daily", token=C)
        r = play(C, [0, 1], [5000, 4000, 3000, 2000, 1500])
        check("C Q1 회사·시총 모두 실패 → 0점, 정답 공개", r.get("score") == 0 and r.get("mcap") == TEST_QS[0][1], r)
        r = anon("start_daily", token=C)
        check("C 새로고침 → 2번 문제로 이어짐", (r.get("current") or {}).get("qn") == 1, r)

        section("6. 랭킹")
        r = anon("get_leaderboard", token=A)
        rows = [x for x in r.get("rows", []) if x["nickname"] in NICKS + ["새이름B"]]
        order = [(x["nickname"], x["score"], x["rank"]) for x in rows]
        print("   ", order)
        check("하루 순위: A 330 > 새이름B 226 > D 226(오차 평균 큼), C(1문제만)는 제외",
              [x[0] for x in order] == ["가짜A", "새이름B", "가짜D"] and order[0][1] == 330 and order[1][1] == 226)
        check("랭킹에 입력값·선택 보기 없음", all("guesses" not in x and "company_choices" not in x for x in rows))
        check("참여 인원에 C 포함 (4명 이상)", r.get("started", 0) >= 4, r.get("started"))
        r = anon("get_period_leaderboard", token=A, days=7)
        prow = {x["nickname"]: x for x in r.get("rows", [])}
        check("주간 랭킹: A 330점·1일, C 0점 포함", prow.get("가짜A", {}).get("score") == 330
              and prow.get("가짜A", {}).get("days") == 1 and prow.get("가짜C", {}).get("score") == 0, r)
        r = anon("get_my_history", token=B)
        h = r.get("rows", [{}])[0]
        check("내 기록: B 226점, 3/3문제", h.get("score") == 226 and h.get("solved") == 3 and h.get("questions") == 3, h)
        r = anon("get_leaderboard", token="가짜세션")
        check("세션 없이 랭킹 → SESSION_EXPIRED", r.get("error") == "SESSION_EXPIRED", r)

        section("7. 팀 코드 5회 실패 잠금 (IP 기준)")
        for _ in range(5):
            r = anon("verify_team_code", team_code="wrong")
        r = anon("verify_team_code", team_code=code)
        check("5회 틀린 뒤 맞는 코드도 → LOCKED", r.get("error") == "LOCKED", r)
    finally:
        cleanup()
        print("\n테스트 데이터 삭제 완료" + (" · 오늘 문제 정답 복원" if backup else "")
              + (" · 팀 코드 복원" if code_backup else ""))

    print(f"\n결과: {sum(results)}/{len(results)} 통과")


if __name__ == "__main__":
    main()
