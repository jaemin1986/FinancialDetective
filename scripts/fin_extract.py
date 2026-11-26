"""재무제표 원본(fnlttSinglAcntAll 응답 list)에서 화면용 표준 항목을 뽑는 모듈.

- 회사마다 같은 개념을 다른 account_id로 쓰므로, 개념별로 후보 ID를 묶어 둔다.
  후보 ID는 data/raw/fin/2025 원본 732개 회사에서 실제로 확인한 것만 쓴다(2026-11-14).
- 표준 ID가 없는 행(account_id='-표준계정코드 미사용-')은 account_nm으로만 보조 매칭한다.
- 화면에는 아래 표준 이름(label)만 쓴다. 회사 고유 계정명은 회사를 특정할 수 있어 쓰지 않는다.
"""

NONSTD = "-표준계정코드 미사용-"

# ---------------------------------------------------------------------------
# 개념 정의
#   alts : 후보 묶음 리스트. 앞에서부터 보고, 묶음 안에 있는 ID가 하나라도 있으면
#          그 묶음에서 찾은 행을 모두 더한다(뒤 묶음은 보지 않음).
#   names: 표준 ID가 없는 행일 때 쓸 계정명(공백 제거 후 일치)
#   amb  : 유동/비유동 구분이 없는 ID. 재무상태표 안의 위치(section)가 같을 때만 사용
#   show : always = 항상 표시, material = 자산총계 대비 5% 이상인 해만 표시(화면 단계에서 판단)
# ---------------------------------------------------------------------------
BS_TOTALS = {
    "current_assets": "ifrs-full_CurrentAssets",
    "noncurrent_assets": "ifrs-full_NoncurrentAssets",
    "assets": "ifrs-full_Assets",
    "current_liabilities": "ifrs-full_CurrentLiabilities",
    "noncurrent_liabilities": "ifrs-full_NoncurrentLiabilities",
    "liabilities": "ifrs-full_Liabilities",
    "equity": "ifrs-full_Equity",
    "equity_owners": "ifrs-full_EquityAttributableToOwnersOfParent",
}

