"""Raw PCAP corpus discovery, streaming member access, metadata derivation, and audit.

Supports nested ZIP archives without extracting to disk, derives scenario and
session provenance for group-disjoint evaluation, assigns resolver-IP-based L1
and capture-based L2 labels, and generates structured audit records.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

from .pcap import FlowRecord

DEFAULT_MAX_STANDALONE_CAPTURE_BYTES: int = 20 * 1024 * 1024 * 1024  # 20 GB
DEFAULT_MAX_MEMBER_BYTES: int = 10 * 1024 * 1024 * 1024  # 10 GB (for PCAP members)
DEFAULT_MAX_NESTED_ARCHIVE_BYTES: int = 25 * 1024 * 1024 * 1024  # 25 GB (for container ZIPs)
DEFAULT_MAX_ZIP_CUMULATIVE_BYTES: int = 200 * 1024 * 1024 * 1024  # 200 GB (shared cumulative)
DEFAULT_MAX_COMPRESSION_RATIO: float = 100.0
DEFAULT_CHUNK_SIZE: int = 65536  # 64 KB


class _CumulativeBudgetTracker:
    """Shares one uncompressed expansion budget across outer and all nested archives."""

    def __init__(self, max_total_bytes: int) -> None:
        self.max_total_bytes = max_total_bytes
        self.charged_bytes = 0

    def charge(self, num_bytes: int, name: str = "") -> None:
        if self.charged_bytes + num_bytes > self.max_total_bytes:
            raise ValueError(
                f"Aggregate uncompressed archive expansion budget exceeded: "
                f"{self.charged_bytes + num_bytes} > {self.max_total_bytes} bytes "
                f"(rejected item '{name}')"
            )
        self.charged_bytes += num_bytes

def _validate_zip_member(
    info: zipfile.ZipInfo,
    *,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
) -> None:
    """Validate ZIP member metadata before decompression to defeat zip bombs."""
    if info.file_size > max_member_bytes:
        raise ValueError(
            f"ZIP member '{info.filename}' uncompressed size ({info.file_size} bytes) "
            f"exceeds limit ({max_member_bytes} bytes)"
        )
    if info.compress_size > 0:
        ratio = info.file_size / info.compress_size
        if ratio > max_compression_ratio:
            raise ValueError(
                f"ZIP member '{info.filename}' compression ratio ({ratio:.1f}) "
                f"exceeds maximum allowed ratio ({max_compression_ratio})"
            )
    elif info.file_size > 1024:
        raise ValueError(
            f"ZIP member '{info.filename}' declares 0 compressed bytes but {info.file_size} uncompressed bytes"
        )


@dataclass(frozen=True)
class CaptureSource:
    """Represents a discoverable PCAP/PCAPNG capture artifact.

    Can refer to a standalone file on disk, a direct member of a ZIP archive,
    or a member inside a nested ZIP archive. Streaming access is provided via
    `open_stream()` without full-corpus disk extraction.
    """

    path: str
    member_name: str | None = None
    container_path: str | None = None
    nested_member_name: str | None = None
    scenario_id: str = "unknown"
    session_id: str = "unknown"
    is_malicious: bool = False
    sha256: str | None = None
    size_bytes: int = 0
    category: str = "unknown"  # "non_doh", "benign_doh", "malicious_doh"
    root_dir: str | None = None
    max_standalone_capture_bytes: int = DEFAULT_MAX_STANDALONE_CAPTURE_BYTES
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES
    max_nested_archive_bytes: int = DEFAULT_MAX_NESTED_ARCHIVE_BYTES
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO

    @property
    def source_id(self) -> str:
        """Globally unique, deterministic, root-relative provenance identifier."""
        if self.root_dir:
            try:
                rel_container = os.path.relpath(self.container_path, self.root_dir).replace("\\", "/") if self.container_path else ""
            except ValueError:
                rel_container = os.path.basename(self.container_path) if self.container_path else ""
            try:
                rel_path = os.path.relpath(self.path, self.root_dir).replace("\\", "/")
            except ValueError:
                rel_path = os.path.basename(self.path)
        else:
            rel_container = os.path.basename(self.container_path) if self.container_path else ""
            rel_path = os.path.basename(self.path)

        if self.container_path and self.member_name:
            norm_member = self.member_name.strip("/").replace("\\", "/")
            if self.nested_member_name:
                norm_nested = self.nested_member_name.strip("/").replace("\\", "/")
                return f"{rel_container}:{norm_member}/{norm_nested}"
            return f"{rel_container}:{norm_member}"
        return rel_path

    @contextmanager
    def open_stream(self) -> Iterator[io.IOBase]:
        """Stream binary packet capture bytes without extracting archives to disk."""
        target_path = self.container_path if (self.container_path and self.member_name) else self.path

        # Symlink and regular-file validation
        if os.path.islink(target_path):
            raise ValueError(f"Symlinks are prohibited for capture sources: {target_path}")
        mode = os.lstat(target_path).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError(f"Target capture is not a regular file: {target_path}")

        # Dataset root containment check
        if self.root_dir is not None:
            resolved_root = Path(self.root_dir).resolve()
            resolved_target = Path(target_path).resolve()
            try:
                resolved_target.relative_to(resolved_root)
            except ValueError:
                raise ValueError(
                    f"Path escape detected: {target_path} resolves outside dataset root {self.root_dir}"
                )

        if self.container_path is None or self.member_name is None:
            file_size = os.path.getsize(self.path)
            if file_size > self.max_standalone_capture_bytes:
                raise ValueError(
                    f"Standalone capture '{self.path}' ({file_size} bytes) exceeds limit ({self.max_standalone_capture_bytes} bytes)"
                )
            with open(self.path, "rb") as f:
                yield f
        else:
            with zipfile.ZipFile(self.container_path, "r") as zf:
                info = zf.getinfo(self.member_name)
                if self.nested_member_name:
                    # Validate container limits for nested ZIP member
                    _validate_zip_member(
                        info,
                        max_member_bytes=self.max_nested_archive_bytes,
                        max_compression_ratio=self.max_compression_ratio,
                    )
                    # Spool nested zip member in bounded chunks to a seekable temporary file
                    with tempfile.TemporaryFile() as tmp:
                        with zf.open(self.member_name, "r") as member_stream:
                            bytes_written = 0
                            while chunk := member_stream.read(DEFAULT_CHUNK_SIZE):
                                bytes_written += len(chunk)
                                if bytes_written > self.max_nested_archive_bytes:
                                    raise ValueError(
                                        f"Nested ZIP {self.member_name} exceeded hard byte cap ({self.max_nested_archive_bytes} bytes)"
                                    )
                                tmp.write(chunk)
                        tmp.flush()
                        tmp.seek(0)
                        with zipfile.ZipFile(tmp, "r") as inner_zf:
                            inner_info = inner_zf.getinfo(self.nested_member_name)
                            _validate_zip_member(
                                inner_info,
                                max_member_bytes=self.max_member_bytes,
                                max_compression_ratio=self.max_compression_ratio,
                            )
                            with inner_zf.open(self.nested_member_name, "r") as inner_file:
                                yield inner_file
                else:
                    _validate_zip_member(
                        info,
                        max_member_bytes=self.max_member_bytes,
                        max_compression_ratio=self.max_compression_ratio,
                    )
                    with zf.open(self.member_name, "r") as member_file:
                        yield member_file
    def compute_sha256(self) -> str:
        """Compute SHA-256 checksum by streaming chunks with bounded memory."""
        if self.container_path is None or self.member_name is None:
            file_size = os.path.getsize(self.path)
            if file_size > self.max_standalone_capture_bytes:
                raise ValueError(
                    f"Standalone capture '{self.path}' ({file_size} bytes) exceeds limit ({self.max_standalone_capture_bytes} bytes)"
                )
        hasher = hashlib.sha256()
        with self.open_stream() as stream:
            while chunk := stream.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()


def derive_capture_metadata(path_or_name: str | os.PathLike) -> dict[str, Any]:
    """Derive scenario_id, session_id, category, and malicious flag from capture path.

    Adheres to CIRA-CIC-DoHBrw-2020 layout semantics:
      - MaliciousDoH / malicious / iodine / dns2tcp / dnscat2 -> malicious_doh (category),
        malicious_doh_<tool> (scenario_id), is_malicious=True
      - BenignDoH / benign / combined BenignDoH_NonDoH -> benign_doh (category),
        benign_doh_<browser|resolver> (scenario_id), is_malicious=False
      - NonDoH / ndoh -> non_doh (category), non_doh_<app> (scenario_id), is_malicious=False
    """
    raw_str = str(path_or_name).replace("\\", "/")
    norm = raw_str.lower()

    # 1. Determine category and scenario_id
    if any(m in norm for m in ("malicious", "iodine", "dns2tcp", "dnscat2")):
        category = "malicious_doh"
        is_malicious = True
        if "iodine" in norm:
            tool = "iodine"
        elif "dns2tcp" in norm:
            tool = "dns2tcp"
        elif "dnscat2" in norm:
            tool = "dnscat2"
        else:
            tool = "tunnel"
        scenario_id = f"malicious_doh_{tool}"

    elif "benign" in norm:
        category = "benign_doh"
        is_malicious = False
        if "firefox" in norm:
            browser = "firefox"
        elif "chrome" in norm:
            browser = "chrome"
        elif "google" in norm:
            browser = "google"
        elif "cloudflare" in norm:
            browser = "cloudflare"
        elif "adguard" in norm:
            browser = "adguard"
        elif "quad9" in norm:
            browser = "quad9"
        else:
            browser = "browsing"
        scenario_id = f"benign_doh_{browser}"

    elif any(nd in norm for nd in ("nondoh", "non_doh", "non-doh", "non doh")) or re.search(r"(?<!benig)ndoh", norm):
        category = "non_doh"
        is_malicious = False
        if "firefox" in norm:
            app = "firefox"
        elif "chrome" in norm:
            app = "chrome"
        elif "video" in norm:
            app = "video"
        elif "download" in norm:
            app = "download"
        else:
            app = "browsing"
        scenario_id = f"non_doh_{app}"

    elif "doh" in norm:
        category = "benign_doh"
        is_malicious = False
        if "firefox" in norm:
            browser = "firefox"
        elif "chrome" in norm:
            browser = "chrome"
        elif "google" in norm:
            browser = "google"
        elif "cloudflare" in norm:
            browser = "cloudflare"
        elif "adguard" in norm:
            browser = "adguard"
        elif "quad9" in norm:
            browser = "quad9"
        else:
            browser = "browsing"
        scenario_id = f"benign_doh_{browser}"

    else:
        category = "non_doh"
        is_malicious = False
        scenario_id = "non_doh_unknown"

    # 2. Derive unique session_id for group/session-disjoint splitting
    # Uses capture file stem or scenario + numeric session indicator
    base_name = os.path.basename(raw_str)
    stem = os.path.splitext(base_name)[0]
    # Remove nested .pcap if filename was like capture.pcap.gz
    if stem.endswith((".pcap", ".pcapng", ".cap")):
        stem = os.path.splitext(stem)[0]

    # Clean stem of invalid identifier characters
    clean_stem = re.sub(r"[^a-zA-Z0-9_\-]", "_", stem)
    parent_name = os.path.basename(os.path.dirname(raw_str))
    if parent_name and parent_name not in (".", "") and len(clean_stem) < 6:
        clean_parent = re.sub(r"[^a-zA-Z0-9_\-]", "_", parent_name)
        session_id = f"{clean_parent}_{clean_stem}"
    else:
        session_id = clean_stem

    return {
        "scenario_id": scenario_id,
        "session_id": session_id,
        "is_malicious": is_malicious,
        "category": category,
    }


def discover_capture_sources(
    root: str | os.PathLike,
    *,
    max_capture_members: int | None = None,
    max_standalone_capture_bytes: int = DEFAULT_MAX_STANDALONE_CAPTURE_BYTES,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_nested_archive_bytes: int = DEFAULT_MAX_NESTED_ARCHIVE_BYTES,
    max_total_uncompressed_bytes: int = DEFAULT_MAX_ZIP_CUMULATIVE_BYTES,
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
) -> list[CaptureSource]:
    """Scan root directory or archive and return a deterministic list of CaptureSources.

    Recursively discovers standalone .pcap / .pcapng files, members inside .zip archives,
    and members inside nested .zip archives without extracting archives to disk.
    Enforces symlink rejection, dataset root containment, zip bomb guards, duplicate
    source ID rejection, and standalone size limits.
    """
    if os.path.islink(root):
        raise ValueError(f"Dataset root cannot be a symlink: {root}")

    root_path = Path(root).resolve()
    sources: list[CaptureSource] = []
    budget_tracker = _CumulativeBudgetTracker(max_total_bytes=max_total_uncompressed_bytes)
    seen_source_ids: set[str] = set()

    def add_source(src: CaptureSource) -> None:
        sid = src.source_id
        if sid in seen_source_ids:
            raise ValueError(f"Duplicate capture source ID detected: '{sid}'")
        seen_source_ids.add(sid)
        sources.append(src)

    if not root_path.exists():
        return sources

    root_dir_str = str(root_path.parent if root_path.is_file() else root_path)

    # Direct file case
    if root_path.is_file():
        mode = os.lstat(root).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError(f"Dataset root file is not a regular file: {root}")

        name_lower = root_path.name.lower()
        if name_lower.endswith((".pcap", ".pcapng", ".cap")):
            size = root_path.stat().st_size
            if size > max_standalone_capture_bytes:
                raise ValueError(
                    f"Standalone capture '{root_path}' ({size} bytes) exceeds limit ({max_standalone_capture_bytes} bytes)"
                )
            meta = derive_capture_metadata(root_path)
            src = CaptureSource(
                path=str(root_path),
                root_dir=root_dir_str,
                size_bytes=size,
                max_standalone_capture_bytes=max_standalone_capture_bytes,
                max_member_bytes=max_member_bytes,
                max_nested_archive_bytes=max_nested_archive_bytes,
                max_compression_ratio=max_compression_ratio,
                **meta,
            )
            add_source(src)
            return sources
        elif name_lower.endswith(".zip"):
            _scan_zip_archive(
                root_path,
                sources=sources,
                budget_tracker=budget_tracker,
                seen_source_ids=seen_source_ids,
                max_capture_members=max_capture_members,
                max_standalone_capture_bytes=max_standalone_capture_bytes,
                max_member_bytes=max_member_bytes,
                max_nested_archive_bytes=max_nested_archive_bytes,
                max_compression_ratio=max_compression_ratio,
                root_dir=root_dir_str,
            )
            sources.sort(key=lambda s: s.source_id)
            return sources

    # Directory walk case
    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
        # Prune symlinked directories to prevent descending outside root
        dirnames[:] = [d for d in sorted(dirnames) if not (Path(dirpath) / d).is_symlink()]

        for fname in sorted(filenames):
            if max_capture_members is not None and len(sources) >= max_capture_members:
                break

            fpath = Path(dirpath) / fname
            if fpath.is_symlink() or os.path.islink(fpath):
                continue

            try:
                mode = os.lstat(fpath).st_mode
                if not stat.S_ISREG(mode):
                    continue
            except OSError:
                continue

            # Containment check
            try:
                fpath.resolve().relative_to(root_path)
            except ValueError:
                continue

            name_lower = fname.lower()
            if name_lower.endswith((".pcap", ".pcapng", ".cap")):
                size = fpath.stat().st_size
                if size > max_standalone_capture_bytes:
                    raise ValueError(
                        f"Standalone capture '{fpath}' ({size} bytes) exceeds limit ({max_standalone_capture_bytes} bytes)"
                    )
                meta = derive_capture_metadata(fpath)
                src = CaptureSource(
                    path=str(fpath),
                    root_dir=root_dir_str,
                    size_bytes=size,
                    max_standalone_capture_bytes=max_standalone_capture_bytes,
                    max_member_bytes=max_member_bytes,
                    max_nested_archive_bytes=max_nested_archive_bytes,
                    max_compression_ratio=max_compression_ratio,
                    **meta,
                )
                add_source(src)
            elif name_lower.endswith(".zip"):
                _scan_zip_archive(
                    fpath,
                    sources=sources,
                    budget_tracker=budget_tracker,
                    seen_source_ids=seen_source_ids,
                    max_capture_members=max_capture_members,
                    max_standalone_capture_bytes=max_standalone_capture_bytes,
                    max_member_bytes=max_member_bytes,
                    max_nested_archive_bytes=max_nested_archive_bytes,
                    max_compression_ratio=max_compression_ratio,
                    root_dir=root_dir_str,
                )

        if max_capture_members is not None and len(sources) >= max_capture_members:
            break

    sources.sort(key=lambda s: s.source_id)
    if max_capture_members is not None and len(sources) > max_capture_members:
        sources = sources[:max_capture_members]
    return sources

def _scan_zip_archive(
    zip_path: Path,
    sources: list[CaptureSource],
    budget_tracker: _CumulativeBudgetTracker,
    seen_source_ids: set[str],
    *,
    max_capture_members: int | None = None,
    max_standalone_capture_bytes: int = DEFAULT_MAX_STANDALONE_CAPTURE_BYTES,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_nested_archive_bytes: int = DEFAULT_MAX_NESTED_ARCHIVE_BYTES,
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
    root_dir: str | None = None,
) -> None:
    """Inspect ZIP archive central directory without extracting contents."""
    if os.path.islink(zip_path):
        return
    try:
        mode = os.lstat(zip_path).st_mode
        if not stat.S_ISREG(mode):
            return
    except OSError:
        return

    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if max_capture_members is not None and len(sources) >= max_capture_members:
                break

            info_name_lower = info.filename.lower()
            if info_name_lower.endswith((".pcap", ".pcapng", ".cap")):
                _validate_zip_member(
                    info,
                    max_member_bytes=max_member_bytes,
                    max_compression_ratio=max_compression_ratio,
                )
                budget_tracker.charge(info.file_size, info.filename)
                meta = derive_capture_metadata(info.filename)
                src = CaptureSource(
                    path=str(zip_path),
                    member_name=info.filename,
                    container_path=str(zip_path),
                    size_bytes=info.file_size,
                    root_dir=root_dir,
                    max_standalone_capture_bytes=max_standalone_capture_bytes,
                    max_member_bytes=max_member_bytes,
                    max_nested_archive_bytes=max_nested_archive_bytes,
                    max_compression_ratio=max_compression_ratio,
                    **meta,
                )
                sid = src.source_id
                if sid in seen_source_ids:
                    raise ValueError(f"Duplicate capture source ID detected: '{sid}'")
                seen_source_ids.add(sid)
                sources.append(src)

            elif info_name_lower.endswith(".zip"):
                _validate_zip_member(
                    info,
                    max_member_bytes=max_nested_archive_bytes,
                    max_compression_ratio=max_compression_ratio,
                )
                # Spool nested zip archive via bounded tempfile spooling (NEVER wholly in RAM)
                with tempfile.TemporaryFile() as tmp:
                    with zf.open(info.filename, "r") as member_stream:
                        bytes_written = 0
                        while chunk := member_stream.read(DEFAULT_CHUNK_SIZE):
                            bytes_written += len(chunk)
                            if bytes_written > max_nested_archive_bytes:
                                raise ValueError(
                                    f"Nested ZIP '{info.filename}' exceeded container limit ({max_nested_archive_bytes} bytes)"
                                )
                            tmp.write(chunk)
                    tmp.flush()
                    tmp.seek(0)

                    with zipfile.ZipFile(tmp, "r") as inner_zf:
                        for inner_info in inner_zf.infolist():
                            if inner_info.is_dir():
                                continue
                            if max_capture_members is not None and len(sources) >= max_capture_members:
                                break
                            inner_lower = inner_info.filename.lower()
                            if inner_lower.endswith((".pcap", ".pcapng", ".cap")):
                                _validate_zip_member(
                                    inner_info,
                                    max_member_bytes=max_member_bytes,
                                    max_compression_ratio=max_compression_ratio,
                                )
                                budget_tracker.charge(inner_info.file_size, f"{info.filename}/{inner_info.filename}")
                                combined_virtual_path = f"{info.filename}/{inner_info.filename}"
                                meta = derive_capture_metadata(combined_virtual_path)
                                src = CaptureSource(
                                    path=str(zip_path),
                                    member_name=info.filename,
                                    container_path=str(zip_path),
                                    nested_member_name=inner_info.filename,
                                    size_bytes=inner_info.file_size,
                                    root_dir=root_dir,
                                    max_standalone_capture_bytes=max_standalone_capture_bytes,
                                    max_member_bytes=max_member_bytes,
                                    max_nested_archive_bytes=max_nested_archive_bytes,
                                    max_compression_ratio=max_compression_ratio,
                                    **meta,
                                )
                                sid = src.source_id
                                if sid in seen_source_ids:
                                    raise ValueError(f"Duplicate capture source ID detected: '{sid}'")
                                seen_source_ids.add(sid)
                                sources.append(src)

def labels_for_flow(
    flow: FlowRecord, capture: CaptureSource | None = None
) -> dict[str, int | None]:
    """Compute Layer 1 and Layer 2 ground truth labels for a flow.

    Shared Contract:
      - Layer 1: non_doh=0, doh=1 (determined by DoH resolver IP match).
      - Layer 2: benign_doh=0, malicious_doh=1 (determined by capture scenario provenance).
        Returns None for Layer 2 when the flow is non-DoH.
    """
    # Layer 1: Resolver-IP based
    is_doh = flow.is_doh
    l1_label = 1 if is_doh else 0

    # Layer 2: Benign DoH (0) vs Malicious DoH Tunnel (1)
    if l1_label == 0:
        l2_label: int | None = None
    else:
        if capture is not None:
            if capture.is_malicious or capture.category == "malicious_doh":
                l2_label = 1
            elif capture.category == "benign_doh":
                l2_label = 0
            else:
                l2_label = None
        else:
            if flow.scenario_id.startswith("malicious"):
                l2_label = 1
            elif flow.scenario_id.startswith("benign"):
                l2_label = 0
            else:
                l2_label = None

    return {"l1_label": l1_label, "l2_label": l2_label}


def audit_capture_sources(
    root: str | os.PathLike,
    *,
    compute_hashes: bool = True,
    max_sources: int | None = None,
    max_standalone_capture_bytes: int = DEFAULT_MAX_STANDALONE_CAPTURE_BYTES,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_nested_archive_bytes: int = DEFAULT_MAX_NESTED_ARCHIVE_BYTES,
    max_total_uncompressed_bytes: int = DEFAULT_MAX_ZIP_CUMULATIVE_BYTES,
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
    sources: Sequence[CaptureSource] | None = None,
) -> dict[str, Any]:
    """Inspect capture inventory under root and generate structured audit record.

    Produces audit data matching pcap_audit.json schema, recording member
    provenance, sizes, scenario/session groupings, checksums, and active caps.
    """
    if sources is not None:
        discovered = list(sources)
        if max_sources is not None and max_sources > 0:
            discovered = discovered[:max_sources]
    else:
        discovered = discover_capture_sources(
            root,
            max_capture_members=max_sources,
            max_standalone_capture_bytes=max_standalone_capture_bytes,
            max_member_bytes=max_member_bytes,
            max_nested_archive_bytes=max_nested_archive_bytes,
            max_total_uncompressed_bytes=max_total_uncompressed_bytes,
            max_compression_ratio=max_compression_ratio,
        )
    is_capped = max_sources is not None
    category_counts: dict[str, int] = {"non_doh": 0, "benign_doh": 0, "malicious_doh": 0}
    scenario_counts: dict[str, int] = {}
    session_counts: dict[str, int] = {}
    sources_records: list[dict[str, Any]] = []
    total_bytes = 0

    for src in discovered:
        category_counts[src.category] = category_counts.get(src.category, 0) + 1
        scenario_counts[src.scenario_id] = scenario_counts.get(src.scenario_id, 0) + 1
        session_counts[src.session_id] = session_counts.get(src.session_id, 0) + 1
        total_bytes += src.size_bytes

        sha256_hash = src.sha256
        if sha256_hash is None and compute_hashes:
            try:
                sha256_hash = src.compute_sha256()
            except Exception as exc:
                sha256_hash = f"error: {exc}"

        sources_records.append(
            {
                "source_id": src.source_id,
                "path": src.path,
                "container_path": src.container_path,
                "member_name": src.member_name,
                "nested_member_name": src.nested_member_name,
                "category": src.category,
                "scenario_id": src.scenario_id,
                "session_id": src.session_id,
                "is_malicious": src.is_malicious,
                "size_bytes": src.size_bytes,
                "sha256": sha256_hash,
            }
        )

    return {
        "root": str(root),
        "total_sources": len(discovered),
        "total_capture_sources": len(discovered),
        "total_bytes": total_bytes,
        "total_uncompressed_bytes": total_bytes,
        "category_counts": category_counts,
        "summary_by_category": category_counts,
        "scenario_counts": scenario_counts,
        "session_counts": session_counts,
        "sources": sources_records,
        "capture_sources": sources_records,
        "is_capped_run": is_capped,
        "limits": {
            "max_capture_members": max_sources,
            "max_standalone_capture_bytes": max_standalone_capture_bytes,
            "max_member_bytes": max_member_bytes,
            "max_nested_archive_bytes": max_nested_archive_bytes,
            "max_total_uncompressed_bytes": max_total_uncompressed_bytes,
            "max_compression_ratio": max_compression_ratio,
        },
        "audit_counters": {
            "sources_discovered": len(discovered),
            "total_uncompressed_bytes": total_bytes,
            "truncated_due_to_max_sources": (len(discovered) == max_sources) if max_sources is not None else False,
        },
    }
