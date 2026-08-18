import requests
import time
import statistics
import os
from datetime import datetime

# 테스트할 API 엔드포인트
API_URL = "http://localhost:8080/api/v1/analyze-policy"
'''
ollama-qwen: http://localhost:8000/api/v1/analyze-policy
vllm-exaone test: http://localhost:8080/api/v1/analyze-policy
'''


# 테스트에 사용할 가짜 개정안 데이터
PAYLOAD = {
    "new_policy_text": "2026년 신규 인사 규정 안내입니다. 첫째, 임직원의 반차 사용 기준 시간은 기존 4시간에서 4.5시간 근무 후 가능하도록 변경됩니다. 둘째, 본인 결혼 시 부여되는 경조사 휴가는 기존 5일에서 7일로 확대 시행됩니다."
}

def run_n_times_test(n: int = 5):
    print(f"🚀 API {n}회 반복 테스트를 시작합니다...")
    print(f"📍 Target: {API_URL}\n")

    times = []
    engine = "Ollama"           # vLLM / Ollama
    model = "Qwen2.5-7B"    # exaone3.5-7.8b / Qwen2.5-7B
    details = []

    for i in range(1, n + 1):
        print(f"[{i}/{n}] 요청 발송 중... ", end="", flush=True)
        start_time = time.time()
        
        try:
            response = requests.post(API_URL, json=PAYLOAD, timeout=120)
            response.raise_for_status()
            
            elapsed_time = time.time() - start_time
            times.append(elapsed_time)
            
            res_data = response.json()
            
            # 첫 번째 성공 응답에서 엔진과 모델 정보를 추출해 기록
            if engine == "Unknown":
                engine = res_data.get("engine", "Unknown")
                model = res_data.get("model", "Unknown")
            
            print(f"완료! (소요 시간: {elapsed_time:.2f}초)")
            details.append(f"- **{i}회차:** 성공 ({elapsed_time:.2f}초)")
            
        except Exception as e:
            print(f"실패! ❌ (에러: {e})")
            details.append(f"- **{i}회차:** 실패 ❌ ({e})")

    # 모든 요청이 끝난 후 마크다운 문서화 작업 진행
    if times:
        # 1. test 폴더 생성 (없으면 만들기)
        os.makedirs("test", exist_ok=True)
        
        # 2. 파일명 생성 (특수문자 치환)
        # 예: qwen2.5:7b -> qwen2.5-7b, EXAONE/3.0 -> EXAONE-3.0
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_model_name = model.replace(":", "-").replace("/", "-")
        filename = f"test/{current_time}-{engine}-{safe_model_name}.md"
        
        # 3. 통계 계산
        mean_time = statistics.mean(times)
        min_time = min(times)
        max_time = max(times)
        
        # 4. 마크다운 리포트 내용 구성
        md_content = f"""# 📊 LXP 백오피스 AI 성능 테스트 리포트

## 1. 테스트 환경 정보
* **테스트 일시:** {datetime.now().strftime("%Y년 %m월 %d일 %H:%M:%S")}
* **사용 엔진 (Engine):** `{engine}`
* **사용 모델 (Model):** `{model}`
* **총 테스트 횟수:** {n} 회

## 2. 성능 요약 (Summary)
| 지표 | 측정 결과 |
|---|---|
| **성공 횟수** | {len(times)} / {n} 회 |
| **평균 소요 시간** | **{mean_time:.2f} 초** |
| **최소 소요 시간 (Fastest)** | {min_time:.2f} 초 |
| **최대 소요 시간 (Slowest)** | {max_time:.2f} 초 |

## 3. 회차별 상세 기록
"""
        md_content += "\n".join(details)
        
        # 5. 파일 저장
        with open(filename, "w", encoding="utf-8") as f:
            f.write(md_content)
            
        print("\n" + "="*60)
        print(f"✅ 테스트 완료! 마크다운 리포트가 성공적으로 저장되었습니다.")
        print(f"📁 파일 위치: {filename}")
        print("="*60)
    else:
        print("\n❌ 성공한 요청이 없어 리포트를 생성하지 못했습니다.")

if __name__ == "__main__":
    N_TIMES = 5 
    run_n_times_test(N_TIMES)