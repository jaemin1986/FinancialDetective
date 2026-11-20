/* FinancialDetective — 화면 동작
 * 연습 모드: pool/index.json + pool/pNNN.json (정답 인코딩, 브라우저에서 판정, 랭킹 반영 안 함)
 * 오늘의 문제: daily/YYYY-MM-DD.json (정답 없음) + Supabase RPC (판정·점수·랭킹은 서버)
 * 금액은 원 단위 정수로 오고, 화면에는 억원(천 단위 콤마)으로 표시한다.
 */
"use strict";

const XOR_KEY = new TextEncoder().encode("FinancialDetective-practice"); // build_quiz.py와 동일 (보안 목적 아님)
const COMPANY_POINTS = [40, 20];            // 1번째, 2번째에 맞힘
const MCAP_POINTS = [60, 48, 36, 24, 12];   // 1~5번째에 맞힘
const MAX_COMPANY_TRIES = 2;
const MAX_GUESSES = 5;
const TOLERANCE = 0.10;
const BONUS_TOLERANCE = 0.03;               // 맞힌 입력의 오차율이 3% 이내면
const BONUS_POINTS = 10;                    // 정확도 보너스 (만점 110)
const SESSION_KEY = "fd_session";

const $ = (id) => document.getElementById(id);
const state = {
  index: null, queue: [], usedChunks: new Set(),   // 연습 풀
  session: null,                                    // {token, nickname}
  game: null,                                       // 진행 중인 문제 (연습·오늘 공용)
};

/* ---------------- 숫자 표시 ---------------- */
const nf = new Intl.NumberFormat("ko-KR");
function eok(won) {
  if (won === null || won === undefined) return "-";
  return nf.format(Math.round(won / 1e8));
}
function pct(v) { return v === null || v === undefined ? "-" : `${v.toFixed(1)}%`; }
function prettyEok(x) {               // 억원 → "1조 2,345억"
  if (!isFinite(x) || x <= 0) return "";
  const jo = Math.floor(x / 10000);
  const rest = Math.round(x - jo * 10000);
  if (jo === 0) return `${nf.format(rest)}억`;
  return rest ? `${nf.format(jo)}조 ${nf.format(rest)}억` : `${nf.format(jo)}조`;
}
function fmtDate(basDt) { return `${basDt.slice(0, 4)}-${basDt.slice(4, 6)}-${basDt.slice(6, 8)}`; }

/* ---------------- 정답 디코딩 (base64 + XOR) ---------------- */
function decode(s) {
  const bin = atob(s);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i) ^ XOR_KEY[i % XOR_KEY.length];
  return JSON.parse(new TextDecoder().decode(bytes));
}

/* ---------------- 문제 불러오기 ---------------- */
async function loadIndex() {
  const res = await fetch("pool/index.json", { cache: "no-cache" });
  if (!res.ok) throw new Error("index");
  state.index = await res.json();
}
async function refillQueue() {
  const n = state.index.chunks;
  if (state.usedChunks.size >= n) state.usedChunks.clear();
  let k;
  do { k = Math.floor(Math.random() * n); } while (state.usedChunks.has(k));
  state.usedChunks.add(k);
  const res = await fetch(`pool/p${String(k).padStart(3, "0")}.json`);
  const qs = await res.json();
  for (let i = qs.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [qs[i], qs[j]] = [qs[j], qs[i]]; }
  state.queue.push(...qs);
}

/* ---------------- 재무표 그리기 (탭: 손익 / 재무상태 / 현금·비율) ---------------- */
const TAB_OF = { "손익계산서": "손익", "재무상태표": "재무상태", "현금흐름": "현금·비율", "주요 비율": "현금·비율" };

function renderStatement(st, target) {
  const tabs = [];
  for (const sec of st.sections) {
    const name = TAB_OF[sec.title] || sec.title;
    let t = tabs.find((x) => x.name === name);
    if (!t) tabs.push((t = { name, sections: [] }));
    t.sections.push(sec);
  }
  target.innerHTML = `<div class="tabs">${tabs.map((t, i) =>
      `<button type="button" class="tab" data-i="${i}">${t.name}</button>`).join("")}</div>
    <div class="tab-body"></div>`;
  const bodyEl = target.querySelector(".tab-body");
  const select = (i) => {
    target.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", Number(b.dataset.i) === i));
    const ttm = st.ttm || null;  // 최신 분기 데이터가 없는 회사는 연간 3개년만
    const secs = tabs[i].sections;
    let html = tableHtml(st, secs, ttm);
    if (secs.some((s) => s.title === "손익계산서")) html += cumHtml(st, ttm);
    bodyEl.innerHTML = html;
  };
  target.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => select(Number(b.dataset.i))));
  select(0);
}

// ttm: 있으면 연간 3개년 뒤에 최신 분기 열을 붙인다.
//  손익·현금흐름 = 올해 누적(예: 1~9월), 비율 = 누적 기준, 재무상태 = 분기말 잔액.
//  실제 값은 각 행 v의 4번째 값. 미리보기(st.ttm 없음)면 빈 칸(·).
function tableHtml(st, sections, ttm) {
  const n = st.years.length;
  const isBs = sections.every((s) => s.title === "재무상태표");
  // 숫자 열은 모두 같은 너비 (항목명 칸은 CSS에서 글자 길이만큼)
  const w = `style="width:${(99 / (n + (ttm ? 1 : 0))).toFixed(1)}%"`;
  const ttmHead = ttm
    ? `<th class="ttm" ${w}>${ttm.label}<br><small>${isBs ? ttm.bsDate : ttm.period}</small></th>` : "";
  const head = `<tr><th></th>${st.years.map((y) => `<th ${w}>${y}</th>`).join("")}${ttmHead}</tr>`;
  const body = sections.map((sec) => {
    const secRow = sections.length > 1
      ? `<tr class="sec"><td class="label" colspan="${n + 1 + (ttm ? 1 : 0)}">${sec.title}</td></tr>` : "";
    const rows = sec.rows.map(([label, level, kind, v]) => {
      const vals = (v || []).slice(0, n);
      while (vals.length < n) vals.push(null);
      const cell = (x, extra = "") => {
        const txt = kind === "pct" ? pct(x) : eok(x);
        const neg = x !== null && x !== undefined && x < 0 ? " neg" : "";
        return `<td class="num${neg}${extra}">${txt}</td>`;
      };
      let cells = vals.map((x) => cell(x)).join("");
      if (ttm) cells += cell(v ? v[n] : null, " ttm");
      const cls = [kind === "sub" ? "sub" : "", kind === "total" ? "total" : "", level ? "lv1" : ""].join(" ");
      return `<tr class="${cls}"><td class="label">${label}</td>${cells}</tr>`;
    }).join("");
    return secRow + rows;
  }).join("");
  return `<div class="tbl-wrap"><table class="fin">${head}${body}</table></div>`;
}

