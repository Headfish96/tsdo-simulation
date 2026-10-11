"""
Baseline 방식 측정 스크립트.
KEDA + Argo Rollouts 방식을 재현: Deployment를 하나씩 순차적으로 삭제/배포.
"""

import subprocess
import time
import json
import os
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
YAML_DIR = os.path.join(PROJECT_DIR, "yamls")
RESULTS_DIR = os.path.join(PROJECT_DIR, "results")

ISR_YAML = os.path.join(YAML_DIR, "isr-modelset.yaml")
ENGAGEMENT_YAML = os.path.join(YAML_DIR, "engagement-modelset.yaml")

ISR_DEPLOYMENTS = ["anomaly-detection", "pattern-analysis"]
ENGAGEMENT_DEPLOYMENTS = ["target-tracking", "threat-assessment", "strike-recommendation"]

TIMEOUT = "120s"

SINGLE_YAMLS = {
    "target-tracking": """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: target-tracking
  labels:
    mission: engagement
    model-set: "true"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: target-tracking
  template:
    metadata:
      labels:
        app: target-tracking
    spec:
      containers:
      - name: model
        image: nginx:alpine
        resources:
          requests:
            cpu: "150m"
            memory: "128Mi"
""",
    "threat-assessment": """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: threat-assessment
  labels:
    mission: engagement
    model-set: "true"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: threat-assessment
  template:
    metadata:
      labels:
        app: threat-assessment
    spec:
      containers:
      - name: model
        image: nginx:alpine
        resources:
          requests:
            cpu: "150m"
            memory: "128Mi"
""",
    "strike-recommendation": """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: strike-recommendation
  labels:
    mission: engagement
    model-set: "true"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: strike-recommendation
  template:
    metadata:
      labels:
        app: strike-recommendation
    spec:
      containers:
      - name: model
        image: nginx:alpine
        resources:
          requests:
            cpu: "100m"
            memory: "128Mi"
""",
}


def run_cmd(cmd, check=True):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"[ERROR] 명령 실패: {cmd}")
        print(result.stderr)
        sys.exit(1)
    return result


def apply_single_deployment(name):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(SINGLE_YAMLS[name])
        tmp_path = f.name
    try:
        run_cmd(f"kubectl apply -f {tmp_path}")
    finally:
        os.unlink(tmp_path)


def wait_deployment_available(name, timeout=TIMEOUT):
    print(f"  → {name} Ready 대기...")
    run_cmd(f"kubectl wait --for=condition=available deployment/{name} --timeout={timeout}")


def wait_pods_deleted(app_label, timeout=TIMEOUT):
    print(f"  → {app_label} Pod 종료 대기...")
    run_cmd(
        f"kubectl wait --for=delete pod -l app={app_label} --timeout={timeout}",
        check=False,
    )


def cleanup():
    print("[정리] 기존 Deployment 삭제 중...")
    run_cmd(f"kubectl delete -f {ISR_YAML} --ignore-not-found=true", check=False)
    run_cmd(f"kubectl delete -f {ENGAGEMENT_YAML} --ignore-not-found=true", check=False)
    time.sleep(10)


def run_baseline_once(run_id):
    print(f"\n=== Baseline Run #{run_id} ===")

    # 1. ISR 모델 세트 배포 및 준비
    print("[준비] ISR 모델 세트 배포...")
    run_cmd(f"kubectl apply -f {ISR_YAML}")
    for dep in ISR_DEPLOYMENTS:
        wait_deployment_available(dep)
    print("[준비] ISR 모델 세트 Ready 완료")

    # 타이머 시작
    t_start = time.time()

    # 4. 순차 처리 (Baseline의 핵심)
    print("[전환] 순차 처리 시작...")

    # a-b. anomaly-detection 삭제 및 Pod 종료 대기
    print("  [삭제] anomaly-detection...")
    run_cmd("kubectl delete deployment anomaly-detection --ignore-not-found=true")
    wait_pods_deleted("anomaly-detection")

    # c-d. pattern-analysis 삭제 및 Pod 종료 대기
    print("  [삭제] pattern-analysis...")
    run_cmd("kubectl delete deployment pattern-analysis --ignore-not-found=true")
    wait_pods_deleted("pattern-analysis")

    # e-f. target-tracking 배포 및 Ready 대기
    print("  [배포] target-tracking...")
    apply_single_deployment("target-tracking")
    partial_start = time.time()
    wait_deployment_available("target-tracking")

    # g-h. threat-assessment 배포 및 Ready 대기
    print("  [배포] threat-assessment...")
    apply_single_deployment("threat-assessment")
    wait_deployment_available("threat-assessment")

    # i-j. strike-recommendation 배포 및 Ready 대기
    print("  [배포] strike-recommendation...")
    apply_single_deployment("strike-recommendation")
    wait_deployment_available("strike-recommendation")
    partial_end = time.time()

    # 타이머 종료
    t_end = time.time()

    total_time = t_end - t_start
    partial_exposure = partial_end - partial_start

    print(f"  전환 완료 시간: {total_time:.2f}초")
    print(f"  부분 전환 노출 시간: {partial_exposure:.2f}초")

    # 정리
    run_cmd(f"kubectl delete -f {ENGAGEMENT_YAML} --ignore-not-found=true", check=False)
    time.sleep(10)

    return {"total_time": total_time, "partial_exposure_time": partial_exposure}


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    print("=== Baseline 실험 시작 (10회 반복) ===")
    print("환경 확인 중...")
    run_cmd("kubectl cluster-info")

    cleanup()

    results = []
    for i in range(1, 11):
        result = run_baseline_once(i)
        results.append(result)

    output_path = os.path.join(RESULTS_DIR, "baseline_times.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    total_times = [r["total_time"] for r in results]
    partial_times = [r["partial_exposure_time"] for r in results]
    avg_total = sum(total_times) / len(total_times)
    avg_partial = sum(partial_times) / len(partial_times)

    print(f"\n=== Baseline 실험 완료 ===")
    print(f"평균 전환 완료 시간: {avg_total:.2f}초")
    print(f"평균 부분 전환 노출 시간: {avg_partial:.2f}초")
    print(f"결과 저장: {output_path}")


if __name__ == "__main__":
    main()
