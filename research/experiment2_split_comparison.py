"""Experiment 2: compare unsupervised anomaly flags across train/test ratios.

Reads the configured historical SQLite database in read-only mode. The regular
70:30, 80:20 and 90:10 experiments use each ratio's own held-out cohort. The
stability analysis separately scores all fitted models on one common 10% cohort
with nested training prefixes, so its Jaccard values compare identical projects.
No ground-truth labels or supervised metrics are used.
"""
from __future__ import annotations

import importlib.metadata
import json
import sqlite3
import sys
import time
import warnings
from pathlib import Path
from typing import Any

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from sklearn.covariance import EllipticEnvelope
    from sklearn.ensemble import IsolationForest
    from sklearn.neighbors import LocalOutlierFactor
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import OneClassSVM
except ImportError as exc:
    raise SystemExit(f"Missing experiment dependency: {exc}. Required: numpy, pandas, scikit-learn, matplotlib") from exc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from backend.database import HISTORICAL_DB_PATH
except Exception as exc:
    raise SystemExit(f"Could not read configured historical database path: {exc}") from exc

FEATURES = ["sanction_amount", "total_disbursed", "budget_disbursement_ratio",
            "sanction_lead_time_days", "payment_tranche_count", "max_single_tranche_ratio",
            "work_description_length"]
IDENTIFIERS = ["work_id", "state", "district"]
TABLE = "project_monitoring_features"
SEED = 42
CONTAMINATION = 0.05
RATIOS = [("70:30", .70), ("80:20", .80), ("90:10", .90)]
MODELS = ["Isolation Forest", "Local Outlier Factor", "One-Class SVM", "Elliptic Envelope"]
OUT_BASE = ROOT / "research" / "experiment2_results"


