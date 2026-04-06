import json
import os
import sys
from collections import defaultdict
from datetime import datetime


def _safe_float(val):
    try:
        return float(val)
    except Exception:
        return None


def _load_records(path):
    if not os.path.exists(path):
        print(f"ERROR: File not found: {path}")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("records", [])
    except Exception as exc:
        print(f"ERROR: Failed to read {path}: {exc}")
    return []


def _get_outcome(rec):
    # Prefer r_multiple if present; else pnl/profit
    r_mult = _safe_float(rec.get("r_multiple"))
    pnl = _safe_float(rec.get("pnl"))
    profit = _safe_float(rec.get("profit"))
    outcome = None
    if r_mult is not None:
        outcome = r_mult
    elif pnl is not None:
        outcome = pnl
    elif profit is not None:
        outcome = profit
    return outcome


def _is_win(outcome):
    if outcome is None:
        return None
    return outcome > 0


def _regime_bucket(regime):
    reg = str(regime or "UNKNOWN").upper()
    if "TREND" in reg:
        return "TRENDING"
    if "RANG" in reg:
        return "RANGING"
    if "LOW_LIQ" in reg:
        return "LOW_LIQUIDITY"
    return "OTHER"


def _parse_dt(val):
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val))
    except Exception:
        return None


def _load_exit_history(path="exit_history.json"):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else data.get("records", [])
    except Exception:
        return []


def _pip_size(symbol):
    return 0.01 if "JPY" in str(symbol or "").upper() else 0.0001


def _match_exit_record(attrib_rec, exit_records):
    """
    Strict match by symbol + direction + entry price proximity + tight time delta.
    """
    sym = str(attrib_rec.get("symbol") or "")
    ts = _parse_dt(attrib_rec.get("timestamp"))
    entry_px = _safe_float(attrib_rec.get("entry_price"))
    direction = str(attrib_rec.get("direction") or "").upper()
    if not sym or ts is None or entry_px is None or not direction:
        return None
    candidates = [r for r in exit_records if str(r.get("symbol") or "") == sym]
    if not candidates:
        return None
    best = None
    best_delta = None
    pip = _pip_size(sym)
    for r in candidates:
        entry_t = _parse_dt(r.get("entry_time"))
        if entry_t is None:
            continue
        r_dir = str(r.get("direction") or "").upper()
        if r_dir and direction and r_dir != direction:
            continue
        r_entry = _safe_float(r.get("entry_price"))
        if r_entry is None:
            continue
        if abs(r_entry - entry_px) > (5 * pip):
            continue
        delta = abs((entry_t - ts).total_seconds())
        if delta > 600:
            continue
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best = r
    return best