// 보조 표: 올해 누적 vs 전년 동기 누적. st.cum = {revenue:[전년,올해], operating_income:[..], net_income:[..]}
function cumHtml(st, ttm) {
  if (!ttm) return "";
  const items = [["매출액", "revenue"], ["영업이익", "operating_income"], ["당기순이익", "net_income"]];
  const rows = items.map(([label, k]) => {
    const v = st.cum ? st.cum[k] : null;
    if (!v) return `<tr><td class="label">${label}</td><td class="num ph">·</td><td class="num ph">·</td><td class="num ph">·</td></tr>`;
    const [a, b] = v;
    const g = a && b !== null ? ((b - a) / Math.abs(a)) * 100 : null;
    const neg = (x) => (x !== null && x < 0 ? " neg" : "");
    return `<tr><td class="label">${label}</td><td class="num${neg(a)}">${eok(a)}</td>
      <td class="num${neg(b)}">${eok(b)}</td><td class="num${neg(g)}">${pct(g)}</td></tr>`;
  }).join("");
  return `<p class="cum-title">누적 실적 비교</p>
    <div class="tbl-wrap"><table class="fin cum"><tr><th></th><th>${ttm.cumLabel[0]}</th>
    <th>${ttm.cumLabel[1]}</th><th>증감률</th></tr>${rows}</table></div>`;
}

/* ---------------- 보기 4개 비교 (정답 공개 후) ---------------- */
function renderCompare(list, answerIdx) {
  // 정답 회사를 맨 위로, 나머지는 원래 보기 순서대로
  const order = [answerIdx, ...list.map((_, i) => i).filter((i) => i !== answerIdx)];
  const cards = order.map((i) => list[i]).map((r, k) => {
    const i = order[k];
    const mult = (x, d, why) => (x === null || x === undefined ? (r.rows ? why : "-") : x.toFixed(d));
    const fs = r.fs_div ? `<span class="tag">${r.fs_div === "CFS" ? "연결" : "별도"}</span>` : "";
    const key = `<div class="keystats">
        <div><span>시가총액</span><b>${eok(r.mcap)}</b></div>
        <div><span>${r.per_label || "PER"}</span><b>${mult(r.per, 1, "적자")}</b></div>
        <div><span>${r.pbr_label || "PBR"}</span><b>${mult(r.pbr, 2, "잠식")}</b></div></div>`;
    // 회사명·업종 부분을 누르면 DART 최근 보고서를 새 탭으로 (이 화면은 그대로 남음)
    const rcp = r.dart && /^\d{14}$/.test(r.dart.rcept_no) ? r.dart.rcept_no : "";
    const dartOpen = rcp ? `<a class="dart-link" href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${rcp}" target="_blank" rel="noopener">` : "";
    const dartClose = rcp ? "</a>" : "";
    const dartNote = rcp ? ` <span class="dart-note">· DART ${esc(r.dart.label)} ↗</span>` : "";
    const table = r.rows
      ? tableHtml({ years: r.years, ttm: r.ttm }, [{ title: "", rows: r.rows }], r.ttm || null)
      : `<p class="muted small">재무 데이터 없음</p>`;
    return `<div class="cmp-card${i === answerIdx ? " answer" : ""}">
      ${dartOpen}<div class="cmp-head"><span class="cmp-name">${i === answerIdx ? "★ " : ""}${r.name}</span>
        <span class="tags">${fs}<span class="tag">${r.market}</span></span></div>
      <div class="industry">${r.industry || r.industry_code}${dartNote}</div>${dartClose}
      ${key}${table}
    </div>`;
  }).join("");
  $("compare").innerHTML = cards;
}

/* ---------------- Supabase RPC ---------------- */
const CFG = window.FD_CONFIG || {};
const sb = window.supabase && CFG.SUPABASE_URL
  ? window.supabase.createClient(CFG.SUPABASE_URL, CFG.SUPABASE_ANON_KEY, { auth: { persistSession: false } })
  : null;

async function rpc(fn, params) {
  if (!sb) throw new Error("서버 설정(config.js)을 찾지 못했어요");
  const { data, error } = await sb.rpc(fn, params);
  if (error) throw new Error(error.message || "서버 오류");
  return data;
}

