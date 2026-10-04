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
Mỗi thành viên sở hữu một kernel Kaggle độc lập dưới tài khoản của mình. Định danh kernel bắt buộc tuân theo định dạng:
```text
<kaggle_username>/<kernel_slug>
```
* Ví dụ: `alice_sec/cicdohbrw2020-statistical-baseline` hoặc `charlie/doh-statistical-baseline`.
* Wrapper sẽ kiểm tra nghiêm ngặt định dạng này và tự động từ chối nếu tên chứa các chuỗi placeholder như `INSERT_KAGGLE_USERNAME`, `your_username`, hoặc để trống.

### 4.2. Thiết Lập Biến Trong Phiên Shell (Khuyến Nghị)
Thiết lập trực tiếp trong terminal đang làm việc. Biến này chỉ tồn tại trong bộ nhớ phiên và tự hủy khi đóng cửa sổ:

```bash
export KAGGLE_KERNEL_ID="<your-kaggle-username>/cicdohbrw2020-statistical-baseline"
```

### 4.3. Sử Dụng Tệp Mẫu `scripts/kaggle/.env.example`
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
| `--model` | `string` | `all` | Mô hình huấn luyện: `all`, `random_forest`, `decision_tree`, `gaussian_nb`, `linear_svm`. |
| `--seed` | `int` | `42` | Random seed cố định đảm bảo tính tái lập. |
| `--split` | `string` | `paper_flow_random_80_20` | Giao thức phân chia luồng ngẫu nhiên 80/20 theo bài báo. |
| `--max-samples-per-class`| `int` | `None` | Giới hạn số mẫu mỗi lớp phục vụ kiểm thử nhanh (optional). |
| `--dataset-slug` | `string` | `dhoogla/cicdohbrw2020` | Định danh tập dữ liệu Kaggle. |
| `--dataset-version` | `string` | `3` | Số hiệu phiên bản tập dữ liệu. |

> **LƯU Ý VỀ CÁC MÔ HÌNH BỊ LOẠI TRỪ:**  
> * **Không sử dụng RBF Kernel SVM:** Tập dữ liệu luồng có quy mô hàng trăm nghìn mẫu. Thuật toán SVM nhân RBF có độ phức tạp tính toán $O(n^2)$ đến $O(n^3)$, gây quá tải và tràn bộ nhớ trên môi trường CPU của Kaggle. Thay vào đó, script sử dụng `LinearSVC` với thời gian hội tụ tuyến tính.  
> * **Không sử dụng mạng LSTM:** Dữ liệu dạng bảng không có cấu trúc chuỗi thời gian gói tin, không thể áp dụng mạng hồi quy tuần tự.

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

## 8. Danh Mục Tạo Tác & Chính Sách Đưa Vào Git (Artifact Promotion Policy)

### 8.1. Các Tạo Tác Sinh Ra Tại `artifacts/kaggle/<kernel-slug>/`
Mỗi phiên chạy thành công sẽ kết xuất bộ 4 thành phần tạo tác chuẩn:

1. **`schema_audit.json`:** Báo cáo kiểm toán toàn bộ các tệp dữ liệu đầu vào, kích thước byte, băm SHA-256, số hàng, số thuộc tính và kiểu dữ liệu.
2. **`metrics.json`:** Báo cáo đo lường chi tiết của các mô hình đã đánh giá trên tập kiểm thử (Test Set):
   ```json
   {
     "task": "l1",
     "split_protocol": "paper_flow_random_80_20",
     "seed": 42,
     "total_test_samples": 45000,
     "models": {
       "random_forest": {
         "accuracy": 0.9982,
         "precision": 0.9985,
         "recall": 0.9979,
         "f1_score": 0.9982,
         "confusion_matrix": {"tp": 22450, "fp": 34, "tn": 22466, "fn": 50},
         "fit_time_seconds": 12.4
       }
     }
   }
   ```
