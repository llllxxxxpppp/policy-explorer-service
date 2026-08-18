# uvicorn 실행 명령어
- ollama
uv run uvicorn main:app --host 0.0.0.0 --port 8000

curl http://localhost:11434
ps aux | grep ollama

sudo systemctl stop ollama
sudo killall ollama

nvidia-smi

- vLLM
uv run uvicorn lxp-vllm-exaone:app --host 0.0.0.0 --port 8080
uv run uvicorn lxp-vllm-qwen:app --host 0.0.0.0 --port 8080
uv run uvicorn lxp-ollama-qwen:app --host 0.0.0.0 --port 8080

# 테스트 진행
'''
💡 측정 시 주의사항 (Warm-up)
처음 서버를 켜고 첫 번째 API 요청(1/5)을 보낼 때는 시간이 유독 오래 걸립니다. (Ollama가 하드디스크에 있는 모델을 VRAM으로 불러오는 시간, 코드 초기 컴파일 시간 등이 포함되기 때문입니다).

따라서 보다 정확한 평균 성능을 측정하시려면, 테스트를 한 번 돌려서 모델을 예열(Warm-up)시킨 후, 두 번째 돌린 테스트의 통계 결과를 기준점으로 잡으시는 것이 좋습니다.
'''

- n_test.py 실행
python n_test.py

# ollama-qwen 실행

# vLLM - EXAONE 실행
# bitsandbytes 패키지가 추가로 필요합니다 (압축용)
uv pip install bitsandbytes

vllm serve "LGAI-EXAONE/EXAONE-3.0-7.8B-Instruct" \
  --port 8000 \
  --trust-remote-code \
  --quantization bitsandbytes \
  --load-format bitsandbytes \
  --gpu-memory-utilization 0.85 \
  --max-model-len 4096

uv run vllm serve "LGAI-EXAONE/EXAONE-3.0-7.8B-Instruct" \
  --port 8000 \
  --trust-remote-code \
  --quantization bitsandbytes \
  --load-format bitsandbytes \
  --gpu-memory-utilization 0.9 \
  --max-model-len 2048 \
  --enforce-eager

uv run vllm serve "LGAI-EXAONE/EXAONE-3.0-7.8B-Instruct" \
  --port 8000 \
  --trust-remote-code \
  --quantization bitsandbytes \
  --load-format bitsandbytes \
  --gpu-memory-utilization 0.8 \
  --max-model-len 2048 \
  --enforce-eager \
  --max-num-seqs 16

uv run vllm serve "Qwen/Qwen2.5-7B-Instruct" \
  --port 8000 \
  --trust-remote-code \
  --quantization bitsandbytes \
  --load-format bitsandbytes \
  --gpu-memory-utilization 0.8 \
  --max-model-len 2048 \
  --enforce-eager \
  --max-num-seqs 16

# =========================================================
# 엔진 / 모델 조합별 실행 방법
# =========================================================
# 💡 아래 5가지 조합은 모두 동일한 LangGraph 파이프라인(규정 추출 → 하이브리드 검색 →
#    충돌 분석 → 리포트 생성)을 사용하며, "엔진(Ollama/vLLM) × 모델(Qwen/EXAONE)" +
#    "파일 업로드 RAG" 버전을 실측 비교하기 위해 나뉘어 있습니다. (자세한 채택 이유는
#    select_reason.md, 전체 개요는 PROJECT_PLAN.md 참고)

## 1) Ollama + Qwen2.5-7B (`lxp-ollama-qwen.py`, 포트 8000)
```bash
# 1. Ollama 구동 확인 (미실행 시 `ollama serve` 또는 시스템 서비스로 기동)
curl http://localhost:11434

# 2. 모델 준비 (최초 1회)
ollama pull qwen2.5:7b

# 3. API 서버 실행
uv run python lxp-ollama-qwen.py
# 또는
uv run uvicorn lxp-ollama-qwen:app --host 0.0.0.0 --port 8000

# 4. 성능 테스트
uv run python n_test.py           # 순차 5회
uv run python async_n_test.py     # 동시 100건 부하
```
> 💡 `n_test.py`/`async_n_test.py`의 `API_URL`은 기본값이 `:8080`입니다. 8000번 포트로
> 띄운 Ollama 조합을 테스트하려면 두 스크립트의 `API_URL`을 `http://localhost:8000/...`로
> 먼저 바꿔주세요.