BS_ITEMS = {
    "current_assets": [
        dict(key="cash", label="현금및현금성자산", show="always",
             alts=[["ifrs-full_CashAndCashEquivalents"]], names=["현금및현금성자산"]),
        dict(key="st_fin_assets", label="단기금융자산", show="always",
             alts=[["ifrs-full_ShorttermDepositsNotClassifiedAsCashEquivalents",
                    "ifrs-full_OtherCurrentFinancialAssets",
                    "ifrs-full_CurrentFinancialAssetsAtFairValueThroughProfitOrLoss",
                    "ifrs-full_CurrentFinancialAssetsAtFairValueThroughProfitOrLossMandatorilyMeasuredAtFairValue",
                    "ifrs-full_CurrentFinancialAssetsAtFairValueThroughProfitOrLossDesignatedUponInitialRecognition",
                    "ifrs-full_CurrentFinancialAssetsAtAmortisedCost",
                    "ifrs-full_CurrentFinancialAssetsMeasuredAtFairValueThroughOtherComprehensiveIncome",
                    "ifrs-full_CurrentFinancialAssetsAtFairValueThroughOtherComprehensiveIncome",
                    "ifrs-full_CurrentFinancialAssets", "ifrs-full_CurrentInvestments",
                    "dart_CurrentFinancialAssetsHeldToMaturity"]],
             amb=["ifrs-full_FinancialAssetsAtFairValueThroughProfitOrLoss",
                  "ifrs-full_FinancialAssetsAtFairValueThroughOtherComprehensiveIncome",
                  "ifrs-full_FinancialAssetsAtAmortisedCost", "ifrs-full_OtherFinancialAssets"],
             names=["단기금융상품"]),
        dict(key="receivables", label="매출채권", show="always",
             alts=[["ifrs-full_TradeAndOtherCurrentReceivables"], ["ifrs-full_CurrentTradeReceivables"],
                   ["dart_ShortTermTradeReceivable"]],
             amb=["ifrs-full_TradeReceivables"], names=["매출채권", "매출채권및기타채권"]),
        dict(key="inventories", label="재고자산", show="always",
             alts=[["ifrs-full_Inventories"], ["ifrs-full_InventoriesTotal"]],   # InventoriesTotal: 84개사 (2026-11-26)
             names=["재고자산"]),
        dict(key="contract_assets", label="계약자산", show="material",
             alts=[["ifrs-full_CurrentContractAssets"]], names=["계약자산"]),
    ],
    "noncurrent_assets": [
        dict(key="ppe", label="유형자산", show="always",
             alts=[["ifrs-full_PropertyPlantAndEquipment"]], names=["유형자산"]),
        dict(key="intangibles", label="무형자산(영업권 포함)", show="material",
             alts=[["ifrs-full_IntangibleAssetsAndGoodwill"],
                   ["ifrs-full_IntangibleAssetsOtherThanGoodwill", "ifrs-full_Goodwill",
                    "dart_GoodwillGross", "dart_OtherIntangibleAssetsGross"]],
             names=["무형자산", "영업권"]),
        dict(key="rou", label="사용권자산", show="material",
             alts=[["ifrs-full_RightofuseAssets"]], names=["사용권자산"]),
        dict(key="inv_property", label="투자부동산", show="material",
             alts=[["ifrs-full_InvestmentProperty"]], names=["투자부동산"]),
        dict(key="equity_investments", label="관계·종속기업 투자", show="material",
             alts=[["ifrs-full_InvestmentAccountedForUsingEquityMethod"],
                   ["ifrs-full_InvestmentsInAssociates", "ifrs-full_InvestmentsInJointVentures",
                    "ifrs-full_InvestmentsInAssociatesAccountedForUsingEquityMethod",
                    "ifrs-full_InvestmentsInJointVenturesAccountedForUsingEquityMethod",
                    "ifrs-full_InvestmentsInSubsidiariesJointVenturesAndAssociates",
                    "ifrs-full_InvestmentsInSubsidiaries"]],
             names=["관계기업투자", "종속기업투자"]),
        dict(key="lt_fin_assets", label="장기금융자산", show="material",
             alts=[["ifrs-full_OtherNoncurrentFinancialAssets",
                    "dart_LongTermDepositsNotClassifiedAsCashEquivalents",
                    "ifrs-full_NoncurrentFinancialAssetsMeasuredAtFairValueThroughOtherComprehensiveIncome",
                    "ifrs-full_NoncurrentFinancialAssetsAtFairValueThroughOtherComprehensiveIncome",
                    "ifrs-full_NoncurrentFinancialAssetsAtFairValueThroughProfitOrLoss",
                    "ifrs-full_NoncurrentFinancialAssetsAtFairValueThroughProfitOrLossDesignatedUponInitialRecognition",
                    "ifrs-full_NoncurrentFinancialAssetsAtFairValueThroughProfitOrLossMandatorilyMeasuredAtFairValue",
                    "ifrs-full_NoncurrentInvestmentsInEquityInstrumentsDesignatedAtFairValueThroughOtherComprehensiveIncome",
                    "ifrs-full_NoncurrentFinancialAssetsAtAmortisedCost", "ifrs-full_NoncurrentFinancialAssets",
                    "ifrs-full_NoncurrentFinancialAssetsAvailableforsale",
                    "dart_NonCurrentAvailableForSaleFinancialAssets", "dart_NonCurrentFairValueFinancialAsset",
                    "dart_NonCurrentFinancialAssetsHeldToMaturity",
                    "ifrs-full_NoncurrentInvestmentsOtherThanInvestmentsAccountedForUsingEquityMethod"]],
             amb=["ifrs-full_FinancialAssetsAtFairValueThroughProfitOrLoss",
                  "ifrs-full_FinancialAssetsAtFairValueThroughOtherComprehensiveIncome",
                  "ifrs-full_FinancialAssetsAtAmortisedCost", "ifrs-full_OtherFinancialAssets"],
             names=["장기금융상품"]),
        dict(key="dta", label="이연법인세자산", show="material",
             alts=[["ifrs-full_DeferredTaxAssets"], ["ifrs-full_NetDeferredTaxAssets"]],
             names=["이연법인세자산"]),
    ],
    "current_liabilities": [
        dict(key="payables", label="매입채무", show="always",
             alts=[["ifrs-full_TradeAndOtherCurrentPayables"],
                   ["ifrs-full_TradeAndOtherCurrentPayablesToTradeSuppliers"],
                   ["dart_ShortTermTradePayables"], ["ifrs-full_TradeAndOtherPayablesToTradeSuppliers"]],
             names=["매입채무", "매입채무및기타채무"]),
        dict(key="st_borrowings", label="단기차입금(유동성사채 포함)", show="always",
             alts=[["ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"],
                   ["ifrs-full_ShorttermBorrowings", "ifrs-full_CurrentPortionOfLongtermBorrowings",
                    "ifrs-full_CurrentLoansReceivedAndCurrentPortionOfNoncurrentLoansReceived",
                    "ifrs-full_CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued",
                    "ifrs-full_OtherCurrentBorrowingsAndCurrentPortionOfOtherNoncurrentBorrowings",
                    "dart_CurrentPortionOfConvertibleBonds", "dart_CurrentPortionOfBonds",
                    # 2026-11-26 추가: 유동성 BW·EB·사채, 금융기관 차입금(DART 확장 ID)
                    "dart_CurrentPortionOfBondWithWarrant", "dart_CurrentPortionOfExchangeableBond",
                    "dart_CurrentBondsIssued", "dart_CurrentPortionOfNoncurrentBondsIssued",
                    "ifrs-full_CurrentNotesAndDebenturesIssuedAndCurrentPortionOfNoncurrentNotesAndDebenturesIssued",
                    "dart_CurrentLoansReceived", "dart_CurrentPortionOfNoncurrentLoansReceived"]],
             amb=["ifrs-full_Borrowings", "ifrs-full_LoansReceived", "dart_BondWithWarrant", "dart_BondWithWarrantNet"],
             names=["단기차입금", "유동성장기차입금", "유동성장기부채", "유동성사채", "유동성전환사채",
                    "단기사채", "유동성신주인수권부사채", "유동성교환사채"]),
        dict(key="advances", label="선수금·계약부채", show="always",
             alts=[["ifrs-full_CurrentContractLiabilities", "ifrs-full_CurrentAdvances",
                    "dart_ShortTermAdvancesCustomers",
                    "ifrs-full_CurrentContractLiabilitiesForPerformanceObligationsSatisfiedOverTime"]],
             names=["선수금", "계약부채"]),
        dict(key="lease_cur", label="리스부채(유동)", show="material",
             alts=[["ifrs-full_CurrentLeaseLiabilities"], ["dart_CurentPortionOfFinanceLeaseLiabilities"]],
             amb=["ifrs-full_LeaseLiabilities"], names=["유동리스부채", "리스부채"]),
        dict(key="provisions_cur", label="충당부채(유동)", show="material",
             alts=[["ifrs-full_CurrentProvisions"],
                   ["ifrs-full_OtherShorttermProvisions", "dart_CurrentProvisionsForProductWarranties",
                    "dart_CurrentProvisionsForConstructionWarranties",
                    "ifrs-full_ShorttermMiscellaneousOtherProvisions",
                    "ifrs-full_CurrentProvisionsForEmployeeBenefits"]],
             names=["유동충당부채", "충당부채"]),
    ],
    "noncurrent_liabilities": [
        dict(key="lt_borrowings", label="장기차입금", show="always",
             alts=[["ifrs-full_LongtermBorrowings"], ["dart_LongTermBorrowingsGross"],
                   ["ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived",
                    "ifrs-full_NoncurrentPortionOfOtherNoncurrentBorrowings"]],
             amb=["ifrs-full_Borrowings", "ifrs-full_LoansReceived"], names=["장기차입금"]),
        dict(key="bonds", label="사채(CB 포함)", show="always",
             alts=[["ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued", "dart_ConvertibleBonds",
                    "dart_ConvertibleBondsNet", "dart_ExchangeableBonds", "dart_ExchangeableBondsNet",
                    "dart_BondsIssuedNominalValue", "dart_HybridBonds",
                    # 2026-11-26 추가
                    "ifrs-full_NoncurrentPortionOfNoncurrentNotesAndDebenturesIssued", "dart_NoncurrentBondsIssued"]],
             amb=["ifrs-full_BondsIssued", "dart_BondWithWarrant", "dart_BondWithWarrantNet"],   # BW는 위치(유동/비유동)로 판단
             names=["사채", "전환사채", "신주인수권부사채", "교환사채"]),
        dict(key="lease_nc", label="리스부채(비유동)", show="material",
             alts=[["ifrs-full_NoncurrentLeaseLiabilities"], ["dart_NonCurrentFinanceLeaseLiabilities"]],
             amb=["ifrs-full_LeaseLiabilities"], names=["비유동리스부채", "리스부채"]),
        dict(key="retirement", label="퇴직급여부채", show="material",
             alts=[["ifrs-full_NoncurrentRecognisedLiabilitiesDefinedBenefitPlan"],
                   ["dart_PostemploymentBenefitObligations"],
                   ["ifrs-full_RecognisedLiabilitiesDefinedBenefitPlan"],
                   ["ifrs-full_NoncurrentProvisionsForEmployeeBenefits"]],
             names=["순확정급여부채", "퇴직급여부채", "확정급여부채"]),
        dict(key="dtl", label="이연법인세부채", show="material",
             alts=[["ifrs-full_DeferredTaxLiabilities"], ["ifrs-full_NetDeferredTaxLiabilities"]],
             names=["이연법인세부채"]),
    ],
}