const ERR = {
  WRONG_CODE: "팀 코드를 확인해 주세요",
  NOT_CONFIGURED: "팀 코드가 아직 설정되지 않았어요 (관리자에게 문의)",
  LENGTH: "2~10자로 정해 주세요",
  CHARS: "한글·영문·숫자·밑줄(_)만 쓸 수 있어요 (공백·이모지 불가)",
  BANNED: "쓸 수 없는 단어가 들어 있어요",
  TAKEN: "이미 있는 닉네임이에요",
  PIN_FORMAT: "PIN은 숫자 4자리예요",
  SIGNUP_EXPIRED: "가입 시간(10분)이 지났어요. 팀 코드부터 다시 입력해 주세요",
  WRONG_LOGIN: "닉네임 또는 PIN이 맞지 않아요",
  WRONG_PIN: "현재 PIN이 맞지 않아요",
  SESSION_EXPIRED: "로그인이 만료됐어요. 다시 로그인해 주세요",
  PIN_CHANGE_REQUIRED: "임시 PIN을 받았어요. 새 PIN으로 바꿔 주세요",
  NO_QUIZ: "오늘의 문제가 아직 준비되지 않았어요",
  TOO_SOON: "닉네임은 30일에 한 번 바꿀 수 있어요",
  COMPANY_DONE: "이미 회사를 골랐어요",
  BAD_CHOICE: "이미 고른 보기예요",
  COMPANY_NOT_DONE: "회사부터 골라 주세요",
  FINISHED: "이미 끝난 문제예요",
  BAD_AMOUNT: "금액(억원)을 확인해 주세요",
};
function errMsg(r) {
  if (r.error === "LOCKED") return `여러 번 틀려서 잠겼어요. ${Math.ceil((r.wait_seconds || 600) / 60)}분 뒤에 다시 시도해 주세요`;
  if (r.error === "TOO_SOON" && r.available_at) return `${ERR.TOO_SOON} (${r.available_at.slice(0, 10)}부터 가능)`;
  return ERR[r.error] || `오류: ${r.error}`;
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
// 공통 오류 처리: 세션 만료·PIN 변경 필요는 해당 화면으로
function handleErr(r) {
  if (r.error === "SESSION_EXPIRED") { clearSession(); toast(ERR.SESSION_EXPIRED); goHome(); return; }
  if (r.error === "PIN_CHANGE_REQUIRED") { openPin(true); return; }
  toast(errMsg(r));
}

/* ---------------- 로그인 상태 (브라우저에는 세션 토큰만 저장) ---------------- */
function loadSession() {
  try { state.session = JSON.parse(localStorage.getItem(SESSION_KEY)); } catch { state.session = null; }
}
function saveSession(token, nickname) {
  state.session = { token, nickname };
  localStorage.setItem(SESSION_KEY, JSON.stringify(state.session));
  updateHeader();
}
function clearSession() {
  state.session = null;
  localStorage.removeItem(SESSION_KEY);
  updateHeader();
}
function updateHeader(modeText) {
  const me = $("btnMe");
  me.hidden = !state.session;
  if (state.session) me.textContent = `${state.session.nickname} ⚙`;
  $("modeLabel").hidden = !modeText;
  $("modeLabel").textContent = modeText || "";
}

/* ---------------- 날짜 (KST 'YYYY-MM-DD') ---------------- */
// 오늘의 문제 날짜: 하루의 경계는 새벽 3시 KST (서버 private.kst_today와 같음)
const DAY_START_HOUR = 3;
function kstToday() {
  return new Date(Date.now() + (9 - DAY_START_HOUR) * 3600e3).toISOString().slice(0, 10);
}
function addDays(d, n) {
  const t = new Date(`${d}T00:00:00Z`);
  t.setUTCDate(t.getUTCDate() + n);
  return t.toISOString().slice(0, 10);
}

/* ---------------- 화면 전환 ---------------- */
function show(id, modeText) {
  for (const s of document.querySelectorAll(".screen")) s.hidden = s.id !== id;
  updateHeader(modeText);
  window.scrollTo(0, 0);
}

/* ---------------- 시작 화면 ---------------- */
async function goHome() {
  show("screenStart");
  $("startGuest").hidden = !!state.session;
  $("startMember").hidden = !state.session;
  if (!state.session) return;
  $("helloName").textContent = state.session.nickname;
  $("todayInfo").textContent = `${kstToday()} · 하루 3문제 · 새벽 3시에 새 문제 · 한 번 낸 답은 되돌릴 수 없어요`;
  $("btnDaily").textContent = "오늘의 문제 풀기";
  $("myStats").innerHTML = "";
  try {
    const h = await rpc("get_my_history", { token: state.session.token });
    if (!h.ok) return handleErr(h);
    renderStats(h);
  } catch (e) { /* 통계는 못 불러와도 진행 */ }
}

// streak·누적 정답률은 서버 기록(plays)으로 계산 → 기기를 바꿔도 유지
// rows: 날짜별 {score(합계), solved(끝낸 문제 수), questions(그날 문제 수), company_ok, mcap_hits}
function renderStats(h) {
  const done = h.rows.filter((r) => r.solved >= r.questions);       // 그날 문제를 다 푼 날
  const todayRow = h.rows.find((r) => r.quiz_date === h.today);
  if (todayRow && todayRow.solved >= todayRow.questions) {
    $("btnDaily").textContent = "오늘 결과 보기";
    $("todayInfo").textContent = `${h.today} · 오늘 완료: ${todayRow.score}점`;
  } else if (todayRow) {
    $("btnDaily").textContent = `오늘의 문제 이어서 풀기 (${todayRow.solved + 1}/${todayRow.questions})`;
  }
  if (!done.length) { $("myStats").innerHTML = `<p class="muted small">아직 기록이 없어요. 첫 문제를 풀어 보세요!</p>`; return; }
  const days = new Set(done.map((r) => r.quiz_date));
  let d = days.has(h.today) ? h.today : addDays(h.today, -1);
  let streak = 0;
  while (days.has(d)) { streak++; d = addDays(d, -1); }
  const nq = h.rows.reduce((s, r) => s + r.solved, 0);              // 지금까지 끝낸 문제 수
  const rate = (k) => `${Math.round((h.rows.reduce((s, r) => s + r[k], 0) / nq) * 100)}%`;
  const avg = Math.round(done.reduce((s, r) => s + (r.score || 0), 0) / done.length);
  const items = [["연속 참여", `${streak}일`], ["참여", `${done.length}일`],
                 ["회사 정답률", rate("company_ok")], ["시총 정답률", rate("mcap_hits")], ["하루 평균", `${avg}점`]];
  $("myStats").innerHTML = items.map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join("");
}

/* ---------------- 가입 (팀 코드 → 닉네임 → PIN → 확인) ---------------- */
const signup = { token: null, nick: "", pin: "" };

function signupStep(n) {
  for (let i = 1; i <= 4; i++) $(`signupStep${i}`).hidden = i !== n;
  document.querySelectorAll(".steps span").forEach((s) => s.classList.toggle("on", Number(s.dataset.s) === n));
  show("screenSignup", "가입");
  const focus = { 1: "teamCode", 2: "nickInput", 3: "pin1" }[n];
  if (focus) setTimeout(() => $(focus).focus(), 50);
}
function setMsg(id, text, ok) {
  const el = $(id);
  el.textContent = text || " ";
  el.className = `msg${ok === true ? " ok" : ok === false ? " bad" : ""}`;
}

$("signupStep1").addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = $("teamCode").value.trim();
  if (!code) return setMsg("msg1", "팀 코드를 입력해 주세요", false);
  try {
    const r = await rpc("verify_team_code", { team_code: code });
    if (!r.ok) return setMsg("msg1", errMsg(r), false);
    signup.token = r.signup_token;
    setMsg("msg1", "");
    signupStep(2);
  } catch (err) { setMsg("msg1", err.message, false); }
});

// 닉네임: 입력을 멈추고 0.5초 뒤 서버에서 중복·규칙 확인
function nickChecker(inputId, msgId, btnId) {
  let timer = null, seq = 0;
  $(inputId).addEventListener("input", () => {
    const v = $(inputId).value.trim();
    if (btnId) $(btnId).disabled = true;
    clearTimeout(timer);
    if (!v) return setMsg(msgId, "");
    setMsg(msgId, "확인 중…");
    const my = ++seq;
    timer = setTimeout(async () => {
      try {
        const r = await rpc("check_nickname", { nickname: v });
        if (my !== seq) return;          // 그사이 더 입력했으면 무시
        if (r.ok) { setMsg(msgId, "✅ 사용할 수 있어요", true); if (btnId) $(btnId).disabled = false; }
        else setMsg(msgId, `❌ ${errMsg(r)}`, false);
      } catch (err) { setMsg(msgId, err.message, false); }
    }, 500);
  });
}
nickChecker("nickInput", "msg2", "btnNick");

$("signupStep2").addEventListener("submit", (e) => {
  e.preventDefault();
  if ($("btnNick").disabled) return;
  signup.nick = $("nickInput").value.trim();
  signupStep(3);
});

$("signupStep3").addEventListener("submit", (e) => {
  e.preventDefault();
  const a = $("pin1").value, b = $("pin2").value;
  if (!/^\d{4}$/.test(a)) return setMsg("msg3", "PIN은 숫자 4자리로 정해 주세요", false);
  if (a !== b) return setMsg("msg3", "두 번 입력한 PIN이 달라요", false);
  signup.pin = a;
  setMsg("msg3", "");
  $("confirmNick").textContent = signup.nick;
  setMsg("msg4", "");
  signupStep(4);
});

$("btnSignupEdit").addEventListener("click", () => signupStep(2));
$("btnSignupGo").addEventListener("click", async () => {
  const btn = $("btnSignupGo");
  btn.disabled = true;
  try {
    const r = await rpc("register_player", { signup_token: signup.token, nickname: signup.nick, pin: signup.pin });
    if (!r.ok) {
      if (r.error === "SIGNUP_EXPIRED") { setMsg("msg1", errMsg(r), false); signupStep(1); }
      else if (r.error === "PIN_FORMAT") { setMsg("msg3", errMsg(r), false); signupStep(3); }
      else { setMsg("msg2", `❌ ${errMsg(r)}`, false); $("btnNick").disabled = true; signupStep(2); }
      return;
    }
    $("pin1").value = $("pin2").value = $("teamCode").value = "";
    signup.pin = "";
    saveSession(r.token, r.nickname);
    toast(`환영해요, ${r.nickname}님!`);
    startDaily();
  } catch (err) { setMsg("msg4", err.message, false); }
  finally { btn.disabled = false; }
});

