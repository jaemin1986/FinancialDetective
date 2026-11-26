"""연습 문제 풀(docs/pool/) + 오늘의 문제(data/answers/YYYY-MM-DD.json) 생성

실행 예:
  .\\.venv\\Scripts\\python.exe scripts\\build_quiz.py                  # 내일 문제 + 연습 풀
  .\\.venv\\Scripts\\python.exe scripts\\build_quiz.py --date 2026-11-15
입력: data/corp_list.json, data/financials.json, data/market_cap.json
출력:
  data/answers/<날짜>.json 오늘의 문제 3개(재무표+보기)와 정답 (git 제외 → upload_daily.py가 Supabase로)
                           공개 파일로는 만들지 않는다: 문제는 그날 새벽 3시 이후 RPC로만 내려감
  docs/pool/               연습 문제 (정답은 base64+XOR 인코딩, git 제외 — Actions가 만들어 배포)
보안:
  - 오늘의 문제 회사는 SystemRandom으로 고른다(코드·데이터가 공개돼도 재현 불가).
  - 최근 90일 출제 회사, 오늘·내일 출제 회사는 연습 풀에서 뺀다.
금액은 원 단위 정수로 저장하고, 억원 표시는 화면(app.js)에서 한다.
"""
import argparse
import base64
import json
import random
import re
from datetime import date, timedelta

from common import ROOT, DATA, RAW, read_json, write_json, now_kst, quiz_today
from fin_extract import BS_ITEMS
from fetch_market_cap import year_end_caps

YE_CAPS = {}  # 연도 → 그해 마지막 거래일 시총 (main에서 채움)

DOCS = ROOT / "docs"
ANSWERS = DATA / "answers"
XOR_KEY = b"FinancialDetective-practice"  # 연습 모드용 가벼운 가림막(보안 목적 아님)
REPEAT_DAYS = 90
MATERIAL = 0.05  # 자산총계 대비 이 비율 이상인 해가 있으면 '클 때만 표시' 항목을 보여줌
CHUNK = 50       # 연습 풀 파일 하나에 넣을 문제 수
N_DISTRACTORS = 3  # 오답 보기 수 (보기 = 정답 1 + 오답 3 = 4개, 2026-11-14 결정)
DAILY_COUNT = 3    # 오늘의 문제 하루 문제 수 (2026-11-14 결정)

sysrand = random.SystemRandom()


# ---------------------------------------------------------------- 표 만들기
def _row(label, v, level=0, kind="amt"):
    """화면용 한 줄: [이름, 들여쓰기(0/1), 종류(amt|sub|total|pct), [값...]]  (파일 크기를 줄이려고 배열)"""
    return [label, level, kind, v]


def _sub(a, b):
    return [None if x is None or y is None else x - y for x, y in zip(a, b)]


def _material(v, assets):
    return v and any(x is not None and a and abs(x) >= MATERIAL * a for x, a in zip(v, assets))


def bs_rows(bs):
    assets = bs["assets"]
    rows = []
    blocks = [("current_assets", "유동자산"), ("noncurrent_assets", "비유동자산"), None,
              ("current_liabilities", "유동부채"), ("noncurrent_liabilities", "비유동부채")]
    for blk in blocks:
        if blk is None:
            rows.append(_row("자산총계", assets, 0, "total"))
            continue
        sec, title = blk
        tot = bs[sec]
        rows.append(_row(title, tot, 0, "sub"))
        shown_sum = [0] * len(tot)
        for spec in BS_ITEMS[sec]:
            v = bs.get(spec["key"])
            if spec["show"] == "always" or _material(v, assets):
                v = v or [0] * len(tot)
                rows.append(_row(spec["label"], v, 1))
                shown_sum = [s + (x or 0) for s, x in zip(shown_sum, v)]
        rows.append(_row("기타", _sub(tot, shown_sum), 1))  # 소계 − 표시한 항목 합
    rows.append(_row("부채총계", bs["liabilities"], 0, "total"))
    rows.append(_row("자본총계", bs["equity"], 0, "total"))
    eo = bs.get("equity_owners")
    if eo and eo != bs["equity"]:
        rows.append(_row("지배주주 자본", eo, 1))
    return rows


