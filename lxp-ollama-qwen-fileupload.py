import os
import time
import logging
import shutil
from typing import List, Dict, Optional, TypedDict

from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
import uvicorn

from langchain_ollama import ChatOllama
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import StateGraph, END

# =========================================================
# 0. 테스트 환경 식별자 및 성능 로깅(Logging) 세팅
# =========================================================
# 💡 성능 측정 시 이 두 변수를 상황에 맞게 수정하여 테스트합니다.
CURRENT_ENGINE = "Ollama"                    # 예: "vLLM", "Ollama", "HF_TGI"
CURRENT_MODEL = "qwen2.5:7b"                 # 예: "EXAONE-3.0-7.8B-Instruct", "qwen2.5:7b"

# 로그 폴더 생성
os.makedirs("logs", exist_ok=True)

# 파일 및 콘솔 동시에 로그를 기록하도록 logger 구성
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/performance.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# 1. Pydantic 스키마 정의 (구조화된 출력용 / API 요청·응답용)
# ---------------------------------------------------------
class ExtractedRule(BaseModel):
    keyword: str = Field(description="규정의 핵심 검색 키워드 (예: 반차, 경조사 휴가, 중식대)")
    fact: str = Field(description="새로운 규정의 명제 팩트 (예: 반차 사용 기준 시간 4.5시간으로 변경)")

class RuleExtractionOutput(BaseModel):
    rules: List[ExtractedRule]

class ConflictAnalysis(BaseModel):
    is_conflict: bool = Field(description="기존 내용과 신규 규정이 충돌(불일치)하면 true, 아니면 false")
    # 결과가 중국어로 나와서 한국어로만 작성 강제
    action_suggested: str = Field(description="수정 제안 (충돌 시에만 작성하되, 반드시 '한국어(Korean)'로만 작성할 것. 예: 5일을 7일로 변경 권장)")

class PolicyRequest(BaseModel):
    new_policy_text: str

class DocumentInfo(BaseModel):
    source: str
    chunk_count: int

# ---------------------------------------------------------
# 2. 모델 설정 (로컬 LLM + 임베딩)
# ---------------------------------------------------------
# 로컬 LLM (Ollama 구동 Qwen2.5 7B)
llm = ChatOllama(model="qwen2.5:7b", temperature=0.0)
structured_llm = llm.with_structured_output(ConflictAnalysis)
rule_extractor_llm = llm.with_structured_output(RuleExtractionOutput)

# 임베딩 모델 (한국어 성능 최적화)
embeddings = HuggingFaceEmbeddings(model_name="jhgan/ko-sroberta-multitask")

# ---------------------------------------------------------
# 3. 파일 업로드 기반 RAG 저장소 설정
# ---------------------------------------------------------
# 🚨 기존 코드의 legacy_documents(하드코딩 샘플)를 제거하고,
#    사용자가 업로드한 문서(PDF, DOCX)를 청킹하여 쌓아가는 방식으로 교체합니다.
UPLOAD_DIR = "./uploaded_documents"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 지원 확장자 → 로더 매핑. 새로운 포맷을 추가할 때는 이 딕셔너리에만 등록하면 됩니다.
# (Excel/HWP는 별도 검토 후 추가 예정 — select_reason.md 8번 항목 참고)
SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


def _load_document(save_path: str, ext: str) -> List[Document]:
    """확장자에 맞는 LangChain 로더로 파일을 읽어 Document 리스트를 반환합니다."""
    if ext == ".pdf":
        return PyPDFLoader(save_path).load()
    if ext == ".docx":
        return Docx2txtLoader(save_path).load()
    raise ValueError(f"지원하지 않는 확장자입니다: {ext}")

# 다른 스크립트(lxp-ollama-qwen.py 등)와 벡터 데이터가 섞이지 않도록
# 업로드 전용 persist 디렉터리 + 컬렉션명을 별도로 사용합니다.
persist_directory = "./chroma_db_fileupload"
COLLECTION_NAME = "uploaded_policy_docs"

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

vector_db = Chroma(
    collection_name=COLLECTION_NAME,
    embedding_function=embeddings,
    persist_directory=persist_directory,
)
chroma_retriever = vector_db.as_retriever(search_kwargs={"k": 2})

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
)

