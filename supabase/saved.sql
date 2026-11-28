-- =====================================================================
-- FinancialDetective — "저장한 종목" (안 외워지는 회사 따로 모아 보기, 2026-11-28 추가)
-- 사용법: Supabase 대시보드 → SQL Editor → 이 파일 전체를 붙여넣고 Run. 여러 번 실행해도 된다.
--         schema.sql을 먼저 실행한 상태여야 한다(private.session_player 사용).
--
-- 규칙
--  - 로그인한 참가자만. 세션 토큰으로 본인을 확인하고, 본인 목록만 저장·조회·삭제한다.
--  - 저장 이유(여러 개): 1 시총이 높아서 / 2 시총이 낮아서 / 3 종목이 안 외워져서 / 4 기타(메모 50자)
--  - 회사는 종목코드로 구분한다(회사 맞히기는 DART 이름, 시총 게임은 시세 이름이라 이름이 다를 수 있음).
--  - 같은 회사를 다시 저장하면 이유·메모만 바꾼다(처음 저장한 날짜·당시 시총은 유지).
--  - 1인 최대 300개. 테이블은 RLS를 켜고 anon에 권한을 주지 않는다. 아래 RPC 3개만 연다.
--  - 참가자가 삭제되면 저장 목록도 함께 지워진다.
-- =====================================================================

create table if not exists public.saved_companies (
  player_id    uuid not null references public.players(id) on delete cascade,
  stock_code   text not null check (stock_code ~ '^[0-9A-Z]{6}$'),
  name         text not null check (char_length(name) between 1 and 60),
  reasons      int[] not null check (cardinality(reasons) between 1 and 4 and reasons <@ array[1, 2, 3, 4]),
  memo         text check (memo is null or char_length(memo) <= 50),
  market       text check (market is null or market in ('KOSPI', 'KOSDAQ')),
  mcap_at_save bigint check (mcap_at_save is null or mcap_at_save > 0),
  rcept_no     text check (rcept_no is null or rcept_no ~ '^[0-9]{14}$'),
  source       text not null check (source in ('quiz', 'rank')),
  saved_at     timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  primary key (player_id, stock_code)
);
alter table public.saved_companies enable row level security;

revoke all on public.saved_companies from public, anon, authenticated;
grant select, insert, update, delete on public.saved_companies to service_role;

-- 저장(또는 이유 바꾸기)
create or replace function public.save_company(token text, code text, name text, reasons int[], memo text,
                                               market text, mcap bigint, rcept_no text, source text)
returns jsonb
language plpgsql security definer set search_path = '' as $$
#variable_conflict use_variable
declare
  p public.players := private.session_player(token);
  c text := upper(btrim(coalesce(code, '')));
  n text := btrim(coalesce(name, ''));
  r int[] := (select coalesce(array_agg(distinct x order by x), '{}') from unnest(coalesce(reasons, '{}')) x);
  m text := nullif(btrim(coalesce(memo, '')), '');
begin
  if p.id is null then
    return jsonb_build_object('ok', false, 'error', 'SESSION_EXPIRED');
  end if;
  if c !~ '^[0-9A-Z]{6}$' or char_length(n) < 1 or char_length(n) > 60 then
    return jsonb_build_object('ok', false, 'error', 'S_BAD_NAME');
  end if;
  if cardinality(r) = 0 or not (r <@ array[1, 2, 3, 4]) then
    return jsonb_build_object('ok', false, 'error', 'S_NO_REASON');
  end if;
  if m is not null and char_length(m) > 50 then
    return jsonb_build_object('ok', false, 'error', 'S_MEMO_LONG');
  end if;
  if not (4 = any(r)) then
    m := null;   -- 메모는 '기타'를 골랐을 때만
  end if;
  if not exists (select 1 from public.saved_companies s where s.player_id = p.id and s.stock_code = c)
     and (select count(*) from public.saved_companies s where s.player_id = p.id) >= 300 then
    return jsonb_build_object('ok', false, 'error', 'S_FULL');
  end if;
  insert into public.saved_companies(player_id, stock_code, name, reasons, memo, market, mcap_at_save, rcept_no, source)
  values (p.id, c, n, r, m,
          case when market in ('KOSPI', 'KOSDAQ') then market end,
          case when mcap > 0 then mcap end,
          case when rcept_no ~ '^[0-9]{14}$' then rcept_no end,
          case when source in ('quiz', 'rank') then source else 'quiz' end)
  on conflict (player_id, stock_code) do update
    set reasons = excluded.reasons, memo = excluded.memo, updated_at = now(),
        rcept_no = coalesce(excluded.rcept_no, public.saved_companies.rcept_no),
        market = coalesce(excluded.market, public.saved_companies.market);
  return jsonb_build_object('ok', true);
end $$;

-- 내 저장 목록 (최근 저장 순)
create or replace function public.list_saved(token text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare p public.players := private.session_player(token);
begin
  if p.id is null then
    return jsonb_build_object('ok', false, 'error', 'SESSION_EXPIRED');
  end if;
  return jsonb_build_object('ok', true, 'items', coalesce((
    select jsonb_agg(jsonb_build_object('code', s.stock_code, 'name', s.name, 'reasons', s.reasons, 'memo', s.memo,
                                        'market', s.market, 'mcap_at_save', s.mcap_at_save,
                                        'rcept_no', s.rcept_no, 'source', s.source,
                                        'saved_at', s.saved_at) order by s.saved_at desc)
      from public.saved_companies s where s.player_id = p.id), '[]'::jsonb));
end $$;

-- 삭제
create or replace function public.delete_saved(token text, code text) returns jsonb
language plpgsql security definer set search_path = '' as $$
#variable_conflict use_variable
declare p public.players := private.session_player(token);
begin
  if p.id is null then
    return jsonb_build_object('ok', false, 'error', 'SESSION_EXPIRED');
  end if;
  delete from public.saved_companies s where s.player_id = p.id and s.stock_code = upper(code);
  return jsonb_build_object('ok', true);
end $$;

revoke execute on function public.save_company(text, text, text, int[], text, text, bigint, text, text),
                           public.list_saved(text), public.delete_saved(text, text) from public;
grant execute on function public.save_company(text, text, text, int[], text, text, bigint, text, text),
                          public.list_saved(text), public.delete_saved(text, text) to anon, authenticated;
