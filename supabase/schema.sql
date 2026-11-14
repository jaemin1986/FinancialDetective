-- =====================================================================
-- FinancialDetective — Supabase 스키마 (테이블 + RLS + 권한 + RPC 함수)
-- 사용법: Supabase 대시보드 → SQL Editor → 이 파일 전체를 붙여넣고 Run.
--         여러 번 실행해도 되도록 작성함 (테이블은 if not exists, 함수는 create or replace).
--
-- 보안 원칙
--  1) 모든 테이블은 RLS를 켜고, anon/authenticated에는 테이블 권한을 주지 않는다.
--  2) 브라우저(anon)는 아래 public RPC 함수(SECURITY DEFINER)만 실행할 수 있다.
--  3) 오늘의 문제 정답(answers)은 RPC가 판정에만 쓰고, 다 풀기 전에는 돌려주지 않는다.
--  4) 팀 코드·PIN은 crypt() 해시, 세션 토큰은 sha256 해시로만 저장한다.
--  5) 날짜는 한국시간(Asia/Seoul) 기준, 하루의 경계는 새벽 3시 (private.kst_today).
--  6) 예상 가능한 오류(틀린 PIN 등)는 예외를 던지지 않고 {"ok":false,"error":"코드"}로 돌려준다.
--     (예외를 던지면 실패 횟수 기록까지 롤백되기 때문)
-- =====================================================================

create extension if not exists pgcrypto with schema extensions;

-- 내부용 함수는 Data API에 노출되지 않는 private 스키마에 둔다
create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

-- ---------------------------------------------------------------- 테이블
create table if not exists public.config (
  key   text primary key,
  value text not null
);
alter table public.config enable row level security;

create table if not exists public.banned_words (
  word text primary key
);
alter table public.banned_words enable row level security;

create table if not exists public.players (
  id                  uuid primary key default gen_random_uuid(),
  nickname            text not null,
  nickname_lower      text not null unique,
  pin_hash            text not null,
  created_at          timestamptz not null default now(),
  nickname_changed_at timestamptz,
  fail_count          int not null default 0,
  locked_until        timestamptz,
  must_change_pin     boolean not null default false
);
alter table public.players enable row level security;

create table if not exists public.sessions (
  token_hash text primary key,
  player_id  uuid not null references public.players(id) on delete cascade,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
alter table public.sessions enable row level security;
create index if not exists sessions_player_idx on public.sessions(player_id);

-- 팀 코드 확인 후 발급하는 10분짜리 가입용 토큰
create table if not exists public.signup_tokens (
  token_hash text primary key,
  expires_at timestamptz not null
);
alter table public.signup_tokens enable row level security;

-- 연속 실패 잠금 (팀 코드: 접속 IP 기준, 없는 닉네임 로그인: IP 기준)
create table if not exists public.attempts (
  key          text primary key,
  fail_count   int not null default 0,
  locked_until timestamptz
);
alter table public.attempts enable row level security;

-- 오늘의 문제 정답 (GitHub Actions가 service_role 키로 넣음). 하루 여러 문제: qn = 0, 1, 2
create table if not exists public.answers (
  quiz_date    date not null,
  qn           smallint not null default 0,
  answer_index int not null check (answer_index between 0 and 9),
  mcap         bigint not null check (mcap > 0),   -- 원
  bas_dt       date not null,                       -- 시가총액 기준일
  corp_name    text not null,
  reveal       jsonb,                               -- 보기 4개 비교 데이터
  created_at   timestamptz not null default now(),
  primary key (quiz_date, qn)
);
alter table public.answers enable row level security;

create table if not exists public.plays (
  id              bigint generated always as identity primary key,
  player_id       uuid not null references public.players(id) on delete cascade,
  quiz_date       date not null,
  qn              smallint not null default 0,
  started_at      timestamptz not null default now(),
  company_choices int[] not null default '{}',
  company_ok      boolean not null default false,
  guesses         bigint[] not null default '{}',  -- 원
  finished_at     timestamptz,
  score           int,
  last_err        numeric,                          -- 마지막 시총 입력의 오차율 (동점 처리용)
  constraint plays_player_date_qn_key unique (player_id, quiz_date, qn)
);
alter table public.plays enable row level security;
create index if not exists plays_date_idx on public.plays(quiz_date);

-- (2026-11-14) 하루 1문제 → 3문제 변경: 이미 만든 테이블에 qn 추가
alter table public.answers add column if not exists qn smallint not null default 0;
alter table public.plays   add column if not exists qn smallint not null default 0;
-- (2026-11-14) 문제(재무제표+보기)도 서버에 두고, 그날·순서가 된 문제만 RPC로 내려준다
alter table public.answers add column if not exists question jsonb;
do $$
begin
  if exists (select 1 from pg_constraint where conname = 'answers_pkey'
             and conrelid = 'public.answers'::regclass and cardinality(conkey) = 1) then
    alter table public.answers drop constraint answers_pkey;
    alter table public.answers add primary key (quiz_date, qn);
  end if;
  if exists (select 1 from pg_constraint where conname = 'plays_player_id_quiz_date_key') then
    alter table public.plays drop constraint plays_player_id_quiz_date_key;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'plays_player_date_qn_key') then
    alter table public.plays add constraint plays_player_date_qn_key unique (player_id, quiz_date, qn);
  end if;
