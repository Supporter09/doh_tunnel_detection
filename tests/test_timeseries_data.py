"""Unit tests for time-series data pipeline, DoHLyzer normalization, windowing, and splits.

Acceptance criteria verified:
1. Exact transform equations and DoHLyzer vector ordering.
2. [-1, -1, -1, -1, 0] padding and attention masks.
3. Stride-1 sliding windows.
4. Deterministic stratification.
5. Explicit paper flow-level leakage caveat.
6. Zero session overlap for corrected session/scenario-disjoint splits.
7. Impossible split errors.
8. Train-only metadata separation (class weights, positive weights, empirical scalers).
"""

from __future__ import annotations

import dataclasses
import json
import math
import unittest

from doh_reproduction.clumping import Clump
from doh_reproduction.timeseries_data import (
    CORRECTED_DISJOINT_ASSURANCE,
    LAYER1_LABEL_DOH,
    LAYER1_LABEL_NON_DOH,
    LAYER2_LABEL_BENIGN,
    LAYER2_LABEL_MALICIOUS,
    PADDING_VECTOR,
    PAPER_FLOW_RANDOM_LEAKAGE_CAVEAT,
    PAPER_REFERENCE_FEATURE_ORDER,
    ImpossibleSplitError,
    SequenceMetadata,
    SequenceSample,
    SplitManifest,
    SplitResult,
    TrainOnlyFeatureScaler,
    build_split_manifest,
    clump_to_reference_vector,
    clumps_to_reference_vectors,
    compute_class_weights,
    compute_pos_weight,
    create_mask_for_window,
    create_segments,
    create_sequence_samples,
    evaluate_split_leakage,
    normalize_count,
    normalize_direction,
    normalize_size,
    normalize_time,
    paper_flow_random,
    samples_to_arrays,
    samples_to_numpy_payload,
    session_scenario_disjoint,
    split_samples,
)


