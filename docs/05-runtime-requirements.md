# 05. 실행 전제조건 (Runtime Requirements)

## 소프트웨어
| 항목 | 버전/값 | 근거 |
|---|---|---|
| Python | 3.12 (`.python-version`, `pyproject.toml`의 `requires-python = ">=3.12"`) | |
| 패키지 관리자 | [uv](https://github.com/astral-sh/uv) | `uv.lock`으로 의존성 고정 |
| 핵심 의존성 | `langchain`/`langchain-community`/`langgraph`/`fastapi`/`chromadb`/`sentence-transformers`/`vllm`/`bitsandbytes` 등 (`pyproject.toml` 전체 목록 참고) | |

### ⚠️ 의존성 용량 이슈 (실측)
현재 로컬 `.venv` 크기는 **약 9.1GB**입니다. `vllm`, `bitsandbytes`, `sentence-transformers`
등 CUDA/torch 기반 패키지가 `pyproject.toml`에 **하나의 프로젝트 의존성**으로 묶여 있어서,
Ollama 전용 스크립트(vLLM을 전혀 쓰지 않는 `lxp-ollama-qwen.py`, `lxp-ollama-exaone.py`,
`lxp-ollama-qwen-fileupload.py`)를 위한 컨테이너 이미지에도 `vllm`이 그대로 설치되어 이미지가
불필요하게 커집니다. → 이미지 크기를 줄이려면 의존성 그룹 분리가 필요합니다
([08-migration-checklist.md](08-migration-checklist.md) 참고).

## 하드웨어 (GPU/VRAM)
`README.md`에 기록된 실제 서빙 옵션 기준입니다.

| 모델 | 엔진 | 양자화 | GPU 메모리 사용률 설정 | `max-model-len` |
|---|---|---|---|---|
| Qwen2.5-7B-Instruct | vLLM | bitsandbytes | 0.8 | 2048 |
| EXAONE-3.0-7.8B-Instruct | vLLM | bitsandbytes | 0.8~0.9 | 2048~4096 |
| qwen2.5:7b | Ollama | Ollama 자체 양자화(GGUF, 기본값) | - | - |
| exaone3.5:7.8b | Ollama | Ollama 자체 양자화(GGUF, 기본값) | - | - |

- 7~8B급 모델을 `bitsandbytes` 8bit/4bit 양자화로 서빙하는 것을 전제로 하므로, **최소 12GB
  이상의 VRAM을 갖춘 GPU**(예: RTX 3060 12GB 이상)를 권장합니다. 정확한 최소 사양은 실제
  배포 전 목표 `max-model-len`/`max-num-seqs`로 재측정이 필요합니다.
- 임베딩 모델(`jhgan/ko-sroberta-multitask`)은 CPU로도 동작하나, 업로드 문서량이 많을수록
  청킹 임베딩 속도가 느려집니다.
- vLLM/Ollama 각 엔진의 동시 처리량 차이는 [`select_reason.md`](../select_reason.md) 1절의
  실측 데이터를 참고해 용량 산정에 반영하세요 (동시 요청 100건 기준 vLLM+EXAONE이 가장
  빠르고 Ollama+Qwen이 가장 느림).

## 네트워크/디스크 (최초 기동 시)
| 항목 | 필요 이유 |
|---|---|
| HuggingFace Hub 접근 (`huggingface.co`) | `jhgan/ko-sroberta-multitask` 임베딩 모델 최초 다운로드 (약 400MB 내외). 폐쇄망 환경이라면 사전에 모델을 다운로드해 로컬 캐시(`HF_HOME`)로 볼륨 마운트해야 합니다. |
| Ollama 모델 레지스트리 접근 | `ollama pull qwen2.5:7b`, `ollama pull exaone3.5:7.8b` — 모델당 수 GB (Ollama 컨테이너의 `/root/.ollama` 볼륨에 영구 저장 필요, [04](04-deployment-guide.md) 참고) |
| HuggingFace 모델 저장소 접근 (vLLM) | `Qwen/Qwen2.5-7B-Instruct`, `LGAI-EXAONE/EXAONE-3.0-7.8B-Instruct` 원본 가중치 다운로드 (수 GB~십수 GB) |
| 디스크 여유 공간 | 모델 가중치 + Docker 이미지 레이어(`vllm` 포함 시 이미지 자체가 수 GB) + ChromaDB 데이터 + uv 패키지 캐시를 고려해 **최소 50GB 이상** 여유 공간 권장 |

## 다음 문서
- 보안/데이터 취급 검토 → [06-data-and-security.md](06-data-and-security.md)
