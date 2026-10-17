# Phase 2: Phương Pháp Luận & Giao Thức Chuỗi Thời Gian Packet-Clump (Phase 2 Time-Series Methodology & Execution Contract)

Tài liệu này xác lập phương pháp luận kỹ thuật, giao thức trích xuất dữ liệu từ lưu lượng bắt gói mạng thô (Raw PCAP), kiến trúc mô hình học sâu chuỗi thời gian, và các ranh giới khoa học kiểm định cho Phase 2 của dự án nghiên cứu phòng thủ DoH tunnel (*CIRA-CIC-DoHBrw-2020*).

---

## 1. Phạm Vi & Bốn Cấp Độ Bằng Chứng Khoa Học (Scope & Evidentiary Hierarchy)

Để duy trì tính liêm chính học thuật và bảo đảm khả năng tái lập độc lập, dự án áp dụng ranh giới phân định minh bạch qua **bốn cấp độ bằng chứng thực nghiệm**:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        HỆ THỐNG PHÂN CẤP BẰNG CHỨNG THỰC NGHIỆM                        │
├──────────────────────────┬─────────────────────────────────────────────────────────────┤
│ Cấp 1: [Paper-Reported]  │ Số liệu công bố trong bài báo gốc (Bảng III, IV, V, VI).    │
│                          │ Bất biến; đánh giá trên phân chia ngẫu nhiên 80/20.         │
├──────────────────────────┼─────────────────────────────────────────────────────────────┤
│ Cấp 2: [Project-Observed]│ Số liệu Phase 1 quan sát độc lập trên Kaggle mirror v3      │
│        (Statistical)     │ (29 đặc trưng bảng; Random Forest, HGB; seed=42; có audit). │
├──────────────────────────┼─────────────────────────────────────────────────────────────┤
│ Cấp 3: [Project-         │ Toàn bộ pipeline chuỗi thời gian đã lập trình trong repo    │
│        Implemented]      │ (src/doh_reproduction/): gom cụm 1ms sửa lỗi, chuẩn hóa     │
│                          │ DoHLyzer, split 70/15/15 disjoint, v4 LSTM & BiGRU cải tiến.│
├──────────────────────────┼─────────────────────────────────────────────────────────────┤
│ Cấp 4: [Project-Observed]│ Thực nghiệm chuỗi thời gian trên Kaggle raw-PCAP hiện đang  │
│        (Time-Series)     │ Ở TRẠNG THÁI CHỜ (PENDING) khi bộ PCAP đang tải lại.        │
│                          │ Mọi chỉ số chưa chạy BẮT BUỘC ghi nhận là [Unavailable].    │
└──────────────────────────┴─────────────────────────────────────────────────────────────┘
```

### Các nguyên tắc cốt lõi:
1. **Tuyệt đối không bịa đặt số liệu**: Các kết quả chuỗi thời gian chưa thực thi phải xuất hiện dưới dạng chuỗi `"unavailable"`, không bao giờ được thay thế bằng giá trị `0.0`, ô trống, hoặc số liệu suy đoán ngoại suy.
2. **Công bố về tham số huấn luyện khuyết thiếu**: Bài báo của MontazeriShatoori et al. (*IEEE CyberSciTech 2020*) hoàn toàn bỏ sót các siêu tham số huấn luyện mạng nơ-ron: thuật toán tối ưu (optimizer), tốc độ học (learning rate), kích thước batch, số epoch, và điều kiện dừng sớm (early stopping). Các tham số được sử dụng trong repo (`Adam`, `lr=0.001`, `batch_size=64`, `patience=5`) là các lựa chọn kỹ thuật phục vụ tái hiện của nhóm nghiên cứu, **tuyệt đối không được mạo nhận là quy chuẩn của bài báo gốc**.
3. **Phân định giữa thiết kế kiến trúc và lợi ích chứng minh**: Mô hình BiGRU cải tiến với cơ chế attention pooling nhận biết mặt nạ đệm và hàm mất mát có trọng số là đóng góp về mặt thiết kế đã được cài đặt hoàn chỉnh (`timeseries_models.py`, được kiểm chứng qua bộ kiểm thử hành vi toàn diện). Hiệu năng thực tế phải chờ chạy chính thức trên tập PCAP thô và **tuyệt đối không được tuyên bố là "lợi ích đã chứng minh trên thực tế"** khi chưa có dữ liệu quan sát.

---

## 2. Kiến Trúc Kho PCAP & Cơ Chế Đọc Luồng (Raw Archive & Nested ZIP Streaming)

### 2.1. Cấu Trúc Lưu Trữ Archive Lồng Nhau (Nested ZIP Structure)
* Bộ dữ liệu gốc *CIRA-CIC-DoHBrw-2020* được cung cấp dưới dạng archive nén lớn: `PCAPs.zip` (35 tệp thành phần, tổng dung lượng giải nén `80,870,581,876` bytes ~ 80.87 GB).
* Cấu trúc archive chứa đồng thời:
  * Các tệp PCAP/PCAPNG độc lập ở thư mục gốc archive.
  * Các tệp nén ZIP lồng nhau (`nested ZIP archives`) đại diện cho từng phiên thu thập theo kịch bản (ví dụ: các đợt chạy DNS tunnel qua Iodine, dnscat2, dns2tcp, hoặc các đợt duyệt web thông thường).

### 2.2. Cơ Chế Đọc Luồng Tránh Cạn Kiệt Đĩa (Streaming Ingestion via Virtual Members)
* Môi trường thực thi tạm thời trên máy ảo đám mây (Kaggle CPU worker) giới hạn dung lượng đĩa ghi `/kaggle/working` ở mức 20 GB. Việc giải nén toàn bộ 80 GB archive ra đĩa sẽ lập tức gây lỗi `Disk Quota Exceeded`.
* Module `src/doh_reproduction/raw_dataset.py` áp dụng kỹ thuật giải nén luồng trực tiếp (`Streaming Decompression`):
  * `CaptureSource`: Lớp dữ liệu đại diện cho thành viên PCAP (độc lập hoặc lồng nhau).
  * `open_stream()`: Trả về một context manager cung cấp luồng đọc nhị phân `io.IOBase` trực tiếp từ bộ nhớ hoặc từ tệp tạm có kiểm soát dung lượng, đóng luồng ngay khi hoàn tất giải mã gói tin.
  * **Không bao giờ giải nén toàn bộ kho dữ liệu ra đĩa cứng**.

### 2.3. Ngăn Chặn Zip Bomb & Bộ Đếm Ngân Sách Tích Lũy (`_CumulativeBudgetTracker`)
Để ngăn chặn các tấn công cạn kiệt tài nguyên hoặc tệp nén bị lỗi làm sập hệ thống:
* `max_standalone_capture_bytes`: Giới hạn 20 GB cho tệp PCAP đơn lẻ.
* `max_member_bytes`: Giới hạn 10 GB cho một thành viên PCAP bên trong archive.
* `max_nested_archive_bytes`: Giới hạn 25 GB cho một tệp nén ZIP lồng nhau.
* `max_total_uncompressed_bytes`: Giới hạn ngân sách giải nén tích lũy toàn phiên là 200 GB.
* `max_compression_ratio`: Giới hạn tỷ lệ nén tối đa 100.0 (giới hạn rủi ro giải nén tệp độc hại theo cơ chế fail-closed: lập tức từ chối và ngắt tiến trình đối với các archive vượt ngưỡng tỷ lệ nén hoặc khai báo kích thước không hợp lệ trước khi cấp phát bộ nhớ).

---

## 3. Tiêu Chuẩn Trích Xuất Gói Tin & Ghép Luồng (Packet Decoding & Flow Assembly)

Module `src/doh_reproduction/pcap.py` chịu trách nhiệm giải mã luồng nhị phân:

```text
PCAP / PCAPNG Stream
  │
  ▼ [Lazy dpkt Loader]
