# Kết Quả Benchmark Tabular Trên Kaggle

## Phạm vi

Hai thực nghiệm này đánh giá bộ phân loại cổ điển trên 29 đặc trưng thống kê cấp flow từ `dhoogla/cicdohbrw2020`, version 3. Chúng là **tabular statistical baselines**, không phải tái hiện packet-clumping hay LSTM của MontazeriShatoori et al. Raw PCAP vẫn là điều kiện bắt buộc để thực hiện nhánh replication time-series.

Cả hai lượt chạy dùng stratified random 80/20 flow-level split (`paper_flow_random_80_20`), seed 42. Đây là protocol đối sánh với paper, nhưng không loại trừ leakage theo session/scenario vì Kaggle mirror không cung cấp metadata phiên capture.

## Xuất xứ có thể kiểm toán

| Task | Input | Git source | Snapshot SHA-256 | Metrics | Experiment manifest |
|---|---|---|---|---|---|
| L1 — DoH vs NonDoH | `L1-DoH-NonDoH.parquet`, 1,019,117 flows | `2f6c7de2feecf85b4155e98a0090f579a61dd074` | `41268752f8f8136d68af7eaf6e65adf5d7877d9b0500e11b5191bb4ccd3c471f` | [`data/manifests/kaggle_tabular_l1_metrics.json`](../data/manifests/kaggle_tabular_l1_metrics.json) | [`data/manifests/kaggle_tabular_l1_experiment.json`](../data/manifests/kaggle_tabular_l1_experiment.json) |
| L2 — Benign DoH vs Malicious DoH | `L2-BenignDoH-MaliciousDoH.parquet`, 268,661 flows | `03e3166dff4a920a7a6a538f343ec7be19c495a3` | `7660d6f404a7e60200165f9fff5190d99a9bf079baa66ceaf8ddc33b6c7b9d53` | [`data/manifests/kaggle_tabular_l2_metrics.json`](../data/manifests/kaggle_tabular_l2_metrics.json) | [`data/manifests/kaggle_tabular_l2_experiment.json`](../data/manifests/kaggle_tabular_l2_experiment.json) |

## Kết quả Layer 1

Positive class là `doh`; test set có 203,824 flows.

| Model | Macro-F1 | DoH F1 | FPR (NonDoH → DoH) | ROC-AUC | PR-AUC |
|---|---:|---:|---:|---:|---:|
| Random Forest | 0.996570 | 0.994945 | 0.000959 | 0.999303 | 0.998830 |
| Decision Tree | 0.994931 | 0.992534 | 0.002525 | 0.994856 | 0.987281 |
| Linear SVM | 0.877381 | 0.816561 | 0.046991 | 0.944419 | 0.884568 |
| GaussianNB | 0.474924 | 0.494389 | 0.702209 | 0.891848 | 0.765818 |

Decision: Random Forest is the Layer-1 tabular candidate in this comparison. GaussianNB is rejected: it misclassified 105,396 of 150,092 NonDoH test flows as DoH.

## Kết quả Layer 2

Positive class là `malicious_doh`; test set có 53,733 flows: 3,825 benign và 49,908 malicious. Vì benign chỉ chiếm 7.1%, accuracy không phải metric quyết định; dùng Macro-F1, benign error count và PR-AUC.

| Model | Macro-F1 | Malicious F1 | Benign → Malicious FPR | ROC-AUC | PR-AUC |
|---|---:|---:|---:|---:|---:|
| Random Forest | 0.999789 | 0.999970 | 0.000261 | 1.000000 | 1.000000 |
| Decision Tree | 0.999507 | 0.999930 | 0.000784 | 0.999568 | 0.999934 |
| Linear SVM | 0.889112 | 0.985193 | 0.256209 | 0.946026 | 0.993909 |
| GaussianNB | 0.745602 | 0.966201 | 0.510065 | 0.896054 | 0.986663 |

Decision: Random Forest is the selected Layer-2 tabular candidate. It made 1 benign-to-malicious error and 2 malicious-to-benign errors in this flow-random split. This is not evidence of generalization to unseen capture sessions; raw-PCAP session metadata is needed for that test.

## Limits and next comparison

1. The Kaggle mirror has only flow summaries; it cannot evaluate packet clumps, early detection latency, clump length, direction, or a time-series LSTM.
2. The current random flow split can place correlated flows from one capture scenario on both sides of the split. The reported scores may therefore be optimistic.
3. When official PCAP acquisition completes, rerun an explicit session/scenario-disjoint benchmark and the paper-compatible clump-sequence path.