def pl_rows(pl):
    n = len(pl["revenue"])
    z = [0] * n
    g = lambda k: pl.get(k) or [None] * n  # 없는 항목은 빈 칸("-")
    rows = [_row("매출액", g("revenue"), 0, "sub"),
            _row("매출원가", g("cost_of_sales"), 1),
            _row("매출총이익", g("gross_profit"), 0, "sub"),
            _row("판매비와관리비", g("sga"), 1),
            _row("영업이익", g("operating_income"), 0, "total"),
            _row("기타수익", g("other_gains") or z, 1),
            _row("기타비용", g("other_losses") or z, 1),
            _row("금융수익", g("finance_income") or z, 1),
            _row("금융비용", g("finance_costs") or z, 1)]
    em = pl.get("equity_method_pl")
    if em and any(em):
        rows.append(_row("지분법손익", em, 1))
    # 나머지(중단영업 전 기타 영업외 항목 등): 세전이익 − 위 항목들
    oi, pt = g("operating_income"), g("pretax")
    if pl.get("operating_income") and pl.get("pretax"):
        calc = [None if a is None else a + (b or 0) - (c or 0) + (d or 0) - (e or 0) + (f or 0)
                for a, b, c, d, e, f in zip(oi, g("other_gains") or z, g("other_losses") or z,
                                            g("finance_income") or z, g("finance_costs") or z, em or z)]
        rest = _sub(pt, calc)
        if any(x for x in rest if x):
            rows.append(_row("기타 영업외손익", rest, 1))
    rows += [_row("법인세차감전이익", pt, 0, "sub"),
             _row("법인세비용", g("income_tax"), 1),
             _row("당기순이익", g("net_income"), 0, "total")]
    if pl.get("net_income_owners") and pl["net_income_owners"] != pl["net_income"]:
        rows.append(_row("지배주주 순이익", pl["net_income_owners"], 1))
    return rows


def cf_rows(cf):
    n = len(cf["operating_cf"])
    g = lambda k: cf.get(k) or [None] * n  # 없는 항목은 빈 칸("-")
    ocf, capex = g("operating_cf"), g("capex")
    rows = [_row("영업활동현금흐름", ocf, 0, "sub"),
            _row("투자활동현금흐름", g("investing_cf"), 0, "sub"),
            _row("유형자산 취득", capex, 1),
            _row("재무활동현금흐름", g("financing_cf"), 0, "sub"),
            _row("현금 순증감", g("cash_change"), 0, "total")]
    if cf.get("capex"):
        rows.append(_row("잉여현금흐름(FCF)",
                         [None if a is None or b is None else a + b for a, b in zip(ocf, capex)], 0, "sub"))
    return rows


def ratio_rows(pl, bs):
    def div(a, b):
        return None if a is None or not b else round(a / b * 100, 1)
    rev, gp, oi, ni = pl["revenue"], pl.get("gross_profit"), pl["operating_income"], pl["net_income"]
    ni_o = pl.get("net_income_owners") or ni
    eq_o = bs.get("equity_owners") or bs["equity"]
    n = len(rev)
    growth = [None] + [div((rev[i] or 0) - (rev[i - 1] or 0), rev[i - 1]) if rev[i] is not None else None
                       for i in range(1, n)]
    rows = [_row("매출성장률", growth, 0, "pct")]
    if gp and any(x is not None for x in gp):
        rows.append(_row("매출총이익률", [div(a, b) for a, b in zip(gp, rev)], 0, "pct"))
    rows += [_row("영업이익률", [div(a, b) for a, b in zip(oi, rev)], 0, "pct"),
             _row("순이익률", [div(a, b) for a, b in zip(ni, rev)], 0, "pct"),
             _row("부채비율", [div(a, b) for a, b in zip(bs["liabilities"], bs["equity"])], 0, "pct"),
             _row("ROE", [div(a, b) if b and b > 0 else None for a, b in zip(ni_o, eq_o)], 0, "pct")]
    return rows


def _with_quarter(annual, qpart):
    """연간 [3개년] 뒤에 최신 분기 값(올해 누적 또는 분기말) 하나를 붙여 4칸으로."""
    out = {}
    for k in set(annual) | set(qpart):
        a, qv = annual.get(k), qpart.get(k)
        cur = qv[-1] if qv else None
        out[k] = None if a is None and cur is None else (a or [None] * 3) + [cur]
    return out