Ethernet Frame / Linux Cooked Capture
  │
  ▼ [IPv4 / IPv6 Parsing]
TCP Stream
  │
  ▼ [TLS Application Data Filter: Content Type == 23 && Payload >= 40 Bytes]
Valid TLS Application Packets
  │
  ▼ [Flow Assembly: Bidirectional 5-tuple, Timeout = 40.0 s]
Directional Flow Sequences (Forward: Client->Server=0, Backward: Server->Client=1)
```

### 3.1. Bộ Lọc Dữ Liệu Ứng Dụng TLS (TLS Application Data Filter)
1. **Content Type**: Chỉ chấp nhận các bản ghi TLS có trường Content Type bằng **23** (`TLS_RECORD_APPLICATION_DATA` theo RFC 5246 / RFC 8446). Toàn bộ các gói tin bắt tay (Handshake, type 22), cảnh báo (Alert, type 21) hoặc thay đổi mật mã (Change Cipher Spec, type 20) đều bị loại bỏ.
2. **Ngưỡng tải trọng tối thiểu $\ge 40$ Bytes (`DEFAULT_MIN_TLS_APP_BYTES = 40`)**:
   Theo quy chuẩn của công cụ DoHLyzer, ngưỡng này lọc bỏ các khung điều khiển mức ứng dụng nhỏ:
   * Khung HTTP/2 PING frame (kích thước cố định 34 bytes bao gồm 9 bytes header và 8 bytes opaque data cộng TLS padding).
   * Các gói tin TCP ACK rỗng không mang dữ liệu TLS.
   * Các khung thông điệp giữ kết nối (keepalive) không chứa truy vấn/phản hồi DNS.

### 3.2. Lắp Ghép Luồng Hai Chiều & Thời Gian Hết Hạn 40 Giây (Flow Expiry)
* **Thời gian hết hạn luồng**: `DEFAULT_FLOW_TIMEOUT_SECONDS = 40.0` giây (khớp chính xác hằng số `EXPIRED_UPDATE = 40` trong mã nguồn DoHLyzer). Hai gói tin cùng endpoint nhưng cách nhau quá 40 giây sẽ được cắt thành hai luồng độc lập.
* **Xác định chiều luồng (Direction Assignment)**: Gói tin TLS Application Data hợp lệ đầu tiên xuất hiện trong luồng xác định `client_ip:client_port` là bên khởi tạo (chiều đi - forward, gán nhãn `0`). Chiều ngược lại từ `server_ip:server_port` về máy khách là chiều về (backward, gán nhãn `1`).
* **Bảo vệ chống rò rỉ định danh**: Địa chỉ IP và số hiệu cổng chỉ được sử dụng nội bộ để ghép luồng và xác định chiều; chúng bị loại bỏ hoàn toàn và không bao giờ được đưa vào vector đặc trưng đầu vào của mô hình học sâu.

---

## 4. Thuật Toán Gom Cụm 1ms & Sửa Lỗi Thuật Toán Bài Báo (Clumping & Bug Fixes)

### 4.1. Khái Niệm Cụm Gói Tin (Packet Clump)
Mỗi cụm là một 5-tuple đặc trưng cho một đợt bùng nổ dữ liệu truyền liên tiếp theo cùng một chiều mà khoảng cách thời gian giữa các gói không vượt quá $\tau = 0.001\text{ s}$ (1 millisecond):
$$\text{Clump} = \langle \text{size}, \text{pkt\_count}, \text{direction}, \text{duration}, \text{interarrival} \rangle$$
* `size`: Tổng số bytes tải trọng của tất cả các gói tin trong cụm (integer).
* `pkt_count`: Tổng số gói tin vật lý được gộp trong cụm (integer $\ge 1$).
* `direction`: Chiều truyền tải ($0$ cho forward, $1$ cho backward).
* `duration`: Thời gian trôi qua từ gói đầu tiên đến gói cuối cùng trong cụm ($t_{\text{last}} - t_{\text{first}}$ tính bằng giây).
* `interarrival`: Thời gian trôi qua từ thời điểm kết thúc cụm trước đến thời điểm bắt đầu cụm này ($t_{\text{start}} - t_{\text{prev\_end}}$). Với cụm đầu tiên của luồng, giá trị này bằng $0.0$.

### 4.2. Sửa Hai Lỗi Nghiêm Trọng Trong Thuật Toán 1 Của Bài Báo Gốc
Thuật toán 1 in trong bài báo của MontazeriShatoori et al. (Hình 4, Trang 4) chứa hai lỗi in ấn nghiêm trọng khiến việc triển khai trực tiếp từ bài báo sẽ dẫn đến sai lệch hoàn toàn hoặc sập chương trình:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        HAI LỖI IN ẤN TRONG THUẬT TOÁN 1 CỦA BÀI BÁO                    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. Lỗi Đảo Ngược Logic Ngắt Vòng Lặp (Termination Logic Inversion):                    │
│    - Bài báo in (Line 6):                                                              │
│        if packets[counter].direction == nextPacket.direction then break                │
│    - Hậu quả: Vòng lặp ngắt ngay khi gói tiếp theo CÙNG CHIỀU! Khiến mọi cụm bị xé     │
│      nhỏ thành từng gói tin đơn lẻ (pkt_count=1, duration=0), mất hoàn toàn bản chất   │
│      gom cụm bùng nổ lưu lượng.                                                        │
│    - Khắc phục chuẩn xác (theo DoHLyzer):                                              │
│        if packets[counter].direction != nextPacket.direction or timePassed > 0.001:    │
│            break                                                                       │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 2. Lỗi Tràn Biên Mảng Gây Sập Tiến Trình (Array Bounds Check Crash):                   │
│    - Bài báo in (Line 8-9):                                                            │
│        counter = counter + 1                                                           │
│        nextPacket = packets[counter]                                                   │
│    - Hậu quả: Khi counter đạt tới gói cuối cùng, counter+1 vượt độ dài mảng packets,   │
│      gây ra lỗi IndexError hoặc Segmentation Fault.                                    │
│    - Khắc phục chuẩn xác (trong clumping.py):                                          │
│        counter += 1                                                                    │
│        if counter >= len(packets):                                                     │
│            break                                                                       │
│        next_pkt = packets[counter]                                                     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Chuẩn Hóa DoHLyzer, Vector Đệm & Thứ Tự Đặc Trưng

Để đảm bảo khả năng tái hiện tương thích 100% với mô hình tham chiếu của Arash Habibi Lashkari et al.:

### 5.1. Thứ Tự Đặc Trưng (`PAPER_REFERENCE_FEATURE_ORDER`)
Khác với thứ tự trình bày logic, mã nguồn DoHLyzer (`dataset.py` và `v4.py`) quy định thứ tự 5 phần tử trong vector đặc trưng của mỗi cụm là:
```python
(interarrival, duration, size, packet_count, direction)
```

### 5.2. Vector Đệm Chuẩn (`PADDING_VECTOR`)
Khi luồng kết thúc sớm hoặc số cụm thực tế ít hơn độ dài cửa sổ trượt $\ell$, các bước cụm thiếu được đệm bằng vector:
```python
[-1.0, -1.0, -1.0, -1.0, 0.0]
```
Trong đó 4 giá trị liên tục đầu tiên mang giá trị $-1.0$, và chiều `direction` mang giá trị $0.0$.

### 5.3. Các Phương Trình Chuẩn Hóa Phi Tuyến (Normalization Equations)
Các đặc trưng được đưa về thang đo min-max logarit:
1. **Thời gian liên cụm và Thời lượng cụm (`interarrival`, `duration`)**:
   $$\text{norm}(x) = \frac{\log_{10}(\max(10^{-12}, x)) - (-12)}{-2 - (-12)}$$
   (Biến đổi thang logarit từ $10^{-12}\text{ s}$ đến $10^{-2}\text{ s}$ thành khoảng $[0, 1]$).
2. **Kích thước cụm tính bằng byte (`size`)**:
   $$\text{norm}(s) = \frac{\log_{10}(\min(10^4, \max(10^{-12}, s))) - 0.5}{4.0 - 0.5}$$
   (Biến đổi thang logarit từ $\approx 3.16\text{ bytes}$ đến $10,000\text{ bytes}$).
3. **Số lượng gói tin (`packet_count`)**:
   $$\text{norm}(c) = \frac{\log_2(\min(256, \max(1, c))) - 0}{8.0 - 0}$$
   (Biến đổi thang lũy thừa bậc 2 từ $1$ gói đến $256$ gói thành $[0, 1]$).
4. **Chiều truyền tải (`direction`)**:
   $$\text{Canonical Direction} = \begin{cases} +1.0 & \text{nếu Client } \to \text{ Server (0, Forward)} \\ -1.0 & \text{nếu Server } \to \text{ Client (1, Backward)} \end{cases}$$

---

## 6. Cửa Sổ Trượt $\ell \in [1, 10]$ & Đánh Giá Nhận Diện Sớm

### 6.1. Sinh Chuỗi Cửa Sổ Trượt (Sliding Windows)
* Mỗi luồng được chia thành các chuỗi con gồm $\ell$ cụm liên tiếp với bước trượt $\text{stride} = 1$.
* Nếu luồng có $N < \ell$ cụm, chuỗi được đệm bên phải (post-padding) bằng $\ell - N$ vector đệm `[-1.0, -1.0, -1.0, -1.0, 0.0]`.

### 6.2. Các Điểm Tối Ưu Của Bài Báo Gốc (Paper Operating Points)
Bài báo gốc khảo sát toàn diện $\ell \in [1, 10]$ và rút ra hai điểm vận hành tối ưu:
* **Tầng 1 (DoH vs Non-DoH) — Tối ưu tại $\ell = 6$**:
  * Đạt $F_1 = 0.993$, Precision $0.993$, Recall $0.993$ (Bảng V).
  * Thời gian trôi qua trung bình để quan sát 6 cụm là **$0.574\text{ s}$** (trung vị $0.047\text{ s}$), giảm **$97.2\%$** thời gian trễ so với việc phải chờ toàn bộ luồng kết thúc ($20.393\text{ s}$ ở mô hình Random Forest).
* **Tầng 2 (Benign DoH vs Malicious DoH) — Tối ưu tại $\ell = 3$**:
  * Đạt $F_1 = 0.991$, Precision $0.991$, Recall $0.991$ (Bảng VI).
  * Thời gian trôi qua trung bình để quan sát 3 cụm là **$0.502\text{ s}$** (trung vị $0.050\text{ s}$), giảm **$99.1\%$** thời gian trễ so với việc phải chờ toàn bộ luồng kết thúc ($53.924\text{ s}$).

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│               ĐÁNH ĐỔI GIỮA ĐỘ TRỄ PHÁT HIỆN VÀ ĐỘ CHÍNH XÁC (EARLY DETECTION)         │
├──────────────────────────┬──────────┬───────────────┬──────────────────────────────────┤
│ Cấu hình / Độ dài cửa sổ │ F1-Score │ Trễ TB (Mean) │ Ý nghĩa phòng thủ vận hành       │
├──────────────────────────┼──────────┼───────────────┼──────────────────────────────────┤
│ L1 Random Forest (Flow)  │ 0.993    │ 20.393 s      │ Phải chờ luồng đóng; trễ quá lớn │
│ L1 Clump LSTM (l = 1)    │ 0.876    │ 0.081 s       │ Tốc độ cực nhanh; tỷ lệ báo sai cao│
│ L1 Clump LSTM (l = 6) ★  │ 0.993    │ 0.574 s       │ Điểm vàng: bằng RF chỉ sau 0.57s │
├──────────────────────────┼──────────┼───────────────┼──────────────────────────────────┤
│ L2 Random Forest (Flow)  │ 0.999    │ 53.924 s      │ Gần 1 phút; dữ liệu đã bị đánh cắp│
│ L2 Clump LSTM (l = 1)    │ 0.782    │ 0.164 s       │ Bỏ sót nhiều đường hầm tinh vi   │
│ L2 Clump LSTM (l = 3) ★  │ 0.991    │ 0.502 s       │ Điểm vàng: bằng RF chỉ sau 0.50s │
│ L2 Clump LSTM (l = 6)    │ 0.998    │ 1.063 s       │ F1 gần tuyệt đối trong khoảng 1s │
└──────────────────────────┴──────────┴───────────────┴──────────────────────────────────┘
```

