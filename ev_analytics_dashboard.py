"""
EV Analytics Dashboard

Standalone analytics utility for EV telemetry:
- Loads admission history JSON (trade_admission_history.json)
- Extracts EV/confidence/macro penalty + realized outcomes (if present)
- Optionally merges outcomes from exit history JSON (exit_history.json)
- Computes calibration metrics (Brier score, win-rate vs predicted prob)
- Produces institutional-grade plots with pandas + matplotlib
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# Candidate field names across versions
PROB_FIELDS = [
    "calibrated_ml_confidence",
    "adjusted_win_prob",
    "confidence",
]
EV_FIELDS = [
    "ev",
    "expected_value",
    "predicted_ev",
]
PENALTY_FIELDS = [
    "macro_risk_penalty",
    "macro_penalty",
]
PNL_R_FIELDS = [
    "realized_pnl_r",
    "pnl_r",
    "realized_r",
    "r_multiple",
    "profit_loss_r",
]
OUTCOME_FIELDS = [
    "outcome",
    "win",
    "is_win",
    "won",
]


@dataclass
class EvalSummary:
    sample_size: int
    brier_score: float
    realized_win_rate: float
    avg_predicted_prob: float
    avg_ev: float
    avg_realized_pnl_r: float


def _coalesce_numeric(df: pd.DataFrame, fields: Iterable[str], default: float = np.nan) -> pd.Series:
    out = pd.Series(np.nan, index=df.index, dtype="float64")
    for name in fields:
        if name in df.columns:
            out = out.fillna(pd.to_numeric(df[name], errors="coerce"))
    if not math.isnan(default):
        out = out.fillna(default)
    return out


def _coalesce_bool_as_float(df: pd.DataFrame, fields: Iterable[str]) -> pd.Series:
    out = pd.Series(np.nan, index=df.index, dtype="float64")
    for name in fields:
        if name in df.columns:
            col = df[name]
            if col.dtype == bool:
                out = out.fillna(col.astype(float))
            else:
                mapped = col.astype(str).str.strip().str.lower().map(
                    {"1": 1.0, "true": 1.0, "yes": 1.0, "y": 1.0, "win": 1.0,
                     "0": 0.0, "false": 0.0, "no": 0.0, "n": 0.0, "loss": 0.0}
                )
                out = out.fillna(pd.to_numeric(mapped, errors="coerce"))
    return out


def load_admission_history(path: str) -> pd.DataFrame:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    rows: List[Dict[str, Any]] = []
    if isinstance(payload, dict) and "opportunity_windows" in payload:
        windows = payload.get("opportunity_windows", {})
        for regime, records in windows.items():
            for rec in records or []:
                row = dict(rec)
                row.setdefault("regime", regime)
                rows.append(row)
    elif isinstance(payload, list):
        rows = [dict(x) for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict) and "records" in payload and isinstance(payload["records"], list):
        rows = [dict(x) for x in payload["records"] if isinstance(x, dict)]
    else:
        raise ValueError(f"Unsupported JSON shape in {path}")

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)

    df["pred_prob"] = _coalesce_numeric(df, PROB_FIELDS)
    df["pred_ev"] = _coalesce_numeric(df, EV_FIELDS)
    df["macro_risk_penalty"] = _coalesce_numeric(df, PENALTY_FIELDS, default=0.0)
    df["realized_pnl_r"] = _coalesce_numeric(df, PNL_R_FIELDS)

    outcome = _coalesce_bool_as_float(df, OUTCOME_FIELDS)
    if "realized_pnl_r" in df.columns:
        outcome_from_pnl = (df["realized_pnl_r"] > 0).astype(float)
        outcome = outcome.fillna(outcome_from_pnl)
    df["outcome"] = outcome

    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].astype(str)
    if "was_admitted" in df.columns:
        df["was_admitted"] = df["was_admitted"].astype(bool)

    return df


def merge_outcomes_from_exit_history(
    admission_df: pd.DataFrame,
    exit_history_path: str,
    tolerance_minutes: int = 120,
) -> pd.DataFrame:
    if admission_df.empty or "timestamp" not in admission_df.columns or "symbol" not in admission_df.columns:
        return admission_df
    if not os.path.exists(exit_history_path):
        return admission_df

    with open(exit_history_path, "r", encoding="utf-8") as f:
        exits_payload = json.load(f)
    if not isinstance(exits_payload, list):
        return admission_df

    exits_df = pd.DataFrame([x for x in exits_payload if isinstance(x, dict)])
    if exits_df.empty or "symbol" not in exits_df.columns or "entry_time" not in exits_df.columns:
        return admission_df

    exits_df["entry_time"] = pd.to_datetime(exits_df["entry_time"], errors="coerce", utc=True)
    exits_df["symbol"] = exits_df["symbol"].astype(str)
    exits_df["realized_pnl_r_exit"] = _coalesce_numeric(exits_df, PNL_R_FIELDS)
    if "realized_pnl_r_exit" not in exits_df or exits_df["realized_pnl_r_exit"].isna().all():
        if "profit_loss" in exits_df.columns:
            exits_df["realized_pnl_r_exit"] = pd.to_numeric(exits_df["profit_loss"], errors="coerce")

    admissions = admission_df.copy().sort_values("timestamp")
    exits = exits_df.sort_values("entry_time")

    merged_parts: List[pd.DataFrame] = []
    for sym, part in admissions.groupby("symbol", dropna=False):
        part_exits = exits[exits["symbol"] == sym]
        if part_exits.empty:
            merged_parts.append(part)
            continue
        m = pd.merge_asof(
            part.sort_values("timestamp"),
            part_exits[["entry_time", "realized_pnl_r_exit"]].sort_values("entry_time"),
            left_on="timestamp",
            right_on="entry_time",
            direction="nearest",
            tolerance=pd.Timedelta(minutes=tolerance_minutes),
        )
        merged_parts.append(m)

    merged = pd.concat(merged_parts, ignore_index=True)
    if "realized_pnl_r_exit" in merged.columns:
        merged["realized_pnl_r"] = merged["realized_pnl_r"].fillna(merged["realized_pnl_r_exit"])
        merged["outcome"] = merged["outcome"].fillna((merged["realized_pnl_r"] > 0).astype(float))
    return merged


def clean_eval_dataset(df: pd.DataFrame, admitted_only: bool = True) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()
    if admitted_only and "was_admitted" in out.columns:
        out = out[out["was_admitted"] == True]  # noqa: E712

    out["pred_prob"] = pd.to_numeric(out["pred_prob"], errors="coerce").clip(0.0, 1.0)
    out["pred_ev"] = pd.to_numeric(out["pred_ev"], errors="coerce")
    out["macro_risk_penalty"] = pd.to_numeric(out["macro_risk_penalty"], errors="coerce").fillna(0.0).clip(0.0, 0.4)
    out["realized_pnl_r"] = pd.to_numeric(out.get("realized_pnl_r"), errors="coerce")
    out["outcome"] = pd.to_numeric(out.get("outcome"), errors="coerce")

    out = out.dropna(subset=["pred_prob", "pred_ev"])
    out = out[(out["pred_prob"] >= 0.0) & (out["pred_prob"] <= 1.0)]

    # Keep rows where we can evaluate realized outcomes.
    if "outcome" in out.columns:
        has_outcome = out["outcome"].notna()
    else:
        has_outcome = pd.Series(False, index=out.index)
    if "realized_pnl_r" in out.columns:
        has_pnl = out["realized_pnl_r"].notna()
    else:
        has_pnl = pd.Series(False, index=out.index)

    out = out[has_outcome | has_pnl].copy()
    out["outcome"] = out["outcome"].fillna((out["realized_pnl_r"] > 0).astype(float))
    # Plot-safe realized R: use actual realized_pnl_r when available; else fallback to +/-1R proxy from binary outcome.
    out["realized_pnl_r_plot"] = out["realized_pnl_r"]
    proxy_r = out["outcome"].map({1.0: 1.0, 0.0: -1.0})
    out["realized_pnl_r_plot"] = out["realized_pnl_r_plot"].fillna(proxy_r)

    return out


def compute_summary(df: pd.DataFrame) -> EvalSummary:
    y = df["outcome"].astype(float).clip(0, 1)
    p = df["pred_prob"].astype(float).clip(0, 1)
    brier = float(np.mean((p - y) ** 2))

    return EvalSummary(
        sample_size=int(len(df)),
        brier_score=brier,
        realized_win_rate=float(y.mean()),
        avg_predicted_prob=float(p.mean()),
        avg_ev=float(df["pred_ev"].mean()),
        avg_realized_pnl_r=float(df["realized_pnl_r_plot"].mean()),
    )


def plot_ev_vs_realized(df: pd.DataFrame, out_dir: str) -> str:
    path = os.path.join(out_dir, "ev_vs_realized_pnl_scatter.png")
    plt.figure(figsize=(10, 6))
    plt.scatter(df["pred_ev"], df["realized_pnl_r_plot"], alpha=0.45, s=24, edgecolors="none")
    plt.axhline(0.0, color="gray", linestyle="--", linewidth=1.0)
    plt.axvline(0.0, color="gray", linestyle="--", linewidth=1.0)
    plt.xlabel("Predicted EV (R)")
    plt.ylabel("Realized PnL (R)")
    plt.title("Predicted EV vs Realized PnL")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    return path


def plot_calibration_curve(df: pd.DataFrame, out_dir: str, bins: int = 10) -> str:
    path = os.path.join(out_dir, "calibration_curve.png")
    work = df.copy()
    work["prob_bin"] = pd.cut(work["pred_prob"], bins=np.linspace(0.0, 1.0, bins + 1), include_lowest=True)
    agg = (
        work.groupby("prob_bin", observed=False)
        .agg(pred_prob_mean=("pred_prob", "mean"), actual_win_rate=("outcome", "mean"), n=("outcome", "size"))
        .dropna()
    )

    plt.figure(figsize=(8, 8))
    if not agg.empty:
        plt.plot(agg["pred_prob_mean"], agg["actual_win_rate"], marker="o", linewidth=2)
        for x, y, n in zip(agg["pred_prob_mean"], agg["actual_win_rate"], agg["n"]):
            plt.annotate(str(int(n)), (x, y), textcoords="offset points", xytext=(4, 4), fontsize=8)
    plt.plot([0, 1], [0, 1], linestyle="--", color="gray", label="Perfect calibration")
    plt.xlim(0.0, 1.0)
    plt.ylim(0.0, 1.0)
    plt.xlabel("Predicted Probability")
    plt.ylabel("Observed Win Rate")
    plt.title("Reliability Diagram (Calibration Curve)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    return path


def plot_macro_penalty_impact(df: pd.DataFrame, out_dir: str) -> str:
    path = os.path.join(out_dir, "macro_penalty_impact.png")
    work = df.copy()
    work["macro_group"] = np.where(work["macro_risk_penalty"] > 0.0, "Penalty > 0", "Penalty = 0")
    agg = (
        work.groupby("macro_group", observed=False)
        .agg(avg_realized_pnl_r=("realized_pnl_r_plot", "mean"), n=("realized_pnl_r_plot", "size"))
        .reindex(["Penalty = 0", "Penalty > 0"])
        .fillna(0.0)
    )

    plt.figure(figsize=(8, 5))
    bars = plt.bar(agg.index.astype(str), agg["avg_realized_pnl_r"], color=["#2E86AB", "#F05D5E"])
    plt.axhline(0.0, color="gray", linestyle="--", linewidth=1.0)
    plt.ylabel("Average Realized PnL (R)")
    plt.title("Macro Risk Penalty Impact on Realized Returns")
    for bar, n in zip(bars, agg["n"]):
        plt.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"n={int(n)}", ha="center", va="bottom")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    return path


def run_dashboard(
    admission_path: str,
    out_dir: str,
    outcomes_path: Optional[str] = None,
    admitted_only: bool = True,
    show: bool = False,
    match_tolerance_minutes: int = 120,
) -> Dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)

    raw = load_admission_history(admission_path)
    if raw.empty:
        raise RuntimeError(f"No records found in {admission_path}")

    # Optional merge from separate realized-trade history if outcomes missing.
    if outcomes_path:
        raw = merge_outcomes_from_exit_history(raw, outcomes_path, tolerance_minutes=match_tolerance_minutes)

    clean = clean_eval_dataset(raw, admitted_only=admitted_only)
    if clean.empty:
        raise RuntimeError(
            "No evaluable rows after cleaning. Need realized outcomes (win/loss or pnl_r) "
            "in admission JSON, or provide --outcomes-json (e.g. exit_history.json)."
        )

    summary = compute_summary(clean)
    scatter_path = plot_ev_vs_realized(clean, out_dir)
    calib_path = plot_calibration_curve(clean, out_dir, bins=10)
    macro_path = plot_macro_penalty_impact(clean, out_dir)

    results = {
        "summary": {
            "sample_size": summary.sample_size,
            "brier_score": summary.brier_score,
            "realized_win_rate": summary.realized_win_rate,
            "avg_predicted_probability": summary.avg_predicted_prob,
            "avg_predicted_ev_r": summary.avg_ev,
            "avg_realized_pnl_r": summary.avg_realized_pnl_r,
        },
        "plots": {
            "ev_vs_realized_scatter": scatter_path,
            "calibration_curve": calib_path,
            "macro_penalty_impact": macro_path,
        },
    }

    with open(os.path.join(out_dir, "ev_analytics_summary.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    if show:
        # Re-open saved files for interactive sessions if needed.
        for p in [scatter_path, calib_path, macro_path]:
            img = plt.imread(p)
            plt.figure(figsize=(10, 6))
            plt.imshow(img)
            plt.axis("off")
            plt.tight_layout()
        plt.show()

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EV telemetry analytics dashboard")
    parser.add_argument(
        "--admission-json",
        default="trade_admission_history.json",
        help="Path to admission history JSON file",
    )
    parser.add_argument(
        "--outcomes-json",
        default="exit_history.json",
        help="Optional path to realized outcomes JSON (set empty string to disable)",
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join("reports", "ev_analytics"),
        help="Directory for output plots and summary JSON",
    )
    parser.add_argument(
        "--include-rejected",
        action="store_true",
        help="Include rejected signals if they contain realized outcomes",
    )
    parser.add_argument(
        "--match-tolerance-minutes",
        type=int,
        default=120,
        help="Timestamp tolerance for merging admission rows with exit history",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display plots interactively",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outcomes_path = args.outcomes_json.strip() if args.outcomes_json is not None else ""
    if not outcomes_path:
        outcomes_path = None

    results = run_dashboard(
        admission_path=args.admission_json,
        out_dir=args.output_dir,
        outcomes_path=outcomes_path,
        admitted_only=not args.include_rejected,
        show=args.show,
        match_tolerance_minutes=args.match_tolerance_minutes,
    )

    summary = results["summary"]
    print("EV Analytics Summary")
    print(f"- Sample size: {summary['sample_size']}")
    print(f"- Brier score: {summary['brier_score']:.6f}")
    print(f"- Realized win rate: {summary['realized_win_rate']:.2%}")
    print(f"- Avg predicted probability: {summary['avg_predicted_probability']:.2%}")
    print(f"- Avg predicted EV (R): {summary['avg_predicted_ev_r']:.4f}")
    print(f"- Avg realized PnL (R): {summary['avg_realized_pnl_r']:.4f}")
    print("Output files:")
    for name, path in results["plots"].items():
        print(f"- {name}: {path}")


if __name__ == "__main__":
    main()