/* ---------------- 로그인 ---------------- */
$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const nick = $("loginNick").value.trim(), pin = $("loginPin").value;
  if (!nick || !/^\d{4}$/.test(pin)) return setMsg("msgLogin", "닉네임과 PIN 4자리를 입력해 주세요", false);
  try {
    const r = await rpc("login", { nickname: nick, pin });
    if (!r.ok) return setMsg("msgLogin", errMsg(r), false);
    $("loginPin").value = "";
    setMsg("msgLogin", "");
    saveSession(r.token, r.nickname);
    if (r.must_change_pin) openPin(true);
    else { toast(`어서 오세요, ${r.nickname}님!`); goHome(); }
  } catch (err) { setMsg("msgLogin", err.message, false); }
});

/* ---------------- PIN 변경 ---------------- */
let pinForced = false;
function openPin(forced) {
  pinForced = forced;
  $("pinTitle").textContent = forced ? "새 PIN을 정해 주세요" : "PIN 변경";
  $("pinDesc").textContent = forced ? "관리자에게 받은 임시 PIN을 입력하고, 앞으로 쓸 새 PIN을 정해 주세요." : "";
  ["pinOld", "pinNew1", "pinNew2"].forEach((id) => ($(id).value = ""));
  setMsg("msgPin", "");
  show("screenPin", "PIN");
}
$("pinForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const o = $("pinOld").value, a = $("pinNew1").value, b = $("pinNew2").value;
  if (!/^\d{4}$/.test(a)) return setMsg("msgPin", "새 PIN은 숫자 4자리로 정해 주세요", false);
  if (a !== b) return setMsg("msgPin", "새 PIN 두 번 입력한 것이 달라요", false);
  try {
    const r = await rpc("change_pin", { token: state.session.token, old_pin: o, new_pin: a });
    if (!r.ok) return r.error === "SESSION_EXPIRED" ? handleErr(r) : setMsg("msgPin", errMsg(r), false);
    toast("PIN을 바꿨어요");
    goHome();
  } catch (err) { setMsg("msgPin", err.message, false); }
});

/* ---------------- 설정: 닉네임 변경·로그아웃 ---------------- */
nickChecker("newNick", "msgNick", null);
$("nickForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const v = $("newNick").value.trim();
  if (!v) return;
  try {
    const r = await rpc("change_nickname", { token: state.session.token, new_nickname: v });
    if (!r.ok) return r.error === "SESSION_EXPIRED" ? handleErr(r) : setMsg("msgNick", `❌ ${errMsg(r)}`, false);
    saveSession(state.session.token, r.nickname);
    $("newNick").value = "";
    toast(`닉네임을 「${r.nickname}」(으)로 바꿨어요`);
    goHome();
  } catch (err) { setMsg("msgNick", err.message, false); }
});
$("btnLogout").addEventListener("click", async () => {
  try { await rpc("logout", { token: state.session.token }); } catch { /* 서버 실패해도 이 기기에서는 로그아웃 */ }
  clearSession();
  toast("로그아웃했어요");
  goHome();
});

/* ---------------- 문제 진행 (연습·오늘 공용) ---------------- */
// state.game = { mode, statement, options, basDt, quizDate, choices, companyOk, companyDone,
//                answerIndex, corpName, guesses:[{x(억원), hint}], finished, score, mcap, reveal, ans(연습만) }
let busy = false;

async function nextQuestion() {
  if (!state.queue.length) await refillQueue();
  const q = state.queue.shift();
  const ans = decode(q.a);
  state.game = { mode: "practice", statement: q.statement, options: q.options, basDt: state.index.basDt,
                 choices: [], companyOk: false, companyDone: false, answerIndex: null, corpName: null,
                 guesses: [], finished: false, ans };
  renderQuiz();
}

// 서버 응답(play_state)을 화면 상태로
function applyServer(g, r) {
  Object.assign(g, {
    quizDate: r.quiz_date,
    qn: r.qn ?? 0,
    choices: r.company_choices || [],
    companyOk: !!r.company_ok,
    companyDone: !!r.company_done,
    answerIndex: r.answer_index ?? null,
    corpName: r.corp_name ?? null,
    guesses: (r.guesses || []).map((x) => ({ x: Number(x.amount_eok), hint: x.hint })),
    finished: !!r.finished,
    score: r.score ?? null,
    mcap: r.mcap ?? null,
    reveal: r.reveal ?? null,
  });
}

// 오늘의 문제: 하루 여러 문제를 순서대로. 진행 중인 문제가 있으면 이어서, 없으면 다음 문제 시작
// state.day = { quizDate, total, basDt, qs(문제 파일), finished:[끝낸 문제 game...] }
async function startDaily() {
  if (!state.session) return goHome();
  try {
    const r = await rpc("start_daily", { token: state.session.token });
    if (!r.ok) return handleErr(r);
    // 문제(재무표+보기)는 서버가 그날·순서가 된 것만 내려준다 (공개 파일 없음)
    state.day = { quizDate: r.quiz_date, total: r.total, finished: r.finished.map(dailyGame) };
    if (r.all_done) return showDayResult();
    state.game = dailyGame(r.current);
    renderQuiz();
  } catch (err) { toast(err.message); }
}
function dailyGame(st) {
  const q = st.question || { statement: { years: [], sections: [] }, options: [] };
  const g = { mode: "daily", statement: q.statement, options: q.options,
              basDt: String(st.bas_dt || "").replace(/-/g, "") };
  applyServer(g, st);
  return g;
}

function renderQuiz() {
  const g = state.game;
  $("fsDiv").textContent = g.statement.fs_div === "CFS" ? "연결" : "별도";
  $("quizTitle").textContent = g.mode === "daily"
    ? `오늘의 문제 ${g.quizDate} · ${g.qn + 1}/${state.day.total}번` : "연습";
  renderStatement(g.statement, $("statement"));
  const box = $("options");
  box.innerHTML = "";
  g.options.forEach((name, i) => {
    const b = document.createElement("button");
    b.className = "opt";
    b.textContent = `${i + 1}. ${name}`;
    b.addEventListener("click", () => pickCompany(i));
    box.appendChild(b);
  });
  renderStage1();
  $("guessInput").value = "";
  $("guessPretty").innerHTML = "&nbsp;";
  $("basDt").textContent = fmtDate(g.basDt);
  renderGuesses();
  $("stage2").hidden = !g.companyDone;
  show("screenQuiz", g.mode === "daily" ? "오늘의 문제" : "연습 모드");
}

function renderStage1() {
  const g = state.game;
  [...$("options").children].forEach((b, i) => {
    const right = g.companyDone && i === g.answerIndex;
    b.classList.toggle("right", right);
    b.classList.toggle("wrong", g.choices.includes(i) && !right);
    b.disabled = g.companyDone || g.choices.includes(i);
  });
  const pts = g.choices.length === 1 ? 40 : 20;
  $("stage1Msg").innerHTML = g.companyDone
    ? (g.companyOk ? `정답! <b>${esc(g.corpName)}</b> (+${pts})` : `정답은 <b>${esc(g.corpName)}</b>입니다.`)
    : g.choices.length ? "아쉬워요! 한 번 더 골라 보세요." : "기회 2번";
}

