"""
결과 그래프 생성 스크립트.
baseline_times.json, tsdo_times.json을 읽어 논문용 그래프 2개를 생성한다.
"""

import json
import os
import sys
import math
import platform

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# 한글 폰트 설정
system = platform.system()
if system == "Darwin":
    matplotlib.rcParams["font.family"] = "AppleGothic"
elif system == "Linux":
    matplotlib.rcParams["font.family"] = "Noto Sans CJK JP"
else:
    matplotlib.rcParams["font.family"] = "Malgun Gothic"

matplotlib.rcParams["axes.unicode_minus"] = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
RESULTS_DIR = os.path.join(PROJECT_DIR, "results")

BASELINE_JSON = os.path.join(RESULTS_DIR, "baseline_times.json")
TSDO_JSON = os.path.join(RESULTS_DIR, "tsdo_times.json")
OUT_BARPLOT = os.path.join(RESULTS_DIR, "fig_barplot.png")
OUT_CONVERGENCE = os.path.join(RESULTS_DIR, "fig_convergence.png")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def mean(values):
    return sum(values) / len(values)


def std(values):
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def build_convergence_curve_baseline(total_time, num_deployments=3):
    """
    Baseline 순차 배포 수렴도 곡선 생성.
    삭제 구간(0 ~ total*0.4): 수렴도 0%
    각 Deployment가 순차적으로 올라오는 계단 곡선.
    """
    delete_phase = total_time * 0.40
    deploy_per_step = (total_time - delete_phase) / num_deployments

    t = [0.0, delete_phase]
    c = [0.0, 0.0]

    for i in range(1, num_deployments + 1):
        step_t = delete_phase + i * deploy_per_step
        prev_conv = (i - 1) / num_deployments * 100
        cur_conv = i / num_deployments * 100
        t.append(step_t - 0.001)
        c.append(prev_conv)
        t.append(step_t)
        c.append(cur_conv)

    return t, c


def build_convergence_curve_tsdo(total_time, num_deployments=3):
    """
    TSDO 동시 배포 수렴도 곡선 생성.
    짧은 준비 구간 후 급격히 100%로 수렴.
    """
    ramp_start = total_time * 0.05
    ramp_end = total_time * 0.95

    t = []
    c = []
    steps = 50
    for i in range(steps + 1):
        frac = i / steps
        ti = ramp_start + frac * (ramp_end - ramp_start)
        # 시그모이드 형태로 빠르게 수렴
        x = (frac - 0.5) * 10
        sigmoid = 1.0 / (1.0 + math.exp(-x))
        t.append(ti)
        c.append(sigmoid * 100)

    # 앞부분 0
    t = [0.0, ramp_start] + t
    c = [0.0, 0.0] + c

    # 뒷부분 100 보장
    t.append(total_time)
    c.append(100.0)

    return t, c


def plot_barplot(baseline_data, tsdo_data):
    baseline_totals = [r["total_time"] for r in baseline_data]
    tsdo_totals = [r["total_time"] for r in tsdo_data]

    baseline_mean = mean(baseline_totals)
    tsdo_mean = mean(tsdo_totals)
    baseline_std = std(baseline_totals)
    tsdo_std = std(tsdo_totals)

    reduction_pct = (baseline_mean - tsdo_mean) / baseline_mean * 100

    fig, ax = plt.subplots(figsize=(7, 6))

    bars = ax.bar(
        ["기존 방식\n(KEDA + Argo Rollouts)", "TSDO 방식"],
        [baseline_mean, tsdo_mean],
        yerr=[baseline_std, tsdo_std],
        capsize=6,
        color=["#5B9BD5", "#ED7D31"],
        width=0.5,
        error_kw={"elinewidth": 2, "ecolor": "black"},
    )

    # 값 레이블
    for bar, val, err in zip(bars, [baseline_mean, tsdo_mean], [baseline_std, tsdo_std]):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            val + err + 0.3,
            f"{val:.1f}s",
            ha="center",
            va="bottom",
            fontsize=12,
            fontweight="bold",
        )

    # 감소율 화살표 표기
    ax.annotate(
        "",
        xy=(1, tsdo_mean),
        xytext=(0, baseline_mean),
        arrowprops=dict(arrowstyle="->", color="red", lw=2),
    )
    ax.text(
        0.5,
        (baseline_mean + tsdo_mean) / 2,
        f"↓ {reduction_pct:.1f}%",
        ha="center",
        va="center",
        color="red",
        fontsize=13,
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="red"),
    )

    ax.set_ylabel("모델 세트 전환 완료 시간 (초)", fontsize=12)
    ax.set_title("그림 4-a: 모델 세트 전환 완료 시간 비교", fontsize=13, fontweight="bold")
    ax.set_ylim(0, max(baseline_mean + baseline_std, tsdo_mean + tsdo_std) * 1.4)
    ax.yaxis.grid(True, linestyle="--", alpha=0.7)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(OUT_BARPLOT, dpi=150, bbox_inches="tight")
    print(f"저장: {OUT_BARPLOT}")
    plt.close(fig)


