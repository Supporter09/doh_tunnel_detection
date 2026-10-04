"""Focused unit tests for packet clumping, timeout, direction, short flow, and validation."""

import unittest

from doh_reproduction.clumping import (
    CLUMP_TIMEOUT_SECONDS,
    Clump,
    Packet,
    clumping,
    segment_clumps,
)


class TestClumpingDirection(unittest.TestCase):
    """Verify clumping behavior when packet direction changes."""

    def test_same_direction_merges_into_single_clump(self) -> None:
        packets = [
            Packet(timestamp=0.0000, length=100, direction=0),
            Packet(timestamp=0.0005, length=200, direction=0),
            Packet(timestamp=0.0009, length=300, direction=0),
        ]
        clumps = clumping(packets)
        self.assertEqual(len(clumps), 1)
        c = clumps[0]
        self.assertEqual(c.size, 600)
        self.assertEqual(c.pkt_count, 3)
        self.assertEqual(c.direction, 0)
        self.assertAlmostEqual(c.duration, 0.0009, places=6)
        self.assertEqual(c.interarrival, 0.0)

    def test_direction_alternation_creates_distinct_clumps(self) -> None:
        # Alternating directions with microscopic time delta (<0.0001s)
        packets = [
            Packet(timestamp=0.0000, length=150, direction=0),
            Packet(timestamp=0.0001, length=250, direction=1),
            Packet(timestamp=0.0002, length=180, direction=0),
            Packet(timestamp=0.0003, length=320, direction=1),
        ]
        clumps = clumping(packets)
        self.assertEqual(len(clumps), 4)
        self.assertEqual([c.direction for c in clumps], [0, 1, 0, 1])
        self.assertEqual([c.size for c in clumps], [150, 250, 180, 320])
        self.assertEqual([c.pkt_count for c in clumps], [1, 1, 1, 1])
        for c in clumps:
            self.assertEqual(c.duration, 0.0)


class TestClumpingTimeout(unittest.TestCase):
    """Verify idle gap threshold timeout behavior."""

    def test_gap_within_timeout_accumulates(self) -> None:
        # Gap is exactly 0.001s (<= timeout 0.001s), must remain in same clump
        packets = [
            Packet(timestamp=1.0000, length=100, direction=0),
            Packet(timestamp=1.0010, length=200, direction=0),
        ]
        clumps = clumping(packets, timeout=CLUMP_TIMEOUT_SECONDS)
        self.assertEqual(len(clumps), 1)
        self.assertEqual(clumps[0].pkt_count, 2)
        self.assertEqual(clumps[0].size, 300)
        self.assertAlmostEqual(clumps[0].duration, 0.0010, places=6)

    def test_gap_exceeding_timeout_splits_clump(self) -> None:
        # Gap is 0.001001s (> timeout 0.001s), must split into 2 clumps
        packets = [
            Packet(timestamp=1.000000, length=100, direction=0),
            Packet(timestamp=1.001001, length=200, direction=0),
        ]
        clumps = clumping(packets, timeout=CLUMP_TIMEOUT_SECONDS)
        self.assertEqual(len(clumps), 2)
        self.assertEqual(clumps[0].size, 100)
        self.assertEqual(clumps[0].pkt_count, 1)
        self.assertEqual(clumps[1].size, 200)
        self.assertEqual(clumps[1].pkt_count, 1)
        self.assertAlmostEqual(clumps[1].interarrival, 0.001001, places=6)

    def test_custom_timeout_override(self) -> None:
        # Custom timeout 0.050s
        packets = [
            Packet(timestamp=0.000, length=100, direction=0),
            Packet(timestamp=0.020, length=100, direction=0),
            Packet(timestamp=0.080, length=100, direction=0),
        ]
        clumps = clumping(packets, timeout=0.050)
        self.assertEqual(len(clumps), 2)
        self.assertEqual(clumps[0].pkt_count, 2)
        self.assertEqual(clumps[1].pkt_count, 1)