class TestClumpTransformEquationsAndOrder(unittest.TestCase):
    """Prove exact transform equations and reference vector ordering."""

    def test_paper_reference_feature_order_definition(self) -> None:
        expected = ("interarrival", "duration", "size", "packet_count", "direction")
        self.assertEqual(PAPER_REFERENCE_FEATURE_ORDER, expected)

    def test_normalize_time_exact_equations(self) -> None:
        # Equation: (log10(max(1e-12, x)) - (-12)) / (-2 - (-12))
        # Case 1: x = 0.0 -> max(1e-12, 0.0) = 1e-12 -> log10 = -12 -> norm = 0.0
        self.assertAlmostEqual(normalize_time(0.0), 0.0, places=9)

        # Case 2: x = 1e-12 -> norm = 0.0
        self.assertAlmostEqual(normalize_time(1e-12), 0.0, places=9)

        # Case 3: x = 0.01 (10 ms) -> log10 = -2 -> norm = 1.0
        self.assertAlmostEqual(normalize_time(0.01), 1.0, places=9)

        # Case 4: x = 0.001 (1 ms) -> log10 = -3 -> (-3 - (-12)) / 10 = 9 / 10 = 0.9
        self.assertAlmostEqual(normalize_time(0.001), 0.9, places=9)

    def test_normalize_size_exact_equations(self) -> None:
        # Equation: (log10(min(1e4, size)) - 0.5) / (4.0 - 0.5)
        # Case 1: size = 10000 (1e4) -> log10 = 4.0 -> (4.0 - 0.5) / 3.5 = 1.0
        self.assertAlmostEqual(normalize_size(10000), 1.0, places=9)

        # Case 2: size = 10**0.5 (~3.16227766) -> log10 = 0.5 -> norm = 0.0
        self.assertAlmostEqual(normalize_size(10.0**0.5), 0.0, places=9)

        # Case 3: size = 1000 -> log10 = 3.0 -> (3.0 - 0.5) / 3.5 = 2.5 / 3.5 = 5/7
        self.assertAlmostEqual(normalize_size(1000), 2.5 / 3.5, places=9)

        # Case 4: size > 1e4 capped at 1e4 -> 1.0
        self.assertAlmostEqual(normalize_size(50000), 1.0, places=9)

    def test_normalize_count_exact_equations(self) -> None:
        # Equation: (log2(min(256, count)) - 0.0) / (8.0 - 0.0)
        # Case 1: count = 1 -> log2(1) = 0.0 -> norm = 0.0
        self.assertAlmostEqual(normalize_count(1), 0.0, places=9)

        # Case 2: count = 256 -> log2(256) = 8.0 -> norm = 1.0
        self.assertAlmostEqual(normalize_count(256), 1.0, places=9)

        # Case 3: count = 16 -> log2(16) = 4.0 -> 4.0 / 8.0 = 0.5
        self.assertAlmostEqual(normalize_count(16), 0.5, places=9)

        # Case 4: count > 256 capped at 256 -> 1.0
        self.assertAlmostEqual(normalize_count(1000), 1.0, places=9)

    def test_normalize_direction_mapping(self) -> None:
        # Canonical Clump: 0: forward (Client->Server), 1: backward (Server->Client)
        self.assertEqual(normalize_direction(0), 1.0)
        self.assertEqual(normalize_direction(1), -1.0)
        self.assertEqual(normalize_direction(-1), -1.0)

        with self.assertRaises(ValueError):
            normalize_direction(99)

    def test_clump_to_reference_vector_ordering_and_values(self) -> None:
        clump = Clump(
            size=10000,
            pkt_count=256,
            direction=0,
            duration=0.01,
            interarrival=0.001,
        )

        vec = clump_to_reference_vector(clump, normalize=True)
        self.assertEqual(len(vec), 5)

        # Expected: [interarrival, duration, size, packet_count, direction]
        # interarrival (0.001) -> 0.9
        # duration (0.01) -> 1.0
        # size (10000) -> 1.0
        # pkt_count (256) -> 1.0
        # direction (0) -> 1.0
        self.assertAlmostEqual(vec[0], 0.9, places=6)
        self.assertAlmostEqual(vec[1], 1.0, places=6)
        self.assertAlmostEqual(vec[2], 1.0, places=6)
        self.assertAlmostEqual(vec[3], 1.0, places=6)
        self.assertAlmostEqual(vec[4], 1.0, places=6)

        # Unnormalized check
        raw_vec = clump_to_reference_vector(clump, normalize=False)
        self.assertEqual(raw_vec, [0.001, 0.01, 10000.0, 256.0, 0.0])


class TestPaddingVectorAndMasks(unittest.TestCase):
    """Prove [-1, -1, -1, -1, 0] padding and mask behaviors."""

    def test_padding_vector_exact_values(self) -> None:
        self.assertEqual(PADDING_VECTOR, [-1.0, -1.0, -1.0, -1.0, 0.0])

    def test_short_flow_post_padding(self) -> None:
        clumps = [
            Clump(size=500, pkt_count=2, direction=0, duration=0.0005, interarrival=0.0),
            Clump(size=800, pkt_count=3, direction=1, duration=0.0008, interarrival=0.005),
        ]
        # Window size 6 with pad=True
        segments = create_segments(clumps, window_size=6, stride=1, pad=True)
        self.assertEqual(len(segments), 1)
        window = segments[0]
        self.assertEqual(len(window), 6)

        # First 2 steps are normalized clumps
        self.assertNotEqual(window[0], PADDING_VECTOR)
        self.assertNotEqual(window[1], PADDING_VECTOR)

        # Steps 2, 3, 4, 5 are exact padding vectors
        for step_idx in range(2, 6):
            self.assertEqual(window[step_idx], PADDING_VECTOR)

    def test_mask_generation(self) -> None:
        clumps = [
            Clump(size=500, pkt_count=2, direction=0, duration=0.0005, interarrival=0.0),
        ]
        segments = create_segments(clumps, window_size=4, pad=True)
        mask = create_mask_for_window(segments[0])
        # 1 valid step followed by 3 padding steps
        self.assertEqual(mask, [1.0, 0.0, 0.0, 0.0])

    def test_short_flow_without_padding_returns_empty(self) -> None:
        clumps = [
            Clump(size=500, pkt_count=2, direction=0, duration=0.0005, interarrival=0.0),
        ]
        segments = create_segments(clumps, window_size=6, pad=False)
        self.assertEqual(segments, [])