---

## 7. Kiến Trúc Mạng Nơ-ron v4 Bài Báo & Mô Hình BiGRU Cải Tiến

### 7.1. Kiến Trúc Tái Lập Bài Báo (`PaperReferenceLSTMModel`)
Khôi phục chính xác từng tầng từ mã nguồn `v4.py` của DoHLyzer:
1. **Lớp Chiếu Từng Bước (Step Dense)**: `Linear(5 -> 10, ReLU)` áp dụng độc lập cho từng cụm gói tin trong chuỗi.
2. **Lõi Hồi Quy LSTM**: `LSTM(input_size=10, hidden_size=8*l, batch_first=True)`. Lớp ẩn tự động co giãn theo độ dài cửa sổ $\ell$ (ví dụ: $\ell=3 \to \text{hidden}=24$; $\ell=6 \to \text{hidden}=48$).
3. **Lớp Tuyến Tính 1 (Dense 1)**: `Linear(8*l -> 6*l, ReLU)`.
4. **Lớp Chống Quá Khớp (Dropout)**: `Dropout(p=0.2)`.
5. **Lớp Tuyến Tính 2 (Dense 2)**: `Linear(6*l -> 2*l, ReLU)`.
6. **Lớp Đầu Ra (Output)**: `Linear(2*l -> 1)` kết hợp `Sigmoid` (hoặc trả về logits khi huấn luyện cùng `BCEWithLogitsLoss`).