async function pickCompany(i) {
  const g = state.game;
  if (busy || g.companyDone || g.choices.includes(i)) return;
  if (g.mode === "practice") {
    g.choices.push(i);
    g.companyOk = i === g.ans.i;
    g.companyDone = g.companyOk || g.choices.length >= MAX_COMPANY_TRIES;
    if (g.companyDone) { g.answerIndex = g.ans.i; g.corpName = g.ans.n; }
  } else {
    busy = true;
    try {
      const r = await rpc("submit_company", { token: state.session.token, choice: i });
      if (!r.ok) return handleErr(r);
      applyServer(g, r);
    } catch (err) { return toast(err.message); }
    finally { busy = false; }
  }
  renderStage1();
  if (g.companyDone) startStage2();
}

function startStage2() {
  $("stage2").hidden = false;
  $("stage2").scrollIntoView({ behavior: "smooth", block: "start" });
  setTimeout(() => $("guessInput").focus({ preventScroll: true }), 300);
}

function parseGuess(s) {
  const x = Number(String(s).replace(/[,\s]/g, ""));
  return isFinite(x) && x > 0 ? x : null;
}

function renderGuesses() {
  const mark = { HIT: '<span class="hint-hit">✅ 정답!</span>', UP: '<span class="hint-up">UP ⬆</span>',
                 DOWN: '<span class="hint-down">DOWN ⬇</span>' };
  $("guessList").innerHTML = state.game.guesses.map((x) => `<li>${prettyEok(x.x)} → ${mark[x.hint]}</li>`).join("");
}

async function submitGuess(e) {
  e.preventDefault();
  const g = state.game;
  if (busy || g.finished || !g.companyDone) return;
  const x = parseGuess($("guessInput").value);
  if (x === null) { toast("숫자(억원)를 입력해 주세요"); return; }
  if (g.mode === "practice") {
    const actual = g.ans.m, won = x * 1e8;
    const hint = Math.abs(won - actual) / actual <= TOLERANCE ? "HIT" : actual > won ? "UP" : "DOWN";
    g.guesses.push({ x, hint });
    if (hint === "HIT" || g.guesses.length >= MAX_GUESSES) {
      Object.assign(g, { finished: true, mcap: actual, reveal: g.ans.r });
      g.score = scoreOf(g).total;
    }
  } else {
    busy = true;
    $("btnGuess").disabled = true;
    try {
      const r = await rpc("submit_guess", { token: state.session.token, amount_eok: x });
      if (!r.ok) return handleErr(r);
      applyServer(g, r);
    } catch (err) { return toast(err.message); }
    finally { busy = false; $("btnGuess").disabled = false; }
  }
  $("guessInput").value = "";
  $("guessPretty").innerHTML = "&nbsp;";
  renderGuesses();
  if (g.finished) setTimeout(showResult, 700);
  else $("guessInput").focus();
}

/* ---------------- 결과 ---------------- */
// 점수 계산 (연습용, 서버와 같은 규칙). 오늘의 문제는 서버 점수를 쓰고 보너스 표시만 여기서 계산
function scoreOf(g) {
  const c = g.companyOk ? COMPANY_POINTS[g.choices.length - 1] : 0;
  const hitAt = g.guesses.findIndex((x) => x.hint === "HIT");
  const m = hitAt >= 0 ? MCAP_POINTS[hitAt] : 0;
  const bonus = hitAt >= 0 && g.mcap && Math.abs(g.guesses[hitAt].x * 1e8 - g.mcap) / g.mcap <= BONUS_TOLERANCE
    ? BONUS_POINTS : 0;
  return { total: c + m + bonus, hitAt, bonus };
}

// 문제 하나의 요약: "✅ 3/5 ⬆⬇✅" (회사 표시 · 시총 몇 번째 · 화살표)
function questionMarks(g, withArrows = true) {
  const s = scoreOf(g);
  const comp = g.choices.map((i) => (i === g.answerIndex ? "✅" : "❌")).join("");
  const mc = s.hitAt >= 0 ? `${s.hitAt + 1}/5` : "X/5";
  const arrows = withArrows ? " " + g.guesses.map((x) => ({ HIT: "✅", UP: "⬆", DOWN: "⬇" }[x.hint])).join("") : "";
  return `회사 ${comp} | 시총 ${mc}${arrows}${s.bonus ? " 🎯+10" : ""}`;
}
function summaryLine(g) {
  return `FinancialDetective 연습 | ${g.score}점 | ${questionMarks(g)}`;
}
// 오늘의 문제 하루 요약 (카톡·슬랙 공유용, 회사명·시총 숫자 없음)
function daySummaryLine(day, rankText) {
  const total = day.finished.reduce((s, g) => s + (g.score || 0), 0);
  const per = day.finished.map((g, k) => {
    const s = scoreOf(g);
    const comp = g.choices.map((i) => (i === g.answerIndex ? "✅" : "❌")).join("");
    return `Q${k + 1} ${comp} ${s.hitAt >= 0 ? `${s.hitAt + 1}/5` : "X/5"}${s.bonus ? "🎯" : ""}`;
  }).join(" | ");
  return `FinancialDetective ${day.quizDate} | ${total}점${rankText ? " " + rankText : ""} | ${per}`;
}

// 문제 하나의 정답·보기 비교·재무제표를 결과 화면 아래쪽에 그린다
function renderReview(g) {
  $("reviewAnswer").innerHTML =
    `<b>${esc(g.corpName)}</b> · 시가총액 <b>${prettyEok(Math.round(g.mcap / 1e8))}</b> (${fmtDate(g.basDt)})` +
    ` · <b>${g.score}점</b> <span class="muted small">${esc(questionMarks(g, false))}</span>`;
  $("basDt2").textContent = fmtDate(g.basDt);
  renderCompare(g.reveal || [], g.answerIndex);
  renderStatement(g.statement, $("statementAgain"));
}
function reviewTabs(games) {
  $("reviewTabs").hidden = games.length < 2;
  $("reviewTabs").innerHTML = games.map((g, k) => `<button type="button" class="tab" data-k="${k}">Q${k + 1}</button>`).join("");
  const select = (k) => {
    $("reviewTabs").querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", Number(b.dataset.k) === k));
    renderReview(games[k]);
  };
  $("reviewTabs").querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => select(Number(b.dataset.k))));
  select(0);
}

// 문제 하나 끝났을 때 (연습, 또는 오늘의 문제 중간)
function showResult() {
  const g = state.game;
  if (g.mode === "daily") {
    const day = state.day;
    if (!day.finished.some((x) => x.qn === g.qn)) day.finished.push(g);
    if (day.finished.length >= day.total) return showDayResult();
    const sum = day.finished.reduce((s, x) => s + (x.score || 0), 0);
    $("scoreNum").textContent = g.score;
    $("rankLine").textContent = `${g.qn + 1}/${day.total}번 완료 · 오늘 합계 ${sum}점`;
    $("rankLine").hidden = false;
    $("resultAnswer").textContent = "";
    $("summaryLine").hidden = true;
    $("btnCopy").hidden = true;
    $("btnNext").textContent = `다음 문제 (${day.finished.length + 1}/${day.total})`;
    $("resultRank").hidden = true;
  } else {
    $("scoreNum").textContent = g.score;
    $("rankLine").hidden = true;
    $("resultAnswer").textContent = "";
    $("summaryLine").hidden = false;
    $("summaryLine").textContent = summaryLine(g);
    $("btnCopy").hidden = false;
    $("btnNext").textContent = "다음 문제";
    $("resultRank").hidden = true;
  }
  reviewTabs([g]);
  show("screenResult", g.mode === "daily" ? "오늘의 문제" : "연습 모드");
}

