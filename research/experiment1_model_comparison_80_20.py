"""Experiment 1: comparative unsupervised anomaly detection on MPLADS projects.

This script is deliberately separate from the application pipeline. It reads the
configured historical SQLite database in read-only mode and writes new artifacts
under research/experiment1_results_80_20 (or a unique run subdirectory if needed).

Method notes:
* One common seeded training/holdout split is used for all models. The training
  sample is 80% of eligible records; all remaining records form the common
  scoring/overlap cohort.
* Median imputation is fit on the training sample and shared by every model.
* Isolation Forest uses the existing raw-feature baseline configuration. The
  other three models use a StandardScaler fit on training data because their
  distance, kernel, or covariance calculations are scale-sensitive/numerically
  better conditioned when these heterogeneous units are standardized.
* Scores are oriented so that larger values mean more anomalous. See each
  model's score convention in score_definition below.
* There are no independently verified anomaly labels. No supervised metrics are
  computed and model predictions are not used as ground truth.
"""

from __future__ import annotations

import importlib.metadata
import json
import sqlite3
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from scipy.stats import spearmanr
    from sklearn.covariance import EllipticEnvelope
    from sklearn.ensemble import IsolationForest
    from sklearn.model_selection import train_test_split
    from sklearn.neighbors import LocalOutlierFactor
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import OneClassSVM
except ImportError as exc:  # report missing libraries before any output is written
    raise SystemExit(
        f"Missing experiment dependency: {exc}. Required packages: numpy, pandas, "
        "scikit-learn, scipy, matplotlib. Install them in the chosen Python "
        "environment, then rerun this script."
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    # Import only the project's path configuration; this does not initialize DBs.
    from backend.database import HISTORICAL_DB_PATH
except Exception as exc:
    raise SystemExit(f"Could not read configured historical database path: {exc}") from exc

FEATURES = [
    "sanction_amount",
    "total_disbursed",
    "budget_disbursement_ratio",
    "sanction_lead_time_days",
    "payment_tranche_count",
    "max_single_tranche_ratio",
    "work_description_length",
]
IDENTIFIERS = ["work_id", "state", "district"]
SOURCE_TABLE = "project_monitoring_features"
TRAIN_FRACTION = 0.80
SPLIT_SEED = 42
CONTAMINATION = 0.05
TOP_N_PER_MODEL = 100
MODEL_NAMES = ["Isolation Forest", "Local Outlier Factor", "One-Class SVM", "Elliptic Envelope"]


def package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def load_data(db_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not db_path.is_file():
        raise RuntimeError(f"Configured historical database does not exist: {db_path}")
    columns = ["work_id", *FEATURES]
    # State/district are optional display context; only required columns drive ML.
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as conn:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (SOURCE_TABLE,)
        ).fetchone()
        if not table_exists:
            raise RuntimeError(f"Required feature table {SOURCE_TABLE!r} is absent from {db_path}")
        actual_columns = {row[1] for row in conn.execute(f"PRAGMA table_info({SOURCE_TABLE})")}
        missing_columns = [name for name in columns if name not in actual_columns]
        if missing_columns:
            raise RuntimeError(f"Missing required columns in {SOURCE_TABLE}: {missing_columns}")
        selected = [name for name in IDENTIFIERS if name in actual_columns] + FEATURES
        quoted = ", ".join('"' + name.replace('"', '""') + '"' for name in selected)
        data = pd.read_sql_query(f"SELECT {quoted} FROM {SOURCE_TABLE}", conn)

    source_rows = len(data)
    blank_id = data["work_id"].isna() | data["work_id"].astype(str).str.strip().eq("")
    excluded_missing_id = int(blank_id.sum())
    data = data.loc[~blank_id].copy()
    data["work_id"] = data["work_id"].astype(str).str.strip()
    duplicate_ids = int(data["work_id"].duplicated(keep=False).sum())
    if duplicate_ids:
        duplicated = data.loc[data["work_id"].duplicated(keep=False), "work_id"].head(10).tolist()
        raise RuntimeError(
            f"Found {duplicate_ids} rows with duplicate work_id values; refusing ambiguous "
            f"project-level evaluation. Examples: {duplicated}"
        )

    missing_by_feature: dict[str, int] = {}
    nonfinite_by_feature: dict[str, int] = {}
    for feature in FEATURES:
        numeric = pd.to_numeric(data[feature], errors="coerce")
        values = numeric.to_numpy(dtype=float, na_value=np.nan)
        finite = np.isfinite(values)
        missing_by_feature[feature] = int(np.isnan(values).sum())
        nonfinite_by_feature[feature] = int((~finite & ~np.isnan(values)).sum())
        # Infinities and malformed numeric strings become missing and are imputed.
        data[feature] = numeric.where(np.isfinite(values), np.nan)

    quality = {
        "source_table": SOURCE_TABLE,
        "source_rows": source_rows,
        "rows_excluded_missing_work_id": excluded_missing_id,
        "duplicate_work_id_rows": duplicate_ids,
        "missing_values_by_feature_before_imputation": missing_by_feature,
        "nonfinite_values_by_feature_before_imputation": nonfinite_by_feature,
        "eligible_rows": len(data),
        "excluded_rows_total": excluded_missing_id,
    }
    if len(data) < 100:
        raise RuntimeError(f"Too few eligible records for the specified experiment: {len(data)}")
    return data.reset_index(drop=True), quality


def impute_from_train(
    train: np.ndarray, test: np.ndarray
) -> tuple[np.ndarray, np.ndarray, list[float]]:
    medians: list[float] = []
    for column in range(train.shape[1]):
        finite_train = train[np.isfinite(train[:, column]), column]
        median = float(np.median(finite_train)) if finite_train.size else 0.0
        medians.append(median)
    train_out = train.copy()
    test_out = test.copy()
    for column, median in enumerate(medians):
        train_out[~np.isfinite(train_out[:, column]), column] = median
        test_out[~np.isfinite(test_out[:, column]), column] = median
    return train_out, test_out, medians


def score_distribution(scores: np.ndarray) -> dict[str, float]:
    qs = np.percentile(scores, [1, 5, 25, 50, 75, 95, 99])
    return {
        "score_min": float(np.min(scores)),
        "score_p01": float(qs[0]),
        "score_p05": float(qs[1]),
        "score_p25": float(qs[2]),
        "score_median": float(qs[3]),
        "score_p75": float(qs[4]),
        "score_p95": float(qs[5]),
        "score_p99": float(qs[6]),
        "score_max": float(np.max(scores)),
        "score_mean": float(np.mean(scores)),
        "score_std": float(np.std(scores)),
    }


def choose_output_dir(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    expected = [
        "model_comparison_summary.csv",
        "per_record_anomaly_scores.csv",
        "pairwise_model_overlap.csv",
        "flagged_projects_for_manual_review.csv",
        "flagged_counts_and_percentages.png",
        "model_agreement_jaccard.png",
        "experiment_manifest.json",
        "lof_neighbor_diagnostics.csv",
        "elliptic_support_fraction_sensitivity.csv",
    ]
    if not any((base / name).exists() for name in expected):
        return base
    stamp = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    candidate = base / stamp
    suffix = 1
    while candidate.exists():
        candidate = base / f"{stamp}_{suffix}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def save_no_overwrite(frame: pd.DataFrame, path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {path}")
    frame.to_csv(path, index=False, encoding="utf-8")


def main() -> None:
    db_path = Path(HISTORICAL_DB_PATH).resolve()
    data, quality = load_data(db_path)
    indices = np.arange(len(data))
    train_idx, test_idx = train_test_split(
        indices, train_size=TRAIN_FRACTION, random_state=SPLIT_SEED, shuffle=True
    )
    expected_train = int(len(data) * TRAIN_FRACTION)
    expected_test = len(data) - expected_train
    if len(train_idx) != expected_train or len(test_idx) != expected_test:
        raise RuntimeError(
            f"Unexpected 80:20 split counts: train={len(train_idx)}, test={len(test_idx)}, "
            f"expected train={expected_train}, test={expected_test}"
        )
    if len(train_idx) + len(test_idx) != quality["eligible_rows"]:
        raise RuntimeError("Train and held-out counts do not sum to the eligible project count")
    raw = data[FEATURES].to_numpy(dtype=float, na_value=np.nan)
    x_train, x_test, imputation_medians = impute_from_train(raw[train_idx], raw[test_idx])
    if not np.isfinite(x_train).all() or not np.isfinite(x_test).all():
        raise RuntimeError("Imputation did not produce finite model input values")

    fitted: dict[str, dict[str, Any]] = {}

    # Existing baseline: preserve estimator settings and do not scale its features.
    print("Fitting Isolation Forest...", flush=True)
    model = IsolationForest(n_estimators=100, random_state=42, contamination=CONTAMINATION)
    t0 = time.perf_counter()
    model.fit(x_train)
    fit_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    normality = model.decision_function(x_test)
    predictions = model.predict(x_test)
    score_s = time.perf_counter() - t0
    fitted[MODEL_NAMES[0]] = {
        "scores": -normality,
        "predictions": predictions,
        "fit_time_seconds": fit_s,
        "scoring_time_seconds": score_s,
        "settings": "n_estimators=100; contamination=0.05; random_state=42; raw features",
        "score_definition": "-decision_function(X); sklearn decision_function is larger for inliers, negated so higher means more anomalous",
        "scaling": "None (preserves existing backend Isolation Forest baseline)",
    }

    # LOF novelty mode is required to score the shared held-out cohort. sklearn
    # documents that novelty methods should only score unseen data this way.
    print("Fitting Local Outlier Factor...", flush=True)
    lof_scaler = StandardScaler()
    t0 = time.perf_counter()
    x_train_lof = lof_scaler.fit_transform(x_train)
    lof = LocalOutlierFactor(
        n_neighbors=min(20, len(x_train) - 1),
        contamination=CONTAMINATION,
        novelty=True,
        metric="minkowski",
        p=2,
        n_jobs=-1,
    )
    lof.fit(x_train_lof)
    fit_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    x_test_lof = lof_scaler.transform(x_test)
    # score_samples is opposite LOF: lower scores are more anomalous.
    lof_inlier_score = lof.score_samples(x_test_lof)
    predictions = lof.predict(x_test_lof)
    score_s = time.perf_counter() - t0
    fitted[MODEL_NAMES[1]] = {
        "scores": -lof_inlier_score,
        "predictions": predictions,
        "fit_time_seconds": fit_s,
        "scoring_time_seconds": score_s,
        "settings": f"n_neighbors={lof.n_neighbors}; contamination=0.05; novelty=True; metric=minkowski; p=2",
        "score_definition": "-score_samples(X); sklearn documents lower score_samples as more abnormal, negated so higher means more anomalous",
        "scaling": "StandardScaler fit on common training split; applied to train and held-out records",
    }

    print("Fitting One-Class SVM (RBF)...", flush=True)
    svm_scaler = StandardScaler()
    t0 = time.perf_counter()
    x_train_svm = svm_scaler.fit_transform(x_train)
    one_class_svm = OneClassSVM(kernel="rbf", nu=CONTAMINATION, gamma="scale", cache_size=2048)
    one_class_svm.fit(x_train_svm)
    fit_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    x_test_svm = svm_scaler.transform(x_test)
    svm_normality = one_class_svm.decision_function(x_test_svm)
    predictions = one_class_svm.predict(x_test_svm)
    score_s = time.perf_counter() - t0
    fitted[MODEL_NAMES[2]] = {
        "scores": -svm_normality,
        "predictions": predictions,
        "fit_time_seconds": fit_s,
        "scoring_time_seconds": score_s,
        "settings": "kernel=rbf; nu=0.05; gamma=scale; cache_size=2048 MiB",
        "score_definition": "-decision_function(X); positive decision values indicate inliers, negated so higher means more anomalous",
        "scaling": "StandardScaler fit on common training split; applied to train and held-out records",
    }

    print("Fitting primary Elliptic Envelope...", flush=True)
    ee_scaler = StandardScaler()
    t0 = time.perf_counter()
    x_train_ee = ee_scaler.fit_transform(x_train)
    elliptic = EllipticEnvelope(
        contamination=CONTAMINATION,
        random_state=42,
        assume_centered=False,
        support_fraction=None,
    )
    with warnings.catch_warnings(record=True) as caught_ee_warnings:
        warnings.simplefilter("always")
        elliptic.fit(x_train_ee)
    elliptic_warning_messages = [str(item.message) for item in caught_ee_warnings]
    fit_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    x_test_ee = ee_scaler.transform(x_test)
    ee_normality = elliptic.decision_function(x_test_ee)
    predictions = elliptic.predict(x_test_ee)
    score_s = time.perf_counter() - t0
    fitted[MODEL_NAMES[3]] = {
        "scores": -ee_normality,
        "predictions": predictions,
        "fit_time_seconds": fit_s,
        "scoring_time_seconds": score_s,
        "settings": "contamination=0.05; random_state=42; assume_centered=False; support_fraction=None",
        "score_definition": "-decision_function(X); sklearn decision values are positive for inliers, negated so higher means more anomalous",
        "scaling": "StandardScaler fit on common training split; applied to train and held-out records",
        "warnings": elliptic_warning_messages,
    }

    test_rows = data.iloc[test_idx].reset_index(drop=True)
    summary_rows: list[dict[str, Any]] = []
    per_record = test_rows[[c for c in IDENTIFIERS if c in test_rows.columns] + FEATURES].copy()
    per_record.insert(0, "split", "held_out")
    model_arrays: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    # LOF novelty diagnostics for the highest-scoring held-out projects. These
    # local reachability values explain the LOF score rather than altering it.
    lof_scores = np.asarray(fitted[MODEL_NAMES[1]]["scores"], dtype=float)
    diagnostic_indices = np.argsort(lof_scores, kind="mergesort")[-min(TOP_N_PER_MODEL, len(lof_scores)):][::-1]
    distances, neighbor_indices = lof.kneighbors(x_test_lof[diagnostic_indices], n_neighbors=lof.n_neighbors)
    train_k_distances = getattr(lof, "_distances_fit_X_", None)
    train_lrd = getattr(lof, "_lrd", None)
    if train_k_distances is None or train_lrd is None:
        raise RuntimeError("Installed scikit-learn LOF internals unavailable for required neighbor diagnostics")
    neighbor_k_distances = train_k_distances[neighbor_indices, -1]
    reachability_distances = np.maximum(distances, neighbor_k_distances)
    query_lrd = 1.0 / (np.mean(reachability_distances, axis=1) + 1e-10)
    neighbor_lrd = train_lrd[neighbor_indices]
    recomputed_lof = np.mean(neighbor_lrd / query_lrd[:, np.newaxis], axis=1)
    lof_diagnostics = test_rows.iloc[diagnostic_indices][
        [c for c in IDENTIFIERS if c in test_rows.columns]
    ].reset_index(drop=True)
    lof_diagnostics.insert(0, "rank_by_lof_anomaly_score", np.arange(1, len(diagnostic_indices) + 1))
    lof_diagnostics["reported_lof_anomaly_score"] = lof_scores[diagnostic_indices]
    lof_diagnostics["nearest_neighbor_distance_min"] = distances.min(axis=1)
    lof_diagnostics["nearest_neighbor_distance_median"] = np.median(distances, axis=1)
    lof_diagnostics["nearest_neighbor_distance_max"] = distances.max(axis=1)
    lof_diagnostics["neighbor_k_distance_median"] = np.median(neighbor_k_distances, axis=1)
    lof_diagnostics["reachability_distance_mean"] = reachability_distances.mean(axis=1)
    lof_diagnostics["query_local_reachability_density"] = query_lrd
    lof_diagnostics["neighbor_lrd_min"] = neighbor_lrd.min(axis=1)
    lof_diagnostics["neighbor_lrd_median"] = np.median(neighbor_lrd, axis=1)
    lof_diagnostics["neighbor_lrd_mean"] = neighbor_lrd.mean(axis=1)
    lof_diagnostics["neighbor_lrd_max"] = neighbor_lrd.max(axis=1)
    lof_diagnostics["recomputed_lof_ratio"] = recomputed_lof
    lof_diagnostics["absolute_score_formula_difference"] = np.abs(recomputed_lof - lof_scores[diagnostic_indices])

    for name in MODEL_NAMES:
        result = fitted[name]
        scores = np.asarray(result["scores"], dtype=float)
        predictions = np.asarray(result["predictions"], dtype=int)
        if len(scores) != len(test_rows) or len(predictions) != len(test_rows):
            raise RuntimeError(f"{name} returned a different number of scores/predictions")
        if not np.isfinite(scores).all():
            raise RuntimeError(f"{name} returned non-finite anomaly scores")
        flagged = predictions == -1
        model_arrays[name] = (scores, flagged)
        distribution = score_distribution(scores)
        summary_rows.append({
            "model": name,
            "training_records": len(train_idx),
            "evaluated_records": len(test_idx),
            "flagged_count": int(flagged.sum()),
            "flagged_percentage": float(flagged.mean() * 100.0),
            "fit_time_seconds": float(result["fit_time_seconds"]),
            "scoring_time_seconds": float(result["scoring_time_seconds"]),
            **distribution,
            "settings": result["settings"],
            "scaling": result["scaling"],
            "score_definition": result["score_definition"],
        })
        safe_name = name.lower().replace(" ", "_").replace("-", "_")
        per_record[f"{safe_name}_anomaly_score"] = scores
        per_record[f"{safe_name}_prediction"] = np.where(flagged, "ANOMALY", "INLIER")

    pair_rows: list[dict[str, Any]] = []
    for i, model_a in enumerate(MODEL_NAMES):
        scores_a, flags_a = model_arrays[model_a]
        for model_b in MODEL_NAMES[i + 1 :]:
            scores_b, flags_b = model_arrays[model_b]
            intersection = int(np.logical_and(flags_a, flags_b).sum())
            union = int(np.logical_or(flags_a, flags_b).sum())
            corr = spearmanr(scores_a, scores_b)
            pair_rows.append({
                "model_a": model_a,
                "model_b": model_b,
                "evaluated_records": len(test_idx),
                "model_a_flagged": int(flags_a.sum()),
                "model_b_flagged": int(flags_b.sum()),
                "intersection_flagged_count": intersection,
                "union_flagged_count": union,
                "overlap_percent_of_evaluated": intersection / len(test_idx) * 100.0,
                "model_a_flags_also_flagged_by_b_percent": intersection / flags_a.sum() * 100.0 if flags_a.sum() else 0.0,
                "model_b_flags_also_flagged_by_a_percent": intersection / flags_b.sum() * 100.0 if flags_b.sum() else 0.0,
                "jaccard_similarity": intersection / union if union else 1.0,
                "spearman_rank_rho": float(corr.statistic),
                "spearman_pvalue_descriptive_only": float(corr.pvalue),
            })

    rank_rows: list[pd.DataFrame] = []
    for name in MODEL_NAMES:
        scores, flags = model_arrays[name]
        candidates = test_rows.loc[flags, [c for c in IDENTIFIERS if c in test_rows.columns]].copy()
        candidates["model"] = name
        candidates["anomaly_score_higher_is_more_anomalous"] = scores[flags]
        candidates = candidates.sort_values(
            "anomaly_score_higher_is_more_anomalous", ascending=False, kind="mergesort"
        ).head(TOP_N_PER_MODEL)
        candidates.insert(0, "rank_within_model", np.arange(1, len(candidates) + 1))
        rank_rows.append(candidates)
    review = pd.concat(rank_rows, ignore_index=True) if rank_rows else pd.DataFrame()

    # Alternative supports are an isolated Elliptic Envelope sensitivity check.
    # They do not alter the primary model arrays, summary, overlap, or charts.
    sensitivity_rows: list[dict[str, Any]] = []
    primary_ee_scores, primary_ee_flags = model_arrays[MODEL_NAMES[3]]
    for support_fraction in (0.75, 0.90):
        print(f"Elliptic Envelope sensitivity support_fraction={support_fraction:.2f}...", flush=True)
        sensitivity_model = EllipticEnvelope(
            contamination=CONTAMINATION,
            random_state=42,
            assume_centered=False,
            support_fraction=support_fraction,
        )
        with warnings.catch_warnings(record=True) as caught_sensitivity_warnings:
            warnings.simplefilter("always")
            started = time.perf_counter()
            sensitivity_model.fit(x_train_ee)
            sensitivity_fit_s = time.perf_counter() - started
        started = time.perf_counter()
        sensitivity_normality = sensitivity_model.decision_function(x_test_ee)
        sensitivity_predictions = sensitivity_model.predict(x_test_ee)
        sensitivity_score_s = time.perf_counter() - started
        sensitivity_scores = -sensitivity_normality
        sensitivity_flags = sensitivity_predictions == -1
        intersection = int(np.logical_and(primary_ee_flags, sensitivity_flags).sum())
        union = int(np.logical_or(primary_ee_flags, sensitivity_flags).sum())
        sensitivity_corr = spearmanr(primary_ee_scores, sensitivity_scores)
        sensitivity_rows.append({
            "analysis": "sensitivity_only_not_primary_comparison",
            "support_fraction": support_fraction,
            "contamination": CONTAMINATION,
            "random_state": 42,
            "training_records": len(train_idx),
            "evaluated_records": len(test_idx),
            "flagged_count": int(sensitivity_flags.sum()),
            "flagged_percentage": float(sensitivity_flags.mean() * 100.0),
            "fit_time_seconds": sensitivity_fit_s,
            "scoring_time_seconds": sensitivity_score_s,
            "jaccard_vs_primary_support_fraction_none": intersection / union if union else 1.0,
            "spearman_rho_vs_primary_support_fraction_none": float(sensitivity_corr.statistic),
            "score_min": float(sensitivity_scores.min()),
            "score_median": float(np.median(sensitivity_scores)),
            "score_p95": float(np.percentile(sensitivity_scores, 95)),
            "score_p99": float(np.percentile(sensitivity_scores, 99)),
            "score_max": float(sensitivity_scores.max()),
            "warning_count": len(caught_sensitivity_warnings),
            "warnings": " | ".join(str(item.message) for item in caught_sensitivity_warnings),
        })

    output_dir = choose_output_dir(ROOT / "research" / "experiment1_results_80_20")
    outputs = {
        "summary": output_dir / "model_comparison_summary.csv",
        "records": output_dir / "per_record_anomaly_scores.csv",
        "overlap": output_dir / "pairwise_model_overlap.csv",
        "review": output_dir / "flagged_projects_for_manual_review.csv",
        "counts_chart": output_dir / "flagged_counts_and_percentages.png",
        "agreement_chart": output_dir / "model_agreement_jaccard.png",
        "lof_diagnostics": output_dir / "lof_neighbor_diagnostics.csv",
        "elliptic_sensitivity": output_dir / "elliptic_support_fraction_sensitivity.csv",
        "manifest": output_dir / "experiment_manifest.json",
    }
    for path in outputs.values():
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing output: {path}")

    summary = pd.DataFrame(summary_rows)
    save_no_overwrite(summary, outputs["summary"])
    save_no_overwrite(per_record.sort_values("work_id", kind="mergesort"), outputs["records"])
    save_no_overwrite(pd.DataFrame(pair_rows), outputs["overlap"])
    save_no_overwrite(review, outputs["review"])
    save_no_overwrite(lof_diagnostics, outputs["lof_diagnostics"])
    save_no_overwrite(pd.DataFrame(sensitivity_rows), outputs["elliptic_sensitivity"])

    fig, ax_count = plt.subplots(figsize=(10, 5.5))
    x = np.arange(len(summary))
    bars = ax_count.bar(x, summary["flagged_count"], color=["#2563eb", "#0f766e", "#9333ea", "#ea580c"])
    ax_count.set_ylabel("Flagged projects in held-out cohort")
    ax_count.set_xticks(x, summary["model"], rotation=12, ha="right")
    ax_count.set_title("Unsupervised model flags (shared held-out MPLADS projects)")
    ax_pct = ax_count.twinx()
    ax_pct.plot(x, summary["flagged_percentage"], color="#111827", marker="o", linewidth=2)
    ax_pct.set_ylabel("Flagged (%)")
    ax_pct.set_ylim(bottom=0)
    for bar, pct in zip(bars, summary["flagged_percentage"]):
        ax_count.annotate(f"{int(bar.get_height()):,}", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                          xytext=(0, 4), textcoords="offset points", ha="center", fontsize=9)
        ax_pct.annotate(f"{pct:.2f}%", (bar.get_x() + bar.get_width() / 2, pct),
                        xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(outputs["counts_chart"], dpi=160, bbox_inches="tight")
    plt.close(fig)

    model_count = len(MODEL_NAMES)
    jaccard = np.eye(model_count)
    for row in pair_rows:
        ia = MODEL_NAMES.index(row["model_a"])
        ib = MODEL_NAMES.index(row["model_b"])
        jaccard[ia, ib] = jaccard[ib, ia] = row["jaccard_similarity"]
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    image = ax.imshow(jaccard, vmin=0, vmax=1, cmap="YlGnBu")
    ax.set_xticks(range(model_count), MODEL_NAMES, rotation=30, ha="right")
    ax.set_yticks(range(model_count), MODEL_NAMES)
    ax.set_title("Pairwise Jaccard agreement of flagged projects")
    for i in range(model_count):
        for j in range(model_count):
            ax.text(j, i, f"{jaccard[i, j]:.3f}", ha="center", va="center", color="black")
    fig.colorbar(image, ax=ax, label="Jaccard similarity")
    fig.tight_layout()
    fig.savefig(outputs["agreement_chart"], dpi=160, bbox_inches="tight")
    plt.close(fig)

    manifest = {
        "experiment": "Experiment 1: Comparative Evaluation of Unsupervised Anomaly-Detection Models",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "database_path": str(db_path),
        "source_table": SOURCE_TABLE,
        "features": FEATURES,
        "data_quality": quality,
        "split": {
            "method": "random shuffled train/held-out split",
            "training_fraction": TRAIN_FRACTION,
            "training_records": len(train_idx),
            "held_out_fraction": 1.0 - TRAIN_FRACTION,
            "held_out_records": len(test_idx),
            "random_state": SPLIT_SEED,
            "expected_counts_check": {
                "expected_training_records": expected_train,
                "expected_held_out_records": expected_test,
                "counts_sum_to_eligible": len(train_idx) + len(test_idx) == quality["eligible_rows"],
            },
            "imputation": "per-feature median fit using training rows; reused for all models; all-empty training feature falls back to 0.0",
            "imputation_medians": dict(zip(FEATURES, imputation_medians)),
        },
        "models": {name: {"settings": fitted[name]["settings"], "scaling": fitted[name]["scaling"],
                           "score_definition": fitted[name]["score_definition"]} for name in MODEL_NAMES},
        "primary_elliptic_envelope_warnings": elliptic_warning_messages,
        "implementation_changes_vs_25_75_script": [
            "TRAIN_FRACTION changed from 0.25 to 0.80; random seed, features, imputation, scaling, primary model parameters, and score conventions retained.",
            "Outputs isolated to research/experiment1_results_80_20 with no-overwrite behavior.",
            "Added nearest-neighbor distance and local reachability-density diagnostics for the top 100 LOF-scoring held-out projects.",
            "Added separate Elliptic Envelope support_fraction=0.75 and 0.90 sensitivity fits; these do not replace primary support_fraction=None results.",
        ],
        "elliptic_sensitivity_settings": "support_fraction=0.75 and 0.90; contamination=0.05; random_state=42; same split and standardized features; sensitivity only.",
        "preprocessing_rationale": "Isolation Forest baseline retains raw features; LOF and RBF One-Class SVM depend on distances/kernels, while Elliptic Envelope uses covariance geometry and scaling improves numerical conditioning across dollar, day, ratio, count, and text-length units.",
        "limitations": [
            "The project has no independently verified anomaly labels; no accuracy, precision, recall, F1, confusion matrix, or ROC-AUC is reported.",
            "Anomaly flags are statistical screening outputs, not evidence of fraud, corruption, or wrongdoing.",
            "Contamination and nu are model threshold/settings, not accuracy measures; holdout flagged percentages can differ from them.",
            "LOF uses novelty=True and scores only the held-out cohort; sklearn notes novelty-mode scores can differ from standard in-sample outlier-detection scores.",
            "Isolation Forest keeps its existing estimator settings but is fit only on the common training split for this comparative experiment, not on the full dataset as in the application pipeline.",
        ],
        "software_versions": {
            "python": sys.version.split()[0],
            "numpy": package_version("numpy"),
            "pandas": package_version("pandas"),
            "scikit_learn": package_version("scikit-learn"),
            "scipy": package_version("scipy"),
            "matplotlib": package_version("matplotlib"),
        },
        "output_files": {key: path.name for key, path in outputs.items()},
    }
    if outputs["manifest"].exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {outputs['manifest']}")
    outputs["manifest"].write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # Basic post-write validation before printing results.
    for key, path in outputs.items():
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Output validation failed: missing or empty {key} file {path}")
    if len(pd.read_csv(outputs["summary"])) != len(MODEL_NAMES):
        raise RuntimeError("Output validation failed: summary must contain one row per model")
    if len(pd.read_csv(outputs["records"])) != len(test_idx):
        raise RuntimeError("Output validation failed: per-record output count differs from holdout")
    if len(pd.read_csv(outputs["overlap"])) != 6:
        raise RuntimeError("Output validation failed: pairwise output must contain six model pairs")
    if len(pd.read_csv(outputs["lof_diagnostics"])) != min(TOP_N_PER_MODEL, len(test_idx)):
        raise RuntimeError("Output validation failed: LOF diagnostic row count is incorrect")
    if len(pd.read_csv(outputs["elliptic_sensitivity"])) != 2:
        raise RuntimeError("Output validation failed: expected two Elliptic Envelope sensitivity rows")

    print("EXPERIMENT 1 COMPLETED")
    print(f"Database: {db_path}")
    print(f"Source records: {quality['source_rows']:,}; eligible: {quality['eligible_rows']:,}; excluded: {quality['excluded_rows_total']:,}; duplicate work IDs: {quality['duplicate_work_id_rows']:,}")
    print(f"Train records: {len(train_idx):,}; held-out evaluated records: {len(test_idx):,}; features: {len(FEATURES)}")
    print(f"Split verified: {len(train_idx) + len(test_idx):,} total; expected {expected_train:,} train + {expected_test:,} held out.")
    print("No ground-truth labels available; supervised metrics were not calculated.")
    for row in summary_rows:
        print(f"{row['model']}: flagged {row['flagged_count']:,}/{row['evaluated_records']:,} ({row['flagged_percentage']:.2f}%); fit {row['fit_time_seconds']:.3f}s; score {row['scoring_time_seconds']:.3f}s")
    print(f"Primary Elliptic Envelope warnings: {len(elliptic_warning_messages)}")
    for item in elliptic_warning_messages:
        print(f"  WARNING: {item}")
    print(f"Top LOF anomaly score: {float(lof_scores[diagnostic_indices[0]]):.6g}; diagnostics saved for {len(lof_diagnostics)} records.")
    print("Pairwise Jaccard / Spearman rank correlation:")
    for row in pair_rows:
        print(f"  {row['model_a']} / {row['model_b']}: Jaccard={row['jaccard_similarity']:.4f}; Spearman rho={row['spearman_rank_rho']:.4f}")
    print(f"Outputs: {output_dir}")
    for key, path in outputs.items():
        print(f"  {key}: {path}")


if __name__ == "__main__":
    main()
