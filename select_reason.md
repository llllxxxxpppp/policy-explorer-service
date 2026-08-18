# 모델/기술 채택 이유 정리

이 문서는 `lxp-ollama-qwen.py`, `lxp-ollama-exaone.py`, `lxp-vllm-qwen.py`, `lxp-vllm-exaone.py`,
`lxp-ollama-qwen-fileupload.py` 등 현재까지 작성된 코드의 주석과 `test/`, `test-result.md`에 기록된
실측 성능 테스트 결과를 근거로, 각 구성 요소를 왜 선택했는지 정리한 기록입니다.

## 1. 서빙 엔진: Ollama vs vLLM

| 항목 | Ollama | vLLM |
|---|---|---|
| 장점 | 로컬 설치/실행이 간단하고, 별도 서빙 인프라 구축 없이 바로 모델을 구동할 수 있어 초기 PoC에 적합 | PagedAttention 기반의 배치 처리로 동시 요청 처리량이 훨씬 높음 |
| 단점 | 동시 요청이 몰릴 때 처리량이 급격히 저하됨 | 최초 구동 시 서버 기동/양자화 설정 등 준비 과정이 더 복잡함 |

**채택 근거 (실측 데이터):**
- 순차 5회 테스트(`test-result.md`) 기준 Ollama+Qwen2.5-7B는 평균 **81.69초**, vLLM+Qwen2.5-7B는 평균
  **75.50초**로 이미 vLLM이 근소하게 빨랐습니다.
- 동시 요청 100건 부하 테스트(`test/2026081*-ASYNC-*.md`) 기준으로는 격차가 크게 벌어졌습니다.
  - Ollama + Qwen2.5-7B: 전체 처리 시간 **8255.93초**
  - vLLM + Qwen2.5-7B: 전체 처리 시간 **7157.55초**
  - vLLM + EXAONE-3.0-7.8B: 전체 처리 시간 **3310.60초** (가장 빠름)
- 따라서 두 엔진을 나란히 구현해 비교(`lxp-ollama-*.py` vs `lxp-vllm-*.py`)한 것은, "로컬 개발/소규모
  검증은 Ollama, 동시 사용자 트래픽을 감당해야 하는 운영 환경은 vLLM"이라는 결론을 데이터로 검증하기
  위함입니다. 백오피스처럼 다수의 요청이 몰릴 수 있는 서비스라면 vLLM 채택이 유리합니다.

## 2. LLM: Qwen2.5-7B-Instruct vs EXAONE-3.0/3.5-7.8B-Instruct

- 두 모델 모두 **로컬(온프레미스) 구동이 가능한 7~8B급 오픈 가중치 모델**이라는 공통점 때문에 후보로
  선정했습니다. 사내 인사 규정처럼 민감한 문서를 외부 API(OpenAI 등)로 보내지 않고 자체 인프라에서
  처리하기 위해, 클라우드 LLM이 아닌 로컬 구동 모델을 우선 검토했습니다.
- **Qwen2.5-7B-Instruct**: 다국어(한국어 포함) instruction-following 성능이 준수하고, Ollama/vLLM
  양쪽에서 모두 안정적으로 구동되어 엔진 비교 실험의 기준(baseline) 모델로 채택했습니다.
- **EXAONE-3.0/3.5-7.8B-Instruct**: LG AI연구원이 한국어 데이터에 특화해 학습한 모델로, 사내 HR
  규정처럼 한국어 문맥·용어 이해가 중요한 도메인에 강점이 있을 것으로 기대되어 비교 대상으로
  채택했습니다.
- **실측 결과**: 동시 요청 100건 기준 vLLM 환경에서 EXAONE-3.0(3310.60초)이 Qwen2.5(7157.55초)보다
  약 2배 이상 빨랐습니다. 다만 이는 `--quantization bitsandbytes` 양자화 설정, `max_model_len`,
  `max_num_seqs` 등 서빙 옵션(`README.md` 참고)의 영향도 섞여 있어, 모델 자체의 순수 추론 성능
  차이만으로 단정하기보다는 "엔진 설정을 포함한 종합 서빙 성능" 관점에서 참고할 지표로 기록합니다.
- **공통 이슈 및 대응**: 두 모델 모두 구조화 출력(`ConflictAnalysis.action_suggested`) 생성 시
  중국어가 섞여 나오는 현상이 있어(`lxp-ollama-qwen.py` 주석 참고), 프롬프트에 "반드시 한국어로만
  작성" 지시문을 명시적으로 강제해 대응했습니다.

## 3. 임베딩 모델: `jhgan/ko-sroberta-multitask`

- 한국어 문장 임베딩에 최적화된 SBERT 계열 모델로, 사내 규정 문서(한국어 텍스트)의 의미 기반 검색
  품질을 높이기 위해 채택했습니다. (코드 주석: `# 임베딩 모델 (한국어 성능 최적화)`)
- HuggingFace 기반이라 `langchain_huggingface.HuggingFaceEmbeddings`로 손쉽게 연동 가능하고, LLM
  서빙 엔진(Ollama/vLLM)과 무관하게 재사용할 수 있어 모든 스크립트에서 동일하게 사용했습니다.

## 4. 벡터 스토어: ChromaDB

- 별도의 서버/클러스터 구축 없이 `persist_directory`만 지정하면 로컬 디스크에 영구 저장되는
  경량 벡터 DB로, 온프레미스 PoC 환경에 적합해 채택했습니다.