// 오늘의 문제를 모두 끝냈을 때: 합계·순위·랭킹 + 문제별 결과(탭)
async function showDayResult() {
  const day = state.day;
  state.game = null;
  const total = day.finished.reduce((s, g) => s + (g.score || 0), 0);
  $("scoreNum").textContent = total;
  $("resultAnswer").innerHTML = `<span class="muted">오늘 ${day.total}문제 합계 (만점 ${day.total * 110})</span>`;
  $("rankLine").hidden = true;
  $("summaryLine").hidden = false;
  $("summaryLine").textContent = daySummaryLine(day);
  $("btnCopy").hidden = false;
  $("btnNext").textContent = "연습하러 가기";
  $("resultRank").hidden = false;
  reviewTabs(day.finished);
  show("screenResult", "오늘의 문제");
  $("resultRankBody").innerHTML = `<p class="muted small">랭킹을 불러오는 중…</p>`;
  try {
    const lb = await rpc("get_leaderboard", { token: state.session.token, quiz_date: day.quizDate });
    if (!lb.ok) return handleErr(lb);
    const me = lb.rows.find((r) => r.me);
    if (me) {
      const rankText = `${me.rank}위/${lb.rows.length}명`;
      $("rankLine").textContent = `오늘 ${rankText}`;
      $("rankLine").hidden = false;
      $("summaryLine").textContent = daySummaryLine(day, rankText);
    }
    $("resultRankBody").innerHTML = rankTableHtml(lb);
  } catch (err) { $("resultRankBody").innerHTML = `<p class="muted small">${esc(err.message)}</p>`; }
}

/* ---------------- 랭킹 ---------------- */
function fmtSec(s) {
  if (s === null || s === undefined) return "-";
  const m = Math.floor(s / 60);
  return m >= 60 ? `${Math.floor(m / 60)}시간 ${m % 60}분` : `${m}:${String(s % 60).padStart(2, "0")}`;
}
// 하루 랭킹 표
function rankTableHtml(lb) {
  const n = lb.questions;
  const head = `<p class="muted small">참여 ${lb.started}명 · ${n}문제 모두 완료 ${lb.rows.length}명</p>`;
  if (!lb.rows.length) return head + `<p class="muted small">아직 ${n}문제를 다 푼 사람이 없어요.</p>`;
  const rows = lb.rows.map((r) => `<tr class="${r.me ? "mine" : ""}"><td>${r.rank}</td><td class="nick">${esc(r.nickname)}</td>
      <td class="num"><b>${r.score}</b></td><td>${r.company_ok}/${n}</td><td>${r.mcap_hits}/${n}</td>
      <td class="num">${fmtSec(r.seconds)}</td></tr>`).join("");
  return `${head}<div class="tbl-wrap"><table class="rank hist"><tr><th>순위</th><th>닉네임</th><th>점수</th>
    <th>회사</th><th>시총</th><th>시간</th></tr>${rows}</table></div>
    <p class="muted small">회사·시총 = 맞힌 문제 수 · 동점이면 시총 오차율 평균이 작은 순, 그다음 풀이 시간 합 순</p>`;
}
// 기간 랭킹 표 (주간·월간: 점수 누적)
function periodTableHtml(lb) {
  if (!lb.rows.length) return `<p class="muted small">이 기간에 기록이 없어요.</p>`;
  const rows = lb.rows.map((r) => `<tr class="${r.me ? "mine" : ""}"><td>${r.rank}</td><td class="nick">${esc(r.nickname)}</td>
      <td class="num"><b>${nf.format(r.score)}</b></td><td>${r.days}일</td><td class="num">${r.avg}</td></tr>`).join("");
  return `<div class="tbl-wrap"><table class="rank hist"><tr><th>순위</th><th>닉네임</th><th>누적 점수</th>
    <th>참여</th><th>하루 평균</th></tr>${rows}</table></div>
    <p class="muted small">기간 안에 푼 문제 점수를 모두 더한 순위 · 동점이면 참여일이 많은 순</p>`;
}