def _format_table(headers, rows):
    try:
        from tabulate import tabulate
        return tabulate(rows, headers=headers, tablefmt="github")
    except Exception:
        # simple fallback
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(cell)))
        sep = " | "
        header_line = sep.join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers))
        divider = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
        lines = [header_line, divider]
        for row in rows:
            lines.append(sep.join(str(row[i]).ljust(col_widths[i]) for i in range(len(headers))))
        return "\n".join(lines)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join("logs", "trade_attribution.json")
    records = _load_records(path)
    if not records:
        print("No records available.")
        return

    exit_records = _load_exit_history()

    # Normalize records
    norm = []
    for rec in records:
        attrib = rec.get("attribution") or {}
        ob = bool(attrib.get("OB"))
        fvg = bool(attrib.get("FVG"))
        sweep = bool(attrib.get("Sweep"))
        regime = attrib.get("Regime")
        strength = _safe_float(attrib.get("Strength"))
        conviction = attrib.get("Conviction", "UNKNOWN")
        dynamic_rr = _safe_float(rec.get("dynamic_rr"))
        outcome = _get_outcome(rec)
        win = _is_win(outcome)
        authority_level = str(rec.get("authority_level") or "LEVEL_3").upper()
        pruning_status = str(rec.get("pruning_status") or "ACTIVE")
        regime_risk_weight = _safe_float(rec.get("regime_risk_weight"))
        effective_threshold = _safe_float(rec.get("effective_threshold"))
        confidence = _safe_float(rec.get("confidence")) or _safe_float(rec.get("signal_confidence")) or _safe_float(rec.get("ml_confidence"))
        norm.append({
            "ob": ob,
            "fvg": fvg,
            "sweep": sweep,
            "regime": regime,
            "strength": strength,
            "conviction": conviction,
            "dynamic_rr": dynamic_rr,
            "outcome": outcome,
            "win": win,
            "timestamp": rec.get("timestamp"),
            "authority_level": authority_level,
            "pruning_status": pruning_status,
            "regime_risk_weight": regime_risk_weight,
            "effective_threshold": effective_threshold,
            "confidence": confidence,
            "raw": rec,
        })

    print("\nSTRATEGIC INTELLIGENCE REPORT")
    print("=" * 34)

    # 1) Confluence Win-Rate Matrix
    matrix = defaultdict(list)
    for r in norm:
        key = (r["ob"], r["fvg"], r["sweep"])
        matrix[key].append(r)

    rows = []
    for (ob, fvg, sweep), items in sorted(matrix.items()):
        wins = [x for x in items if x["win"] is True]
        losses = [x for x in items if x["win"] is False]
        win_rate = (len(wins) / max(1, (len(wins) + len(losses)))) * 100 if (wins or losses) else None
        outcomes = [x["outcome"] for x in items if x["outcome"] is not None]
        avg_r = sum(outcomes) / len(outcomes) if outcomes else None
        rows.append([
            f"OB={ob},FVG={fvg},Sweep={sweep}",
            len(items),
            f"{win_rate:.1f}%" if win_rate is not None else "n/a",
            f"{avg_r:.2f}" if avg_r is not None else "n/a",
        ])

    print("\n1) Confluence Win-Rate Matrix")
    print(_format_table(["Combo", "N", "Win%", "Avg R"], rows))

    # 2) SMC Component Profit Factor
    def _profit_factor(items):
        wins = sum(x["outcome"] for x in items if x["outcome"] is not None and x["outcome"] > 0)
        losses = sum(abs(x["outcome"]) for x in items if x["outcome"] is not None and x["outcome"] < 0)
        if losses == 0:
            return "inf" if wins > 0 else "n/a"
        return f"{(wins / losses):.2f}"

    ob_items = [r for r in norm if r["ob"]]
    fvg_items = [r for r in norm if r["fvg"]]
    sweep_items = [r for r in norm if r["sweep"]]
    pf_rows = [
        ["OB_Profit_Factor", _profit_factor(ob_items), len(ob_items)],
        ["FVG_Profit_Factor", _profit_factor(fvg_items), len(fvg_items)],
        ["Sweep_Profit_Factor", _profit_factor(sweep_items), len(sweep_items)],
    ]
    print("\n2) Alpha Discovery (SMC Profit Factor)")
    print(_format_table(["Component", "Profit Factor", "N"], pf_rows))

    # 3) Strength-to-Profit Correlation
    buckets = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9]
    bucket_rows = []
    for threshold in buckets:
        items = [r for r in norm if r["strength"] is not None and r["strength"] >= threshold]
        wins = [x for x in items if x["win"] is True]
        losses = [x for x in items if x["win"] is False]
        win_rate = (len(wins) / max(1, (len(wins) + len(losses)))) * 100 if (wins or losses) else None
        bucket_rows.append([
            f">= {threshold:.1f}",
            len(items),
            f"{win_rate:.1f}%" if win_rate is not None else "n/a",
        ])

    print("\n3) Strength-to-Profit Correlation (Sweet Spot)")
    print(_format_table(["Strength", "N", "Win%"], bucket_rows))

    sweet = None
    best_rate = -1
    for row in bucket_rows:
        if row[2] == "n/a":
            continue
        rate = float(row[2].strip("%"))
        if rate > best_rate:
            best_rate = rate
            sweet = row[0]
    if sweet:
        print(f"\nSweet Spot Suggestion: strength {sweet} shows highest win-rate (~{best_rate:.1f}%).")
    else:
        print("\nSweet Spot Suggestion: insufficient outcome data.")

    # 4) Dynamic RR Audit
    rr_rows = []
    rr_items = [r for r in norm if r["dynamic_rr"] is not None and r["outcome"] is not None]
    if rr_items:
        avg_target = sum(r["dynamic_rr"] for r in rr_items) / len(rr_items)
        avg_real = sum(r["outcome"] for r in rr_items) / len(rr_items)
        rr_rows.append([len(rr_items), f"{avg_target:.2f}", f"{avg_real:.2f}"])
        print("\n4) Dynamic RR Audit")
        print(_format_table(["N", "Avg Target RR", "Avg Real RR"], rr_rows))
        if avg_real < avg_target - 0.5:
            print("Target Optimization Suggestion: actual outcomes are significantly below target. Consider reducing RR targets or adding earlier scale-outs.")
    else:
        print("\n4) Dynamic RR Audit")
        print("No outcome data available (r_multiple/pnl/profit missing).")

    # 5) Regime Performance Filter
    regime_groups = defaultdict(list)
    for r in norm:
        regime_groups[_regime_bucket(r["regime"])].append(r)
    reg_rows = []
    for reg, items in sorted(regime_groups.items()):
        wins = [x for x in items if x["win"] is True]
        losses = [x for x in items if x["win"] is False]
        win_rate = (len(wins) / max(1, (len(wins) + len(losses)))) * 100 if (wins or losses) else None
        outcomes = [x["outcome"] for x in items if x["outcome"] is not None]
        avg_r = sum(outcomes) / len(outcomes) if outcomes else None
        reg_rows.append([reg, len(items), f"{win_rate:.1f}%" if win_rate is not None else "n/a", f"{avg_r:.2f}" if avg_r is not None else "n/a"])

    print("\n5) Regime Performance Filter")
    print(_format_table(["Regime", "N", "Win%", "Avg R"], reg_rows))

    # 6) Pruning Effectiveness Audit
    pruned = [r for r in norm if str(r["pruning_status"]).upper() == "PRUNED"]
    pruned_winners = 0
    pruned_matched = 0
    for r in pruned:
        exit_rec = _match_exit_record(r["raw"], exit_records)
        if exit_rec:
            pruned_matched += 1
            mfe = _safe_float(exit_rec.get("mfe"))
            if mfe is not None and mfe >= 3.5:
                pruned_winners += 1
    print("\n6) Pruning Effectiveness Audit")
    if pruned:
        pct = (pruned_winners / max(1, len(pruned))) * 100
        print(_format_table(
            ["Pruned Trades", "Matched Exit Records", "Pruned Winners (MFE>=3.5R)", "% Pruned Winners"],
            [[len(pruned), pruned_matched, pruned_winners, f\"{pct:.1f}%\"]],
        ))
        if pct > 20:
            print("Actionable Advice: Pruned winners > 20%. Consider increasing grace window from 15 min to 30 min.")
    else:
        print("No PRUNED trades found in attribution log.")

    # 7) Regime Risk ROI
    regime_roi = defaultdict(list)
    for r in norm:
        if r["outcome"] is None:
            continue
        reg = _regime_bucket(r["regime"])
        w = r["regime_risk_weight"] if r["regime_risk_weight"] is not None else 1.0
        regime_roi[reg].append(r["outcome"] * w)
    roi_rows = []
    for reg, vals in sorted(regime_roi.items()):
        avg = sum(vals) / len(vals) if vals else None
        roi_rows.append([reg, len(vals), f"{avg:.2f}" if avg is not None else "n/a"])
    print("\n7) Regime Risk ROI (Outcome * Risk Weight)")
    print(_format_table(["Regime", "N", "Avg Weighted Outcome"], roi_rows))

    # 8) Performance by Authority Layer
    auth_groups = defaultdict(list)
    for r in norm:
        lvl = str(r.get("authority_level") or "LEVEL_3").upper()
        auth_groups[lvl].append(r)
    auth_rows = []
    for lvl, items in sorted(auth_groups.items()):
        outcomes = [x["outcome"] for x in items if x["outcome"] is not None]
        total_r = sum(outcomes) if outcomes else 0.0
        avg_r = (total_r / len(outcomes)) if outcomes else None
        auth_rows.append([
            lvl,
            len(items),
            f"{total_r:.2f}",
            f"{avg_r:.2f}" if avg_r is not None else "n/a",
        ])
    print("\n8) Performance by Authority Layer")
    print(_format_table(["Authority", "N", "Total R", "Avg R"], auth_rows))

    # 9) Near Miss Analysis (confidence between 0.05 and 0.08)
    near_miss = [r for r in norm if r["confidence"] is not None and 0.05 <= r["confidence"] < 0.08]
    print("\n9) Near Miss Analysis (0.05 <= confidence < 0.08)")
    if near_miss:
        outcomes = [r["outcome"] for r in near_miss if r["outcome"] is not None]
        avg_out = sum(outcomes) / len(outcomes) if outcomes else None
        print(_format_table(
            ["Count", "Avg Outcome"],
            [[len(near_miss), f"{avg_out:.2f}" if avg_out is not None else "n/a"]],
        ))
        if avg_out is not None:
            print("Est. Missed Profit Proxy: average outcome of near-miss signals (if admitted).")
    else:
        print("No confidence data in [0.05, 0.08). If logs lack confidence fields, this audit will be empty.")

    # 10) Fee & Swap Leak Test (BE+0.2R)
    be_hits = []
    if exit_records:
        for rec in exit_records:
            reason = str(rec.get("reason") or "").lower()
            r_mult = _safe_float(rec.get("r_multiple"))
            pnl = _safe_float(rec.get("profit_loss"))
            if "breakeven" in reason or "break-even" in reason or "be" in reason:
                if r_mult is not None and 0.15 <= r_mult <= 0.30:
                    be_hits.append((r_mult, pnl))
    print("\n10) Fee & Swap Leak Test (BE+0.2R)")
    if be_hits:
        avg_r = sum(x[0] for x in be_hits) / len(be_hits)
        pnl_vals = [x[1] for x in be_hits if x[1] is not None]
        avg_pnl = sum(pnl_vals) / len(pnl_vals) if pnl_vals else None
        print(_format_table(
            ["Count", "Avg R", "Avg PnL"],
            [[len(be_hits), f"{avg_r:.2f}", f"{avg_pnl:.2f}" if avg_pnl is not None else "n/a"]],
        ))
        if avg_r > 0:
            print("Result: BE+0.2R buffer appears to cover costs (positive average R).")
        else:
            print("Result: BE+0.2R buffer may be insufficient; consider widening offset.")
    else:
        print("No BE+0.2R exits found (reason or r_multiple missing).")

    # 11) Visual Output
    try:
        import matplotlib.pyplot as plt
        # Build equity curves by conviction
        curves = defaultdict(list)
        time_series = defaultdict(list)
        for r in norm:
            if r["outcome"] is None:
                continue
            conv = str(r["conviction"]) or "UNKNOWN"
            ts = r.get("timestamp")
            try:
                dt = datetime.fromisoformat(ts) if ts else None
            except Exception:
                dt = None
            if dt is None:
                dt = datetime.min
            time_series[conv].append(dt)
            curves[conv].append(r["outcome"])

        if curves:
            plt.figure(figsize=(10, 5))
            for conv, vals in curves.items():
                # Simple cumulative sum
                equity = []
                total = 0.0
                for v in vals:
                    total += v
                    equity.append(total)
                plt.plot(equity, label=conv)
            plt.title("Equity Curve by Conviction")
            plt.xlabel("Trades")
            plt.ylabel("Cumulative R / PnL")
            plt.legend()
            plt.tight_layout()
            plt.show()
        else:
            print("\n11) Visual Output: No outcome data available for plotting.")
    except Exception as exc:
        print(f"\n11) Visual Output: matplotlib not available or error ({exc}).")


if __name__ == "__main__":
    main()