end $$;

-- 테이블 권한: anon/authenticated는 없음, service_role(서버·관리 스크립트)만
revoke all on all tables in schema public from public, anon, authenticated;
grant select, insert, update, delete on all tables in schema public to service_role;

insert into public.banned_words(word) values
  ('관리자'), ('운영자'), ('운영진'), ('admin'), ('administrator'), ('root'), ('system'), ('test'), ('테스트')
on conflict do nothing;

-- ---------------------------------------------------------------- 내부 함수 (private)
-- 오늘의 문제 날짜. 하루의 경계는 새벽 3시(KST) — 03:00~다음날 02:59가 하루 (2026-11-14 결정)
create or replace function private.kst_today() returns date
language sql stable set search_path = '' as $$
  select ((now() at time zone 'Asia/Seoul') - interval '3 hours')::date
$$;

create or replace function private.sha256(p text) returns text
language sql immutable set search_path = '' as $$
  select encode(extensions.digest(p, 'sha256'), 'hex')
$$;

create or replace function private.client_ip() returns text
language plpgsql stable set search_path = '' as $$
declare h json;
begin
  h := nullif(current_setting('request.headers', true), '')::json;
  return coalesce(nullif(trim(split_part(h->>'x-forwarded-for', ',', 1)), ''),
                  h->>'cf-connecting-ip', 'unknown');
exception when others then
  return 'unknown';
end $$;

-- 잠금 남은 초 (0이면 잠금 아님)
create or replace function private.locked_seconds(p_until timestamptz) returns int
language sql stable set search_path = '' as $$
  select greatest(0, ceil(extract(epoch from (p_until - now()))))::int
$$;

create or replace function private.attempt_locked(p_key text) returns int
language sql stable set search_path = '' as $$
  select coalesce((select private.locked_seconds(locked_until) from public.attempts where key = p_key), 0)
$$;

-- 실패 1회 기록. 5회째면 10분 잠금하고 횟수 초기화
create or replace function private.attempt_fail(p_key text) returns void
language plpgsql set search_path = '' as $$
begin
  insert into public.attempts(key, fail_count) values (p_key, 1)
  on conflict (key) do update set fail_count = public.attempts.fail_count + 1;
  update public.attempts set fail_count = 0, locked_until = now() + interval '10 minutes'
   where key = p_key and fail_count >= 5;
end $$;

create or replace function private.attempt_reset(p_key text) returns void
language sql set search_path = '' as $$
  delete from public.attempts where key = p_key
$$;

