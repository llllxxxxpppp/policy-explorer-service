import os
import time
import logging
import json
from typing import List, Dict, TypedDict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn

from langchain_ollama import ChatOllama
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from langgraph.graph import StateGraph, END

# =========================================================
# 0. 테스트 환경 식별자 및 성능 로깅(Logging) 세팅
# =========================================================
# 💡 성능 측정 시 이 두 변수를 상황에 맞게 수정하여 테스트합니다.
CURRENT_ENGINE = "Ollama"                          # 예: "vLLM", "Ollama", "HF_TGI"
CURRENT_MODEL = "qwen2.5:7b"       # 예: "EXAONE-3.0-7.8B-Instruct", "qwen2.5:7b"

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
# 1. Pydantic 스키마 정의 (구조화된 출력용)
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

# ---------------------------------------------------------
# 2. 모델 및 리트리버 설정 (하이브리드 검색)
# ---------------------------------------------------------
# 로컬 LLM (Ollama 구동 Qwen2.5 7B)
llm = ChatOllama(model="qwen2.5:7b", temperature=0.0)
structured_llm = llm.with_structured_output(ConflictAnalysis)
rule_extractor_llm = llm.with_structured_output(RuleExtractionOutput)

# 임베딩 모델 (한국어 성능 최적화)
embeddings = HuggingFaceEmbeddings(model_name="jhgan/ko-sroberta-multitask")

# 모의 데이터
legacy_documents = [
    Document(page_content="신규 입사자의 반차 사용 기준은 4시간 근무 후 가능합니다.", metadata={"source": "2023_OT_영상.txt", "id": "doc1"}),
    Document(page_content="본인 결혼 시 주어지는 경조사 휴가는 총 5일입니다.", metadata={"source": "복지_가이드북_v1.pdf", "id": "doc2"}),
    Document(page_content="점심 시간은 12시부터 1시까지 1시간입니다.", metadata={"source": "근태관리_매뉴얼.pdf", "id": "doc3"}),
    Document(page_content="오전 반차는 09:00~13:00 (4시간) 입니다.", metadata={"source": "근태시스템_FAQ.pdf", "id": "doc4"})
]

# ChromaDB 벡터 검색 (의미 기반)
persist_directory = "./chroma_db"
vector_db = Chroma.from_documents(legacy_documents, embeddings, persist_directory=persist_directory)
chroma_retriever = vector_db.as_retriever(search_kwargs={"k": 2})

# BM25 검색 (키워드 기반)
bm25_retriever = BM25Retriever.from_documents(legacy_documents)
bm25_retriever.k = 2

# 앙상블 리트리버 (벡터 50% + BM25 50%)
ensemble_retriever = EnsembleRetriever(
    retrievers=[chroma_retriever, bm25_retriever], weights=[0.5, 0.5]
)

# ---------------------------------------------------------
# 3. LangGraph 상태(State) 정의
# ---------------------------------------------------------
class GraphState(TypedDict):
    new_policy_doc: str
    extracted_rules: List[Dict]
    search_results: List[Dict]
    conflict_report: List[Dict]
    final_markdown_report: str

# ---------------------------------------------------------
# 4. LangGraph 노드 함수
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

    """2. 하이브리드 검색으로 기존 콘텐츠를 찾습니다."""
    print("[Node] Retrieving Legacy Data...")
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
        # 🚨 수정됨: LLM 연산 시작 전 시간을 반드시 기록해야 에러가 나지 않습니다.
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
# 5. LangGraph 그래프 빌드
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
# 6. FastAPI 엔드포인트
# ---------------------------------------------------------
app = FastAPI(title="LXP Backoffice Policy Assistant")

class PolicyRequest(BaseModel):
    new_policy_text: str

@app.post("/api/v1/analyze-policy")
async def analyze_policy(request: PolicyRequest):
    try:
        # log
        api_start_t = time.time()

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
            "extracted_rules": final_state.get("extracted_rules", []),
            "conflict_count": len(final_state.get("conflict_report", [])),
            "markdown_report": final_state.get("final_markdown_report", "")
        }
    except Exception as e:
        logger.error(f"[{CURRENT_ENGINE} | {CURRENT_MODEL}] ❌ 에러 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)