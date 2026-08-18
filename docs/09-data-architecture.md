# 09. 문서 메타데이터 & 파일 스토리지 아키텍처

이전 버전의 문서 세트(01~08)에는 **업로드된 문서를 어떻게 관리하는지**에 대한 데이터 계층
설계가 빠져 있었습니다. 이 문서는 그 공백을 메우기 위해, (1) 문서 메타데이터를 저장할 DB와
(2) 원본 물리 파일을 저장할 공간을 어떻게 둘지 정리합니다.

> 결정된 방향(사용자 확인): 메타데이터 DB는 **SQLite**(경량, 단일 인스턴스 전제 유지),
> 물리 파일 저장 공간은 **공유 네트워크 볼륨(NFS)**을 사용합니다. 아래 내용은 **제안 설계**이며
> 코드에는 아직 반영되지 않았습니다 — 실행 항목은
> [08-migration-checklist.md](08-migration-checklist.md)에 추가했습니다.

## 왜 필요한가 — 현재 상태의 공백
`lxp-ollama-qwen-fileupload.py`를 코드 기준으로 확인한 현재 상태:

- **문서 단위 메타데이터가 없습니다.** "메타데이터"라고 부를 수 있는 것은 각 **청크**의
  `metadata["source"]`(파일명), `metadata["id"]`(`{파일명}::chunk_{i}`)가 전부이며, 이는
  ChromaDB 청크 레코드 안에만 존재합니다(`upload_document`, L356-357, L363). 업로더가 누구인지,
  언제 업로드했는지, 처리 상태(처리 중/완료/실패)가 무엇인지, 체크섬이 무엇인지는 어디에도
  기록되지 않습니다.
- **`GET /api/v1/documents`는 매번 메모리를 순회해 집계합니다.** 별도 조회 테이블 없이
  `all_chunks`(프로세스 메모리 리스트)를 순회하며 `source`별 청크 개수만 셉니다
  (`list_documents`, L391-394). 서버가 재시작되면 `all_chunks`는 Chroma에 저장된 청크
  메타데이터로부터 다시 복원됩니다(`_load_persisted_chunks_on_startup`) — 즉 "문서(파일)"라는
  단위가 시스템에 1급 개념으로 존재하지 않고, 청크 메타데이터로부터 매번 역산됩니다.
- **동일 파일명 재업로드 시 원본 파일과 메타데이터가 조용히 덮어써집니다.**
  `save_path = os.path.join(UPLOAD_DIR, file.filename)`(L339)는 항상 같은 파일명이면 같은
  경로에 쓰기 때문에 물리 파일이 덮어써지고, 청크 id도 `{파일명}::chunk_{i}` 규칙이라 새
  업로드분이 이전 업로드분의 id와 충돌합니다. 재업로드가 "새 버전으로 대체"인지 "실수로 같은
  이름을 또 올린 것"인지 구분할 방법이 없습니다.
- **물리 파일 저장 공간이 로컬 디스크 하나뿐입니다.** `UPLOAD_DIR`은 컨테이너 로컬 볼륨이며,
  다른 서비스(예: 원본 문서를 다운로드/미리보기해야 하는 별도 MSA 서비스)가 이 파일에 접근할
  방법이 없습니다.

## 제안 아키텍처

```
                 ┌───────────────────────────────────────────┐
 업로드 요청 ───▶ │ policy-explorer (FastAPI)                   │
                 │                                             │
                 │  1) SQLite documents 테이블에 레코드 생성      │──▶ [SQLite: documents.db]
                 │     (status=uploading, id=UUID 발급)          │     (문서 단위 메타데이터,
                 │                                             │      단일 인스턴스 로컬 파일)
                 │  2) 원본 파일을 안전한 키로 저장               │──▶ [NFS 공유 볼륨: /data/uploads]
                 │     ({document_id}/{original_filename})      │     (원본 파일, 여러 서비스가
                 │                                             │      공유 접근 가능)
                 │  3) 로더/청킹 → ChromaDB 적재                 │──▶ [ChromaDB: chroma_db_fileupload]
                 │                                             │     (청크 콘텐츠 + 임베딩)
                 │  4) SQLite 레코드 status=ready로 갱신          │
                 │     (실패 시 status=failed + error_message)  │
                 └───────────────────────────────────────────┘
```

### 1) 메타데이터 DB — SQLite
새 DB 서버를 추가로 운영 부담으로 두지 않기 위해 **SQLite 파일 기반**으로 설계합니다. 이는
[07-operations-runbook.md](07-operations-runbook.md)에 이미 명시된 "현재 구조는 단일 인스턴스
전제"라는 제약과도 일관됩니다 — 여러 레플리카로 확장하게 되면 이 SQLite도 함께
PostgreSQL 등으로 승격 검토가 필요합니다(해당 항목은
[08-migration-checklist.md](08-migration-checklist.md)의 🟢 장기 검토 항목으로 등록).

