<!-- ppt-master-schema: design-spec/v1 -->
# DoH Tunnel Detection Paper Reproduction - Design Spec

## I. Project Information

| Item | Value |
| --- | --- |
| Project Name | DoH Tunnel Detection Paper Reproduction |
| Canvas Format | PPT 16:9 (1280 × 720) |
| Page Count | 15 |
| Primary Language | en-US |
| Target Audience | Faculty members and academic evaluators with technical literacy in networking, cybersecurity, and machine learning |
| Communication Intent | Explain the original paper, demonstrate a faithful reproduction, expose the evaluation leakage risk, and report evidence-backed improvements with limitations before conclusions |
| Desired Audience Outcome | The audience can trace the two-layer method from packets to decisions, distinguish flow-random from session-disjoint evidence, and judge the BiGRU improvement without overgeneralizing the capped run |
| Core Message / Ask / Action | A leakage-aware evaluation changes what “high accuracy” means: on the capped session-disjoint run, the mask-aware BiGRU improves best-window F1 by 4.73 pp on L1 and 4.40 pp on L2, but this is not a full-dataset convergence claim |
| Delivery Context | Presenter-led academic report, approximately 12–15 minutes, with the deck retained for review |
| Artifact Afterlife | Review, audit, archive, and technical hand-off |
| Reading Mode | balanced |
| Content Strategy | Balanced restructuring: preserve all source facts and provenance while organizing them into a claim-led academic narrative |
| Design Style | Evidence Ledger — conclusion-first instructional argument with a light data-journalism and Swiss-grid visual system |
| AI Image Acquisition Path | not applicable |
| Generation Mode | continuous |
| Spec Refinement | disabled |
| Speaker Notes | enabled — confirmed Standard production policy |
| Custom Animations | disabled — confirmed Standard production policy |
| Narration Audio | disabled — confirmed Standard production policy |
| Created Date | 2026-10-17 |

## II. Canvas Specification

| Property | Value |
| --- | --- |
| Format | PPT 16:9 |
| Dimensions | 1280 × 720 |
| viewBox | `0 0 1280 720` |
| Margins | 64 px horizontal, 48 px vertical |
| Content Area | x=64..1216, y=48..672 |

## III. Visual Theme

### Theme Style

- **Mode**: custom; pyramid conclusion-first titles establish the findings, while instructional sequencing makes the packet-clump pipeline and evaluation protocol traceable.
- **Visual style**: custom; publication-grade data hierarchy and source lines sit on a rigorous Swiss grid with large white fields, sharp geometry, and restrained evidence accents.
- **Theme**: Evidence Ledger — every claim is paired with a metric, mechanism, provenance label, or caveat.
- **Tone**: rigorous, calm, technical, transparent about uncertainty.

### Color Scheme

| Role | HEX | Purpose |
| --- | --- | --- |
| Background | #F7F9FC | Primary light field |
| Secondary background | #EAF0F5 | Section bands and comparison zones |
| Primary | #14324B | Titles, axes, primary method |
| Accent | #0E7490 | Project-improved model and key evidence |
| Secondary accent | #D97706 | Caveats, leakage and constrained-run warnings |
| Body text | #172033 | Main copy |
| Secondary text | #5B6875 | Captions, annotations, provenance |
| Divider | #C9D3DC | Hairlines and chart grid |
| Surface | #FFFFFF | Lifted evidence field |
| Positive | #15803D | Verified improvement and pass states |
| Negative | #B42318 | Failure and recall-collapse states |

## IV. Typography System

### Font Plan

| Role | Character (Reference) | Primary | English if non-English | Fallback tail |
| --- | --- | --- | --- | --- |
| Title | Neo-grotesque, bold, assertion-led | Aptos Display | Not applicable | Arial |
| Body | Neutral screen sans | Aptos | Not applicable | Arial |
| Data | Tabular numerical precision | Consolas | Not applicable | Courier New |
| Code | Monospaced technical labels | Consolas | Not applicable | Courier New |

- **Title stack**: Aptos Display, Arial
- **Body stack**: Aptos, Arial
- **Data stack**: Consolas, Courier New
- **Code stack**: Consolas, Courier New
- **Role rationale**: Data and code recur across metrics, protocol labels, configuration values, and provenance identifiers.