class TestStrideOneWindows(unittest.TestCase):
    """Prove stride-1 sliding window mechanics."""

    def test_stride_one_window_count(self) -> None:
        # 8 clumps, window_size=6, stride=1 -> exactly 8 - 6 + 1 = 3 windows
        clumps = [
            Clump(size=100 * (i + 1), pkt_count=1, direction=i % 2, duration=0.0, interarrival=0.001)
            for i in range(8)
        ]
        segments = create_segments(clumps, window_size=6, stride=1, pad=False)
        self.assertEqual(len(segments), 3)

        # Window 0 has size 6, Window 1 has size 6, Window 2 has size 6
        for seg in segments:
            self.assertEqual(len(seg), 6)

        # Step 0 of Window 1 must equal Step 1 of Window 0 (stride=1 overlap)
        self.assertEqual(segments[1][0], segments[0][1])
        # Step 0 of Window 2 must equal Step 2 of Window 0
        self.assertEqual(segments[2][0], segments[0][2])

    def test_exact_window_size_flow(self) -> None:
        clumps = [
            Clump(size=100, pkt_count=1, direction=0, duration=0.0, interarrival=0.0)
            for _ in range(6)
        ]
        segments = create_segments(clumps, window_size=6, stride=1)
        self.assertEqual(len(segments), 1)
        self.assertEqual(len(segments[0]), 6)


class TestImmutableSequenceMetadataAndSamples(unittest.TestCase):
    """Prove immutability and provenance tracking of sequence samples."""

    def test_sample_and_metadata_are_frozen(self) -> None:
        meta = SequenceMetadata(
            sample_id="flow_001_w0",
            flow_id="flow_001",
            session_id="session_A",
            scenario_id="benign_doh_firefox",
            label=LAYER1_LABEL_DOH,
            layer=1,
            window_index=0,
            window_size=6,
        )
        sample = SequenceSample(
            features=tuple((0.0, 0.0, 0.0, 0.0, 1.0) for _ in range(6)),
            metadata=meta,
        )

        # Attempting mutation must raise FrozenInstanceError
        with self.assertRaises(dataclasses.FrozenInstanceError):
            sample.metadata.label = 99  # type: ignore[misc]

        with self.assertRaises(dataclasses.FrozenInstanceError):
            sample.features = ()  # type: ignore[misc]

    def test_sample_properties_and_arrays_payload(self) -> None:
        clumps = [
            Clump(size=1000, pkt_count=4, direction=0, duration=0.001, interarrival=0.0)
            for _ in range(6)
        ]
        samples = create_sequence_samples(
            flow_id="flow_42",
            session_id="session_alpha",
            scenario_id="malicious_doh_iodine",
            label=LAYER2_LABEL_MALICIOUS,
            clumps=clumps,
            window_size=6,
            layer=2,
        )
        self.assertEqual(len(samples), 1)
        s = samples[0]
        self.assertEqual(s.label, LAYER2_LABEL_MALICIOUS)
        self.assertEqual(s.session_id, "session_alpha")
        self.assertEqual(s.scenario_id, "malicious_doh_iodine")
        self.assertEqual(s.flow_id, "flow_42")
        self.assertFalse(s.is_padded)

        X, y, masks = samples_to_arrays(samples)
        self.assertEqual(len(X), 1)
        self.assertEqual(len(X[0]), 6)
        self.assertEqual(len(X[0][0]), 5)
        self.assertEqual(y, [LAYER2_LABEL_MALICIOUS])
        self.assertEqual(masks, [[1.0, 1.0, 1.0, 1.0, 1.0, 1.0]])

        payload = samples_to_numpy_payload(samples)
        self.assertIn("X", payload)
        self.assertIn("y", payload)
        self.assertIn("masks", payload)
        self.assertEqual(payload["sample_ids"], ["flow_42_w0"])