**제안 스키마** (`documents` 테이블 — 문서/파일 단위, 청크 단위 콘텐츠는 계속 ChromaDB가 담당):
```sql
CREATE TABLE documents (
    id              TEXT PRIMARY KEY,       -- UUID
    original_filename TEXT NOT NULL,        -- 사용자가 업로드한 원본 파일명 (표시용)
    storage_key     TEXT NOT NULL UNIQUE,   -- 물리 저장 경로/키 (예: "{id}/{original_filename}")
    content_type    TEXT,                   -- 확장자 기반 (.pdf / .docx)
    size_bytes      INTEGER,
    checksum_sha256 TEXT,                   -- 동일 내용 재업로드 감지용
    status          TEXT NOT NULL,          -- uploading | processing | ready | failed | deleted
    chunk_count     INTEGER DEFAULT 0,
    error_message   TEXT,
    uploaded_by     TEXT,                   -- 인증 도입 후 채워짐 (06-data-and-security.md 참고)
    uploaded_at     TEXT NOT NULL,          -- ISO8601
    updated_at      TEXT NOT NULL,
    deleted_at      TEXT
);
CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_documents_checksum ON documents(checksum_sha256);
```
- `checksum_sha256`으로 **완전히 동일한 파일의 중복 업로드**를 감지해 재처리를 건너뛰거나
  경고할 수 있습니다.
- `storage_key`를 `{document_id}/{original_filename}`처럼 UUID 하위 디렉터리를 두는 방식으로
  설계하면, **파일명 충돌 문제와 [06-data-and-security.md](06-data-and-security.md)의 경로
  순회 취약점을 동시에 완화**할 수 있습니다 (사용자 입력 파일명이 최상위 디렉터리 이름으로
  쓰이지 않음).
- SQLite 파일 자체도 컨테이너 재시작 시 유실되지 않도록 **로컬 상태 볼륨**에 저장해야 합니다
  (아래 볼륨 표 참고). 여러 컨테이너가 같은 SQLite 파일에 동시 쓰기를 하면 파일 잠금 문제가
  발생하므로, **SQLite는 NFS 등 네트워크 파일시스템에 두지 않고 인스턴스 로컬 볼륨에만
  둡니다** — 이것이 원본 파일과 메타데이터 DB의 저장 위치를 분리한 이유입니다.

### 2) 물리 파일 저장 — 공유 네트워크 볼륨 (NFS)
원본 PDF/DOCX 파일은 **NFS 기반 공유 볼륨**에 저장합니다. 로컬 디스크 대비 이점:
- policy-explorer 컨테이너가 재생성되어도 원본 파일이 유지됨 (로컬 볼륨으로도 가능하지만,
  NFS는 호스트가 바뀌어도 유지됨)
- 같은 MSA 안의 다른 서비스(예: 문서 뷰어, 감사 로그 서비스)가 원본 파일에 직접 접근 가능
- 다만 SQLite와 달리 파일은 "쓰기 후 읽기 전용"에 가까운 접근 패턴이라 NFS의 동시 쓰기 잠금
  이슈에서 상대적으로 자유로움

**주의사항** (자세한 내용은 [06-data-and-security.md](06-data-and-security.md) 갱신분 참고):
- NFS는 기본적으로 강력한 인증이 없으므로, 네트워크 레벨에서 접근을 제한(방화벽/사설망)하거나
  NFSv4 + Kerberos 조합을 검토해야 합니다.
- NFS 서버 자체가 새로운 단일 장애점(SPOF)이 되므로, 운영 런북에 NFS 가용성 모니터링을
  추가해야 합니다([07-operations-runbook.md](07-operations-runbook.md) 갱신분 참고).

## 업로드/조회/삭제 API에 대한 영향 (제안, 아직 미구현)
- `POST /api/v1/documents/upload` — 응답에 `document_id`, `status`가 추가될 수 있음
  (현재는 파일명 기준 요약만 반환).
- `GET /api/v1/documents` — 현재는 `[{source, chunk_count}]`뿐이지만, SQLite 도입 후에는
  아래처럼 확장 가능합니다:
  ```json
  [
    {
      "id": "b3f1...": ,
      "original_filename": "규정문서.pdf",
      "status": "ready",
      "chunk_count": 149,
      "size_bytes": 2456123,
      "uploaded_at": "2026-08-18T09:00:00Z"
    }
  ]
  ```
  (이 확장은 [02-api-specification.md](02-api-specification.md)에 "현재 스펙"이 아니라
  "향후 변경 예정"으로만 표시해뒀습니다 — 실제 코드가 바뀌기 전까지 02번 문서의 계약이
  유효합니다.)
- `DELETE /api/v1/documents` — 현재는 전체 초기화만 가능합니다. 문서 단위 삭제
  (`DELETE /api/v1/documents/{document_id}`)가 자연스럽게 추가될 수 있으나, 이는 이번 문서
  세트의 범위를 넘는 API 설계 변경이므로 아이디어로만 남겨둡니다.

## 다른 문서에 반영된 변경사항
- [03-environment-config.md](03-environment-config.md) — `METADATA_DB_PATH` 환경변수 추가
- [04-deployment-guide.md](04-deployment-guide.md), [`docker/docker-compose.yml`](docker/docker-compose.yml) —
  상태 볼륨(SQLite+Chroma+로그)과 업로드 볼륨(NFS)을 분리
- [06-data-and-security.md](06-data-and-security.md) — SQLite/NFS 관련 보안 고려사항 추가
- [07-operations-runbook.md](07-operations-runbook.md) — 백업 대상 및 NFS 장애 대응 추가
- [08-migration-checklist.md](08-migration-checklist.md) — 관련 작업 항목 추가