-- 닉네임 규칙 위반 사유 (문제 없으면 null)
create or replace function private.nickname_problem(p_nick text, p_exclude uuid default null) returns text
language plpgsql stable set search_path = '' as $$
begin
  if p_nick is null or char_length(p_nick) < 2 or char_length(p_nick) > 10 then
    return 'LENGTH';
  end if;
  if p_nick !~ '^[가-힣A-Za-z0-9_]+$' then
    return 'CHARS';
  end if;
  if exists (select 1 from public.banned_words b where position(lower(b.word) in lower(p_nick)) > 0) then
    return 'BANNED';
  end if;
  if exists (select 1 from public.players p where p.nickname_lower = lower(p_nick)
             and p.id is distinct from p_exclude) then
    return 'TAKEN';
  end if;
  return null;
end $$;

create or replace function private.new_session(p_player uuid) returns text
language plpgsql set search_path = '' as $$
declare t text := encode(extensions.gen_random_bytes(32), 'hex');
begin
  delete from public.sessions where expires_at < now();
  insert into public.sessions(token_hash, player_id, expires_at)
  values (private.sha256(t), p_player, now() + interval '90 days');
  return t;
end $$;

create or replace function private.session_player(p_token text) returns public.players
language sql stable set search_path = '' as $$
  select p.* from public.sessions s join public.players p on p.id = s.player_id
   where s.token_hash = private.sha256(coalesce(p_token, '')) and s.expires_at > now()
$$;

create or replace function private.hint(p_guess bigint, p_mcap bigint) returns text
language sql immutable set search_path = '' as $$
  select case when abs(p_guess - p_mcap)::numeric / p_mcap <= 0.10 then 'HIT'
              when p_mcap > p_guess then 'UP' else 'DOWN' end
$$;

-- 점수: 회사 40/20/0 + 시총 60/48/36/24/12 + 맞힌 입력 오차 ≤3%면 +10
create or replace function private.calc_score(p_play public.plays, p_ans public.answers) returns int
language plpgsql immutable set search_path = '' as $$
declare
  c int := 0; m int := 0; i int; n int := cardinality(p_play.guesses);
begin
  if p_play.company_ok then
    c := case cardinality(p_play.company_choices) when 1 then 40 else 20 end;
  end if;
  for i in 1..n loop
    if private.hint(p_play.guesses[i], p_ans.mcap) = 'HIT' then
      m := (array[60, 48, 36, 24, 12])[i];
      if abs(p_play.guesses[i] - p_ans.mcap)::numeric / p_ans.mcap <= 0.03 then
        m := m + 10;
      end if;
      exit;
    end if;
  end loop;
  return c + m;
end $$;

-- 진행 상태 (정답 정보는 해당 단계가 끝난 뒤에만 포함)
create or replace function private.play_state(p_play public.plays, p_ans public.answers) returns jsonb
language plpgsql stable set search_path = '' as $$
declare
  company_done boolean := p_play.company_ok or cardinality(p_play.company_choices) >= 2;
  g jsonb := '[]'::jsonb; i int;
  out jsonb;
begin
  for i in 1..cardinality(p_play.guesses) loop
    g := g || jsonb_build_object('amount_eok', p_play.guesses[i]::numeric / 100000000,
                                 'hint', private.hint(p_play.guesses[i], p_ans.mcap));
  end loop;
  out := jsonb_build_object(
    'ok', true,
    'quiz_date', p_play.quiz_date,
    'qn', p_play.qn,
    'question', p_ans.question,          -- 재무제표 + 보기 (정답 없음)
    'bas_dt', p_ans.bas_dt,
    'company_choices', to_jsonb(p_play.company_choices),
    'company_ok', p_play.company_ok,
    'company_done', company_done,
    'guesses', g,
    'finished', p_play.finished_at is not null);
  if company_done then
    out := out || jsonb_build_object('answer_index', p_ans.answer_index, 'corp_name', p_ans.corp_name);
  end if;
  if p_play.finished_at is not null then
    out := out || jsonb_build_object('score', p_play.score, 'mcap', p_ans.mcap, 'reveal', p_ans.reveal,
                                     'seconds', floor(extract(epoch from p_play.finished_at - p_play.started_at)));
  end if;
  return out;
end $$;