class TestPaperFlowRandomSplitAndCaveat(unittest.TestCase):
    """Prove paper_flow_random deterministic stratification and explicit caveat."""

    def _generate_synthetic_samples(self) -> list[SequenceSample]:
        samples: list[SequenceSample] = []
        # Create 100 samples across 2 classes (60 non_doh, 40 doh) from shared sessions
        for i in range(100):
            lbl = LAYER1_LABEL_NON_DOH if i < 60 else LAYER1_LABEL_DOH
            # Intentionally reuse 5 sessions to trigger cross-flow session leakage
            sess_id = f"session_{(i % 5):02d}"
            scen_id = "non_doh_browsing" if lbl == 0 else "benign_doh_firefox"
            meta = SequenceMetadata(
                sample_id=f"sample_{i:03d}",
                flow_id=f"flow_{i:03d}",
                session_id=sess_id,
                scenario_id=scen_id,
                label=lbl,
            )
            samples.append(
                SequenceSample(
                    features=tuple((0.5, 0.5, 0.5, 0.5, 1.0) for _ in range(6)),
                    metadata=meta,
                )
            )
        return samples

    def test_stratification_preserves_class_proportions(self) -> None:
        samples = self._generate_synthetic_samples()
        result = paper_flow_random(samples, train_ratio=0.80, seed=42)

        # Total 100 samples -> 80 train, 20 test
        self.assertEqual(len(result.train), 80)
        self.assertEqual(len(result.test), 20)
        self.assertEqual(len(result.val), 0)

        # Non-DoH: 60 total -> 48 train (80%), 12 test (20%)
        train_non_doh = sum(1 for s in result.train if s.label == LAYER1_LABEL_NON_DOH)
        test_non_doh = sum(1 for s in result.test if s.label == LAYER1_LABEL_NON_DOH)
        self.assertEqual(train_non_doh, 48)
        self.assertEqual(test_non_doh, 12)

        # DoH: 40 total -> 32 train (80%), 8 test (20%)
        train_doh = sum(1 for s in result.train if s.label == LAYER1_LABEL_DOH)
        test_doh = sum(1 for s in result.test if s.label == LAYER1_LABEL_DOH)
        self.assertEqual(train_doh, 32)
        self.assertEqual(test_doh, 8)

    def test_deterministic_reproducibility(self) -> None:
        samples = self._generate_synthetic_samples()
        res1 = paper_flow_random(samples, train_ratio=0.80, seed=123)
        res2 = paper_flow_random(samples, train_ratio=0.80, seed=123)

        ids1_train = [s.metadata.sample_id for s in res1.train]
        ids2_train = [s.metadata.sample_id for s in res2.train]
        self.assertEqual(ids1_train, ids2_train)

    def test_explicit_paper_leakage_caveat_emitted(self) -> None:
        samples = self._generate_synthetic_samples()
        result = paper_flow_random(samples, train_ratio=0.80, seed=42)

        # Must emit the explicit paper caveat string
        self.assertEqual(result.leakage_caveat, PAPER_FLOW_RANDOM_LEAKAGE_CAVEAT)
        self.assertIn("CAVEAT: paper_flow_random splits flows randomly", result.leakage_caveat)
        self.assertIn("leading to overly optimistic test metrics", result.leakage_caveat)

        # Must detect that shared sessions leaked between train and test
        self.assertTrue(result.leakage_report.has_session_leakage)
        self.assertTrue(len(result.leakage_report.train_test_session_overlap) > 0)
        self.assertTrue(result.manifest.has_leakage)


