# 04. Docker Compose 배포 가이드

이 문서는 policy-explorer를 Docker Compose 기반 MSA 환경에 이식하는 방법을 설명합니다. 예시
파일은 [`docker/`](docker/) 폴더에 있습니다:
- [`docker/Dockerfile.fileupload`](docker/Dockerfile.fileupload) — 실서비스 후보
  (`lxp-ollama-qwen-fileupload.py`)
- [`docker/Dockerfile.benchmark`](docker/Dockerfile.benchmark) — 벤치마크 4종 공용
  (빌드 시 `--build-arg SCRIPT_NAME=`으로 선택)
- [`docker/docker-compose.yml`](docker/docker-compose.yml) — Ollama + policy-explorer 예시 구성

> ⚠️ 이 예시들은 **빌드 가능한 초안**이지만, [03-environment-config.md](03-environment-config.md)에서
> 제안한 환경변수 리팩터링이 코드에 반영되기 전까지는 `environment:` 값들이 실제로 적용되지
> 않습니다(코드가 여전히 하드코딩된 값을 사용). 리팩터링 전까지는 "목표 구성을 보여주는
> 참고 자료"로 사용하세요.

## 컨테이너 분리 전략
```
┌─────────────────────────────┐      HTTP (11434)      ┌───────────────────┐
│  policy-explorer 컨테이너     │ ──────────────────────▶ │  ollama 컨테이너    │
│  (FastAPI 래퍼 + 임베딩 +     │                          │  (GPU 필요, LLM    │
│   ChromaDB/BM25)             │                          │   가중치 서빙)      │
└─────────────────────────────┘                          └───────────────────┘
        ▲
        │ HTTP (8001)
        │
   API Gateway / 다른 MSA 서비스
```
- **policy-explorer(래퍼) 컨테이너는 GPU가 필수는 아닙니다.** 실제 LLM 추론은 Ollama/vLLM
  컨테이너가 담당하고, 래퍼는 그 HTTP API를 호출할 뿐입니다. 임베딩(`ko-sroberta-multitask`)만
  래퍼 컨테이너 안에서 직접 계산되며, CPU로도 동작하나 문서량이 많으면 느려질 수 있습니다.
  (필요 시 `HuggingFaceEmbeddings(model_kwargs={"device": "cpu"})`로 명시 고정 — 현재 코드는
  가용 시 자동으로 GPU를 사용하도록 되어 있습니다.)
- **GPU가 꼭 필요한 쪽은 Ollama/vLLM 컨테이너**입니다. `docker-compose.yml` 예시의 `ollama`
  서비스에 `deploy.resources.reservations.devices`로 GPU를 예약했습니다.

## 볼륨 마운트 대상 (상태 보존 필요 데이터)
`policy-explorer` 서비스는 **두 종류의 볼륨**을 구분해서 마운트합니다 (근거:
[09-data-architecture.md](09-data-architecture.md) — SQLite는 네트워크 파일시스템 동시쓰기에
취약해 로컬 볼륨에, 원본 파일은 다른 서비스와의 공유를 위해 NFS 볼륨에 둡니다).

| 볼륨 종류 | 경로 (컨테이너 내부, env 반영 후 기준) | 용도 | 마운트 필요 여부 |
|---|---|---|---|
| **인스턴스 로컬 볼륨** (`policy_explorer_state`) | `${CHROMA_PERSIST_DIR}` (예: `/data/state/chroma_db_fileupload`) | ChromaDB 벡터 데이터 | 필수 — 없으면 재기동 시 업로드 데이터 전부 유실 |
| 〃 | `${METADATA_DB_PATH}` (예: `/data/state/documents.db`) | 문서 메타데이터 SQLite (신규 제안, [09](09-data-architecture.md)) | 필수(도입 시) |
| 〃 | `${LOG_DIR}` (예: `/data/state/logs`) | 성능 로그 | 권장 (컨테이너 로그 드라이버로 대체 가능) |
| **공유 네트워크 볼륨 (NFS)** (`policy_explorer_uploads`) | `${UPLOAD_DIR}` (예: `/data/uploads`, 파일업로드 버전 전용) | 업로드 원본 파일 보관 | 필수 |
| Ollama 전용 로컬 볼륨 | 모델 캐시 (`/root/.ollama`, ollama 공식 이미지 기준) | 다운로드된 모델 가중치 | 필수 — 없으면 재기동마다 재다운로드 |

## 이미지 빌드/기동
```bash
# 1) policy-explorer(파일 업로드 버전) 단독 빌드
docker build -f docs/docker/Dockerfile.fileupload -t policy-explorer:fileupload .

# 2) 벤치마크 조합별 빌드 (예: Ollama+Qwen)
docker build -f docs/docker/Dockerfile.benchmark \
  --build-arg SCRIPT_NAME=lxp-ollama-qwen.py \
  -t policy-explorer-bench:ollama-qwen .

# 3) Docker Compose로 Ollama + policy-explorer 함께 기동
cd docs/docker
docker compose up -d
docker compose logs -f policy-explorer

# 4) Ollama 컨테이너 안에 모델 최초 1회 pull
docker compose exec ollama ollama pull qwen2.5:7b
```

## 포트 매핑
| 서비스 | 컨테이너 내부 포트 | 호스트 노출 포트(예시) |
|---|---|---|
| `ollama` | 11434 | 11434 |
| `policy-explorer` (파일업로드) | 8001 | 8001 |
| `lxp-ollama-qwen`/`lxp-ollama-exaone` 벤치마크 | 8000 | 8000 (Ollama 조합끼리는 동시 기동 시 포트 겹침 — 하나씩만) |
| `lxp-vllm-qwen`/`lxp-vllm-exaone` 벤치마크 | 8080 | 8080 |
| vLLM 서버(공식 `vllm/vllm-openai` 이미지 사용 권장) | 8000 | 8000 |

## vLLM 조합 관련 참고
vLLM 추론 서버 자체는 이 리포지토리의 스크립트로 띄우는 게 아니라, **공식 `vllm/vllm-openai`
이미지**(또는 호스트에서 `vllm serve`, `README.md` 하단 참고)로 별도 기동하고, 이 리포지토리의
`lxp-vllm-*.py` 래퍼는 그 OpenAI 호환 엔드포인트(`VLLM_BASE_URL`)를 바라보게 해야 합니다.
`docker-compose.yml` 하단에 주석 처리된 예시를 참고하세요.

## 다음 문서
- 서버 사양(GPU/디스크/네트워크) 산정 → [05-runtime-requirements.md](05-runtime-requirements.md)
- 보안/데이터 취급 검토 → [06-data-and-security.md](06-data-and-security.md)
- 메타데이터 DB(SQLite)/업로드 스토리지(NFS) 분리 설계 근거 → [09-data-architecture.md](09-data-architecture.md)
