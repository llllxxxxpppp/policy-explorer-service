# 07. 운영 가이드 (Operations Runbook)

## 헬스체크 엔드포인트 없음
현재 5개 서비스 모두 `/health`, `/healthz` 같은 헬스체크 엔드포인트가 없습니다. MSA
오케스트레이션(로드밸런서, 오토스케일러, Compose의 `healthcheck:`, 향후 Kubernetes
liveness/readiness probe 등)이 서비스 상태를 판단하려면 이런 엔드포인트가 필요합니다.

- **임시 대안**: FastAPI가 기본 제공하는 `/docs`(Swagger UI) 응답 여부로 "프로세스가 떠
  있는지"만 확인 가능하나, 이는 Ollama/vLLM/ChromaDB 등 실제 의존 컴포넌트의 정상 동작을
  보장하지 않습니다.
- **권장 조치**(코드 변경 필요, [08](08-migration-checklist.md) 참고): `GET /health`를
  추가해 최소한 (1) 프로세스 응답 여부, (2) Ollama/vLLM 엔드포인트 접근 가능 여부, (3) Chroma
  컬렉션 접근 가능 여부를 확인하도록 구현.

## 콜드스타트 / 웜업 특성
`test-result.md`/`README.md`에 기록된 대로, 서버를 처음 띄우고 보내는 **첫 API 요청은
모델을 VRAM에 로드하는 시간 때문에 이후 요청보다 눈에 띄게 오래 걸립니다.** 오토스케일링으로
새 인스턴스가 뜨는 시점, 또는 배포 직후 헬스체크가 너무 이르게 "정상"으로 판단하지 않도록
readiness probe의 초기 지연(initial delay)을 충분히 확보해야 합니다.

## 엔진별 동시 처리 한계 (용량 계획 참고)
[`select_reason.md`](../select_reason.md) 1절의 동시 요청 100건 부하 테스트 실측치:

| 엔진 + 모델 | 전체 처리 시간 (100건 동시) |
|---|---|
| Ollama + Qwen2.5-7B | 8255.93초 (가장 느림) |
| vLLM + Qwen2.5-7B | 7157.55초 |
| vLLM + EXAONE-3.0-7.8B | 3310.60초 (가장 빠름) |

운영 환경에서 동시 사용자 트래픽이 예상된다면, Ollama보다 vLLM 기반 배포가 유리합니다. 다만
이 수치는 특정 양자화/서빙 옵션 조합에서 측정된 것이므로, 실제 배포 전 목표 환경에서 재측정을
권장합니다.

## 장애 대응 시 확인 순서
1. **컨테이너/프로세스 상태**: `docker compose ps`, `docker compose logs -f policy-explorer`
2. **성능 로그**: `logs/performance.log` (또는 컨테이너 stdout — [04](04-deployment-guide.md)의
   `LOG_DIR` 설정에 따라 다름). 각 LangGraph 노드(추출/검색/분석/리포트) 단계별 소요 시간이
   기록되므로, 어느 단계에서 지연/에러가 발생했는지 특정할 수 있습니다.
3. **의존 서비스 확인**: Ollama(`curl http://<ollama-host>:11434`) 또는 vLLM
   (`curl http://<vllm-host>:8000/v1/models`)이 응답하는지 확인.
4. **API 자체 에러 응답**: 모든 엔드포인트는 실패 시 `{"detail": "..."}` 형태의 메시지를
   반환하므로([02](02-api-specification.md)), 클라이언트 응답 바디의 `detail`을 우선 확인.
5. **NFS 공유 볼륨 확인** (메타데이터 DB 아키텍처 도입 후, [09](09-data-architecture.md) 참고):
   업로드가 전부 실패하기 시작하면 애플리케이션보다 먼저 NFS 마운트 상태를 의심하세요
   (`mount | grep nfs`, 컨테이너 내부에서 `${UPLOAD_DIR}`에 쓰기 테스트). NFS 서버가 이 서비스의
   새로운 단일 장애점(SPOF)이 됩니다.

## 백업 대상
| 데이터 | 위치 | 비고 |
|---|---|---|
| ChromaDB 벡터 데이터 | `${CHROMA_PERSIST_DIR}` (로컬 볼륨) | 정기 스냅샷 권장 |
| 문서 메타데이터 SQLite (신규 제안) | `${METADATA_DB_PATH}` (로컬 볼륨) | [09](09-data-architecture.md) 도입 후 — 파일 단위 백업으로 충분 (SQLite는 단일 파일) |
| 업로드 원본 파일 | `${UPLOAD_DIR}` (NFS 공유 볼륨) | NFS 서버 자체의 백업 정책을 따름 — 이 서비스와 별개로 NFS 운영 주체와 협의 필요 |
| Ollama 모델 캐시 | `/root/.ollama` (Ollama 컨테이너 볼륨) | 백업보다는 재다운로드가 더 간단할 수 있음 (모델은 재현 가능한 산출물) |

## 멀티 레플리카 관련 주의사항
- **ChromaDB**는 로컬 디스크(SQLite 기반)에 persist되고, **BM25 인덱스는 프로세스 메모리에만
  존재**합니다(`all_chunks` 리스트를 기동 시 Chroma에서 복원). 즉 현재 구조는 **단일 인스턴스
  전제**입니다.
- 파일업로드 버전(`lxp-ollama-qwen-fileupload.py`)을 여러 레플리카로 스케일아웃하면:
  - 레플리카 A에 업로드한 문서가 레플리카 B의 BM25/Chroma 상태에는 반영되지 않을 수 있음
    (같은 볼륨을 공유해도 BM25는 각 프로세스 메모리에 따로 존재).
  - 업로드/초기화(`DELETE /api/v1/documents`) 같은 쓰기 작업은 단일 인스턴스로 라우팅하거나,
    별도의 공유 벡터 DB(예: 외부 Chroma 서버 모드, 또는 Postgres+pgvector 등)로 전환하는 설계
    변경이 필요합니다. 이번 문서 세트에서는 이 사실을 명시하는 데 그치고, 실제 아키텍처 변경은
    범위에 포함하지 않았습니다.

## 다음 문서
- 위에서 언급된 코드 변경 필요 항목들을 실행 체크리스트로 정리 →
  [08-migration-checklist.md](08-migration-checklist.md)
- 메타데이터 DB/업로드 스토리지 설계 전체 → [09-data-architecture.md](09-data-architecture.md)