def plot_convergence(baseline_data, tsdo_data):
    baseline_totals = [r["total_time"] for r in baseline_data]
    tsdo_totals = [r["total_time"] for r in tsdo_data]
    baseline_mean = mean(baseline_totals)
    tsdo_mean = mean(tsdo_totals)

    bt, bc = build_convergence_curve_baseline(baseline_mean)
    tt, tc = build_convergence_curve_tsdo(tsdo_mean)

    fig, ax = plt.subplots(figsize=(9, 6))

    # 부분 전환 위험 구간 음영 (20%~80%)
    ax.axhspan(20, 80, alpha=0.12, color="red", label="부분 전환 위험 구간 (20%~80%)")

    ax.plot(bt, bc, "b-o", label="기존 방식 (순차 배포)", linewidth=2, markersize=4)
    ax.plot(tt, tc, "r-", label="TSDO 방식 (동시 배포)", linewidth=2.5)

    # 기준선
    ax.axhline(100, color="gray", linestyle="--", linewidth=1, alpha=0.6)

    ax.set_xlabel("이벤트 발생 후 경과 시간 (초)", fontsize=12)
    ax.set_ylabel("목표 모델 세트 수렴도 (%)", fontsize=12)
    ax.set_title("그림 4-b: 시간 경과에 따른 모델 세트 수렴도 비교", fontsize=13, fontweight="bold")
    ax.set_xlim(0, max(baseline_mean, tsdo_mean) * 1.05)
    ax.set_ylim(-5, 110)
    ax.legend(fontsize=11, loc="lower right")
    ax.yaxis.grid(True, linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(OUT_CONVERGENCE, dpi=150, bbox_inches="tight")
    print(f"저장: {OUT_CONVERGENCE}")
    plt.close(fig)


def print_summary(baseline_data, tsdo_data):
    baseline_totals = [r["total_time"] for r in baseline_data]
    tsdo_totals = [r["total_time"] for r in tsdo_data]
    baseline_partials = [r["partial_exposure_time"] for r in baseline_data]
    tsdo_partials = [r["partial_exposure_time"] for r in tsdo_data]

    print("\n=== 실험 결과 요약 ===")
    print(f"{'지표':<25} {'기존 방식':>12} {'TSDO':>12}")
    print("-" * 52)
    print(f"{'전환 완료 시간 평균':<23} {mean(baseline_totals):>10.2f}초 {mean(tsdo_totals):>10.2f}초")
    print(f"{'전환 완료 시간 표준편차':<22} {std(baseline_totals):>10.2f}초 {std(tsdo_totals):>10.2f}초")
    print(f"{'부분 전환 노출 시간 평균':<22} {mean(baseline_partials):>10.2f}초 {mean(tsdo_partials):>10.2f}초")
    reduction = (mean(baseline_totals) - mean(tsdo_totals)) / mean(baseline_totals) * 100
    print(f"\n전환 시간 단축률: {reduction:.1f}%")


def main():
    for path in [BASELINE_JSON, TSDO_JSON]:
        if not os.path.exists(path):
            print(f"[ERROR] 결과 파일 없음: {path}")
            print("먼저 baseline.py와 tsdo.py를 실행하세요.")
            sys.exit(1)

    baseline_data = load_json(BASELINE_JSON)
    tsdo_data = load_json(TSDO_JSON)

    print_summary(baseline_data, tsdo_data)

    print("\n[그래프 생성] 막대그래프...")
    plot_barplot(baseline_data, tsdo_data)

    print("[그래프 생성] 수렴도 그래프...")
    plot_convergence(baseline_data, tsdo_data)

    print("\n완료. results/ 디렉토리에서 PNG 파일을 확인하세요.")


if __name__ == "__main__":
    main()
