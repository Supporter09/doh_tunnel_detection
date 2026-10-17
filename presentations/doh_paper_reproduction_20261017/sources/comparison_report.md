# Comprehensive Experimental Comparison: CIRA-CIC-DoHBrw-2020 Reproduction

This document presents the complete comparative evaluation between the published findings
of MontazeriShatoori et al. (IEEE DASC/PiCom/CBDCom/CyberSciTech 2020) and the defensive
offline reproduction and improvement study.

## Evidentiary Provenance Taxonomy
- `[Paper-Reported]`: Numbers published in original paper (Tables III–VI). Evaluated under 80/20 random flow split.
- `[Project-Observed]`: Tabular statistical baseline independently evaluated on Kaggle mirror (29 features).
- `[Project-Calibrated]`: Models tuned via Platt scaling on validation targeting FPR <= 0.001.
- `[Project-Replication]`: Packet-clump LSTM evaluated under paper-like 80/20 flow split.
- `[Project-Corrected]`: Evaluated under group-disjoint 70/15/15 split eliminating cross-session leakage.
- `[Project-Improved]`: Mask-aware BiGRU with attention pooling and class weighting.
- `[Unavailable]`: Missing or future experiments; explicitly rendered as unavailable (never zero).

---

### Statistical Flow-Level Classification: Paper vs. Project Benchmark

*Baseline comparison on flow-summary statistical features (DoHMeter). Evaluated under stratified random 80/20 flow split. Flow-random splits permit cross-session correlation across train/test.*

