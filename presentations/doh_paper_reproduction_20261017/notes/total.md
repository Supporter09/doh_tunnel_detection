# 01_Reproducing and Improving DoH Tunnel Detection

This project reproduces the two-layer DoH tunnel detector and then evaluates a mask-aware bidirectional GRU under a stricter protocol. In the capped, session-disjoint experiment, best-window F1 improves by 4.73 percentage points on layer one and 4.40 points on layer two. These are bounded comparative results, not a claim of full-dataset convergence.

---

# 02_Encryption hides content—not packet behavior

DNS-over-HTTPS hides domain names, answers, and tunnel content inside TLS. It does not hide packet direction, packet length, timing, or burst structure. The paper’s central hypothesis is that these observable sequences remain discriminative without decrypting payloads.

---

# 03_A two-layer decision system

The first layer separates DoH from ordinary HTTPS traffic. Only traffic classified as DoH proceeds to the second layer, which separates benign DoH from malicious tunnels. We reproduce these two decisions independently so that each result has a clear task definition and evidence boundary.

---

# 04_Packet clumps convert traffic into a sequence

A packet clump groups consecutive packets moving in the same direction until direction changes or the timeout is exceeded. Each clump preserves direction, packet lengths, and timing, and the first N clumps form a model window. Increasing N adds behavioral context but also delays the decision.

---

# 05_CIRA-CIC-DoHBrw-2020 provides both tables and packets

The benchmark contains non-DoH HTTPS, benign DoH, and malicious DoH tunnel traffic. Published CSV features support the statistical replication, while raw PCAP files are required to reconstruct packet-clump sequences. Our evidence path therefore starts with the tabular baseline and then moves to a raw-PCAP session-disjoint experiment.

---

# 06_The paper evaluates two representations in parallel

The statistical path waits for a completed flow, derives summary features, and evaluates classical and neural classifiers. The time-series path converts packet streams into directional clumps and sweeps LSTM windows from one through ten. The original work evaluates both paths with an eighty–twenty random split at flow level.

---

# 07_Flow-summary models reproduce near-perfect F1

The paper reports random-forest F1 of 0.993 for layer one and 0.999 for layer two. Our project random forest reaches 0.9965 and 0.9997 under the same flow-random paradigm. This reproduces the headline statistical performance, but it also inherits the same cross-session leakage risk.

---

# 08_A few clumps recover most discriminative signal

The paper’s LSTM improves rapidly as the model observes more clumps. Its selected operating points reach 0.993 F1 for layer one at six clumps and 0.991 for layer two at three clumps. The reported mean detection delays are 0.574 and 0.502 seconds, supporting the early-detection argument relative to waiting for full flows.

---

# 09_Reproducibility required fixing method and protocol gaps

We corrected the printed clump termination condition and added a bounds check before packet indexing. We also pinned optimizer settings, seeds, manifests, and the source snapshot. Most importantly, we added a session-and-scenario group-disjoint split and a mask-aware BiGRU with attention as the improved sequence model.

---

# 10_Random flow splits overstate cross-session generalization

At the paper-selected windows, the replicated paper architecture scores 0.9784 and 0.9405 F1 under flow-random splits. Under session-disjoint evaluation, those values fall to zero and 0.1324. This collapse demonstrates that random flow accuracy cannot be interpreted as unseen-session generalization.

---

# 11_The corrected run is broad—but intentionally capped

The audit covers 13,754 capture sources, 13,150 session groups, and about 97.1 gigabytes of uncompressed evidence. It processes 201,321 flows and retains 1,325: five hundred non-DoH, 325 benign DoH, and five hundred malicious DoH. The cap of twenty-five flows per capture controls runtime, so these results remain comparative rather than converged full-data estimates.

---

# 12_The improved model is strong—but not at every selected window

At the paper’s windows, the improved BiGRU reaches 0.9153 F1 on layer one and 0.5538 on layer two under the corrected split. These values substantially exceed the corrected paper architecture, but layer two is still far below the paper’s flow-random claim at three clumps. The table therefore keeps paper-reported, project-random, corrected-baseline, and improved evidence separate.

---

# 13_Mask-aware BiGRU improves both detection layers

When each model is compared at its own best corrected window, layer-one F1 increases from 0.9179 to 0.9651 and layer-two F1 from 0.9425 to 0.9864. The absolute gains are 4.73 and 4.40 percentage points, with zero observed false-positive rate at both improved optima. This is the project’s positive model result within the capped session-disjoint sample.

---

# 14_What the current evidence does—and does not—establish

Four limitations constrain interpretation. The per-capture cap limits convergence evidence, benign DoH availability stops at 325 retained flows, all traffic comes from one benchmark environment, and best windows are selected after the sweep. Larger caps, repeated seeds, confidence intervals, external datasets, and a locked holdout are the next required checks.

---

# 15_Preserve the baseline. Fix the evaluation. Improve the sequence model.

The reproduction keeps the statistical and four-layer LSTM baselines traceable. The corrected protocol tests transfer to unseen sessions, and the mask-aware BiGRU improves both tasks under that protocol. The primary result is methodological validity; the model gain matters because it survives the stricter evaluation.