PL_ITEMS = [
    dict(key="revenue", label="매출액", alts=[["ifrs-full_Revenue"]],
         names=["매출액", "수익(매출액)", "영업수익", "매출"]),
    dict(key="cost_of_sales", label="매출원가", alts=[["ifrs-full_CostOfSales"]], names=["매출원가"]),
    dict(key="gross_profit", label="매출총이익", alts=[["ifrs-full_GrossProfit"]],
         names=["매출총이익", "매출총이익(손실)"]),
    dict(key="sga", label="판매비와관리비", alts=[["dart_TotalSellingGeneralAdministrativeExpenses"]],
         names=["판매비와관리비"]),
    dict(key="operating_income", label="영업이익", alts=[["dart_OperatingIncomeLoss"]],
         names=["영업이익", "영업이익(손실)", "영업손익"]),
    dict(key="other_gains", label="기타수익", alts=[["dart_OtherGains"], ["dart_NonOperatingIncome"]],
         names=["기타수익", "기타영업외수익", "영업외수익"]),
    dict(key="other_losses", label="기타비용", alts=[["dart_OtherLosses"], ["dart_NonOperatingExpense"]],
         names=["기타비용", "기타영업외비용", "영업외비용"]),
    dict(key="finance_income", label="금융수익", alts=[["ifrs-full_FinanceIncome"]], names=["금융수익"]),
    dict(key="finance_costs", label="금융비용", alts=[["ifrs-full_FinanceCosts"]],
         names=["금융비용", "금융원가"]),
    dict(key="equity_method_pl", label="지분법손익",
         alts=[["ifrs-full_ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod"],
               ["dart_ProfitsOfAssociatesAndJointVenturesAccountedForUsingEquityMethod"]],
         names=["지분법이익", "지분법손익", "지분법손실"]),
    dict(key="pretax", label="법인세비용차감전순이익", alts=[["ifrs-full_ProfitLossBeforeTax"]],
         names=["법인세비용차감전순이익", "법인세비용차감전순이익(손실)"]),
    dict(key="income_tax", label="법인세비용", alts=[["ifrs-full_IncomeTaxExpenseContinuingOperations"]],
         names=["법인세비용", "법인세비용(수익)"]),
    dict(key="net_income", label="당기순이익", alts=[["ifrs-full_ProfitLoss"]],
         names=["당기순이익", "당기순이익(손실)", "분기순이익", "분기순이익(손실)",
                "반기순이익", "반기순이익(손실)"]),
    dict(key="net_income_owners", label="지배주주 순이익",
         alts=[["ifrs-full_ProfitLossAttributableToOwnersOfParent"]], names=[]),
]

