# Hướng Dẫn Vận Hành Kaggle Runner An Toàn & Tái Lập (Secure Kaggle Runner Guide)

Tài liệu này hướng dẫn chi tiết quy trình thiết lập môi trường, kiểm toán dữ liệu và vận hành thực nghiệm từ xa trên nền tảng Kaggle cho bài toán phát hiện đường hầm DoH (DNS-over-HTTPS).

> **LƯU Ý CỐT LÕI (GIT IS SOURCE OF TRUTH & TRUTHFUL PROVENANCE):**  
> Kho lưu trữ Git cục bộ là **nguồn chân lý duy nhất (single source of truth)** cho toàn bộ mã nguồn, cấu hình và giao thức thực nghiệm. Kaggle chỉ đóng vai trò là môi trường tính toán thực thi tạm thời (immutable execution worker).
> Tuy nhiên, mã commit Git của worktree cha (`git rev-parse HEAD`) **chỉ đại diện cho xuất xứ mã nguồn khi toàn bộ thư mục dự án `doh_tunnel_detection/` đã được commit sạch trong Git**. Khi mã nguồn chưa được commit hoặc đang ở trạng thái untracked/dirty, mã commit Git không thể chứng minh tính đồng nhất của mã nguồn kernel đã tải lên.
> Do đó, wrapper đẩy kernel luôn tự động tính toán mã băm bối cảnh nội dung xác định (**deterministic SHA-256 content snapshot** qua biến runtime `KAGGLE_SOURCE_SNAPSHOT_SHA256`) trên chính xác các tệp kernel được sao chép vào thư mục tải lên. Biến `KAGGLE_GIT_SHA` chỉ ghi nhận commit SHA khi mã nguồn kernel được theo dõi sạch (tracked and clean); nếu chưa được commit, biến này mang giá trị `unknown_uncommitted_source`.
> Các lần chạy kiểm toán schema (audit runs) được phép tiến hành với mã băm snapshot; tuy nhiên, **bắt buộc phải commit dự án vào kho Git chính thức trước khi bất kỳ kết quả thực nghiệm nào được quảng bá (promote) thành thực nghiệm chính thức có tính tái lập khoa học**.
---

## 1. Tuyên Bố Ranh Giới Nghiên Cứu & Phạm Vi Không Mạo Nhận (Claim Boundaries & Non-Claim Disclaimer)

### 1.1. Phạm Vi Dữ Liệu Kaggle: Baseline Thống Kê Dạng Bảng (Statistical Baseline Only)
* Tập dữ liệu đầu vào công khai trên Kaggle là **`dhoogla/cicdohbrw2020`** (phiên bản 3 - Version 3). Lệnh `kaggle datasets files dhoogla/cicdohbrw2020` xác nhận tập dữ liệu gồm chính xác 2 tệp định dạng Parquet:
  1. `L1-DoH-NonDoH.parquet` (107,043,097 bytes)
  2. `L2-BenignDoH-MaliciousDoH.parquet` (34,164,502 bytes)
* Bộ dữ liệu này chứa các đặc trưng thống kê tóm tắt ở cấp độ luồng (flow-level statistical summary features) được sinh ra từ công cụ `DoHLyzer` (ví dụ: `duration`, `packet_count`, `bytes_count`, các thống kê min/max/mean/std của độ dài gói và thời gian liên gói). Runner hỗ trợ cả định dạng bảng CSV và Parquet (sử dụng pandas với engine pyarrow).
* Do đó, runner Kaggle trong không gian làm việc này **CHỈ PHỤC VỤ DUY NHẤT** việc huấn luyện và đánh giá các mô hình học máy truyền thống làm thước đo đối sánh thống kê (tabular/statistical baselines):
  * **Random Forest** (`RandomForestClassifier`)
  * **Decision Tree** (`DecisionTreeClassifier`)
  * **Gaussian Naive Bayes** (`GaussianNB`)
  * **Linear SVM** (`LinearSVC`)

### 1.2. Cảnh Báo Bản Quyền & Tuyên Bố Không Mạo Nhận Mô Hình LSTM (Strict Non-Claim Disclaimer)
* **CẢNH BÁO QUAN TRỌNG:** Tập dữ liệu Kaggle dạng bảng (CSV/Parquet) **TUYỆT ĐỐI KHÔNG HỖ TRỢ** và **KHÔNG ĐƯỢC PHÉP ĐẠI DIỆN** cho việc tái hiện kiến trúc mạng nơ-ron chuỗi thời gian (Packet Clumping + LSTM) của bài báo gốc:
  > **MontazeriShatoori et al. (2020), *Detection of DoH Tunnels using Time-series Classification of Encrypted Traffic*, IEEE CyberSciTech 2020.**
* **Nguyên nhân kỹ thuật:**
  1. Mô hình phân loại chuỗi thời gian của bài báo yêu cầu dữ liệu chuỗi các cụm gói tin (**Packet Clump Sequences**): mỗi cụm là 5-tuple $(size, pkt\_count, direction, duration, interarrival)$ gom các gói tin cùng chiều có khoảng cách thời gian $dt \le 1\text{ ms}$.
  2. Để trích xuất chuỗi cụm, đường ống bắt buộc phải có vết gói tin thô (raw PCAP) với đầy đủ thông tin: **thứ tự xuất hiện của từng gói tin (packet arrival order)**, **chiều truyền tải (forward/backward)**, và **nhãn thời gian vi giây/mili-giây (packet timestamps)**.
  3. Dữ liệu dạng bảng (CSV/Parquet) trên Kaggle đã trải qua quá trình tổng hợp thống kê gộp (aggregation) trên toàn bộ luồng, triệt tiêu hoàn toàn thứ tự gói tin và cấu trúc chuỗi thời gian cục bộ.
  4. Việc sử dụng dữ liệu dạng bảng trên Kaggle để huấn luyện mô hình là bước thiết lập đường cơ sở so sánh (baseline comparison), tuyệt đối không được mạo nhận trong các báo cáo học thuật là đã tái hiện mô hình LSTM hay cơ chế gom cụm gói tin của bài báo.
* **Tài liệu đối chiếu bắt buộc:**
  * Hợp đồng dữ liệu & ranh giới an toàn: [docs/data_contract.md](data_contract.md)
  * Giao thức tái hiện khoa học nghiêm ngặt: [docs/replication_protocol.md](replication_protocol.md)
  * Phân tích chuyên sâu bài báo gốc & tham số khuyết thiếu: [docs/paper_analysis.md](paper_analysis.md)
  * Kế hoạch cộng tác nhóm & quy chuẩn bàn giao: [docs/team_plan.md](team_plan.md)


### 1.3. Bốn Cấp Độ Bằng Chứng Khoa Học & Phạm Vi Runner Chuỗi Thời Gian (Four-Level Evidentiary Hierarchy & Time-Series Scope)
Dự án thiết lập ranh giới phân định minh bạch qua bốn cấp độ bằng chứng thực nghiệm:
1. **Cấp 1 — Baseline Bài Báo Công Bố (Paper-Reported Baselines)**: Các số liệu bất biến được công bố trong MontazeriShatoori et al. (2020) (Bảng III, IV, V, VI).
2. **Cấp 2 — Baseline Thống Kê Quan Sát Được (Project-Observed Statistical)**: Số liệu độc lập trên 29 đặc trưng bảng từ Kaggle mirror (`dhoogla/cicdohbrw2020` v3), có tệp kê khai nguồn và commit Git sạch (`kaggle_phase1_l*_evidence.json`).
3. **Cấp 3 — Phương Pháp Luận & Mã Nguồn Chuỗi Thời Gian Đã Cài Đặt (Project-Implemented Time-Series)**: Toàn bộ pipeline tái lập và hiện đại hóa trong `src/doh_reproduction/` và `experiments/kaggle/timeseries_clump_lstm/` (đọc PCAP trực tiếp từ ZIP lồng nhau, gom cụm 1ms đã sửa lỗi, chuẩn hóa DoHLyzer, chia rời rạc 70/15/15, kiến trúc v4 paper và mô hình BiGRU cải tiến). Được bao phủ bởi hệ thống kiểm thử hành vi toàn diện (behavioral test suite) kiểm chứng cấu trúc dữ liệu, thuật toán gom cụm, bảo vệ chống zip-bomb và tính tương thích của mô hình.
4. **Cấp 4 — Kết Quả Thực Nghiệm Chuỗi Thời Gian Quan Sát Được (Project-Observed Time-Series)**: Hiện đang ở trạng thái **CHỜ THỰC THI (PENDING)** trong khi tập dữ liệu PCAP thô riêng tư được tải lại lên Kaggle. Mọi bảng kết quả hoặc slide trình chiếu **bắt buộc ghi nhận là `[Unavailable]`**, tuyệt đối không điền số giả lập `0.0` hay suy đoán kết quả.

