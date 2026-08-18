# PROJECT_PLAN — LXP Backoffice Policy Assistant

## 1. 프로젝트 목적
사내 인사(HR) 규정 문서가 개정될 때, **신규 규정 내용이 기존 콘텐츠(정책 문서/매뉴얼/FAQ 등)와
충돌하는지 자동으로 검출**해주는 백오피스 어시스턴트를 만드는 것이 목표입니다. 동시에, 이 어시스턴트를
**어떤 LLM 서빙 엔진 + 어떤 로컬 LLM 모델 조합으로 구동할지**를 실측 성능(응답 속도, 동시 부하 처리량)
기준으로 검증·비교하는 것도 이 리포지토리의 핵심 목적입니다. 민감한 사내 문서를 다루므로 외부 API가
아닌 **온프레미스(로컬) LLM 구동**을 전제로 합니다.

## 2. 핵심 파이프라인 (LangGraph)
모든 스크립트가 공유하는 4단계 상태 기반 파이프라인입니다.

```
[신규 규정 문서 입력]
      │
      ▼
① extract_rules      : LLM이 신규 문서에서 핵심 규정(팩트)을 구조화 추출 (keyword, fact)
      │
      ▼
② retrieve_legacy     : 추출된 키워드로 하이브리드 검색(Chroma 벡터 + BM25 키워드, 50:50 앙상블)
      │                  → 관련 있는 기존 문서 조각(old_content)을 조회
      ▼
③ analyze_conflicts   : LLM이 old_content와 new_fact를 비교해 충돌 여부(is_conflict) + 수정 제안 판단
      │
      ▼
④ generate_report     : 충돌이 발견된 항목만 모아 마크다운 표 형태의 리포트 생성
      │
      ▼
[FastAPI 응답: extracted_rules, conflict_count, markdown_report, total_time_seconds]
```

## 3. 구현체 목록 및 역할

| 파일 | 엔진 | 모델 | 데이터 소스 | 포트 |
|---|---|---|---|---|
| `lxp-ollama-qwen.py` | Ollama | qwen2.5:7b | `legacy_documents` 하드코딩 샘플 4건 | 8000 |
| `lxp-ollama-exaone.py` | Ollama | exaone3.5:7.8b | `legacy_documents` 하드코딩 샘플 4건 | 8000 |
| `lxp-vllm-qwen.py` | vLLM (OpenAI 호환) | Qwen2.5-7B-Instruct | `legacy_documents` 하드코딩 샘플 4건 | 8080 |
| `lxp-vllm-exaone.py` | vLLM (OpenAI 호환) | EXAONE-3.0-7.8B-Instruct | `legacy_documents` 하드코딩 샘플 4건 | 8080 |
| `lxp-ollama-qwen-fileupload.py` | Ollama | qwen2.5:7b | **사용자가 업로드한 PDF/DOCX** → 청킹 → ChromaDB(+BM25) RAG | 8001 |

- 앞의 4개(`lxp-*-qwen.py` / `lxp-*-exaone.py`)는 **엔진(Ollama vs vLLM) × 모델(Qwen vs EXAONE)** 4가지
  조합을 동일한 파이프라인으로 비교하기 위한 성능 벤치마크용 구현입니다.
- `lxp-ollama-qwen-fileupload.py`는 하드코딩 샘플 데이터를 실제 업무에 쓸 수 있도록, **PDF/DOCX 파일
  업로드 → 청킹 → RAG 구축**으로 확장한 실사용 지향 버전입니다.
  - 별도 persist 디렉터리(`./chroma_db_fileupload`)와 컬렉션을 사용해 벤치마크용 샘플 데이터와 섞이지
    않도록 격리했습니다.
  - `POST /api/v1/documents/upload`(업로드), `GET /api/v1/documents`(목록 조회),
    `DELETE /api/v1/documents`(초기화), `POST /api/v1/analyze-policy`(분석) 4개 엔드포인트 제공.
  - 현재 지원 확장자: `.pdf`, `.docx`. **Excel(.xlsx/.xls), HWP(.hwp/.hwpx)는 검토 후 이번 범위에서
    제외**(사유는 아래 5번 항목 및 `select_reason.md` 참고).

