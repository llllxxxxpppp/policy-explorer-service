# 08. 이식 체크리스트 (Migration Checklist)

이 문서는 01~07번 문서에서 식별된 "MSA 이식 전 실제로 해야 할 작업"을 실행 가능한 체크리스트로
모은 것입니다. **이번 작업 범위에는 코드 변경이 포함되지 않으며, 아래 항목은 모두 향후 별도
승인 후 진행할 작업입니다.**

## 🔴 필수 (이식 전 반드시 처리)
- [ ] **경로 순회 취약점 수정** — `lxp-ollama-qwen-fileupload.py:339`의
      `os.path.join(UPLOAD_DIR, file.filename)`을 `os.path.basename()` + 화이트리스트 검증
      (또는 서버 생성 UUID 파일명)으로 교체. ([06-data-and-security.md](06-data-and-security.md))
- [ ] **환경변수화** — 포트, `OLLAMA_BASE_URL`/`OLLAMA_MODEL`, `VLLM_BASE_URL`/`VLLM_MODEL_NAME`,
      `EMBEDDING_MODEL_NAME`, `CHROMA_PERSIST_DIR`, `UPLOAD_DIR`, `LOG_DIR`,
      `CURRENT_ENGINE`/`CURRENT_MODEL`을 5개 스크립트 전체에서 `os.environ.get(...)` 기반으로
      교체. ([03-environment-config.md](03-environment-config.md))
- [ ] **인증/인가 추가** — API 게이트웨이 레벨 mTLS/토큰 인증 도입, 또는 애플리케이션 레벨
      인증 미들웨어 추가. 특히 업로드/초기화(`DELETE /api/v1/documents`) 엔드포인트의 인가
      정책 설계. ([06-data-and-security.md](06-data-and-security.md))
- [ ] **헬스체크 엔드포인트 추가** — `GET /health`에서 프로세스/LLM 엔드포인트/Chroma 접근성
      확인. Docker Compose `healthcheck:` 및 향후 오케스트레이터 probe에 연결.
      ([07-operations-runbook.md](07-operations-runbook.md))
- [ ] **문서 메타데이터 DB(SQLite) 도입** — `documents` 테이블 스키마 적용 후
      `upload_document`/`list_documents`/`reset_documents`를 SQLite 조회 기반으로 전환하고,
      저장 키를 `{document_id}/{original_filename}` 방식으로 바꿔 (1) 동일 파일명 재업로드 시
      원본/청크가 조용히 덮어써지는 문제와 (2) 경로 순회 취약점을 함께 완화.
      ([09-data-architecture.md](09-data-architecture.md))

## 🟡 권장 (품질/운영 개선)
- [ ] **의존성 그룹 분리** — `pyproject.toml`에서 `vllm`/`bitsandbytes`를
      `[project.optional-dependencies]`로 분리해, Ollama 전용 이미지가 불필요하게 vLLM/CUDA
      스택(9.1GB `.venv` 기준 상당 비중)을 포함하지 않도록 개선.
      ([05-runtime-requirements.md](05-runtime-requirements.md))
- [ ] **`.gitignore` 보강** — `chroma_db*/`, `uploaded_documents/`, `logs/` 등 런타임 산출물
      디렉터리를 버전관리 대상에서 제외 (현재 미반영).
- [ ] **임베딩 device 명시** — 래퍼 컨테이너에 GPU가 없는 배포 조합을 고려해
      `HuggingFaceEmbeddings(model_kwargs={"device": "cpu"})`처럼 device를 명시적으로 선택할
      수 있게 옵션화. ([04-deployment-guide.md](04-deployment-guide.md))
- [ ] **구조화 로깅** — 현재 텍스트 포맷 로그를 JSON 구조화 로깅으로 전환하면, MSA 환경의
      중앙 로그 수집(ELK/Loki 등)과의 연동이 쉬워짐.
- [ ] **`response_model` 명시** — `analyze-policy`/`upload_document` 등 응답 모델을 Pydantic
      `response_model`로 선언해 OpenAPI 스펙에 실제 응답 스키마가 드러나도록 개선
      ([02-api-specification.md](02-api-specification.md)).
- [ ] **NFS 공유 볼륨 구성** — 업로드 원본 파일 저장소를 로컬 볼륨에서 NFS 공유 볼륨
      (`docker/docker-compose.yml`의 `policy_explorer_uploads`)으로 전환하고, NFS 서버 가용성
      모니터링을 운영 런북에 반영. NFS 서버 구축/운영 주체를 다른 팀과 사전 협의 필요.
      ([09-data-architecture.md](09-data-architecture.md), [07-operations-runbook.md](07-operations-runbook.md))

## 🟢 장기 검토 (아키텍처 변경 수반)
- [ ] **멀티 레플리카 지원** — BM25 인메모리 상태 + 로컬 Chroma persist 구조를 공유 스토리지
      기반(외부 Chroma 서버 모드, pgvector 등)으로 전환할지 검토.
      ([07-operations-runbook.md](07-operations-runbook.md))
- [ ] **벤치마크 스크립트 운영 방식 결정** — 4개 벤치마크 스크립트를 내부 CI 성능 회귀
      테스트로 재활용할지, 아니면 이식 대상에서 완전히 제외할지 결정.
      ([01-service-overview.md](01-service-overview.md))
- [ ] **Excel/HWP 업로드 지원 여부 재검토** — 현재 PDF/DOCX만 지원 (근거:
      [`select_reason.md`](../select_reason.md) 8절).
- [ ] **문서 단위 삭제 API 검토** — 현재 `DELETE /api/v1/documents`는 전체 초기화만 지원.
      메타데이터 DB 도입 후 `DELETE /api/v1/documents/{document_id}` 같은 단건 삭제 API 추가
      여부 결정. ([09-data-architecture.md](09-data-architecture.md))
- [ ] **메타데이터 DB 확장 검토** — 멀티 레플리카로 확장할 경우 SQLite를 PostgreSQL 등으로
      승격할지 결정. ([09-data-architecture.md](09-data-architecture.md))

## 진행 방법 제안
1. 🔴 항목부터 순서대로 별도 PR/작업으로 진행 (한 항목당 하나의 변경으로 리뷰 용이하게 유지).
2. 각 항목 완료 시 이 체크리스트와 관련 문서(03/06/07)를 함께 업데이트.
3. 🔴 항목이 모두 끝난 뒤 [04-deployment-guide.md](04-deployment-guide.md)의 예시
   docker-compose로 실제 통합 테스트 진행.
