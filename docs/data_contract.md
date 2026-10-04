# Hợp Đồng Dữ Liệu Thực Nghiệm (Data Contract)

Tài liệu này xác định các quy tắc ràng buộc, lược đồ dữ liệu, cấu trúc thư mục và giao diện trao đổi dữ liệu giữa các module trong không gian làm việc `doh_tunnel_detection/`. Mục tiêu là đảm bảo tính toàn vẹn khoa học, khả năng tái lập độc lập và tuân thủ tuyệt đối các nguyên tắc an toàn dữ liệu, phòng thủ mạng và bảo vệ quyền riêng tư.

---

## 1. Nguyên tắc Cốt lõi & Ranh giới An toàn (Core Safety & Data Boundaries)

1. **Nguyên tắc Phòng thủ Tuyệt đối (Defensive-Only Boundary):**
   * Workspace phục vụ phân tích, phát hiện và phòng thủ trước kỹ thuật che giấu đường hầm DNS trong lưu lượng HTTPS.
   * **CẤM:** Không tạo mã nguồn vận hành DNS tunnel thật, không gửi gói tin bất hợp pháp ra mạng internet, không hướng dẫn triển khai cơ sở hạ tầng Command & Control (C2).
2. **Quy định Cấm Lưu trữ Tệp Bắt Gói Mạng Thô (No PCAPs in Version Control):**
   * Tệp tin bắt gói mạng (`.pcap`, `.pcapng`, `.cap`) chứa toàn bộ luồng byte thô. Việc commit các tệp này vào kho mã nguồn bị cấm tuyệt đối vì lý do bản quyền của tổ chức cung cấp dữ liệu (UNB/CIRA), dung lượng tệp và rủi ro rò rỉ thông tin riêng tư.
3. **Quy tắc Bảo mật Thông tin Nhạy cảm (No PII or Decrypted Secrets):**
   * Không lưu trữ chứng thư số riêng tư, khoá phiên TLS (`SSLKEYLOGFILE`), cookie, header xác thực hoặc nội dung thông điệp ứng dụng.
4. **Không Commit Trọng số Mô hình Nhị phân Lớn (No Binary Model Weights):**
   * Checkpoint của các mô hình học máy và học sâu (`.h5`, `.pt`, `.onnx`, `.pkl`) phải được lưu trữ ngoài Git tại thư mục riêng hoặc bộ nhớ lưu trữ thực nghiệm cục bộ.
5. **Tính Bất biến & Khả năng Kiểm toán (Immutability & Auditability):**
   * Mọi tệp dữ liệu được nạp vào đường ống phân tích phải được gắn nhãn qua một tệp manifest JSON có chữ ký băm mã hoá SHA-256 xác thực.

---

## 2. Đặc tả Lược đồ Manifest Phiên bản hoá (Versioned, Privacy-Safe Manifest Schema)

Mỗi tập dữ liệu cục bộ (dữ liệu thô tải về, dữ liệu phái sinh, hoặc dữ liệu phân vùng train/test) bắt buộc phải có một tệp manifest tương ứng tuân thủ định dạng JSON với schema phiên bản `1.0.0` dưới đây.

### 2.1. Bảng Chi tiết Các Trường Thuộc tính (Manifest Field Specification)