3. **`experiment_manifest.json`:** Tệp kê khai xuất xứ khoa học đầy đủ (Provenance Manifest v1.0.0), bao gồm:
   * Mã băm Git commit thực thi (`git_sha` trích xuất từ `KAGGLE_GIT_SHA`, mang giá trị `unknown_uncommitted_source` khi mã nguồn chưa commit trong Git).
   * Mã băm bối cảnh nội dung kernel (`source_snapshot_sha256` trích xuất từ `KAGGLE_SOURCE_SNAPSHOT_SHA256`), bảo đảm bằng chứng mã nguồn bất biến ngay cả khi chưa commit.
   * Định danh và phiên bản tập dữ liệu (`dhoogla/cicdohbrw2020` v3).
   * Giá trị seed ngẫu nhiên (`random_seed: 42`).
   * Danh mục các tệp đầu vào kèm mã băm SHA-256 xác thực.
   * Danh sách các cột thuộc tính đã sử dụng (đã loại bỏ triệt để các thuộc tính định danh IP/Port/Timestamp nhằm chống rò rỉ định danh luồng).
   * Tuyên bố phạm vi nghiên cứu (`non_claim_scope`): khẳng định đây là baseline thống kê, không phải tái hiện LSTM.
   * Phiên bản các thư viện thực thi (`python`, `scikit-learn`, `pandas`, `numpy`, `scipy`).

### 8.2. Quy Tắc Đưa Tạo Tác Vào Git (Git Promotion Rules)

Nhóm áp dụng ranh giới phân định nghiêm ngặt giữa tài liệu học thuật và dữ liệu nhị phân:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        QUY TẮC ĐƯA VÀO GIT                             │
├───────────────────────────────────┬────────────────────────────────────┤
│   ĐƯỢC PHÉP ĐƯA VÀO VERSION CONTROL│    TUYỆT ĐỐI CẤM COMMIT VÀO GIT    │
│   (PROMOTED ARTIFACTS)            │    (PROHIBITED ARTIFACTS)          │
├───────────────────────────────────┼────────────────────────────────────┤
│ ✔ schema_audit.json               │ ✘ Tệp bảng dữ liệu thô (*.parquet, *.csv)│
│ ✔ metrics.json                    │ ✘ Tệp bắt gói mạng PCAP (*.pcap)   │
│ ✔ experiment_manifest.json        │ ✘ Checkpoint mô hình (*.pkl, *.pt) │
│ ✔ confusion_matrix_*.csv          │ ✘ Tệp chứa khoá API (kaggle.json)  │
│ (Lưu tại data/manifests/ hoặc docs)│ ✘ Tệp biến môi trường cục bộ (.env)│
└───────────────────────────────────┴────────────────────────────────────┘
```

**Điều kiện tiên quyết trước khi quảng bá (Promotion Prerequisite):**
* **BẮT BUỘC COMMIT VÀO GIT:** Tuyệt đối không quảng bá bất kỳ kết quả thực nghiệm nào thành thực nghiệm chính thức (official reproducible experiment) nếu `git_sha` trong manifest vẫn mang giá trị `unknown_uncommitted_source`. Toàn bộ dự án `doh_tunnel_detection/` bắt buộc phải được commit sạch vào kho lưu trữ Git trước khi chạy thực nghiệm huấn luyện chính thức để mã Git commit SHA và Snapshot SHA256 liên kết chặt chẽ và có thể kiểm chứng độc lập.
* **Quy trình cho Audit Runs:** Các lần chạy kiểm toán schema (audit-only runs) được phép tiến hành với mã băm snapshot `KAGGLE_SOURCE_SNAPSHOT_SHA256` khi mã nguồn chưa commit nhằm phục vụ thăm dò cấu trúc dữ liệu ban đầu.

**Cách thức quảng bá (promote) kết quả vào Git:**
Khi một thí nghiệm huấn luyện hoàn tất từ mã nguồn đã commit sạch trong Git và đạt tiêu chuẩn kiểm định, thành viên sao chép tệp manifest và metrics vào thư mục theo dõi phiên bản:
```bash
# Ví dụ lưu vết manifest chính thức cho lần chạy baseline L1 (đã có Git SHA sạch)
cp artifacts/kaggle/cicdohbrw2020-statistical-baseline/experiment_manifest.json data/manifests/baseline_l1_manifest.json
cp artifacts/kaggle/cicdohbrw2020-statistical-baseline/metrics.json data/manifests/baseline_l1_metrics.json

