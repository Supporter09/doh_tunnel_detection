"""Streaming PCAP/PCAPNG packet decoding and bidirectional TCP flow assembly.

Implements lazy dpkt loading, TLS Application Data filtering (record type 23,
payload >= 40 bytes), 40 s flow expiry, client/server direction assignment,
and conversion to canonical Packet and Clump sequences without exposing raw
IP/port features to downstream models.
"""

from __future__ import annotations

import io
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

from .clumping import Clump, Packet, clumping

# Canonical DoHLyzer resolver IPv4 addresses per meter/constants.py
DOH_RESOLVER_IPS: frozenset[str] = frozenset(
    {
        "8.8.8.8",
        "8.8.4.4",
        "9.9.9.9",
        "9.9.9.10",
        "9.9.9.11",
        "1.1.1.1",
        "1.0.0.1",
        "149.112.112.10",
        "149.112.112.112",
        "176.103.130.130",
        "176.103.130.131",
        "104.16.248.249",
        "104.16.249.249",
    }
)

# Flow timeout in seconds per DoHLyzer EXPIRED_UPDATE = 40
DEFAULT_FLOW_TIMEOUT_SECONDS: float = 40.0

# Minimum TLS application payload bytes per DoHLyzer filter
# (e.g. filters out HTTP/2 PING frame of length 34 and small control frames)
DEFAULT_MIN_TLS_APP_BYTES: int = 40

# TLS Application Data record content type (RFC 5246 / RFC 8446)
TLS_RECORD_APPLICATION_DATA: int = 23


def _get_dpkt() -> Any:
    """Lazy loader for dpkt module with actionable runtime diagnostic."""
    try:
        import dpkt  # type: ignore

        return dpkt
    except ImportError as exc:
        raise RuntimeError(
            "The 'dpkt' library is required to decode PCAP/PCAPNG streams. "
            "Please install it using 'pip install dpkt'."
        ) from exc


@dataclass(frozen=True)
class FlowKey:
    """Bidirectional endpoint identifier for a network flow.

    The first observed packet defines client_ip:client_port as the client
    (forward direction, 0) and server_ip:server_port as the server
    (reverse direction, 1).
    """

    client_ip: str
    client_port: int
    server_ip: str
    server_port: int
    protocol: str = "TCP"

    @property
    def bidi_key(self) -> tuple[tuple[str, int], tuple[str, int], str]:
        """Symmetric key for hash map lookup invariant to client/server order."""
        ep1 = (self.client_ip, self.client_port)
        ep2 = (self.server_ip, self.server_port)
        if ep1 <= ep2:
            return (ep1, ep2, self.protocol)
        return (ep2, ep1, self.protocol)

    def matches_forward(self, src_ip: str, sport: int, dst_ip: str, dport: int) -> bool:
        """True if packet is in client -> server direction (0)."""
        return (
            self.client_ip == src_ip
            and self.client_port == sport
            and self.server_ip == dst_ip
            and self.server_port == dport
        )

    def matches_reverse(self, src_ip: str, sport: int, dst_ip: str, dport: int) -> bool:
        """True if packet is in server -> client direction (1)."""
        return (
            self.server_ip == src_ip
            and self.server_port == sport
            and self.client_ip == dst_ip
            and self.client_port == dport
        )


@dataclass
class FlowRecord:
    """Represents an assembled bidirectional flow and its extracted clumps.

    Strict boundary: Raw IP/ports are stored here for flow isolation, provenance,
    and resolver-based L1 labeling, but are never exposed in clump feature vectors.
    """

    flow_key: FlowKey
    source_id: str
    session_id: str
    scenario_id: str
    start_time: float
    end_time: float
    packets: list[Packet]
    clumps: list[Clump]
    is_doh: bool
    truncated: bool = False

    @property
    def is_truncated(self) -> bool:
        """True if the flow was truncated by packet or byte resource caps."""
        return self.truncated
    @property
    def duration(self) -> float:
        """Total flow duration in seconds."""
        return max(0.0, self.end_time - self.start_time)

    @property
    def packet_count(self) -> int:
        """Total number of accepted TLS application packets."""
        return len(self.packets)

    @property
    def clump_count(self) -> int:
        """Total number of directional packet clumps."""
        return len(self.clumps)