def _quarter_ratios(rows, q, pl4, bs4):
    """비율 4번째 칸 보정: 매출성장률은 전년 동기 누적 대비, ROE는 누적 순이익 연환산 / 분기말 자본."""
    def div(a, b):
        return None if a is None or not b else round(a / b * 100, 1)
    rev = q["pl"]["revenue"]  # [전년 동기 누적, 올해 누적]
    ni_o = (q["pl"].get("net_income_owners") or q["pl"]["net_income"])[1]
    eq_o = bs4.get("equity_owners") or bs4["equity"]
    for r in rows:
        if r[0] == "매출성장률":
            r[3][3] = div(rev[1] - rev[0], abs(rev[0])) if rev[0] and rev[1] is not None else None
        elif r[0] == "ROE":
            r[3][3] = div(ni_o * 12 / q["months"], eq_o[3]) if ni_o is not None and eq_o[3] and eq_o[3] > 0 else None
    return rows


def statement(fin):
    a, q = fin["annual"], fin.get("quarter")
    pl, bs, cf = a["pl"], a["bs"], a["cf"]
    if q:
        pl, bs, cf = _with_quarter(pl, q["pl"]), _with_quarter(bs, q["bs"]), _with_quarter(cf, q["cf"])
    ratios = ratio_rows(pl, bs)
    if q:
        ratios = _quarter_ratios(ratios, q, pl, bs)
    out = {
        "years": fin["years"],
        "fs_div": fin["fs_div"],  # CFS=연결, OFS=별도
        "sections": [
            {"title": "손익계산서", "rows": pl_rows(pl)},
            {"title": "재무상태표", "rows": bs_rows(bs)},
            {"title": "현금흐름", "rows": cf_rows(cf)},
            {"title": "주요 비율", "rows": ratios},
        ],
    }
    if q:  # 최신 분기 열(4번째 값) + 누적 실적 비교표
        out["ttm"] = {"label": q["label"], "period": q["period"], "bsDate": q["bs_date"],
                      "cumLabel": q["cum_label"]}
        out["cum"] = {k: q["pl"][k] for k in ("revenue", "operating_income", "net_income")}
    return out


# ---------------------------------------------------------------- 보기 고르기
def clean_name(name):
    name = re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사", "", name)
    return " ".join(name.split()).strip()


def pick_distractors(target, universe, caps, rng):
    """같은 업종 + 시총 0.33~3배 우선 → 조건을 넓혀 가며 N_DISTRACTORS개."""
    tcap = caps[target["stock_code"]]["mcap"]
    tname = clean_name(target["corp_name"])
    steps = [(3, 0.33, 3), (2, 0.33, 3), (3, 0.1, 10), (2, 0.1, 10), (0, 0.33, 3), (0, 0, float("inf"))]
    chosen = []
    for plen, lo, hi in steps:
        cands = [c for c in universe
                 if c["corp_code"] != target["corp_code"] and c not in chosen
                 and clean_name(c["corp_name"]) != tname
                 and (plen == 0 or c["induty_code"][:plen] == target["induty_code"][:plen])
                 and lo <= caps[c["stock_code"]]["mcap"] / tcap <= hi]
        rng.shuffle(cands)
        chosen += cands[:N_DISTRACTORS - len(chosen)]
        if len(chosen) == N_DISTRACTORS:
            break
    return chosen


def load_ksic():
    """업종코드 → 업종명. data/ksic.json 이 있으면 쓰고, 없으면 빈 dict(화면엔 코드만 표시)."""
    p = DATA / "ksic.json"
    return read_json(p) if p.exists() else {}


def industry_name(code, ksic):
    for n in range(len(code), 1, -1):  # 5자리 → 4 → 3 → 2 순으로 이름이 있는 것
        if code[:n] in ksic:
            return ksic[code[:n]]
    return None


