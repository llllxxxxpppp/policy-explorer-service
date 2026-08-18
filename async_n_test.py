import asyncio
import aiohttp
import time
import statistics
import os
from datetime import datetime

# 타겟 API 주소 (FastAPI 포트 확인)
API_URL = "http://localhost:8080/api/v1/analyze-policy"

# 테스트 페이로드
PAYLOAD = {
    "new_policy_text": "2026년 신규 인사 규정 안내입니다. 첫째, 임직원의 반차 사용 기준 시간은 기존 4시간에서 4.5시간 근무 후 가능하도록 변경됩니다. 둘째, 본인 결혼 시 부여되는 경조사 휴가는 기존 5일에서 7일로 확대 시행됩니다."
}

# 개별 비동기 요청 함수
async def fetch_api(session, req_id):
    print(f"[{req_id}번 요청] 🚀 서버로 전송 완료! (답변 대기 중...)")
    start_time = time.time()
    
    try:
        # 🚨 추가된 부분: 타임아웃(Timeout) 제한을 완전히 해제 (무제한 대기)
        no_timeout = aiohttp.ClientTimeout(total=None)

        # timeout을 넉넉히 120초로 설정 -> # timeout 파라미터에 no_timeout 객체를 넘겨줍니다.
        async with session.post(API_URL, json=PAYLOAD, timeout=no_timeout) as response:
            response.raise_for_status()
            res_data = await response.json()
            elapsed = time.time() - start_time
            print(f"[{req_id}번 요청] ✅ 응답 수신 완료! ({elapsed:.2f}초)")
            return {"id": req_id, "success": True, "time": elapsed, "data": res_data, "error": None}
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[{req_id}번 요청] ❌ 실패! ({e})")
        return {"id": req_id, "success": False, "time": elapsed, "data": None, "error": str(e)}

# 메인 비동기 실행 함수
async def run_concurrent_test(n: int = 100):
    print("="*60)
    print(f"🔥 비동기 동시 부하 테스트 시작 (총 {n}개 요청 동시 발송) 🔥")
    print("="*60)
    
    start_total = time.time()
    
    # aiohttp 세션을 열고 n개의 요청을 동시에 쏟아냅니다 (asyncio.gather)
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_api(session, i) for i in range(1, n + 1)]
        results = await asyncio.gather(*tasks)
        
    total_elapsed = time.time() - start_total
    
    print("\n" + "="*60)
    print(f"🏁 모든 요청 처리 완료! (전체 소요 시간: {total_elapsed:.2f}초)")
    
    # 결과 분석
    success_results = [r for r in results if r["success"]]
    times = [r["time"] for r in success_results]
    
    if not success_results:
        print("❌ 성공한 요청이 없어 리포트를 생성하지 않습니다.")
        return

    # 엔진 및 모델 정보 추출 (첫 번째 성공 응답 기준)
    engine = success_results[0]["data"].get("engine", "Unknown")
    model = success_results[0]["data"].get("model", "Unknown")
    
    # 마크다운 리포트 생성
    os.makedirs("test", exist_ok=True)
    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_model_name = model.replace(":", "-").replace("/", "-")
    filename = f"test/{current_time}-ASYNC-{engine}-{safe_model_name}.md"
    
    md_content = f"""# 🌩️ LXP 백오피스 동시 부하(비동기) 테스트 리포트

## 1. 테스트 환경
* **테스트 일시:** {datetime.now().strftime("%Y년 %m월 %d일 %H:%M:%S")}
* **사용 엔진:** `{engine}`
* **사용 모델:** `{model}`
* **동시 요청 수:** {n} 개 (동시에 API 호출)

## 2. 전체 성능 요약
| 지표 | 측정 결과 |
|---|---|
| **성공률** | {len(success_results)} / {n} 개 성공 |
| **전체 프로세스 소요 시간** | **{total_elapsed:.2f} 초** (N개를 모두 처리하는 데 걸린 실제 시간) |
| **개별 요청 평균 응답 시간** | {statistics.mean(times):.2f} 초 |
| **가장 빠른 응답** | {min(times):.2f} 초 |
| **가장 늦은 응답** | {max(times):.2f} 초 |

## 3. 개별 요청 상세 기록
"""
    for r in results:
        if r["success"]:
            md_content += f"* **요청 {r['id']}:** 성공 ({r['time']:.2f}초)\n"
        else:
            md_content += f"* **요청 {r['id']}:** 실패 ❌ ({r['error']})\n"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    print(f"📁 리포트 저장 완료: {filename}")
    print("="*60)

if __name__ == "__main__":
    N_CONCURRENT = 100  # 동시에 쏠 요청의 개수
    asyncio.run(run_concurrent_test(N_CONCURRENT))