### 7.2. Mô Hình Hiện Đại Hóa Cải Tiến (`ImprovedMaskedBiGRUModel`)
Khắc phục các hạn chế cố hữu của kiến trúc 2020:
1. **BiGRU Hai Chiều (`nn.GRU(input_size=5, hidden_size=64, bidirectional=True)`)**:
   Cho phép thông tin lan truyền theo cả hai chiều thời gian, giúp cụm phía trước nhận biết được phản hồi tương ứng phía sau.
2. **Attention Pooling Nhận Biết Mặt Nạ Đệm (Mask-Aware Attention Pooling)**:
   * Thuật toán tự động tính toán mặt nạ nhị phân: phát hiện các vector đệm `[-1.0, -1.0, -1.0, -1.0, 0.0]`.
   * Trước khi đưa qua hàm softmax tính trọng số attention, toàn bộ các vị trí đệm được gán điểm bằng $-\infty$.
   * **Lợi ích thiết kế**: Triệt tiêu hiện tượng gradient bị nhiễu do mạng nơ-ron phải tính toán trên các vector đệm nhân tạo.
3. **Hàm Mất Mát BCE Có Trọng Số Lớp (Class-Weighted Loss)**:
   Tính toán trọng số thực nghiệm `pos_weight = N_neg / N_pos` từ tập Train để giải quyết triệt để vấn đề mất cân bằng lớp ở Tầng 2 (lưu lượng Benign chỉ chiếm khoảng $7\%$).
