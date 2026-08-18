# 02. API 명세 (API Specification)

> 이 문서는 실제 코드([`lxp-ollama-qwen-fileupload.py`](../lxp-ollama-qwen-fileupload.py),
> [`lxp-ollama-qwen.py`](../lxp-ollama-qwen.py) 등)를 근거로 작성되었습니다. 형식적으로 검증된
> 실제 OpenAPI 3.1 스펙은 [`openapi/`](openapi/) 폴더에 JSON으로 첨부되어 있으니, 클라이언트
> 코드 생성(codegen) 등에는 문서 대신 그 파일을 1차 소스로 사용하세요.
>
> - [`openapi/lxp-ollama-qwen.openapi.json`](openapi/lxp-ollama-qwen.openapi.json) — 벤치마크
>   4종 대표 스펙 (`lxp-ollama-exaone.py`/`lxp-vllm-qwen.py`/`lxp-vllm-exaone.py`도 엔드포인트
>   구조가 완전히 동일하여 대표 1개만 첨부했습니다. `engine`/`model` 응답 필드의 값만 다릅니다.)
> - [`openapi/lxp-ollama-qwen-fileupload.openapi.json`](openapi/lxp-ollama-qwen-fileupload.openapi.json)
>   — 파일 업로드 RAG 버전(실서비스 후보) 전체 스펙

## 공통 사항
- 모든 응답은 `application/json`.
- 별도 `response_model`이 지정되지 않은 엔드포인트(`analyze-policy`, `upload_document`,
  `reset_documents`)는 OpenAPI 스펙상 200 응답 스키마가 비어 있습니다(FastAPI가 자동 추론하지
  못함). 아래 표의 응답 예시는 **실제 코드 반환값 기준**입니다.
- **인증 없음.** 현재 어떤 엔드포인트에도 인증/인가가 걸려 있지 않습니다. MSA 게이트웨이 레벨에서
  반드시 보강해야 합니다 (→ [06-data-and-security.md](06-data-and-security.md)).
- 에러 형식: 검증 실패(422)는 FastAPI 표준 `HTTPValidationError`(`detail: [{loc, msg, type}]`),
  그 외 비즈니스 에러는 `HTTPException`을 통해 `{"detail": "<메시지>"}` 형태(400/500)로 반환됩니다.

---

## A. 전 서비스 공통 — 규정 충돌 분석

### `POST /api/v1/analyze-policy`
5개 서비스 모두 동일한 계약을 갖습니다. 다만 검색 대상 문서(②단계)가 벤치마크 4종은 하드코딩
샘플 4건, 파일업로드 버전은 사용자가 업로드한 문서라는 점만 다릅니다.

**Request**
```json
{ "new_policy_text": "2026년 신규 인사 규정 안내입니다. 반차 사용 기준 시간을 4.5시간으로 변경합니다." }
```

**Response `200`** (코드 기준, 파일업로드 버전은 `documents_in_store` 필드가 추가됨 —
[`lxp-ollama-qwen-fileupload.py:426-437`](../lxp-ollama-qwen-fileupload.py#L426-L437)):
```json
{
  "status": "success",
  "engine": "Ollama",
  "model": "qwen2.5:7b",
  "total_time_seconds": 12.34,
  "documents_in_store": 150,
  "extracted_rules": [
    { "keyword": "반차", "fact": "반차 사용 기준 시간을 4.5시간으로 변경" }
  ],
  "conflict_count": 1,
  "markdown_report": "## 🚨 사내 콘텐츠 규정 충돌 검출 리포트\n..."
}
```
> `documents_in_store`는 `lxp-ollama-qwen.py` 등 벤치마크 4종에는 없습니다.

**Response `500`**: LLM 호출 실패, 파싱 오류 등 — `{"detail": "<에러 메시지>"}`

**참고 (코드 위치)**
- 벤치마크: [`lxp-ollama-qwen.py:248-249`](../lxp-ollama-qwen.py#L248-L249)
- 파일업로드: [`lxp-ollama-qwen-fileupload.py:416-417`](../lxp-ollama-qwen-fileupload.py#L416-L417)

---

## B. 파일 업로드 RAG 버전 전용 (`lxp-ollama-qwen-fileupload.py`)

### `POST /api/v1/documents/upload`
PDF 또는 DOCX 문서를 업로드하면 청킹 후 ChromaDB(+BM25)에 적재합니다.
([`lxp-ollama-qwen-fileupload.py:324-325`](../lxp-ollama-qwen-fileupload.py#L324-L325))

**Request**: `multipart/form-data`, 필드명 `file` (지원 확장자: `.pdf`, `.docx`)
```bash
curl -X POST http://localhost:8001/api/v1/documents/upload -F "file=@규정문서.pdf"
```

**Response `200`**
```json
{
  "status": "success",
  "filename": "규정문서.pdf",
  "num_source_documents": 85,
  "num_chunks": 149,
  "total_chunks_in_store": 150,
  "elapsed_seconds": 8.59
}
```

**Response `400`**: 지원하지 않는 확장자, 또는 텍스트 추출 실패
```json
{ "detail": "지원하지 않는 파일 형식입니다 (.xlsx). 업로드 가능한 확장자: .docx, .pdf" }
```

> ⚠️ 업로드된 `file.filename`이 저장 경로 생성에 그대로 쓰이며 별도 검증이 없습니다. 경로 순회
> 취약점에 대한 상세 내용은 [06-data-and-security.md](06-data-and-security.md)를 참고하세요.

### `GET /api/v1/documents`
현재 적재된 문서(출처)별 청크 개수를 조회합니다.
([`lxp-ollama-qwen-fileupload.py:390-391`](../lxp-ollama-qwen-fileupload.py#L390-L391))

**Response `200`**
```json
[
  { "source": "규정문서.pdf", "chunk_count": 149 },
  { "source": "sample.docx", "chunk_count": 1 }
]
```

> 💡 **향후 변경 예정 (아직 미구현)**: 문서 메타데이터 DB(SQLite) 도입 후에는 이 응답에
> `id`, `status`, `size_bytes`, `uploaded_at` 등이 추가될 수 있습니다. 위 스키마는 **현재
> 코드 기준 계약**이며, 실제 변경 시점까지는 그대로 유효합니다. 자세한 제안 설계는
> [09-data-architecture.md](09-data-architecture.md)를 참고하세요.

### `DELETE /api/v1/documents`
업로드된 문서를 모두 초기화합니다 (ChromaDB + BM25 인메모리 캐시).
([`lxp-ollama-qwen-fileupload.py:400-401`](../lxp-ollama-qwen-fileupload.py#L400-L401))

**Response `200`**
```json
{ "status": "success", "message": "업로드된 문서를 모두 초기화했습니다." }
```

---

## 다음 문서
- 이 엔드포인트들을 컨테이너 환경에서 어떤 설정으로 띄울지 → [03-environment-config.md](03-environment-config.md)
