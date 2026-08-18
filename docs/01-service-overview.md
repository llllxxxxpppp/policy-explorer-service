# 01. 서비스 개요

## policy-explorer란
**policy-explorer(사내규정 통합탐색기)**는 사내 인사(HR) 규정 문서가 개정될 때, 신규 규정
내용이 기존 정책 문서/매뉴얼/FAQ와 충돌하는지 로컬 LLM을 이용해 자동 검출해주는 백오피스
어시스턴트입니다. 민감한 사내 문서를 다루는 특성상 **외부 LLM API가 아닌 온프레미스(로컬) LLM
구동**을 전제로 설계되었습니다(근거: [`select_reason.md`](../select_reason.md) 2절).

## 5개 서비스 변형과 각각의 역할
현재 리포지토리에는 동일한 파이프라인을 공유하는 5개의 독립 실행 파일이 있습니다. 이들은
"하나의 서비스를 여러 버전으로 배포"하는 것이 아니라, **엔진/모델 조합 성능 비교를 위한
벤치마크 도구 4개**와 **실사용 대상 서비스 1개**로 목적이 다릅니다.

| 파일 | 성격 | 엔진 | 모델 | 데이터 소스 | 기본 포트 |
|---|---|---|---|---|---|
| `lxp-ollama-qwen.py` | 벤치마크 | Ollama | qwen2.5:7b | 하드코딩 샘플 4건 | 8000 |
| `lxp-ollama-exaone.py` | 벤치마크 | Ollama | exaone3.5:7.8b | 하드코딩 샘플 4건 | 8000 |
| `lxp-vllm-qwen.py` | 벤치마크 | vLLM | Qwen2.5-7B-Instruct | 하드코딩 샘플 4건 | 8080 |
| `lxp-vllm-exaone.py` | 벤치마크 | vLLM | EXAONE-3.0-7.8B-Instruct | 하드코딩 샘플 4건 | 8080 |
| **`lxp-ollama-qwen-fileupload.py`** | **실서비스 후보** | Ollama | qwen2.5:7b | **사용자 업로드 PDF/DOCX → RAG** | 8001 |

### MSA 이식 권고
- **`lxp-ollama-qwen-fileupload.py`만이 실제 사용자 데이터(업로드 문서)를 다루는 서비스**이며,
  MSA 환경에 "policy-explorer 서비스"로 노출할 대상은 이 파일이 되어야 합니다.
- 나머지 4개 벤치마크 스크립트는 하드코딩된 샘플 데이터로 엔진/모델 성능을 비교하기 위한
  **내부 QA/성능 검증 도구**입니다. 외부에 API로 노출할 필요는 없지만, "어떤 엔진·모델
  조합을 운영에 쓸지" 결정하는 근거 자료로서 함께 이식(또는 사내 CI/성능 회귀 테스트 도구로
  재활용)하는 것을 권장합니다.
- 다만 5개 파일 모두 **같은 LangGraph 파이프라인 구조**를 공유하므로, 향후 벤치마크 스크립트
  중 하나를 실서비스로 승격하기로 결정이 바뀌어도 아래 문서(특히 03, 04)의 내용을 거의
  그대로 재사용할 수 있습니다.

## 핵심 파이프라인 (LangGraph, 4단계)
```
[신규 규정 문서 텍스트 입력]
      │
      ▼
① extract_rules      LLM이 신규 문서에서 핵심 규정(팩트)을 구조화 추출 (keyword, fact)
      │
      ▼
② retrieve_legacy     하이브리드 검색(Chroma 벡터 검색 + BM25 키워드 검색, 50:50 앙상블)으로
      │                관련된 기존 문서 조각(old_content) 조회
      ▼
③ analyze_conflicts   LLM이 old_content와 new_fact를 비교해 충돌 여부(is_conflict) + 수정 제안 판단
      │
      ▼
④ generate_report     충돌이 발견된 항목만 모아 마크다운 표 형태의 리포트 생성
      │
      ▼
[FastAPI 응답: extracted_rules, conflict_count, markdown_report, total_time_seconds]
```
`lxp-ollama-qwen-fileupload.py`는 ②번 단계에서 조회하는 "기존 문서"가 하드코딩 샘플이 아니라
**사용자가 업로드한 PDF/DOCX를 청킹해 ChromaDB(+BM25)에 적재한 데이터**라는 점만 다릅니다.

## 기술 스택 요약
| 구성 요소 | 선택 |
|---|---|
| 오케스트레이션 | LangGraph (`StateGraph`) |
| API 서버 | FastAPI + Uvicorn |
| LLM 서빙 엔진 | Ollama 또는 vLLM (OpenAI 호환 API) |
| 임베딩 | `jhgan/ko-sroberta-multitask` (한국어 특화) |
| 벡터 스토어 | ChromaDB (로컬 persist) |
| 검색 전략 | Chroma(의미 검색) + BM25(키워드 검색) 하이브리드 (50:50) |
| PDF/DOCX 파싱 | `PyPDFLoader`, `Docx2txtLoader` (`lxp-ollama-qwen-fileupload.py`만 해당) |

각 선택의 상세 근거는 [`select_reason.md`](../select_reason.md)에 실측 성능 데이터와 함께
정리되어 있습니다. 프로젝트 전체 로드맵/향후 과제는 [`PROJECT_PLAN.md`](../PROJECT_PLAN.md)를
참고하세요.

## 업로드 문서의 데이터 계층 (현재 공백)
"실서비스 후보"인 `lxp-ollama-qwen-fileupload.py`는 청크 콘텐츠+임베딩(ChromaDB)만 관리할 뿐,
**문서(파일) 단위 메타데이터를 저장하는 DB나, 원본 파일을 위한 별도 스토리지 전략이 없습니다.**
이 공백과 제안 설계(메타데이터 DB: SQLite, 원본 파일: 공유 네트워크 볼륨)는
[09-data-architecture.md](09-data-architecture.md)에서 다룹니다.

## 다음 문서
- 이 서비스를 API로 호출해야 한다면 → [02-api-specification.md](02-api-specification.md)
- 컨테이너로 이식하기 전 코드 변경 필요 사항 → [03-environment-config.md](03-environment-config.md)
- 업로드 문서 메타데이터/파일 저장 설계 → [09-data-architecture.md](09-data-architecture.md)