CF_ITEMS = [
    dict(key="operating_cf", label="영업활동현금흐름",
         alts=[["ifrs-full_CashFlowsFromUsedInOperatingActivities"]], names=["영업활동현금흐름"]),
    dict(key="investing_cf", label="투자활동현금흐름",
         alts=[["ifrs-full_CashFlowsFromUsedInInvestingActivities"]],
         names=["투자활동현금흐름", "투자활동으로인한현금흐름"]),
    dict(key="capex", label="유형자산 취득",  # 회사마다 부호가 달라서 extract()에서 음수로 통일
         alts=[["ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"]],
         names=["유형자산의취득", "투자활동으로분류된유형자산의취득"]),
    dict(key="financing_cf", label="재무활동현금흐름",
         alts=[["ifrs-full_CashFlowsFromUsedInFinancingActivities"]],
         names=["재무활동현금흐름", "재무활동으로인한현금흐름"]),
    dict(key="cash_change", label="현금 순증감",
         alts=[["ifrs-full_IncreaseDecreaseInCashAndCashEquivalents"],
               ["ifrs-full_IncreaseDecreaseInCashAndCashEquivalentsBeforeEffectOfExchangeRateChanges"]],
         names=["현금및현금성자산의순증가(감소)", "현금및현금성자산의순증감", "현금의증가(감소)"]),
]