def per_pbr_base(f, q):
    """PER·PBR 분모 (2026-11-19 결정).
    PER = 최근 12개월(LTM) 지배주주 순이익 = 직전 연간 + 올해 누적 − 전년 동기 누적
    PBR = 최신 지배주주 자본(분기말). 분기 데이터가 없으면 직전 사업연도 기준.
    지배주주 값이 하나라도 없으면 당기순이익·자본총계로 대신한다."""
    a_pl, a_bs = f["annual"]["pl"], f["annual"]["bs"]
    year = str(f["years"][-1])[2:]
    if q and q.get("fs_div", f["fs_div"]) != f["fs_div"]:
        # 분기만 기준이 다름(예: 연간 연결, 분기 별도) → 섞어서 LTM을 만들지 않고 PER은 연간, PBR은 분기말
        last = lambda v: v[-1] if v else None
        ni = last(a_pl.get("net_income_owners")) or last(a_pl["net_income"])
        eq = (q["bs"].get("equity_owners") or [None])[0] or q["bs"]["equity"][0]
        return ni, eq, f"PER ({year})", f"PBR ({q['label']})"
    if q:
        own = a_pl.get("net_income_owners"), q["pl"].get("net_income_owners")
        if own[0] and own[0][-1] is not None and own[1] and None not in own[1]:
            ann, cum = own[0][-1], own[1]
        else:
            ann, cum = a_pl["net_income"][-1], q["pl"]["net_income"]
        ni = None if ann is None or None in cum else ann + cum[1] - cum[0]
        eq = (q["bs"].get("equity_owners") or [None])[0] or q["bs"]["equity"][0]
        return ni, eq, "PER (LTM)", f"PBR ({q['label']})"
    last = lambda v: v[-1] if v else None
    ni = last(a_pl.get("net_income_owners")) or last(a_pl["net_income"])
    eq = last(a_bs.get("equity_owners")) or last(a_bs["equity"])
    return ni, eq, f"PER ({year})", f"PBR ({year})"


_RCEPT = {}


def latest_report(code, f):
    """결과 화면의 DART 링크용: 가장 최근 보고서(분기 있으면 분기, 없으면 사업보고서)의 접수번호와 이름.
    data/raw/fin 캐시에서 읽는다(API 호출 없음). 정답 공개 후에만 보이는 reveal에만 넣는다."""
    if code in _RCEPT:
        return _RCEPT[code]
    q, fs = f.get("quarter"), f["fs_div"]
    if q:
        path = RAW / "fin" / str(q["year"]) / f"{code}_{q.get('fs_div', fs)}_{q['reprt_code']}.json"
        name = {"11013": "1분기보고서", "11012": "반기보고서", "11014": "3분기보고서"}[q["reprt_code"]]
        label = f"{q['year']} {name}"
    else:
        path = RAW / "fin" / str(f["bsns_year"]) / f"{code}_{fs}.json"
        label = f"{f['bsns_year']} 사업보고서"
    out = None
    if path.exists():
        lst = read_json(path).get("list") or []
        if lst and lst[0].get("rcept_no"):
            out = {"rcept_no": lst[0]["rcept_no"], "label": label}
    _RCEPT[code] = out
    return out