const RANK_TABS = { today: "오늘", yesterday: "어제", week: "주간", month: "월간" };
async function openRank(tab = "today") {
  if (!state.session) return goHome();
  show("screenRank", "랭킹");
  document.querySelectorAll("#screenRank .tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  $("rankBody").innerHTML = `<p class="muted small">불러오는 중…</p>`;
  const token = state.session.token;
  const today = kstToday();
  try {
    if (tab === "week" || tab === "month") {
      const days = tab === "week" ? 7 : 30;
      const lb = await rpc("get_period_leaderboard", { token, days });
      if (!lb.ok) return handleErr(lb);
      $("rankBody").innerHTML = `<h3>${RANK_TABS[tab]} 랭킹 <span class="muted small">${lb.from} ~ ${lb.to} (최근 ${days}일)</span></h3>
        ${periodTableHtml(lb)}`;
      return;
    }
    const d = tab === "today" ? today : addDays(today, -1);
    const lb = await rpc("get_leaderboard", { token, quiz_date: d });
    if (!lb.ok) return handleErr(lb);
    let banner = "";
    if (tab === "today") {
      const y = await rpc("get_leaderboard", { token, quiz_date: addDays(d, -1) });
      const top = y.ok ? y.rows.filter((r) => r.rank === 1) : [];
      if (top.length) banner = `<p class="banner">🏆 어제의 1위: ${top.map((r) => `<b>${esc(r.nickname)}</b>`).join(", ")} (${top[0].score}점)</p>`;
    }
    $("rankBody").innerHTML = `<h3>${d} 랭킹</h3>${banner}${rankTableHtml(lb)}`;
  } catch (err) { $("rankBody").innerHTML = `<p class="muted small">${esc(err.message)}</p>`; }
}

/* ---------------- 출제 히스토리 ---------------- */
// docs/history.json (Actions가 매일 갱신): 어제까지 오늘의 문제 보기에 나온 횟수 + 최신 시가총액
async function openHistory() {
  show("screenHistory", "출제 히스토리");
  $("historyBody").innerHTML = `<p class="muted small">불러오는 중…</p>`;
  try {
    const res = await fetch("history.json", { cache: "no-cache" });
    if (!res.ok) throw new Error("아직 기록이 없습니다.");
    const h = await res.json();
    if (!h.items.length) { $("historyBody").innerHTML = `<p class="muted small">아직 기록이 없습니다.</p>`; return; }
    renderHistory(h, null);
  } catch (err) { $("historyBody").innerHTML = `<p class="muted small">${esc(err.message)}</p>`; }
}

// sortDate: 누른 날짜(그날 O인 회사를 맨 위로). 같은 날짜를 다시 누르면 기본 순서(보기 횟수 많은 순)
function renderHistory(h, sortDate) {
  const dates = h.dates || [];        // 날짜 열: 오래된 날 → 최근 (하루에 1열씩 늘어남)
  const items = sortDate
    ? [...h.items.filter((x) => (x.on || []).includes(sortDate)),
       ...h.items.filter((x) => !(x.on || []).includes(sortDate))]   // 안정 정렬: 그룹 안은 기본 순서 유지
    : h.items;
  const dateHead = dates.map((d) => `<th class="day sortable${d === sortDate ? " sorted" : ""}" data-date="${d}">` +
    `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}${d === sortDate ? " ▲" : ""}</th>`).join("");
  const rows = items.map((x) => {
    const on = new Set(x.on || []);
    const cells = dates.map((d) => `<td class="day${d === sortDate ? " sorted" : ""}">${on.has(d) ? "O" : ""}</td>`).join("");
    // 회사명은 7글자 폭까지만 보이고 넘치면 칸 안에서 옆으로 밀어서 봄. 시장은 PI/DAQ로 줄임
    const mkt = { KOSPI: "PI", KOSDAQ: "DAQ" }[x.market] || x.market || "";
    return `<tr><td class="nick"><div class="hist-name" title="${esc(x.name)}">${esc(x.name)}</div></td><td>${esc(mkt)}</td>
      <td class="num">${x.count}</td><td class="num">${x.answer || ""}</td>
      <td class="num">${eok(x.mcap)}</td>${cells}</tr>`;
  }).join("");
  const wrap = document.querySelector("#historyBody .tbl-wrap");
  const scrollX = wrap ? wrap.scrollLeft : 0;   // 다시 그려도 가로 스크롤 위치 유지
  $("historyBody").innerHTML = `
    <p class="muted small">${h.through}까지 ${h.days}일 · ${h.questions}문제 · 보기 ${h.options}개<br>
      출제 가능 ${nf.format(h.universe)}개 회사 중 <b>${h.items.length}개</b>가 한 번 이상 보기에 나왔습니다.</p>
    <div class="tbl-wrap"><table class="rank hist"><tr><th>회사</th><th>시장</th><th>보기</th><th>정답</th>
      <th>시가총액(억원)<br><small>${fmtDate(h.basDt)}</small></th>${dateHead}</tr>${rows}</table></div>
    <p class="muted small">보기 = 보기 4개 안에 나온 횟수 · 정답 = 그중 정답이었던 횟수 · 날짜 열 O = 그날 보기에 나옴 · 오늘 문제는 다음 날 반영<br>
      날짜를 누르면 그날 나온 회사가 맨 위로 올라옵니다(한 번 더 누르면 원래 순서).</p>`;
  document.querySelector("#historyBody .tbl-wrap").scrollLeft = scrollX;
  document.querySelectorAll("#historyBody th.sortable").forEach((th) =>
    th.addEventListener("click", () => renderHistory(h, th.dataset.date === sortDate ? null : th.dataset.date)));
}

/* ---------------- 추가 게임: 시총 순위를 맞춰라! ---------------- */
// docs/rank.json(매일 갱신): 코스피·코스닥 시총 상위 300개. 문제는 여기서 무작위로 만든다(랭킹 반영 없음)
// state.rg = { market, ranks[RG_N], items[{name,mcap,rank}](무작위 순서), slots[RG_N](item 번호|null), done, sel }
const RG_N = 5;                         // 한 문제의 회사 수 (2026-11-20 10개 → 5개)
const RG_STEPS = [5, 10, 20, 30, 50, 100, 150];
const RG_WIDE_FROM = 300, RG_WIDE_STEP = 50;   // 300위 밖에서 시작하면 간격 50위 이상   // 순위 간격 (2026-11-20 800위까지 확대)
const RG_MKT = { KOSPI: "코스피", KOSDAQ: "코스닥" };

async function openRankGame() {
  show("screenRankGame", "시총 순위 게임");
  if (!state.rgData) {
    $("rgBoard").innerHTML = `<p class="muted small">불러오는 중…</p>`;
    try {
      const res = await fetch("rank.json", { cache: "no-cache" });
      if (!res.ok) throw new Error("no data");
      state.rgData = await res.json();
    } catch (err) { $("rgBoard").innerHTML = `<p class="muted small">시총 데이터를 불러오지 못했습니다.</p>`; return; }
  }
  newRankGame();
}

function newRankGame() {
  const data = state.rgData;
  if (!data) return;
  const market = Math.random() < 0.5 ? "KOSPI" : "KOSDAQ";
  const list = data.markets[market];
  const steps = RG_STEPS.filter((st) => 1 + st * (RG_N - 1) <= list.length);
  // 1~800위 어디서든 시작. 단 300위 밖에서 시작하면 회사끼리 시총 차이가 작아서 간격을 50위 이상으로
  let step, start;
  do {
    step = steps[Math.floor(Math.random() * steps.length)];
    start = 1 + Math.floor(Math.random() * (list.length - step * (RG_N - 1)));
  } while (start > RG_WIDE_FROM && step < RG_WIDE_STEP);
  const ranks = Array.from({ length: RG_N }, (_, i) => start + step * i);
  const items = ranks.map((r) => ({ ...list[r - 1], rank: r }));
  for (let i = items.length - 1; i > 0; i--) {                // 보기 순서 섞기
    const j = Math.floor(Math.random() * (i + 1)); [items[i], items[j]] = [items[j], items[i]];
  }
  state.rg = { market, ranks, items, slots: Array(RG_N).fill(null), done: false, sel: null };
  $("rgTitle").textContent = `${RG_MKT[market]} 시총 순위를 맞춰라!`;
  $("rgInfo").innerHTML = `${RG_MKT[market]} 시가총액 <b>${ranks.join("위, ")}위</b>의 회사를 맞혀 보세요.<br>` +
    `아래 회사를 시가총액 오른쪽 칸으로 끌어다 놓으세요(회사를 누른 뒤 칸을 눌러도 됩니다). 시가총액 기준일 ${fmtDate(data.basDt)}`;
  renderRankGame();
}

function rgChip(k) {
  const it = state.rg.items[k];
  return `<div class="rg-chip${state.rg.sel === k ? " sel" : ""}" data-item="${k}">${esc(it.name)}</div>`;
}

function renderRankGame() {
  const g = state.rg;
  const placed = new Set(g.slots.filter((x) => x !== null));
  const rows = g.ranks.map((r, i) => {
    const k = g.slots[i];
    let cell = k === null ? `<span class="rg-empty">여기에 놓기</span>` : rgChip(k);
    let mark = "";
    if (g.done) {
      const ok = k !== null && g.items[k].rank === r;
      const right = g.items.find((it) => it.rank === r);
      cell = k === null ? "" : `<div class="rg-chip fixed">${esc(g.items[k].name)}</div>`;
      mark = ok ? `<span class="rg-ok">✅</span>`
        : `<span class="rg-bad">❌</span><div class="rg-answer">정답: <b>${esc(right.name)}</b></div>`;
    }
    const cap = g.items.find((it) => it.rank === r).mcap;   // 순위 옆 시가총액(힌트)
    return `<div class="rg-row"><span class="rg-rank">${r}위</span><span class="rg-mcap">${prettyEok(Math.round(cap / 1e8))}</span>
      <div class="rg-slot${g.done ? " done" : ""}" data-slot="${i}">${cell}</div><div class="rg-mark">${mark}</div></div>`;
  }).join("");
  let foot;
  if (g.done) {
    const n = g.ranks.filter((r, i) => g.slots[i] !== null && g.items[g.slots[i]].rank === r).length;
    foot = `<p class="rank-line">${n} / ${RG_N} 정답${n === RG_N ? " 🎯" : ""}</p>`;
  } else {
    const pool = g.items.map((_, k) => k).filter((k) => !placed.has(k)).map((k) => rgChip(k)).join("");
    foot = `<div class="rg-pool" data-pool="1">${pool || `<span class="rg-empty">모두 놓았습니다. 정답 확인을 누르세요</span>`}</div>`;
  }
  $("rgBoard").innerHTML = `<div class="rg-list">${rows}</div>${foot}`;
  $("rgSubmit").disabled = g.done || g.slots.some((x) => x === null);
  $("rgSubmit").hidden = g.done;
}

// 회사 k를 칸(slot 번호) 또는 아래 목록(null)으로 옮긴다. 칸에 다른 회사가 있으면 자리를 바꾼다
function rgMove(k, slot) {
  const g = state.rg;
  const from = g.slots.indexOf(k);                 // -1이면 아래 목록에 있던 회사
  if (from >= 0) g.slots[from] = null;
  if (slot !== null) {
    const other = g.slots[slot];
    if (other !== null && from >= 0) g.slots[from] = other;  // 칸끼리는 자리 바꾸기(목록에서 왔으면 원래 회사는 목록으로)
    g.slots[slot] = k;
  }
  g.sel = null;
  renderRankGame();
}

// 끌어다 놓기: 마우스·손가락 모두 pointer 이벤트로 처리. 조금 움직이면 드래그, 아니면 누르기(고르기)
(function rankGameDrag() {
  let drag = null;   // { k, x0, y0, ghost, chip }
  const targetAt = (x, y) => {
    const el = document.elementFromPoint(x, y);
    if (!el) return undefined;
    const slot = el.closest("#rgBoard [data-slot]");
    if (slot) return Number(slot.dataset.slot);
    if (el.closest("#rgBoard [data-pool]")) return null;
    return undefined;                                       // 바깥에 놓으면 취소
  };
  document.addEventListener("pointerdown", (e) => {
    if (!state.rg || state.rg.done) return;
    const chip = e.target.closest("#rgBoard .rg-chip");
    if (!chip || chip.classList.contains("fixed")) return;
    drag = { k: Number(chip.dataset.item), x0: e.clientX, y0: e.clientY, ghost: null, chip };
  });
  document.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (!drag.ghost) {
      if (Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) < 6) return;
      drag.ghost = drag.chip.cloneNode(true);
      drag.ghost.classList.add("ghost");
      document.body.appendChild(drag.ghost);
      drag.chip.classList.add("dragging");
    }
    e.preventDefault();
    drag.ghost.style.left = `${e.clientX}px`;
    drag.ghost.style.top = `${e.clientY}px`;
    document.querySelectorAll("#rgBoard .over").forEach((el) => el.classList.remove("over"));
    const t = targetAt(e.clientX, e.clientY);
    if (t !== undefined) {
      const el = document.querySelector(t === null ? "#rgBoard [data-pool]" : `#rgBoard [data-slot="${t}"]`);
      if (el) el.classList.add("over");
    }
    if (e.clientY < 60) window.scrollBy(0, -12);                    // 화면 끝으로 끌면 자동 스크롤
    else if (e.clientY > window.innerHeight - 60) window.scrollBy(0, 12);
  }, { passive: false });
  const end = (e) => {
    if (!drag) return;
    const d = drag; drag = null;
    if (d.ghost) {
      d.ghost.remove();
      const t = e.type === "pointerup" ? targetAt(e.clientX, e.clientY) : undefined;
      if (t !== undefined) rgMove(d.k, t); else renderRankGame();
    } else if (e.type === "pointerup") {                           // 누르기: 고르기/해제
      state.rg.sel = state.rg.sel === d.k ? null : d.k;
      renderRankGame();
    }
  };
  document.addEventListener("pointerup", end);
  document.addEventListener("pointercancel", end);
  // 회사를 고른 상태에서 칸·목록을 누르면 그리로 옮김
  document.addEventListener("click", (e) => {
    const g = state.rg;
    if (!g || g.done || g.sel === null || e.target.closest(".rg-chip")) return;
    const slot = e.target.closest("#rgBoard [data-slot]");
    if (slot) rgMove(g.sel, Number(slot.dataset.slot));
    else if (e.target.closest("#rgBoard [data-pool]")) rgMove(g.sel, null);
  });
})();

