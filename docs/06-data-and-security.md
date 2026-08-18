# 06. 데이터 취급 및 보안 (Data & Security)

## 왜 온프레미스(로컬) LLM만 쓰는가
policy-explorer는 사내 인사(HR) 규정이라는 민감한 문서를 다룹니다. 그래서 처음부터 OpenAI 등
외부 LLM API가 아니라 **로컬에서 구동되는 Ollama/vLLM**만을 후보로 검토했습니다. 자세한 근거는
[`select_reason.md`](../select_reason.md) 2절을 참고하세요. MSA로 이식할 때도 이 전제(문서
원문이 외부 네트워크로 나가지 않는 것)를 유지해야 합니다 — LLM 서빙 엔드포인트를 클라우드
API로 교체하는 결정을 내린다면 이 문서의 전제가 깨지므로 별도 보안 검토가 필요합니다.

## 🚨 발견된 취약점: 경로 순회 (Path Traversal)
`lxp-ollama-qwen-fileupload.py`의 업로드 엔드포인트는 클라이언트가 보낸 `file.filename`을
검증 없이 그대로 저장 경로 생성에 사용합니다.

```python
# lxp-ollama-qwen-fileupload.py:339
save_path = os.path.join(UPLOAD_DIR, file.filename)
```

`file.filename`은 HTTP 요청의 `multipart/form-data` 필드 값으로, **클라이언트가 임의로 지정할
수 있는 신뢰할 수 없는 입력**입니다. 예를 들어 `filename="../../../etc/cron.d/evil"`처럼
`..`가 포함된 파일명을 보내면 `UPLOAD_DIR` 바깥의 임의 경로에 파일을 쓸 수 있습니다
(`os.path.join`은 `..`를 정규화하지 않습니다).

- **위험도**: 로컬 프로토타입 단계에서는 신뢰된 사용자만 접근했으므로 실질적 위험이 낮았지만,
  MSA 환경에서 다른 서비스/게이트웨이를 통해 외부 요청을 받게 되면 **임의 경로 파일 쓰기로
  이어질 수 있는 실질적 취약점**입니다.
- **권장 조치** (아직 코드에 적용하지 않음 — [08-migration-checklist.md](08-migration-checklist.md)
  작업 항목):
  1. `file.filename`에서 `os.path.basename()`으로 경로 구분자를 제거하고,
  2. 화이트리스트 문자(영숫자/한글/`.`/`_`/`-`)만 허용하도록 검증하거나 서버가 생성한 UUID를
     실제 저장 파일명으로 사용하고 원본 파일명은 메타데이터로만 보관.

## 인증/인가 없음
현재 모든 엔드포인트(`/api/v1/analyze-policy`, `/api/v1/documents*`)에 인증/인가가 전혀
없습니다. 로컬 단독 실행 프로토타입에서는 문제가 없었지만, MSA 환경에서는 다음 중 하나가
반드시 필요합니다.
- API 게이트웨이/서비스 메시 레벨에서 mTLS 또는 내부 서비스 토큰으로 접근 제어
- 또는 애플리케이션 레벨에 인증 미들웨어 추가 (현재 코드에는 없음)

또한 업로드/초기화(`DELETE /api/v1/documents`)처럼 상태를 바꾸는 엔드포인트에 대해 별도의
인가(누가 규정 문서를 업로드/삭제할 수 있는지) 정책도 함께 설계해야 합니다.

## 로그에 남는 정보
`logs/performance.log`를 실제 코드 기준으로 점검한 결과:
- **규정 원문 내용(`old_content`, `new_fact`, 업로드 문서 본문)은 로그에 기록되지 않습니다.**
  로그에는 키워드, 소요 시간, 엔진/모델명, 청크 개수 등 메타 정보만 남습니다.
- **업로드 파일명(`file.filename`)은 로그에 그대로 노출됩니다**
  (`lxp-ollama-qwen-fileupload.py:371` 등). 파일명 자체에 민감한 정보(예: 특정 인물명이 포함된
  파일명)가 있을 수 있으므로, 로그 접근 통제 및 보존 기간 정책이 필요합니다.

## 데이터 저장 위치
| 데이터 | 저장 위치 | 비고 |
|---|---|---|
| 업로드 원본 파일 | `./uploaded_documents/` (로컬 디스크, 평문) — 이식 후 NFS 공유 볼륨(`UPLOAD_DIR`) | 암호화 미적용 |
| 벡터/청크 데이터 | `./chroma_db_fileupload/` (로컬 디스크 SQLite 기반) | 암호화 미적용, 접근 통제 없음 |
| 벤치마크용 샘플 데이터 | `./chroma_db/` | 하드코딩 샘플이라 민감정보 아님 |
| 문서 메타데이터 (신규 제안) | SQLite 파일(`METADATA_DB_PATH`) | 아직 미구현 — [09-data-architecture.md](09-data-architecture.md) 참고 |

컨테이너 이식 시 이 디렉터리들은 볼륨으로 마운트되므로([04](04-deployment-guide.md)), 호스트/
스토리지 레벨의 접근 통제와 백업 정책도 함께 검토해야 합니다.

## 메타데이터 DB(SQLite) / 업로드 스토리지(NFS) 관련 추가 보안 고려사항
[09-data-architecture.md](09-data-architecture.md)에서 제안한 구조를 실제로 도입할 경우
추가로 검토해야 할 사항입니다.
- **SQLite 파일 접근 통제**: `documents.db`에는 (인증 도입 후) `uploaded_by` 등 사용자 식별
  정보가 담기게 됩니다. 컨테이너 파일 권한을 애플리케이션 실행 사용자로 제한하고, 백업 시
  이 파일도 접근 통제 대상에 포함해야 합니다.
- **SQLite를 NFS에 두지 않는 이유가 곧 보안 이유이기도 함**: 네트워크 파일시스템 위의 SQLite는
  동시쓰기 시 파일 잠금이 깨지며 데이터가 손상될 수 있어, 무결성 관점에서도 로컬 볼륨 고정이
  맞습니다.
- **NFS 인증/암호화 부재**: 표준 NFSv3는 강력한 인증이 없고 트래픽이 평문입니다. 사내 규정
  원본 파일이 오가는 경로이므로, 최소한 사설망/방화벽으로 NFS 서버 접근을 제한하고, 가능하면
  NFSv4 + Kerberos(`sec=krb5p`) 또는 IPsec으로 암호화를 검토해야 합니다.
- **NFS 서버가 새로운 신뢰 경계**: NFS 서버 운영 주체가 이 서비스 팀이 아니라면(다른 프로젝트의
  공용 인프라), 그 서버의 접근 통제 정책이 곧 policy-explorer 데이터의 보안 수준을 결정하게
  됩니다 — 이식 전에 반드시 확인이 필요합니다.

## 다음 문서
- 운영 중 장애 대응/헬스체크 → [07-operations-runbook.md](07-operations-runbook.md)
- 위 이슈들을 실제 작업 항목으로 관리 → [08-migration-checklist.md](08-migration-checklist.md)
- 메타데이터 DB/업로드 스토리지 전체 설계 → [09-data-architecture.md](09-data-architecture.md)