# Đưa vào Git staging và tạo commit có chữ ký
git add data/manifests/baseline_l1_manifest.json data/manifests/baseline_l1_metrics.json
git commit -m "docs(manifest): record verified Kaggle statistical baseline metrics and provenance"
```

---

## 9. Xử Lý Sự Cố Thường Gặp (Troubleshooting & FAQs)

### 9.1. Lỗi: `Missing required kernel ID`
* **Triệu chứng:** Script báo `Error: Missing required kernel ID` khi chạy `push`, `status`, hoặc `pull`.
* **Khắc phục:** Thiết lập biến môi trường trong shell:
  ```bash
  export KAGGLE_KERNEL_ID="<your-kaggle-username>/cicdohbrw2020-statistical-baseline"
  ```
  Hoặc truyền trực tiếp làm tham số:
  ```bash
  bash scripts/kaggle/status.sh <your-kaggle-username>/cicdohbrw2020-statistical-baseline
  ```

### 9.2. Lỗi: `Unauthorized` hoặc `401 - Unauthorized` từ Kaggle CLI
* **Triệu chứng:** Lệnh Kaggle báo lỗi không có quyền truy cập hoặc token không hợp lệ.
* **Khắc phục:**
  1. Kiểm tra sự tồn tại của tệp `~/.kaggle/kaggle.json`.
  2. Kiểm tra phân quyền: `ls -la ~/.kaggle/kaggle.json` phải hiển thị `-rw-------` (600).
  3. Nếu token đã hết hạn hoặc bị thu hồi trên web, tạo lại token mới tại Kaggle Settings và thay thế tệp `~/.kaggle/kaggle.json`.

### 9.3. Lỗi: `Refusing to overwrite existing outputs without explicit --force`
* **Triệu chứng:** Lệnh `pull_outputs.sh` từ chối tải tệp về vì thư mục `artifacts/kaggle/<slug>/` đã chứa dữ liệu từ phiên chạy trước.
* **Khắc phục:** Thêm cờ `--force` để xác nhận ghi đè:
  ```bash
  bash scripts/kaggle/pull_outputs.sh --force
  ```

### 9.4. Lỗi: `Kernel status is queued/running` khi chạy `pull_outputs.sh`
* **Triệu chứng:** `pull_outputs.sh` từ chối tải về, in thông báo trạng thái hiện tại (ví dụ: `queued` hoặc `running`) và thoát với mã lỗi khác 0 mà không tạo thư mục đích.
* **Khắc phục:** Không thực hiện tải tạo tác khi kernel chưa hoàn tất. Sử dụng `bash scripts/kaggle/status.sh` để tiếp tục giám sát cho tới khi trạng thái chuyển sang `complete`, sau đó mới thực thi lại `pull_outputs.sh`.

### 9.5. Lỗi: `No output files retrieved / empty artifact download`
* **Triệu chứng:** `pull_outputs.sh` báo lỗi và thoát nonzero vì thư mục đầu ra không chứa bất kỳ tệp dữ liệu thông thường nào sau khi tải.
* **Khắc phục:** Kiểm tra log thực thi của kernel qua giao diện web Kaggle để đảm bảo tác vụ không gặp lỗi ngầm trước khi tạo output, hoặc kiểm tra xem script kernel có kết xuất đúng tệp vào `/kaggle/working` hay không.

### 9.6. Lỗi: `Ambiguous label column` hoặc Không Xác Định Được Nhãn
* **Triệu chứng:** Script thoát với thông báo tìm thấy nhiều cột có từ khóa nhãn (ví dụ: vừa có `Label`, vừa có `label_code`).
* **Khắc phục:** Mở `schema_audit.json`, quan sát mục `candidate_labels`, và chỉ định rõ ràng tên cột nhãn qua tham số:
  ```bash
  --label-column <ten_cot_chinh_xac>
  ```

### 9.7. Cảnh báo: `Kernel source is not tracked and clean in Git`
* **Triệu chứng:** Khi chạy `push_statistical_baseline.sh`, màn hình hiển thị:
  `Notice: Kernel source is not tracked and clean at parent git commit ... KAGGLE_GIT_SHA recorded as: unknown_uncommitted_source`.
* **Nguyên nhân:** Thư mục dự án `doh_tunnel_detection/` chưa được commit vào kho lưu trữ Git hiện tại (đang là untracked trong worktree cha), hoặc có các tệp chưa được lưu/staging trong thư mục kernel.
* **Ý nghĩa thực tế:**
  1. Đối với **Audit Runs**: Lần chạy vẫn được phép tiến hành bình thường; tính toàn vẹn và xuất xứ của kernel được bảo đảm thông qua mã băm snapshot `KAGGLE_SOURCE_SNAPSHOT_SHA256`.
  2. Đối với **Thực Nghiệm Huấn Luyện Chính Thức (Official Experiments)**: Kết quả tạo ra KHÔNG ĐƯỢC PHÉP quảng bá vào `data/manifests/` cho đến khi dự án được commit đầy đủ vào kho Git nhằm bảo đảm khả năng tái lập khoa học 100%.
* **Khắc phục:** Thực hiện `git add doh_tunnel_detection/` và tạo commit Git trước khi chạy thực nghiệm huấn luyện chính thức.
---

## 10. Tóm Tắt Quy Trình Dành Cho Thành Viên Nhóm (Teammate Checklist)

Để một thành viên mới trong nhóm có thể bắt đầu vận hành ngay lập tức:

- [ ] **Bước 1:** Tạo Kaggle API token tại web, lưu tại `~/.kaggle/kaggle.json`, chạy `chmod 600 ~/.kaggle/kaggle.json`.
- [ ] **Bước 2:** Xác minh an toàn: `kaggle datasets list --mine > /dev/null 2>&1 && echo OK`.
- [ ] **Bước 3:** Khởi tạo môi trường ảo công cụ: `bash scripts/kaggle/bootstrap_cli.sh`.
- [ ] **Bước 4:** Thiết lập ID kernel: `export KAGGLE_KERNEL_ID="<username>/cicdohbrw2020-statistical-baseline"`.
- [ ] **Bước 5:** Đẩy chạy kiểm toán trước: `bash scripts/kaggle/push_statistical_baseline.sh` (chạy với mã băm snapshot `KAGGLE_SOURCE_SNAPSHOT_SHA256`).
- [ ] **Bước 6:** Giám sát trạng thái: `bash scripts/kaggle/status.sh` cho tới khi `complete` (tuyệt đối không pull khi kernel còn ở trạng thái `queued` hoặc `running`).
- [ ] **Bước 7:** Tải tạo tác: `bash scripts/kaggle/pull_outputs.sh` (chỉ chạy sau khi status xác nhận `complete`; script tự động từ chối nếu kernel chưa chạy xong hoặc tải về thư mục rỗng).
- [ ] **Bước 8:** Mở `schema_audit.json`, kiểm tra số đếm nhãn toàn bộ cột (`value_counts`, `complete_column_audit: true` - tuyệt đối không suy đoán từ mẫu hàng đầu), xác định tệp dữ liệu bảng (`data_file`, ví dụ: `L1-DoH-NonDoH.parquet`), tên cột nhãn và giá trị lớp; chỉ chuyển `run_config.json` từ `"audit"` sang `"train"` sau khi số đếm lớp được phê duyệt.
- [ ] **Bước 9:** Commit mã nguồn vào Git để có Git SHA sạch trước khi thực hiện chạy huấn luyện chính thức.
- [ ] **Bước 10:** Đẩy chạy huấn luyện, kiểm tra trạng thái và tải tạo tác kết quả.
- [ ] **Bước 11:** Quảng bá duy nhất `metrics.json` và `experiment_manifest.json` (đã có Git commit SHA và Snapshot SHA xác thực) vào Git theo dõi.