| Tên trường | Kiểu dữ liệu | Bắt buộc | Mô tả chi tiết & Quy chuẩn |
| :--- | :--- | :--- | :--- |
| `manifest_version` | `string` | Có | Phiên bản schema của manifest (quy chuẩn: `"1.0.0"`). |
| `dataset_id` | `string` | Có | Định danh duy nhất của tập dữ liệu (ví dụ: `"cira-cic-dohbrw-2020-raw"`, `"dohbrw-2020-benign-firefox"`, `"synthetic-workflow-demo-v1"`). |
| `source_uri` | `string` | Có | URI hoặc URL chính thức nơi dữ liệu được công bố/tải về (ví dụ: `"https://www.unb.ca/cic/datasets/dohbrw-2020.html"`). Với synthetic demo ghi `"memory://doh_reproduction/synthetic_generator"`. |
| `licence_or_access_evidence` | `string` | Có | Tuyên bố giấy phép sử dụng hoặc bằng chứng cấp quyền tiếp cận học thuật (ví dụ: `"CIRA-CIC Academic Research License (UNB CIC)"`, `"Internal Synthetic Data Generator (No external license required)"`). |
| `sha256` | `string` | Có | Mã băm SHA-256 (64 ký tự hex viết thường) của tệp lưu trữ hoặc tệp dữ liệu tương ứng để kiểm tra tính toàn vẹn tuyệt đối. |
| `capture_period` | `object` | Có | Khoảng thời gian thu thập dữ liệu gốc, gồm hai trường con định dạng ISO 8601 UTC: `start_time` và `end_time`. |
| `label_provenance` | `string` | Có | Xuất xứ và cơ chế gán nhãn ground-truth (ví dụ: `"Isolated testbed container per scenario; labels determined by launch script"` hoặc `"Deterministic synthetic prototype generator"`). |
| `scenario_id` | `string` | Có | Định danh kịch bản tạo dữ liệu (ví dụ: `"non_doh_browsing"`, `"benign_doh_firefox"`, `"malicious_doh_iodine"`, `"malicious_doh_dnscat2"`, `"malicious_doh_dns2tcp"`). |
| `session_id` | `string` | Có | Mã định danh phiên thu thập hoặc khối thời gian liên tục, dùng để thực hiện phân vùng chia tập (split) độc lập theo session nhằm tránh rò rỉ dữ liệu (data leakage). |
| `extractor_version` | `string` | Có | Tên và phiên bản cụ thể của công cụ trích xuất đặc trưng (ví dụ: `"DoHLyzer-1.0.0-scapy"`, `"doh_reproduction.clumping-0.1.0"`). |
| `split_id` | `string` | Có | Mục đích phân vùng dữ liệu trong bài thực nghiệm (`"train"`, `"validation"`, `"test"`, hoặc `"holdout"`). |

### 2.2. Ví dụ Tệp Manifest Hợp lệ

#### Ví dụ A: Manifest cho Tập Dữ liệu Thật (CIRA-CIC-DoHBrw-2020)
```json
{
  "manifest_version": "1.0.0",
  "dataset_id": "cira-cic-dohbrw-2020-iodine-pcap",
  "source_uri": "https://www.unb.ca/cic/datasets/dohbrw-2020.html",
  "licence_or_access_evidence": "CIRA-CIC Research Access Agreement (Form signed by Research Lead)",
  "sha256": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
  "capture_period": {
    "start_time": "2020-02-15T09:12:00Z",
    "end_time": "2020-02-15T10:45:00Z"
  },
  "label_provenance": "Controlled testbed running Iodine tunnel traffic encapsulated in HTTPS to Cloudflare DoH endpoint",
  "scenario_id": "malicious_doh_iodine",
  "session_id": "cic-doh-2020-iodine-session-03",
  "extractor_version": "DoHLyzer-1.0.0-custom-fork",
  "split_id": "train"
}
```

#### Ví dụ B: Manifest cho Bộ Dữ liệu Synthetic Demo
```json
{
  "manifest_version": "1.0.0",
  "dataset_id": "synthetic-doh-workflow-proof-v1",
  "source_uri": "memory://doh_reproduction/synthetic_generator",
  "licence_or_access_evidence": "Zero-dependency pure Python synthetic trace (Internal workflow verification only)",
  "sha256": "8f3b2a59a721c5f6e9b4d1e2a3c4b5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2",
  "capture_period": {
    "start_time": "2026-09-30T00:00:00Z",
    "end_time": "2026-09-30T00:01:00Z"
  },
  "label_provenance": "Procedural packet sequence generated with explicit scenario ground truth",
  "scenario_id": "synthetic_multi_scenario_balance",
  "session_id": "synth-seed-42-session-alpha",
  "extractor_version": "doh_reproduction.clumping-0.1.0",
  "split_id": "test"
}
```