* **Công bố về tham số huấn luyện khuyết thiếu trong bài báo**: Nhóm tác giả 2020 đã bỏ sót toàn bộ tham số tối ưu hóa (optimizer, learning rate, batch size, epoch budget, early stopping). Các tham số (Adam, lr=1e-3, batch=64, patience=5) là quyết định kỹ thuật của dự án nhằm phục vụ tái hiện, tuyệt đối không được mạo nhận là quy chuẩn của bài báo.
* **Không mạo nhận lợi ích khi chưa thực thi**: Mô hình BiGRU cải tiến nhận biết mặt nạ đệm và hàm mất mát có trọng số là đóng góp kiến trúc đã được cài đặt; hiệu năng thực tế phải chờ thực nghiệm chính thức trên Kaggle và không được tuyên bố là "lợi ích đã chứng minh" trước khi có kết quả quan sát.
---

## 2. Thiết Lập Kaggle CLI An Toàn (Secure Kaggle CLI Setup)

Quy trình quản lý danh tính Kaggle tuân thủ nghiêm ngặt nguyên tắc **Zero Credential Leakage**: Tuyệt đối không lưu trữ khóa API hoặc token trong Git, không in mã xác thực ra màn hình terminal, và thiết lập quyền truy cập tệp tối thiểu trên hệ điều hành.

```
┌─────────────────────────┐       Tải về       ┌──────────────────────────────┐
│  Kaggle Account Settings│ ─────────────────> │   ~/Downloads/kaggle.json    │
│  (API -> Create Token)  │                    │   {"username":"..","key":".."}│
└─────────────────────────┘                    └──────────────┬───────────────┘
                                                              │
                                            Di chuyển an toàn & phân quyền 600
                                                              ▼
                                               ┌──────────────────────────────┐
                                               │   ~/.kaggle/kaggle.json      │
                                               │   (chmod 600, KHÔNG COMMIT)  │
                                               └──────────────────────────────┘
```

