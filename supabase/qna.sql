-- =====================================================================
-- FinancialDetective — "무엇이든 물어보세요" 게시판 (2026-11-24 추가)
-- 사용법: Supabase 대시보드 → SQL Editor → 이 파일 전체를 붙여넣고 Run.
--         schema.sql을 먼저 실행한 상태여야 한다(private.client_ip, private.sha256 사용).
--         여러 번 실행해도 된다.
--
-- 규칙 (2026-11-24 사용자 결정: 질문·조회 모두 로그인 없이 누구나)
--  - 질문은 익명. 개인정보(닉네임·IP)를 질문과 함께 저장하지 않는다.
--    도배 방지 횟수만 attempts 테이블에 'ask:' || sha256(IP) 키로 센다(질문과 연결 안 됨).
--  - 질문 2~300자, 같은 접속에서 1시간에 5개, 답변 대기 질문이 50개면 새 질문을 받지 않음.
--  - 답변은 관리자 PC(scripts/qna.py, service_role 키)에서만 넣는다. 브라우저는 RPC로 읽기만.
--  - 테이블은 RLS를 켜고 anon에 권한을 주지 않는다. 아래 RPC 3개만 연다.
-- =====================================================================

create table if not exists public.questions (
  id          bigint generated always as identity primary key,
  body        text not null check (char_length(body) between 2 and 300),
  asked_at    timestamptz not null default now(),
  answer      jsonb,            -- {"text": "...", "tables": [{"title", "columns": [...], "rows": [[...]]}]}
  answered_at timestamptz,
  hidden      boolean not null default false   -- 관리자가 숨긴 질문(장난·스팸)
);
alter table public.questions enable row level security;

revoke all on public.questions from public, anon, authenticated;
grant select, insert, update, delete on public.questions to service_role;

-- 질문 올리기 (로그인 없음)
create or replace function public.ask_question(body text) returns jsonb
language plpgsql security definer set search_path = '' as $$
#variable_conflict use_variable
declare
  k text := 'ask:' || private.sha256(private.client_ip());
  b text := btrim(coalesce(body, ''));
  a public.attempts;
  new_id bigint;
begin
  if char_length(b) < 2 then
    return jsonb_build_object('ok', false, 'error', 'Q_TOO_SHORT');
  end if;
  if char_length(b) > 300 then
    return jsonb_build_object('ok', false, 'error', 'Q_TOO_LONG');
  end if;
  if (select count(*) from public.questions where answer is null and not hidden) >= 50 then
    return jsonb_build_object('ok', false, 'error', 'Q_QUEUE_FULL');
  end if;
  -- 1시간에 5개: attempts.fail_count = 이번 1시간 동안 올린 수, locked_until = 1시간 창이 끝나는 시각
  select * into a from public.attempts where key = k;
  if a.key is not null and a.locked_until > now() then
    if a.fail_count >= 5 then
      return jsonb_build_object('ok', false, 'error', 'Q_RATE_LIMIT',
                                'wait_seconds', ceil(extract(epoch from a.locked_until - now())));
    end if;
    update public.attempts set fail_count = fail_count + 1 where key = k;
  else
    insert into public.attempts(key, fail_count, locked_until) values (k, 1, now() + interval '1 hour')
    on conflict (key) do update set fail_count = 1, locked_until = now() + interval '1 hour';
  end if;
  insert into public.questions(body) values (b) returning id into new_id;
  return jsonb_build_object('ok', true, 'id', new_id);
end $$;

-- 질문 목록 (최근 100개, 숨긴 질문 제외). 답변 내용은 get_answer로 따로
create or replace function public.list_questions() returns jsonb
language sql security definer set search_path = '' as $$
  select jsonb_build_object('ok', true, 'items', coalesce(jsonb_agg(q order by q.asked_at desc), '[]'::jsonb))
  from (
    select id, body, asked_at, answered_at, (answer is not null) as answered
    from public.questions where not hidden
    order by asked_at desc limit 100
  ) q
$$;

-- 답변 보기
create or replace function public.get_answer(question_id bigint) returns jsonb
language sql security definer set search_path = '' as $$
  select coalesce(
    (select jsonb_build_object('ok', true, 'answer', answer, 'answered_at', answered_at)
       from public.questions where id = question_id and not hidden and answer is not null),
    jsonb_build_object('ok', false, 'error', 'Q_NOT_FOUND'))
$$;

revoke execute on function public.ask_question(text), public.list_questions(), public.get_answer(bigint)
  from public;
grant execute on function public.ask_question(text), public.list_questions(), public.get_answer(bigint)
  to anon, authenticated;