### Font Size Hierarchy

| Purpose | Anchor Size (px) |
| --- | ---: |
| Body | 24 |
| Title | 42 |
| Subtitle | 30 |
| Lead | 28 |
| Annotation | 18 |
| Footnote | 14 |
| Data | 20 |
| Code | 18 |
| Display | 68 |

## V. Layout Principles

### Deck-wide Direction

- **Hierarchy direction**: assertion title → dominant evidence or mechanism → one takeaway/caveat → source line.
- **Composition tendency**: asymmetric evidence-led grids; charts and diagrams form the page spine instead of sitting inside repeated card walls.
- **Cross-page continuity**: a thin vertical ledger rule and compact provenance tag recur; its accent changes from primary method to teal improvement and amber caveat.
- **Spacing posture**: variable by page rhythm, with dense methods/results pages separated by breathing synthesis pages.
- **Spacing anchors**: page margin 64 px; block gap 24 px; column gutter 32 px; corner radius 4 px; body leading 34 px.

## VI. Icon Usage Specification

- **Primary bundled library**: tabler-outline
- **Stroke width**: 2

| Icon Path | Suitable Scenarios |
| --- | --- |
| tabler-outline/shield-lock | Encrypted traffic and detection boundary |
| tabler-outline/network | Network capture and flow topology |
| tabler-outline/database | Dataset and evidence artifacts |
| tabler-outline/chart-line | Metrics and sweeps |
| tabler-outline/microscope | Reproduction and audit |
| tabler-outline/alert-triangle | Leakage and limitations |
| tabler-outline/check | Verified implementation and evidence |
| tabler-outline/clock | Detection latency |
| tabler-outline/arrows-split | Evaluation split protocols |
| tabler-outline/brain | Recurrent models and attention |

## VII. Visualization Reference List

| Page | Family | Template | Usage |
| --- | --- | --- | --- |
| P07 | chart | grouped_bar_chart | Compare published statistical F1 across models and layers |
| P08 | chart | line_chart | Show published LSTM F1 across clump-window length |
| P10 | chart | grouped_bar_chart | Contrast paper-window F1 under flow-random and session-disjoint evaluation |
| P12 | table | comparison_matrix | Compare paper-window replication and improved model across both layers |
| P13 | chart | grouped_bar_chart | Compare best corrected F1 for Paper v4 and improved BiGRU |

## VIII. Image Resource List

| Filename | Dimensions | Ratio | Purpose | Type | Image pattern | Crop Policy | Acquire Via | Status | Reference | text_policy | page_role |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NetworkData2_p3_2.jpeg | 947×829 | 1.14 | Original paper classification architecture evidence | Figure | Place as a supporting paper excerpt beside the reconstructed pipeline; retain caption context | no-crop | user | Existing | Extracted from the original paper; preserve every label and edge | none | local |
| NetworkData2_p5_5.jpeg | 403×1143 | 0.35 | Original network capture setup evidence | Figure | Use as a narrow evidence strip with a concise explanatory caption | no-crop | user | Existing | Extracted from the original paper; preserve full diagram | none | local |

## IX. Content Outline

### Part 1: Research question and original contribution

#### Slide 01 - The Real Test Is Generalization

- **Audience move**: From expecting an ordinary replication report → anticipating a claim about leakage-aware evidence.
- **Relationships**: The title claim is supported by the two measured F1 gains and bounded by the capped-run qualifier.
- **Composition**: One dominant claim with two large metric deltas and a narrow provenance footer.
- **Title**: Reproducing and Improving DoH Tunnel Detection
- **Core message**: High flow-random scores are not the end of the story; session-disjoint evidence changes the judgment.
- **Content**: Detection of DoH Tunnels using Time-series Classification of Encrypted Traffic · Paper reproduction + corrected evaluation · L1 +4.73 pp / L2 +4.40 pp best corrected F1 · capped-run qualifier.

#### Slide 02 - Encryption Removes Payload Visibility, Not Traffic Behavior