def load_data(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not path.is_file():
        raise RuntimeError(f"Configured historical database does not exist: {path}")
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone():
            raise RuntimeError(f"Feature table {TABLE!r} is absent")
        available = {r[1] for r in conn.execute(f'PRAGMA table_info("{TABLE}")')}
        missing = [x for x in ["work_id", *FEATURES] if x not in available]
        if missing:
            raise RuntimeError(f"Missing required feature columns: {missing}")
        columns = [c for c in IDENTIFIERS if c in available] + FEATURES
        q = ", ".join('"' + c.replace('"', '""') + '"' for c in columns)
        df = pd.read_sql_query(f'SELECT {q} FROM "{TABLE}"', conn)
    source_rows = len(df)
    no_id = df.work_id.isna() | df.work_id.astype(str).str.strip().eq("")
    excluded_ids = int(no_id.sum())
    df = df.loc[~no_id].copy()
    df["work_id"] = df.work_id.astype(str).str.strip()
    dup = int(df.work_id.duplicated(keep=False).sum())
    if dup:
        raise RuntimeError(f"Duplicate work_id rows found ({dup}); refusing ambiguous project-level experiment")
    missing_counts, nonfinite_counts = {}, {}
    for col in FEATURES:
        series = pd.to_numeric(df[col], errors="coerce")
        vals = series.to_numpy(dtype=float, na_value=np.nan)
        missing_counts[col] = int(np.isnan(vals).sum())
        nonfinite_counts[col] = int((~np.isfinite(vals) & ~np.isnan(vals)).sum())
        df[col] = series.where(np.isfinite(vals), np.nan)
    quality = {"source_rows": source_rows, "eligible_rows": len(df), "rows_excluded_missing_work_id": excluded_ids,
              "duplicate_work_id_rows": dup, "missing_values_by_feature_before_imputation": missing_counts,
              "nonfinite_values_by_feature_before_imputation": nonfinite_counts,
              "excluded_rows_total": excluded_ids}
    if len(df) < 100:
        raise RuntimeError(f"Only {len(df)} eligible records; insufficient for experiment")
    return df.reset_index(drop=True), quality


def impute(train: np.ndarray, other: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[float]]:
    medians = []
    for j in range(train.shape[1]):
        finite = train[np.isfinite(train[:, j]), j]
        medians.append(float(np.median(finite)) if finite.size else 0.0)
    a, b = train.copy(), other.copy()
    for j, value in enumerate(medians):
        a[~np.isfinite(a[:, j]), j] = value
        b[~np.isfinite(b[:, j]), j] = value
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise RuntimeError("Train-fitted median imputation left nonfinite values")
    return a, b, medians


def estimator(name: str, n_train: int):
    if name == MODELS[0]:
        return IsolationForest(n_estimators=100, random_state=42, contamination=.05)
    if name == MODELS[1]:
        return LocalOutlierFactor(n_neighbors=min(20, n_train - 1), contamination=.05,
                                  novelty=True, metric="minkowski", p=2, n_jobs=-1)
    if name == MODELS[2]:
        return OneClassSVM(kernel="rbf", nu=.05, gamma="scale", cache_size=2048)
    return EllipticEnvelope(contamination=.05, random_state=42, assume_centered=False, support_fraction=None)


def oriented_score(model: Any, x: np.ndarray, name: str) -> tuple[np.ndarray, np.ndarray]:
    if name == MODELS[1]:
        return -np.asarray(model.score_samples(x), dtype=float), np.asarray(model.predict(x), dtype=int)
    return -np.asarray(model.decision_function(x), dtype=float), np.asarray(model.predict(x), dtype=int)


def jaccard(a: np.ndarray, b: np.ndarray) -> float:
    union = int(np.logical_or(a, b).sum())
    return int(np.logical_and(a, b).sum()) / union if union else 1.0


def settings(name: str, n_train: int) -> str:
    return {
        MODELS[0]: "n_estimators=100; random_state=42; contamination=0.05; raw features",
        MODELS[1]: f"n_neighbors={min(20, n_train - 1)}; contamination=0.05; novelty=True; metric=minkowski; p=2",
        MODELS[2]: "kernel=rbf; nu=0.05; gamma=scale; cache_size=2048 MiB",
        MODELS[3]: "contamination=0.05; random_state=42; assume_centered=False; support_fraction=None",
    }[name]


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def main() -> None:
    # Preserve any earlier run; use a fresh timestamped subdirectory on reruns.
    OUT = OUT_BASE
    if OUT.exists():
        stamp = time.strftime("run_%Y%m%dT%H%M%SZ", time.gmtime())
        OUT = OUT_BASE / stamp
        suffix = 1
        while OUT.exists():
            OUT = OUT_BASE / f"{stamp}_{suffix}"
            suffix += 1
    db_path = Path(HISTORICAL_DB_PATH).resolve()
    df, quality = load_data(db_path)
    n = len(df)
    raw = df[FEATURES].to_numpy(dtype=float, na_value=np.nan)
    # One deterministic permutation makes all primary training sets nested.
    permutation = np.random.RandomState(SEED).permutation(n)
    common_n = n - int(n * .90)
    common_idx = permutation[-common_n:]
    common_raw = raw[common_idx]
    common_ids = df.iloc[common_idx].reset_index(drop=True)
    fitted: dict[tuple[str, str], dict[str, Any]] = {}
    summary_rows, record_frames = [], []
    split_counts = {}

    for split_label, fraction in RATIOS:
        train_n = int(n * fraction)
        test_idx = permutation[train_n:]
        train_idx = permutation[:train_n]
        if len(train_idx) + len(test_idx) != n or len(test_idx) == 0:
            raise RuntimeError(f"Invalid split counts for {split_label}")
        split_counts[split_label] = {"train_records": len(train_idx), "held_out_records": len(test_idx),
                                     "train_fraction_requested": fraction}
        x_train, x_test, medians = impute(raw[train_idx], raw[test_idx])
        _, x_common, _ = impute(raw[train_idx], common_raw)
        test_rows = df.iloc[test_idx].reset_index(drop=True)
        print(f"Running {split_label}: train={len(train_idx):,}, held-out={len(test_idx):,}", flush=True)
        for name in MODELS:
            scaler = None
            if name == MODELS[0]:
                train_model, test_model, common_model = x_train, x_test, x_common
            else:
                scaler = StandardScaler()
                train_model = scaler.fit_transform(x_train)
                test_model = scaler.transform(x_test)
                common_model = scaler.transform(x_common)
            model = estimator(name, len(train_idx))
            caught: list[warnings.WarningMessage] = []
            started = time.perf_counter()
            with warnings.catch_warnings(record=True) as fit_warnings:
                warnings.simplefilter("always")
                model.fit(train_model)
            fit_seconds = time.perf_counter() - started
            caught.extend(fit_warnings)
            started = time.perf_counter()
            with warnings.catch_warnings(record=True) as score_warnings:
                warnings.simplefilter("always")
                scores, preds = oriented_score(model, test_model, name)
            score_seconds = time.perf_counter() - started
            caught.extend(score_warnings)
            if not np.isfinite(scores).all() or len(scores) != len(test_idx):
                raise RuntimeError(f"{name} returned nonfinite or mismatched scores for {split_label}")
            flags = preds == -1
            key = (split_label, name)
            fitted[key] = {"model": model, "scaler": scaler, "medians": medians, "x_common": common_model,
                           "fit_seconds": fit_seconds, "score_seconds": score_seconds,
                           "warning_messages": list(dict.fromkeys(str(w.message) for w in caught)),
                           "warning_count": len(caught)}
            # Time common-cohort scoring separately; never mix it into primary holdout timing.
            started = time.perf_counter()
            with warnings.catch_warnings(record=True) as common_warnings:
                warnings.simplefilter("always")
                common_scores, common_preds = oriented_score(model, common_model, name)
            common_seconds = time.perf_counter() - started
            fitted[key].update({"common_scores": common_scores, "common_flags": common_preds == -1,
                                "common_scoring_seconds": common_seconds,
                                "common_warning_messages": list(dict.fromkeys(str(w.message) for w in common_warnings))})
            q = np.percentile(scores, [1, 50, 95, 99])
            warning_text = " | ".join(fitted[key]["warning_messages"])
            numeric_note = ""
            if name == MODELS[1] and float(scores.max()) > 1e6:
                numeric_note = "Extreme LOF novelty score (>1e6); inspect repeated/near-zero-distance neighborhoods; retained without alteration."
            if name == MODELS[3] and fitted[key]["warning_count"]:
                numeric_note = "Covariance/FastMCD warnings recorded; results retained as requested and warrant stability review."
            result = {"split": split_label, "train_fraction": fraction, "training_records": len(train_idx),
                     "evaluated_records": len(test_idx), "model": name, "flagged_count": int(flags.sum()),
                     "flagged_percentage": float(flags.mean() * 100), "fit_time_seconds": fit_seconds,
                     "scoring_time_seconds": score_seconds, "score_min": float(scores.min()),
                     "score_p01": float(q[0]), "score_median": float(q[1]), "score_p95": float(q[2]),
                     "score_p99": float(q[3]), "score_max": float(scores.max()),
                     "warning_count": fitted[key]["warning_count"], "warnings": warning_text,
                     "numerical_notes": numeric_note, "settings": settings(name, len(train_idx)),
                     "preprocessing": "train-fitted median imputation; " + ("no scaling (baseline)" if scaler is None else "train-fitted StandardScaler")}
            summary_rows.append(result)
            identifiers = [c for c in IDENTIFIERS if c in test_rows.columns]
            part = test_rows[identifiers].copy()
            part.insert(0, "analysis_type", "ratio_specific_holdout")
            part.insert(1, "split", split_label)
            part["model"] = name
            part["anomaly_score_higher_is_more_anomalous"] = scores
            part["prediction"] = np.where(flags, "ANOMALY", "INLIER")
            record_frames.append(part.loc[flags].copy())
            # Common fixed evaluation cohort: same work_ids for every split/model.
            cpart = common_ids[identifiers].copy()
            cpart.insert(0, "analysis_type", "common_fixed_cohort_stability")
            cpart.insert(1, "split", split_label)
            cpart["model"] = name
            cpart["anomaly_score_higher_is_more_anomalous"] = common_scores
            cpart["prediction"] = np.where(common_preds == -1, "ANOMALY", "INLIER")
            record_frames.append(cpart.loc[common_preds == -1].copy())
            print(f"  {name}: flags={int(flags.sum()):,} ({flags.mean()*100:.2f}%), fit={fit_seconds:.3f}s, score={score_seconds:.3f}s, warnings={len(caught)}", flush=True)

    # Jaccard values only use flags for the exact same common evaluation work_ids.
    stability_rows = []
    split_pairs = [("70:30", "80:20"), ("70:30", "90:10"), ("80:20", "90:10")]
    for a, b in split_pairs:
        for name in MODELS:
            fa, fb = fitted[(a, name)]["common_flags"], fitted[(b, name)]["common_flags"]
            stability_rows.append({"split_a": a, "split_b": b, "model": name,
                                   "evaluation_cohort": "shared 90:10 held-out cohort",
                                   "evaluation_records": common_n, "model_a_flagged": int(fa.sum()),
                                   "model_b_flagged": int(fb.sum()), "intersection_flagged": int(np.logical_and(fa, fb).sum()),
                                   "union_flagged": int(np.logical_or(fa, fb).sum()), "jaccard_similarity": jaccard(fa, fb)})
    stability_df = pd.DataFrame(stability_rows)
    summary = pd.DataFrame(summary_rows)
    for row in stability_rows:
        col = f"stability_jaccard_vs_{row['split_b'].replace(':', '_')}"
        mask = (summary.split == row["split_a"]) & (summary.model == row["model"])
        summary.loc[mask, col] = row["jaccard_similarity"]
    details = summary.copy()
    flagged = pd.concat(record_frames, ignore_index=True) if record_frames else pd.DataFrame()
    if flagged.empty or not {"work_id", "model", "prediction"}.issubset(flagged.columns):
        raise RuntimeError("Flagged-project output unexpectedly contains no usable results")

    # Fail before creating outputs if any model has not completed.
    OUT.mkdir(parents=True, exist_ok=False)
    outputs = {"summary": OUT / "split_comparison_summary.csv", "details": OUT / "split_comparison_details.csv",
               "flagged_projects": OUT / "split_flagged_projects.csv", "flagging_rates": OUT / "split_flagging_rates.png",
               "training_times": OUT / "split_training_times.png", "stability": OUT / "split_stability_jaccard.png",
               "manifest": OUT / "experiment2_manifest.json"}
    summary.to_csv(outputs["summary"], index=False, encoding="utf-8")
    details.to_csv(outputs["details"], index=False, encoding="utf-8")
    flagged.sort_values(["analysis_type", "split", "model", "work_id"], kind="mergesort").to_csv(outputs["flagged_projects"], index=False, encoding="utf-8")

    colors = ["#2563eb", "#0f766e", "#9333ea", "#ea580c"]
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for color, name in zip(colors, MODELS):
        sub = summary[summary.model == name]
        ax.plot(sub.split, sub.flagged_percentage, marker="o", linewidth=2, color=color, label=name)
    ax.set(xlabel="Train:test split ratio", ylabel="Held-out records flagged (%)", title="Anomaly Flagging Rate Across Split Ratios")
    ax.grid(axis="y", alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(outputs["flagging_rates"], dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5.5))
    for color, name in zip(colors, MODELS):
        sub = summary[summary.model == name]
        ax.plot(sub.split, sub.fit_time_seconds, marker="o", linewidth=2, color=color, label=name)
    ax.set(xlabel="Train:test split ratio", ylabel="Fitting time (seconds)", title="Model Training Time Across Split Ratios")
    ax.grid(axis="y", alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(outputs["training_times"], dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    for color, name in zip(colors, MODELS):
        sub = stability_df[stability_df.model == name]
        ax.plot([f"{a} vs {b}" for a, b in zip(sub.split_a, sub.split_b)], sub.jaccard_similarity,
                marker="o", linewidth=2, color=color, label=name)
    ax.set(xlabel="Training subset comparison", ylabel="Jaccard similarity", ylim=(0, 1.02),
           title=f"Anomaly Detection Stability (shared {common_n:,}-project evaluation cohort)")
    ax.grid(axis="y", alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(outputs["stability"], dpi=160); plt.close(fig)

    manifest = {"experiment": "Experiment 2: Train-Test Split Ratio Comparison", "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "dataset_source": str(db_path), "source_table": TABLE, "feature_names": FEATURES,
                "source_rows": quality["source_rows"], "eligible_rows": n, "quality_checks": quality,
                "random_seed": SEED, "split_definitions": split_counts,
                "split_design": "One RandomState(42) permutation; each training set is the requested floor(N*fraction) prefix and its primary held-out set is the remaining suffix. Thus training subsets are nested; primary test cohorts differ in size and membership.",
                "stability_design": {"evaluation_cohort": "The exact held-out suffix for the 90:10 split", "evaluation_records": common_n,
                                     "training_sets": "Nested 70%, 80%, 90% prefixes from the same permutation, each disjoint from the common evaluation suffix.",
                                     "caveat": "For 70% and 80% stability models, intervening permutation rows are unused; primary ratio metrics remain computed on their own test cohorts. Jaccard stability values all use identical work_ids."},
                "models": {name: {"settings_by_split": {label: settings(name, split_counts[label]["train_records"]) for label, _ in RATIOS},
                                  "score_direction": "higher score means more anomalous", "scaling": "none for Isolation Forest; StandardScaler fitted on training data only for other models"} for name in MODELS},
                "preprocessing": "For each split, median imputation is fit from that split's training records only; scalers for LOF, One-Class SVM, and Elliptic Envelope are fit on training data only and applied to holdout/common cohort.",
                "warnings": [{"split": r["split"], "model": r["model"], "count": r["warning_count"], "messages": r["warnings"], "numerical_notes": r["numerical_notes"]} for r in summary_rows if r["warning_count"] or r["numerical_notes"]],
                "package_versions": {"numpy": package_version("numpy"), "pandas": package_version("pandas"), "scikit-learn": package_version("scikit-learn"), "matplotlib": package_version("matplotlib")},
                "ground_truth_labels": "Unavailable; no supervised accuracy metrics computed. Model agreement is not accuracy.",
                "outputs": {key: str(path) for key, path in outputs.items()}}
    outputs["manifest"].write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # Validate saved files and real row counts/content.
    expected_counts = {"70:30": (int(n*.70), n-int(n*.70)), "80:20": (int(n*.80), n-int(n*.80)), "90:10": (int(n*.90), n-int(n*.90))}
    for label, pair in expected_counts.items():
        actual = split_counts[label]
        if (actual["train_records"], actual["held_out_records"]) != pair or sum(pair) != n:
            raise RuntimeError(f"Count validation failed for {label}: {actual}")
    if len(summary) != 12 or len(details) != 12 or len(stability_df) != 12:
        raise RuntimeError("Unexpected comparison output row count")
    for key, path in outputs.items():
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Output missing or empty: {path}")
    if len(pd.read_csv(outputs["summary"])) != 12 or len(pd.read_csv(outputs["details"])) != 12:
        raise RuntimeError("CSV validation failed: comparison CSV row counts")
    if len(pd.read_csv(outputs["flagged_projects"])) != len(flagged):
        raise RuntimeError("CSV validation failed: flagged projects row count")
    print("\nExperiment 2 completed and outputs validated.")
    print(f"Dataset: {db_path} | eligible records: {n:,}")
    print("Split counts (train / held-out): " + "; ".join(f"{k} {v['training_records']:,}/{v['evaluated_records']:,}" for k, v in summary.groupby("split").first().iterrows()))
    for _, r in summary.iterrows():
        print(f"{r['split']} | {r['model']}: flagged {int(r['flagged_count']):,}/{int(r['evaluated_records']):,} ({r['flagged_percentage']:.2f}%), fit {r['fit_time_seconds']:.3f}s, score {r['scoring_time_seconds']:.3f}s, warnings {int(r['warning_count'])}")
    print("Stability Jaccard (same fixed held-out cohort):")
    for _, r in stability_df.iterrows():
        print(f"  {r['model']} {r['split_a']} vs {r['split_b']}: {r['jaccard_similarity']:.4f}")
    print("Outputs:")
    for path in outputs.values(): print(f"  {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
