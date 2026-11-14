# FinancialDetective — 프로젝트 지침

## 한 줄 요약
DART 재무제표만 보고 상장사를 맞히고(4지선다, 기회 2번), 이어서 그 회사의 시가총액을 추정(최대 5회, ±10% 이내면 정답)하는 **팀 공유용 일일 퀴즈 웹앱**. 오늘의 문제는 **하루 3문제**(팀원 모두 같은 문제)이고 **일간·주간·월간 팀 랭킹**을 보여준다.

## 사용자에 대해
- 투자/PE 실무자. 회계·재무 용어(K-IFRS, 연결/별도, 영업CF 등)는 설명할 필요 없음.
- 코딩은 초보. 터미널 명령을 실행하기 전에 **무엇을 하는 명령인지 한 줄로 설명**할 것.
- 모든 답변은 한국어로.

## 기술 스택 (바꾸려면 먼저 사용자에게 물어볼 것)
- 데이터 수집: Python 3.11+ (`requests`, `python-dotenv`, `supabase` 정도만)
- 화면: 정적 HTML + CSS + 바닐라 JavaScript (React 등 프레임워크·빌드 도구 사용 안 함). Supabase JS는 CDN 스크립트로 불러온다.
- 랭킹·기록 저장: **Supabase 무료 플랜** (Postgres + RPC 함수)
- 배포: GitHub Pages(`docs/` 폴더) + GitHub Actions(매일 1회 문제 생성)
- 개발 환경: Windows + PowerShell. 경로와 명령어는 Windows 기준으로 안내.

## 절대 규칙
1. **비밀 키는 `.env`와 GitHub Secrets에만 둔다.**
   - 비밀: `DART_API_KEY`, `DATA_GO_KR_API_KEY`, Supabase `service_role`(secret) 키
   - 이 키들은 코드, 커밋, `docs/` 아래 파일에 절대 넣지 않는다. `.gitignore`에 `.env`와 `data/raw/`를 반드시 넣는다.
   - 예외: Supabase **anon(publishable) 키와 프로젝트 URL**은 브라우저용으로 설계된 공개 키라 `docs/config.js`에 넣어도 된다. 단, 아래 규칙 2를 지킬 때만.
2. **Supabase의 모든 테이블은 RLS(Row Level Security)를 켠다.** anon 역할에는 테이블 직접 읽기·쓰기를 주지 않고, 정해진 RPC 함수(`SECURITY DEFINER`)만 실행할 수 있게 한다. 테이블 생성 SQL 바로 다음 줄에 `enable row level security`를 쓴다.
3. **오늘의 문제 정답은 브라우저로 보내지 않는다.** 정답 판정(회사, UP/DOWN, 점수 계산)은 모두 Supabase RPC에서 한다. 정답은 GitHub Actions가 `service_role` 키로 `answers` 테이블에 넣는다.
4. **브라우저에서 DART·공공데이터포털 API를 직접 호출하지 않는다.** 모든 외부 API 호출은 `scripts/`의 Python에서만 한다.
5. **API 응답 필드명을 추측하지 않는다.** 처음 쓰는 API는 실제로 1건 호출해 응답을 `data/samples/`에 저장하고, 필드명을 확인한 뒤 코드를 짠다.
6. **호출 한도를 아낀다.** OpenDART는 키당 하루 약 20,000건 한도. 받은 데이터는 `data/raw/`에 캐시하고 다시 호출하지 않는다. 호출 사이에 짧은 대기(예: 0.2초)를 둔다.
7. 금액은 **원 단위 정수**로 저장하고, 화면에는 **억원(천 단위 콤마)**으로 표시한다.
8. 연습 모드 문제(`docs/pool.json`)는 정답을 평문으로 두지 않는다(base64 + 간단한 XOR 정도). 연습 모드는 랭킹에 반영하지 않는다.
9. 날짜 기준은 항상 **한국시간(KST, Asia/Seoul)**. **하루의 경계는 새벽 03:00 KST**(2026-11-14 결정, 03:00~다음날 02:59가 하루). DB는 `private.kst_today()`, Python은 `common.quiz_today()`, 화면은 `kstToday()`로 같은 규칙을 쓴다.
10. 닉네임·PIN 화면에는 "게임용 PIN입니다. 실제 쓰는 비밀번호를 넣지 마세요."라는 안내를 항상 표시한다. 개인정보는 닉네임과 PIN 해시 외에 받지 않는다(이메일·실명·전화번호 수집 금지).
11. 데이터는 팀 내부·비영리 연습용으로만 쓴다. 외부 공개나 수익화가 필요해지면 먼저 사용자에게 알린다(공공데이터 이용허락범위 확인 필요).

## 목표 폴더 구조
```
FinancialDetective/
├─ CLAUDE.md            ← 이 파일 (Claude Code가 자동으로 읽음)
├─ PLAN.md              ← 게임 규칙·랭킹·데이터 설계·단계별 계획
├─ README.md            ← 팀원용 사용법 (Phase 5에서 작성)
├─ .env / .env.example / .gitignore / requirements.txt
├─ scripts/
│  ├─ fetch_corp_list.py     # 상장사 목록 + 업종
│  ├─ fetch_financials.py    # 재무제표
│  ├─ fetch_market_cap.py    # 시가총액
│  ├─ build_quiz.py          # 연습 풀 + 내일의 문제 생성
│  ├─ upload_daily.py        # 내일의 문제(재무표+보기)와 정답을 Supabase answers 테이블에 저장
│  ├─ daily_job.py           # Actions가 매일 실행: 시총 수집 → 문제 생성 → 업로드
│  ├─ admin.py               # 관리자용: 팀 코드 설정, PIN 재설정, 닉네임 변경·삭제, 점수 리셋 (로컬 전용)
│  ├─ make_config.py         # docs/config.js 생성 (공개 키만)
│  └─ test_backend.py        # Supabase 보안·로직 테스트
├─ supabase/
│  └─ schema.sql        # 테이블·RLS·RPC 함수 (Supabase SQL Editor에 붙여넣어 실행)
├─ data/
│  ├─ raw/              # API 원본 캐시 (git 제외)
│  └─ samples/          # 필드 확인용 샘플 응답
├─ docs/                # GitHub Pages가 서비스하는 웹 루트
│  ├─ index.html / style.css / app.js
│  ├─ config.js         # Supabase URL + anon 키만
│  ├─ pool.json         # 연습 모드 문제 풀 (정답 인코딩)
│  └─ pool/                 # 연습 문제 (git 제외, Actions가 만들어 배포)
│     (오늘의 문제는 파일로 만들지 않음 — 그날 새벽 3시 이후 RPC로만 내려감)
└─ .github/workflows/daily.yml
```

## 작업 방식
- `PLAN.md`의 Phase 순서대로 진행한다. **한 Phase가 끝나면 멈추고** 결과를 사용자에게 보여준 뒤 다음으로 넘어갈지 확인받는다.
- 진행할 때마다 `PLAN.md`의 체크박스를 갱신한다.
- `PLAN.md`의 "결정 필요" 항목은 적힌 기본값으로 진행하되, 해당 기능을 만들 때 사용자에게 한 번 확인한다.
- Supabase 대시보드에서 사용자가 직접 해야 하는 일(프로젝트 생성, SQL 실행, 키 복사)은 클릭 순서대로 안내한다.

@PLAN.md