- **Audience move**: From knowing DoH is encrypted → understanding why timing and size remain detectable signals.
- **Relationships**: DoH encryption hides DNS content; HTTPS metadata remains observable; tunnels alter temporal and volumetric behavior.
- **Composition**: A left-to-right contrast between hidden payload and observable behavior, ending in the detection question.
- **Title**: Encryption hides content, but not packet behavior
- **Core message**: The detector must operate on encrypted traffic metadata rather than DNS payload inspection.
- **Content**: HTTPS/HTTP2 channel · payload inspection blocked · observable size/timing/direction · benign browsing versus covert tunnel.

#### Slide 03 - The Paper Uses a Two-Layer Decision System

- **Audience move**: From a broad detection problem → a precise two-stage classification contract.
- **Relationships**: Layer 1 filters DoH from non-DoH; Layer 2 classifies retained DoH as benign or malicious; both consume derived traffic representations.
- **Composition**: A dominant reconstructed two-layer flow with the original paper figure as supporting evidence.
- **Title**: Detect DoH first; characterize tunnels second
- **Core message**: L1 and L2 are distinct binary tasks and must not be conflated.
- **Content**: PCAP → bidirectional flows → L1 DoH/non-DoH → L2 benign/malicious DoH · labels from resolver/tool context.
- **Images**: NetworkData2_p3_2.jpeg supports the original architecture claim.

#### Slide 04 - Packet Clumps Enable Early Decisions

- **Audience move**: From seeing raw packets as a stream → understanding the clump sequence used by the LSTM.
- **Relationships**: Consecutive TLS application-data packets join a clump when direction is unchanged and gap ≤1 ms; ordered clumps become fixed-length windows.
- **Composition**: One packet timeline transforming into clumps, then into a model-ready sequence.
- **Title**: A clump is a directional packet burst within 1 ms
- **Core message**: Clumping compresses encrypted traffic into short, early behavioral sequences.
- **Content**: TLS application data only · five features: interarrival / duration / size / packet count / direction · stride-one windows ℓ=1…10.
- **Mathematical content**: C_i=\langle interarrival_i,duration_i,size_i,packetCount_i,direction_i\rangle

#### Slide 05 - CIRA-CIC-DoHBrw-2020 Covers Browsing and Three Tunnel Families

- **Audience move**: From knowing the representation → understanding what behavior generated the labels.
- **Relationships**: Non-DoH and benign DoH browsing form normal traffic; dns2tcp, dnscat2, and iodine form malicious DoH scenarios; captures belong to sessions.
- **Composition**: Dataset taxonomy as the dominant structure with a narrow original network-setup excerpt.
- **Title**: The dataset separates traffic class, tool family, and capture session
- **Core message**: Session identity matters because many flows originate from the same experimental scenario.
- **Content**: Firefox + Chrome benign traffic · dns2tcp / dnscat2 / iodine tunnels · DoH resolver labeling · 13,754 capture sources and 13,150 audited sessions.
- **Images**: NetworkData2_p5_5.jpeg shows the paper’s capture setup.

### Part 2: Original methodology and published evidence

#### Slide 06 - The Original Pipeline Has Two Feature Paths

- **Audience move**: From dataset structure → a complete view of the paper’s statistical and sequential methods.
- **Relationships**: One branch aggregates whole-flow statistical features; the other transforms packet clumps into recurrent windows; both feed L1 and L2 classifiers.
- **Composition**: A shared ingestion spine splitting into statistical and time-series branches, then rejoining at evaluation.
- **Title**: One PCAP corpus supports full-flow and early-sequence detection
- **Core message**: Statistical and time-series results answer different latency and evidence questions.
- **Content**: DoHMeter flow extraction · 28 paper features · classical ML/DL · four-layer LSTM · random 80/20 flow split.

#### Slide 07 - Full-Flow Models Are Accurate but Slow

- **Audience move**: From methodology → recognizing the latency cost of whole-flow statistics.
- **Relationships**: Model F1 is compared within each layer; detection delay is determined by waiting for the flow summary.
- **Composition**: Grouped bars for model F1 with two large duration callouts.
- **Title**: Statistical RF reaches 0.993/0.999 F1—but waits 20–54 seconds on average
- **Core message**: Accuracy is strong, but full-flow completion delays intervention.
- **Content**: Paper Table III L1 RF F1 0.993 · Paper Table IV L2 RF F1 0.999 · mean flow duration 20.393 s / 53.924 s · project tabular RF/HGB also near-perfect under flow-random split.
- **Visualization**: `statistical-f1` grouped bars for paper classifier F1; callouts for mean duration.
- **Native-ready**: statistical-f1=yes