def summary(c, fins, caps, ksic):
    """정답 공개 후 비교 화면용 요약 (보기 각각)."""
    mcap = caps[c["stock_code"]]["mcap"]
    out = {"name": clean_name(c["corp_name"]), "industry_code": c["induty_code"],
           "industry": industry_name(c["induty_code"], ksic),
           "market": caps[c["stock_code"]]["market"], "mcap": mcap}
    f = fins.get(c["corp_code"])
    if f:
        pl, bs, cf = f["annual"]["pl"], f["annual"]["bs"], f["annual"]["cf"]
        q = f.get("quarter")
        ni_o, eq_o, per_label, pbr_label = per_pbr_base(f, q)
        if q:  # 결과 화면에도 최신 분기 누적 열 (문제 화면과 같은 방식)
            pl, bs, cf = _with_quarter(pl, q["pl"]), _with_quarter(bs, q["bs"]), _with_quarter(cf, q["cf"])
        ratios = ratio_rows(pl, bs)
        if q:
            ratios = _quarter_ratios(ratios, q, pl, bs)
        ratio = {r[0]: r for r in ratios}
        lv1 = lambda r: [r[0], 1, r[2], r[3]]  # 비율은 들여쓰기
        # 기말 시가총액: 각 연도 마지막 거래일(+ 분기 열은 분기말 마지막 거래일).
        # 결산월이 12월인 회사만 (그 외는 결산일과 시점이 달라 "-")
        dec = c.get("acc_mt", "12") == "12"
        ye = [YE_CAPS.get(y, {}).get("caps", {}).get(c["stock_code"]) if dec else None for y in f["years"]]
        if q:
            ye.append(year_end_caps(q["year"], q["months"])["caps"].get(c["stock_code"]) if dec else None)
        rows = [_row("시가총액(기말)", ye, 0, "sub"),
                _row("매출액", pl["revenue"], 0, "sub"), lv1(ratio["매출성장률"])]
        if "매출총이익률" in ratio:
            rows.append(lv1(ratio["매출총이익률"]))
        rows += [_row("영업이익", pl["operating_income"], 0, "sub"), lv1(ratio["영업이익률"]),
                 _row("당기순이익", pl["net_income"], 0, "sub"), lv1(ratio["순이익률"])]
        rows += [r for r in cf_rows(cf) if r[0] in ("영업활동현금흐름", "잉여현금흐름(FCF)")]
        rows += [_row("자산총계", bs["assets"], 0, "sub"),
                 _row("부채총계", bs["liabilities"], 0, "sub"), lv1(ratio["부채비율"]),
                 _row("자본총계", bs["equity"], 0, "sub"), lv1(ratio["ROE"])]
        out.update({
            "years": f["years"], "fs_div": f["fs_div"], "rows": rows,
            "per": round(mcap / ni_o, 1) if ni_o and ni_o > 0 else None,
            "pbr": round(mcap / eq_o, 2) if eq_o and eq_o > 0 else None,
            "per_label": per_label, "pbr_label": pbr_label,
        })
        rep = latest_report(c["corp_code"], f)
        if rep:
            out["dart"] = rep  # {"rcept_no", "label"}
        if q:
            out["ttm"] = {"label": q["label"], "period": q["period"], "bsDate": q["bs_date"],
                          "cumLabel": q["cum_label"]}
    return out


def make_question(target, fin, universe, caps, rng, fins, ksic):
    options = pick_distractors(target, universe, caps, rng) + [target]
    rng.shuffle(options)
    answer = next(i for i, c in enumerate(options) if c["corp_code"] == target["corp_code"])
    q = {"statement": statement(fin), "options": [clean_name(c["corp_name"]) for c in options]}
    ans = {"answer_index": answer, "mcap": caps[target["stock_code"]]["mcap"],
           "corp_name": clean_name(target["corp_name"]), "corp_code": target["corp_code"],
           "reveal": [summary(c, fins, caps, ksic) for c in options]}
    return q, ans


def encode(obj):
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(bytes(b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(raw))).decode()


# ---------------------------------------------------------------- 메인
def answer_codes(ans_file):
    """정답 파일의 회사 코드 목록 (하루 여러 문제 형식과 옛 1문제 형식 모두)."""
    a = read_json(ans_file)
    return [q["corp_code"] for q in a["questions"]] if "questions" in a else [a["corp_code"]]