def extract_tls_application_data_bytes(
    payload: bytes, min_bytes: int = DEFAULT_MIN_TLS_APP_BYTES
) -> int | None:
    """Extract total TLS Application Data (type 23) payload bytes from a TCP segment.

    Parses standard TLS record headers:
      - Byte 0: ContentType (20: ChangeCipherSpec, 21: Alert, 22: Handshake, 23: ApplicationData)
      - Bytes 1-2: Protocol Version (major version 3 for SSL 3.0, TLS 1.0, 1.1, 1.2, 1.3)
      - Bytes 3-4: 16-bit unsigned payload length

    Returns total bytes across type 23 records if total >= min_bytes, else None.
    Filters out pure control frames, alerts, handshakes, and short frames (e.g. ping frame = 34).
    """
    if not payload or len(payload) < 5:
        return None

    offset = 0
    total_app_data_bytes = 0
    has_app_data = False
    payload_len = len(payload)

    while offset + 5 <= payload_len:
        content_type = payload[offset]
        major_version = payload[offset + 1]

        # Valid TLS record checks: ContentType 20-24 and major version 3 (SSLv3/TLS1.x)
        if content_type not in (20, 21, 22, 23, 24) or major_version != 3:
            break

        rec_len = int.from_bytes(payload[offset + 3 : offset + 5], "big")
        if rec_len <= 0:
            break

        if content_type == TLS_RECORD_APPLICATION_DATA:
            has_app_data = True
            total_app_data_bytes += rec_len

        offset += 5 + rec_len
        # If payload was truncated/fragmented across TCP segment boundary, record still counted
        if offset > payload_len:
            break

    if has_app_data and total_app_data_bytes >= min_bytes:
        return total_app_data_bytes
    return None


class _ActiveFlowState:
    """Internal accumulator for a bidirectional TCP flow."""

    __slots__ = (
        "flow_key",
        "start_time",
        "latest_timestamp",
        "packets",
        "accepted_packets",
        "accepted_bytes",
        "truncated",
    )

    def __init__(self, flow_key: FlowKey, first_packet_time: float) -> None:
        self.flow_key = flow_key
        self.start_time = first_packet_time
        self.latest_timestamp = first_packet_time
        self.packets: list[Packet] = []
        self.accepted_packets: int = 0
        self.accepted_bytes: int = 0
        self.truncated: bool = False

    def add_packet(
        self,
        ts: float,
        length: int,
        direction: int,
        *,
        max_flow_packets: int | None = None,
        max_flow_bytes: int | None = None,
    ) -> bool:
        if ts > self.latest_timestamp:
            self.latest_timestamp = ts
        if max_flow_packets is not None and self.accepted_packets >= max_flow_packets:
            self.truncated = True
            return False
        if max_flow_bytes is not None and (self.accepted_bytes + length) > max_flow_bytes:
            self.truncated = True
            return False
        self.packets.append(Packet(timestamp=ts, length=length, direction=direction))
        self.accepted_packets += 1
        self.accepted_bytes += length
        return True
    def to_flow_record(
        self, source_id: str, session_id: str, scenario_id: str
    ) -> FlowRecord:
        # Guarantee non-decreasing timestamp ordering for clumping in case of capture jitter
        sorted_packets = sorted(self.packets, key=lambda p: p.timestamp)
        clumps = clumping(sorted_packets) if sorted_packets else []
        is_doh = (
            self.flow_key.server_ip in DOH_RESOLVER_IPS
            or self.flow_key.client_ip in DOH_RESOLVER_IPS
        )
        return FlowRecord(
            flow_key=self.flow_key,
            source_id=source_id,
            session_id=session_id,
            scenario_id=scenario_id,
            start_time=self.start_time,
            end_time=self.latest_timestamp,
            packets=sorted_packets,
            clumps=clumps,
            is_doh=is_doh,
            truncated=self.truncated,
        )