#### Slide 08 - More Clumps Increase Accuracy While Remaining Early

- **Audience move**: From full-flow latency → seeing the time-series accuracy/latency trade-off.
- **Relationships**: Window length ℓ orders the observations; F1 and elapsed duration rise together; paper identifies practical operating points.
- **Composition**: Two small-multiple line charts for L1 and L2 with the paper operating windows highlighted.
- **Title**: The paper reaches near-statistical F1 within the first few clumps
- **Core message**: L1 ℓ=6 gives F1 0.993 in 0.574 s mean; L2 ℓ=3 gives F1 0.991 in 0.502 s mean.
- **Content**: Paper Tables V–VI · ℓ=1…10 · early detection versus sequence evidence · mean latency reduction 97.2% L1 and 99.1% L2 versus full-flow baseline.
- **Visualization**: `paper-window-sweep` two-series line chart over ℓ=1…10.
- **Native-ready**: paper-window-sweep=yes

### Part 3: Reproduction and corrected protocol

#### Slide 09 - Reproduction Required Explicit Corrections and Decisions

- **Audience move**: From accepting the paper procedure literally → seeing what had to be fixed or specified.
- **Relationships**: Printed algorithm defects affect clump formation; omitted hyperparameters affect training reproducibility; project choices are separated from paper facts.
- **Composition**: Three evidence lanes: corrected algorithm, reconstructed model, immutable provenance.
- **Title**: Faithful reproduction required fixing logic—not changing the baseline model
- **Core message**: The project preserves the paper model while correcting implementation defects and recording omitted choices.
- **Content**: termination condition direction change OR gap>1 ms · array-bound guard · exact v4 dimensions Dense(10)→LSTM(8ℓ)→Dense(6ℓ)→Dropout→Dense(2ℓ)→sigmoid · seed/config/source snapshot.

#### Slide 10 - Flow-Random Evaluation Can Leak Session Identity

- **Audience move**: From treating 80/20 as neutral → understanding why session-disjoint evaluation is the scientific correction.
- **Relationships**: Flow-random permits one capture session in both train and test; group-disjoint assigns sessions to only one partition; the metric gap exposes generalization risk.
- **Composition**: Split topology above a paired F1 comparison at the paper windows.
- **Title**: Random flow splits test memorization and generalization at the same time
- **Core message**: Session/scenario-disjoint 70/15/15 is the defensible deployment-oriented protocol.
- **Content**: flow-random 80/20: overlap permitted · group-disjoint 70/15/15: zero session overlap by construction · L1 paper-v4 ℓ=6 F1 0.9784→0.0000 · L2 ℓ=3 F1 0.9405→0.1324.
- **Visualization**: `protocol-gap` grouped bars for paper-window F1 by task and protocol.
- **Native-ready**: protocol-gap=yes

#### Slide 11 - The Raw-PCAP Run Is Broadly Audited but Deliberately Capped

- **Audience move**: From seeing a protocol correction → understanding the exact evidence boundary of the experiment.
- **Relationships**: Audit coverage describes the corpus; resource caps determine the retained sample; the sample supports 80 evaluations but not a full-dataset convergence claim.
- **Composition**: A provenance ledger with four hero numbers and one explicit warning strip.
- **Title**: 80 evaluations completed on a capped, session-diverse PCAP sample
- **Core message**: The result is reproducible and informative, but bounded by sampling and class imbalance.
- **Content**: 13,754 capture sources · 97,088,837,141 uncompressed bytes audited · 201,321 flows processed · 1,325 retained: 500 non-DoH / 325 benign DoH / 500 malicious DoH · 25 flows/capture · one invalid iodine PCAPNG skipped · seed 42.

### Part 4: Results and improvement

#### Slide 12 - At the Paper Windows, BiGRU Recovers Much of the Lost Recall