SECTION_HEADS = {
    "ifrs-full_CurrentAssets": "current_assets",
    "ifrs-full_NoncurrentAssets": "noncurrent_assets",
    "ifrs-full_CurrentLiabilities": "current_liabilities",
    "ifrs-full_NoncurrentLiabilities": "noncurrent_liabilities",
    "ifrs-full_Equity": None,
    "ifrs-full_EquityAttributableToOwnersOfParent": None,
    "ifrs-full_EquityAndLiabilities": None,
}

# 기간별로 읽을 필드
ANNUAL = {"bs": ["bfefrmtrm_amount", "frmtrm_amount", "thstrm_amount"],
          "pl": ["bfefrmtrm_amount", "frmtrm_amount", "thstrm_amount"],
          "cf": ["bfefrmtrm_amount", "frmtrm_amount", "thstrm_amount"]}
# 분기·반기: [전년 동기 누적, 당기 누적], 재무상태는 [분기말]
QUARTER = {"bs": ["thstrm_amount"],
           "pl": ["frmtrm_add_amount", "thstrm_add_amount"],
           "cf": ["frmtrm_amount", "thstrm_amount"]}


def to_int(s):
    s = (s or "").replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _norm(name):
    return "".join((name or "").split())


def _top_level(rows):
    return [r for r in rows if (r.get("account_detail") or "-") in ("-", "")]


def _assign_sections(bs_rows):
    """재무상태표를 ord 순으로 훑어 각 행이 어느 소계 아래 있는지 표시한다(애매한 ID 판단용)."""
    sec, out = None, {}
    for r in sorted(bs_rows, key=lambda r: int(r.get("ord") or 0)):
        aid = r["account_id"]
        if aid in SECTION_HEADS:
            sec = SECTION_HEADS[aid]
            continue
        out[id(r)] = sec
    return out


