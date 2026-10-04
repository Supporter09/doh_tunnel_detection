# Quản lý Dữ liệu Thực nghiệm (Data Management & Manifests)

Thư mục này chứa tài liệu hướng dẫn, lược đồ hợp đồng dữ liệu và các tệp siêu dữ liệu kiểm soát phiên bản (**manifests**) phục vụ quá trình tái hiện bài báo khoa học:

> **MontazeriShatoori et al. (2020)**, *Detection of DoH Tunnels using Time-series Classification of Encrypted Traffic*, IEEE CyberSciTech / DASC 2020.

---

## 1. Nguyên tắc An toàn & Quy tắc Không Lưu trữ PCAP (Strict Safety Rules)

Để đảm bảo an toàn thông tin, bảo vệ quyền riêng tư và tuân thủ giấy phép nghiên cứu:

1. **TUYỆT ĐỐI KHÔNG commit tệp tin bắt gói tin mạng thô:** Cấm đưa các tệp `.pcap`, `.pcapng`, `.cap`, `.dmp` vào kho lưu trữ Git. Các tệp này đã được đưa vào `.gitignore`.
2. **TUYỆT ĐỐI KHÔNG lưu trữ dữ liệu nhạy cảm hoặc PII:** Cấm đưa payload gói tin giải mã, tệp ghi khoá TLS (`SSLKEYLOGFILE`), cookie, token, thông tin định danh cá nhân hoặc thông tin xác thực vào repository.
3. **TUYỆT ĐỐI KHÔNG commit trọng số mô hình lớn:** Các tệp checkpoint mô hình (`.h5`, `.pt`, `.onnx`) không thuộc phạm vi theo dõi của Git.
4. **Chỉ commit siêu dữ liệu (Manifests) và tài liệu:** Git chỉ lưu trữ các tệp manifest nhẹ định dạng JSON (`*.manifest.json`) mô tả nguồn gốc, mã băm SHA-256, phiên bản bộ trích xuất và phân vùng thực nghiệm.

---

## 2. Tập Dữ liệu Gốc: CIRA-CIC-DoHBrw-2020

Tập dữ liệu chuẩn được công bố bởi **Canadian Institute for Cybersecurity (CIC)** thuộc **Đại học New Brunswick (UNB)**, với sự tài trợ của **Cơ quan Đăng ký Internet Canada (CIRA)**:

* **Tên tập dữ liệu:** CIRA-CIC-DoHBrw-2020 (DNS-over-HTTPS Browser Traffic 2020).
* **Trang thông tin & Yêu cầu truy cập:** [https://www.unb.ca/cic/datasets/dohbrw-2020.html](https://www.unb.ca/cic/datasets/dohbrw-2020.html)
* **Bản phân phối cân bằng (SMOTE 50/50):** [York University BCCC DoH Dataset](https://www.yorku.ca/research/bccc/ucs-technical/cybersecurity-datasets-cds/dns-over-https-bccc-cira-cic-dohbrw-2020/)
* **Điều kiện tiếp cận & Cấp phép:** Dữ liệu có điều kiện truy cập (gated/licensed). Nhà nghiên cứu phải điền biểu mẫu thoả thuận nghiên cứu học thuật với UNB CIC trước khi tải về.
* **Cấu trúc lưu lượng thu thập:**
  * **Non-DoH:** Lưu lượng HTTPS thông thường (lướt web duyệt các trang trong top Alexa, xem video, truyền tệp tải xuống qua Google Chrome và Mozilla Firefox).
  * **Benign DoH:** Lưu lượng truy vấn DNS được mã hoá trong HTTPS qua các DoH resolver công cộng (Cloudflare, Google Public DNS, AdGuard, Quad9) sử dụng cấu hình DoH tích hợp sẵn trên trình duyệt.
  * **Malicious DoH (DNS Tunneling):** Lưu lượng đường hầm DNS bất hợp pháp được bọc trong HTTPS thông qua các công cụ:
    * `Iodine`
    * `dns2tcp`
    * `dnscat2`

---

## 3. Phân biệt Dữ liệu Thực vs Dữ liệu Synthetic Demo (Workflow Proof)

| Tiêu chí | Dữ liệu Thực tế (CIRA-CIC-DoHBrw-2020) | Dữ liệu Synthetic Demo (`doh_reproduction.demo`) |
| :--- | :--- | :--- |
| **Nguồn gốc** | Thu thập từ môi trường mạng lab thực tế tại UNB CIC | Sinh ngẫu nhiên có kiểm soát trong bộ nhớ (pure Python stdlib) |
| **Mục đích** | Đánh giá chính xác hiệu năng học thuật của bài báo | Kiểm chứng luồng hoạt động phần mềm (workflow proof) |
| **Độ phụ thuộc** | Cần tải PCAP từ UNB, giải nén, chạy trích xuất Scapy | Không cần mạng, không cần file ngoài, zero dependencies |
| **Giá trị đo lường** | Dùng để công bố kết quả khoa học tái hiện | **Chỉ dùng minh hoạ pipeline; KHÔNG phản ánh kết quả bài báo** |

> **TUYÊN BỐ KHÔNG MẠO NHẬN (Non-Claim Disclaimer):**
> Mã nguồn demo trong repository này sinh ra vết gói tin tổng hợp (synthetic traces) nhằm mục đích kiểm chứng tính đúng đắn về mặt cơ chế của thuật toán gom cụm gói tin (Packet Clumping) và chuỗi phân loại 2 tầng. Mọi chỉ số Precision, Recall hay F1 thu được từ lệnh chạy `python -m doh_reproduction.demo` là kết quả trên tập tổng hợp giả lập và **TUYỆT ĐỐI KHÔNG ĐƯỢC COI LÀ KẾT QUẢ TÁI HIỆN BÀI BÁO CỦA NHÓM**. Việc tái hiện bài báo bắt buộc phải thực thi trên tập dữ liệu CIRA-CIC-DoHBrw-2020 theo quy trình tại `docs/replication_protocol.md`.

---

## 4. Bố cục Thư mục Dữ liệu Cục bộ (Local Data Layout)

Khi làm việc với dữ liệu thực tế trên máy trạm cục bộ, các thành viên tuân thủ cấu trúc thư mục sau (các thư mục đánh dấu `[GITIGNORED]` sẽ không bao giờ xuất hiện trên Git):

```text
doh_tunnel_detection/data/
├── README.md                          # Tài liệu hướng dẫn này (được commit)
├── manifests/                         # Chứa các file JSON manifest phiên bản hoá (được commit)
│   ├── cira_cic_dohbrw_2020.manifest.json
│   └── synthetic_demo.manifest.json
├── raw/                               # [GITIGNORED] Lưu trữ file PCAP gốc tải từ UNB CIC
│   ├── NonDoH/
│   │   ├── chrome_https.pcap
│   │   └── firefox_https.pcap
│   ├── BenignDoH/
│   │   ├── cloudflare_doh.pcap
│   │   └── google_doh.pcap
│   └── MaliciousDoH/
│       ├── iodine_tunnel.pcap
│       ├── dns2tcp_tunnel.pcap
│       └── dnscat2_tunnel.pcap
└── derived/                           # [GITIGNORED] Dữ liệu trích xuất đặc trưng
    ├── l1_clumps_train.json
    ├── l1_clumps_test.json
    ├── l2_clumps_train.json
    └── l2_clumps_test.json
```

---

## 5. Cấu trúc Tệp Manifest Mẫu (`*.manifest.json`)

Mọi tập dữ liệu hoặc phân vùng nạp vào hệ thống phải đi kèm tệp manifest xác thực nguồn gốc và tính toàn vẹn:

```json
{
  "manifest_version": "1.0.0",
  "dataset_id": "cira-cic-dohbrw-2020-pcap-sample",
  "source_uri": "https://www.unb.ca/cic/datasets/dohbrw-2020.html",
  "license_or_access_evidence": "CIRA-CIC Academic Research Use Agreement (UNB)",
  "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "capture_period": {
    "start_time": "2020-01-01T00:00:00Z",
    "end_time": "2020-04-30T23:59:59Z"
  },
  "label_provenance": "Isolated testbed capture by UNB CIC with ground-truth application labels",
  "scenario_id": "malicious-iodine-tunnel",
  "session_id": "session-unb-2020-iodine-01",
  "extractor_version": "DoHLyzer-1.0.0-packet-clumping",
  "split_id": "train"
}
```

Chi tiết đặc tả từng trường và quy tắc bảo vệ dữ liệu được trình bày đầy đủ tại `docs/data_contract.md`.