---

## 3. Bố cục Phân cấp Dữ liệu (Raw vs Derived Data Layout)

```text
doh_tunnel_detection/data/
├── README.md                          # Hướng dẫn quy tắc dữ liệu & thủ tục tải CIRA
├── manifests/                         # Toàn bộ manifest JSON được theo dõi bởi Git
│   ├── cira_cic_dohbrw_2020.manifest.json
│   └── synthetic_demo.manifest.json
├── raw/                               # [GITIGNORED] Dữ liệu PCAP tải về cục bộ
│   ├── NonDoH/                        # Lưu lượng web thông thường (HTTPS port 443)
│   ├── BenignDoH/                     # Lưu lượng DoH thông thường (Chrome/Firefox qua DoH)
│   └── MaliciousDoH/                  # Lưu lượng DoH chứa đường hầm (Iodine, dns2tcp, dnscat2)
└── derived/                           # [GITIGNORED] Dữ liệu phái sinh sau khi trích xuất
    ├── l1_statistical_train.json      # 28 đặc trưng thống kê flow phục vụ Tầng 1
    ├── l1_statistical_test.json
    ├── l1_clumps_train.json           # Chuỗi Clump (l=6) phục vụ Tầng 1
    ├── l1_clumps_test.json
    ├── l2_clumps_train.json           # Chuỗi Clump (l=3) phục vụ Tầng 2
    └── l2_clumps_test.json
```

---

## 4. Hợp Đồng Cấu Trúc Bản Ghi Đặc Trưng Clump (Clump Feature Sequence Contract)

### 4.1. Quy tắc Định nghĩa Clump của Bài báo (Paper Clumping Semantics)
Thuật toán gom cụm gói tin (Packet Clumping) theo công bố của MontazeriShatoori et al. (2020) và mã nguồn công khai `DoHLyzer` tuân theo định nghĩa:
1. **Cùng chiều truyền tải (Same Direction):** Tất cả các gói tin trong cùng một clump phải có cùng chiều truyền (hoặc là Client-to-Server, hoặc là Server-to-Client). Khi có một gói tin đổi chiều, clump hiện tại lập tức kết thúc và một clump mới bắt đầu.
2. **Khoảng cách liên tiếp không vượt quá 1 ms (Inter-packet gap $\le 1\text{ ms}$):** Giữa hai gói tin liên tiếp cùng chiều, nếu khoảng cách thời gian giữa thời điểm đến của chúng lớn hơn $1\text{ ms}$ ($dt > 0.001\text{ s}$), clump hiện tại kết thúc và một clump mới được mở.
3. **Tính đơn điệu và Hợp lệ của Dữ liệu:**
   * Mốc thời gian gói tin ($t$) phải tăng đơn điệu ($t_{i+1} \ge t_i$). Nếu phát hiện gói tin bị nghịch đảo mốc thời gian (out-of-order) do bắt gói trễ, bộ trích xuất phải sắp xếp lại hoặc báo lỗi nếu vi phạm nghiêm trọng.
   * Kích thước payload/kích thước gói tin không được là số âm.

### 4.2. Cấu trúc Bản ghi 5-Tuple của một Clump
Mỗi clump được biểu diễn bằng một bộ 5 thành phần số học xác định theo thứ tự `(size, pkt_count, direction, duration, interarrival)`:

$$\mathbf{C}_k = \left( S_k, N_k, d_k, \Delta t_k, IAT_k \right)$$