def _parse_packet_ip_tcp(
    buf: bytes, datalink: int, dpkt_mod: Any
) -> tuple[str, int, str, int, bytes, int] | None:
    """Extract (src_ip, sport, dst_ip, dport, tcp_payload, tcp_flags) from raw packet bytes.

    Supports Ethernet (DLT_EN10MB), Linux Cooked v1/v2 (DLT_LINUX_SLL/SLL2),
    and raw IP captures. Returns None if packet is not an IPv4/IPv6 TCP packet.
    """
    ip: Any = None
    try:
        if datalink == 1:  # DLT_EN10MB Ethernet
            eth = dpkt_mod.ethernet.Ethernet(buf)
            ip = eth.data
            while isinstance(ip, getattr(dpkt_mod.ethernet, "VLAN", ())) :
                ip = ip.data
        elif datalink == 113:  # DLT_LINUX_SLL
            sll = dpkt_mod.sll.SLL(buf)
            ip = sll.data
        elif datalink == 276:  # DLT_LINUX_SLL2
            sll2_mod = getattr(dpkt_mod, "sll2", None)
            if sll2_mod and hasattr(sll2_mod, "SLL2"):
                ip = sll2_mod.SLL2(buf).data
            else:
                ip = buf[20:]
        elif datalink in (12, 101):  # DLT_RAW / DLT_RAW_ALT
            ip = buf
        else:
            # Fallback heuristic: check if Ethernet header or raw IP
            try:
                eth = dpkt_mod.ethernet.Ethernet(buf)
                ip = eth.data
            except Exception:
                ip = buf
    except Exception:
        return None

    # Resolve raw byte buffer if ip is not yet parsed
    if isinstance(ip, (bytes, bytearray)):
        if not ip:
            return None
        version = ip[0] >> 4
        try:
            if version == 4:
                ip = dpkt_mod.ip.IP(ip)
            elif version == 6:
                ip = dpkt_mod.ip6.IP6(ip)
            else:
                return None
        except Exception:
            return None

    if not isinstance(ip, (dpkt_mod.ip.IP, dpkt_mod.ip6.IP6)):
        return None

    tcp = ip.data
    if not isinstance(tcp, dpkt_mod.tcp.TCP):
        return None

    try:
        if isinstance(ip, dpkt_mod.ip.IP):
            src_ip = socket.inet_ntoa(ip.src)
            dst_ip = socket.inet_ntoa(ip.dst)
        else:
            src_ip = socket.inet_ntop(socket.AF_INET6, ip.src)
            dst_ip = socket.inet_ntop(socket.AF_INET6, ip.dst)
    except Exception:
        return None

    sport = int(tcp.sport)
    dport = int(tcp.dport)
    payload = bytes(tcp.data)
    flags = int(tcp.flags)
    return (src_ip, sport, dst_ip, dport, payload, flags)


def _open_pcap_reader(stream: io.IOBase, dpkt_mod: Any) -> Any:
    """Instantiate dpkt PCAP or PCAPNG reader detecting header magic."""
    magic = b""
    if hasattr(stream, "seekable") and stream.seekable():
        pos = stream.tell()
        magic = stream.read(4)
        stream.seek(pos)
    elif hasattr(stream, "peek"):
        magic = stream.peek(4)[:4]

    # PCAPNG Section Header Block magic: 0x0A0D0D0A (\n\r\r\n)
    if magic == b"\x0a\x0d\x0d\x0a":
        return dpkt_mod.pcapng.Reader(stream)

    try:
        return dpkt_mod.pcap.Reader(stream)
    except Exception:
        if hasattr(stream, "seekable") and stream.seekable():
            stream.seek(pos)
        return dpkt_mod.pcapng.Reader(stream)


