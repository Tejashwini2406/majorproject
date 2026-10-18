"""Calibrate and evaluate the advisory BCL on manifest-verified splits."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from iot_ids.models.ensemble.bcl import BehavioralConsistencyLayer
from iot_ids.runtime.bcl_engine import BCLInferenceEngine
from iot_ids.runtime.engine import InferenceEngine
from iot_ids.runtime.schema import STANDARDIZED_21_FEATURES
from iot_ids.utils.paths import REPO_ROOT


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wilson_interval(successes: int, total: int) -> list[float]:
    if total <= 0:
        raise ValueError("Confidence intervals require at least one observation")
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return [max(0.0, center - margin), min(1.0, center + margin)]


def _read_verified_splits(
    dataset: str, data_dir: Path, model_dir: Path
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dataset_dir = data_dir / dataset
    manifest_path = dataset_dir / "split_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Missing corrected split manifest: {manifest_path}; regenerate Stage 3 first"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("sampling_method") != "uniform_reservoir":
        raise ValueError(f"Unsupported sampling protocol in {manifest_path}")
    expected_strategy = (
        "official_source_partitions"
        if dataset == "CICIoT2023"
        else "bot_iot_source_file_holdout_v1"
        if dataset == "BoT-IoT"
        else "seeded_stratified_random"
    )
    if manifest.get("split_strategy") != expected_strategy:
        raise ValueError(
            f"Expected {expected_strategy!r} for {dataset}, found "
            f"{manifest.get('split_strategy')!r}"
        )

    model_manifest_path = model_dir / "training_split_manifest.json"
    if not model_manifest_path.is_file():
        raise FileNotFoundError(
            f"Missing model training provenance: {model_manifest_path}; retrain models first"
        )
    model_manifest = json.loads(
        model_manifest_path.read_text(encoding="utf-8")
    )
    if model_manifest != manifest:
        raise ValueError(
            "Model training manifest does not match the requested Stage 3 split manifest"
        )
    training_config_path = model_dir / "training_config.json"
    if not training_config_path.is_file():
        raise FileNotFoundError(
            f"Missing model training configuration: {training_config_path}; retrain models first"
        )
    training_config = json.loads(
        training_config_path.read_text(encoding="utf-8")
    )
    if (
        training_config.get("dataset") != dataset
        or training_config.get("feature_names") != list(STANDARDIZED_21_FEATURES)
        or training_config.get("split_manifest_sha256")
        != _sha256(manifest_path)
    ):
        raise ValueError("Model training configuration does not match split provenance")
    expected_artifacts = {
        "prep_standardized.joblib",
        "rf_model.joblib",
        "mlp_adversarial.pt",
        "ae_model.pt",
    }
    artifact_hashes = training_config.get("artifact_sha256", {})
    if set(artifact_hashes) != expected_artifacts or any(
        not (model_dir / name).is_file()
        or _sha256(model_dir / name) != artifact_hashes[name]
        for name in expected_artifacts
    ):
        raise ValueError("Trained model artifacts do not match their recorded hashes")

    validation = pd.read_parquet(dataset_dir / "val.parquet")
    test = pd.read_parquet(dataset_dir / "test.parquet")
    for split_name, split in (("validation", validation), ("test", test)):
        missing = [
            name
            for name in (*STANDARDIZED_21_FEATURES, "label")
            if name not in split.columns
        ]
        if missing:
            raise ValueError(f"{dataset} {split_name} split is missing columns: {missing}")
        if set(split["label"].unique()) != {0, 1}:
            raise ValueError(
                f"{dataset} {split_name} split must contain both binary labels"
            )
        counts = manifest["label_counts"]["validation" if split_name == "validation" else "test"]
        actual_counts = {
            "benign": int((split["label"] == 0).sum()),
            "attack": int((split["label"] == 1).sum()),
        }
        if counts != actual_counts:
            raise ValueError(
                f"{dataset} {split_name} labels do not match the split manifest"
            )
    return validation, test


def _decision_metrics(
    labels: np.ndarray, results: list[dict[str, Any]]
) -> dict[str, Any]:
    alerts = np.asarray(
        [result["behavioral_consistency"]["suspicious"] for result in results],
        dtype=bool,
    )
    detector_predictions = np.asarray(
        [result["prediction"] for result in results], dtype=bool
    )
    benign = labels == 0
    attacks = labels == 1
    if not benign.any() or not attacks.any():
        raise ValueError("Evaluation split must include benign and attack examples")
    bcl_fp = int(alerts[benign].sum())
    bcl_tp = int(alerts[attacks].sum())
    detector_fp = int(detector_predictions[benign].sum())
    detector_tp = int(detector_predictions[attacks].sum())
    component_auc = {
        signal_name: float(
            roc_auc_score(
                labels,
                [
                    result["behavioral_consistency"][signal_name]
                    for result in results
                ],
            )
        )
        for signal_name in (
            "model_disagreement",
            "confidence_drift",
            "prediction_instability",
            "autoencoder_deviation",
        )
    }
    return {
        "benign_false_positive_rate": bcl_fp / int(benign.sum()),
        "benign_false_positive_rate_95ci": _wilson_interval(
            bcl_fp, int(benign.sum())
        ),
        "attack_detection_rate": bcl_tp / int(attacks.sum()),
        "attack_detection_rate_95ci": _wilson_interval(
            bcl_tp, int(attacks.sum())
        ),
        "detector_benign_false_positive_rate_at_0_5": detector_fp
        / int(benign.sum()),
        "detector_attack_detection_rate_at_0_5": detector_tp / int(attacks.sum()),
        "bcl_score_roc_auc": float(
            roc_auc_score(
                labels,
                [result["behavioral_consistency"]["score"] for result in results],
            )
        ),
        "component_roc_auc": component_auc,
        "detector_roc_auc": float(
            roc_auc_score(labels, [result["probability"] for result in results])
        ),
    }


def evaluate_bcl(
    dataset: str,
    data_dir: Path,
    models_base_dir: Path,
    target_false_positive_rate: float = 0.01,
    history_size: int = 10,
) -> dict[str, Any]:
    model_dir = models_base_dir / dataset
    validation, test = _read_verified_splits(dataset, data_dir, model_dir)
    split_manifest = json.loads(
        (data_dir / dataset / "split_manifest.json").read_text(encoding="utf-8")
    )
    if "temporal_and_behavioral_features_supported" not in split_manifest:
        raise ValueError("Split manifest is missing state-feature provenance")
    training_config = json.loads(
        (model_dir / "training_config.json").read_text(encoding="utf-8")
    )
    calibration_path = model_dir / "bcl_calibration.json"
    runtime = BCLInferenceEngine(
        InferenceEngine(
            profile="standardized_21",
            dataset=dataset,
            models_base_dir=models_base_dir,
        ),
        BehavioralConsistencyLayer(
            target_false_positive_rate=target_false_positive_rate,
            history_size=history_size,
            use_stream_history=bool(
                split_manifest["temporal_and_behavioral_features_supported"]
            ),
        ),
    )
    runtime.calibrate(
        validation[list(STANDARDIZED_21_FEATURES)],
        validation["label"].to_numpy(),
    )
    runtime.consistency_layer.save(calibration_path)

    test_inputs = test[list(STANDARDIZED_21_FEATURES)]
    labels = test["label"].to_numpy(dtype=np.int8)
    ordered_results = runtime.predict(test_inputs)
    if isinstance(ordered_results, dict):
        ordered_results = [ordered_results]
    ordered_metrics = _decision_metrics(labels, ordered_results)

    shuffle_seeds = (2027, 2041, 4093, 8191, 16381)
    shuffled_metrics = []
    for seed in shuffle_seeds:
        permutation = np.random.default_rng(seed).permutation(len(test))
        runtime.reset_state()
        shuffled_results = runtime.predict(test_inputs.iloc[permutation])
        if isinstance(shuffled_results, dict):
            shuffled_results = [shuffled_results]
        shuffled_metrics.append(
            {
                "seed": seed,
                **_decision_metrics(labels[permutation], shuffled_results),
            }
        )

    output = {
        "dataset": dataset,
        "evaluation_status": "exploratory_not_confirmatory",
        "evaluation_caveat": (
            "The two-sided BCL scoring rule was introduced after inspecting an "
            "earlier evaluation on the ToN-IoT test split. Treat all current "
            "metrics as exploratory; confirm with a fresh holdout or nested "
            "validation protocol before making paper claims."
        ),
        "training_config": training_config,
        "split_artifact_sha256": {
            filename: _sha256(data_dir / dataset / filename)
            for filename in ("split_manifest.json", "val.parquet", "test.parquet")
        },
        "split_strategy": split_manifest["split_strategy"],
        "calibration": {
            "target_false_positive_rate": target_false_positive_rate,
            "observed_validation_false_positive_rate": runtime.consistency_layer.calibration_false_positive_rate,
            "benign_validation_samples": int((validation["label"] == 0).sum()),
            "history_size": history_size,
            "use_stream_history": runtime.consistency_layer.use_stream_history,
            "artifact": str(calibration_path),
        },
        "ordered_test_stream": ordered_metrics,
        "test_input_order": (
            "source event-time order where supported; otherwise dataset row order, "
            "not asserted to be chronological"
        ),
        "confidence_interval_method": (
            "95% Wilson score intervals on row-level rates; intervals do not model "
            "within-host, campaign, or temporal dependence"
        ),
        "shuffled_test_streams": shuffled_metrics,
        "order_sensitivity": {
            name: float(
                np.mean([run[name] for run in shuffled_metrics])
                - ordered_metrics[name]
            )
            for name in (
                "benign_false_positive_rate",
                "attack_detection_rate",
                "bcl_score_roc_auc",
            )
        },
    }
    evaluation_path = model_dir / "bcl_evaluation.json"
    evaluation_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        required=True,
        choices=("Edge-IIoTset", "NF-ToN-IoT-v2", "ToN-IoT", "CICIoT2023", "BoT-IoT"),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "data" / "processed" / "stage3_corrected",
    )
    parser.add_argument(
        "--models-dir", type=Path, default=REPO_ROOT / "models" / "corrected_run"
    )
    parser.add_argument("--target-fpr", type=float, default=0.01)
    parser.add_argument("--history-size", type=int, default=10)
    args = parser.parse_args()

    result = evaluate_bcl(
        args.dataset,
        args.data_dir,
        args.models_dir,
        target_false_positive_rate=args.target_fpr,
        history_size=args.history_size,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