class TestClumpingShortFlow(unittest.TestCase):
    """Verify handling of short flows, zero-packet flows, and sliding window padding."""

    def test_empty_packets_returns_empty_clumps(self) -> None:
        self.assertEqual(clumping([]), [])

    def test_single_packet_flow(self) -> None:
        packets = [Packet(timestamp=5.0, length=450, direction=1)]
        clumps = clumping(packets)
        self.assertEqual(len(clumps), 1)
        self.assertEqual(clumps[0].size, 450)
        self.assertEqual(clumps[0].pkt_count, 1)
        self.assertEqual(clumps[0].direction, 1)
        self.assertEqual(clumps[0].duration, 0.0)
        self.assertEqual(clumps[0].interarrival, 0.0)

    def test_short_flow_segment_padding(self) -> None:
        # Flow with 2 clumps segmented with window_size=6 (L1 threshold)
        packets = [
            Packet(timestamp=0.0, length=100, direction=0),
            Packet(timestamp=0.1, length=200, direction=1),
        ]
        clumps = clumping(packets)
        self.assertEqual(len(clumps), 2)

        # When pad=True, pads up to window_size with empty clumps
        padded_segs = segment_clumps(clumps, window_size=6, pad=True)
        self.assertEqual(len(padded_segs), 1)
        seg = padded_segs[0]
        self.assertEqual(len(seg), 6)
        self.assertEqual(seg[0].size, 100)
        self.assertEqual(seg[1].size, 200)
        for empty_clump in seg[2:]:
            self.assertEqual(empty_clump, Clump.empty())
            self.assertEqual(empty_clump.size, 0)
            self.assertEqual(empty_clump.pkt_count, 0)

    def test_short_flow_segment_without_padding_returns_empty(self) -> None:
        clumps = [Clump(size=100, pkt_count=1, direction=0, duration=0.0, interarrival=0.0)]
        unpadded_segs = segment_clumps(clumps, window_size=6, pad=False)
        self.assertEqual(unpadded_segs, [])

    def test_empty_clumps_segmentation(self) -> None:
        self.assertEqual(segment_clumps([], window_size=6), [])


class TestClumpingInvalidInput(unittest.TestCase):
    """Verify input validation and defensive error rejection."""

    def test_negative_payload_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            Packet(timestamp=1.0, length=-50, direction=0)

    def test_non_monotonic_timestamps_raise_value_error(self) -> None:
        packets = [
            Packet(timestamp=2.0, length=100, direction=0),
            Packet(timestamp=1.5, length=100, direction=0),
        ]
        with self.assertRaises(ValueError):
            clumping(packets)

    def test_invalid_types_raise_type_error(self) -> None:
        with self.assertRaises(TypeError):
            Packet(timestamp="not-a-number", length=100, direction=0)  # type: ignore[arg-type]

        with self.assertRaises(TypeError):
            Packet(timestamp=1.0, length=12.5, direction=0)  # type: ignore[arg-type]

        with self.assertRaises(TypeError):
            Packet(timestamp=1.0, length=100, direction="forward")  # type: ignore[arg-type]

    def test_invalid_segmentation_parameters(self) -> None:
        clumps = [Clump.empty()]
        with self.assertRaises(ValueError):
            segment_clumps(clumps, window_size=0)
        with self.assertRaises(ValueError):
            segment_clumps(clumps, window_size=3, stride=0)


class TestDeterministicInterarrival(unittest.TestCase):
    """Verify deterministic interarrival calculation."""

    def test_default_first_clump_interarrival_zero(self) -> None:
        packets = [
            Packet(timestamp=10.5, length=100, direction=0),
            Packet(timestamp=10.6, length=200, direction=1),
        ]
        clumps = clumping(packets)
        self.assertEqual(clumps[0].interarrival, 0.0)
        self.assertAlmostEqual(clumps[1].interarrival, 0.1, places=6)

    def test_custom_first_clump_interarrival(self) -> None:
        packets = [Packet(timestamp=10.5, length=100, direction=0)]
        clumps = clumping(packets, first_interarrival=0.042)
        self.assertEqual(clumps[0].interarrival, 0.042)


if __name__ == "__main__":
    unittest.main()