class TestSessionScenarioDisjointSplit(unittest.TestCase):
    """Prove corrected group/session-disjoint split guarantees zero session overlap."""

    def _generate_multi_session_dataset(self) -> list[SequenceSample]:
        samples: list[SequenceSample] = []
        # Create 12 distinct sessions: 6 for class 0, 6 for class 1
        # Each session has 10 samples
        for s_idx in range(12):
            lbl = LAYER1_LABEL_NON_DOH if s_idx < 6 else LAYER1_LABEL_DOH
            sess_id = f"session_{s_idx:02d}"
            scen_id = f"scenario_type_{lbl}"
            for i in range(10):
                meta = SequenceMetadata(
                    sample_id=f"s_{s_idx:02d}_{i:02d}",
                    flow_id=f"f_{s_idx:02d}_{i:02d}",
                    session_id=sess_id,
                    scenario_id=scen_id,
                    label=lbl,
                )
                samples.append(
                    SequenceSample(
                        features=tuple((0.5, 0.5, 0.5, 0.5, 1.0) for _ in range(6)),
                        metadata=meta,
                    )
                )
        return samples

    def test_zero_session_overlap_guarantee(self) -> None:
        samples = self._generate_multi_session_dataset()
        result = session_scenario_disjoint(
            samples,
            train_ratio=0.70,
            val_ratio=0.15,
            test_ratio=0.15,
            seed=42,
        )

        train_sessions = {s.session_id for s in result.train}
        val_sessions = {s.session_id for s in result.val}
        test_sessions = {s.session_id for s in result.test}

        # Mathematical proof: Disjoint intersections
        self.assertEqual(len(train_sessions & val_sessions), 0)
        self.assertEqual(len(train_sessions & test_sessions), 0)
        self.assertEqual(len(val_sessions & test_sessions), 0)

        # Audit report verification
        self.assertFalse(result.leakage_report.has_session_leakage)
        self.assertEqual(result.leakage_report.train_test_session_overlap, [])
        self.assertEqual(result.leakage_report.train_val_session_overlap, [])
        self.assertEqual(result.leakage_report.val_test_session_overlap, [])
        self.assertFalse(result.manifest.has_leakage)
        self.assertEqual(result.leakage_caveat, CORRECTED_DISJOINT_ASSURANCE)

    def test_tuple_unpacking_and_proportions(self) -> None:
        samples = self._generate_multi_session_dataset()
        train, val, test = split_samples(samples, protocol="session_scenario_disjoint", seed=42)

        self.assertTrue(len(train) > 0)
        self.assertTrue(len(val) > 0)
        self.assertTrue(len(test) > 0)
        self.assertEqual(len(train) + len(val) + len(test), len(samples))


class TestImpossibleSplitErrors(unittest.TestCase):
    """Prove actionable ImpossibleSplitError exceptions under constrained configurations."""

    def test_empty_dataset_raises_impossible_split(self) -> None:
        with self.assertRaises(ImpossibleSplitError):
            paper_flow_random([])

        with self.assertRaises(ImpossibleSplitError):
            session_scenario_disjoint([])

    def test_single_class_stratification_fails(self) -> None:
        # Only class 0 samples
        samples = [
            SequenceSample(
                features=tuple((0.0, 0.0, 0.0, 0.0, 0.0) for _ in range(6)),
                metadata=SequenceMetadata(
                    sample_id=f"s_{i}",
                    flow_id=f"f_{i}",
                    session_id=f"sess_{i}",
                    scenario_id="scen_0",
                    label=0,
                ),
            )
            for i in range(10)
        ]
        with self.assertRaises(ImpossibleSplitError):
            paper_flow_random(samples)

        with self.assertRaises(ImpossibleSplitError):
            session_scenario_disjoint(samples)

    def test_insufficient_sessions_per_class_fails(self) -> None:
        # Only 2 sessions for class 0, but 3-way disjoint split requires at least 3 sessions per class
        samples = [
            SequenceSample(
                features=tuple((0.0, 0.0, 0.0, 0.0, 0.0) for _ in range(6)),
                metadata=SequenceMetadata(
                    sample_id=f"s_{i}",
                    flow_id=f"f_{i}",
                    session_id="sess_0" if i < 5 else "sess_1",
                    scenario_id="scen_0",
                    label=0 if i < 10 else 1,
                ),
            )
            for i in range(12)
        ]
        with self.assertRaises(ImpossibleSplitError):
            session_scenario_disjoint(samples)

    def test_invalid_ratios_raise_value_error(self) -> None:
        samples = [
            SequenceSample(
                features=tuple((0.0, 0.0, 0.0, 0.0, 0.0) for _ in range(6)),
                metadata=SequenceMetadata(
                    sample_id=f"s_{i}",
                    flow_id=f"f_{i}",
                    session_id=f"sess_{i}",
                    scenario_id="scen_0",
                    label=i % 2,
                ),
            )
            for i in range(10)
        ]
        # Sum != 1.0
        with self.assertRaises(ValueError):
            session_scenario_disjoint(samples, train_ratio=0.5, val_ratio=0.2, test_ratio=0.2)

        # Invalid protocol
        with self.assertRaises(ValueError):
            split_samples(samples, protocol="unsupported_protocol")