| Layer | Model | Provenance | Split Protocol | Precision | Recall | F1-Score / Macro-F1 | FPR | Median Latency | Mean Latency | Caveats & Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Layer 1 (DoH vs Non-DoH) | Random Forest (RF) | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.993 | 0.993 | 0.993 | unavailable | 1.397 s | 20.393 s | Flow-random split; vulnerable to cross-session correlation/leakage; Highest performance in paper flow-statistical evaluation |
| Layer 1 (DoH vs Non-DoH) | C4.5 Decision Tree | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.993 | 0.993 | 0.993 | unavailable | 1.397 s | 20.393 s | Flow-random split; vulnerable to cross-session correlation/leakage; Tied with Random Forest |
| Layer 1 (DoH vs Non-DoH) | 2D CNN | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.980 | 0.980 | 0.980 | unavailable | 1.397 s | 20.393 s | Flow-random split; vulnerable to cross-session correlation/leakage; 28 features reshaped into 2D matrix |
| Layer 1 (DoH vs Non-DoH) | DNN | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.970 | 0.970 | 0.970 | unavailable | 1.397 s | 20.393 s | Flow-random split; vulnerable to cross-session correlation/leakage; Multi-layer feedforward network |
| Layer 1 (DoH vs Non-DoH) | SVM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.877 | 0.877 | 0.877 | unavailable | 1.397 s | 20.393 s | Flow-random split; vulnerable to cross-session correlation/leakage; Support Vector Machine |
| Layer 1 (DoH vs Non-DoH) | Naive Bayes (NB) | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.840 | 0.834 | 0.833 | unavailable | 1.397 s | 20.393 s | Flow-random split; vulnerable to cross-session correlation/leakage; Conditional independence assumption |
| Layer 1 (DoH vs Non-DoH) | Project Random Forest | [Project-Observed] | Stratified Random Flow Split (80/20) | unavailable | unavailable | 0.9965 | 0.000939 | unavailable | unavailable | Flow-random split; tabular baseline on 29 summary features |
| Layer 1 (DoH vs Non-DoH) | Project Random Forest (Calibrated τ=0.66) | [Project-Calibrated] | Stratified Random Flow Split (80/20) | unavailable | unavailable | 0.9964 | 0.000853 | unavailable | unavailable | Validation-fit Platt scaling targeting FPR <= 0.001 |
| Layer 1 (DoH vs Non-DoH) | Project Hist Gradient Boosting | [Project-Observed] | Stratified Random Flow Split (80/20) | unavailable | unavailable | 0.9957 | 0.001213 | unavailable | unavailable | Flow-random split; tabular baseline on 29 summary features |
| Layer 1 (DoH vs Non-DoH) | Project Hist Gradient Boosting (Calibrated τ=0.72) | [Project-Calibrated] | Stratified Random Flow Split (80/20) | unavailable | unavailable | 0.9956 | 0.000933 | unavailable | unavailable | Validation-fit Platt scaling targeting FPR <= 0.001 |
| Layer 1 (DoH vs Non-DoH) | Project Decision Tree | [Project-Observed] | Stratified Random Flow Split (80/20) | unavailable | unavailable | 0.9945 | 0.002912 | unavailable | unavailable | Flow-random split; tabular baseline on 29 summary features |
| Layer 1 (DoH vs Non-DoH) | Project Linear Svm | [Project-Observed] | Stratified Random Flow Split (80/20) | unavailable | unavailable | 0.8775 | 0.046978 | unavailable | unavailable | Flow-random split; tabular baseline on 29 summary features |
| Layer 1 (DoH vs Non-DoH) | Project Gaussian Nb | [Project-Observed] | Stratified Random Flow Split (80/20) | unavailable | unavailable | 0.4753 | 0.701736 | unavailable | unavailable | Flow-random split; tabular baseline on 29 summary features |
| Layer 2 (Benign DoH vs Malicious DoH) | Random Forest (RF) | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.999 | 0.999 | 0.999 | unavailable | 34.064 s | 53.924 s | Flow-random split; vulnerable to cross-session correlation/leakage; Near-perfect discrimination on holdout flow split |
| Layer 2 (Benign DoH vs Malicious DoH) | C4.5 Decision Tree | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.999 | 0.999 | 0.999 | unavailable | 34.064 s | 53.924 s | Flow-random split; vulnerable to cross-session correlation/leakage; Tied with Random Forest |
| Layer 2 (Benign DoH vs Malicious DoH) | 2D CNN | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.990 | 0.990 | 0.990 | unavailable | 34.064 s | 53.924 s | Flow-random split; vulnerable to cross-session correlation/leakage; 28 features reshaped into 2D matrix |
| Layer 2 (Benign DoH vs Malicious DoH) | DNN | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.980 | 0.980 | 0.980 | unavailable | 34.064 s | 53.924 s | Flow-random split; vulnerable to cross-session correlation/leakage; Multi-layer feedforward network |
| Layer 2 (Benign DoH vs Malicious DoH) | SVM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.890 | 0.885 | 0.884 | unavailable | 34.064 s | 53.924 s | Flow-random split; vulnerable to cross-session correlation/leakage; Support Vector Machine |
| Layer 2 (Benign DoH vs Malicious DoH) | Naive Bayes (NB) | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.836 | 0.833 | 0.832 | unavailable | 34.064 s | 53.924 s | Flow-random split; vulnerable to cross-session correlation/leakage; Conditional independence assumption |
| Layer 2 (Benign DoH vs Malicious DoH) | Project Random Forest | [Project-Observed] | Stratified Random Flow Split (80/20) | unavailable | unavailable | 0.9997 | 0.000523 | unavailable | unavailable | Flow-random split; tabular baseline on 29 summary features |
| Layer 2 (Benign DoH vs Malicious DoH) | Project Random Forest (Calibrated τ=0.86) | [Project-Calibrated] | Stratified Random Flow Split (80/20) | unavailable | unavailable | 0.9994 | 0.000261 | unavailable | unavailable | Validation-fit Platt scaling targeting FPR <= 0.001 |
| Layer 2 (Benign DoH vs Malicious DoH) | Project Hist Gradient Boosting | [Project-Observed] | Stratified Random Flow Split (80/20) | unavailable | unavailable | 0.9999 | 0.000523 | unavailable | unavailable | Flow-random split; tabular baseline on 29 summary features |
| Layer 2 (Benign DoH vs Malicious DoH) | Project Hist Gradient Boosting (Calibrated τ=0.50) | [Project-Calibrated] | Stratified Random Flow Split (80/20) | unavailable | unavailable | 0.9999 | 0.000523 | unavailable | unavailable | Validation-fit Platt scaling targeting FPR <= 0.001 |
| Layer 2 (Benign DoH vs Malicious DoH) | Project Decision Tree | [Project-Observed] | Stratified Random Flow Split (80/20) | unavailable | unavailable | 0.9995 | 0.000784 | unavailable | unavailable | Flow-random split; tabular baseline on 29 summary features |
| Layer 2 (Benign DoH vs Malicious DoH) | Project Linear Svm | [Project-Observed] | Stratified Random Flow Split (80/20) | unavailable | unavailable | 0.8882 | 0.257778 | unavailable | unavailable | Flow-random split; tabular baseline on 29 summary features |
| Layer 2 (Benign DoH vs Malicious DoH) | Project Gaussian Nb | [Project-Observed] | Stratified Random Flow Split (80/20) | unavailable | unavailable | 0.7302 | 0.521569 | unavailable | unavailable | Flow-random split; tabular baseline on 29 summary features |

