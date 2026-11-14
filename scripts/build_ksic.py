"""한국표준산업분류 코드표(CSV) → data/ksic.json (업종코드 → 업종명)

입력: data/ksic/*.csv  — 공공데이터포털 "국가데이터처_산업직업분류" (data.go.kr/data/15159306)
      컬럼: 분류(산업/직업), 코드값, 상세설명. 인코딩 CP949. (2026-11-14 확인)
실행: .\\.venv\\Scripts\\python.exe scripts\\build_ksic.py
"""
import csv
import io
from collections import Counter

from common import DATA, read_json, write_json


def main():
    src = sorted((DATA / "ksic").glob("*.csv"))
    if not src:
        raise SystemExit("[오류] data/ksic/ 에 CSV가 없습니다.")
    rows = list(csv.reader(io.StringIO(src[-1].read_bytes().decode("cp949"))))
    header, body = rows[0], rows[1:]
    if header[:3] != ["분류", "코드값", "상세설명"]:
        raise SystemExit(f"[오류] 예상과 다른 컬럼: {header}")

    # 1자리 코드는 대분류(알파벳 섹션)라 DART 업종코드와 겹치지 않으므로 2자리 이상만 사용
    ksic = {code.strip(): name.strip() for kind, code, name in body
            if kind == "산업" and len(code.strip()) >= 2}
    print(f"산업분류 {len(ksic):,}개 (원본 {src[-1].name})")

    corps = read_json(DATA / "corp_list.json")["included"]
    exact = Counter()
    unmatched = []
    for c in corps:
        code = c["induty_code"]
        hit = next((n for n in range(len(code), 1, -1) if code[:n] in ksic), None)
        if hit is None:
            unmatched.append((code, c["corp_name"]))
        else:
            exact["코드 그대로 일치" if hit == len(code) else f"앞 {hit}자리로 일치"] += 1
    print("상장사 업종코드 매칭:", dict(exact), f"/ 못 찾음 {len(unmatched)}개")
    for code, name in unmatched[:10]:
        print("  못 찾음:", code, name)

    write_json(DATA / "ksic.json", ksic, indent=0)
    print("저장: data/ksic.json")


if __name__ == "__main__":
    main()
