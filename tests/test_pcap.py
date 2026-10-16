"""Unit tests for streaming PCAP/PCAPNG flow assembly and TLS clumping."""

from __future__ import annotations

import io
import struct
import unittest

from doh_reproduction.clumping import Clump, Packet
from doh_reproduction.pcap import (
    DEFAULT_FLOW_TIMEOUT_SECONDS,
    DOH_RESOLVER_IPS,
    FlowKey,
    FlowRecord,
    TLS_RECORD_APPLICATION_DATA,
    _get_dpkt,
    extract_tls_application_data_bytes,
    iter_pcap_flows,
)


class MockDpkt:
    """Deterministic, pure-stdlib mock of dpkt for PCAP and packet unpacking."""

    class ethernet:
        DLT_EN10MB = 1

        class Ethernet:
            def __init__(self, buf: bytes) -> None:
                if len(buf) < 14:
                    raise ValueError("Buffer too short for Ethernet")
                self.dst = buf[:6]
                self.src = buf[6:12]
                self.type = int.from_bytes(buf[12:14], "big")
                self.data = buf[14:]

    class ip:
        class IP:
            def __init__(self, buf: bytes) -> None:
                if len(buf) < 20:
                    raise ValueError("Buffer too short for IPv4")
                ihl = (buf[0] & 0x0F) * 4
                self.src = buf[12:16]
                self.dst = buf[16:20]
                self.p = buf[9]
                self.data = MockDpkt.tcp.TCP(buf[ihl:])

    class ip6:
        class IP6:
            pass

    class tcp:
        TH_FIN = 0x01
        TH_SYN = 0x02
        TH_RST = 0x04
        TH_PUSH = 0x08
        TH_ACK = 0x10

        class TCP:
            def __init__(self, buf: bytes) -> None:
                if len(buf) < 20:
                    raise ValueError("Buffer too short for TCP")
                self.sport = int.from_bytes(buf[:2], "big")
                self.dport = int.from_bytes(buf[2:4], "big")
                self.seq = int.from_bytes(buf[4:8], "big")
                self.ack = int.from_bytes(buf[8:12], "big")
                offset = ((buf[12] >> 4) & 0x0F) * 4
                self.flags = buf[13]
                self.data = buf[offset:]

    class pcap:
        DLT_EN10MB = 1

        class Reader:
            def __init__(self, stream: io.IOBase) -> None:
                self.stream = stream
                hdr = stream.read(24)
                if len(hdr) < 24:
                    raise ValueError("Truncated PCAP header")

            def datalink(self) -> int:
                return 1

            def __iter__(self):
                while True:
                    hdr = self.stream.read(16)
                    if len(hdr) < 16:
                        break
                    ts_sec, ts_usec, incl_len, _ = struct.unpack("<IIII", hdr)
                    ts = ts_sec + ts_usec / 1_000_000.0
                    buf = self.stream.read(incl_len)
                    if len(buf) < incl_len:
                        break
                    yield (ts, buf)

    class pcapng:
        class Reader:
            pass


def _make_ipv4_bytes(ip_str: str) -> bytes:
    parts = [int(p) for p in ip_str.split(".")]
    return bytes(parts)


def build_synthetic_packet(
    src_ip: str,
    sport: int,
    dst_ip: str,
    dport: int,
    tcp_payload: bytes = b"",
    tcp_flags: int = 0x18,  # PSH | ACK
) -> bytes:
    """Build raw Ethernet + IPv4 + TCP packet bytes."""
    eth = b"\x00" * 6 + b"\x01" * 6 + b"\x08\x00"
    src_bytes = _make_ipv4_bytes(src_ip)
    dst_bytes = _make_ipv4_bytes(dst_ip)
    total_len = 20 + 20 + len(tcp_payload)
    ip_hdr = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        total_len,
        1,
        0x4000,
        64,
        6,
        0,
        src_bytes,
        dst_bytes,
    )
    tcp_hdr = struct.pack(
        "!HHIIBBHHH", sport, dport, 1000, 2000, 0x50, tcp_flags, 8192, 0, 0
    )
    return eth + ip_hdr + tcp_hdr + tcp_payload