class TestTrainOnlyMetadataSeparation(unittest.TestCase):
    """Prove train-only class weights, positive weights, and feature statistics."""

    def test_class_weights_strictly_derived_from_train(self) -> None:
        # Imbalanced training labels: 80 class 0, 20 class 1
        train_labels = [0] * 80 + [1] * 20
        weights = compute_class_weights(train_labels)

        # w_c = N / (K * N_c)
        # w_0 = 100 / (2 * 80) = 0.625
        # w_1 = 100 / (2 * 20) = 2.5
        self.assertAlmostEqual(weights[0], 0.625, places=6)
        self.assertAlmostEqual(weights[1], 2.5, places=6)

        # Pos weight: neg_count / pos_count = 80 / 20 = 4.0
        self.assertAlmostEqual(compute_pos_weight(train_labels), 4.0, places=6)

    def test_train_only_feature_scaler_no_test_leakage(self) -> None:
        # Create train samples with feature 0 ~ 10.0
        train_samples = [
            SequenceSample(
                features=tuple((10.0, 1.0, 1.0, 1.0, 1.0) for _ in range(6)),
                metadata=SequenceMetadata(
                    sample_id=f"train_{i}",
                    flow_id=f"f_tr_{i}",
                    session_id=f"sess_tr_{i}",
                    scenario_id="scen_0",
                    label=0,
                ),
            )
            for i in range(5)
        ]

        # Create test samples with feature 0 ~ 100.0 (distribution shift)
        test_samples = [
            SequenceSample(
                features=tuple((100.0, 1.0, 1.0, 1.0, 1.0) for _ in range(6)),
                metadata=SequenceMetadata(
                    sample_id=f"test_{i}",
                    flow_id=f"f_te_{i}",
                    session_id=f"sess_te_{i}",
                    scenario_id="scen_0",
                    label=0,
                ),
            )
            for i in range(2)
        ]

        scaler = TrainOnlyFeatureScaler()
        # Transform before fit must raise ValueError
        with self.assertRaises(ValueError):
            scaler.transform(test_samples)

        scaler.fit(train_samples)
        self.assertTrue(scaler.is_fitted)
        self.assertEqual(scaler.fitted_samples_count, 5)
        self.assertAlmostEqual(scaler.means[0], 10.0, places=4)  # type: ignore[index]

        # Transform test samples using TRAIN parameters (mean=10.0)
        # Scaled feature 0 will be non-zero (shifted), proving test data did not update scaler
        test_scaled = scaler.transform(test_samples)
        self.assertEqual(len(test_scaled), 2)
        # If test data had contaminated scaler, test mean would have driven mean towards ~35
        self.assertAlmostEqual(scaler.means[0], 10.0, places=4)  # type: ignore[index]

    def test_split_manifest_serialization(self) -> None:
        samples = [
            SequenceSample(
                features=tuple((0.5, 0.5, 0.5, 0.5, 1.0) for _ in range(6)),
                metadata=SequenceMetadata(
                    sample_id=f"s_{i}",
                    flow_id=f"f_{i}",
                    session_id=f"sess_{i % 4}",
                    scenario_id="scen_0",
                    label=i % 2,
                ),
            )
            for i in range(20)
        ]
        result = paper_flow_random(samples, train_ratio=0.80, seed=42)
        manifest = result.manifest

        self.assertEqual(manifest.manifest_version, "1.0.0")
        self.assertIn("0", manifest.train_class_counts)
        self.assertIn("1", manifest.train_class_counts)
        self.assertIn("0", manifest.class_weights)
        self.assertIn("1", manifest.class_weights)

        # Check JSON serialization roundtrip
        json_str = manifest.to_json()
        manifest_dict = json.loads(json_str)
        self.assertEqual(manifest_dict["manifest_version"], "1.0.0")
        self.assertEqual(manifest_dict["protocol"], "paper_flow_random")