def _pick(rows, spec, used, section=None, sections=None):
    """개념 하나에 해당하는 행 목록을 고른다. 이미 다른 개념에 쓰인 행은 건너뛴다."""
    by_id = {}
    for r in rows:
        if id(r) not in used:
            by_id.setdefault(r["account_id"], r)  # 같은 ID가 여러 번이면 첫 행
    for alt in spec["alts"]:
        hits = [by_id[a] for a in alt if a in by_id]
        if hits:
            break
    else:
        hits = []
    if section and sections is not None:
        hits += [by_id[a] for a in spec.get("amb", []) if a in by_id and sections.get(id(by_id[a])) == section]
    if not hits and spec.get("names"):
        names = {_norm(n) for n in spec["names"]}
        cand = [r for r in rows if id(r) not in used and r["account_id"] == NONSTD and _norm(r["account_nm"]) in names]
        if section and sections is not None:
            cand = [r for r in cand if sections.get(id(r)) in (section, None)]
        hits = cand
    return hits


def _values(hits, fields):
    if not hits:
        return None
    out = []
    for f in fields:
        vals = [to_int(r.get(f)) for r in hits]
        out.append(None if all(v is None for v in vals) else sum(v or 0 for v in vals))
    return out


def extract(rows, periods):
    """rows: fnlttSinglAcntAll 응답의 list. periods: ANNUAL 또는 QUARTER.
    반환: {"bs": {key: [..]}, "pl": {...}, "cf": {...}, "pl_source": "IS"|"CIS"}"""
    rows = _top_level(rows)
    bs = [r for r in rows if r["sj_div"] == "BS"]
    pl_src = "IS" if any(r["sj_div"] == "IS" for r in rows) else "CIS"
    pl = [r for r in rows if r["sj_div"] == pl_src]
    cf = [r for r in rows if r["sj_div"] == "CF"]

    out = {"bs": {}, "pl": {}, "cf": {}, "pl_source": pl_src}

    used = set()
    for key, aid in BS_TOTALS.items():
        hit = next((r for r in bs if r["account_id"] == aid), None)
        out["bs"][key] = _values([hit] if hit else [], periods["bs"])
        if hit:
            used.add(id(hit))
    sections = _assign_sections(bs)
    for section, specs in BS_ITEMS.items():
        for spec in specs:
            hits = _pick(bs, spec, used, section, sections)
            used.update(id(h) for h in hits)
            out["bs"][spec["key"]] = _values(hits, periods["bs"])

    for specs, src, dst in ((PL_ITEMS, pl, "pl"), (CF_ITEMS, cf, "cf")):
        used = set()
        for spec in specs:
            hits = _pick(src, spec, used)
            used.update(id(h) for h in hits)
            out[dst][spec["key"]] = _values(hits, periods[dst])

    # 유형자산 취득(현금 유출)은 회사마다 양수/음수 표기가 섞여 있어 음수로 통일
    if out["cf"].get("capex"):
        out["cf"]["capex"] = [None if v is None else -abs(v) for v in out["cf"]["capex"]]

    # 매출총이익이 없으면 매출액 - 매출원가로 계산 (둘 다 있을 때만)
    p = out["pl"]
    if p["gross_profit"] is None and p["revenue"] and p["cost_of_sales"]:
        p["gross_profit"] = [None if a is None or b is None else a - b
                             for a, b in zip(p["revenue"], p["cost_of_sales"])]
        out["gross_profit_computed"] = True
    # 판관비가 표준 ID로 없으면 매출총이익 - 영업이익으로 계산
    if p["sga"] is None and p["gross_profit"] and p["operating_income"]:
        p["sga"] = [None if a is None or b is None else a - b
                    for a, b in zip(p["gross_profit"], p["operating_income"])]
        out["sga_computed"] = True

    # 재무상태표 세부 검증: 항목 합이 소계를 1% 넘게 초과하면 회사 원본 데이터가
    # 중복·불일치인 경우라 세부를 믿을 수 없음 → 오늘의 문제 출제에서 제외할 때 사용
    out["bs_detail_ok"] = True
    for section, specs in BS_ITEMS.items():
        tot = out["bs"].get(section) or []
        for i, t in enumerate(tot):
            if t is None:
                continue
            s = sum(((out["bs"][sp["key"]] or [])[i:i + 1] or [0])[0] or 0 for sp in specs)
            if s - t > 0.01 * abs(t) + 1e8:
                out["bs_detail_ok"] = False
    return out
