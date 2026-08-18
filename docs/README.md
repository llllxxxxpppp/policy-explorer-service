# policy-explorer 문서 인덱스

이 폴더는 **policy-explorer(사내규정 통합탐색기)** 프로젝트를 다른 프로젝트의 MSA(Docker
Compose 기반) 환경으로 이식하기 위해 필요한 문서 세트입니다. 리포지토리 루트의
[`README.md`](../README.md)(실행 명령어 모음), [`PROJECT_PLAN.md`](../PROJECT_PLAN.md)(전체
개요), [`select_reason.md`](../select_reason.md)(기술 채택 근거)가 "이 프로젝트를 로컬에서
어떻게 만들고 검증했는가"를 다룬다면, 이 폴더는 **"다른 서비스/팀이 이 프로젝트를 어떻게
가져다 쓰는가"**에 초점을 맞춥니다.

## 언제 어떤 문서를 보면 되나요?

| 상황 | 문서 |
|---|---|
| policy-explorer가 뭔지, 어떤 구성요소가 있는지 처음 파악하고 싶다 | [01-service-overview.md](01-service-overview.md) |
| 이 서비스를 호출하는 클라이언트/게이트웨이를 만들어야 한다 | [02-api-specification.md](02-api-specification.md), [`openapi/`](openapi/) |
| 컨테이너로 이식하기 전에 코드에서 무엇을 바꿔야 하는지 알고 싶다 | [03-environment-config.md](03-environment-config.md) |
| Docker Compose로 실제로 띄워야 한다 | [04-deployment-guide.md](04-deployment-guide.md), [`docker/`](docker/) |
| 서버 사양(GPU/디스크/네트워크)을 산정해야 한다 | [05-runtime-requirements.md](05-runtime-requirements.md) |
| 보안 검토/개인정보 취급 여부를 확인해야 한다 | [06-data-and-security.md](06-data-and-security.md) |
| 운영 중 장애 대응, 헬스체크, 스케일링 이슈를 확인해야 한다 | [07-operations-runbook.md](07-operations-runbook.md) |
| 이식 작업을 실제로 진행하며 체크리스트로 관리하고 싶다 | [08-migration-checklist.md](08-migration-checklist.md) |
| 업로드 문서의 메타데이터/원본 파일을 어디에 어떻게 저장할지 궁금하다 | [09-data-architecture.md](09-data-architecture.md) |

## 문서 목록
1. [01-service-overview.md](01-service-overview.md) — 서비스 개요 및 아키텍처
2. [02-api-specification.md](02-api-specification.md) — REST API 계약 (+ `openapi/*.json` 실스펙)
3. [03-environment-config.md](03-environment-config.md) — 하드코딩된 설정값과 환경변수화 제안
4. [04-deployment-guide.md](04-deployment-guide.md) — Docker Compose 배포 가이드 (+ `docker/` 예시 파일)
5. [05-runtime-requirements.md](05-runtime-requirements.md) — 하드웨어/소프트웨어 실행 전제조건
6. [06-data-and-security.md](06-data-and-security.md) — 데이터 취급 및 보안 고려사항
7. [07-operations-runbook.md](07-operations-runbook.md) — 운영/장애 대응 가이드
8. [08-migration-checklist.md](08-migration-checklist.md) — 이식 작업 체크리스트
9. [09-data-architecture.md](09-data-architecture.md) — 문서 메타데이터 DB(SQLite) & 원본 파일 스토리지(NFS) 설계

## ⚠️ 읽기 전 꼭 알아야 할 전제
현재 policy-explorer는 **로컬에서 혼자 실행해보는 프로토타입** 상태입니다. 컨테이너화,
환경변수 기반 설정, 헬스체크, 인증이 전혀 없고, 파일 업로드 경로에는 **경로 순회(path
traversal) 취약점**이 존재합니다(자세한 내용은 [06](06-data-and-security.md),
[08](08-migration-checklist.md) 참고). 이 문서 세트는 "지금 상태를 있는 그대로" 설명하고
"이식 전에 무엇을 고쳐야 하는지"를 명시하는 데 목적이 있으며, **코드 변경 자체는 아직 반영되어
있지 않습니다.**