---

### Time-Series Packet-Clump Sequence Evaluation: Sliding Window Sweeps (l = 1..10)

*Evaluation of recurrent sequence classifiers over packet-clump sequences with sliding window lengths l in [1, 10]. Clump timeout = 1 ms. Missing future project runs render as 'unavailable', never as 0.*

| Layer | Window Length (l) | Model | Provenance | Split Protocol | Precision | Recall | F1-Score | Mean Duration | Median Duration | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Layer 1 (DoH vs Non-DoH) | 1 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.877 | 0.876 | 0.876 | 0.081 s | 0.000 s | published |
| Layer 1 (DoH vs Non-DoH) | 1 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.8535 | 0.9585 | 0.9030 | unavailable | unavailable | completed |
| Layer 1 (DoH vs Non-DoH) | 2 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.950 | 0.949 | 0.949 | 0.167 s | 0.002 s | published |
| Layer 1 (DoH vs Non-DoH) | 2 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9199 | 0.9645 | 0.9417 | unavailable | unavailable | completed |
| Layer 1 (DoH vs Non-DoH) | 3 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.953 | 0.951 | 0.951 | 0.262 s | 0.010 s | published |
| Layer 1 (DoH vs Non-DoH) | 3 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9459 | 0.9710 | 0.9583 | unavailable | unavailable | completed |
| Layer 1 (DoH vs Non-DoH) | 4 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.983 | 0.983 | 0.983 | 0.366 s | 0.020 s | published |
| Layer 1 (DoH vs Non-DoH) | 4 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9598 | 0.9900 | 0.9746 | unavailable | unavailable | completed |
| Layer 1 (DoH vs Non-DoH) | 5 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.987 | 0.987 | 0.987 | 0.468 s | 0.030 s | published |
| Layer 1 (DoH vs Non-DoH) | 5 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9655 | 0.9945 | 0.9798 | unavailable | unavailable | completed |
| Layer 1 (DoH vs Non-DoH) | 6 | Paper 4-Layer LSTM (Paper Optimal) | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.993 | 0.993 | 0.993 | 0.574 s | 0.047 s | published |
| Layer 1 (DoH vs Non-DoH) | 6 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9723 | 0.9845 | 0.9784 | unavailable | unavailable | completed |
| Layer 1 (DoH vs Non-DoH) | 7 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.996 | 0.996 | 0.996 | 0.675 s | 0.060 s | published |
| Layer 1 (DoH vs Non-DoH) | 7 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9755 | 0.9950 | 0.9851 | unavailable | unavailable | completed |
| Layer 1 (DoH vs Non-DoH) | 8 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.996 | 0.996 | 0.996 | 0.775 s | 0.077 s | published |
| Layer 1 (DoH vs Non-DoH) | 8 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9755 | 0.9950 | 0.9851 | unavailable | unavailable | completed |
| Layer 1 (DoH vs Non-DoH) | 9 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.998 | 0.998 | 0.998 | 0.871 s | 0.091 s | published |
| Layer 1 (DoH vs Non-DoH) | 9 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9789 | 0.9955 | 0.9871 | unavailable | unavailable | completed |
| Layer 1 (DoH vs Non-DoH) | 10 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.998 | 0.998 | 0.998 | 0.964 s | 0.105 s | published |
| Layer 1 (DoH vs Non-DoH) | 10 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9910 | 0.9875 | 0.9892 | unavailable | unavailable | completed |
| Layer 2 (Benign DoH vs Malicious DoH) | 1 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.825 | 0.792 | 0.782 | 0.164 s | 0.002 s | published |
| Layer 2 (Benign DoH vs Malicious DoH) | 1 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.6403 | 0.9700 | 0.7714 | unavailable | unavailable | completed |
| Layer 2 (Benign DoH vs Malicious DoH) | 2 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.985 | 0.984 | 0.985 | 0.329 s | 0.022 s | published |
| Layer 2 (Benign DoH vs Malicious DoH) | 2 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.8262 | 0.9485 | 0.8831 | unavailable | unavailable | completed |
| Layer 2 (Benign DoH vs Malicious DoH) | 3 | Paper 4-Layer LSTM (Paper Optimal) | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.991 | 0.991 | 0.991 | 0.502 s | 0.050 s | published |
| Layer 2 (Benign DoH vs Malicious DoH) | 3 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9177 | 0.9645 | 0.9405 | unavailable | unavailable | completed |
| Layer 2 (Benign DoH vs Malicious DoH) | 4 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.995 | 0.995 | 0.995 | 0.685 s | 0.094 s | published |
| Layer 2 (Benign DoH vs Malicious DoH) | 4 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9633 | 0.9720 | 0.9676 | unavailable | unavailable | completed |
| Layer 2 (Benign DoH vs Malicious DoH) | 5 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.997 | 0.997 | 0.997 | 0.872 s | 0.142 s | published |
| Layer 2 (Benign DoH vs Malicious DoH) | 5 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9651 | 0.9960 | 0.9803 | unavailable | unavailable | completed |
| Layer 2 (Benign DoH vs Malicious DoH) | 6 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.998 | 0.998 | 0.998 | 1.063 s | 0.203 s | published |
| Layer 2 (Benign DoH vs Malicious DoH) | 6 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9832 | 0.9970 | 0.9901 | unavailable | unavailable | completed |
| Layer 2 (Benign DoH vs Malicious DoH) | 7 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.997 | 0.997 | 0.997 | 1.260 s | 0.258 s | published |
| Layer 2 (Benign DoH vs Malicious DoH) | 7 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9847 | 0.9965 | 0.9906 | unavailable | unavailable | completed |
| Layer 2 (Benign DoH vs Malicious DoH) | 8 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.999 | 0.999 | 0.999 | 1.450 s | 0.313 s | published |
| Layer 2 (Benign DoH vs Malicious DoH) | 8 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9896 | 0.9975 | 0.9935 | unavailable | unavailable | completed |
| Layer 2 (Benign DoH vs Malicious DoH) | 9 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.999 | 0.999 | 0.999 | 1.630 s | 0.373 s | published |
| Layer 2 (Benign DoH vs Malicious DoH) | 9 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9940 | 0.9955 | 0.9948 | unavailable | unavailable | completed |
| Layer 2 (Benign DoH vs Malicious DoH) | 10 | Paper 4-Layer LSTM | [Paper-Reported] | Stratified Random Flow Split (80/20) | 0.999 | 0.999 | 0.999 | 1.803 s | 0.440 s | published |
| Layer 2 (Benign DoH vs Malicious DoH) | 10 | Project paper_v4 | [Project-Replication] | paper_flow_random | 0.9950 | 0.9970 | 0.9960 | unavailable | unavailable | completed |

