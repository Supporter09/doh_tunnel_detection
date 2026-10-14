# Phase 1: Cải Tiến Tabular Cho Demo Hai Tầng

## Phạm vi

Phase 1 dùng Kaggle mirror `dhoogla/cicdohbrw2020` v3 để cải tiến demo hai tầng dựa trên 29 flow-summary features. Đây là **tabular statistical detection**, không phải packet-clumping/LSTM replication. Split vẫn là stratified random flow-level 80/20; do thiếu session/scenario metadata, các điểm số chỉ là đối sánh trong cùng corpus và có thể lạc quan.

Mỗi experiment giữ outer test 20%. Khi calibration bật, outer-train được tách tiếp thành 60% model-train và 20% calibration-validation. Platt scaling và operating threshold chỉ fit/chọn trên calibration-validation; outer test không tham gia quyết định threshold.

## Cấu hình

| Thiết lập | Giá trị |
|---|---|
| Seed | `42` |
| Calibration | Logistic/Platt scaling trên continuous score |
| Mục tiêu FPR | `0.001` trên validation — 0.1% negative traffic bị báo thành positive |
| Models | Random Forest, HistGradientBoosting, Decision Tree, Linear SVM, GaussianNB |
| Ablation | Loại lần lượt flow-volume, packet-length, packet-timing, response-timing khỏi Random Forest |

## Kết quả Layer 1 — DoH vs NonDoH

| Model | Macro-F1 mặc định | FPR mặc định | Macro-F1 sau threshold | FPR sau threshold |
|---|---:|---:|---:|---:|
| **Random Forest** | **0.996494** | **0.000939** | **0.996385** | **0.000853** |
| HistGradientBoosting | 0.995734 | 0.001213 | 0.995636 | 0.000933 |
| Decision Tree | 0.994535 | 0.002912 | 0.424089 | 0.000000 |
| Linear SVM | 0.877509 | 0.046978 | 0.607905 | 0.001013 |
| GaussianNB | 0.475267 | 0.701736 | 0.424089 | 0.000000 |

**Chọn cho demo L1:** Random Forest, threshold `0.658077`. Trên outer test, threshold giảm false positives từ 141 xuống 128, đổi lại false negatives tăng từ 413 lên 443. Random Forest vẫn có Macro-F1 tốt nhất trong experiment này; HistGradientBoosting train nhanh hơn nhưng không cải thiện F1/FPR.

### Ablation L1 — Random Forest

| Feature group bị loại | Macro-F1 | FPR |
|---|---:|---:|
| Không loại | 0.996494 | 0.000939 |
| Flow volume | 0.996240 | 0.000973 |
| **Packet length** | **0.993530** | **0.001199** |
| Packet timing | 0.996298 | 0.001133 |
| Response timing | 0.996107 | 0.001033 |

Packet-length features đóng góp mạnh nhất cho L1. `PacketLengthMode` là feature importance cao nhất của Random Forest (`0.265283`).

## Kết quả Layer 2 — Benign DoH vs Malicious DoH

Positive class là `malicious_doh`; chỉ 7.1% outer test là benign. Macro-F1 và benign-to-malicious FPR là metric chính, không phải accuracy.

| Model | Macro-F1 mặc định | FPR mặc định | Macro-F1 sau threshold | FPR sau threshold |
|---|---:|---:|---:|---:|
| Random Forest | 0.999719 | 0.000523 | 0.999437 | **0.000261** |
| **HistGradientBoosting** | **0.999859** | **0.000523** | **0.999859** | **0.000523** |
| Decision Tree | 0.999507 | 0.000784 | 0.066455 | 0.000000 |
| Linear SVM | 0.888156 | 0.257778 | 0.203151 | 0.000523 |
| GaussianNB | 0.730161 | 0.521569 | 0.066455 | 0.000000 |

**Chọn cho demo L2:** HistGradientBoosting với threshold `0.5`. Nó có Macro-F1 `0.999859`, 2 benign-to-malicious errors, và không bỏ sót malicious flow trên outer test. Random Forest là phương án dự phòng nếu ưu tiên giảm false alarm xuống 1 benign flow: threshold `0.858102` đổi thêm 5 false negatives để giảm false positives từ 2 còn 1.

### Ablation L2 — Random Forest

| Feature group bị loại | Macro-F1 | FPR |
|---|---:|---:|
| Không loại | 0.999719 | 0.000523 |
| Flow volume | 0.999648 | 0.000523 |
| **Packet length** | **0.990190** | **0.029020** |
| Packet timing | 0.999789 | 0.000261 |
| Response timing | 0.999437 | 0.001307 |

Packet-length features cũng là nhóm quyết định nhất cho L2. Khi bỏ nhóm này, benign false-alarm rate tăng từ khoảng 0.05% lên 2.90%. `PacketLengthMode` là feature importance cao nhất (`0.226472`).

## Demo configuration

```text
Input: 29 flow-statistical features
  → Layer 1: calibrated Random Forest, τ = 0.658077
  → if predicted DoH
  → Layer 2: HistGradientBoosting, τ = 0.5
  → output: NonDoH | Benign DoH | Malicious DoH
```

Các classifiers L1 và L2 được đánh giá trên hai Kaggle tables riêng. Đây là demo kiến trúc hai tầng dùng chung feature schema, không phải chứng minh end-to-end trên cùng một linked flow corpus.

## Bằng chứng tái lập

- [L1 evidence manifest](../data/manifests/kaggle_phase1_l1_evidence.json)
- [L2 evidence manifest](../data/manifests/kaggle_phase1_l2_evidence.json)
- L1 source: Git `fb2dbe7e3fe3818be23769612a3061a65afae24f`, snapshot `7967e12c8dea97fda343f3372eaa6234fbcb60bac0b2b84a34fee109b1d310a9`.
- L2 source: Git `7a2dbeb243bef03ee3393494c15890674333c9de`, snapshot `9b8f8644a43474fd5894d439aba5458124d86d71d3872ceaef0b80e042e5884b`.

## Không suy luận quá mức

1. Random flow split có thể rò session/scenario; không dùng các số này để tuyên bố khả năng generalize sang resolver, tunnel tool, hoặc capture session chưa thấy.
2. CSV/Parquet không có packet order, direction, timestamp; Phase 1 không đánh giá packet clumping, sequence length, latency, hay LSTM.
3. Cần PCAP và session/scenario metadata cho Phase 2: scenario-disjoint evaluation cùng packet-clump time-series model.