- **Audience move**: From protocol risk → a direct model comparison at the paper’s chosen windows.
- **Relationships**: Rows separate L1 and L2; columns compare Paper v4 and BiGRU under group-disjoint evaluation; recall explains F1 change while FPR remains constrained.
- **Composition**: Compact comparison matrix with F1 as the visual emphasis and recall/FPR as diagnostic support.
- **Title**: The improved model is materially stronger at the paper’s operating windows
- **Core message**: At ℓ=6/3, BiGRU raises corrected F1 from 0.0000→0.9153 on L1 and 0.1324→0.5538 on L2.
- **Content**: L1 ℓ=6 Paper v4 recall 0.0000 versus BiGRU 0.8438 · L2 ℓ=3 Paper v4 recall 0.0709 versus BiGRU 0.3840 · observed FPR 0.0000 / 0.0016.
- **Visualization**: `paper-window-model-matrix` comparison table for task/model/F1/recall/FPR.
- **Native-ready**: paper-window-model-matrix=yes

#### Slide 13 - Best-Window BiGRU Improves Both Layers

- **Audience move**: From fixed paper windows → the strongest observed model comparison under corrected evaluation.
- **Relationships**: Within each layer, the best Paper v4 window is contrasted with the best BiGRU window; delta labels quantify improvement.
- **Composition**: Two dominant paired bars with metric deltas and calibrated operating-point annotations.
- **Title**: Best corrected F1 rises by 4.73 pp on L1 and 4.40 pp on L2
- **Core message**: Mask-aware BiGRU with attention is the successful improvement in this run.
- **Content**: L1 Paper v4 ℓ=5 F1 0.9179 vs BiGRU ℓ=7 F1 0.9651 · L2 Paper v4 ℓ=9 F1 0.9425 vs BiGRU ℓ=10 F1 0.9864 · precision 1.0000 and observed FPR 0.0000 at both improved best points · validation-only Platt calibration and threshold selection.
- **Visualization**: `best-corrected-f1` grouped bars for Paper v4 versus BiGRU by layer.
- **Native-ready**: best-corrected-f1=yes

#### Slide 14 - Phase A Latency Evidence and Phase B Scale Plan

- **Audience move**: From model-quality gains → understanding operational delay and the evidence-expansion plan.
- **Relationships**: End-to-end delay decomposes into traffic collection, preprocessing, and inference; selected-window L1/L2 results lead into a gated Windows CUDA scale ladder.
- **Composition**: Two latency KPI cards above a long-tail warning strip and a five-stage scale sequence.
- **Title**: Traffic collection dominates detection time
- **Core message**: Sub-millisecond model inference does not remove traffic-observation delay; scale tests must preserve session-disjoint evaluation.
- **Content**: L1 BiGRU ℓ=7 F1 0.9651 / p50 end-to-end 0.871 s / inference p50 0.132 ms / n=25 · L2 BiGRU ℓ=10 F1 0.9864 / p50 end-to-end 3.513 s / inference p50 0.168 ms / n=22 · p95 end-to-end approximately 30.055 s for both selected windows · Phase B stages cap 25→50→100→250→optional uncapped on Windows CUDA with split, RAM, metric, and latency gates.

#### Slide 15 - Reproduction Became a Better Scientific Test

- **Audience move**: From reviewing individual results → retaining one defensible conclusion and action plan.
- **Relationships**: Original contribution, corrected evaluation, successful improvement, and next validation form an ordered conclusion.
- **Composition**: One closing statement with a four-step evidence chain and a final hand-off line.
- **Title**: The contribution is not just a better model—it is a better evaluation
- **Core message**: Preserve the paper baseline, eliminate session leakage, improve the sequence model, and expand validation before deployment claims.
- **Content**: reproduce faithfully · separate paper facts from project choices · evaluate session-disjoint · retain BiGRU improvement as provisional evidence · artifacts: manifests, six comparison tables, validated source pipeline.

## X. Speaker Notes Requirements

- **Generation**: enabled
- **Filename**: match each SVG filename under `notes/`
- **Content**: concise presenter interpretation, transitions, source provenance, and caveats; do not introduce unsourced metrics or claims absent from the Design Spec.
- **Total duration**: 12–15 minutes
- **Notes style**: formal, conclusion-first, technically explanatory
- **Presentation purpose**: explain the original paper, demonstrate reproduction, expose leakage risk, and report evidence-backed improvements with limitations