def build_tls_record(content_type: int, payload: bytes, version: int = 0x0303) -> bytes:
    """Build a TLS record header and body."""
    return struct.pack("!BHH", content_type, version, len(payload)) + payload


def build_synthetic_pcap_bytes(packets: list[tuple[float, bytes]]) -> bytes:
    """Build standard 24-byte header PCAP binary data."""
    out = io.BytesIO()
    # PCAP Global Header: magic 0xa1b2c3d4, v2.4, thiszone=0, sigfigs=0, snaplen=65535, DLT=1 (EN10MB)
    out.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
    for ts, pkt_data in packets:
        sec = int(ts)
        usec = int(round((ts - sec) * 1_000_000))
        incl_len = len(pkt_data)
        out.write(struct.pack("<IIII", sec, usec, incl_len, incl_len))
        out.write(pkt_data)
    return out.getvalue()


class TestLazyDpktImport(unittest.TestCase):
    """Verify dpkt failure produces actionable runtime errors without import failures."""

    def test_missing_dpkt_raises_actionable_runtime_error(self) -> None:
        """Calling iter_pcap_flows without dpkt installed must raise actionable RuntimeError."""
        import builtins
        from unittest.mock import patch

        real_import = builtins.__import__

        def import_without_dpkt(name: str, *args: object, **kwargs: object) -> object:
            if name == "dpkt":
                raise ImportError("simulated missing optional dependency")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_dpkt):
            with self.assertRaises(RuntimeError) as ctx:
                list(
                    iter_pcap_flows(
                        io.BytesIO(b"\x00" * 30),
                        source_id="test",
                        session_id="s1",
                        scenario_id="sc1",
                    )
                )

        self.assertIn("dpkt", str(ctx.exception))
        self.assertIn("pip install dpkt", str(ctx.exception))


class TestTlsApplicationDataFilter(unittest.TestCase):
    """Verify DoHLyzer TLS Application Data filtering semantics."""

    def test_record_type_23_under_40_bytes_ignored(self) -> None:
        """Ping frames (e.g. 34 bytes) must be filtered out (< 40 bytes)."""
        small_payload = b"X" * 34
        tls_rec = build_tls_record(23, small_payload)
        self.assertIsNone(extract_tls_application_data_bytes(tls_rec, min_bytes=40))

    def test_record_type_23_at_or_above_40_bytes_accepted(self) -> None:
        """Application data >= 40 bytes returns exact payload length."""
        valid_payload = b"A" * 75
        tls_rec = build_tls_record(23, valid_payload)
        self.assertEqual(extract_tls_application_data_bytes(tls_rec, min_bytes=40), 75)

    def test_non_application_records_ignored(self) -> None:
        """Handshake (type 22), Alert (21), ChangeCipherSpec (20) are ignored."""
        handshake_rec = build_tls_record(22, b"H" * 120)
        self.assertIsNone(extract_tls_application_data_bytes(handshake_rec, min_bytes=40))

        alert_rec = build_tls_record(21, b"AL" * 25)
        self.assertIsNone(extract_tls_application_data_bytes(alert_rec, min_bytes=40))