## 2) Ollama + EXAONE-3.5-7.8B (`lxp-ollama-exaone.py`, 포트 8000)
```bash
curl http://localhost:11434

ollama pull exaone3.5:7.8b

uv run python lxp-ollama-exaone.py
# 또는
uv run uvicorn lxp-ollama-exaone:app --host 0.0.0.0 --port 8000

uv run python n_test.py
uv run python async_n_test.py
```
> 🚨 Ollama 두 스크립트 모두 기본 포트가 8000이므로, 두 조합을 동시에 띄우려면 한쪽의
> `--port`를 바꿔서 실행해야 합니다. (`n_test.py`/`async_n_test.py`의 `API_URL` 포트도
> 위 1번과 동일하게 맞춰주세요.)

## 3) vLLM + Qwen2.5-7B-Instruct (`lxp-vllm-qwen.py`, 포트 8080)
```bash
# 1. vLLM 서버를 먼저 8000번 포트로 기동 (양자화 설정은 위 "vLLM - EXAONE/Qwen 실행" 섹션 참고)
uv run vllm serve "Qwen/Qwen2.5-7B-Instruct" \
  --port 8000 \
  --trust-remote-code \
  --quantization bitsandbytes \
  --load-format bitsandbytes \
  --gpu-memory-utilization 0.8 \
  --max-model-len 2048 \
  --enforce-eager \
  --max-num-seqs 16

# 2. (새 터미널) FastAPI 래퍼 서버 실행 — 8000번(vLLM)과 겹치지 않도록 8080번 사용
uv run python lxp-vllm-qwen.py
# 또는
uv run uvicorn lxp-vllm-qwen:app --host 0.0.0.0 --port 8080

# 3. 성능 테스트 (API_URL이 8080을 가리키는지 확인)
uv run python n_test.py
uv run python async_n_test.py
```

## 4) vLLM + EXAONE-3.0-7.8B-Instruct (`lxp-vllm-exaone.py`, 포트 8080)
```bash
# bitsandbytes 패키지가 추가로 필요합니다 (압축용, 최초 1회)
uv pip install bitsandbytes

uv run vllm serve "LGAI-EXAONE/EXAONE-3.0-7.8B-Instruct" \
  --port 8000 \
  --trust-remote-code \
  --quantization bitsandbytes \
  --load-format bitsandbytes \
  --gpu-memory-utilization 0.85 \
  --max-model-len 4096

uv run python lxp-vllm-exaone.py
# 또는
uv run uvicorn lxp-vllm-exaone:app --host 0.0.0.0 --port 8080

uv run python n_test.py
uv run python async_n_test.py
```

## 5) Ollama + Qwen2.5-7B + 파일 업로드 RAG (`lxp-ollama-qwen-fileupload.py`, 포트 8001)
샘플 데이터 대신 사용자가 업로드한 PDF/DOCX 문서를 청킹해 ChromaDB(+BM25)에 적재하고,
그 문서를 기반으로 규정 충돌을 검출하는 버전입니다.
```bash
curl http://localhost:11434
ollama pull qwen2.5:7b

uv run python lxp-ollama-qwen-fileupload.py
# 또는
uv run uvicorn lxp-ollama-qwen-fileupload:app --host 0.0.0.0 --port 8001

# 문서 업로드 (PDF 또는 DOCX)
curl -X POST http://localhost:8001/api/v1/documents/upload \
  -F "file=@/path/to/규정문서.pdf"

# 업로드된 문서 목록 확인
curl http://localhost:8001/api/v1/documents

# 업로드 문서 전체 초기화
curl -X DELETE http://localhost:8001/api/v1/documents

# 규정 충돌 분석 (업로드된 문서를 대상으로 검색)
curl -X POST http://localhost:8001/api/v1/analyze-policy \
  -H "Content-Type: application/json" \
  -d '{"new_policy_text": "반차 사용 기준 시간을 4.5시간으로 변경합니다."}'
```
> 🚨 Excel(.xlsx/.xls), HWP(.hwp/.hwpx) 업로드는 아직 지원하지 않습니다 (사유는
> select_reason.md 참고).