---

### Head-to-Head Comparison: Original Paper Claims vs Project Implementations

*Direct comparison between published paper values and project results at the paper's identified optimal operating points (l=6 for Layer 1, l=3 for Layer 2). Maintains strict paradigm separation between full-flow statistical and packet-clump sequential.*

| Layer | Evaluation Paradigm | Model Name | Provenance | Split Protocol | Window (l) | Precision | Recall | F1-Score | Detection Delay (Median) | Detection Delay (Mean) | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Layer 1 (DoH vs Non-DoH) | Statistical Flow Summary (28/29 Features) | Paper Random Forest (Table III) | [Paper-Reported] | Stratified Random Flow Split (80/20) | N/A | 0.993 | 0.993 | 0.993 | 1.397 s | 20.393 s | published |
| Layer 1 (DoH vs Non-DoH) | Statistical Flow Summary (28/29 Features) | Project Random Forest (Tabular) | [Project-Observed] | Stratified Random Flow Split (80/20) | N/A | unavailable | unavailable | 0.9965 | < 0.005 ms | unavailable | observed |
| Layer 1 (DoH vs Non-DoH) | Time-Series Packet Clumps (5-tuple Clumps) | Paper 4-Layer LSTM (Table V) | [Paper-Reported] | Stratified Random Flow Split (80/20) | 6 | 0.993 | 0.993 | 0.993 | 0.047 s | 0.574 s | published |
| Layer 1 (DoH vs Non-DoH) | Time-Series Packet Clumps (5-tuple Clumps) | Project paper_v4 | [Project-Replication] | session_scenario_disjoint | 6 | 0.0000 | 0.0000 | 0.0000 | unavailable | unavailable | completed |
| Layer 2 (Benign DoH vs Malicious DoH) | Statistical Flow Summary (28/29 Features) | Paper Random Forest (Table IV) | [Paper-Reported] | Stratified Random Flow Split (80/20) | N/A | 0.999 | 0.999 | 0.999 | 34.064 s | 53.924 s | published |
| Layer 2 (Benign DoH vs Malicious DoH) | Statistical Flow Summary (28/29 Features) | Project Random Forest (Tabular) | [Project-Observed] | Stratified Random Flow Split (80/20) | N/A | unavailable | unavailable | 0.9997 | < 0.005 ms | unavailable | observed |
| Layer 2 (Benign DoH vs Malicious DoH) | Time-Series Packet Clumps (5-tuple Clumps) | Paper 4-Layer LSTM (Table VI) | [Paper-Reported] | Stratified Random Flow Split (80/20) | 3 | 0.991 | 0.991 | 0.991 | 0.050 s | 0.502 s | published |
| Layer 2 (Benign DoH vs Malicious DoH) | Time-Series Packet Clumps (5-tuple Clumps) | Project paper_v4 | [Project-Replication] | session_scenario_disjoint | 3 | 1.0000 | 0.0709 | 0.1324 | unavailable | unavailable | completed |