# BM25는 인메모리 키워드 검색이라 증분(add) API가 없으므로,
# 업로드된 청크 전체를 이 리스트에 계속 누적해두고 업로드 시마다 재구축합니다.
all_chunks: List[Document] = []
ensemble_retriever: Optional[EnsembleRetriever] = None


def _rebuild_ensemble_retriever() -> None:
    """업로드된 전체 청크로 BM25를 재구축하고, Chroma(벡터) + BM25(키워드) 앙상블 리트리버를 갱신합니다."""
    global ensemble_retriever
    if not all_chunks:
        ensemble_retriever = None
        return

    bm25_retriever = BM25Retriever.from_documents(all_chunks)
    bm25_retriever.k = 2

    # 앙상블 리트리버 (벡터 50% + BM25 50%)
    ensemble_retriever = EnsembleRetriever(
        retrievers=[chroma_retriever, bm25_retriever], weights=[0.5, 0.5]
    )


def _load_persisted_chunks_on_startup() -> None:
    """서버 재기동 시, 이미 ChromaDB에 저장된 청크들을 불러와 BM25/앙상블 리트리버를 복원합니다."""
    try:
        existing = vector_db.get(include=["documents", "metadatas"])
    except Exception as e:
        logger.warning(f"기존 벡터 컬렉션을 불러오지 못했습니다: {e}")
        return

    contents = existing.get("documents") or []
    metadatas = existing.get("metadatas") or []
    if not contents:
        return

    for content, metadata in zip(contents, metadatas):
        all_chunks.append(Document(page_content=content, metadata=metadata or {}))

    _rebuild_ensemble_retriever()
    logger.info(f"[Startup] 기존 업로드 문서 {len(all_chunks)}개 청크를 복원했습니다.")


_load_persisted_chunks_on_startup()

# ---------------------------------------------------------
# 4. LangGraph 상태(State) 정의
# ---------------------------------------------------------
class GraphState(TypedDict):
    new_policy_doc: str
    extracted_rules: List[Dict]
    search_results: List[Dict]
    conflict_report: List[Dict]
    final_markdown_report: str

# ---------------------------------------------------------
# 5. LangGraph 노드 함수
# ---------------------------------------------------------
def extract_rules_node(state: GraphState) -> Dict:
    # log
    logger.info(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] [Node 1] 규정 팩트 추출 시작...")
    start_t = time.time()

    """1. 신규 문서에서 팩트를 추출합니다."""
    print("[Node] Extracting Rules...")
    prompt = ChatPromptTemplate.from_template(
        "다음은 새롭게 개정된 사내 규정 문서입니다. 이 문서에서 변경된 핵심 규정(팩트)들을 추출하세요.\n\n"
        "문서: {policy}"
    )
    chain = prompt | rule_extractor_llm
    result = chain.invoke({"policy": state["new_policy_doc"]})

    # log
    logger.info(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] 👉 [Node 1 완료] 추출 소요 시간: {time.time() - start_t:.2f}초")

    rules = [{"keyword": r.keyword, "fact": r.fact} for r in result.rules]
    return {"extracted_rules": rules}

def retrieve_legacy_node(state: GraphState) -> Dict:

    # log: 시작
    logger.info(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] [Node 2] 하이브리드 검색 시작...")
    start_t = time.time()

    """2. 하이브리드 검색(업로드된 문서 기반 RAG)으로 기존 콘텐츠를 찾습니다."""
    print("[Node] Retrieving Legacy Data...")

    if ensemble_retriever is None:
        logger.warning(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] ⚠️ 업로드된 문서가 없어 검색을 건너뜁니다.")
        return {"search_results": []}

    rules = state["extracted_rules"]
    search_results = []
    seen_docs = set()

    for rule in rules:
        docs = ensemble_retriever.invoke(rule["keyword"])
        for doc in docs:
            doc_id = doc.metadata.get("id", doc.page_content[:20])
            if doc_id not in seen_docs:
                seen_docs.add(doc_id)
                search_results.append({
                    "keyword": rule["keyword"],
                    "new_fact": rule["fact"],
                    "old_content": doc.page_content,
                    "source": doc.metadata.get("source", "Unknown")
                })

    # log: 완료
    logger.info(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] 👉 [Node 2 완료] 검색 소요 시간: {time.time() - start_t:.3f}초")
    return {"search_results": search_results}