## 4. 공통 기술 스택
| 구성 요소 | 선택 |
|---|---|
| 오케스트레이션 | LangGraph (`StateGraph`) — 단계별 로깅/성능 측정이 쉬운 명시적 노드 구조 |
| API 서버 | FastAPI + Uvicorn (비동기, 동시 부하 테스트에 적합) |
| 임베딩 | `jhgan/ko-sroberta-multitask` (한국어 특화) |
| 벡터 스토어 | ChromaDB (로컬 persist, 별도 서버 불필요) |
| 검색 전략 | Chroma(의미 검색) + BM25(키워드 검색) `EnsembleRetriever` 50:50 하이브리드 |
| 로깅 | `logs/performance.log` — 노드별 소요 시간 기록 |

각 선택의 상세 근거(왜 Ollama/vLLM 둘 다 만들었는지, 왜 Qwen과 EXAONE을 비교하는지, 왜 하이브리드
검색인지 등)는 **`select_reason.md`**에 실측 데이터와 함께 정리되어 있습니다.

## 5. 지금까지의 의사결정 요약
- **엔진**: 로컬 개발/PoC는 Ollama, 동시 트래픽을 감당해야 하는 운영 환경은 vLLM이 유리 — 동시 요청
  100건 부하 테스트에서 Ollama+Qwen(8255.93초) > vLLM+Qwen(7157.55초) > vLLM+EXAONE(3310.60초, 최속)
  순으로 실측 확인 (`test/2026081*-ASYNC-*.md`).
- **모델**: Qwen2.5-7B를 기준(baseline)으로, 한국어 특화 모델인 EXAONE-3.0/3.5-7.8B를 비교 대상으로
  선정. 두 모델 모두 구조화 출력에서 중국어가 섞이는 이슈가 있어 프롬프트에 "반드시 한국어로만 작성"
  지시문을 명시적으로 강제.
- **파일 업로드 포맷 확장**: DOCX는 `docx2txt`/`Docx2txtLoader`로 경량 지원 추가 완료. Excel은 로더
  방식(경량 openpyxl vs `UnstructuredExcelLoader`) 미결정으로 보류, HWP는 `pyhwp` 유지보수 미비·최신
  버전 파싱 불안정성 및 성숙한 `.hwpx` 라이브러리 부재로 이번 범위에서 제외.
- **버그 수정**: 파일 업로드 RAG의 `DELETE /api/v1/documents`(초기화) 엔드포인트가 Chroma에 문서를
  적재할 때 `ids`를 명시하지 않아 실제로는 아무것도 삭제되지 않던 문제를 발견 → `add_documents(...,
  ids=[...])`로 수정 및 재검증 완료.

## 6. 테스트/검증 자산
- `n_test.py` : 순차 5회 API 호출 테스트 (평균/최소/최대 응답 시간 측정)
- `async_n_test.py` : `aiohttp` 기반 동시 100건 부하 테스트
- `test-result.md`, `test/*.md` : 위 두 테스트의 실행 결과 기록 (엔진×모델 조합별)
- `logs/performance.log` : LangGraph 노드 단위 상세 성능 로그

## 7. 향후 과제 (Not Yet Done)
- [ ] Excel(.xlsx/.xls) 업로드 지원 — 로더 방식(경량 openpyxl 커스텀 vs `UnstructuredExcelLoader`) 결정 필요
- [ ] HWP(.hwp/.hwpx) 업로드 지원 — 별도 파서 구현 필요 여부 재검토
- [ ] vLLM/EXAONE 조합의 우수한 동시 처리 성능이 양자화(`bitsandbytes`) 설정 등 서빙 옵션 때문인지,
      모델 자체 특성 때문인지 분리 검증
- [ ] `lxp-ollama-qwen-fileupload.py`의 vLLM 버전(문서 업로드 + vLLM 서빙) 필요 여부 검토
- [ ] 재업로드 시 동일 파일명 청크 id 충돌(덮어쓰기) 처리 정책 정리