def iter_pcap_flows(
    stream: io.IOBase | bytes | str | os.PathLike,
    *,
    source_id: str,
    session_id: str,
    scenario_id: str,
    flow_timeout_seconds: float = DEFAULT_FLOW_TIMEOUT_SECONDS,
    min_tls_application_bytes: int = DEFAULT_MIN_TLS_APP_BYTES,
    max_active_flows: int = 50000,
    max_raw_packets: int | None = None,
    max_raw_bytes: int | None = None,
    max_capture_packets: int | None = None,
    max_capture_bytes: int | None = None,
    max_flow_packets: int | None = None,
    max_flow_bytes: int | None = None,
    stats: dict[str, Any] | None = None,
    _dpkt_module: Any | None = None,
) -> Iterator[FlowRecord]:
    """Stream and yield completed bidirectional TCP flows from a PCAP/PCAPNG input.

    Parameters
    ----------
    stream : io.IOBase | bytes | str | Path
        Readable binary stream, raw bytes, or filesystem path.
    source_id : str
        Provenance identifier of the capture (e.g. filename or zip member).
    session_id : str
        Capture session ID for group-disjoint evaluation.
    scenario_id : str
        Scenario name (e.g. non_doh_browsing, benign_doh_firefox, malicious_doh_iodine).
    flow_timeout_seconds : float, default 40.0
        Flow inactivity timeout per DoHLyzer reference. Flows inactive for > 40s
        are finalized and yielded.
    min_tls_application_bytes : int, default 40
        Minimum application payload bytes (type 23) to filter out control frames.
    max_active_flows : int, default 50000
        Maximum active flows retained in memory before bounded LRU eviction.
    _dpkt_module : Any | None, optional
        Injected dpkt module for testing/mocking.

    Yields
    ------
    FlowRecord
        Completed flow containing canonical Packet and Clump sequences.
    """
    dpkt_mod = _dpkt_module if _dpkt_module is not None else _get_dpkt()

    # Normalize input into an open binary stream
    close_on_exit = False
    if isinstance(stream, (str, os.PathLike)):
        file_stream: io.IOBase = open(stream, "rb")
        close_on_exit = True
    elif isinstance(stream, (bytes, bytearray)):
        file_stream = io.BytesIO(stream)
    else:
        file_stream = stream

    try:
        reader = _open_pcap_reader(file_stream, dpkt_mod)
        datalink = getattr(reader, "datalink", lambda: 1)()
        if callable(datalink):
            datalink = datalink()

        # Active flow table: bidi_key -> _ActiveFlowState
        active_flows: dict[tuple[tuple[str, int], tuple[str, int], str], _ActiveFlowState] = {}
        packet_counter = 0
        raw_packet_counter = 0
        raw_bytes_counter = 0
        raw_packets_capped = False
        raw_bytes_capped = False
        capture_accepted_packets = 0
        capture_accepted_bytes = 0
        capture_truncated = False
        flows_yielded_count = 0
        flows_truncated_count = 0
        # TCP flags for connection control (SYN, RST)
        th_syn = getattr(dpkt_mod.tcp, "TH_SYN", 0x02)
        th_rst = getattr(dpkt_mod.tcp, "TH_RST", 0x04)

        for ts, buf in reader:
            raw_packet_counter += 1
            raw_bytes_counter += len(buf) if buf is not None else 0

            # Enforce raw packet and byte limits BEFORE packet decode / filtering
            if max_raw_packets is not None and raw_packet_counter > max_raw_packets:
                raw_packets_capped = True
                capture_truncated = True
                break
            if max_raw_bytes is not None and raw_bytes_counter > max_raw_bytes:
                raw_bytes_capped = True
                capture_truncated = True
                break

            ts_float = float(ts)
            packet_counter += 1
            parsed = _parse_packet_ip_tcp(buf, datalink, dpkt_mod)
            if parsed is None:
                continue

            src_ip, sport, dst_ip, dport, tcp_payload, tcp_flags = parsed

            # Ignore TCP control packets (pure SYN, RST)
            if tcp_flags & (th_syn | th_rst):
                continue

            # TLS Application Data filter (content type 23, >= min_tls_application_bytes)
            app_bytes = extract_tls_application_data_bytes(
                tcp_payload, min_bytes=min_tls_application_bytes
            )
            if app_bytes is None:
                continue

            # Enforce capture-level accepted packet and byte bounds
            if max_capture_packets is not None and capture_accepted_packets >= max_capture_packets:
                capture_truncated = True
                break
            if max_capture_bytes is not None and (capture_accepted_bytes + app_bytes) > max_capture_bytes:
                capture_truncated = True
                break
            capture_accepted_packets += 1
            capture_accepted_bytes += app_bytes
            # Bidirectional key
            bidi_key = (
                min((src_ip, sport), (dst_ip, dport)),
                max((src_ip, sport), (dst_ip, dport)),
                "TCP",
            )

            state = active_flows.get(bidi_key)
            if state is not None:
                # Check 40-second inactivity timeout
                if (ts_float - state.latest_timestamp) > flow_timeout_seconds:
                    # Previous flow expired; finalize and yield it
                    rec = state.to_flow_record(source_id, session_id, scenario_id)
                    flows_yielded_count += 1
                    if rec.truncated:
                        flows_truncated_count += 1
                    yield rec

                    # Start new flow with this packet defining client (direction 0)
                    new_key = FlowKey(
                        client_ip=src_ip,
                        client_port=sport,
                        server_ip=dst_ip,
                        server_port=dport,
                        protocol="TCP",
                    )
                    state = _ActiveFlowState(new_key, ts_float)
                    state.add_packet(
                        ts_float,
                        app_bytes,
                        direction=0,
                        max_flow_packets=max_flow_packets,
                        max_flow_bytes=max_flow_bytes,
                    )
                    active_flows[bidi_key] = state
                else:
                    # Packet belongs to active flow; determine direction
                    if state.flow_key.matches_forward(src_ip, sport, dst_ip, dport):
                        direction = 0  # Client to Server (Forward)
                    else:
                        direction = 1  # Server to Client (Reverse)
                    state.add_packet(
                        ts_float,
                        app_bytes,
                        direction=direction,
                        max_flow_packets=max_flow_packets,
                        max_flow_bytes=max_flow_bytes,
                    )
            else:
                # First packet of a new flow: sender is client (direction 0)
                new_key = FlowKey(
                    client_ip=src_ip,
                    client_port=sport,
                    server_ip=dst_ip,
                    server_port=dport,
                    protocol="TCP",
                )
                state = _ActiveFlowState(new_key, ts_float)
                state.add_packet(
                    ts_float,
                    app_bytes,
                    direction=0,
                    max_flow_packets=max_flow_packets,
                    max_flow_bytes=max_flow_bytes,
                )
                active_flows[bidi_key] = state

            # Periodic eviction of expired flows to keep memory strictly bounded
            if packet_counter % 2000 == 0:
                expired_keys = [
                    k
                    for k, st in active_flows.items()
                    if (ts_float - st.latest_timestamp) > flow_timeout_seconds
                ]
                for k in expired_keys:
                    st = active_flows.pop(k)
                    rec = st.to_flow_record(source_id, session_id, scenario_id)
                    flows_yielded_count += 1
                    if rec.truncated:
                        flows_truncated_count += 1
                    yield rec
                # Cap active flow table to avoid unbounded RAM under high concurrency
                if len(active_flows) > max_active_flows:
                    # Evict oldest flows by latest_timestamp
                    sorted_by_age = sorted(
                        active_flows.items(), key=lambda item: item[1].latest_timestamp
                    )
                    excess = len(active_flows) - max_active_flows
                    for k, st in sorted_by_age[:excess]:
                        del active_flows[k]
                        rec = st.to_flow_record(source_id, session_id, scenario_id)
                        flows_yielded_count += 1
                        if rec.truncated:
                            flows_truncated_count += 1
                        yield rec
        # Stream finished: flush all remaining active flows
        for state in active_flows.values():
            rec = state.to_flow_record(source_id, session_id, scenario_id)
            flows_yielded_count += 1
            if rec.truncated:
                flows_truncated_count += 1
            yield rec
        active_flows.clear()

        if stats is not None:
            stats["raw_packets_read"] = raw_packet_counter
            stats["raw_bytes_read"] = raw_bytes_counter
            stats["raw_packets_capped"] = raw_packets_capped
            stats["raw_bytes_capped"] = raw_bytes_capped
            stats["packets_read"] = packet_counter
            stats["accepted_packets"] = capture_accepted_packets
            stats["accepted_bytes"] = capture_accepted_bytes
            stats["capture_truncated"] = capture_truncated
            stats["flows_yielded"] = flows_yielded_count
            stats["flows_truncated"] = flows_truncated_count

    finally:
        if close_on_exit:
            file_stream.close()