Trong đó:
* **$S_k$ (`size` - Total Size / Bytes - Tổng kích thước):** Tổng số byte (tổng kích thước gói hoặc payload) của các gói trong clump.
* **$N_k$ (`pkt_count` - Packet Count - Số lượng gói tin):** Số nguyên dương biểu thị số lượng gói tin hợp thành clump này.
* **$d_k$ (`direction` - Direction - Chiều gói tin):** `0` cho chiều Client-to-Server (tương ứng chiều đi / request); `1` cho chiều Server-to-Client (tương ứng chiều về / response).
* **$\Delta t_k$ (`duration` - Duration - Thời lượng clump):** Thời gian tính từ gói đầu tiên đến gói cuối cùng của clump: $\Delta t_k = t_{\text{last}} - t_{\text{first}}$ (đơn vị: giây, $\ge 0.0$). Nếu clump chỉ có 1 gói, $\Delta t_k = 0.0$.
* **$IAT_k$ (`interarrival` - Inter-Arrival Time - Thời gian liên clump):** Khoảng cách thời gian tính từ mốc kết thúc của clump trước đó ($t_{k-1, \text{last}}$) đến mốc bắt đầu của clump hiện tại ($t_{k, \text{first}}$).
  * **Quy ước xác định (Deterministic Rule):** Đối với clump đầu tiên trong một flow ($k=0$), $IAT_0$ được quy ước bằng chính xác `0.0` giây (không sử dụng giá trị NaN hay null). Đối với các clump tiếp theo ($k \ge 1$), khoảng cách thời gian được tính là $IAT_k = t_{k, \text{first}} - t_{k-1, \text{last}}$.

### 4.3. Ngưỡng Chiều dài Chuỗi Phân loại 2 Tầng (Sequence Length Thresholds)
* **Tầng 1 (Layer 1 - DoH vs Non-DoH):**
  * Ngưỡng bài báo: $l_1 = 6$ clumps.
  * Khi luồng mạng tích luỹ đủ 6 clumps đầu tiên, chuỗi được chuyển tới bộ phân loại Tầng 1 để đưa ra quyết định sớm.
* **Tầng 2 (Layer 2 - Benign DoH vs Malicious DoH Tunnel):**
  * Ngưỡng bài báo: $l_2 = 3$ clumps.
  * Chỉ các luồng được Tầng 1 kết luận là DoH mới được đưa vào Tầng 2 để nhận diện đường hầm ẩn lậu.

---

## 5. Quy trình Chống Rò rỉ Dữ liệu Thực nghiệm (Data Leakage Prevention Protocol)

Để tránh hiện tượng mô hình học vẹt thông tin nền của môi trường lab (như nhận diện địa chỉ IP máy trạm hay cổng dịch vụ thay vì học hành vi luồng):

1. **Loại bỏ Hoàn toàn Đặc trưng Định danh Máy (IP/Port Feature Strip):**
   * Các đặc trưng IP nguồn, IP đích, Port nguồn, MAC address và các cờ TCP phụ thuộc hệ điều hành TUYỆT ĐỐI KHÔNG được đưa vào không gian đặc trưng của bộ phân loại.
2. **Chiến lược Phân vùng Tách biệt Nhóm/Phiên (Session/Group-Disjoint Splits):**
   * **Vấn đề trong bài báo gốc:** Bài báo chia dữ liệu ngẫu nhiên $80/20$ theo từng flow riêng lẻ. Do các flow trong cùng một phiên duyệt web hoặc cùng một phiên chạy tunnel có hành vi rất giống nhau, việc chia ngẫu nhiên dẫn đến nguy cơ rò rỉ mẫu giữa tập train và tập test (mô hình đạt độ chính xác giả tạo cao).
   * **Quy chuẩn bắt buộc của nhóm:** Khi đánh giá nâng cao, dữ liệu train và test phải được phân chia tách biệt theo `session_id` hoặc theo thời gian capture (time-based holdout), đảm bảo không có phiên capture nào vừa xuất hiện trong train vừa xuất hiện trong test.
3. **Tiền xử lý Riêng trên Tập Train (Train-Only Fit):**
   * Mọi thao tác chuẩn hoá (MinMaxScaler, StandardScaler) hoặc tính toán trung bình/độ lệch chuẩn phải được tính toán duy nhất trên tập Train, sau đó áp dụng phép chuyển đổi (transform) sang tập Test. Nghiêm cấm fit trên toàn bộ tập dữ liệu gộp.