4. **Hiệu Chuẩn Xác Suất Platt Scaling Trên Tập Validation**:
   Khớp mô hình logistic trên tập Validation nhằm lựa chọn ngưỡng vận hành tối ưu $\tau$ thỏa mãn ràng buộc $\text{FPR} \le 0.001$ ($0.1\%$).
   *Lưu ý về trạng thái kiểm chứng*: Lợi ích thực tế khống chế $\text{FPR} < 0.1\%$ đã được kiểm chứng đầy đủ trên dữ liệu luồng thống kê Phase 1 (với test FPR đạt 0.00085 ở L1 và 0.00026 ở L2); đối với chuỗi thời gian packet-clump, thuật toán hiệu chuẩn đã được cài đặt hoàn chỉnh trong pipeline nhưng hiệu năng thực tế đang ở trạng thái chờ thực thi trên Kaggle raw-PCAP.
---

## 8. Giao Thức Phân Chia Dữ Liệu: Cảnh Báo Rò Rỉ vs Phân Chia Rời Rạc

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                   SO SÁNH HAI GIAO THỨC PHÂN CHIA DỮ LIỆU                              │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Giao Thức 1: 80/20 Random Flow Split (Bài báo gốc)                                     │
│   - Cơ chế: Phân chia ngẫu nhiên ở cấp độ luồng (individual flow level).               │
│   - LỖI PHƯƠNG PHÁP LUẬN: Các luồng sinh ra từ cùng một phiên duyệt web hoặc cùng một │
│     phiên điều khiển mã độc C2 bị phân tán sang CẢ tập Train và Test.                  │
│   - Hậu quả: Mô hình học vẹt các thuộc tính tĩnh của phiên (TLS Cipher Suites, SNI,   │
│     TCP Window Size) thay vì học bản chất bùng nổ của DoH tunnel. Điểm số F1 > 0.999   │
│     nhưng sẽ sụp đổ khi đối đầu với phiên mạng mới ở thực tế.                          │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Giao Thức 2: 70/15/15 Group-Disjoint Split (Dự án hiệu chỉnh)                          │
│   - Cơ chế: Phân chia theo nhóm (group-disjoint) dựa trên session_id và scenario_id.   │
│   - ĐẢM BẢO KHOA HỌC: Toàn bộ các luồng thuộc cùng một phiên chỉ xuất hiện ở DUY NHẤT  │
│     hoặc Train (70%), hoặc Validation (15%), hoặc Test (15%).                          │
│   - Kết quả: Đo lường chính xác năng lực tổng quát hóa đối với các cuộc tấn công và     │
│     máy chủ phân giải DoH hoàn toàn mới.                                               │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Hạn Ngạch Bắt Buộc & Giới Hạn Tài Nguyên (Finite Caps & Resource Safeguards)