---

### Protocol Leakage Audit: Flow-Level Random Split vs Session/Scenario Group-Disjoint Split

*Evaluation of the cross-session generalization gap. The 2020 paper used a flow-level 80/20 random split that risks cross-session leakage. Our corrected protocol enforces 70/15/15 group-disjoint splits across capture sessions.*

| Layer | Model | Split Protocol | Cross-Session Overlap | Precision | Recall | F1-Score | FPR | Leakage Assessment / Generalization Note | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Layer 1 (DoH vs Non-DoH) | Paper Replication Model (l=6) | Stratified Random Flow Split (80/20) | Permitted (flows from same session in train & test) | 0.9723 | 0.9845 | 0.9784 | 0.1164 | Vulnerable to cross-session leakage; potentially optimistic benchmark | completed |
| Layer 1 (DoH vs Non-DoH) | Corrected Evaluation (l=6) | Session/Scenario Group-Disjoint Split (70/15/15) | Zero (group-disjoint by PCAP session/scenario) | 0.0000 | 0.0000 | 0.0000 | 0.0000 | True out-of-session generalization test; benchmark for operational deployment | completed |
| Layer 2 (Benign DoH vs Malicious DoH) | Paper Replication Model (l=3) | Stratified Random Flow Split (80/20) | Permitted (flows from same session in train & test) | 0.9177 | 0.9645 | 0.9405 | 0.0865 | Vulnerable to cross-session leakage; identical tunneling tools correlated | completed |
| Layer 2 (Benign DoH vs Malicious DoH) | Corrected Evaluation (l=3) | Session/Scenario Group-Disjoint Split (70/15/15) | Zero (group-disjoint by PCAP session/scenario) | 1.0000 | 0.0709 | 0.1324 | 0.0000 | True out-of-session generalization test; evaluates tunnel detection on unseen capture scenarios | completed |

---

### Early Detection Latency vs Accuracy Trade-Off: Full-Flow vs Clump Sequences

*Analysis of the critical trade-off between detection delay and classification accuracy. Packet clumping achieves statistical-grade discrimination within the first 3-6 clumps, reducing detection delay from tens of seconds to hundreds of milliseconds.*