def recent_answer_codes(before, days):
    codes = {}
    for p in ANSWERS.glob("*.json"):
        d = date.fromisoformat(p.stem)
        if before - timedelta(days=days) <= d:
            for code in answer_codes(p):
                codes[code] = d
    return codes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="오늘의 문제 날짜 YYYY-MM-DD (기본: 내일 KST)")
    ap.add_argument("--force", action="store_true", help="이미 있는 날짜 문제를 다시 만듦")
    args = ap.parse_args()
    qdate = date.fromisoformat(args.date) if args.date else (quiz_today() + timedelta(days=1))

    corps = read_json(DATA / "corp_list.json")["included"]
    fins = read_json(DATA / "financials.json")
    mc = read_json(DATA / "market_cap.json")
    caps, basdt = mc["caps"], mc["basDt"]
    for y in sorted({y for f in fins.values() for y in f.get("years", [])}):
        YE_CAPS[y] = year_end_caps(y)  # 처음 한 번만 API 호출(연도당 약 4건), 이후 캐시

    ksic = load_ksic()
    # 보기 후보: 시총이 있고, 비교 화면에 보여줄 재무 데이터(필수 항목)가 있는 회사
    # 12월 결산 회사만 (그 외 28개는 연도·분기 열의 기간이 달라 정답·보기 모두에서 제외, 2026-11-16 결정)
    universe = [c for c in corps if c.get("acc_mt") == "12"
                and c["stock_code"] in caps and caps[c["stock_code"]]["mcap"] > 0
                and (f := fins.get(c["corp_code"])) and f["complete"]]
    eligible = [c for c in universe
                if (f := fins.get(c["corp_code"])) and f["complete"] and f["bs_detail_ok"]
                and (f["annual"]["pl"]["revenue"][-1] or 0) > 0]
    print(f"보기 후보 {len(universe):,}개 / 출제 가능 {len(eligible):,}개, 시총 기준일 {basdt}")

    # 1) 오늘의 문제 (문제·정답 모두 data/answers/에만 → upload_daily.py가 Supabase로. 공개 파일 없음)
    ans_path = ANSWERS / f"{qdate}.json"
    recent = recent_answer_codes(qdate, REPEAT_DAYS)
    if ans_path.exists() and not args.force:
        print(f"{qdate} 문제는 이미 있음 (다시 만들려면 --force)")
    else:
        if ans_path.exists():  # --force로 다시 만들 때는 기존 그날 회사를 이력에서 뺌
            for code in answer_codes(ans_path):
                recent.pop(code, None)
        cands = [c for c in eligible if c["corp_code"] not in recent]
        targets = sysrand.sample(cands, DAILY_COUNT)   # 서로 다른 회사 DAILY_COUNT개
        anss = []
        for target in targets:
            q, ans = make_question(target, fins[target["corp_code"]], universe, caps, sysrand, fins, ksic)
            anss.append({**ans, "question": q})   # question = 재무표 + 보기 (정답 없음)
            recent[target["corp_code"]] = qdate
        write_json(ans_path, {"quiz_date": str(qdate), "basDt": basdt, "questions": anss}, indent=1)
        print(f"오늘의 문제 {qdate}: {len(anss)}문제 저장 data/answers/{qdate}.json (git 제외 → upload_daily.py)")

    # 2) 연습 풀: 최근·예정 오늘의 문제 회사는 정답으로도, 보기로도 쓰지 않음
    #    (연습 풀의 공개 정보로 오늘의 문제 정답을 역추적하지 못하게)
    blocked = set(recent_answer_codes(qdate + timedelta(days=1), REPEAT_DAYS + 1))
    p_universe = [c for c in universe if c["corp_code"] not in blocked]
    pool = []
    prng = random.Random()
    for c in eligible:
        if c["corp_code"] in blocked:
            continue
        q, ans = make_question(c, fins[c["corp_code"]], p_universe, caps, prng, fins, ksic)
        pool.append({**q, "a": encode({"i": ans["answer_index"], "m": ans["mcap"], "n": ans["corp_name"],
                                       "r": ans["reveal"]})})
    prng.shuffle(pool)
    # 휴대폰에서 한 번에 받는 양을 줄이려고 CHUNK문제씩 나눠 저장 (화면은 무작위 한 묶음만 받음)
    pool_dir = DOCS / "pool"
    for old in pool_dir.glob("p*.json"):
        old.unlink()
    chunks = [pool[i:i + CHUNK] for i in range(0, len(pool), CHUNK)]
    for n, chunk in enumerate(chunks):
        write_json(pool_dir / f"p{n:03d}.json", chunk, compact=True)
    write_json(pool_dir / "index.json", {"basDt": basdt, "generated_at": now_kst().isoformat(timespec="seconds"),
                                         "count": len(pool), "chunks": len(chunks)}, compact=True)
    sizes = [p.stat().st_size for p in pool_dir.glob("p*.json")]
    print(f"연습 풀 {len(pool):,}문제 (제외 {len(blocked)}개) → docs/pool/ {len(chunks)}개 파일, "
          f"파일당 평균 {sum(sizes) / len(sizes) / 1e3:,.0f}KB, 전체 {sum(sizes) / 1e6:.1f}MB")


if __name__ == "__main__":
    main()