Tệp cấu hình `experiments/kaggle/timeseries_clump_lstm/run_config.json` tích hợp các ngưỡng chặn an toàn nhằm đảm bảo việc thực thi không bao giờ vượt quá ngưỡng CPU time và bộ nhớ của Kaggle:

| Tham số | Giá trị | Ý nghĩa bảo vệ hệ thống |
| :--- | :---: | :--- |
| `max_capture_members` | `20,000` | Trần discovery cao hơn inventory quan sát 13,754 capture; huấn luyện vẫn dừng sớm theo quota luồng mỗi lớp. |
| `max_flows_per_class` | `500` | Giới hạn tối đa 500 luồng thu thập cho mỗi lớp phân loại (áp dụng theo nhãn thực tế). |
| `max_flows_per_capture` | `25` | Ngăn một capture/session chiếm hết quota lớp trước khi split group-disjoint. |
| `max_raw_packets` | `1,000,000` | Giới hạn tối đa 1 triệu gói tin thô được phân tích trong mỗi tệp capture. |
| `max_raw_bytes` | `1,073,741,824` | Giới hạn tối đa 1 GB dữ liệu gói tin thô cho mỗi capture. |
| `max_capture_packets` | `200,000` | Giới hạn tối đa 200,000 gói tin TLS Application Data được chấp nhận mỗi capture. |
| `max_capture_bytes` | `536,870,912` | Giới hạn tối đa 512 MB dữ liệu TLS Application Data mỗi capture. |
| `max_flow_packets` | `10,000` | Giới hạn tối đa 10,000 gói tin TLS cho mỗi luồng riêng biệt. |
| `max_flow_bytes` | `52,428,800` | Giới hạn tối đa 50 MB dữ liệu TLS cho mỗi luồng riêng biệt. |
| `max_windows_per_flow`| `1,000` | Giới hạn tối đa 1,000 mẫu cửa sổ cụm được sinh ra từ một luồng. |
| `max_windows_per_class`| `10,000` | Giới hạn tối đa 10,000 mẫu cửa sổ cụm cho mỗi lớp huấn luyện. |
| `epochs` | `15` | Số vòng lặp huấn luyện tối đa. |
| `batch_size` | `64` | Kích thước mini-batch cho PyTorch DataLoader. |
| `learning_rate` | `0.001` | Tốc độ học khởi tạo cho Adam optimizer. |
| `patience` | `5` | Số epoch chờ cải thiện loss trên tập Validation trước khi dừng sớm. |
| `target_false_positive_rate` | `0.001` | Ngưỡng FPR mục tiêu ($0.1\%$) khi lựa chọn ngưỡng vận hành Platt scaling. |

