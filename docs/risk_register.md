# Sổ Đăng Ký Rủi Ro Nghiên Cứu (Risk Register): Phát Hiện Đường Hầm DoH

---

## 1. Giới Thiệu & Khung Quản Trị Rủi Ro Nghiên Cứu

Tài liệu này thiết lập sổ đăng ký và cơ chế kiểm soát rủi ro toàn diện cho dự án tái hiện học thuật công trình:
> **MontazeriShatoori et al. (2020), *Detection of DoH Tunnels using Time-series Classification of Encrypted Traffic*, IEEE DASC/PiCom/CBDCom/CyberSciTech 2020.**  
> DOI: [`10.1109/DASC-PICom-CBDCom-CyberSciTech49142.2020.00026`](https://doi.org/10.1109/DASC-PICom-CBDCom-CyberSciTech49142.2020.00026) | Tệp cục bộ: `Papers for Capstone Projects/NetworkData2.pdf`

### 1.1 Khung Đánh Giá & Ma Trận Rủi Ro (Risk Matrix)
`Nhóm quyết định`: Mọi rủi ro được định lượng dựa trên hai trục độc lập:
* **Khả năng xảy ra (Likelihood):** `Cao (High)` $\to$ `Trung bình (Medium)` $\to$ `Thấp (Low)`.
* **Mức độ tác động (Impact):** `Nghiêm trọng (Critical)` $\to$ `Đáng kể (Major)` $\to$ `Vừa phải (Moderate)` $\to$ `Thấp (Minor)`.
* **Mức độ rủi ro tổng hợp (Risk Severity):**
  * **Cực cao (Critical Risk):** Tác động Nghiêm trọng + Khả năng Trung bình/Cao $\to$ Kích hoạt Điều kiện dừng (Stop Condition) ngay lập tức.
  * **Cao (High Risk):** Cần biện pháp giảm thiểu chủ động trước khi tiến hành thực nghiệm.
  * **Trung bình (Medium Risk):** Giám sát thường xuyên trong quá trình phát triển mã nguồn.

### 1.2 Phân Định Trách Nhiệm (Owner Roles)
`Nhóm quyết định`: Ba vai trò phụ trách chính trong nhóm nghiên cứu:
1. **Lead Researcher (Trưởng nhóm Nghiên cứu):** Chịu trách nhiệm về tính hợp lệ học thuật, phương pháp luận khoa học, kiểm soát phạm vi và tính trung thực trong công bố kết quả.
2. **Machine Learning Engineer (Kỹ sư Học máy):** Chịu trách nhiệm về đường ống dữ liệu, chống rò rỉ thông tin, cấu hình mô hình, tối ưu độ trễ và kiểm soát mã nguồn.
3. **Data & Safety Officer (Cán bộ Dữ liệu & An toàn):** Chịu trách nhiệm về tuân thủ bản quyền dữ liệu, an toàn đạo đức, an toàn môi trường mạng, ranh giới phòng thí nghiệm và bảo mật thông tin.

---

## 2. Bảng Tổng Hợp Sổ Đăng Ký Rủi Ro (Risk Register Summary)

| Mã Rủi Ro | Danh Mục Rủi Ro | Khả Năng Xảy Ra | Mức Độ Tác Động | Mức Rủi Ro | Vai Trò Chịu Trách Nhiệm | Điều Kiện Dừng (Stop Condition / Hard Redline) |
|:---:|---|:---:|:---:|:---:|:---:|---|
| **R01** | **Tính Hợp Lệ Học Thuật & Thiếu Siêu Tham Số** | Cao | Đáng kể | **Cao** | Lead Researcher | Báo cáo số liệu thực nghiệm nhưng tự ý bịa đặt là "thông số của bài báo gốc". |
| **R02** | **Bản Quyền Dữ Liệu & Quyền Tiếp Cận** | Trung bình | Nghiêm trọng | **Cao** | Data & Safety Officer | Phân phối lại tệp PCAP thô công khai lên GitHub vi phạm điều khoản của UNB CIC. |
| **R03** | **Rò Rỉ Dữ Liệu Phiên (Session Leakage)** | Cao | Đáng kể | **Cao** | ML Engineer | Báo cáo F1 > 0,99 mà không kiểm tra trùng lặp Session ID / Client IP giữa Train và Test. |
| **R04** | **Mất Cân Bằng Lớp Thực Tế vs Dataset** | Cao | Vừa phải | **Trung bình** | ML Engineer | Đánh giá mô hình chỉ bằng Accuracy thuần túy mà bỏ qua Precision, Recall, FPR và PR-AUC. |
| **R05** | **Trôi Dạt Công Cụ Phân Giải & Tên Miền** | Trung bình | Vừa phải | **Trung bình** | Lead Researcher | Kết luận mô hình có khả năng áp dụng vạn năng khi chưa kiểm thử trên tên miền ngoài Alexa Top 10k. |
| **R06** | **Phạm Vi Giao Thức Mới: TLS 1.3 & HTTP/3** | Cao | Vừa phải | **Trung bình** | Lead Researcher | Tuyên bố giải pháp phát hiện được HTTP/3 (QUIC) khi mô hình chỉ thiết kế cho TCP 443. |
| **R07** | **Đạo Đức Nghiên Cứu & Quyền Riêng Tư** | Thấp | Nghiêm trọng | **Trung bình** | Data & Safety Officer | Thu thập hoặc lưu trữ lưu lượng mạng cá nhân thật của thành viên trong nhóm hoặc trường học. |
| **R08** | **An Toàn Phòng Thí Nghiệm & Nguy Cơ Vũ Khí Hóa** | Thấp | Nghiêm trọng | **Cao** | Data & Safety Officer | Kích hoạt công cụ sinh tunnel thật (`iodine`, `dns2tcp`, `dnscat2`) hoặc phát lại PCAP ra mạng. |

---

## 3. Phân Tích Chuyên Sâu Từng Danh Mục Rủi Ro & Chiến Lược Giảm Thiểu

---

### R01: Tính Hợp Lệ Học Thuật, Khả Năng Tái Lặp & Thiếu Hụt Siêu Tham Số

* **Bối cảnh & Căn nguyên kỹ thuật:**
  * `Paper báo cáo` [Trang 4–7, Mục III-C & V]: Bài báo công bố kết quả rất cao (Precision $0,993$ và $0,999$) nhưng hoàn toàn không cung cấp:
    1. Ngưỡng timeout cụm trong thuật toán 1 (chỉ ghi chung chung `timeout`).
    2. Cấu trúc chi tiết của 4 lớp ẩn trong mô hình nơ-ron (chỉ ghi có 1 lớp LSTM ở vị trí lớp thứ hai).
    3. Bộ tối ưu hóa (Optimizer), tốc độ học (learning rate), hàm mất mát, batch size, epoch, và cơ chế dừng sớm.
    4. Cách tái định hình véc-tơ 28 đặc trưng thành ma trận đầu vào cho mô hình 2D CNN.
  * `Rủi ro/giả định`: Nếu nhóm nghiên cứu tự chọn một cấu hình siêu tham số và tự nhận đó là "siêu tham số của tác giả", tính liêm chính học thuật sẽ bị xâm phạm. Nếu các tham số tự chọn dẫn đến kết quả thấp hơn bài báo, nhóm có nguy cơ vội vã kết luận rằng "kết quả của bài báo là ngụy tạo".
* **Định lượng:** Khả năng: **Cao** | Tác động: **Đáng kể** | Mức rủi ro: **Cao**.
* **Vai trò chịu trách nhiệm:** `Lead Researcher`.
* **Chiến lược giảm thiểu (Mitigation Strategy):**
  1. `Nhóm quyết định`: Phân định minh bạch: Mọi thông số bổ sung bắt buộc phải được gắn nhãn rõ ràng là `Nhóm quyết định`. Chỉ duy nhất giá trị ngưỡng timeout gom cụm $\tau_{\text{timeout}} = 1\text{ ms}$ (`CLUMP_TIMEOUT = 0.001`) là có bằng chứng độc lập được xác thực từ mã nguồn DoHLyzer (`https://github.com/ahlashkari/DoHLyzer/blob/master/meter/constants.py`).
  2. `Nhóm quyết định`: Giữ nguyên giá trị timeout 1 ms đã được kiểm chứng từ mã nguồn DoHLyzer. Toàn bộ các lựa chọn về bộ tối ưu hóa (như Adam, tốc độ học $\text{lr} = 10^{-3}$) và kích thước lô (batch size 64 hoặc 128) hoàn toàn là quyết định thực nghiệm của nhóm nghiên cứu (`Nhóm quyết định`), không phải là thông số được DoHLyzer xác nhận, và bắt buộc phải được quản lý phiên bản rõ ràng trong bằng chứng thực nghiệm (`experiment_evidence.json`).
  3. `Nhóm quyết định`: Tiến hành khảo sát triệt tiêu (Ablation Study) trên một dải tham số rộng để chứng minh tính ổn định của phương pháp luận thay vì chỉ chạy một cấu hình đơn lẻ.
* **Điều kiện dừng / Ranh giới đỏ (Stop Condition):**
  * **CẤM TUYỆT ĐỐI** phát hành báo cáo hoặc nộp bài nghiệm thu khi có bất kỳ phát biểu nào khẳng định nhóm đã "sử dụng siêu tham số huấn luyện chính xác của bài báo" nếu không có bằng chứng văn bản từ tác giả hoặc mã nguồn kiểm chứng.

---

### R02: Bản Quyền Dữ Liệu, Giấy Phép Sử Dụng & Quyền Truy Cập (Data Access & Licensing)

* **Bối cảnh & Căn nguyên kỹ thuật:**
  * `Paper báo cáo` [Trang 5, Mục IV, Ref 27]: Bộ dữ liệu CIRA-CIC-DoHBrw-2020 được lưu trữ tại máy chủ của Viện An ninh mạng Canada (UNB CIC): [https://www.unb.ca/cic/datasets/dohbrw-2020.html](https://www.unb.ca/cic/datasets/dohbrw-2020.html).
  * `Rủi ro/giả định`: Việc tải về bộ dữ liệu thô (PCAP dung lượng hàng chục Gigabyte) yêu cầu điền biểu mẫu đăng ký học thuật với thông tin cá nhân và tổ chức. Bộ dữ liệu được cấp phép miễn phí cho mục đích học thuật và nghiên cứu phi thương mại, kèm theo yêu cầu bắt buộc phải trích dẫn bài báo gốc và công cụ DoHMeter. Tuy nhiên, việc tự ý đóng gói các tệp PCAP thô này vào kho lưu trữ mã nguồn Git công khai (GitHub repository) có thể vi phạm điều khoản phân phối lại của UNB CIC và làm phình to kho mã nguồn không cần thiết.
* **Định lượng:** Khả năng: **Trung bình** | Tác động: **Nghiêm trọng** | Mức rủi ro: **Cao**.
* **Vai trò chịu trách nhiệm:** `Data & Safety Officer`.
* **Chiến lược giảm thiểu (Mitigation Strategy):**
  1. `Nhóm quyết định`: Đăng ký tài khoản và gửi biểu mẫu chính thức tại cổng thông tin UNB CIC để nhận quyền tải về hợp pháp. Ghi vết toàn bộ URL, mã xác nhận và thời điểm tải vào tệp `dataset_manifest.json`.
  2. `Nhóm quyết định`: Tuyệt đối không commit tệp PCAP thô hay tệp CSV lớn lên kho mã nguồn Git. Cấu hình `.gitignore` loại trừ triệt để toàn bộ thư mục chứa dữ liệu thô (`doh_tunnel_detection/data/raw/`).
  3. `Nhóm quyết định`: Đối với các đợt kiểm thử CI/CD và demo ngoại tuyến, chỉ sử dụng tệp dữ liệu chuỗi cụm thu nhỏ đã được nhóm tác giả phát hành công khai theo giấy phép MIT trong kho DoHLyzer (`analyzer/sample_data/doh.json.gz`), hoặc sử dụng bộ tạo dữ liệu giả lập (synthetic demo data generator) hoàn toàn không chứa lưu lượng thật.
* **Điều kiện dừng / Ranh giới đỏ (Stop Condition):**
  * **CẤM TUYỆT ĐỐI** đẩy các tệp dữ liệu thô (.pcap, .pcapng) lên bất kỳ dịch vụ lưu trữ đám mây công cộng nào mà không có sự phê duyệt bằng văn bản về điều khoản giấy phép từ UNB CIC.

---

### R03: Rò Rỉ Dữ Liệu Phiên & Gian Lận Thống Kê (Data Leakage & Session Snooping)

* **Bối cảnh & Căn nguyên kỹ thuật:**
  * `Paper báo cáo` [Trang 6, Mục IV]: Tác giả áp dụng kỹ thuật phân chia ngẫu nhiên 80% Train và 20% Test trên toàn bộ danh sách các luồng mạng (Flow-level random split).
  * `Rủi ro/giả định`: Trong môi trường thu thập thực tế của bài báo (10 máy trạm ảo kết nối tới 1 máy chủ C2, duyệt lặp lại các tên miền Alexa Top 10k), các luồng mạng phát sinh trong cùng một phiên thử nghiệm (cùng một kịch bản JSON, cùng một cấu hình client tunnel, cùng một khoảng thời gian) sẽ có đặc tính gói tin gần như đồng nhất. Khi phân chia ngẫu nhiên ở cấp độ luồng, các luồng thuộc cùng một phiên sẽ bị xé lẻ và xuất hiện ở cả tập Train lẫn tập Test. Mô hình học sâu sẽ "học vẹt" địa chỉ IP, kích thước khung TLS đặc thù của phiên đó thay vì học được bản chất hành vi phân giải DoH. Điều này dẫn đến hiện tượng "Hiệu năng hoàn hảo trên tập kiểm thử nhưng tê liệt ngoài thực tế" (Overfitting by Leakage).
* **Định lượng:** Khả năng: **Cao** | Tác động: **Đáng kể** | Mức rủi ro: **Cao**.
* **Vai trò chịu trách nhiệm:** `Machine Learning Engineer`.
* **Chiến lược giảm thiểu (Mitigation Strategy):**
  1. `Nhóm quyết định`: Bắt buộc thực hiện đánh giá song song hai giao thức phân chia:
     * *Giao thức A:* 80/20 Flow Split để đối chiếu với bài báo gốc.
     * *Giao thức B (Giao thức chuẩn của nhóm):* **Group-based Stratified Split**. Nhóm các luồng theo `Capture_Session_ID`, theo `Client_Host_ID` (10 máy trạm ảo) hoặc theo dải thời gian thu thập độc lập. Đảm bảo toàn bộ luồng của một phiên hoặc một máy trạm chỉ nằm hoàn toàn trong tập Train hoặc tập Test.
  2. `Nhóm quyết định`: Khớp (fit) toàn bộ bộ chuẩn hóa dữ liệu (`StandardScaler`, `MinMaxScaler`) nghiêm ngặt CHỈ trên tập Train; cấm tuyệt đối việc fit trên toàn bộ dataset trước khi chia.
* **Điều kiện dừng / Ranh giới đỏ (Stop Condition):**
  * Nếu phát hiện có bất kỳ mã nhận diện phiên (`Session_ID`) hoặc cặp IP-Port trùng lặp xuất hiện đồng thời trong cả tập Train và tập Test của giao thức B, toàn bộ kết quả thực nghiệm phải bị hủy bỏ và tiến hành chia lại dữ liệu từ đầu.

---

### R04: Mất Cân Bằng Lớp Trong Môi Trường Mạng Doanh Nghiệp Thực Tế (Class Imbalance)

* **Bối cảnh & Căn nguyên kỹ thuật:**
  * `Paper báo cáo` [Trang 6, Bảng II]: Trong bộ dữ liệu thu thập, số lượng gói tin của các công cụ tunneling lên tới hàng chục triệu (ví dụ Iodine thu được hơn 105 triệu gói, dns2tcp hơn 42 triệu gói), trong khi duyệt web Chrome chỉ có từ 4 đến 10 triệu gói.
  * `Rủi ro/giả định`: Nghiên cứu độc lập của Niktabe et al. (2023, York University BCCC, [DOI: 10.1007/s12083-023-01597-4](https://doi.org/10.1007/s12083-023-01597-4)) chỉ ra rằng bộ dữ liệu CIRA-CIC-DoHBrw-2020 bị mất cân bằng lớp nghiêm trọng (khoảng 90% luồng DoH là tunneling độc hại và chỉ có 10% là duyệt web thông thường). Ngược lại, trong mạng doanh nghiệp thực tế, 99,99% lưu lượng DoH là duyệt web hợp pháp và chỉ có dưới 0,01% là kênh ngầm độc hại. Nếu áp dụng trực tiếp mô hình được huấn luyện trên tập dữ liệu thiên lệch mà không cân chỉnh, tỷ lệ báo động giả (False Positive Rate) sẽ bùng nổ, gây tắc nghẽn trung tâm điều hành an ninh mạng (SOC).
* **Định lượng:** Khả năng: **Cao** | Tác động: **Vừa phải** | Mức rủi ro: **Trung bình**.
* **Vai trò chịu trách nhiệm:** `Machine Learning Engineer`.
* **Chiến lược giảm thiểu (Mitigation Strategy):**
  1. `Nhóm quyết định`: Sử dụng kỹ thuật cân bằng trọng số lớp (`class_weight='balanced'`) trong hàm mất mát khi huấn luyện mô hình.
  2. `Nhóm quyết định`: Khảo sát biến thể dữ liệu cân bằng *BCCC-CIRA-CIC-DoHBrw-2020* (sử dụng SMOTE cân bằng 50/50 do BCCC phát hành) để đánh giá độ lệch chuẩn.
  3. `Nhóm quyết định`: Tuyệt đối không sử dụng độ chính xác tổng thể (Accuracy) làm chỉ số đánh giá chính. Bắt buộc báo cáo đầy đủ: Precision, Recall, F1-Score, False Positive Rate (FPR) và diện tích dưới đường cong Precision-Recall (PR-AUC).
* **Điều kiện dừng / Ranh giới đỏ (Stop Condition):**
  * Dừng triển khai nếu tỷ lệ báo động giả (False Positive Rate) trên tập dữ liệu duyệt web hợp pháp vượt quá $1,0\%$ ($\text{FPR} > 0,01$), vì mức báo động giả này sẽ làm tê liệt hoạt động giám sát thực tế.

---

### R05: Trôi Dạt Công Cụ Phân Giải, Tên Miền & Chữ Ký Trình Duyệt (Environmental Drift)

* **Bối cảnh & Căn nguyên kỹ thuật:**
  * `Paper báo cáo` [Trang 5, Mục IV]: Dữ liệu được thu thập vào năm 2019–2020 trên các phiên bản cũ của Google Chrome và Mozilla Firefox, chỉ kết nối đến 4 máy chủ DoH công cộng (AdGuard, Cloudflare, Google DNS, Quad9) và tập trung vào 10.000 tên miền hàng đầu của Alexa.
  * `Rủi ro/giả định`:
    1. **Trôi dạt máy chủ DoH:** Hiện nay có hàng trăm nhà cung cấp DoH công cộng và DoH nội bộ doanh nghiệp với các cơ chế đệm truy vấn (caching), nén bản ghi và cấu hình Anycast IP hoàn toàn khác biệt.
    2. **Trôi dạt dịch vụ web:** Danh sách Alexa Top 10k đã ngừng hoạt động chính thức từ năm 2022 (chuyển sang Tranco List hoặc Cisco Umbrella). Cấu trúc các trang web hiện đại tích hợp hàng chục nhà cung cấp dịch vụ đám mây (CDN), tạo ra các đợt bùng nổ truy vấn DNS dày đặc hơn nhiều so với năm 2020.
    3. **Trôi dạt công cụ tunneling:** Kẻ tấn công hiện đại không còn chỉ sử dụng các công cụ kinh điển như Iodine, dns2tcp, dnscat2 mà chuyển sang các framework C2 tiên tiến (Cobalt Strike DNS Beacon, Mythic, Sliver) có kỹ thuật chèn độ trễ ngẫu nhiên (jittering) và chia nhỏ payload để ngụy trang tinh vi.
* **Định lượng:** Khả năng: **Trung bình** | Tác động: **Vừa phải** | Mức rủi ro: **Trung bình**.
* **Vai trò chịu trách nhiệm:** `Lead Researcher`.
* **Chiến lược giảm thiểu (Mitigation Strategy):**
  1. `Nhóm quyết định`: Giới hạn phạm vi tuyên bố khoa học: Nghiên cứu này tập trung kiểm chứng khả năng phát hiện các kênh ngầm dạng luồng dữ liệu (data stream tunnels) có nhịp truyền liên tục (100–1100 B/s) như bài báo mô tả, không khái quát hóa cho toàn bộ các dạng C2 beaconing tần suất thấp.
  2. `Nhóm quyết định`: Phân tích triệt tiêu độ trễ giữa các truy vấn nhằm xác định ngưỡng tần suất gửi tối thiểu mà mô hình còn có thể phát hiện được.
* **Điều kiện dừng / Ranh giới đỏ (Stop Condition):**
  * Tuyên bố trong phần giới hạn nghiên cứu rằng kết quả thực nghiệm chưa kiểm chứng trên các biến thể C2 hiện đại ngoài tập dữ liệu CIRA-CIC-DoHBrw-2020.

---

### R06: Phạm Vi Tiến Hóa Giao Thức Mạng: TLS 1.3, ECH & HTTP/3 (QUIC)

* **Bối cảnh & Căn nguyên kỹ thuật:**
  * `Paper báo cáo` [Trang 1–4, Mục I & III]: Bài báo được thiết kế và thu thập hoàn toàn dựa trên giao thức DoH qua HTTP/2 chạy trên nền TLS 1.2 qua cổng TCP 443.
  * `Rủi ro/giả định`:
    1. **TLS 1.3 (RFC 8446):** Bắt buộc mã hóa toàn bộ quá trình bắt tay sau Server Hello, loại bỏ hoàn toàn các bản tin bản rõ, đồng thời tích hợp cơ chế đệm bản ghi (Record Padding) ngẫu nhiên làm thay đổi phân bố kích thước byte của cụm gói tin ($\text{size}$).
    2. **Encrypted Client Hello (ECH):** Che giấu hoàn toàn trường SNI (Server Name Indication), ngăn chặn tường lửa nhận biết tên miền của máy chủ DoH mục tiêu nếu không dựa vào IP.
    3. **HTTP/3 trên nền QUIC (RFC 9000 / RFC 9250 - DoQ):** Chuyển dịch toàn bộ hạ tầng từ TCP 443 sang UDP 443. Giao thức QUIC không có khái niệm luồng TCP truyền thống, quản lý ghép kênh độc lập trên từng stream và tự động mã hóa thông tin điều khiển gói tin (Packet Numbers, ACK frames). Toàn bộ giả định về 5-tuple TCP và việc lọc bỏ gói tin "pure TCP ACK" của bài báo sẽ hoàn toàn sụp đổ trên môi trường HTTP/3.
* **Định lượng:** Khả năng: **Cao** | Tác động: **Vừa phải** | Mức rủi ro: **Trung bình**.
* **Vai trò chịu trách nhiệm:** `Lead Researcher`.
* **Chiến lược giảm thiểu (Mitigation Strategy):**
  1. `Nhóm quyết định`: Xác định ranh giới bài toán: Đề tài giới hạn phạm vi chặt chẽ trong phân tích lưu lượng **DoH trên nền TCP cổng 443 (DoH over HTTP/2 / TLS)** theo đúng phạm vi của bài báo gốc.
  2. `Nhóm quyết định`: Ghi nhận rõ trong tài liệu kiến trúc rằng lưu lượng DoQ (DNS over QUIC) hoặc DoH/3 chạy trên UDP cổng 443 là một bài toán mở độc lập, đòi hỏi bộ trích xuất luồng QUIC chuyên biệt và nằm ngoài phạm vi tái hiện trực tiếp của công trình này.
* **Điều kiện dừng / Ranh giới đỏ (Stop Condition):**
  * Không mở rộng mã nguồn để phân tích gói tin UDP trừ khi có một giao thức nghiên cứu bổ sung được phê duyệt riêng biệt.

---

### R07: Đạo Đức Nghiên Cứu & Bảo Vệ Quyền Riêng Tư Người Dùng (Privacy & Ethics)

* **Bối cảnh & Căn nguyên kỹ thuật:**
  * `Paper báo cáo` [Trang 1, Mục I]: Mục đích sinh ra giao thức DoH là để bảo vệ quyền riêng tư cá nhân của người sử dụng Internet trước sự nhòm ngó của các thực thể mạng.
  * `Rủi ro/giả định`: Khi xây dựng các mô hình máy học phân loại lưu lượng DoH, nếu hệ thống vô tình phân tích hoặc ghi lại các dấu vết truy cập web cụ thể của con người, nguy cơ xâm phạm quyền riêng tư (Privacy Violation) và vi phạm các quy định đạo đức nghiên cứu học thuật sẽ xuất hiện. Nếu nhóm nghiên cứu tự ý "bắt gói tin mạng trong ký túc xá hoặc phòng lab của trường" để làm dữ liệu kiểm thử, hành vi này có thể vi phạm pháp luật về an toàn thông tin và quyền bảo mật thư tín.
* **Định lượng:** Khả năng: **Thấp** | Tác động: **Nghiêm trọng** | Mức rủi ro: **Trung bình**.
* **Vai trò chịu trách nhiệm:** `Data & Safety Officer`.
* **Chiến lược giảm thiểu (Mitigation Strategy):**
  1. `Nhóm quyết định`: Tuyệt đối tuân thủ nguyên tắc: **Chỉ sử dụng dữ liệu mở ẩn danh hóa đã công bố chính thức** (*CIRA-CIC-DoHBrw-2020* và *BCCC-CIRA-CIC-DoHBrw-2020*).
  2. `Nhóm quyết định`: Không thu thập bất kỳ gói tin mạng trực tiếp nào từ người dùng thực tế. Dữ liệu thử nghiệm bổ sung nếu có chỉ được tạo ra thông qua các script tự động truy vấn tên miền công cộng được chỉ định trước trong môi trường lab khép kín.
  3. `Nhóm quyết định`: Toàn bộ các đặc trưng trích xuất (28 đặc trưng DoHMeter và 5 tham số Clump) là các siêu dữ liệu thống kê phi nội dung (non-content statistical metadata). Tuyệt đối không lưu trữ chuỗi truy vấn DNS, không can thiệp giải mã nội dung TLS.
* **Điều kiện dừng / Ranh giới đỏ (Stop Condition):**
  * **CẤM TUYỆT ĐỐI** triển khai công cụ bắt gói tin (`sniffing`, `tcpdump`) trên bất kỳ giao diện mạng công cộng hoặc mạng dùng chung nào của trường Đại học Bách Khoa Hà Nội (HUST).

---

### R08: An Toàn Phòng Thí Nghiệm & Phòng Ngừa Vũ Khí Hóa (Lab Safety & Dual-Use)

* **Bối cảnh & Căn nguyên kỹ thuật:**
  * `Paper báo cáo` [Trang 5, Mục IV]: Bài báo sử dụng các công cụ đường hầm DNS (`iodine`, `dns2tcp`, `dnscat2`) để tạo lưu lượng tấn công.
  * `Rủi ro/giả định`: Các công cụ như `dnscat2` hay `iodine` là các công cụ kiểm thử xâm nhập hai mục đích (Dual-Use Tools) thường xuyên bị các nhóm tấn công mạng lợi dụng làm phần mềm độc hại để thiết lập kênh C2 vượt tường lửa. Nếu sinh viên hoặc thành viên nhóm cài đặt và vận hành các công cụ này trên hạ tầng mạng thực tế, hành vi này có thể:
    1. Kích hoạt hệ thống phòng thủ (SIEM/EDR) của trường, dẫn đến việc bị cô lập mạng hoặc xử lý kỷ luật.
    2. Vô tình biến máy tính cá nhân thành máy chủ proxy mở, bị kẻ tấn công bên ngoài lợi dụng làm bàn đạp tấn công chuyển tiếp.
    3. Vi phạm nghiêm trọng thỏa ước an toàn nghiên cứu phòng thủ.
* **Định lượng:** Khả năng: **Thấp** | Tác động: **Nghiêm trọng** | Mức rủi ro: **Cao**.
* **Vai trò chịu trách nhiệm:** `Data & Safety Officer`.
* **Chiến lược giảm thiểu (Mitigation Strategy):**
  1. `Nhóm quyết định`: **Chính sách Không Sinh Mã Độc / Không Chạy Kênh Ngầm Thật (Zero Live Tunneling Policy):** Trong toàn bộ mã nguồn của dự án (`doh_tunnel_detection/`), tuyệt đối không chứa bất kỳ tệp thực thi, script cấu hình hay mã nguồn nào hướng dẫn hoặc tự động hóa việc khởi tạo kênh ngầm với `iodine`, `dns2tcp` hay `dnscat2`.
  2. `Nhóm quyết định`: Toàn bộ quá trình phát triển, kiểm thử mã nguồn và xác minh tính đúng đắn của thuật toán phải diễn ra ở chế độ **ngoại tuyến hoàn toàn (Offline Mode)** trên các tệp dữ liệu đã ghi nhận từ trước.
  3. `Nhóm quyết định`: Mô-đun demo nội bộ (`demo.py`) sử dụng dữ liệu chuỗi cụm giả lập tổng hợp (synthetic clumps) được tạo ra từ thuật toán toán học tất định trong bộ nhớ RAM, không thực hiện bất kỳ lời gọi hệ thống nào ra mạng.
* **Điều kiện dừng / Ranh giới đỏ (Stop Condition):**
  * **CẤM TUYỆT ĐỐI** cài đặt, biên dịch hoặc thực thi các gói phần mềm client/server của `iodine`, `dns2tcp`, `dnscat2` trên bất kỳ thiết bị nào thuộc phạm vi dự án mà không có môi trường sandbox cách ly vật lý hoàn toàn được cấp phép bằng văn bản.

---

## 4. Bốn Ranh Giới Đỏ Bất Khả Xâm Phạm (Inviolable Redlines)

Để đảm bảo dự án vận hành an toàn tuyệt đối và duy trì tính liêm chính khoa học cao nhất, nhóm nghiên cứu thiết lập 4 "Ranh giới đỏ" có giá trị tối cao:

```text
+----------------------------------------------------------------------------------------------------+
|                                BỐN RANH GIỚI ĐỎ BẤT KHẢ XÂM PHẠM                                    |
+----------------------------------------------------------------------------------------------------+
| 1. KHÔNG SINH ĐƯỜNG HẦM THẬT (NO LIVE TUNNELS):                                                    |
|    Tuyệt đối không chạy iodine, dns2tcp, dnscat2 ra mạng internet hoặc mạng nội bộ.                 |
+----------------------------------------------------------------------------------------------------+
| 2. KHÔNG RÒ RỈ DỮ LIỆU & BẢN QUYỀN (NO PCAP LEAKAGE):                                              |
|    Tuyệt đối không commit tệp PCAP thô hoặc thông tin cá nhân lên GitHub; tuân thủ bản quyền UNB.   |
+----------------------------------------------------------------------------------------------------+
| 3. KHÔNG BỊA ĐẶT THÔNG SỐ (NO FABRICATED PARAMETERS):                                              |
|    Mọi tham số không có trong văn bản PDF phải được gán nhãn [Nhóm quyết định], cấm ngụy tạo.       |
+----------------------------------------------------------------------------------------------------+
| 4. KHÔNG MẠO DANH HIỆU NĂNG MÔ HÌNH (NO PROXY PERFORMANCE CLAIMS):                                |
|    Mô-đun demo synthetic bằng Python stdlib chỉ là bằng chứng quy trình, cấm tự nhận là LSTM paper. |
+----------------------------------------------------------------------------------------------------+
```

Mọi vi phạm đối với một trong bốn ranh giới đỏ trên đều dẫn đến việc đình chỉ ngay lập tức nhánh phát triển liên quan và triệu tập cuộc họp rà soát khẩn cấp của toàn bộ nhóm nghiên cứu.
