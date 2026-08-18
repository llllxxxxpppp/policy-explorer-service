# 03. 환경 설정 (Environment & Config)

## 현재 상태: 환경변수 기반 설정이 전혀 없음
5개 서비스 모두 포트, 모델명, 엔진 접속 주소, 벡터스토어 경로 등이 **소스코드에 하드코딩**되어
있습니다. 컨테이너 이미지 하나로 여러 환경(로컬/스테이징/운영)에 배포하거나, docker-compose에서
포트/모델을 바꿔가며 띄우려면 이 값들을 환경변수로 뺴는 리팩터링이 **선행**되어야 합니다.

> 🚨 이 문서는 "무엇을 바꿔야 하는지"를 정리한 것이며, **코드는 아직 수정하지 않았습니다.**
> 실제 리팩터링은 [08-migration-checklist.md](08-migration-checklist.md)의 작업 항목으로
> 진행하세요.

## 파일별 하드코딩 값 목록

### 공통 (5개 파일 전체)
| 값 | 위치 (예: `lxp-ollama-qwen.py`) | 제안 환경변수 |
|---|---|---|
| 서비스 포트 | `uvicorn.run(app, host="0.0.0.0", port=8000)` — 파일별 라인 다름(아래 표) | `SERVICE_PORT` |
| 벡터스토어 persist 경로 | `persist_directory = "./chroma_db"` (라인 74~75, 파일마다 조금씩) | `CHROMA_PERSIST_DIR` |
| 임베딩 모델명 | `HuggingFaceEmbeddings(model_name="jhgan/ko-sroberta-multitask")` | `EMBEDDING_MODEL_NAME` |
| 로그 파일 경로 | `logging.FileHandler("logs/performance.log", ...)` | `LOG_DIR` (또는 표준출력만 사용하고 컨테이너 로그 드라이버에 위임 — [04](04-deployment-guide.md) 참고) |

### 서비스별 개별 값

| 파일 | LLM 접속 설정 | 기본 포트 | 비고 |
|---|---|---|---|
| `lxp-ollama-qwen.py` | `ChatOllama(model="qwen2.5:7b", ...)` (L59) — Ollama 호스트는 langchain-ollama 기본값(`http://localhost:11434`) 사용, 별도 지정 없음 | 8000 (L275) | `OLLAMA_MODEL`, `OLLAMA_BASE_URL` 환경변수 제안 |
| `lxp-ollama-exaone.py` | `ChatOllama(model="exaone3.5:7.8b", ...)` (L59) | 8000 (L275) | 위와 동일 |
| `lxp-vllm-qwen.py` | `ChatOpenAI(base_url="http://localhost:8000/v1", model="Qwen/Qwen2.5-7B-Instruct", ...)` (L54-60) | 8080 (L248) | `VLLM_BASE_URL`, `VLLM_MODEL_NAME` 환경변수 제안 |
| `lxp-vllm-exaone.py` | `ChatOpenAI(base_url="http://localhost:8000/v1", model="LGAI-EXAONE/EXAONE-3.0-7.8B-Instruct", ...)` (L55-61) | 8080 (L249) | 위와 동일 |
| `lxp-ollama-qwen-fileupload.py` | `ChatOllama(model="qwen2.5:7b", ...)` (L69) | 8001 (L448) | 추가로 `UPLOAD_DIR = "./uploaded_documents"`(L81), `persist_directory = "./chroma_db_fileupload"`(L99), `COLLECTION_NAME = "uploaded_policy_docs"`(L100) |

또한 각 파일 상단의 `CURRENT_ENGINE`/`CURRENT_MODEL` 상수(예: `lxp-ollama-qwen.py:23-24`)는
로그와 API 응답(`engine`, `model` 필드)에 표기되는 라벨입니다. 코드를 바꾸지 않고 모델을
교체하면 이 라벨이 실제 모델과 어긋나게 되므로, 환경변수화 시 함께 반영해야 합니다.

## 제안 환경변수 전체 목록

| 환경변수 | 설명 | 예시 값 |
|---|---|---|
| `SERVICE_PORT` | FastAPI/Uvicorn 리슨 포트 | `8000` |
| `OLLAMA_BASE_URL` | Ollama 서버 주소 (컨테이너 분리 시 서비스명으로) | `http://ollama:11434` |
| `OLLAMA_MODEL` | Ollama에 로드할 모델 태그 | `qwen2.5:7b` |
| `VLLM_BASE_URL` | vLLM OpenAI 호환 엔드포인트 | `http://vllm:8000/v1` |
| `VLLM_MODEL_NAME` | vLLM에 서빙 중인 모델 식별자 | `Qwen/Qwen2.5-7B-Instruct` |
| `EMBEDDING_MODEL_NAME` | HuggingFace 임베딩 모델 | `jhgan/ko-sroberta-multitask` |
| `CHROMA_PERSIST_DIR` | ChromaDB 데이터 저장 경로 (인스턴스 로컬 볼륨 — 아래 참고) | `/data/state/chroma_db_fileupload` |
| `METADATA_DB_PATH` | 문서 메타데이터 SQLite 파일 경로 (인스턴스 로컬 볼륨, 파일업로드 버전 전용, 신규 제안) | `/data/state/documents.db` |
| `UPLOAD_DIR` | 업로드 원본 파일 저장 경로 (공유 네트워크 볼륨(NFS) — 아래 참고, 파일업로드 버전 전용) | `/data/uploads` |
| `LOG_DIR` | 성능 로그 저장 경로 (또는 stdout 전환) | `/data/state/logs` |
| `CURRENT_ENGINE` / `CURRENT_MODEL` | API 응답/로그 라벨 | `Ollama` / `qwen2.5:7b` |

> 💡 `CHROMA_PERSIST_DIR`/`METADATA_DB_PATH`/`LOG_DIR`는 **인스턴스 로컬 볼륨**에,
> `UPLOAD_DIR`만 **NFS 공유 볼륨**에 두는 이유(SQLite의 네트워크 파일시스템 동시쓰기 잠금
> 이슈 등)는 [09-data-architecture.md](09-data-architecture.md)에 정리했습니다.

## 다음 문서
- 위 환경변수들을 실제 docker-compose 서비스 정의에 어떻게 주입하는지 →
  [04-deployment-guide.md](04-deployment-guide.md)
- 메타데이터 DB/업로드 스토리지 설계 근거 → [09-data-architecture.md](09-data-architecture.md)