def analyze_conflicts_node(state: GraphState) -> Dict:

    # log
    logger.info(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] [Node 3] 충돌 검증 연산 시작...")


    """3. 검색된 데이터와 신규 규정을 비교하여 충돌을 검증합니다."""
    print("[Node] Analyzing Conflicts...")
    search_results = state["search_results"]
    conflict_report = []

    prompt = ChatPromptTemplate.from_template(
        "당신은 사내 HR 규정 검수자입니다.\n"
        "아래 '기존 콘텐츠' 내용이 '신규 규정 팩트'와 의미상 상충(불일치)하는지 판단하세요.\n\n"
        "🚨중요: 모든 분석 결과와 제안은 반드시 '한국어(Korean)'로만 작성해야 합니다. 절대 중국어나 영어를 사용하지 마세요.\n\n"
        "기존 콘텐츠: {old_content}\n"
        "신규 규정 팩트: {new_fact}"
    )
    chain = prompt | structured_llm

    for item in search_results:

        # log
        # 🚨 LLM 연산 시작 전 시간을 반드시 기록해야 에러가 나지 않습니다.
        llm_start_t = time.time()

        analysis = chain.invoke({
            "new_fact": item["new_fact"],
            "old_content": item["old_content"]
        })

        logger.info(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] 👉 [{item['keyword']}] 순수 LLM 추론 시간: {time.time() - llm_start_t:.2f}초")

        if analysis.is_conflict:
            conflict_report.append({
                "source": item["source"],
                "old_content": item["old_content"],
                "new_fact": item["new_fact"],
                "action_suggested": analysis.action_suggested
            })

    return {"conflict_report": conflict_report}

def generate_report_node(state: GraphState) -> Dict:

    # log: 시작
    logger.info(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] [Node 4] 최종 리포트 생성 시작...")
    start_t = time.time()

    """4. 충돌 데이터를 바탕으로 마크다운 리포트를 생성합니다."""
    print("[Node] Generating Final Report...")
    report_data = state["conflict_report"]

    if not report_data:
        logger.info(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] 👉 [Node 4 완료] 리포트 생성(충돌없음) 소요 시간: {time.time() - start_t:.3f}초")
        return {"final_markdown_report": "✅ 기존 콘텐츠 중 신규 규정과 충돌하는 항목이 발견되지 않았습니다."}

    markdown_lines = ["## 🚨 사내 콘텐츠 규정 충돌 검출 리포트\n"]
    markdown_lines.append("| 기존 출처(Source) | 기존 내용 (Old) | 신규 규정 (New Fact) | AI 수정 제안 |")
    markdown_lines.append("|---|---|---|---|")

    for item in report_data:
        source = item["source"]
        old = item["old_content"].replace("\n", " ")
        new = item["new_fact"].replace("\n", " ")
        action = item["action_suggested"].replace("\n", " ")
        markdown_lines.append(f"| {source} | {old} | {new} | **{action}** |")

    # log: 완료
    logger.info(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] 👉 [Node 4 완료] 리포트 생성 소요 시간: {time.time() - start_t:.3f}초")
    return {"final_markdown_report": "\n".join(markdown_lines)}

# ---------------------------------------------------------
# 6. LangGraph 그래프 빌드
# ---------------------------------------------------------
workflow = StateGraph(GraphState)

workflow.add_node("extract_rules", extract_rules_node)
workflow.add_node("retrieve_legacy", retrieve_legacy_node)
workflow.add_node("analyze_conflicts", analyze_conflicts_node)
workflow.add_node("generate_report", generate_report_node)

workflow.set_entry_point("extract_rules")
workflow.add_edge("extract_rules", "retrieve_legacy")
workflow.add_edge("retrieve_legacy", "analyze_conflicts")
workflow.add_edge("analyze_conflicts", "generate_report")
workflow.add_edge("generate_report", END)

app_graph = workflow.compile()

# ---------------------------------------------------------
# 7. FastAPI 엔드포인트
# ---------------------------------------------------------
app = FastAPI(title="LXP Backoffice Policy Assistant (Document Upload + RAG)")

