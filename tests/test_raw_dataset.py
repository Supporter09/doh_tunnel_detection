"""Unit tests for raw PCAP dataset discovery, nested ZIP archives, metadata, and labels."""

import hashlib
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from doh_reproduction.clumping import Clump, Packet
from doh_reproduction.pcap import FlowKey, FlowRecord
from doh_reproduction.raw_dataset import (
    CaptureSource,
    audit_capture_sources,
    derive_capture_metadata,
    discover_capture_sources,
    labels_for_flow,
)


class TestMetadataDerivation(unittest.TestCase):
    """Verify scenario, session, category, and malicious flag extraction."""

    def test_nondoh_scenarios(self) -> None:
        chrome_meta = derive_capture_metadata("raw/NonDoH/chrome_https_01.pcap")
        self.assertEqual(chrome_meta["category"], "non_doh")
        self.assertEqual(chrome_meta["scenario_id"], "non_doh_chrome")
        self.assertFalse(chrome_meta["is_malicious"])
        self.assertEqual(chrome_meta["session_id"], "chrome_https_01")

        firefox_meta = derive_capture_metadata("NonDoH/firefox_session_b.pcapng")
        self.assertEqual(firefox_meta["category"], "non_doh")
        self.assertEqual(firefox_meta["scenario_id"], "non_doh_firefox")
        self.assertFalse(firefox_meta["is_malicious"])

        video_meta = derive_capture_metadata("NonDoH/video_download_03.pcap")
        self.assertEqual(video_meta["scenario_id"], "non_doh_video")

    def test_benign_doh_scenarios(self) -> None:
        cf_meta = derive_capture_metadata("raw/BenignDoH/cloudflare_doh_session1.pcap")
        self.assertEqual(cf_meta["category"], "benign_doh")
        self.assertEqual(cf_meta["scenario_id"], "benign_doh_cloudflare")
        self.assertFalse(cf_meta["is_malicious"])

        firefox_doh = derive_capture_metadata("BenignDoH/firefox_google_doh_02.pcap")
        self.assertEqual(firefox_doh["category"], "benign_doh")
        self.assertEqual(firefox_doh["scenario_id"], "benign_doh_firefox")
        self.assertFalse(firefox_doh["is_malicious"])

        # Combined BenignDoH-NonDoH captures must retain benign_doh category
        combined_ff = derive_capture_metadata(
            "BenignDoH_NonDoH-Firefox-CloudFlare/session_01.pcap"
        )
        self.assertEqual(combined_ff["category"], "benign_doh")
        self.assertEqual(combined_ff["scenario_id"], "benign_doh_firefox")
        self.assertFalse(combined_ff["is_malicious"])

        combined_chrome = derive_capture_metadata(
            "BenignDoH_NonDoH-Chrome-Google/capture_02.pcap"
        )
        self.assertEqual(combined_chrome["category"], "benign_doh")
        self.assertEqual(combined_chrome["scenario_id"], "benign_doh_chrome")
        self.assertFalse(combined_chrome["is_malicious"])

        combined_cf = derive_capture_metadata(
            "BenignDoH_NonDoH-CloudFlare/session_03.pcap"
        )
        self.assertEqual(combined_cf["category"], "benign_doh")
        self.assertEqual(combined_cf["scenario_id"], "benign_doh_cloudflare")
        self.assertFalse(combined_cf["is_malicious"])

    def test_malicious_doh_scenarios(self) -> None:
        iodine = derive_capture_metadata("MaliciousDoH/iodine_tunnel_test.pcap")
        self.assertEqual(iodine["category"], "malicious_doh")
        self.assertEqual(iodine["scenario_id"], "malicious_doh_iodine")
        self.assertTrue(iodine["is_malicious"])

        dns2tcp = derive_capture_metadata("MaliciousDoH/dns2tcp_session04.pcapng")
        self.assertEqual(dns2tcp["scenario_id"], "malicious_doh_dns2tcp")
        self.assertTrue(dns2tcp["is_malicious"])

        dnscat2 = derive_capture_metadata("MaliciousDoH/dnscat2_exfil_chunk.pcap")
        self.assertEqual(dnscat2["scenario_id"], "malicious_doh_dnscat2")
        self.assertTrue(dnscat2["is_malicious"])


