"""
TSDO 방식 측정 스크립트.
핵심: Deployment를 동시에 삭제/배포하고, 실패 시 롤백.
"""

import subprocess
import time
import json
import os
import sys
import concurrent.futures

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
YAML_DIR = os.path.join(PROJECT_DIR, "yamls")
RESULTS_DIR = os.path.join(PROJECT_DIR, "results")

ISR_YAML = os.path.join(YAML_DIR, "isr-modelset.yaml")
ENGAGEMENT_YAML = os.path.join(YAML_DIR, "engagement-modelset.yaml")

ISR_DEPLOYMENTS = ["anomaly-detection", "pattern-analysis"]
ENGAGEMENT_DEPLOYMENTS = ["target-tracking", "threat-assessment", "strike-recommendation"]

TIMEOUT = "120s"


def run_cmd(cmd, check=True):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"[ERROR] 명령 실패: {cmd}")
        print(result.stderr)
        sys.exit(1)
    return result


def wait_deployment_available(name, timeout=TIMEOUT):
    result = subprocess.run(
        f"kubectl wait --for=condition=available deployment/{name} --timeout={timeout}",
        shell=True,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, name


def wait_all_deployments_parallel(names):
    """병렬로 여러 Deployment가 Ready 될 때까지 대기. 타임스탬프도 수집."""
    ready_times = {}
    failed = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(names)) as executor:
        future_to_name = {
            executor.submit(wait_deployment_available, name): name for name in names
        }
        for future in concurrent.futures.as_completed(future_to_name):
            name = future_to_name[future]
            success, dep_name = future.result()
            if success:
                ready_times[dep_name] = time.time()
                print(f"  → {dep_name} Ready 완료 ({ready_times[dep_name]:.3f})")
            else:
                failed.append(dep_name)
                print(f"  [FAIL] {dep_name} timeout")

    return ready_times, failed


def rollback(target_yaml, previous_yaml):
    print("[롤백] 롤백 시작...")
    run_cmd(f"kubectl delete -f {target_yaml} --ignore-not-found=true", check=False)
    run_cmd(f"kubectl apply -f {previous_yaml}", check=False)
    print("[롤백] 완료")


def cleanup():
    print("[정리] 기존 Deployment 삭제 중...")
    run_cmd(f"kubectl delete -f {ISR_YAML} --ignore-not-found=true", check=False)
    run_cmd(f"kubectl delete -f {ENGAGEMENT_YAML} --ignore-not-found=true", check=False)
    time.sleep(10)


def run_tsdo_once(run_id):
    print(f"\n=== TSDO Run #{run_id} ===")

    # 1. ISR 모델 세트 배포 및 준비
    print("[준비] ISR 모델 세트 배포...")
    run_cmd(f"kubectl apply -f {ISR_YAML}")
    for dep in ISR_DEPLOYMENTS:
        result = subprocess.run(
            f"kubectl wait --for=condition=available deployment/{dep} --timeout={TIMEOUT}",
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[ERROR] {dep} 준비 실패")
            sys.exit(1)
        print(f"  → {dep} Ready 완료")
    print("[준비] ISR 모델 세트 Ready 완료")

    # 타이머 시작
    t_start = time.time()
    rollback_triggered = False

    # 4. 동시 처리 (TSDO의 핵심)
    print("[전환] 동시 처리 시작...")

    # a. 기존 ISR 세트 동시 삭제
    print("  [삭제] ISR 모델 세트 동시 삭제...")
    run_cmd(f"kubectl delete -f {ISR_YAML} --ignore-not-found=true", check=False)

    # b. 새 Engagement 세트 동시 배포
    print("  [배포] Engagement 모델 세트 동시 배포...")
    run_cmd(f"kubectl apply -f {ENGAGEMENT_YAML}")

    # c. 3개 Deployment 병렬 대기
    print("  [대기] Engagement 모델 세트 병렬 Ready 대기...")
    ready_times, failed = wait_all_deployments_parallel(ENGAGEMENT_DEPLOYMENTS)

    if failed:
        print(f"  [FAIL] 다음 Deployment timeout: {failed} → 롤백 실행")
        rollback(ENGAGEMENT_YAML, ISR_YAML)
        rollback_triggered = True
        t_end = time.time()
        total_time = t_end - t_start
        partial_exposure = 0.0
        run_cmd(f"kubectl delete -f {ISR_YAML} --ignore-not-found=true", check=False)
        run_cmd(f"kubectl delete -f {ENGAGEMENT_YAML} --ignore-not-found=true", check=False)
        time.sleep(10)
        return {
            "total_time": total_time,
            "partial_exposure_time": partial_exposure,
            "rollback_triggered": rollback_triggered,
        }

    # 타이머 종료
    t_end = time.time()
    total_time = t_end - t_start

    # 6. 부분 전환 노출 시간 계산 (첫 Ready ~ 마지막 Ready)
    if len(ready_times) == len(ENGAGEMENT_DEPLOYMENTS):
        first_ready = min(ready_times.values())
        last_ready = max(ready_times.values())
        partial_exposure = last_ready - first_ready
    else:
        partial_exposure = 0.0

    print(f"  전환 완료 시간: {total_time:.2f}초")
    print(f"  부분 전환 노출 시간: {partial_exposure:.2f}초")

    # 정리
    run_cmd(f"kubectl delete -f {ENGAGEMENT_YAML} --ignore-not-found=true", check=False)
    time.sleep(10)

    return {
        "total_time": total_time,
        "partial_exposure_time": partial_exposure,
        "rollback_triggered": rollback_triggered,
    }


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    print("=== TSDO 실험 시작 (10회 반복) ===")
    print("환경 확인 중...")
    run_cmd("kubectl cluster-info")

    cleanup()

    results = []
    for i in range(1, 11):
        result = run_tsdo_once(i)
        results.append(result)

    output_path = os.path.join(RESULTS_DIR, "tsdo_times.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    total_times = [r["total_time"] for r in results]
    partial_times = [r["partial_exposure_time"] for r in results]
    rollback_count = sum(1 for r in results if r["rollback_triggered"])
    avg_total = sum(total_times) / len(total_times)
    avg_partial = sum(partial_times) / len(partial_times)

    print(f"\n=== TSDO 실험 완료 ===")
    print(f"평균 전환 완료 시간: {avg_total:.2f}초")
    print(f"평균 부분 전환 노출 시간: {avg_partial:.2f}초")
    print(f"롤백 발생 횟수: {rollback_count}/10")
    print(f"결과 저장: {output_path}")


if __name__ == "__main__":
    main()