$("rgSubmit").addEventListener("click", () => { state.rg.done = true; state.rg.sel = null; renderRankGame(); });
$("rgNew").addEventListener("click", newRankGame);
$("btnRankGame").addEventListener("click", openRankGame);

/* ---------------- 기타 ---------------- */
let toastTimer;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 2200);
}

async function copySummary() {
  const text = $("summaryLine").textContent;
  try { await navigator.clipboard.writeText(text); }
  catch {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove();
  }
  toast("결과를 복사했어요");
}

/* ---------------- 이벤트 연결·시작 ---------------- */
const practice = () => nextQuestion().catch(() => toast("문제를 불러오지 못했어요"));
$("guessInput").addEventListener("input", (e) => {
  const x = parseGuess(e.target.value);
  $("guessPretty").textContent = x ? prettyEok(x) : " ";
});
$("guessForm").addEventListener("submit", submitGuess);
$("btnStart").addEventListener("click", practice);
$("btnNext").addEventListener("click", () => {
  const day = state.day;
  if (state.game && state.game.mode === "daily" && day && day.finished.length < day.total) startDaily();
  else practice();
});
$("btnCopy").addEventListener("click", copySummary);
$("btnHome").addEventListener("click", goHome);
$("btnMe").addEventListener("click", () => { setMsg("msgNick", ""); show("screenSettings", "설정"); });
$("btnGoSignup").addEventListener("click", () => { setMsg("msg1", ""); signupStep(1); });
$("btnGoLogin").addEventListener("click", () => { show("screenLogin", "로그인"); setTimeout(() => $("loginNick").focus(), 50); });
$("btnDaily").addEventListener("click", startDaily);
$("btnRank").addEventListener("click", () => openRank("today"));
$("btnHistory").addEventListener("click", openHistory);
$("btnRank2").addEventListener("click", () => openRank("week"));
$("btnGoPin").addEventListener("click", () => openPin(false));
document.querySelectorAll("#screenRank .tab").forEach((b) => b.addEventListener("click", () => openRank(b.dataset.tab)));

(async function init() {
  loadSession();
  updateHeader();
  loadIndex()
    .then(() => {
      $("poolInfo").textContent = `문제 ${nf.format(state.index.count)}개 · 시가총액 기준일 ${fmtDate(state.index.basDt)}`;
      $("btnStart").disabled = false;
    })
    .catch(() => { $("poolInfo").textContent = "문제 파일을 찾지 못했어요. (scripts/build_quiz.py 실행 필요)"; });
  if (state.session) {
    // 저장된 세션이 아직 유효한지 확인 (유효기간 90일)
    try {
      const r = await rpc("whoami", { token: state.session.token });
      if (!r.ok) { clearSession(); }
      else {
        saveSession(state.session.token, r.nickname);
        if (r.must_change_pin) return openPin(true);
      }
    } catch { /* 서버 연결 실패: 연습 모드는 그대로 가능 */ }
  }
  goHome();
})();