@app.post("/api/v1/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    """PDF/DOCX 문서를 업로드하면 청킹 후 ChromaDB(+BM25)에 적재하여 RAG 검색 대상에 추가합니다.

    🚨 Excel(.xlsx/.xls), HWP(.hwp/.hwpx)는 아직 미지원입니다. (select_reason.md 8번 항목 참고)
    """
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 파일 형식입니다 ({ext}). 업로드 가능한 확장자: {supported}",
        )

    upload_start_t = time.time()
    save_path = os.path.join(UPLOAD_DIR, file.filename)

    try:
        with open(save_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # 1) 확장자에 맞는 로더로 문서 로드 (PDF는 페이지 단위, DOCX는 파일 전체 단위 Document)
        try:
            docs = _load_document(save_path, ext)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not docs:
            raise HTTPException(status_code=400, detail="문서에서 텍스트를 추출하지 못했습니다.")

        # 2) 청킹
        chunks = text_splitter.split_documents(docs)
        for i, chunk in enumerate(chunks):
            chunk.metadata["source"] = file.filename
            chunk.metadata["id"] = f"{file.filename}::chunk_{i}"

        # 3) ChromaDB(벡터 저장소)에 적재
        # 🚨 반드시 metadata["id"]를 Chroma의 저장 id로도 명시해야, 이후 reset_documents()에서
        #    같은 id로 delete()가 실제로 매칭되어 삭제됩니다 (id를 넘기지 않으면 Chroma가 내부
        #    UUID를 임의로 생성해버려, 우리가 갖고 있는 metadata["id"]로는 삭제가 되지 않습니다).
        vector_db.add_documents(chunks, ids=[chunk.metadata["id"] for chunk in chunks])

        # 4) BM25 + 앙상블 리트리버 재구축 (전체 누적 청크 기준)
        all_chunks.extend(chunks)
        _rebuild_ensemble_retriever()

        elapsed = time.time() - upload_start_t
        logger.info(
            f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] 📄 [문서 업로드 완료] {file.filename} "
            f"(원본 Document {len(docs)}개 → 청크 {len(chunks)}개, 소요 시간: {elapsed:.2f}초)"
        )

        return {
            "status": "success",
            "filename": file.filename,
            "num_source_documents": len(docs),
            "num_chunks": len(chunks),
            "total_chunks_in_store": len(all_chunks),
            "elapsed_seconds": round(elapsed, 2),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] ❌ 업로드 처리 중 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/documents", response_model=List[DocumentInfo])
async def list_documents():
    """현재 RAG 저장소에 적재되어 있는 문서(출처)별 청크 개수를 조회합니다."""
    counts: Dict[str, int] = {}
    for chunk in all_chunks:
        source = chunk.metadata.get("source", "Unknown")
        counts[source] = counts.get(source, 0) + 1
    return [DocumentInfo(source=src, chunk_count=cnt) for src, cnt in counts.items()]


@app.delete("/api/v1/documents")
async def reset_documents():
    """업로드된 문서를 모두 초기화합니다 (ChromaDB 컬렉션 + BM25 인메모리 캐시)."""
    global ensemble_retriever
    try:
        ids = [c.metadata.get("id") for c in all_chunks if c.metadata.get("id")]
        if ids:
            vector_db.delete(ids=ids)
        all_chunks.clear()
        ensemble_retriever = None
        return {"status": "success", "message": "업로드된 문서를 모두 초기화했습니다."}
    except Exception as e:
        logger.error(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] ❌ 초기화 중 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/analyze-policy")
async def analyze_policy(request: PolicyRequest):
    try:
        # log
        api_start_t = time.time()

        if not all_chunks:
            logger.warning(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] ⚠️ 업로드된 문서가 없는 상태로 분석 요청이 들어왔습니다.")

        initial_state = {"new_policy_doc": request.new_policy_text}
        final_state = app_graph.invoke(initial_state)

        # log
        total_serving_time = time.time() - api_start_t
        logger.info(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] ✅ [API 서빙 완료] 총 전체 처리 소요 시간: {total_serving_time:.2f}초")

        return {
            "status": "success",
            "engine": CURRENT_ENGINE,
            "model": CURRENT_MODEL,
            "total_time_seconds": round(total_serving_time, 2), # UI 표시용 데이터 추가
            "documents_in_store": len(all_chunks),
            "extracted_rules": final_state.get("extracted_rules", []),
            "conflict_count": len(final_state.get("conflict_report", [])),
            "markdown_report": final_state.get("final_markdown_report", "")
        }
    except Exception as e:
        logger.error(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] ❌ 에러 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    # 🚨 lxp-ollama-qwen.py(8000번 포트)와 동시에 띄워 비교할 수 있도록 8001번 포트를 사용합니다.
    uvicorn.run(app, host="0.0.0.0", port=8001)
