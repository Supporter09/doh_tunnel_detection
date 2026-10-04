# Hệ Thống Phát Hiện DNS-over-HTTPS (DoH) Tunnel Qua Phân Loại Chuỗi Thời Gian Gói Tin

Không gian làm việc nghiên cứu và tái hiện học thuật bài báo khoa học về an toàn mạng:

> **Mohammadreza MontazeriShatoori, Logan Davidson, Gurdip Kaur, Arash Habibi Lashkari (2020)**  
> *Detection of DoH Tunnels using Time-series Classification of Encrypted Traffic*  
> Xuất bản tại: **2020 IEEE International Conference on Cyber Science and Technology Congress (CyberSciTech)** / DASC / PICom / CBDCom  
> DOI: [10.1109/DASC-PICom-CBDCom-CyberSciTech49142.2020.00026](https://doi.org/10.1109/DASC-PICom-CBDCom-CyberSciTech49142.2020.00026)  
> Đơn vị nghiên cứu: Canadian Institute for Cybersecurity (CIC), University of New Brunswick (UNB), Fredericton, Canada.

---

## 1. Tuyên Bố Phạm Vi & Giới Hạn Nghiên Cứu (Scope & Non-Claim Disclaimer)

### 1.1. Phạm Vi Phòng Thủ & An Toàn Tuyệt Đối (Defensive Boundary)
* Không gian làm việc này được thiết kế phục vụ duy nhất mục đích **nghiên cứu phòng thủ an toàn thông tin** và đánh giá học thuật trong khuôn khổ đồ án Capstone.
* Dự án **TUYỆT ĐỐI KHÔNG**:
  * Tạo lập, triển khai hoặc vận hành máy chủ/máy trạm phục vụ DNS Tunneling thực tế.
  * Replay (phát lại) lưu lượng mã độc hoặc gói tin PCAP ra mạng nội bộ hay mạng Internet.
  * Chứa mã độc, backdoor, hoặc công cụ khai thác lỗ hổng.
  * Thu thập hoặc xử lý dữ liệu định danh người dùng (PII), thông tin xác thực hay khoá giải mã TLS.

### 1.2. Tuyên Bố Không Mạo Nhận Kết Quả Học Thuật (Non-Claim Disclaimer)
* Mã nguồn demo đi kèm dự án (`doh_reproduction.demo`) chạy hoàn toàn ngoại tuyến và độc lập bằng **thư viện chuẩn Python (Python standard library)**, không yêu cầu cài đặt gói phụ thuộc bên ngoài (`zero external dependencies`).
* Dữ liệu sử dụng trong demo là **vết gói tin tổng hợp thủ tục (deterministic synthetic packet traces)** được tạo trong bộ nhớ RAM, phục vụ chứng minh cơ chế làm việc của đường ống phần mềm (**workflow proof**): từ việc trích xuất cụm gói tin (Packet Clumping) đến phân loại chuỗi 2 tầng tuần tự.
* **CẢNH BÁO QUAN TRỌNG:** Các số liệu đo lường (Precision, Recall, F1-score, Confusion Matrix) sinh ra từ script demo **CHỈ LÀ KẾT QUẢ MINH HOẠ QUY TRÌNH KỸ THUẬT TRÊN TẬP DỮ LIỆU TỔNG HỢP VÀ TUYỆT ĐỐI KHÔNG ĐƯỢC COI LÀ KẾT QUẢ TÁI HIỆN BÀI BÁO CỦA NHÓM**.
* Để tái hiện chính xác kết quả khoa học đã công bố của bài báo, nhóm nghiên cứu bắt buộc phải:
  1. Sử dụng tập dữ liệu thực tế **CIRA-CIC-DoHBrw-2020** có bản quyền học thuật từ Đại học New Brunswick.
  2. Áp dụng giao thức huấn luyện và phân tách dữ liệu được chuẩn hoá tại [docs/replication_protocol.md](docs/replication_protocol.md).

---

## 2. Kiến Trúc Phát Hiện Hai Tầng Tuần Tự (Two-Layer Detection Architecture)

Bài báo đề xuất cơ chế phân loại phân cấp nhằm giải quyết bài toán phát hiện lưu lượng DNS ẩn lậu trong kết nối HTTPS mã hoá:

```text
               Lưu lượng mạng HTTPS mã hoá (TCP Port 443)
                                  │
                                  ▼
      ┌────────────────────────────────────────────────────────┐
      │  TẦNG 1: Phân biệt DoH vs Non-DoH                     │
      │  - Tiếp nhận chuỗi Packet Clump ban đầu: l = 6 clumps  │
      │  - Quyết định sớm: Lưu lượng có phải là DoH không?    │
      └───────────────────────────┬────────────────────────────┘
                                  │
                   ┌──────────────┴──────────────┐
                   │ (DoH)                       │ (Non-DoH)
                   ▼                             ▼
      ┌─────────────────────────┐   ┌──────────────────────────┐
      │ TẦNG 2: Phân loại DoH   │   │ Bỏ qua / Cho phép        │
      │ - Chuỗi Clump: l = 3    │   │ (Lưu lượng web chuẩn)    │
      │ - Phân biệt:            │   └──────────────────────────┘
      │   * Benign-DoH (Duyệt)  │
      │   * Malicious Tunnel    │
      │     (Iodine, dns2tcp,   │
      │      dnscat2)           │
      └─────────────────────────┘
```

* **Quy tắc Gom cụm Gói tin (Packet Clumping):** Gom các gói tin liên tiếp cùng chiều truyền tải có khoảng cách thời gian giữa hai gói cạnh nhau không vượt quá 1 mili-giây ($dt \le 0.001\text{ s}$).
* **Đặc trưng 5-Tuple của một Clump:** `(size, pkt_count, direction, duration, interarrival)`. Thời gian liên clump (`interarrival`) của clump đầu tiên mặc định bằng `0.0`, các clump tiếp theo được đo từ thời điểm kết thúc clump trước đến thời điểm bắt đầu clump hiện tại.
* **Ngưỡng chuỗi quyết định:**
  * **Tầng 1 ($l=6$ clumps):** Phát hiện lưu lượng DoH sớm trong vòng 6 clumps đầu tiên.
  * **Tầng 2 ($l=3$ clumps):** Nhận diện lưu lượng đường hầm độc hại chỉ sau 3 clumps DoH.

---

## 3. Hướng Dẫn Vận Hành Nhanh (Zero-Dependency Quickstart)

Toàn bộ harness lõi được viết thuần bằng thư viện chuẩn của **Python 3.11+** (đã kiểm thử tương thích với Python 3.13 trên macOS Apple Silicon). Không cần tạo virtualenv và không cần chạy `pip install`.

### 3.1. Chạy Demo Quy Trình Kiểm Chứng Ngoại Tuyến (Synthetic Demo)
Chạy script demo để kiểm tra đường ống gom cụm gói tin và bộ phân loại nguyên mẫu chuỗi 2 tầng:

```bash
cd doh_tunnel_detection
PYTHONPATH=src python3 -m doh_reproduction.demo
```

### 3.2. Chạy Toàn Bộ Kiểm Thử Đơn Vị Tự Động (Unit Tests)
Chạy bộ kiểm thử đơn vị bao phủ thuật toán clumping (đổi chiều, ngắt quãng thời gian > 1ms, luồng ngắn, kiểm tra timestamp đơn điệu):

```bash
cd doh_tunnel_detection
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

---

## 4. Cấu Trúc Đầu Ra JSON Dự Kiến (Expected JSON Output Schema)

Lệnh thực thi demo xuất ra một đối tượng JSON có cấu trúc xác định, hỗ trợ đọc hiểu trực quan và tích hợp kiểm thử tự động. Dưới đây là mô tả lược đồ các trường thông tin chuẩn (chú ý: đây là cấu trúc trường dữ liệu, không chứa số liệu mạo nhận):

```json
{
  "disclaimer": "Chuỗi cảnh báo: Kết quả sinh ra từ bộ sinh vết tổng hợp trong bộ nhớ (workflow proof), không phản ánh hiệu năng thực tế của bài báo trên tập CIRA-CIC-DoHBrw-2020.",
  "metadata": {
    "engine": "doh_reproduction.demo",
    "version": "Phiên bản harness (ví dụ: '0.1.0')",
    "python_runtime": "Phiên bản Python môi trường thực thi",
    "clumping_parameters": {
      "max_inter_packet_gap_seconds": 0.001,
      "layer1_sequence_length_clumps": 6,
      "layer2_sequence_length_clumps": 3
    }
  },
  "dataset_summary": {
    "generation_mode": "in-memory synthetic scenario-disjoint traces",
    "total_generated_flows": "Tổng số luồng tổng hợp được tạo",
    "split_strategy": "scenario-disjoint train/test split",
    "train_flows_count": "Số lượng luồng dùng để thiết lập nguyên mẫu",
    "test_flows_count": "Số lượng luồng dùng để đánh giá kiểm thử"
  },
  "layer1_evaluation": {
    "target": "DoH vs Non-DoH (l = 6 clumps)",
    "classifier": "DeterministicSequencePrototypeClassifier (Proxy, Non-LSTM)",
    "confusion_matrix": {
      "true_positives": "Số lượng mẫu DoH phân loại đúng",
      "false_positives": "Số lượng mẫu Non-DoH bị nhận nhầm thành DoH",
      "true_negatives": "Số lượng mẫu Non-DoH phân loại đúng",
      "false_negatives": "Số lượng mẫu DoH bị bỏ sót"
    },
    "metrics": {
      "precision": "Độ chính xác TP / (TP + FP)",
      "recall": "Độ nhạy TP / (TP + FN)",
      "f1_score": "Trung bình điều hoà giữa Precision và Recall",
      "mean_latency_ms": "Độ trễ xử lý trung bình mỗi luồng tính bằng mili-giây"
    }
  },
  "layer2_evaluation": {
    "target": "Benign-DoH vs Malicious-Tunnel (l = 3 clumps)",
    "classifier": "DeterministicSequencePrototypeClassifier (Proxy, Non-LSTM)",
    "confusion_matrix": {
      "true_positives": "Số lượng mẫu Malicious Tunnel phân loại đúng",
      "false_positives": "Số lượng mẫu Benign-DoH bị nhận nhầm thành Malicious",
      "true_negatives": "Số lượng mẫu Benign-DoH phân loại đúng",
      "false_negatives": "Số lượng mẫu Malicious Tunnel bị bỏ sót"
    },
    "metrics": {
      "precision": "Độ chính xác Tầng 2",
      "recall": "Độ nhạy Tầng 2",
      "f1_score": "Điểm F1 Tầng 2",
      "mean_latency_ms": "Độ trễ xử lý trung bình mỗi luồng tính bằng mili-giây"
    }
  },
  "sample_prediction": {
    "flow_id": "Mã nhận diện luồng mẫu kiểm tra",
    "ground_truth_label": "Nhãn thực tế của luồng mẫu",
    "layer1_result": {
      "predicted_label": "doh hoặc non_doh",
      "clumps_processed": 6,
      "passed_to_layer2": true
    },
    "layer2_result": {
      "predicted_label": "benign_doh hoặc tunnel_like",
      "clumps_processed": 3
    }
  }
}
```

---

## 5. Vận Hành Thực Nghiệm Kaggle (Kaggle Statistical Baseline Runner)

Dự án cung cấp runner chạy trên môi trường Kaggle CPU phục vụ kiểm toán dữ liệu và đánh giá các mô hình học máy truyền thống (**Random Forest**, **Decision Tree**, **Gaussian Naive Bayes**, **Linear SVM**) trên tập đặc trưng dạng bảng `dhoogla/cicdohbrw2020` (version 3). Lệnh `kaggle datasets files dhoogla/cicdohbrw2020` xác nhận tập dữ liệu gồm chính xác hai tệp bảng Parquet: `L1-DoH-NonDoH.parquet` (107,043,097 bytes) và `L2-BenignDoH-MaliciousDoH.parquet` (34,164,502 bytes):

* **Cảnh Báo Phạm Vi (Statistical Baseline Only):** Runner này **CHỈ ĐÁNH GIÁ ĐƯỜNG CƠ SỞ THỐNG KÊ DẠNG BẢNG** trên các tệp Parquet/CSV, tuyệt đối **KHÔNG ĐẠI DIỆN** cho việc tái hiện mô hình chuỗi thời gian gói tin (Packet Clumping + LSTM) của bài báo gốc (vốn đòi hỏi vết PCAP thô và nhãn thời gian vi giây).
* **Quy Trình Kiểm Toán Trước (Audit-First):** Hỗ trợ khám phá và kiểm toán các tệp bảng CSV và Parquet (sử dụng pandas với pyarrow). Tự động phát hiện cấu trúc thuộc tính, tính toán SHA-256 theo luồng, kiểm toán nhãn và kết xuất `schema_audit.json` trước khi cho phép huấn luyện. Lần kiểm toán tiếp theo xác định chính xác các nhãn thực tế trước khi thay đổi cấu hình huấn luyện; tuyệt đối không tự bịa đặt hay suy đoán nhãn.
* **Cơ Chế Nhúng Cấu Hình An Toàn (Embedded Configuration):** Do Kaggle chỉ tải lên tệp mã nguồn khai báo (`train_statistical.py`) đối với Script kernel, wrapper `push_statistical_baseline.sh` đọc và kiểm thực tệp cấu hình theo dõi `run_config.json`, sau đó tiêm an toàn vào hằng số cấu hình nhúng trong bản sao mã nguồn trước khi tính toán mã băm snapshot và tải lên. Kernel từ xa ưu tiên phân giải cấu hình nhúng này và ghi nhận nguồn `embedded` trong manifest.
* **Cơ Chế Khóa Tải Tạo Tác An Toàn (Completion Guard & Non-Empty Outputs):** Lệnh `pull_outputs.sh` **bắt buộc chỉ được chạy sau khi** trạng thái kernel đã hoàn tất (`complete`). Wrapper tự động kiểm tra trạng thái kernel trước khi tạo hoặc ghi vào thư mục đầu ra và sẽ từ chối thực thi (thoát mã lỗi khác 0) nếu kernel đang ở trạng thái `queued`, `running` hoặc bất kỳ trạng thái nào chưa `complete`; đồng thời từ chối xác nhận thành công nếu kết quả tải về không có tệp tạo tác hợp lệ nào (empty artifact download).
* **Xuất Xứ Mã Nguồn & Băm Snapshot Xác Thực (Truthful Provenance & Snapshot Hash):**
  * Wrapper đẩy kernel tự động tính toán mã băm SHA-256 xác định trên chính xác các tệp nguồn được tải lên (`KAGGLE_SOURCE_SNAPSHOT_SHA256`) và tiêm vào môi trường thực thi để làm bằng chứng xuất xứ bất biến.
  * Mã Git commit (`KAGGLE_GIT_SHA`) chỉ đại diện cho mã nguồn khi thư mục dự án `doh_tunnel_detection/` được commit sạch trong Git. Khi mã nguồn chưa được commit hoặc đang dirty, wrapper ghi nhận `KAGGLE_GIT_SHA="unknown_uncommitted_source"` nhằm phản ánh đúng ngữ cảnh và không đưa ra tuyên bố sai lệch.
  * Các lần chạy kiểm toán schema (audit runs) được phép tiến hành với mã băm snapshot; tuy nhiên, **toàn bộ dự án bắt buộc phải được commit sạch vào kho Git trước khi bất kỳ kết quả thực nghiệm nào được quảng bá (promote) thành thực nghiệm chính thức**.
* **Chu Trình Vận Hành Nhanh:**
  ```bash
  # 1. Khởi tạo môi trường ảo công cụ Kaggle cô lập
  bash scripts/kaggle/bootstrap_cli.sh

  # 2. Khai báo ID kernel trong phiên Shell (không commit vào Git)
  export KAGGLE_KERNEL_ID="<your-kaggle-username>/cicdohbrw2020-statistical-baseline"

  # 3. Đẩy kernel kiểm toán schema (chế độ Private, không Internet)
  bash scripts/kaggle/push_statistical_baseline.sh

  # 4. Kiểm tra trạng thái thực thi (giám sát cho tới khi complete)
  bash scripts/kaggle/status.sh

  # 5. Tải tạo tác kết quả (schema_audit.json, metrics.json, manifest) về máy trạm
  # LƯU Ý: Chỉ chạy sau khi status báo complete; script sẽ từ chối nếu kernel đang queued/running hoặc tải về thư mục rỗng.
  bash scripts/kaggle/pull_outputs.sh
  ```
* Hướng dẫn thiết lập API token an toàn (`chmod 600 ~/.kaggle/kaggle.json`), phân tích schema và chính sách đưa manifest vào Git xem chi tiết tại: [**docs/kaggle_runner.md**](docs/kaggle_runner.md).

---

## 6. Mục Lục Tài Liệu Kỹ Thuật (Documentation Directory)

Dự án cung cấp bộ tài liệu hoàn chỉnh hỗ trợ triển khai, kiểm toán dữ liệu và tái hiện học thuật:

* [**docs/kaggle_runner.md**](docs/kaggle_runner.md): Hướng dẫn vận hành Kaggle runner an toàn, quy trình kiểm toán schema trước (audit-first), quản lý bí mật CLI, cơ chế băm snapshot xác thực (SHA-256) và yêu cầu bắt buộc commit Git trước khi quảng bá tạo tác thực nghiệm.
* [**docs/data_contract.md**](docs/data_contract.md): Hợp đồng dữ liệu, đặc tả các trường manifest kiểm soát phiên bản (`dataset_id`, `sha256`, `licence`, `scenario_id`, `split_id`), bố cục dữ liệu thô / phái sinh và quy tắc bảo vệ quyền riêng tư.
* [**docs/team_plan.md**](docs/team_plan.md): Kế hoạch hợp tác nhóm 3 người, phân chia vai trò, hợp đồng tích hợp giữa các module, các cột mốc tuần tự (M1–M5), tiêu chuẩn Definition of Done (DoD) và quy trình bình duyệt PR.
* [**data/README.md**](data/README.md): Hướng dẫn tiếp cận tập dữ liệu CIRA-CIC-DoHBrw-2020 từ UNB CIC, lưu ý bản quyền, quy tắc cấm commit PCAP và cấu trúc thư mục dữ liệu cục bộ.
* [**docs/paper_analysis.md**](docs/paper_analysis.md): Phân tích chi tiết bài báo gốc, 28 đặc trưng thống kê DoHLyzer, biểu diễn chuỗi clump 5-tuple, đối chiếu các bảng kết quả III–VI và danh mục các tham số bị khuyết thiếu.
* [**docs/replication_protocol.md**](docs/replication_protocol.md): Giao thức tái hiện khoa học nghiêm ngặt, đối chiếu giữa tái hiện nguyên bản (exact replication) và giao thức cải tiến hiện đại (session-disjoint split, train-only normalization).
* [**docs/risk_register.md**](docs/risk_register.md): Sổ đăng ký và quản trị rủi ro học thuật, bản quyền tập dữ liệu, rò rỉ dữ liệu (data leakage), trôi dạt phiên bản DNS resolver và an toàn phòng thí nghiệm.
---

## 7. Trích Dẫn Học Thuật Chuẩn (BibTeX Citation)
Khi sử dụng tài nguyên hoặc tham chiếu đến bài báo gốc trong các báo cáo khoa học:

```bibtex
@inproceedings{montazerishatoori2020detection,
  author    = {MontazeriShatoori, Mohammadreza and Davidson, Logan and Kaur, Gurdip and Lashkari, Arash Habibi},
  title     = {Detection of DoH Tunnels using Time-series Classification of Encrypted Traffic},
  booktitle = {2020 IEEE International Conference on Dependable, Autonomic and Secure Computing, International Conference on Pervasive Intelligence and Computing, International Conference on Cloud and Big Data Computing, International Conference on Cyber Science and Technology Congress (DASC/PiCom/CBDCom/CyberSciTech)},
  year      = {2020},
  pages     = {63--70},
  doi       = {10.1109/DASC-PICom-CBDCom-CyberSciTech49142.2020.00026},
  publisher = {IEEE}
}
```