class TestDiscoveryAndNestedZipStreaming(unittest.TestCase):
    """Verify discovery of standalone files, ZIP members, and nested ZIP archives."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        # 1. Standalone PCAP
        self.standalone_pcap = self.root / "NonDoH" / "chrome_01.pcap"
        self.standalone_pcap.parent.mkdir(parents=True, exist_ok=True)
        self.standalone_pcap_content = b"STANDALONE_PCAP_BYTES_123456"
        self.standalone_pcap.write_bytes(self.standalone_pcap_content)

        # 2. Outer ZIP containing a direct PCAP and a nested ZIP
        self.direct_zip_pcap_content = b"DIRECT_ZIP_PCAP_BYTES_789"
        self.nested_zip_pcap_content = b"NESTED_ZIP_PCAP_BYTES_ABCDEF"

        # Create nested ZIP in memory
        nested_zip_buffer = io.BytesIO()
        with zipfile.ZipFile(nested_zip_buffer, "w") as inner_zf:
            inner_zf.writestr(
                "MaliciousDoH/iodine_inner.pcap", self.nested_zip_pcap_content
            )
        nested_zip_bytes = nested_zip_buffer.getvalue()

        # Create outer ZIP on disk
        self.outer_zip = self.root / "captures_bundle.zip"
        with zipfile.ZipFile(self.outer_zip, "w") as outer_zf:
            outer_zf.writestr(
                "BenignDoH/firefox_doh.pcap", self.direct_zip_pcap_content
            )
            outer_zf.writestr("inner_archive.zip", nested_zip_bytes)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_discovery_finds_all_sources(self) -> None:
        sources = discover_capture_sources(self.root)
        self.assertEqual(len(sources), 3)

        source_ids = [s.source_id for s in sources]
        self.assertIn("NonDoH/chrome_01.pcap", source_ids)
        self.assertIn("captures_bundle.zip:BenignDoH/firefox_doh.pcap", source_ids)
        self.assertIn(
            "captures_bundle.zip:inner_archive.zip/MaliciousDoH/iodine_inner.pcap",
            source_ids,
        )
    def test_streaming_without_disk_extraction(self) -> None:
        sources = discover_capture_sources(self.root)
        source_map = {s.source_id: s for s in sources}

        # 1. Standalone stream
        src_standalone = source_map["NonDoH/chrome_01.pcap"]
        with src_standalone.open_stream() as s:
            content = s.read()
            self.assertEqual(content, self.standalone_pcap_content)
        # 2. Direct ZIP member stream
        src_direct_zip = source_map["captures_bundle.zip:BenignDoH/firefox_doh.pcap"]
        with src_direct_zip.open_stream() as s:
            content = s.read()
            self.assertEqual(content, self.direct_zip_pcap_content)

        # 3. Nested ZIP member stream
        src_nested_zip = source_map[
            "captures_bundle.zip:inner_archive.zip/MaliciousDoH/iodine_inner.pcap"
        ]
        with src_nested_zip.open_stream() as s:
            content = s.read()
            self.assertEqual(content, self.nested_zip_pcap_content)


class TestLabelsForFlow(unittest.TestCase):
    """Verify Layer 1 (resolver IP) and Layer 2 (capture scenario) label mappings."""

    def _make_dummy_flow(self, is_doh: bool, scenario_id: str) -> FlowRecord:
        server_ip = "8.8.8.8" if is_doh else "93.184.216.34"
        return FlowRecord(
            flow_key=FlowKey(
                client_ip="10.0.0.1",
                client_port=50000,
                server_ip=server_ip,
                server_port=443,
            ),
            source_id="dummy.pcap",
            session_id="dummy_session",
            scenario_id=scenario_id,
            start_time=1.0,
            end_time=2.0,
            packets=[Packet(timestamp=1.0, length=60, direction=0)],
            clumps=[Clump(size=60, pkt_count=1, direction=0, duration=0.0, interarrival=0.0)],
            is_doh=is_doh,
        )

    def test_layer1_resolver_labels(self) -> None:
        # Non-DoH flow
        flow_ndoh = self._make_dummy_flow(is_doh=False, scenario_id="non_doh_chrome")
        capture_ndoh = CaptureSource(
            path="web.pcap", category="non_doh", scenario_id="non_doh_chrome"
        )
        labels = labels_for_flow(flow_ndoh, capture_ndoh)
        self.assertEqual(labels["l1_label"], 0)
        self.assertIsNone(labels["l2_label"])  # Non-DoH has no L2 label

        # DoH flow to resolver 8.8.8.8
        flow_doh = self._make_dummy_flow(is_doh=True, scenario_id="benign_doh_google")
        capture_doh = CaptureSource(
            path="doh.pcap", category="benign_doh", scenario_id="benign_doh_google"
        )
        labels = labels_for_flow(flow_doh, capture_doh)
        self.assertEqual(labels["l1_label"], 1)
        self.assertEqual(labels["l2_label"], 0)  # Benign DoH = 0

    def test_layer2_malicious_tunnel_labels(self) -> None:
        # Malicious DoH flow to resolver 8.8.8.8
        flow_mal = self._make_dummy_flow(is_doh=True, scenario_id="malicious_doh_iodine")
        capture_mal = CaptureSource(
            path="iodine.pcap",
            category="malicious_doh",
            scenario_id="malicious_doh_iodine",
            is_malicious=True,
        )
        labels = labels_for_flow(flow_mal, capture_mal)
        self.assertEqual(labels["l1_label"], 1)
        self.assertEqual(labels["l2_label"], 1)  # Malicious DoH = 1


    def test_combined_benign_nondoh_capture_labels(self) -> None:
        """Combined BenignDoH-NonDoH captures produce benign L2 only for resolver flows."""
        capture = CaptureSource(
            path="BenignDoH_NonDoH-Firefox-CloudFlare/session_01.pcap",
            category="benign_doh",
            scenario_id="benign_doh_firefox",
            is_malicious=False,
        )

        # Web browsing flow in combined capture (not to DoH resolver)
        flow_web = self._make_dummy_flow(is_doh=False, scenario_id="benign_doh_firefox")
        labels_web = labels_for_flow(flow_web, capture)
        self.assertEqual(labels_web["l1_label"], 0)
        self.assertIsNone(labels_web["l2_label"])

        # DoH query flow in combined capture (to DoH resolver IP)
        flow_doh = self._make_dummy_flow(is_doh=True, scenario_id="benign_doh_firefox")
        labels_doh = labels_for_flow(flow_doh, capture)
        self.assertEqual(labels_doh["l1_label"], 1)
        self.assertEqual(labels_doh["l2_label"], 0)

class TestAuditCaptureSources(unittest.TestCase):
    """Verify inventory audit dictionary generation for pcap_audit.json."""

    def test_audit_inventory_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pcap1 = root / "NonDoH" / "browsing_01.pcap"
            pcap1.parent.mkdir(parents=True, exist_ok=True)
            content1 = b"CONTENT_FOR_PCAP_ONE"
            pcap1.write_bytes(content1)
            hash1 = hashlib.sha256(content1).hexdigest()

            audit = audit_capture_sources(root, compute_hashes=True)
            self.assertEqual(audit["total_sources"], 1)
            self.assertEqual(audit["total_bytes"], len(content1))
            self.assertEqual(audit["category_counts"]["non_doh"], 1)
            self.assertEqual(audit["scenario_counts"]["non_doh_browsing"], 1)

            src_rec = audit["sources"][0]
            self.assertEqual(src_rec["source_id"], "NonDoH/browsing_01.pcap")
            self.assertEqual(src_rec["sha256"], hash1)


class TestSymlinkContainmentAndRejection(unittest.TestCase):
    """Behavioral tests verifying symlink rejection and resolved root containment."""

    def test_symlink_inside_dataset_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            real_dir = root / "real"
            real_dir.mkdir()
            real_file = real_dir / "legit.pcap"
            real_file.write_bytes(b"LEGIT_PCAP_DATA")

            # Target outside root
            outside_dir = Path(tempfile.gettempdir())
            outside_file = outside_dir / "external_target.pcap"
            outside_file.write_bytes(b"OUTSIDE_SECRET_DATA")
            try:
                # Create symlink pointing outside root
                link_file = root / "escaped.pcap"
                os.symlink(outside_file, link_file)

                sources = discover_capture_sources(root)
                source_paths = [s.path for s in sources]

                # Legit file should be discovered; symlink pointing outside must be skipped
                self.assertEqual(len(sources), 1)
                self.assertIn(str(real_file), source_paths[0])
            finally:
                if outside_file.exists():
                    outside_file.unlink()

    def test_symlink_capture_source_open_stream_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            real_file = root / "real.pcap"
            real_file.write_bytes(b"SOME_PCAP_BYTES")

            link_file = root / "symlink.pcap"
            os.symlink(real_file, link_file)

            src = CaptureSource(path=str(link_file), root_dir=str(root))
            with self.assertRaises(ValueError) as ctx:
                with src.open_stream():
                    pass
            self.assertIn("Symlinks are prohibited", str(ctx.exception))

    def test_root_containment_escape_rejected_at_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
            root1 = Path(tmpdir1)
            root2 = Path(tmpdir2)
            outside_file = root2 / "outside.pcap"
            outside_file.write_bytes(b"DATA")

            src = CaptureSource(path=str(outside_file), root_dir=str(root1))
            with self.assertRaises(ValueError) as ctx:
                with src.open_stream():
                    pass
            self.assertIn("Path escape detected", str(ctx.exception))


class TestZipBombRejection(unittest.TestCase):
    """Behavioral tests verifying metadata-level rejection of oversized/high-ratio ZIP members."""

    def test_oversized_member_rejected_before_decompression(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            zip_path = root / "oversized.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("large.pcap", b"X" * 1000)

            # Fail closed before decompressing an oversized member.
            with self.assertRaises(ValueError):
                discover_capture_sources(root, max_member_bytes=500)

    def test_high_compression_ratio_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            zip_path = root / "ratio_bomb.zip"
            # Repeated byte string compresses exceptionally well with DEFLATED
            data = b"0" * 200000
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("bomb.pcap", data)

            # Fail closed before decompressing a suspicious-ratio member.
            with self.assertRaises(ValueError):
                discover_capture_sources(root, max_compression_ratio=5.0)

    def test_spooled_nested_zip_byte_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Create inner zip
            inner_buf = io.BytesIO()
            with zipfile.ZipFile(inner_buf, "w") as inner_zf:
                inner_zf.writestr("inner.pcap", b"INNER_BYTES")
            inner_bytes = inner_buf.getvalue()

            outer_path = root / "outer.zip"
            with zipfile.ZipFile(outer_path, "w") as outer_zf:
                outer_zf.writestr("nested.zip", inner_bytes)

            # Nested archive containers have an independent bound.
            with self.assertRaises(ValueError):
                discover_capture_sources(
                    root,
                    max_nested_archive_bytes=len(inner_bytes) - 1,
                )


class TestDiscoveryMaxSourcesEarlyStop(unittest.TestCase):
    """Behavioral tests verifying early discovery stop at max_capture_members."""

    def test_discovery_stops_at_max_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for i in range(5):
                p = root / f"capture_{i:02d}.pcap"
                p.write_bytes(f"DATA_{i}".encode("utf-8"))

            sources = discover_capture_sources(root, max_capture_members=2)
            self.assertEqual(len(sources), 2, "Discovery must stop at exactly max_capture_members")

            audit = audit_capture_sources(root, max_sources=2)
            self.assertEqual(audit["total_sources"], 2)
            self.assertTrue(audit["is_capped_run"])
            self.assertTrue(audit["audit_counters"]["truncated_due_to_max_sources"])


class TestStandaloneSizeCap(unittest.TestCase):
    """Behavioral test verifying standalone capture size bound before open/stat/hashing."""

    def test_standalone_capture_oversized_rejected_at_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pcap_file = root / "huge.pcap"
            pcap_file.write_bytes(b"A" * 1000)

            with self.assertRaises(ValueError) as ctx:
                discover_capture_sources(root, max_standalone_capture_bytes=500)
            self.assertIn("exceeds limit", str(ctx.exception))

    def test_standalone_capture_oversized_rejected_at_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pcap_file = root / "huge.pcap"
            pcap_file.write_bytes(b"A" * 1000)

            src = CaptureSource(
                path=str(pcap_file),
                root_dir=str(root),
                max_standalone_capture_bytes=500,
            )
            with self.assertRaises(ValueError) as ctx:
                with src.open_stream():
                    pass
            self.assertIn("exceeds limit", str(ctx.exception))


class TestSharedNestedAggregateCap(unittest.TestCase):
    """Behavioral test verifying shared cumulative expansion budget across nested archives."""

    def test_shared_expansion_budget_not_reset_across_nested_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Nested archive 1 contains 600 bytes
            buf1 = io.BytesIO()
            with zipfile.ZipFile(buf1, "w") as z1:
                z1.writestr("pcap1.pcap", b"X" * 600)
            # Nested archive 2 contains 600 bytes
            buf2 = io.BytesIO()
            with zipfile.ZipFile(buf2, "w") as z2:
                z2.writestr("pcap2.pcap", b"Y" * 600)

            outer_path = root / "outer.zip"
            with zipfile.ZipFile(outer_path, "w") as z_out:
                z_out.writestr("nested1.zip", buf1.getvalue())
                z_out.writestr("nested2.zip", buf2.getvalue())

            # Budget is 1000 bytes. Neither nested1 (600) nor nested2 (600) exceeds 1000 individually,
            # but combined (1200) exceeds 1000. It must fail closed without resetting per archive!
            with self.assertRaises(ValueError) as ctx:
                discover_capture_sources(
                    root,
                    max_nested_archive_bytes=10000,
                    max_member_bytes=10000,
                    max_total_uncompressed_bytes=1000,
                )
            self.assertIn("Aggregate uncompressed archive expansion budget exceeded", str(ctx.exception))


class TestDuplicateBasenameIDs(unittest.TestCase):
    """Behavioral test verifying normalized root-relative source IDs and collision rejection."""

    def test_different_directories_same_basename_have_distinct_source_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sub1 = root / "scenario_a"
            sub2 = root / "scenario_b"
            sub1.mkdir()
            sub2.mkdir()
            (sub1 / "capture.pcap").write_bytes(b"DATA_A")
            (sub2 / "capture.pcap").write_bytes(b"DATA_B")

            sources = discover_capture_sources(root)
            self.assertEqual(len(sources), 2)
            source_ids = {s.source_id for s in sources}
            self.assertEqual(source_ids, {"scenario_a/capture.pcap", "scenario_b/capture.pcap"})


if __name__ == "__main__":
    unittest.main()
