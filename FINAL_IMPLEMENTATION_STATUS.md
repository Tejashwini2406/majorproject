# Implementation and Paper-Readiness Status

**Status: implementation and research evaluation are still in progress. Do not submit the current manuscript or cite its historical metrics.**

## Conference target

**Target: USENIX Security '27, Cycle 2 (aspirational; not submission-ready).** The official CFP sets mandatory registration for January 19, 2027, paper submission for January 26, 2027, and artifact submission for January 29, 2027. Submissions are limited to 13 body pages and must include an Open Science Appendix; an Ethics appendix is strongly encouraged. The current BCL evidence does not yet meet the venue's standards for novelty, independent validation, or adaptive-attacker evaluation. See the [official CFP](https://www.usenix.org/conference/usenixsecurity27/call-for-papers).

## Work completed

- Added a Behavioral Consistency Layer (BCL) that calibrates on an ordered validation stream and reports disagreement, confidence drift, prediction instability, and reconstruction-error signals. It is advisory; it does not alter the detector's ATTACK/BENIGN decision.
- BCL calibration now scores deviation on either side of the benign validation median. Calibration artifacts use version 3 while the loader remains compatible with versions 1 and 2.
- Added a runtime wrapper that connects BCL to the existing 21-feature inference engine and autoencoder artifact.
- Added a manifest- and artifact-hash-gated BCL evaluation runner that calibrates on validation only, reports component/overall ROC-AUC, Wilson confidence intervals and detector baselines at a fixed threshold, and checks five deterministic shuffled input orders.
- Added a lightweight BCL baseline trainer for the standardized RF/MLP detector and benign-only autoencoder; it writes fresh artifacts separately from historical model directories and verifies they load through the production inference engine.
- Added a dataset-filtered Stage 3 materialization option so a dataset with too few benign validation examples can be resampled at a larger size without rerunning or overwriting aggregate audits.
- Updated the golden training pipeline to require the corrected split manifest, verify label counts against it, preserve training provenance with model artifacts, and train the BCL autoencoder on benign training flows.
- Directed corrected datasets, models, and reports to separate `*_corrected` / `corrected_run` output paths so historical artifacts are not overwritten.
- Replaced the Stage 3 first-record class quotas with bounded reservoir sampling and seeded stratified 60/20/20 splits for datasets without official partition files.
- CICIoT2023 materialization now keeps its official train, validation, and test source partitions separate and records split provenance in `split_manifest.json`.
- Stage 3 disables temporal and behavioral features for datasets whose adapters synthesize timestamps or host identities. Only Edge-IIoTset currently enables those state-derived features.
- Added a streaming BoT-IoT CSV adapter and registered a pre-specified, source-file-disjoint split for the four official 5% full-feature CSVs: files 1-2 train, file 3 validation/calibration, file 4 test. Materialization checks the exact source file set, records SHA-256 provenance, samples within each split, and fails on missing class coverage. The official UNSW page confirms a four-file 5% CSV subset (about 1.07 GB), but the SharePoint file-download endpoint requires authentication and returned HTTP 403 from this environment. No access control was bypassed; the dataset is not included in corrected BCL training or results.
- Added focused tests for split isolation, deterministic sampling, adapter partition selection, unsupported synthetic-history feature suppression, and BCL behavior.

## Validation completed

- Corrected Stage 3 materialization completed for all four local raw datasets. CICIoT2023 was enlarged to 50,000 flows (30k/10k/10k from official train/validation/test partitions); the other three use 10,000-flow seeded stratified row-random splits.
- Corrected RF/MLP/autoencoder artifacts trained successfully and the BCL evaluator completed for all four datasets.
- Current verification (October 18, 2026): focused BCL and corrected-split tests **21 passed**; BoT-IoT adapter, materialization, and data-layer tests **21 passed**; full regression suite **161 passed, 8 skipped** in 34.27 seconds. The full run reported 148 warnings, chiefly sklearn artifact-version mismatches, a deprecated feature-builder import, and SHAP pending deprecations. Ruff passed on the BoT-IoT adapter, source-disjoint materializer, trainer/evaluator wiring, and tests; Pylance reported no diagnostics in the changed BoT-IoT materializer/trainer/evaluator.
- Preliminary 10,000-row sample results (all explicitly exploratory, not confirmatory):

  | Dataset | Test rows | BCL test FPR | BCL attack detection | BCL ROC-AUC | Detector ROC-AUC |
  |---|---:|---:|---:|---:|---:|
  | ToN-IoT | 2,002 | 0.41% | 97.55% | 0.991 | 0.999 |
  | Edge-IIoTset | 2,000 | 8.05% | 43.54% | 0.799 | 0.997 |
  | NF-ToN-IoT-v2 | 2,002 | 0.91% | 0.90% | 0.746 | 0.989 |
  | CICIoT2023 | 10,000 | 1.28% | 44.99% | 0.953 | 0.994 |

- ToN-IoT's original one-sided score had ROC-AUC 0.016; the current two-sided score was designed after inspecting that same test split. **ToN-IoT is no longer confirmatory evidence.** Edge-IIoTset also has substantial stream-order sensitivity (21.2 percentage-point attack-detection change across the five shuffle runs). All evaluator outputs are marked `exploratory_not_confirmatory`.
- Increasing CICIoT2023 to 50,000 rows yielded 204 benign validation rows, enabling the 1%-FPR calibration; its test attack detection is 44.99%, below the detector's 99.67% at threshold 0.5.

## Research blockers

- BoT-IoT is the selected independent dataset, but its raw 5% subset could not be downloaded because the official SharePoint file endpoint requires authentication (HTTP 403). The user must provide the files or download them through an authenticated official session. The source-file split is frozen in the materializer, but the resulting source chronology, label coverage, feature semantics, calibration sufficiency, and test metrics remain unverified; no BoT-IoT result is claimed.
- The BCL results do not establish reliable cross-dataset utility: attack detection at the selected operating point is low on NF-ToN-IoT-v2, and test false positives plus stream-order sensitivity are high on Edge-IIoTset.
- All existing accuracy, adversarial, privacy-utility, XAI, and throughput numbers remain historical and must not be represented as evidence for the BCL paper.
- The ToN-IoT sample shows promising exploratory BCL separation, but this is not a confirmation; other dataset results do not show consistent BCL utility. The current runs use bounded samples rather than the full source data. Adaptive evasion remains unevaluated.
- For ToN-IoT and NF-ToN-IoT-v2, the implemented row-level random split is not a host-, campaign-, or time-disjoint generalization test. Claims must be limited accordingly unless stronger provenance is introduced.
- The existing paper and Overleaf ZIP still contain the old multi-claim IEEE manuscript and historical results. The manuscript needs to be rewritten around the approved BCL security contribution after new experiments exist.

## Required next steps

1. Obtain the official BoT-IoT 5% subset through the user's authorized access and place the four full-feature CSV files under `data/raw/BoT-IoT/`; run the frozen materialization and reject the protocol if either class is missing from any split.
2. Verify split provenance, source-file chronology and labels, at least 100 benign validation samples for the 1% calibration target, and feature semantics before opening the file-4 test results.
3. Investigate Edge-IIoTset stream-order sensitivity and NF-ToN-IoT-v2/CICIoT2023 low BCL detection using validation data only.
4. Implement and evaluate adaptive evasion against the full IDS+BCL runtime; report attack success, query/perturbation budgets, and utility at matched false-positive rates.
5. Establish a security contribution that is novel and useful under the USENIX threat model, then rewrite the paper, Open Science Appendix, and Ethics discussion against confirmatory evidence.