### 2.1. Tạo Kaggle API Token từ Cài Đặt Tài Khoản
1. Đăng nhập vào tài khoản cá nhân tại [https://www.kaggle.com](https://www.kaggle.com).
2. Nhấp vào ảnh đại diện (avatar) ở góc trên bên phải màn hình và chọn **Settings** (hoặc truy cập trực tiếp `https://www.kaggle.com/settings`).
3. Cuộn trang xuống phần **API**.
4. Nhấp vào nút **Create New Token**. Trình duyệt sẽ tự động tải về một tệp có tên `kaggle.json`.
5. Tệp này chứa cặp khóa định danh dạng JSON:
   ```json
   {"username": "ten_nguoi_dung", "key": "chuoi_khoa_bi_mat_32_ky_tu"}
   ```

### 2.2. Vị Trí Lưu Trữ Độc Quyền & Cảnh Báo Thư Mục Dự Án
* **VỊ TRÍ HỢP LỆ DUY NHẤT:** Tệp `kaggle.json` chỉ được phép lưu tại thư mục cá nhân người dùng:
  ```text
  ~/.kaggle/kaggle.json
  ```
* **NGHIÊM CẤM:**
  * **TUYỆT ĐỐI KHÔNG** sao chép hoặc di chuyển `kaggle.json` vào thư mục dự án `doh_tunnel_detection/` hoặc bất kỳ vị trí nào trong Git workspace.
  * **TUYỆT ĐỐI KHÔNG** chia sẻ tệp `kaggle.json` qua tin nhắn, email hoặc tài liệu dùng chung.

### 2.3. Phân Quyền Tệp Tin Trên Hệ Điều Hành (macOS / POSIX Permissions)
Hệ điều hành macOS (và Linux) yêu cầu phân quyền hạn chế tối đa để các tiến trình khác hoặc người dùng khác trên cùng máy không thể đọc tệp khóa:

```bash
# 1. Tạo thư mục cấu hình ~/.kaggle nếu chưa tồn tại
mkdir -p ~/.kaggle

# 2. Giới hạn quyền truy cập thư mục: chỉ chủ sở hữu được đọc/ghi/thực thi
chmod 700 ~/.kaggle

# 3. Di chuyển tệp kaggle.json vừa tải về vào ~/.kaggle/
mv ~/Downloads/kaggle.json ~/.kaggle/kaggle.json

# 4. Giới hạn quyền đọc/ghi nghiêm ngặt: chỉ chủ sở hữu được đọc/ghi (read/write only)
chmod 600 ~/.kaggle/kaggle.json
```

### 2.4. Xác Minh Chứng Thực An Toàn (Không Hiển Thị Bí Mật)
Để kiểm tra thông tin chứng thực đã hợp lệ hay chưa mà **KHÔNG** làm lộ tên người dùng hay mã API ra stdout/logs:

```bash
# Xác minh an toàn: chuyển hướng đầu ra để không làm lộ token
kaggle datasets list --mine > /dev/null 2>&1 && echo "[XÁC MINH THÀNH CÔNG] Kaggle CLI đã kết nối hợp lệ." || echo "[LỖI] Xác thực Kaggle thất bại. Vui lòng kiểm tra ~/.kaggle/kaggle.json"
```

> **CẢNH BÁO BẢO MẬT:** Không sử dụng lệnh `cat ~/.kaggle/kaggle.json` hoặc echo biến chứa token trên màn hình làm việc chung.
>
> **Tài liệu tham khảo chính thức từ Kaggle:**
> * Kaggle Official Public API Documentation: [https://www.kaggle.com/docs/api](https://www.kaggle.com/docs/api)
> * Kaggle Official CLI GitHub Repository: [https://github.com/Kaggle/kaggle-api](https://github.com/Kaggle/kaggle-api)

---

## 3. Khởi Tạo Môi Trường Công Cụ Cô Lập (`bootstrap_cli.sh`)

Để đảm bảo công cụ Kaggle CLI hoạt động nhất quán giữa các thành viên mà không gây xung đột với thư viện Python toàn cục trên máy trạm:

### 3.1. Đặc Tính Kỹ Thuật Của Script Bootstrap
* Đường dẫn script: `doh_tunnel_detection/scripts/kaggle/bootstrap_cli.sh`.
* Tự động khởi tạo môi trường ảo chuyên biệt tại `.venv-tools/` (nằm ở thư mục gốc dự án) từ lệnh `python3` của hệ điều hành.
* Tự động tạo tệp `.venv-tools/.gitignore` chứa `*\n` để ngăn Git theo dõi toàn bộ nội dung môi trường ảo.
* Cài đặt và nâng cấp **duy nhất** gói `kaggle` bên trong `.venv-tools/`.
* **Tuyệt đối không xử lý thông tin xác thực:** Script không đọc, không ghi và không lưu trữ bất kỳ khóa API nào.

### 3.2. Lệnh Thực Thi Bootstrap
Từ thư mục `doh_tunnel_detection/`:

```bash
cd doh_tunnel_detection
bash scripts/kaggle/bootstrap_cli.sh
```

Kết quả mong đợi:
```text
Creating virtual environment at /path/to/project/.venv-tools...
Installing/upgrading kaggle in /path/to/project/.venv-tools...
Kaggle CLI successfully bootstrapped:
Kaggle API 1.x.x
```

---

## 4. Cấu Hình Biến Môi Trường Shell (`KAGGLE_KERNEL_ID`)

### 4.1. Quy Ước Định Danh Kernel
Mỗi thành viên sở hữu kernel Kaggle độc lập cho từng nhánh nghiên cứu dưới tài khoản của mình. Định danh kernel bắt buộc tuân theo định dạng:
```text
<kaggle_username>/<kernel_slug>
```
* Cho Runner Thống Kê Dạng Bảng: `<kaggle_username>/cicdohbrw2020-statistical-baseline`
* Cho Runner Chuỗi Thời Gian Packet-Clump: `<kaggle_username>/cicdohbrw2020-timeseries-lstm`
* Wrapper sẽ kiểm tra nghiêm ngặt định dạng này và tự động từ chối nếu tên chứa các chuỗi placeholder như `INSERT_KAGGLE_USERNAME`, `your_username`, hoặc để trống.

### 4.2. Thiết Lập Biến Trong Phiên Shell (Khuyến Nghị)
Thiết lập trực tiếp trong terminal đang làm việc tùy theo nhánh thực nghiệm:

```bash
# Nhánh 1: Baseline thống kê dạng bảng
export KAGGLE_KERNEL_ID="<your-kaggle-username>/cicdohbrw2020-statistical-baseline"

# Nhánh 2: Time-series packet-clump LSTM / BiGRU
export KAGGLE_TIMESERIES_KERNEL_ID="<your-kaggle-username>/cicdohbrw2020-timeseries-lstm"
```

### 4.3. Sử Dụng Tệp Cấu Hình Môi Trường Cục Bộ (`scripts/kaggle/.env`)
Dự án cung cấp tệp cấu hình mẫu `scripts/kaggle/.env.example`:
```bash
# Xem nội dung mẫu
cat scripts/kaggle/.env.example

# Tạo tệp môi trường cục bộ (tùy chọn)
cp scripts/kaggle/.env.example scripts/kaggle/.env
```
* Mở `scripts/kaggle/.env` và cập nhật dòng `KAGGLE_KERNEL_ID=...`.
* **QUY TẮC BẢO MẬT:** Tệp `.env` đã được liệt kê trong `.gitignore`. **TUYỆT ĐỐI KHÔNG commit tệp `.env` cá nhân vào Git**.

---

## 5. Quy Trình Thực Thi: Kiểm Toán Dữ Liệu Trước (Audit-First Workflow)

Do tập dữ liệu cộng đồng `dhoogla/cicdohbrw2020` chưa được kiểm chứng trực tiếp trên máy trạm về danh sách tệp con, tên cột thuộc tính, kiểu dữ liệu hay quy chuẩn đặt nhãn, nhóm áp dụng nguyên tắc: **"Thất bại rõ ràng thay vì suy đoán mơ hồ" (Fail clearly rather than guess)**.

Quy trình vận hành chia làm 2 giai đoạn tuần tự:
```
[Giai đoạn 1: Audit-First]
push_statistical_baseline.sh  ──>  status.sh (chờ complete)  ──>  pull_outputs.sh  ──>  schema_audit.json
                                                                               │
                                                                   Xác minh tệp bảng (Parquet/CSV) & Kiểm toán nhãn toàn bộ cột
                                                                               ▼
[Giai đoạn 2: Model Training]
Cấu hình data_file, task, label_column trong run_config.json  ──>  push  ──>  status (chờ complete)  ──>  pull (metrics, manifest)

> **QUY TẮC BẢO VỆ CẤU HÌNH:** Đợt kiểm toán Parquet ban đầu đã xác nhận sự hiện diện của 2 tệp bảng v3 và cột `Label`, nhưng mẫu hàng đầu tiên (first-rows sample) chỉ ghi nhận `DoH` cho L1 và `Benign` cho L2. Mẫu hàng đầu này là **không đầy đủ** để chọn ánh xạ nhãn huấn luyện. Tuyệt đối không coi các giá trị mẫu `DoH` hay `Benign` là phân bố lớp toàn vẹn. Đợt kiểm toán tiếp theo sẽ tính toán số lượng nhãn chính xác trên toàn bộ cột (full-column label counts) trước khi bất kỳ cấu hình huấn luyện nào được phê duyệt. Tệp `run_config.json` **bắt buộc duy trì ở chế độ audit (`"mode": "audit"`)** cho đến khi các số đếm này được rà soát xong.

### 5.1. Bước 1: Đẩy Kernel Thực Hiện Kiểm Toán Schema (Push Audit)
Trong cấu hình mặc định (khi `mode` là `"audit"` hoặc chưa cấu hình `data_file`), script `train_statistical.py` sẽ tự động quét toàn bộ cây thư mục `/kaggle/input/`, tính toán mã băm SHA-256, kiểm tra cấu trúc bảng Parquet và CSV, kết xuất `schema_audit.json` và kết thúc thành công.

Chạy lệnh đẩy mã nguồn lên Kaggle:
```bash
cd doh_tunnel_detection
bash scripts/kaggle/push_statistical_baseline.sh
```

**Cơ chế hoạt động của wrapper `push_statistical_baseline.sh`:**
1. Kiểm tra biến `KAGGLE_KERNEL_ID`.
2. Kiểm tra trạng thái theo dõi Git: kiểm tra worktree cha; nếu mã nguồn kernel được Git theo dõi và ở trạng thái sạch (tracked and clean), gán `KAGGLE_GIT_SHA` bằng mã commit SHA đó. Nếu mã nguồn chưa được commit (untracked) hoặc có thay đổi chưa commit (dirty), gán `KAGGLE_GIT_SHA="unknown_uncommitted_source"` để đảm bảo xuất xứ trung thực và không đưa ra tuyên bố sai lệch.
3. Tạo thư mục tạm thời ngoài Git (`/tmp/kaggle_push.XXXXXX`).
4. Kết xuất tệp siêu dữ liệu tạm thời `kernel-metadata.json`, thay thế placeholder bằng `$KAGGLE_KERNEL_ID` và kiểm tra để đảm bảo không còn bất kỳ mẫu placeholder nào.
5. Sao chép các tệp kernel khai báo (`train_statistical.py`, `run_config.json`, `requirements.txt`, `README.md`) vào thư mục tạm.
6. **Đọc, kiểm thực `run_config.json` và tiêm an toàn vào mã nguồn kernel:** Do Kaggle chỉ tải lên tệp mã nguồn được khai báo (`train_statistical.py`) đối với Script kernel, tệp `run_config.json` rời không tự động hiện diện trong container Kaggle. Wrapper đọc và kiểm thực cấu hình cục bộ, sau đó tiêm chuỗi cấu hình JSON an toàn vào hằng số `EMBEDDED_CONFIG_JSON` của `train_statistical.py` trong thư mục tạm trước khi tính mã băm snapshot. Script kernel từ xa sẽ ưu tiên phân giải cấu hình nhúng này, ghi nhận nguồn `embedded` và lưu vết chính xác cấu hình trong manifest.
7. Tính toán mã băm SHA-256 xác định trên chính xác các tệp kernel được sao chép (`KAGGLE_SOURCE_SNAPSHOT_SHA256`).
8. Tiêm trực tiếp `KAGGLE_GIT_SHA` và `KAGGLE_SOURCE_SNAPSHOT_SHA256` vào môi trường runtime của `train_statistical.py` trong thư mục tạm, đảm bảo mọi lần chạy trên Kaggle đều ghi nhận chính xác băm snapshot nội dung và ngữ cảnh Git thực tế.
9. Gọi `.venv-tools/bin/kaggle kernels push -p <temp_dir>`.
10. Tự động xóa thư mục tạm thời sau khi kết thúc.

*Lưu ý cốt lõi về kiểm toán nhãn (Đợt kiểm toán ban đầu vs Đợt kiểm toán toàn diện):*
- **Kết quả đợt kiểm toán ban đầu:** Đợt kiểm toán Parquet ban đầu đã xác lập thành công danh sách tệp (`L1-DoH-NonDoH.parquet`, `L2-BenignDoH-MaliciousDoH.parquet`), cấu trúc thuộc tính (schema) và cột nhãn mục tiêu `Label`.
- **Hạn chế của mẫu hàng đầu (First-rows sample is insufficient):** Trong đợt kiểm toán ban đầu, trường trích xuất nhãn ứng viên chỉ lấy mẫu các hàng đầu tiên (first-rows sample), dẫn đến việc chỉ quan sát thấy duy nhất giá trị `DoH` đối với L1 và `Benign` đối với L2. Dữ liệu bảng Parquet thường được gom cụm hoặc sắp xếp theo lớp, do đó mẫu hàng đầu tiên hoàn toàn không đại diện cho phân bố nhãn toàn tập dữ liệu.
- **Quy tắc nghiêm ngặt:** Tuyệt đối không một tài liệu hay quy trình nào được coi các giá trị mẫu `DoH` hay `Benign` là phân bố lớp hoàn chỉnh. Không được suy đoán tập dữ liệu chỉ có một lớp hoặc phê duyệt ánh xạ huấn luyện từ mẫu hàng chưa đầy đủ.
- **Đợt kiểm toán kế tiếp (Full-Label Count Audit):** Script kiểm toán sẽ thực hiện chiếu cột (column projection) trên Parquet để đọc duy nhất cột `Label` trên toàn bộ tập dữ liệu, tính toán chính xác số lượng từng lớp (`value_counts`), số lượng null (`null_count`), và gắn cờ `complete_column_audit: true` (`is_complete_audit: true`) trước khi bất kỳ cấu hình huấn luyện nào được phê duyệt.
- **Trạng thái cấu hình bắt buộc:** Tệp `run_config.json` **bắt buộc duy trì ở chế độ kiểm toán (`"mode": "audit"`)** cho đến khi các số đếm nhãn đầy đủ này được tải về, rà soát và phê duyệt chính thức.
### 5.2. Bước 2: Theo Dõi Trạng Thái Thực Thi (Status Check)
Sau khi đẩy kernel, Kaggle sẽ đưa tác vụ vào hàng đợi và phân bổ tài nguyên CPU:

```bash
bash scripts/kaggle/status.sh
```

Kết quả phản hồi từ Kaggle CLI:
* `queued`: Kernel đang chờ phân bổ máy ảo CPU (chưa có kết quả; tuyệt đối không chạy `pull_outputs.sh`).
* `running`: Kernel đang thực thi script kiểm toán / huấn luyện (đang xử lý; tuyệt đối không chạy `pull_outputs.sh`).
* `complete`: Kernel đã thực thi xong thành công, các tạo tác đã sẵn sàng tải về.
* `error`: Kernel gặp lỗi thực thi (xem log chi tiết trên giao diện Kaggle hoặc tải output lỗi).

### 5.3. Bước 3: Tải Tạo Tác Về Cục Bộ (Pull Outputs)
> **ĐIỀU KIỆN TIÊN QUYẾT BẮT BUỘC:** Lệnh `pull_outputs.sh` **chỉ được phép thực thi sau khi lệnh `status.sh` báo trạng thái hoàn tất (`complete`)**. Tuyệt đối không thực thi lệnh tải khi kernel đang ở hàng đợi (`queued`) hoặc đang trong quá trình thực thi (`running`). Mọi nỗ lực tải kết quả khi kernel chưa hoàn tất đều là thao tác không hợp lệ.
>
> **Cơ chế bảo vệ kép (Status Guard & Empty Artifact Guard):**
> 1. **Khóa trạng thái hoàn tất (Status Guard):** Trước khi tạo thư mục đích hay tải dữ liệu, `pull_outputs.sh` tự động truy vấn trạng thái kernel từ Kaggle CLI. Nếu kernel đang ở trạng thái `queued`, `running` hoặc bất kỳ trạng thái nào chưa `complete`, script sẽ lập tức từ chối thực thi (thoát với mã lỗi khác 0), in rõ trạng thái quan sát được và hướng dẫn người dùng tiếp tục theo dõi bằng `status.sh` mà không tạo hoặc thay đổi thư mục đích.
> 2. **Chống tải tạo tác rỗng (Empty Download Guard):** Sau khi hoàn tất lệnh tải từ Kaggle, script kiểm tra sự tồn tại của các tệp dữ liệu thông thường (regular files) trong thư mục đích. Nếu không có bất kỳ tệp dữ liệu hợp lệ nào được tải về (thư mục rỗng), script sẽ từ chối xác nhận hoàn tất, báo lỗi thất bại và thoát với mã khác 0 thay vì báo thành công sai lệch.

Khi trạng thái xác nhận `complete`, chạy wrapper tải kết quả:

```bash
bash scripts/kaggle/pull_outputs.sh
```

* Toàn bộ tạo tác đầu ra sẽ được tải về thư mục:
  ```text
  doh_tunnel_detection/artifacts/kaggle/<kernel-slug>/
  ```
* **Cơ chế chống ghi đè nhầm (Overwrite Guard):** Nếu thư mục đích đã tồn tại và chứa dữ liệu, script sẽ từ chối tải đè để bảo vệ kết quả trước đó. Để ghi đè có chủ đích, thêm cờ `--force`:
  ```bash
  bash scripts/kaggle/pull_outputs.sh --force
  ```
---

## 6. Đọc Hiểu & Phân Tích Tệp `schema_audit.json`

Sau khi tải tạo tác về máy trạm, mở và kiểm tra tệp kiểm toán:

```bash
python3 -m json.tool artifacts/kaggle/cicdohbrw2020-statistical-baseline/schema_audit.json | head -n 80
```

### 6.1. Cấu Trúc Thông Tin Của `schema_audit.json`
Tệp kiểm toán cung cấp hồ sơ toàn diện về dữ liệu thực tế trên Kaggle:

| Khối thông tin | Ý nghĩa & Dữ liệu cung cấp |
| :--- | :--- |
| `audit_version` | Phiên bản lược đồ kiểm toán (`1.0.0`). |
| `input_directory` | Đường dẫn thư mục quét dữ liệu (`/kaggle/input`). |
| `total_tabular_files_discovered` | Số lượng tệp bảng (Parquet/CSV) được phát hiện trong tập dữ liệu. |
| `discovered_tabular_files` | Danh sách từng tệp: `filename`, `relative_path`, `size_bytes`, `sha256`. |
| `schemas` | Chi tiết cấu trúc từng tệp: `total_rows`, `total_columns`, `column_names`, `dtypes`. |
| `candidate_label_columns` (hoặc `candidate_labels`) | Thông tin kiểm toán toàn diện từng cột nhãn ứng viên: cờ `complete_column_audit` (`is_complete_audit`), số đếm chính xác từng giá trị nhãn trên toàn bộ cột (`value_counts`), `null_count`, `total_rows`, `unique_count`, và bản xem trước giới hạn (`sample_unique_values` bổ trợ). Đảm bảo không dựa vào mẫu hàng đầu để suy đoán phân bố nhãn. |

### 6.2. Quy Tắc Đối Chiếu & Xác Định Nhãn Trước Khi Huấn Luyện
> **CẢNH BÁO QUAN TRỌNG VỀ PHÂN BỐ NHÃN:**  
> Đợt kiểm toán Parquet ban đầu đã xác nhận sự tồn tại của hai tệp bảng v3 và cột `Label`. Tuy nhiên, kết quả trích mẫu hàng đầu (first-rows sample) chỉ ghi nhận `DoH` đối với L1 và `Benign` đối với L2. Kết quả mẫu hàng đầu này **hoàn toàn không đủ cơ sở** để lựa chọn hay phê duyệt ánh xạ nhãn huấn luyện.  
> **Tuyệt đối không coi các giá trị mẫu `DoH` hay `Benign` là phân bố lớp hoàn chỉnh.** Đợt kiểm toán kế tiếp sẽ tính toán số đếm chính xác trên toàn bộ cột từ duy nhất cột nhãn (`complete_column_audit: true`). Tệp `run_config.json` **bắt buộc duy trì ở chế độ `"audit"`** cho đến khi số đếm nhãn đầy đủ này được kiểm tra và phê duyệt.

Từ kết quả kiểm toán toàn diện (full-label counts), nhóm nghiên cứu xác định:
1. **Tệp bảng mục tiêu (`--data-file`):** Tệp bảng tổng hợp phù hợp (cụ thể với v3 là `L1-DoH-NonDoH.parquet` hoặc `L2-BenignDoH-MaliciousDoH.parquet`).
2. **Cột nhãn chuẩn xác (`--label-column`):** Xác định chính xác tên cột chứa nhãn phân loại (ví dụ: `Label`, `label`, `Class`). Nếu trong CSV có nhiều hơn một cột nhãn ứng viên, script huấn luyện bắt buộc phải có đối số `--label-column`.
3. **Ánh xạ giá trị nhãn theo 2 tầng phân loại:**
   * **Tầng 1 - DoH vs Non-DoH (`--task l1`):**
     * Nhóm DoH (nhãn dương `1`): các giá trị như `DoH`, `benign_doh`, `malicious_doh`, `DNS-over-HTTPS`.
     * Nhóm Non-DoH (nhãn âm `0`): các giá trị như `NonDoH`, `non-doh`, `benign_nondoh`.
   * **Tầng 2 - Benign DoH vs Malicious Tunnel (`--task l2`):**
     * Nhóm Malicious Tunnel (nhãn dương `1`): các công cụ đường hầm như `Malicious`, `Iodine`, `dnscat2`, `dns2tcp`.
     * Nhóm Benign DoH (nhãn âm `0`): lưu lượng duyệt web chuẩn như `Benign`, `Firefox`, `Chrome`.

---

## 7. Huấn Luyện Baseline Thống Kê (Model Training Run)

Sau khi kiểm toán xác nhận schema dữ liệu, tiến hành chạy thực nghiệm huấn luyện baseline trên Kaggle.

### 7.1. Bảng Tham Số Dòng Lệnh Của `train_statistical.py`

| Tham số | Kiểu dữ liệu | Giá trị mặc định | Mô tả chi tiết |
| :--- | :--- | :--- | :--- |
| `--input-dir` | `Path` | `/kaggle/input` | Thư mục chứa tập dữ liệu Kaggle đầu vào. |
| `--output-dir` | `Path` | `/kaggle/working` | Thư mục xuất các tệp tạo tác kết quả. |
| `--data-file` | `string` | `None` | Tên tệp bảng (`.parquet` hoặc `.csv`) được chọn để huấn luyện (`--csv-file` được hỗ trợ dưới dạng alias tương thích ngược; nếu bỏ trống: chỉ chạy audit). |
| `--task` | `string` | `None` | Nhiệm vụ phân loại: `l1` (DoH vs Non-DoH) hoặc `l2` (Benign vs Malicious). |
| `--label-column` | `string` | `None` | Tên cột nhãn ground-truth (bắt buộc nếu phát hiện nhiều cột nhãn). |
| `--model` | `string` | `all` | Mô hình huấn luyện: `all`, `random_forest`, `decision_tree`, `gaussian_nb`, `linear_svm`, `hist_gradient_boosting`. |
| `--enable-score-calibration` | `Flag` | `None` | Bật hiệu chuẩn xác suất hậu nghiệm (Platt scaling) và chọn ngưỡng vận hành khống chế FPR. |
| `--validation-fraction` | `float` | `0.25` | Tỷ lệ phân tách outer-train thành model-train và validation cho hiệu chuẩn điểm. |
| `--target-false-positive-rate` | `float` | `0.001` | Ngưỡng FPR tối đa mục tiêu khi lựa chọn ngưỡng vận hành trên tập validation. |
| `--feature-ablation` | `string` | `none` | Đánh giá cắt bỏ nhóm đặc trưng (`none` hoặc `group`) bằng Random Forest. |
| `--seed` | `int` | `42` | Random seed cố định đảm bảo tính tái lập. |
| `--split` | `string` | `paper_flow_random_80_20` | Giao thức phân chia luồng ngẫu nhiên 80/20 theo bài báo. |
| `--max-samples-per-class`| `int` | `None` | Giới hạn số mẫu mỗi lớp phục vụ kiểm thử nhanh (optional). |
| `--dataset-slug` | `string` | `dhoogla/cicdohbrw2020` | Định danh tập dữ liệu Kaggle. |
| `--dataset-version` | `string` | `3` | Số hiệu phiên bản tập dữ liệu. |

> **LƯU Ý VỀ CÁC MÔ HÌNH BỊ LOẠI TRỪ:**  
> * **Không sử dụng RBF Kernel SVM:** Tập dữ liệu luồng có quy mô hàng trăm nghìn mẫu. Thuật toán SVM nhân RBF có độ phức tạp tính toán $O(n^2)$ đến $O(n^3)$, gây quá tải và tràn bộ nhớ trên môi trường CPU của Kaggle. Thay vào đó, script sử dụng `LinearSVC` với thời gian hội tụ tuyến tính.  
> * **Không sử dụng mạng LSTM:** Dữ liệu dạng bảng không có cấu trúc chuỗi thời gian gói tin, không thể áp dụng mạng hồi quy tuần tự.
> * **HistGradientBoosting:** `HistGradientBoostingClassifier(random_state=seed, max_iter=100)` được tích hợp như mô hình gradient boosting chuẩn CPU determinism trong `model: "all"`.
> * **Tạo tác Phase 1:** Khi huấn luyện Random Forest trên toàn bộ đặc trưng, tệp `feature_importance_random_forest.csv` được kết xuất; khi bật `feature_ablation: "group"`, tệp `feature_ablations.json` ghi nhận đánh giá cắt bỏ từng nhóm (`flow_volume`, `packet_length`, `packet_timing`, `response_timing`).

### 7.2. Giao Thức Phân Chia Dữ Liệu: So Sánh Đối Chứng Bài Báo
* Script triển khai phân chia tầng ngẫu nhiên tỷ lệ 80% train / 20% test ở cấp độ luồng (`paper_flow_random_80_20`).
* Phân chia này được thiết kế **CHỈ DÙNG ĐỂ SO SÁNH ĐỐI CHỨNG VỚI CÁC BẢNG KẾT QUẢ III–VI CỦA BÀI BÁO GỐC**.
* Giao thức phân chia hiện đại không rò rỉ theo phiên (`session-disjoint split`) chỉ được kích hoạt khi tệp kiểm toán xác nhận tập dữ liệu có chứa các cột thông tin nguồn gốc phiên (ví dụ: `session_id`, `scenario`, hoặc dải nhãn thời gian thô).

### 7.3. Cấu Hình Huấn Luyện & Đẩy Chạy
> **ĐIỀU KIỆN TIÊN QUYẾT:** `run_config.json` bắt buộc duy trì ở chế độ `"audit"` cho đến khi số đếm nhãn đầy đủ (full-column label counts) được rà soát và phê duyệt. Tuyệt đối không cấu hình huấn luyện dựa trên mẫu hàng đầu tiên.

Chỉ sau khi đã xác thực đầy đủ phân bố lớp qua `schema_audit.json`, người dùng mới cập nhật `run_config.json` (chuyển sang `mode: "train"`, chỉ định `data_file`, `task`, `label_column` đã được kiểm toán xác nhận), commit vào Git, sau đó thực hiện chu trình:

```bash
# 1. Đẩy mã nguồn huấn luyện
bash scripts/kaggle/push_statistical_baseline.sh

# 2. Theo dõi cho đến khi complete (bắt buộc trước khi pull)
bash scripts/kaggle/status.sh

# 3. Tải kết quả về (chỉ chạy sau khi status báo complete; script tự động từ chối nếu kernel đang queued/running hoặc kết xuất rỗng)
bash scripts/kaggle/pull_outputs.sh --force
```

---

## 8. Vận Hành Runner Chuỗi Thời Gian Packet-Clump (Phase 2 Raw-PCAP Time-Series Runner)

Nhánh thực nghiệm Phase 2 tái hiện trực tiếp mô hình chuỗi thời gian nơ-ron hồi quy (Packet Clumping + LSTM/BiGRU) từ dữ liệu bắt gói mạng thô (Raw PCAP) theo phương pháp luận của MontazeriShatoori et al. (2020) và mã nguồn tham chiếu DoHLyzer.

### 8.1. Kiến Trúc Tệp Nén Lồng Nhau & Cơ Chế Đọc Luồng (Streaming Ingestion & Cumulative Budget)
* **Cấu trúc lưu trữ raw archive**: Tập dữ liệu thô `PCAPs.zip` (35 tệp, tổng dung lượng giải nén `80,870,581,876` bytes ~ 80 GB) chứa cả các tệp PCAP độc lập và các tệp nén ZIP lồng nhau (nested ZIP archives) tương ứng với từng phiên thu thập và kịch bản tấn công.
* **Cơ chế đọc luồng (Streaming Decompression mà không giải nén ra đĩa)**:
  Môi trường Kaggle bị giới hạn đĩa làm việc (`/kaggle/working` tối đa 20 GB). Do đó, module `src/doh_reproduction/raw_dataset.py` duyệt cấu trúc tệp ZIP ảo trên bộ nhớ và sử dụng `open_stream()` để mở luồng giải nén trực tiếp từng thành viên PCAP (hoặc giải nén tạm thời một thành viên lồng nhau có giới hạn kích thước). Tuyệt đối **không giải nén toàn bộ 80 GB ra ổ cứng**, chống tràn đĩa 100%.
* **Ngăn chặn Zip Bomb & Quản lý ngân sách giải nén (`_CumulativeBudgetTracker`)**:
  * `max_standalone_capture_bytes`: 20 GB (kích thước tối đa cho tệp PCAP đơn lẻ).
  * `max_member_bytes`: 10 GB (kích thước tối đa cho một thành viên PCAP trong archive).
  * `max_nested_archive_bytes`: 25 GB (kích thước tối đa cho tệp ZIP lồng nhau).
  * `max_total_uncompressed_bytes`: 200 GB (ngân sách giải nén tích lũy toàn phiên).
  * `max_compression_ratio`: 100.0 (tỷ lệ nén tối đa cho phép; giới hạn rủi ro giải nén tệp độc hại theo cơ chế fail-closed: lập tức từ chối và ngắt tiến trình đối với các archive vượt ngưỡng tỷ lệ nén hoặc khai báo kích thước không hợp lệ trước khi giải nén).

### 8.2. Tiêu Chuẩn Trích Xuất Gói Tin & Lắp Ghép Luồng (Packet Decoding & Flow Assembly)
* **Lazy dpkt Loader**: Thư viện `dpkt` được nạp trễ an toàn trong `src/doh_reproduction/pcap.py`, xử lý cả định dạng PCAP chuẩn lẫn PCAPNG.
* **Bộ lọc dữ liệu ứng dụng TLS (TLS Application Data Filter)**:
  * Chỉ chấp nhận các bản ghi TLS có **Content Type = 23** (`TLS_RECORD_APPLICATION_DATA` theo RFC 5246 / RFC 8446).
  * **Ngưỡng tải trọng tối thiểu**: `DEFAULT_MIN_TLS_APP_BYTES = 40` bytes. Quy chuẩn này (theo DoHLyzer) loại bỏ triệt để các khung điều khiển nhỏ như HTTP/2 PING frame (độ dài 34 bytes), TLS handshakes, các gói tin ACK rỗng hoặc các thông điệp giữ kết nối (keepalive) không mang dữ liệu DNS.
* **Hết hạn luồng (Flow Expiry)**: `DEFAULT_FLOW_TIMEOUT_SECONDS = 40.0` giây (chuẩn `EXPIRED_UPDATE = 40` trong DoHLyzer). Các gói tin cùng 5-tuple nhưng cách nhau $> 40\text{ s}$ được tách thành các luồng độc lập.
* **Xác định chiều luồng (Direction Assignment)**:
  Gói tin TLS Application Data hợp lệ đầu tiên xuất hiện trong luồng sẽ định danh `client_ip:client_port` là bên khởi tạo (chiều đi - forward, giá trị `0`). Chiều ngược lại từ máy chủ `server_ip:server_port` về máy khách là chiều về (backward, giá trị `1`).

### 8.3. Thuật Toán Gom Cụm 1ms & Sửa 2 Lỗi Thuật Toán 1 Bài Báo Gốc
* **Định nghĩa Cụm (Packet Clump)**:
  Mỗi cụm là một 5-tuple $(size, pkt\_count, direction, duration, interarrival)$ gom các gói tin truyền liên tiếp cùng chiều có khoảng cách thời gian $dt \le \tau = 0.001\text{ s}$ (1 millisecond).
* **Sửa 2 lỗi in ấn nghiêm trọng trong Thuật toán 1 của bài báo**:
  1. **Lỗi đảo ngược logic ngắt vòng lặp (Termination Logic Inversion)**:
     Trong bài báo gốc (Hình 4 / Thuật toán 1, dòng 6), điều kiện ngắt vòng lặp được in là `packets[counter].direction == nextPacket.direction`. Điều này dẫn đến việc vòng lặp bị ngắt ngay lập tức khi gặp gói tin *cùng chiều*, làm toàn bộ luồng bị vỡ vụn thành các cụm đơn lẻ (1 gói tin/cụm). Dự án sửa lại chính xác theo mã nguồn DoHLyzer: chỉ ngắt cụm khi `packets[counter].direction != nextPacket.direction` HOẶC `timePassed > 0.001\text{ s}`.
  2. **Lỗi tràn biên mảng (Array Bounds Check Crash)**:
     Dòng 9 trong Thuật toán 1 của bài báo truy cập `packets[counter]` ngay sau khi tăng biến đếm `counter = counter + 1` mà không kiểm tra độ dài mảng, gây lỗi IndexError/Segmentation Fault khi đọc đến gói tin cuối cùng. Dự án bổ sung kiểm tra chặn `if counter >= len(packets): break` trước khi truy cập.

### 8.4. Chuẩn Hóa DoHLyzer, Vector Đệm & Thứ Tự Đặc Trưng
Mô hình chuỗi thời gian tuân thủ nghiêm ngặt chuẩn dữ liệu DoHLyzer (`src/doh_reproduction/timeseries_data.py`):
* **Thứ tự đặc trưng chuẩn (`PAPER_REFERENCE_FEATURE_ORDER`)**:
  ```python
  ["interarrival", "duration", "size", "packet_count", "direction"]
  ```
* **Vector đệm chuẩn (`PADDING_VECTOR`)**:
  `[-1.0, -1.0, -1.0, -1.0, 0.0]` (được áp dụng khi chuỗi cụm ngắn hơn độ dài cửa sổ $\ell$).
* **Phương trình chuẩn hóa phi tuyến (DoHLyzer Normalization Equations)**:
  * **Thời gian (Interarrival & Duration)**:
    $$\text{norm}(x) = \frac{\log_{10}(\max(10^{-12}, x)) - (-12)}{-2 - (-12)}$$
  * **Kích thước cụm (Size in bytes)**:
    $$\text{norm}(s) = \frac{\log_{10}(\min(10^4, \max(10^{-12}, s))) - 0.5}{4.0 - 0.5}$$
  * **Số lượng gói tin (Packet Count)**:
    $$\text{norm}(c) = \frac{\log_2(\min(256, \max(1, c))) - 0}{8.0 - 0.0}$$
  * **Chiều truyền tải (Direction)**:
    Client $\to$ Server (Forward, 0) $\to +1.0$; Server $\to$ Client (Backward, 1) $\to -1.0$.

### 8.5. Cửa Sổ Trượt $\ell \in [1, 10]$ & Đánh Giá Nhận Diện Sớm
* Đường ống sinh ra các cửa sổ trượt độ dài $\ell \in [1, 10]$ với bước nhảy stride = 1.
* **Tầng 1 (DoH vs Non-DoH)**: Bảng V của bài báo chỉ ra điểm tối ưu tại $\ell = 6$ ($F_1 = 0.993$, độ trễ trung bình chỉ $0.574\text{ s}$, giảm $97.2\%$ thời gian so với chờ hết luồng $20.393\text{ s}$).
* **Tầng 2 (Benign DoH vs Malicious DoH)**: Bảng VI của bài báo chỉ ra điểm tối ưu tại $\ell = 3$ ($F_1 = 0.991$, độ trễ trung bình $0.502\text{ s}$, giảm $99.1\%$ thời gian so với chờ hết luồng $53.924\text{ s}$).

### 8.6. Kiến Trúc Mạng Nơ-ron v4 Bài Báo & Công Bố Tham Số Khuyết Thiếu
* **Tái tạo kiến trúc v4 (`PaperReferenceLSTMModel`)**:
  Được khôi phục nguyên bản từ mã nguồn `v4.py` của DoHLyzer:
  1. `Dense(5 -> 10, ReLU)` chiếu từng bước cụm gói tin.
  2. `LSTM(input_size=10, hidden_size=8*l, batch_first=True)` trích xuất đặc trưng chuỗi.
  3. `Dense(8*l -> 6*l, ReLU)` nén đặc trưng.
  4. `Dropout(p=0.2)` chống quá khớp.
  5. `Dense(6*l -> 2*l, ReLU)` lớp ẩn phân loại.
  6. `Dense(2*l -> 1, Sigmoid)` xuất xác suất nhị phân.
* **Công bố minh bạch về tham số khuyết thiếu (Hyperparameter Omission Disclaimer)**:
  Bài báo của MontazeriShatoori et al. (2020) **hoàn toàn không công bố**: thuật toán tối ưu (optimizer), tốc độ học (learning rate), kích thước batch, số epoch, hay điều kiện dừng sớm.
  Trong dự án này, các tham số: **Adam, learning rate = 0.001, batch size = 64, epochs = 15, patience = 5** là **quyết định kỹ thuật tái hiện của dự án**, tuyệt đối **KHÔNG ĐƯỢC MẠO NHẬN** là thông số của bài báo gốc.

### 8.7. Giao Thức Phân Chia: Rò Rỉ 80/20 vs Phân Chia Rời Rạc 70/15/15
* **Cảnh báo rò rỉ 80/20 ngẫu nhiên (Paper Split Flaw)**:
  Phân chia ngẫu nhiên ở cấp độ luồng (flow-level) làm phân tán các luồng từ cùng một phiên duyệt web hoặc cùng một đợt chạy C2 sang cả tập train và test. Các luồng này có chung dấu vết TLS Client Hello, danh sách cipher suite, và TCP window scale. Mô hình có xu hướng ghi nhớ các đặc trưng phiên thay vì học hành vi tunneling DoH thực tế.
* **Giao thức hiệu chỉnh phân chia rời rạc 70/15/15 (Corrected Group-Disjoint Protocol)**:
  Phân chia tập dữ liệu thành Train (70%), Validation (15%), Test (15%) nhóm triệt để theo `session_id` và `scenario_id`. Toàn bộ các luồng từ một phiên capture chỉ xuất hiện duy nhất ở một phân vùng, bảo đảm 0% rò rỉ phiên và đo lường chính xác năng lực tổng quát hóa đối với các phiên mạng chưa từng thấy.

### 8.8. Mô Hình Cải Tiến: Mask-Aware BiGRU với Attention Pooling & Hiệu Chuẩn
* **Kiến trúc `ImprovedMaskedBiGRUModel`**:
  * **GRU hai chiều (Bidirectional GRU, hidden_dim=64)**: nắm bắt ngữ cảnh truyền gói tin theo cả chiều xuôi và ngược.
  * **Attention Pooling nhận biết mặt nạ đệm (Mask-Aware Attention Pooling)**: tự động phát hiện các vector đệm `[-1.0, -1.0, -1.0, -1.0, 0.0]` và gán điểm attention trước softmax thành $-\infty$. Cơ chế này ngăn chặn hiện tượng làm méo đạo hàm từ các bước đệm nhân tạo.
  * **Hàm mất mát BCE có trọng số (Class-Weighted BCE)**: `pos_weight` được tính toán trực tiếp từ tỷ lệ phân bố lớp của tập Train nhằm xử lý mất cân bằng dữ liệu nghiêm trọng ở Tầng 2.
  * **Hiệu chuẩn điểm Platt Scaling trên Validation**: Khớp mô hình hồi quy logistic trên logits của tập Validation nhằm chọn ngưỡng vận hành tối ưu khống chế $\text{FPR} \le 0.001$ ($0.1\%$).
* **Ranh giới tuyên bố khoa học (Strict Non-Claim)**:
  Toàn bộ mô hình cải tiến đã được cài đặt hoàn chỉnh và kiểm thử thành công trong mã nguồn (`timeseries_models.py`), nhưng **kết quả thực nghiệm trên tập PCAP thô hiện đang chờ thực thi trên Kaggle**. Do đó, trong mọi bảng kết quả và tài liệu báo cáo, chỉ được phép trình bày đây là *đóng góp về mặt thiết kế kiến trúc*, tuyệt đối không mạo nhận là "đã chứng minh được hiệu năng vượt trội trên thực tế" cho đến khi có số liệu quan sát từ Kaggle.

### 8.9. Hạn Ngạch Bắt Buộc & Giới Hạn Tài Nguyên (Finite Caps in `run_config.json`)
Để đảm bảo kernel không bị Kaggle ngắt tiến trình do vượt quá giới hạn CPU thời gian chạy (9 giờ) hoặc dung lượng RAM (30 GB), tệp `experiments/kaggle/timeseries_clump_lstm/run_config.json` thiết lập các hạn ngạch an toàn:

| Tham số hạn ngạch | Giá trị mặc định | Mục đích bảo vệ tài nguyên |
| :--- | :---: | :--- |
| `max_capture_members` | `20,000` | Trần discovery cao hơn inventory quan sát 13,754 capture; huấn luyện vẫn dừng sớm theo quota luồng mỗi lớp. |
| `max_flows_per_class` | `500` | Số lượng luồng tối đa thu thập cho mỗi lớp (được áp dụng theo nhãn luồng thực tế). |
| `max_flows_per_capture` | `25` | Ngăn một capture/session chiếm hết quota lớp trước khi split group-disjoint. |
| `max_raw_packets` | `1,000,000` | Giới hạn tối đa 1 triệu gói tin thô được quét mỗi capture. |
| `max_raw_bytes` | `1,073,741,824` | Giới hạn tối đa 1 GB dữ liệu gói tin thô mỗi capture. |
| `max_capture_packets` | `200,000` | Giới hạn 200 nghìn gói tin TLS Application Data được chấp nhận mỗi capture. |
| `max_capture_bytes` | `536,870,912` | Giới hạn 512 MB dữ liệu TLS Application Data mỗi capture. |
| `max_flow_packets` | `10,000` | Giới hạn 10 nghìn gói tin TLS mỗi luồng đơn lẻ. |
| `max_flow_bytes` | `52,428,800` | Giới hạn 50 MB dữ liệu TLS mỗi luồng đơn lẻ. |
| `max_windows_per_flow` | `1,000` | Giới hạn tối đa 1 nghìn mẫu cửa sổ cụm được sinh ra từ một luồng. |
| `max_windows_per_class` | `10,000` | Giới hạn tối đa 10 nghìn mẫu cửa sổ cụm cho mỗi lớp huấn luyện. |
| `target_false_positive_rate` | `0.001` | Ngưỡng FPR tối đa mục tiêu ($0.1\%$) khi chọn ngưỡng vận hành Platt scaling. |

### 8.10. Quy Trình 2 Giai Đoạn: Audit-First rồi mới Huấn Luyện
Tương tự như nhánh thống kê, nhánh chuỗi thời gian tuân thủ nghiêm ngặt quy trình:
1. **Giai đoạn 1: Audit Mode (`mode: "audit"`)**:
   * Quét toàn bộ cây thư mục `/kaggle/input/cicdohbrw2020-raw-pcaps`, kiểm toán kích thước, băm SHA-256, phân tích scenario và session.
   * Xuất tệp `pcap_audit.json` và kết thúc với exit code 0 mà không huấn luyện mô hình.
   * Người dùng tải `pcap_audit.json` về máy trạm để kiểm tra tính toàn vẹn và xác thực phân bổ phiên.
2. **Giai đoạn 2: Training Mode (`mode: "train"`)**:
   * Chỉ sau khi `pcap_audit.json` được phê duyệt, người dùng cập nhật `run_config.json` sang `mode: "train"`, commit vào Git để có Git SHA sạch, và đẩy chạy huấn luyện chính thức.

### 8.11. Các Lệnh CLI Wrapper Cho Time-Series

```bash
# 1. Tải lên tập dữ liệu PCAP thô (resumable upload tới private dataset trên Kaggle)
bash scripts/kaggle/upload_raw_pcap_dataset.sh

# 2. Đóng gói và đẩy kernel chuỗi thời gian lên Kaggle (hỗ trợ kiểm thử đóng gói với --dry-run)
bash scripts/kaggle/push_timeseries_lstm.sh

# 3. Theo dõi trạng thái thực thi của kernel
bash scripts/kaggle/status_timeseries_lstm.sh

# 4. Tải các tạo tác kết quả về cục bộ (chỉ thực hiện sau khi status báo complete)
bash scripts/kaggle/pull_timeseries_outputs.sh --force
```

---

## 9. Danh Mục Tạo Tác & Chính Sách Đưa Vào Git (Artifact Promotion Policy)

### 9.1. Các Tạo Tác Sinh Ra
Mỗi phiên chạy thành công sẽ kết xuất bộ tạo tác chuẩn tương ứng với nhánh thực nghiệm:

* **Nhánh Thống Kê Dạng Bảng (`artifacts/kaggle/cicdohbrw2020-statistical-baseline/`)**:
  1. `schema_audit.json`: Kiểm toán tệp bảng Parquet/CSV, số hàng, cột, kiểu dữ liệu và số lượng nhãn.
  2. `metrics.json`: Báo cáo đo lường chi tiết của các mô hình cổ điển (Accuracy, Macro-F1, FPR, ROC-AUC, PR-AUC).
  3. `experiment_manifest.json`: Kê khai xuất xứ khoa học (Git SHA, Snapshot SHA-256, Seed 42, Metadata).
  4. `confusion_matrix_*.csv`: Ma trận nhầm lẫn chi tiết của từng mô hình.
* **Nhánh Chuỗi Thời Gian Packet-Clump (`artifacts/kaggle/cicdohbrw2020-timeseries-lstm/`)**:
  1. `pcap_audit.json`: Kiểm toán toàn diện kho PCAP, tệp ZIP lồng nhau, kịch bản, phiên, và băm SHA-256.
  2. `metrics.json`: Báo cáo đo lường của mô hình Paper v4 và Improved BiGRU theo từng cửa sổ $\ell \in [1, 10]$ và giao thức phân chia (`paper_flow_random` vs `session_scenario_disjoint`).
  3. `experiment_manifest.json`: Kê khai xuất xứ khoa học, phiên bản mã nguồn, seed, và các hạn ngạch đã áp dụng.
  4. `training_history.csv`: Lịch sử hàm mất mát (loss) và độ đo qua từng epoch huấn luyện.
  5. `confusion_matrix_*.csv`: Ma trận nhầm lẫn theo từng cửa sổ trượt.

### 9.2. Quy Tắc Đưa Tạo Tác Vào Git (Git Promotion Rules)

```
┌────────────────────────────────────────────────────────────────────────┐
│                        QUY TẮC ĐƯA VÀO GIT                             │
├───────────────────────────────────┬────────────────────────────────────┤
│   ĐƯỢC PHÉP ĐƯA VÀO VERSION CONTROL│    TUYỆT ĐỐI CẤM COMMIT VÀO GIT    │
│   (PROMOTED ARTIFACTS)            │    (PROHIBITED ARTIFACTS)          │
├───────────────────────────────────┼────────────────────────────────────┤
│ ✔ schema_audit.json               │ ✘ Tệp bảng dữ liệu thô (*.parquet, *.csv)│
│ ✔ pcap_audit.json                 │ ✘ Tệp bắt gói mạng PCAP (*.pcap, *.pcapng)│
│ ✔ metrics.json                    │ ✘ Archive nén dữ liệu (*.zip, *.tar.gz) │
│ ✔ experiment_manifest.json        │ ✘ Trọng số mô hình (*.pkl, *.pt, *.pth)│
│ ✔ training_history.csv            │ ✘ Tệp chứa khoá API (kaggle.json)  │
│ ✔ confusion_matrix_*.csv          │ ✘ Tệp biến môi trường cục bộ (.env)│
│ (Lưu tại data/manifests/ hoặc docs)│                                    │
└───────────────────────────────────┴────────────────────────────────────┘
```

* **Điều kiện tiên quyết trước khi quảng bá (Promotion Prerequisite)**:
  Chỉ được phép sao chép tệp manifest và metrics vào `data/manifests/` để commit vào Git khi mã nguồn kernel đã được commit sạch trong Git (`git_sha` hợp lệ, không phải `unknown_uncommitted_source`).

---

## 10. Xử Lý Sự Cố Thường Gặp (Troubleshooting & FAQs)

### 10.1. Lỗi: `Missing required kernel ID`
* **Triệu chứng:** Script báo `Error: Missing required kernel ID`.
* **Khắc phục:** Thiết lập biến môi trường tương ứng:
  ```bash
  export KAGGLE_KERNEL_ID="<your-username>/cicdohbrw2020-statistical-baseline"
  export KAGGLE_TIMESERIES_KERNEL_ID="<your-username>/cicdohbrw2020-timeseries-lstm"
  ```

### 10.2. Lỗi: `Unauthorized` hoặc `401 - Unauthorized` từ Kaggle CLI
* **Triệu chứng:** Lệnh Kaggle báo không có quyền truy cập hoặc token không hợp lệ.
* **Khắc phục:** Kiểm tra sự tồn tại của `~/.kaggle/kaggle.json` (phân quyền `600`) hoặc `~/.kaggle/access_token`.

### 10.3. Lỗi: `Refusing to overwrite existing outputs without explicit --force`
* **Triệu chứng:** `pull_outputs.sh` hoặc `pull_timeseries_outputs.sh` từ chối tải vì thư mục đích đã có dữ liệu.
* **Khắc phục:** Thêm cờ `--force` để xác nhận ghi đè có chủ đích.

### 10.4. Lỗi: `Kernel status is queued/running` khi chạy pull
* **Triệu chứng:** Script tải tạo tác từ chối thực thi và báo kernel chưa `complete`.
* **Khắc phục:** Giữ kiên nhẫn và dùng `status.sh` hoặc `status_timeseries_lstm.sh` để theo dõi cho tới khi hoàn tất.

### 10.5. Lỗi: Upload PCAP ZIP lớn bị ngắt kết nối & Hành vi Kaggle CLI
* **Triệu chứng:** Trình duyệt quay vòng không hiện tiến độ, hoặc upload ZIP PCAP bị ngắt giữa chừng do đường truyền mạng.
* **Khắc phục:** Sử dụng script CLI chuyên biệt có thanh tiến độ và cơ chế bảo vệ:
  ```bash
  bash scripts/kaggle/upload_raw_pcap_dataset.sh
  ```
* **Hành vi khôi phục (Resumption State & Observed Reality)**:
  * Script sử dụng symbolic link và duy trì trạng thái upload của Kaggle CLI tại thư mục `/tmp/.kaggle/uploads`.
  * Khi Kaggle CLI hỗ trợ và endpoint máy chủ còn lưu phiên tải, việc chạy lại lệnh trên có thể tiếp tục phần tải dang dở. **Tuy nhiên, tính năng tiếp tục (resumption) không được đảm bảo tuyệt đối**: trong thực tế quan sát, Kaggle CLI đã từng khởi động lại việc tải byte từ đầu khi gặp lỗi sau khi đã truyền xong dữ liệu hoặc khi máy chủ Kaggle gặp lỗi tạo dataset (`Dataset creation error`).
* **Quy chuẩn metadata bản quyền (`licenses`)**:
  * Tệp siêu dữ liệu `dataset-metadata.json` khai báo trường `"licenses": [{"name": "other"}]`. Đây là định danh giấy phép hợp lệ duy nhất của Kaggle cho các bộ dữ liệu nghiên cứu học thuật của bên thứ ba (như UNB CIC DoHBrw-2020) có điều khoản ghi công và giới hạn phi thương mại.
* **Cơ chế ngắt an toàn khi tạo dataset thất bại (Fail-on-create-error)**:
  * Script kiểm tra chặt chẽ cả mã thoát (exit code) lẫn nhật ký thực thi. Nếu gặp thông báo `Upload unsuccessful` hoặc `Dataset creation error`, script lập tức dừng tiến trình (`exit 1`) và thông báo lỗi rõ ràng thay vì giả định thành công.
  * Luôn xác minh trạng thái hoàn tất xử lý phía máy chủ bằng lệnh:
    ```bash
    .venv-tools/bin/kaggle datasets status <owner/dataset-slug>
    ```
### 10.6. Lỗi: Quá tải bộ nhớ RAM trên Kaggle khi chạy Time-Series
* **Triệu chứng:** Kernel bị ngắt tiến trình với lỗi `Out Of Memory (OOM)` hoặc `Killed`.
* **Khắc phục:** Mở `run_config.json`, giảm các giới hạn `max_capture_members` (xuống 50 hoặc 20) và `max_flows_per_class` (xuống 200 hoặc 100) để đảm bảo dữ liệu vừa vặn với bộ nhớ RAM 30 GB của Kaggle.

---

## 11. Tóm Tắt Quy Trình Dành Cho Thành Viên Nhóm (Teammate Checklist)

### Lộ Trình 1: Khởi Tạo Công Cụ Chung
- [ ] **Bước 1:** Tạo Kaggle API token tại web, lưu tại `~/.kaggle/kaggle.json`, chạy `chmod 600 ~/.kaggle/kaggle.json`.
- [ ] **Bước 2:** Xác minh an toàn: `kaggle datasets list --mine > /dev/null 2>&1 && echo OK`.
- [ ] **Bước 3:** Khởi tạo môi trường ảo công cụ: `bash scripts/kaggle/bootstrap_cli.sh`.

### Lộ Trình 2: Huấn Luyện Baseline Thống Kê (Tabular Baseline)
- [ ] **Bước 4:** Thiết lập ID: `export KAGGLE_KERNEL_ID="<username>/cicdohbrw2020-statistical-baseline"`.
- [ ] **Bước 5:** Đẩy chạy kiểm toán trước: `bash scripts/kaggle/push_statistical_baseline.sh`.
- [ ] **Bước 6:** Giám sát trạng thái: `bash scripts/kaggle/status.sh` cho tới khi `complete`.
- [ ] **Bước 7:** Tải tạo tác kiểm toán: `bash scripts/kaggle/pull_outputs.sh --force`.
- [ ] **Bước 8:** Mở `schema_audit.json`, xác định tệp bảng (`L1-DoH-NonDoH.parquet`), cột nhãn và phân bố lớp; chuyển `run_config.json` sang `"train"`, commit Git sạch, rồi chạy lại chu trình push $\to$ status $\to$ pull.

### Lộ Trình 3: Tái Hiện Chuỗi Thời Gian Packet-Clump (Raw-PCAP Time-Series)
- [ ] **Bước 9:** Tải lên bộ dữ liệu thô: `bash scripts/kaggle/upload_raw_pcap_dataset.sh` và kiểm tra `kaggle datasets status <owner/dataset-slug>` đến khi sẵn sàng.
- [ ] **Bước 10:** Thiết lập ID: `export KAGGLE_TIMESERIES_KERNEL_ID="<username>/cicdohbrw2020-timeseries-lstm"`.
- [ ] **Bước 11:** Chạy kiểm toán PCAP trước: bảo đảm `run_config.json` ở `"mode": "audit"`, chạy `bash scripts/kaggle/push_timeseries_lstm.sh`.
- [ ] **Bước 12:** Giám sát trạng thái: `bash scripts/kaggle/status_timeseries_lstm.sh` cho tới khi `complete`.
- [ ] **Bước 13:** Tải tạo tác kiểm toán: `bash scripts/kaggle/pull_timeseries_outputs.sh --force`, kiểm tra `pcap_audit.json` về danh sách capture và kịch bản.
- [ ] **Bước 14:** Chuyển `run_config.json` sang `"mode": "train"`, commit mã nguồn vào Git để có Git SHA sạch, sau đó thực hiện push $\to$ status $\to$ pull để huấn luyện và đánh giá mô hình.
- [ ] **Bước 15:** Chỉ quảng bá các tệp JSON/CSV kết quả (`pcap_audit.json`, `metrics.json`, `experiment_manifest.json`) vào `data/manifests/` của Git.