-- ---------------------------------------------------------------- 공개 RPC: 가입·로그인
create or replace function public.verify_team_code(team_code text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  k text := 'team:' || private.client_ip();
  wait int := private.attempt_locked(k);
  h text;
  t text;
begin
  if wait > 0 then
    return jsonb_build_object('ok', false, 'error', 'LOCKED', 'wait_seconds', wait);
  end if;
  select value into h from public.config where key = 'team_code_hash';
  if h is null then
    return jsonb_build_object('ok', false, 'error', 'NOT_CONFIGURED');
  end if;
  if extensions.crypt(coalesce(team_code, ''), h) <> h then
    perform private.attempt_fail(k);
    return jsonb_build_object('ok', false, 'error', 'WRONG_CODE');
  end if;
  perform private.attempt_reset(k);
  delete from public.signup_tokens where expires_at < now();
  t := encode(extensions.gen_random_bytes(24), 'hex');
  insert into public.signup_tokens values (private.sha256(t), now() + interval '10 minutes');
  return jsonb_build_object('ok', true, 'signup_token', t);
end $$;

create or replace function public.check_nickname(nickname text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare r text := private.nickname_problem(nickname);
begin
  return jsonb_build_object('ok', r is null, 'error', r);
end $$;

create or replace function public.register_player(signup_token text, nickname text, pin text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  r text;
  pid uuid;
begin
  delete from public.signup_tokens
   where token_hash = private.sha256(coalesce(signup_token, '')) and expires_at > now();
  if not found then
    return jsonb_build_object('ok', false, 'error', 'SIGNUP_EXPIRED');
  end if;
  r := private.nickname_problem(nickname);
  if r is not null then
    -- 가입 토큰은 이미 지웠으므로 다시 쓸 수 있게 되돌린다(10분 유지)
    insert into public.signup_tokens values (private.sha256(signup_token), now() + interval '10 minutes');
    return jsonb_build_object('ok', false, 'error', r);
  end if;
  if pin is null or pin !~ '^[0-9]{4}$' then
    insert into public.signup_tokens values (private.sha256(signup_token), now() + interval '10 minutes');
    return jsonb_build_object('ok', false, 'error', 'PIN_FORMAT');
  end if;
  insert into public.players(nickname, nickname_lower, pin_hash)
  values (nickname, lower(nickname), extensions.crypt(pin, extensions.gen_salt('bf', 8)))
  returning id into pid;
  return jsonb_build_object('ok', true, 'token', private.new_session(pid), 'nickname', nickname,
                            'must_change_pin', false);
end $$;

create or replace function public.login(nickname text, pin text) returns jsonb
language plpgsql security definer set search_path = '' as $$
#variable_conflict use_variable
declare
  p public.players;
  k text := 'login:' || private.client_ip();
  wait int;
begin
  select * into p from public.players where nickname_lower = lower(coalesce(nickname, '')) for update;
  if not found then
    -- 없는 닉네임: 접속 IP 기준으로 5회 실패 시 10분 잠금
    wait := private.attempt_locked(k);
    if wait > 0 then
      return jsonb_build_object('ok', false, 'error', 'LOCKED', 'wait_seconds', wait);
    end if;
    perform private.attempt_fail(k);
    return jsonb_build_object('ok', false, 'error', 'WRONG_LOGIN');
  end if;
  wait := private.locked_seconds(p.locked_until);
  if wait > 0 then
    return jsonb_build_object('ok', false, 'error', 'LOCKED', 'wait_seconds', wait);
  end if;
  if extensions.crypt(coalesce(pin, ''), p.pin_hash) <> p.pin_hash then
    update public.players
       set fail_count = case when fail_count + 1 >= 5 then 0 else fail_count + 1 end,
           locked_until = case when fail_count + 1 >= 5 then now() + interval '10 minutes' else locked_until end
     where id = p.id;
    return jsonb_build_object('ok', false, 'error', 'WRONG_LOGIN');
  end if;
  update public.players set fail_count = 0, locked_until = null where id = p.id;
  return jsonb_build_object('ok', true, 'token', private.new_session(p.id), 'nickname', p.nickname,
                            'must_change_pin', p.must_change_pin);
end $$;

create or replace function public.logout(token text) returns jsonb
language sql security definer set search_path = '' as $$
  delete from public.sessions where token_hash = private.sha256(coalesce(token, ''));
  select jsonb_build_object('ok', true);
$$;

-- 자동 로그인 확인용: 세션이 살아 있으면 내 정보
create or replace function public.whoami(token text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare p public.players := private.session_player(token);
begin
  if p.id is null then
    return jsonb_build_object('ok', false, 'error', 'SESSION_EXPIRED');
  end if;
  return jsonb_build_object('ok', true, 'nickname', p.nickname, 'must_change_pin', p.must_change_pin,
                            'nickname_changeable_at', p.nickname_changed_at + interval '30 days',
                            'today', private.kst_today());
end $$;

create or replace function public.change_nickname(token text, new_nickname text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  p public.players := private.session_player(token);
  r text;
begin
  if p.id is null then
    return jsonb_build_object('ok', false, 'error', 'SESSION_EXPIRED');
  end if;
  if p.nickname_changed_at is not null and p.nickname_changed_at > now() - interval '30 days' then
    return jsonb_build_object('ok', false, 'error', 'TOO_SOON',
                              'available_at', p.nickname_changed_at + interval '30 days');
  end if;
  r := private.nickname_problem(new_nickname, p.id);
  if r is not null then
    return jsonb_build_object('ok', false, 'error', r);
  end if;
  update public.players set nickname = new_nickname, nickname_lower = lower(new_nickname),
         nickname_changed_at = now() where id = p.id;
  return jsonb_build_object('ok', true, 'nickname', new_nickname);
end $$;

create or replace function public.change_pin(token text, old_pin text, new_pin text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare p public.players := private.session_player(token);
begin
  if p.id is null then
    return jsonb_build_object('ok', false, 'error', 'SESSION_EXPIRED');
  end if;
  if extensions.crypt(coalesce(old_pin, ''), p.pin_hash) <> p.pin_hash then
    return jsonb_build_object('ok', false, 'error', 'WRONG_PIN');
  end if;
  if new_pin is null or new_pin !~ '^[0-9]{4}$' then
    return jsonb_build_object('ok', false, 'error', 'PIN_FORMAT');
  end if;
  update public.players set pin_hash = extensions.crypt(new_pin, extensions.gen_salt('bf', 8)),
         must_change_pin = false where id = p.id;
  return jsonb_build_object('ok', true);
end $$;

-- ---------------------------------------------------------------- 공개 RPC: 오늘의 문제 (하루 여러 문제, 순서대로)
-- 세션 확인 + 지금 풀 문제(내 기록)를 잠그고 가져오는 공통 부분
--  p_create = true: 진행 중인 문제가 없으면 다음 번호 문제를 시작(시작 시각 기록)
drop function if exists private.game_context(text, boolean);
create or replace function private.game_context(p_token text, p_create boolean,
                                                out o_err text, out o_play public.plays,
                                                out o_ans public.answers, out o_total int)
language plpgsql set search_path = '' as $$
declare
  p public.players := private.session_player(p_token);
  d date := private.kst_today();
  nxt int;
begin
  if p.id is null then o_err := 'SESSION_EXPIRED'; return; end if;
  if p.must_change_pin then o_err := 'PIN_CHANGE_REQUIRED'; return; end if;
  select count(*) into o_total from public.answers a where a.quiz_date = d;
  if o_total = 0 then o_err := 'NO_QUIZ'; return; end if;
  select * into o_play from public.plays pl
   where pl.player_id = p.id and pl.quiz_date = d and pl.finished_at is null
   order by pl.qn limit 1 for update;
  if not found then
    if not p_create then o_err := 'NOT_STARTED'; return; end if;
    select count(*) into nxt from public.plays pl where pl.player_id = p.id and pl.quiz_date = d;
    if nxt >= o_total then o_err := 'ALL_DONE'; return; end if;
    insert into public.plays(player_id, quiz_date, qn) values (p.id, d, nxt) on conflict do nothing;
    select * into o_play from public.plays pl
     where pl.player_id = p.id and pl.quiz_date = d and pl.qn = nxt for update;
  end if;
  select * into o_ans from public.answers a where a.quiz_date = d and a.qn = o_play.qn;
end $$;

-- 오늘 끝낸 문제들의 결과 (정답·비교 데이터 포함 — 끝낸 문제만)
create or replace function private.finished_states(p_player uuid, p_date date) returns jsonb
language sql stable set search_path = '' as $$
  select coalesce(jsonb_agg(private.play_state(pl, a) order by pl.qn), '[]'::jsonb)
    from public.plays pl join public.answers a on a.quiz_date = pl.quiz_date and a.qn = pl.qn
   where pl.player_id = p_player and pl.quiz_date = p_date and pl.finished_at is not null
$$;

-- 오늘의 문제 열기: 진행 중인 문제가 있으면 그 상태, 없으면 다음 문제를 시작.
-- 다 풀었으면 current 없이 all_done. finished = 끝낸 문제들의 결과
create or replace function public.start_daily(token text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  ctx record;
  p public.players := private.session_player(token);
  d date := private.kst_today();
  cur jsonb := null;
begin
  select * into ctx from private.game_context(token, true);
  if ctx.o_err is not null and ctx.o_err <> 'ALL_DONE' then
    return jsonb_build_object('ok', false, 'error', ctx.o_err);
  end if;
  if ctx.o_err is null then
    cur := private.play_state(ctx.o_play, ctx.o_ans);
  end if;
  return jsonb_build_object('ok', true, 'quiz_date', d, 'total', ctx.o_total,
                            'all_done', coalesce(ctx.o_err = 'ALL_DONE', false), 'current', cur,
                            'finished', private.finished_states(p.id, d));
end $$;

create or replace function public.submit_company(token text, choice int) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  ctx record;
  pl public.plays;
  a public.answers;
begin
  select * into ctx from private.game_context(token, false);
  if ctx.o_err is not null then
    return jsonb_build_object('ok', false, 'error', ctx.o_err);
  end if;
  pl := ctx.o_play;
  a := ctx.o_ans;
  if pl.company_ok or cardinality(pl.company_choices) >= 2 then
    return jsonb_build_object('ok', false, 'error', 'COMPANY_DONE');
  end if;
  if choice is null or choice < 0 or choice > 3 or choice = any(pl.company_choices) then
    return jsonb_build_object('ok', false, 'error', 'BAD_CHOICE');
  end if;
  update public.plays set company_choices = company_choices || choice,
         company_ok = (choice = a.answer_index)
   where id = pl.id returning * into pl;
  return private.play_state(pl, a) || jsonb_build_object('correct', pl.company_ok, 'total', ctx.o_total);
end $$;

create or replace function public.submit_guess(token text, amount_eok numeric) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  ctx record;
  pl public.plays;
  g bigint;
  h text;
  a public.answers;
begin
  select * into ctx from private.game_context(token, false);
  if ctx.o_err is not null then
    return jsonb_build_object('ok', false, 'error', ctx.o_err);
  end if;
  pl := ctx.o_play;
  a := ctx.o_ans;
  if not (pl.company_ok or cardinality(pl.company_choices) >= 2) then
    return jsonb_build_object('ok', false, 'error', 'COMPANY_NOT_DONE');
  end if;
  if amount_eok is null or amount_eok <= 0 or amount_eok > 10000000 then   -- 1,000조원 상한
    return jsonb_build_object('ok', false, 'error', 'BAD_AMOUNT');
  end if;
  g := round(amount_eok * 100000000)::bigint;
  h := private.hint(g, a.mcap);
  update public.plays set guesses = guesses || g where id = pl.id returning * into pl;
  if h = 'HIT' or cardinality(pl.guesses) >= 5 then
    update public.plays
       set finished_at = now(),
           last_err = abs(g - a.mcap)::numeric / a.mcap,
           score = private.calc_score(pl, a)
     where id = pl.id returning * into pl;
  end if;
  return private.play_state(pl, a) || jsonb_build_object('hint', h, 'total', ctx.o_total);
end $$;

-- ---------------------------------------------------------------- 공개 RPC: 랭킹·기록
-- 그날 문제를 모두 끝낸 사람만 순위에 올린다. 점수 = 문제별 점수 합계.
-- 동점: 시총 마지막 입력 오차율 평균이 작은 순 → 문제별 소요 시간 합이 짧은 순
-- 다른 사람의 입력값·선택한 보기는 돌려주지 않는다 (스포일러 방지)
create or replace function private.day_summary(p_date date)
returns table (player_id uuid, solved int, total_score int, company_ok int, mcap_hits int,
               avg_err numeric, seconds int)
language sql stable set search_path = '' as $$
  select pl.player_id,
         count(*) filter (where pl.finished_at is not null)::int,
         coalesce(sum(pl.score), 0)::int,
         count(*) filter (where pl.company_ok)::int,
         count(*) filter (where exists (select 1 from generate_subscripts(pl.guesses, 1) i
                                         where private.hint(pl.guesses[i], a.mcap) = 'HIT'))::int,
         avg(pl.last_err),
         floor(extract(epoch from sum(pl.finished_at - pl.started_at)))::int
    from public.plays pl
    join public.answers a on a.quiz_date = pl.quiz_date and a.qn = pl.qn
   where pl.quiz_date = p_date
   group by pl.player_id
$$;

create or replace function public.get_leaderboard(token text, quiz_date date default null) returns jsonb
language plpgsql security definer set search_path = '' as $$
#variable_conflict use_variable
declare
  me public.players := private.session_player(token);
  d date := coalesce(quiz_date, private.kst_today());
  n int;
  rows jsonb;
  started int;
begin
  if me.id is null then
    return jsonb_build_object('ok', false, 'error', 'SESSION_EXPIRED');
  end if;
  select count(*) into n from public.answers a where a.quiz_date = d;
  select count(distinct pl.player_id) into started from public.plays pl where pl.quiz_date = d;
  select coalesce(jsonb_agg(x order by x.rank, x.seconds), '[]'::jsonb) into rows from (
    select rank() over (order by s.total_score desc, s.avg_err asc nulls last, s.seconds asc) as rank,
           p.nickname, s.total_score as score, s.company_ok, s.mcap_hits, s.seconds,
           (s.player_id = me.id) as me
      from private.day_summary(d) s
      join public.players p on p.id = s.player_id
     where s.solved >= n and n > 0
  ) x;
  return jsonb_build_object('ok', true, 'quiz_date', d, 'questions', n, 'started', started, 'rows', rows);
end $$;

-- 내 지난 기록 (streak·누적 정답률 계산용): 날짜별 합계
create or replace function public.get_my_history(token text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  me public.players := private.session_player(token);
  rows jsonb;
begin
  if me.id is null then
    return jsonb_build_object('ok', false, 'error', 'SESSION_EXPIRED');
  end if;
  select coalesce(jsonb_agg(x order by x.quiz_date desc), '[]'::jsonb) into rows from (
    select d.quiz_date, s.total_score as score, s.solved, s.company_ok, s.mcap_hits,
           (select count(*) from public.answers a where a.quiz_date = d.quiz_date)::int as questions
      from (select distinct pl.quiz_date from public.plays pl where pl.player_id = me.id) d
      cross join lateral (select * from private.day_summary(d.quiz_date) t where t.player_id = me.id) s
  ) x;
  return jsonb_build_object('ok', true, 'today', private.kst_today(), 'rows', rows);
end $$;

-- 기간 랭킹 (주간 7일·월간 30일 등): 최근 days일 동안 끝낸 문제 점수를 모두 더한 순위
create or replace function public.get_period_leaderboard(token text, days int default 7) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  me public.players := private.session_player(token);
  n int := least(greatest(coalesce(days, 7), 1), 366);
  d_to date := private.kst_today();
  d_from date := private.kst_today() - (least(greatest(coalesce(days, 7), 1), 366) - 1);
  rows jsonb;
begin
  if me.id is null then
    return jsonb_build_object('ok', false, 'error', 'SESSION_EXPIRED');
  end if;
  select coalesce(jsonb_agg(x order by x.rank, x.nickname), '[]'::jsonb) into rows from (
    select rank() over (order by sum(pl.score) desc, count(distinct pl.quiz_date) desc) as rank,
           p.nickname, sum(pl.score)::int as score,
           count(distinct pl.quiz_date)::int as days,
           round(sum(pl.score)::numeric / count(distinct pl.quiz_date))::int as avg,
           (pl.player_id = me.id) as me
      from public.plays pl join public.players p on p.id = pl.player_id
     where pl.quiz_date between d_from and d_to and pl.finished_at is not null
     group by pl.player_id, p.nickname
  ) x;
  return jsonb_build_object('ok', true, 'days', n, 'from', d_from, 'to', d_to, 'rows', rows);
end $$;

-- ---------------------------------------------------------------- 관리자 RPC (service_role 전용, admin.py)
create or replace function public.admin_set_team_code(code text) returns jsonb
language plpgsql security definer set search_path = '' as $$
begin
  if code is null or char_length(code) < 4 then
    return jsonb_build_object('ok', false, 'error', 'TOO_SHORT');
  end if;
  insert into public.config(key, value) values ('team_code_hash', extensions.crypt(code, extensions.gen_salt('bf', 8)))
  on conflict (key) do update set value = excluded.value;
  return jsonb_build_object('ok', true);
end $$;

create or replace function public.admin_reset_pin(nickname text) returns jsonb
language plpgsql security definer set search_path = '' as $$
#variable_conflict use_variable
declare
  t text := lpad((floor(random() * 10000))::int::text, 4, '0');
  pid uuid;
begin
  update public.players set pin_hash = extensions.crypt(t, extensions.gen_salt('bf', 8)),
         must_change_pin = true, fail_count = 0, locked_until = null
   where nickname_lower = lower(nickname) returning id into pid;
  if pid is null then
    return jsonb_build_object('ok', false, 'error', 'NOT_FOUND');
  end if;
  delete from public.sessions where player_id = pid;
  return jsonb_build_object('ok', true, 'temp_pin', t);
end $$;

create or replace function public.admin_rename(nickname text, new_nickname text) returns jsonb
language plpgsql security definer set search_path = '' as $$
#variable_conflict use_variable
declare
  pid uuid;
  r text;
begin
  select id into pid from public.players where nickname_lower = lower(nickname);
  if pid is null then
    return jsonb_build_object('ok', false, 'error', 'NOT_FOUND');
  end if;
  r := private.nickname_problem(new_nickname, pid);
  if r is not null and r <> 'BANNED' then      -- 관리자는 금지어 예외 허용
    return jsonb_build_object('ok', false, 'error', r);
  end if;
  update public.players set nickname = new_nickname, nickname_lower = lower(new_nickname) where id = pid;
  return jsonb_build_object('ok', true);
end $$;

create or replace function public.admin_delete(nickname text) returns jsonb
language plpgsql security definer set search_path = '' as $$
#variable_conflict use_variable
begin
  delete from public.players where nickname_lower = lower(nickname);
  if not found then
    return jsonb_build_object('ok', false, 'error', 'NOT_FOUND');
  end if;
  return jsonb_build_object('ok', true);
end $$;

-- ---------------------------------------------------------------- 함수 실행 권한
-- Postgres는 새 함수에 PUBLIC 실행 권한을 기본으로 주므로 전부 회수한 뒤 필요한 것만 연다
revoke execute on all functions in schema public  from public, anon, authenticated;
revoke execute on all functions in schema private from public, anon, authenticated;

grant execute on function
  public.verify_team_code(text),
  public.check_nickname(text),
  public.register_player(text, text, text),
  public.login(text, text),
  public.logout(text),
  public.whoami(text),
  public.change_nickname(text, text),
  public.change_pin(text, text, text),
  public.start_daily(text),
  public.submit_company(text, int),
  public.submit_guess(text, numeric),
  public.get_leaderboard(text, date),
  public.get_period_leaderboard(text, int),
  public.get_my_history(text)
to anon, authenticated;

grant execute on function
  public.admin_set_team_code(text),
  public.admin_reset_pin(text),
  public.admin_rename(text, text),
  public.admin_delete(text)
to service_role;

-- 앞으로 public에 만드는 함수·테이블도 자동으로 열리지 않게
alter default privileges in schema public revoke execute on functions from public, anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;