---

## 10. Quy Trình Vận Hành 2 Giai Đoạn & Kaggle CLI Wrappers

Nhóm nghiên cứu áp dụng quy trình kiểm toán trước khi huấn luyện (**Audit-First Workflow**):

```text
[Giai đoạn 1: Audit-First]
run_config.json ("mode": "audit")
  ──> bash scripts/kaggle/push_timeseries_lstm.sh
  ──> bash scripts/kaggle/status_timeseries_lstm.sh (chờ complete)
  ──> bash scripts/kaggle/pull_timeseries_outputs.sh --force
  ──> Kiểm tra artifacts/kaggle/cicdohbrw2020-timeseries-lstm/pcap_audit.json
                                   │
                     Xác minh capture, phiên và kịch bản
                                   ▼
[Giai đoạn 2: Model Training]
run_config.json ("mode": "train")
  ──> Commit mã nguồn vào Git (đảm bảo Git SHA sạch)
  ──> bash scripts/kaggle/push_timeseries_lstm.sh
  ──> bash scripts/kaggle/status_timeseries_lstm.sh (giám sát tiến độ)
  ──> bash scripts/kaggle/pull_timeseries_outputs.sh --force
  ──> Thu được: metrics.json (chứa mảng canonical `runs`), experiment_manifest.json, training_history.csv
```

### Các lệnh CLI Wrapper chính thức:
1. **Tải lên archive PCAP thô (`upload_raw_pcap_dataset.sh`)**:
   * Script sử dụng symbolic link và lưu vết phiên tải tại `/tmp/.kaggle/uploads`. Khi Kaggle hỗ trợ, việc chạy lại lệnh có thể tiếp tục phần tải dở, **tuy nhiên tính năng tiếp tục không được đảm bảo tuyệt đối** (Kaggle CLI có thể bắt đầu lại từ đầu nếu gặp lỗi tạo dataset).
   * Khai báo hợp lệ giấy phép `"licenses": [{"name": "other"}]` trong `dataset-metadata.json`.
   * Cơ chế fail-closed: lập tức ngắt tiến trình (`exit 1`) nếu gặp lỗi `Upload unsuccessful` hoặc `Dataset creation error`.
   ```bash
   bash scripts/kaggle/upload_raw_pcap_dataset.sh
   ```
2. **Kiểm tra trạng thái sẵn sàng của dataset trên Kaggle**:
   ```bash
   .venv-tools/bin/kaggle datasets status <owner/dataset-slug>
   ```
3. **Đóng gói và đẩy kernel Time-Series (hỗ trợ `--dry-run`)**:
   ```bash
   bash scripts/kaggle/push_timeseries_lstm.sh
   ```
4. **Giám sát trạng thái thực thi**:
   ```bash
   bash scripts/kaggle/status_timeseries_lstm.sh
   ```
5. **Tải các tạo tác kết quả về cục bộ**:
   ```bash
   bash scripts/kaggle/pull_timeseries_outputs.sh --force
   ```

---

## 11. Bảng Tổng Hợp Trạng Thái Bằng Chứng & Kết Quả Thực Nghiệm

Để chuẩn bị nội dung cho báo cáo học thuật và slide thuyết trình, bảng dưới đây tổng hợp trạng thái thực tế của toàn bộ các chỉ số:

| Hạng mục đánh giá | Tầng | Nguồn dữ liệu | Mô hình | Giao thức phân chia | F1-Score | Trạng thái bằng chứng |
| :--- | :---: | :--- | :--- | :--- | :---: | :---: |
| **Statistical Flow** | L1 | Kaggle Mirror v3 (29 đặc trưng) | Random Forest | 80/20 Flow Random | **0.9964** | **[Project-Observed] (Verified)** |
| **Statistical Flow** | L1 | Paper 2020 (28 đặc trưng) | Random Forest | 80/20 Flow Random | **0.9930** | **[Paper-Reported] (Immutable)** |
| **Statistical Flow** | L2 | Kaggle Mirror v3 (29 đặc trưng) | HistGradientBoosting | 80/20 Flow Random | **0.9999** | **[Project-Observed] (Verified)** |
| **Statistical Flow** | L2 | Paper 2020 (28 đặc trưng) | Random Forest | 80/20 Flow Random | **0.9990** | **[Paper-Reported] (Immutable)** |
| **Clump Sequence ($\ell=6$)** | L1 | Paper 2020 (5-tuple Clumps) | 4-Layer LSTM | 80/20 Flow Random | **0.9930** | **[Paper-Reported] (Immutable)** |
| **Clump Sequence ($\ell=6$)** | L1 | Raw PCAP (DoHLyzer Clumps) | Paper v4 LSTM | 80/20 Flow Random | **0.9784** | **[Project-Replication] (Observed)** |
| **Clump Sequence ($\ell=6$)** | L1 | Raw PCAP (DoHLyzer Clumps) | Paper v4 LSTM | 70/15/15 Disjoint | **0.0000** | **[Project-Corrected] (Observed; recall collapse at paper window)** |
| **Clump Sequence ($\ell=6$)** | L1 | Raw PCAP (DoHLyzer Clumps) | Masked BiGRU | 70/15/15 Disjoint | **0.9153** | **[Project-Improved] (Observed)** |
| **Best corrected ($\ell=5/7$)** | L1 | Raw PCAP (DoHLyzer Clumps) | Paper v4 / Masked BiGRU | 70/15/15 Disjoint | **0.9179 / 0.9651** | **BiGRU +4.73 pp F1** |
| **Clump Sequence ($\ell=3$)** | L2 | Paper 2020 (5-tuple Clumps) | 4-Layer LSTM | 80/20 Flow Random | **0.9910** | **[Paper-Reported] (Immutable)** |
| **Clump Sequence ($\ell=3$)** | L2 | Raw PCAP (DoHLyzer Clumps) | Paper v4 LSTM | 80/20 Flow Random | **0.9405** | **[Project-Replication] (Observed)** |
| **Clump Sequence ($\ell=3$)** | L2 | Raw PCAP (DoHLyzer Clumps) | Paper v4 LSTM | 70/15/15 Disjoint | **0.1324** | **[Project-Corrected] (Observed)** |
| **Clump Sequence ($\ell=3$)** | L2 | Raw PCAP (DoHLyzer Clumps) | Masked BiGRU | 70/15/15 Disjoint | **0.5538** | **[Project-Improved] (Observed)** |
| **Best corrected ($\ell=9/10$)** | L2 | Raw PCAP (DoHLyzer Clumps) | Paper v4 / Masked BiGRU | 70/15/15 Disjoint | **0.9425 / 0.9864** | **BiGRU +4.40 pp F1** |

**Biên diễn giải của lần chạy:** đây là thực nghiệm có giới hạn tài nguyên, không phải huấn luyện hội tụ trên toàn bộ 97 GB dữ liệu. Audit tìm thấy 13.754 capture sources và 13.150 session; collector xử lý 201.321 flows nhưng giữ 1.325 flows (`non_doh=500`, `benign_doh=325`, `malicious_doh=500`) do giới hạn 25 flows/capture và quota 500/class. Vì lớp benign chỉ đạt 325 flows, manifest ghi `class_quotas_satisfied=false`. Một capture iodine bị bỏ qua do `invalid pcapng header`. Tổng cộng 80 cấu hình đánh giá đã hoàn thành; mọi kết luận cải tiến chỉ áp dụng cho mẫu có giới hạn và seed 42 này.

**Kết luận hợp lệ:** dưới giao thức group-disjoint đã hiệu chỉnh, BiGRU tốt hơn Paper v4 ở best-window cho cả L1 (**+4,73 điểm phần trăm F1**) và L2 (**+4,40 điểm phần trăm F1**), đồng thời đạt FPR quan sát bằng 0 tại hai operating point tốt nhất. Không được diễn giải `FPR=0` thành cam kết vận hành ngoài mẫu; test set vẫn hữu hạn và ngưỡng được chọn từ validation.

---

## 12. Tài Liệu Đối Chiếu Bắt Buộc

1. **Hợp đồng so sánh & báo cáo kết quả**: `docs/results_comparison_schema.md`
2. **Hướng dẫn vận hành Kaggle Runner**: `docs/kaggle_runner.md`
3. **Kết quả cải tiến Phase 1 Tabular**: `docs/phase1_tabular_improvements.md`
4. **Giao thức tái hiện thực nghiệm chi tiết**: `docs/replication_protocol.md`
5. **Phân tích chuyên sâu bài báo gốc & tham số khuyết thiếu**: `docs/paper_analysis.md`