class TestFlowAssemblyAndClumping(unittest.TestCase):
    """Verify bidirectional flow assembly, direction assignment, and clumping."""

    def test_control_packets_ignored(self) -> None:
        """SYN, RST, and pure ACK packets without TLS payload must produce 0 flows."""
        packets = [
            # SYN packet from client
            (1.000, build_synthetic_packet("192.168.1.10", 49152, "8.8.8.8", 443, tcp_flags=0x02)),
            # SYN-ACK packet from server
            (1.001, build_synthetic_packet("8.8.8.8", 443, "192.168.1.10", 49152, tcp_flags=0x12)),
            # ACK packet with 0 payload
            (1.002, build_synthetic_packet("192.168.1.10", 49152, "8.8.8.8", 443, tcp_flags=0x10)),
            # RST packet
            (1.003, build_synthetic_packet("8.8.8.8", 443, "192.168.1.10", 49152, tcp_flags=0x04)),
        ]
        pcap_data = build_synthetic_pcap_bytes(packets)
        flows = list(
            iter_pcap_flows(
                pcap_data,
                source_id="test_control.pcap",
                session_id="session_1",
                scenario_id="benign_doh_google",
                _dpkt_module=MockDpkt,
            )
        )
        self.assertEqual(len(flows), 0)

    def test_bidirectional_clumps_and_directions(self) -> None:
        """Verify client-to-server (0) and server-to-client (1) clump directions."""
        c_ip, c_port = "192.168.1.100", 54321
        s_ip, s_port = "8.8.8.8", 443

        tls_payload_50 = build_tls_record(23, b"C" * 50)
        tls_payload_60 = build_tls_record(23, b"C" * 60)
        tls_payload_120 = build_tls_record(23, b"S" * 120)

        packets = [
            # Client packet 1 (t=1.0000s) -> direction 0
            (1.0000, build_synthetic_packet(c_ip, c_port, s_ip, s_port, tls_payload_50)),
            # Client packet 2 (t=1.0005s, delta=0.5ms <= 1ms clump timeout) -> same clump
            (1.0005, build_synthetic_packet(c_ip, c_port, s_ip, s_port, tls_payload_60)),
            # Server packet 1 (t=1.0020s) -> direction 1 (reversal creates new clump)
            (1.0020, build_synthetic_packet(s_ip, s_port, c_ip, c_port, tls_payload_120)),
        ]
        pcap_data = build_synthetic_pcap_bytes(packets)
        flows = list(
            iter_pcap_flows(
                pcap_data,
                source_id="test_bidi.pcap",
                session_id="session_alpha",
                scenario_id="benign_doh_google",
                _dpkt_module=MockDpkt,
            )
        )
        self.assertEqual(len(flows), 1)
        flow = flows[0]

        # Flow properties
        self.assertEqual(flow.source_id, "test_bidi.pcap")
        self.assertEqual(flow.session_id, "session_alpha")
        self.assertEqual(flow.scenario_id, "benign_doh_google")
        self.assertTrue(flow.is_doh)  # 8.8.8.8 is in DOH_RESOLVER_IPS
        self.assertEqual(flow.packet_count, 3)

        # Packets internal canonical directions
        self.assertEqual(flow.packets[0].direction, 0)
        self.assertEqual(flow.packets[0].length, 50)
        self.assertEqual(flow.packets[1].direction, 0)
        self.assertEqual(flow.packets[1].length, 60)
        self.assertEqual(flow.packets[2].direction, 1)
        self.assertEqual(flow.packets[2].length, 120)

        # Clumps: first 2 packets grouped into clump 0 (direction 0), packet 3 into clump 1 (direction 1)
        self.assertEqual(flow.clump_count, 2)
        c1, c2 = flow.clumps[0], flow.clumps[1]

        # Clump 1
        self.assertEqual(c1.direction, 0)
        self.assertEqual(c1.pkt_count, 2)
        self.assertEqual(c1.size, 110)
        self.assertAlmostEqual(c1.duration, 0.0005, places=6)
        self.assertEqual(c1.interarrival, 0.0)

        # Clump 2
        self.assertEqual(c2.direction, 1)
        self.assertEqual(c2.pkt_count, 1)
        self.assertEqual(c2.size, 120)
        self.assertEqual(c2.duration, 0.0)
        self.assertAlmostEqual(c2.interarrival, 1.0020 - 1.0005, places=6)

    def test_flow_expiry_at_40_seconds(self) -> None:
        """Inactivity exceeding 40s splits traffic into distinct flows."""
        c_ip, c_port = "10.0.0.5", 33333
        s_ip, s_port = "9.9.9.9", 443

        tls_req = build_tls_record(23, b"Q" * 45)
        tls_resp = build_tls_record(23, b"R" * 80)

        packets = [
            # Flow 1: t = 0.0s
            (0.0, build_synthetic_packet(c_ip, c_port, s_ip, s_port, tls_req)),
            # Flow 2: t = 45.0s (> 40s delta)
            (45.0, build_synthetic_packet(s_ip, s_port, c_ip, c_port, tls_resp)),
        ]
        pcap_data = build_synthetic_pcap_bytes(packets)
        flows = list(
            iter_pcap_flows(
                pcap_data,
                source_id="test_expiry.pcap",
                session_id="session_exp",
                scenario_id="benign_doh_quad9",
                flow_timeout_seconds=40.0,
                _dpkt_module=MockDpkt,
            )
        )
        self.assertEqual(len(flows), 2)
        f1, f2 = flows[0], flows[1]

        # First flow closed at t=0.0
        self.assertAlmostEqual(f1.start_time, 0.0)
        self.assertEqual(f1.packet_count, 1)
        self.assertEqual(f1.flow_key.client_ip, c_ip)

        # Second flow opened at t=45.0, with sender establishing client direction (0)
        self.assertAlmostEqual(f2.start_time, 45.0)
        self.assertEqual(f2.packet_count, 1)
        self.assertEqual(f2.flow_key.client_ip, s_ip)
        self.assertEqual(f2.packets[0].direction, 0)

    def test_non_doh_flow_detection(self) -> None:
        """Flow with non-resolver IP has is_doh = False."""
        # 93.184.216.34 is example.com, not in DOH_RESOLVER_IPS
        c_ip, c_port = "192.168.1.50", 40000
        s_ip, s_port = "93.184.216.34", 443

        tls_data = build_tls_record(23, b"W" * 100)
        packets = [(5.0, build_synthetic_packet(c_ip, c_port, s_ip, s_port, tls_data))]
        pcap_data = build_synthetic_pcap_bytes(packets)
        flows = list(
            iter_pcap_flows(
                pcap_data,
                source_id="web.pcap",
                session_id="session_web",
                scenario_id="non_doh_browsing",
                _dpkt_module=MockDpkt,
            )
        )
        self.assertEqual(len(flows), 1)
        self.assertFalse(flows[0].is_doh)

    def test_no_ip_or_port_in_clump_vectors(self) -> None:
        """Verify clump feature vectors contain strictly numerical timing/size features."""
        c_ip, c_port = "10.1.2.3", 55555
        s_ip, s_port = "1.1.1.1", 443

        tls_data = build_tls_record(23, b"X" * 60)
        packets = [(10.0, build_synthetic_packet(c_ip, c_port, s_ip, s_port, tls_data))]
        pcap_data = build_synthetic_pcap_bytes(packets)
        flows = list(
            iter_pcap_flows(
                pcap_data,
                source_id="audit_strip.pcap",
                session_id="s_audit",
                scenario_id="benign_doh_cloudflare",
                _dpkt_module=MockDpkt,
            )
        )
        self.assertEqual(len(flows), 1)
        clump = flows[0].clumps[0]
        # Canonical clump fields: size, pkt_count, direction, duration, interarrival
        vec = clump.to_vector()
        self.assertEqual(len(vec), 5)
        for val in vec:
            self.assertIsInstance(val, (int, float))
            # Must not be an IP address or port string
            self.assertNotIsInstance(val, str)