- LangChain과의 통합(`langchain_community.vectorstores.Chroma`)이 잘 되어 있어 리트리버 구성이
  간단하고, 이후 파일 업로드 기능(`lxp-ollama-qwen-fileupload.py`)처럼 문서를 추가/삭제하는
  증분(add/delete) 운영에도 바로 대응할 수 있었습니다.

## 5. 검색 전략: Chroma(의미 검색) + BM25(키워드 검색) 앙상블 (50:50)

- 신규 규정에서 추출한 키워드(예: "반차", "경조사 휴가")가 기존 문서의 표현과 정확히 일치하지 않을
  수 있어 의미 기반 벡터 검색(Chroma)만으로는 관련 문서를 놓칠 위험이 있습니다.
- 반대로 정확한 키워드가 포함된 문서는 BM25(키워드 검색)가 더 확실하게 잡아낼 수 있습니다.
- 두 방식의 장점을 모두 취하기 위해 `EnsembleRetriever`로 두 리트리버를 가중치 0.5:0.5로 결합하는
  하이브리드 검색을 채택했습니다.

## 6. 오케스트레이션: LangGraph

- 규정 충돌 검출 파이프라인을 "① 팩트 추출 → ② 하이브리드 검색 → ③ 충돌 분석 → ④ 리포트 생성"의
  명시적 단계(Node)로 분리하기 위해 LangGraph의 `StateGraph`를 채택했습니다.
- 각 노드 단위로 소요 시간을 로깅(`logs/performance.log`)할 수 있어, 엔진/모델별 성능을 구간별로
  비교·분석하기 쉬운 구조를 제공합니다.

## 7. API 서버: FastAPI + Uvicorn

- 비동기(async) 요청 처리가 가능해 `async_n_test.py` 등 동시 부하 테스트 시나리오를 그대로 검증할
  수 있고, Pydantic 기반 요청/응답 스키마 검증을 자연스럽게 재사용할 수 있어 채택했습니다.

## 8. `lxp-ollama-qwen-fileupload.py`에서 추가로 채택한 기술

| 구성 요소 | 선택 | 이유 |
|---|---|---|
| PDF 파싱 | `PyPDFLoader` (`langchain_community.document_loaders`, `pypdf`) | LangChain Document 생태계와 바로 호환되어 이후 텍스트 분할/벡터 적재 파이프라인에 별도 변환 없이 연결 가능 |
| DOCX 파싱 | `Docx2txtLoader` (`langchain_community.document_loaders`, `docx2txt`) | `python-docx`로 직접 XML을 다루거나 `unstructured` 같은 무거운 파싱 라이브러리를 도입하지 않아도, 전이 의존성 없는 경량 패키지 하나로 텍스트 추출이 가능해 기존 `PyPDFLoader` 사용 패턴과 결을 맞춤 |
| 청킹 | `RecursiveCharacterTextSplitter` (`langchain_text_splitters`) | 문단→줄바꿈→공백 순으로 재귀적으로 분할해 문맥이 급격히 끊기는 것을 최소화하는 LangChain 기본 권장 방식이며, 이미 프로젝트 의존성(`langchain-text-splitters`)에 포함되어 추가 설치 부담이 없음 |
| 업로드 처리 | FastAPI `UploadFile` | 기존 FastAPI 스택을 그대로 재사용할 수 있고, `python-multipart`가 이미 설치되어 있어 추가 설정 없이 멀티파트 파일 업로드를 지원 |
| 벡터 저장소 분리 | 기존 `./chroma_db`와 별도로 `./chroma_db_fileupload` + 전용 컬렉션명 사용 | 성능 비교용 샘플 데이터(`legacy_documents`)를 사용하는 기존 스크립트들과 사용자 업로드 데이터가 뒤섞이지 않도록 격리 |
| BM25 재구축 전략 | 업로드 시마다 누적된 전체 청크로 BM25 재생성 | `BM25Retriever`는 증분 추가 API를 제공하지 않는 인메모리 구조이므로, 소규모 사내 문서 코퍼스 규모에서는 매 업로드 시 재구축하는 비용이 허용 가능하다고 판단 |
| 확장자 지원 범위 | 우선 `.pdf`, `.docx`만 지원 (Excel `.xlsx`/`.xls`, HWP `.hwp`/`.hwpx`는 제외) | Excel은 경량 `openpyxl` 커스텀 로더 vs `UnstructuredExcelLoader`(무거운 `unstructured`+`pandas` 의존성) 중 방식을 아직 결정하지 못해 보류. HWP는 legacy `.hwp`를 다룰 수 있는 사실상 유일한 오픈소스 라이브러리인 `pyhwp`가 유지보수가 뜸하고 최신 HWP 5.1 변형에서 파싱이 깨질 수 있으며, 신형 `.hwpx`(zip+XML 포맷)를 지원하는 성숙한 라이브러리도 없어(직접 파서를 새로 작성해야 함) 이번 범위에서는 제외 |

## 참고
- 성능 수치 출처: `test-result.md`, `test/20260813_*.md`(순차 5회 테스트), `test/2026081*-ASYNC-*.md`(동시 100건 부하 테스트)
- 위 표의 실측치는 테스트 환경(GPU, 양자화 옵션, 동시성 설정 등)에 따라 달라질 수 있으므로, 절대적인
  모델 성능 우열이 아니라 "현재 이 리포지토리의 설정 기준" 비교 결과로 해석해야 합니다.