class TestMultiClassSessionDisjointSplitAndMaxWindows(unittest.TestCase):
    """Behavioral tests for multi-class session-disjoint splits and window bounds."""

    def test_multi_class_sessions_split_without_assuming_single_label(self) -> None:
        # Construct sessions where each session has both class 0 and class 1
        samples = []
        for s_idx in range(6):
            sess_name = f"browsing_session_{s_idx}"
            # Class 0 sample in this session
            samples.append(
                SequenceSample(
                    features=tuple(tuple([0.1] * 5) for _ in range(6)),
                    metadata=SequenceMetadata(
                        sample_id=f"sample_{s_idx}_c0",
                        flow_id=f"flow_{s_idx}_c0",
                        session_id=sess_name,
                        scenario_id="browsing",
                        label=0,
                    ),
                )
            )
            # Class 1 sample in this session
            samples.append(
                SequenceSample(
                    features=tuple(tuple([0.2] * 5) for _ in range(6)),
                    metadata=SequenceMetadata(
                        sample_id=f"sample_{s_idx}_c1",
                        flow_id=f"flow_{s_idx}_c1",
                        session_id=sess_name,
                        scenario_id="browsing",
                        label=1,
                    ),
                )
            )

        # Should NOT fail with "Disjoint stratified split requires at least 2 distinct classes"
        # or incorrectly assume each session is single-labeled
        res = session_scenario_disjoint(samples, train_ratio=0.5, val_ratio=0.25, test_ratio=0.25)

        # Check each split has both classes
        train_labels = {s.label for s in res.train}
        val_labels = {s.label for s in res.val}
        test_labels = {s.label for s in res.test}
        self.assertEqual(train_labels, {0, 1})
        self.assertEqual(val_labels, {0, 1})
        self.assertEqual(test_labels, {0, 1})

        # Verify zero session overlap
        train_sess = {s.session_id for s in res.train}
        val_sess = {s.session_id for s in res.val}
        test_sess = {s.session_id for s in res.test}
        self.assertTrue(train_sess.isdisjoint(val_sess))
        self.assertTrue(train_sess.isdisjoint(test_sess))
        self.assertTrue(val_sess.isdisjoint(test_sess))

    def test_impossible_split_when_class_in_under_3_sessions(self) -> None:
        samples = [
            SequenceSample(
                features=tuple(tuple([0.1] * 5) for _ in range(6)),
                metadata=SequenceMetadata(
                    sample_id=f"s_{i}",
                    flow_id=f"f_{i}",
                    session_id=f"sess_{i}",
                    scenario_id="browsing",
                    label=0 if i < 4 else 1,  # Class 1 only in sess_4 and sess_5 (2 sessions)
                ),
            )
            for i in range(6)
        ]
        with self.assertRaises(ImpossibleSplitError) as ctx:
            session_scenario_disjoint(samples)
        self.assertIn("Class 1 appears in only 2 session(s)", str(ctx.exception))

    def test_bounded_windows_in_create_segments_and_samples(self) -> None:
        clumps = [
            Clump(
                direction=0,
                size=100 + i * 10,
                pkt_count=2,
                duration=0.01,
                interarrival=0.005,
            )
            for i in range(20)
        ]
        # Window size 3, stride 1: 20 clumps would produce 18 segments
        segments = create_segments(clumps, window_size=3, stride=1, max_segments=4)
        self.assertEqual(len(segments), 4, "Must bound segments to max_segments")

        samples = create_sequence_samples(
            flow_id="f1",
            session_id="s1",
            scenario_id="sc1",
            label=0,
            clumps=clumps,
            window_size=3,
            stride=1,
            max_windows=5,
        )
        self.assertEqual(len(samples), 5, "Must bound samples to max_windows")


if __name__ == "__main__":
    unittest.main()