class TestLongFlowAndCaptureCaps(unittest.TestCase):
    """Behavioral tests verifying per-flow and per-capture bounds inside PCAP iteration."""

    def setUp(self) -> None:
        self.mock_dpkt = MockDpkt

    def _build_pcap_with_n_packets(self, n: int, payload_len: int = 50) -> bytes:
        packets = []
        for i in range(n):
            tls = build_tls_record(TLS_RECORD_APPLICATION_DATA, b"A" * payload_len)
            pkt = build_synthetic_packet("192.168.1.10", 50000, "1.1.1.1", 443, tcp_payload=tls)
            packets.append((1000.0 + i * 0.1, pkt))
        return build_synthetic_pcap_bytes(packets)

    def test_max_flow_packets_caps_flow_and_sets_truncated(self) -> None:
        pcap_data = self._build_pcap_with_n_packets(10, payload_len=50)
        stats: dict = {}
        flows = list(
            iter_pcap_flows(
                pcap_data,
                source_id="flow_cap_test.pcap",
                session_id="s1",
                scenario_id="benign_doh_cloudflare",
                max_flow_packets=4,
                stats=stats,
                _dpkt_module=self.mock_dpkt,
            )
        )
        self.assertEqual(len(flows), 1)
        flow = flows[0]
        self.assertEqual(flow.packet_count, 4, "Flow packets must be capped at max_flow_packets")
        self.assertTrue(flow.truncated, "Flow must be marked truncated")
        self.assertTrue(flow.is_truncated)
        self.assertEqual(stats.get("flows_truncated"), 1)

    def test_max_flow_bytes_caps_flow_and_sets_truncated(self) -> None:
        # 5 packets of 100 bytes payload each = 500 bytes total
        pcap_data = self._build_pcap_with_n_packets(5, payload_len=100)
        flows = list(
            iter_pcap_flows(
                pcap_data,
                source_id="flow_bytes_cap.pcap",
                session_id="s2",
                scenario_id="benign_doh_cloudflare",
                max_flow_bytes=250,
                _dpkt_module=self.mock_dpkt,
            )
        )
        self.assertEqual(len(flows), 1)
        flow = flows[0]
        self.assertEqual(flow.packet_count, 2, "Only 2 100-byte packets fit into 250-byte cap")
        self.assertTrue(flow.truncated)

    def test_max_capture_packets_stops_iteration_early(self) -> None:
        pcap_data = self._build_pcap_with_n_packets(15, payload_len=50)
        stats: dict = {}
        flows = list(
            iter_pcap_flows(
                pcap_data,
                source_id="capture_cap.pcap",
                session_id="s3",
                scenario_id="benign_doh_cloudflare",
                max_capture_packets=5,
                stats=stats,
                _dpkt_module=self.mock_dpkt,
            )
        )
        self.assertEqual(len(flows), 1)
        self.assertEqual(flows[0].packet_count, 5)
        self.assertTrue(stats.get("capture_truncated"))
        self.assertEqual(stats.get("accepted_packets"), 5)
    def test_max_raw_packets_caps_before_decode(self) -> None:
        # Build 10 non-TLS raw TCP packets (empty payload)
        packets = []
        for i in range(10):
            pkt = build_synthetic_packet("192.168.1.10", 50000, "93.184.216.34", 80, tcp_payload=b"NOT_TLS_DATA")
            packets.append((1000.0 + i * 0.1, pkt))
        pcap_data = build_synthetic_pcap_bytes(packets)

        stats: dict = {}
        flows = list(
            iter_pcap_flows(
                pcap_data,
                source_id="raw_cap.pcap",
                session_id="s_raw",
                scenario_id="non_doh",
                max_raw_packets=3,
                stats=stats,
                _dpkt_module=self.mock_dpkt,
            )
        )
        self.assertTrue(stats.get("raw_packets_capped"))
        self.assertEqual(stats.get("accepted_packets"), 0)
        self.assertLessEqual(stats.get("raw_packets_read"), 4)


if __name__ == "__main__":
    unittest.main()