| Layer | Methodology | Window / Horizon | F1-Score | Mean Duration | Median Duration | Latency Reduction vs Flow Baseline | Operational Practicality |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Layer 1 (DoH vs Non-DoH) | Full-Flow 28 Features (Paper RF) | Entire flow duration | 0.993 | 20.393 s | 1.397 s | Baseline (0.0%) | High latency; flow must complete or reach timeout before classification |
| Layer 1 (DoH vs Non-DoH) | Packet Clump LSTM (l=1) | First clump (1 packet burst) | 0.876 | 0.081 s | 0.000 s | 99.6% reduction (mean) | Sub-100ms early alert, but precision (0.877) has higher false alarm rate |
| Layer 1 (DoH vs Non-DoH) | Packet Clump LSTM (l=6, Paper Optimal) | First 6 clumps | 0.993 | 0.574 s | 0.047 s | 97.2% reduction (mean) | Optimal sweet spot: matches RF (0.993 F1) in < 0.6s mean delay (100% < 0.8s) |
| Layer 2 (Benign DoH vs Malicious DoH) | Full-Flow 28 Features (Paper RF) | Entire flow duration | 0.999 | 53.924 s | 34.064 s | Baseline (0.0%) | Extremely high latency (~54s mean); unviable for active inline tunnel prevention |
| Layer 2 (Benign DoH vs Malicious DoH) | Packet Clump LSTM (l=1) | First clump (1 packet burst) | 0.782 | 0.164 s | 0.002 s | 99.7% reduction (mean) | Fastest tunnel triage, but low F1 (0.782) misses stealthy tunnels |
| Layer 2 (Benign DoH vs Malicious DoH) | Packet Clump LSTM (l=3, Paper Optimal) | First 3 clumps | 0.991 | 0.502 s | 0.050 s | 99.1% reduction (mean) | Optimal sweet spot: matches RF (0.991 F1) in ~0.5s mean delay (100% < 1.0s) |
| Layer 2 (Benign DoH vs Malicious DoH) | Packet Clump LSTM (l=6) | First 6 clumps | 0.998 | 1.063 s | 0.203 s | 98.0% reduction (mean) | Near-perfect tunnel identification (0.998 F1) within ~1.06s |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - Traffic Collection Delay (Device: arm (cpu)) | First 5 clumps (n=25) | 0.817 | 1.972 s | 0.477 s | 90.3% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - Sequence Preprocessing (Device: arm (cpu)) | First 5 clumps (n=25) | 0.817 | 0.007 ms | 0.007 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - Model Inference (Device: arm (cpu)) | First 5 clumps (n=25) | 0.817 | 0.108 ms | 0.107 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (9281.0 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - End-to-End Latency (Device: arm (cpu)) | First 5 clumps (n=25) | 0.817 | 1.972 s | 0.477 s | 90.3% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Traffic Collection Delay (Device: arm (cpu)) | First 5 clumps (n=25) | 0.918 | 1.972 s | 0.477 s | 90.3% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Sequence Preprocessing (Device: arm (cpu)) | First 5 clumps (n=25) | 0.918 | 0.009 ms | 0.006 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Model Inference (Device: arm (cpu)) | First 5 clumps (n=25) | 0.918 | 0.074 ms | 0.061 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (13464.4 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - End-to-End Latency (Device: arm (cpu)) | First 5 clumps (n=25) | 0.918 | 1.972 s | 0.477 s | 90.3% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - Traffic Collection Delay (Device: arm (cpu)) | First 7 clumps (n=25) | 0.965 | 4.682 s | 0.871 s | 77.0% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - Sequence Preprocessing (Device: arm (cpu)) | First 7 clumps (n=25) | 0.965 | 0.009 ms | 0.008 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - Model Inference (Device: arm (cpu)) | First 7 clumps (n=25) | 0.965 | 0.132 ms | 0.132 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (7552.0 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - End-to-End Latency (Device: arm (cpu)) | First 7 clumps (n=25) | 0.965 | 4.682 s | 0.871 s | 77.0% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Traffic Collection Delay (Device: arm (cpu)) | First 7 clumps (n=25) | 0.000 | 4.682 s | 0.871 s | 77.0% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Sequence Preprocessing (Device: arm (cpu)) | First 7 clumps (n=25) | 0.000 | 0.006 ms | 0.006 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Model Inference (Device: arm (cpu)) | First 7 clumps (n=25) | 0.000 | 0.075 ms | 0.075 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (13338.4 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - End-to-End Latency (Device: arm (cpu)) | First 7 clumps (n=25) | 0.000 | 4.682 s | 0.871 s | 77.0% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - Traffic Collection Delay (Device: arm (cpu)) | First 9 clumps (n=25) | 0.612 | 4.790 s | 0.979 s | 76.5% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - Sequence Preprocessing (Device: arm (cpu)) | First 9 clumps (n=25) | 0.612 | 0.009 ms | 0.009 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - Model Inference (Device: arm (cpu)) | First 9 clumps (n=25) | 0.612 | 0.158 ms | 0.158 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (6315.2 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - End-to-End Latency (Device: arm (cpu)) | First 9 clumps (n=25) | 0.612 | 4.790 s | 0.979 s | 76.5% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Traffic Collection Delay (Device: arm (cpu)) | First 9 clumps (n=25) | 0.000 | 4.790 s | 0.979 s | 76.5% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Sequence Preprocessing (Device: arm (cpu)) | First 9 clumps (n=25) | 0.000 | 0.007 ms | 0.007 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Model Inference (Device: arm (cpu)) | First 9 clumps (n=25) | 0.000 | 0.087 ms | 0.087 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (11480.4 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - End-to-End Latency (Device: arm (cpu)) | First 9 clumps (n=25) | 0.000 | 4.790 s | 0.979 s | 76.5% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - Traffic Collection Delay (Device: arm (cpu)) | First 10 clumps (n=25) | 0.699 | 4.815 s | 1.010 s | 76.4% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - Sequence Preprocessing (Device: arm (cpu)) | First 10 clumps (n=25) | 0.699 | 0.009 ms | 0.009 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - Model Inference (Device: arm (cpu)) | First 10 clumps (n=25) | 0.699 | 0.165 ms | 0.164 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (6070.5 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Improved Masked BiGRU - End-to-End Latency (Device: arm (cpu)) | First 10 clumps (n=25) | 0.699 | 4.816 s | 1.010 s | 76.4% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Traffic Collection Delay (Device: arm (cpu)) | First 10 clumps (n=25) | 0.000 | 4.815 s | 1.010 s | 76.4% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Sequence Preprocessing (Device: arm (cpu)) | First 10 clumps (n=25) | 0.000 | 0.008 ms | 0.008 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Model Inference (Device: arm (cpu)) | First 10 clumps (n=25) | 0.000 | 0.098 ms | 0.097 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (10251.7 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 1 (DoH vs Non-DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - End-to-End Latency (Device: arm (cpu)) | First 10 clumps (n=25) | 0.000 | 4.816 s | 1.010 s | 76.4% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - Traffic Collection Delay (Device: arm (cpu)) | First 5 clumps (n=22) | 0.772 | 2.007 s | 0.086 s | 96.3% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - Sequence Preprocessing (Device: arm (cpu)) | First 5 clumps (n=22) | 0.772 | 0.008 ms | 0.007 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - Model Inference (Device: arm (cpu)) | First 5 clumps (n=22) | 0.772 | 0.107 ms | 0.107 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (9302.7 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - End-to-End Latency (Device: arm (cpu)) | First 5 clumps (n=22) | 0.772 | 2.007 s | 0.086 s | 96.3% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Traffic Collection Delay (Device: arm (cpu)) | First 5 clumps (n=22) | 0.000 | 2.007 s | 0.086 s | 96.3% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Sequence Preprocessing (Device: arm (cpu)) | First 5 clumps (n=22) | 0.000 | 0.006 ms | 0.005 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Model Inference (Device: arm (cpu)) | First 5 clumps (n=22) | 0.000 | 0.061 ms | 0.060 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (16399.0 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - End-to-End Latency (Device: arm (cpu)) | First 5 clumps (n=22) | 0.000 | 2.007 s | 0.086 s | 96.3% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - Traffic Collection Delay (Device: arm (cpu)) | First 7 clumps (n=22) | 0.971 | 6.016 s | 3.058 s | 88.8% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - Sequence Preprocessing (Device: arm (cpu)) | First 7 clumps (n=22) | 0.971 | 0.009 ms | 0.008 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - Model Inference (Device: arm (cpu)) | First 7 clumps (n=22) | 0.971 | 0.131 ms | 0.130 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (7636.0 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - End-to-End Latency (Device: arm (cpu)) | First 7 clumps (n=22) | 0.971 | 6.016 s | 3.058 s | 88.8% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Traffic Collection Delay (Device: arm (cpu)) | First 7 clumps (n=22) | 0.004 | 6.016 s | 3.058 s | 88.8% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Sequence Preprocessing (Device: arm (cpu)) | First 7 clumps (n=22) | 0.004 | 0.007 ms | 0.007 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Model Inference (Device: arm (cpu)) | First 7 clumps (n=22) | 0.004 | 0.076 ms | 0.076 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (13139.2 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - End-to-End Latency (Device: arm (cpu)) | First 7 clumps (n=22) | 0.004 | 6.016 s | 3.058 s | 88.8% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - Traffic Collection Delay (Device: arm (cpu)) | First 9 clumps (n=22) | 0.971 | 6.813 s | 3.475 s | 87.4% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - Sequence Preprocessing (Device: arm (cpu)) | First 9 clumps (n=22) | 0.971 | 0.010 ms | 0.009 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - Model Inference (Device: arm (cpu)) | First 9 clumps (n=22) | 0.971 | 0.156 ms | 0.154 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (6424.5 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - End-to-End Latency (Device: arm (cpu)) | First 9 clumps (n=22) | 0.971 | 6.813 s | 3.476 s | 87.4% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Traffic Collection Delay (Device: arm (cpu)) | First 9 clumps (n=22) | 0.942 | 6.813 s | 3.475 s | 87.4% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Sequence Preprocessing (Device: arm (cpu)) | First 9 clumps (n=22) | 0.942 | 0.008 ms | 0.008 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Model Inference (Device: arm (cpu)) | First 9 clumps (n=22) | 0.942 | 0.088 ms | 0.087 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (11390.6 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - End-to-End Latency (Device: arm (cpu)) | First 9 clumps (n=22) | 0.942 | 6.813 s | 3.476 s | 87.4% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - Traffic Collection Delay (Device: arm (cpu)) | First 10 clumps (n=22) | 0.986 | 6.989 s | 3.513 s | 87.0% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - Sequence Preprocessing (Device: arm (cpu)) | First 10 clumps (n=22) | 0.986 | 0.011 ms | 0.010 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - Model Inference (Device: arm (cpu)) | First 10 clumps (n=22) | 0.986 | 0.169 ms | 0.168 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (5904.1 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Improved Masked BiGRU - End-to-End Latency (Device: arm (cpu)) | First 10 clumps (n=22) | 0.986 | 6.989 s | 3.513 s | 87.0% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Traffic Collection Delay (Device: arm (cpu)) | First 10 clumps (n=22) | 0.898 | 6.989 s | 3.513 s | 87.0% reduction (collection only) | Physical network clump observation time; dominates total detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Sequence Preprocessing (Device: arm (cpu)) | First 10 clumps (n=22) | 0.898 | 0.008 ms | 0.008 ms | N/A (sub-component) | In-memory sequence vectorization and log-normalization (batch=1) |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - Model Inference (Device: arm (cpu)) | First 10 clumps (n=22) | 0.898 | 0.099 ms | 0.098 ms | N/A (sub-component) | PyTorch batch size 1 forward pass (10146.4 samples/s); isolated forward pass does NOT equal detection delay |
| Layer 2 (Benign DoH vs Malicious DoH) | [Project-Observed] Packet Clump LSTM (Paper v4) - End-to-End Latency (Device: arm (cpu)) | First 10 clumps (n=22) | 0.898 | 6.989 s | 3.513 s | 87.0% reduction (mean) | Aligned per-sample sum of collection delay, preprocessing, and model inference |

---

### Project Modernization: Methodological, Algorithmic, and Operational Improvements

*Summary of defensive offline reproduction contributions addressing mathematical errata, missing hyperparameters, data leakage vulnerabilities, and operational false alarm constraints.*

| Pillar | Improvement Area | Paper Baseline / Defect | Project Modernization | Demonstrated Benefit | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Algorithm Bug Fix | Clumping Termination Logic (Algorithm 1) | Printed logic inversion: loop terminated when direction equaled next packet | Fixed loop exit to terminate when direction != next OR timePassed > timeout (1ms) | Prevents fragmentation into single-packet clumps; restores physical burst clumping | verified |
| 1. Algorithm Bug Fix | Clumping Array Bounds | Algorithm 1 line 9 accessed packets[counter] after incrementing counter past end | Strict array bounds check: if counter >= len(packets): break before indexing | Zero index-out-of-bounds crashes during packet ingestion | verified |
| 2. Scientific Protocol | Session/Scenario Leakage Guard | 80/20 random flow split mixed packets from identical capture sessions in train/test | Group-disjoint 70/15/15 split strictly partitioning session and scenario IDs | Measures true generalization against unseen adversaries, eliminating optimistic leakage | verified |
| 3. Operational Reliability | Threshold Calibration for Low FPR | Paper used arbitrary default threshold (0.5), yielding unquantified false alarm rates | Platt scaling fit strictly on validation split to satisfy target FPR <= 0.001 (0.1%) | Prevents operational alert fatigue in enterprise networks with high traffic volume | verified |
| 4. Feature Understanding | Tabular Group Feature Ablation | Paper claimed 28 features necessary without evaluating sub-group contribution | Systematic group ablation proved PacketLength features (PacketLengthMode) dominate | Reduces feature engineering overhead; highlights packet size distribution importance | verified |
| 5. Neural Architecture | Mask-Aware BiGRU with Attention | Vanilla unidirectional LSTM with zero/negative padding and uniform aggregation | Bidirectional GRU with explicit masking and learned multi-head attention pooling | Best corrected group-disjoint F1: L1 0.9179->0.9651 (+4.73 pp); L2 0.9425->0.9864 (+4.40 pp) | verified improvement |
| 6. Reproducibility | Immutable Manifests & Auditing | Omitted Adam optimizer, learning rates, batch sizes, seeds, and dataset versions | Complete JSON artifact contracts, source-snapshot SHA-256 pinning, and deterministic test gates | Reproduces the exact evaluated code/config boundary without claiming a full-dataset hash | verified |

---
