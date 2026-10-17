# Phase B — chạy scale trên Windows với RTX 2060-class

## Mục tiêu và phạm vi

Phase B kiểm tra độ ổn định của kết quả khi tăng dữ liệu, không thay thế kết quả Phase A đã đo trên Mac. Mọi stage đều dùng:

- raw PCAP CIRA-CIC-DoHBrw-2020;
- split `session_scenario_disjoint` để không rò rỉ session/scenario;
- Paper v4 LSTM và Mask-aware BiGRU;
- Layer 1 với cửa sổ `l ∈ {5, 7}`;
- Layer 2 với cửa sổ `l ∈ {9, 10}`;
- calibration và threshold chỉ từ validation fold;
- benchmark latency batch size 1 sau khi warm-up.

> “RTX 2060 Ti” thường được người dùng gọi cho nhóm RTX 2060/2060 Super. Script chỉ yêu cầu PyTorch nhận CUDA; VRAM 6–8 GB đủ cho các model nhỏ này. Nút thắt chính vẫn là đọc/giải mã PCAP từ disk và RAM, không phải GPU.

## 1. Chuẩn bị

### Phần cứng

1. Gắn ổ chứa dataset, ví dụ `E:\PCAPs_members`.
2. Tắt sleep/hibernate trong lúc chạy.
3. Giữ ít nhất 20 GB trống trên ổ chứa repository/output.
4. Khuyến nghị RAM 32 GB. Nếu RAM thấp hơn, chạy từng stage và theo dõi Task Manager trước khi tăng scale.
5. Không rút ổ dataset trong lúc runner còn hoạt động.

### Python và CUDA

Trong PowerShell, tại thư mục repository:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r experiments\kaggle\timeseries_clump_lstm\requirements.txt
```

Nếu lệnh trên cài bản PyTorch không có CUDA, dùng lệnh cài đặt hiện hành từ **PyTorch Start Locally** cho Windows + phiên bản CUDA tương thích driver NVIDIA, rồi kiểm tra:

```powershell
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA')"
```

Điều kiện để chạy: dòng thứ hai là `True` và dòng thứ ba hiển thị GPU NVIDIA.

## 2. Audit dataset trước khi train

```powershell
python experiments\kaggle\timeseries_clump_lstm\train_timeseries.py `
  --dataset-dir "E:\PCAPs_members" `
  --audit-only `
  --output-dir "artifacts\windows-audit"
```

Chỉ tiếp tục khi:

- process exit code bằng `0`;
- `artifacts\windows-audit\pcap_audit.json` tồn tại;
- số capture/source phù hợp với dataset đã copy;
- không có lỗi archive, path hoặc disk disconnect trong console.

## 3. Chạy theo stage

Script chuẩn:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\run_timeseries_scale.ps1 `
  -DatasetDir "E:\PCAPs_members" `
  -OutputRoot "D:\doh-results\windows-scale"
```

| Stage | `max_flows_per_capture` | `max_flows_per_class` | `max_windows_per_class` | Mục đích |
|---:|---:|---:|---:|---|
| 25 | 25 | 500 | 10,000 | Tái lập capped run, kiểm tra môi trường |
| 50 | 50 | 1,000 | 20,000 | Kiểm tra xu hướng khi tăng gấp đôi |
| 100 | 100 | 2,500 | 50,000 | Scale trung bình |
| 250 | 250 | 5,000 | 100,000 | Scale lớn trước khi cân nhắc uncapped |

Chạy riêng một hoặc vài stage:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\run_timeseries_scale.ps1 `
  -DatasetDir "E:\PCAPs_members" `
  -OutputRoot "D:\doh-results\windows-scale" `
  -Stages 25,50
```

### Resume

Đơn vị resume là **stage + task**, ví dụ `stage-50-l1` hoặc `stage-50-l2`.

- Nếu `experiment_manifest.json` có `status: training_completed` và `latency_benchmarks.json` tồn tại, script bỏ qua đơn vị đó.
- Nếu máy tắt giữa một đơn vị, chạy lại cùng lệnh. Các đơn vị hoàn tất được skip; đơn vị dở dang chạy lại từ đầu.
- Runner không lưu model checkpoint theo chủ đích, nên không resume giữa epoch. Dataset/model hiện tại nhỏ; checkpoint nhị phân cũng bị safety guard loại bỏ khỏi output.
- Log liên tục nằm trong `<OutputRoot>\stage-<N>-<task>\console.log`.

## 4. Điều kiện tăng stage

Chỉ chuyển từ stage hiện tại sang stage tiếp theo khi cả L1 và L2 thỏa:

1. `status = training_completed`;
2. không có overlap trong split manifest;
3. không có OOM hoặc disk disconnect;
4. `metrics.json` và `latency_benchmarks.json` đều tồn tại;
5. peak RAM còn biên an toàn tối thiểu khoảng 20%;
6. F1 corrected và FPR không biến động bất thường so với stage trước.

Nếu ingestion chậm nhưng GPU nhàn, đó là hành vi dự kiến: decode PCAP là CPU/I/O-bound. Copy dataset sang SSD nội bộ sẽ cải thiện thời gian hơn đổi batch size.

## 5. Uncapped/full run

Không chạy full tự động. Sau stage 250, chỉ bật khi RAM và thời gian stage cho thấy còn đủ biên:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\run_timeseries_scale.ps1 `
  -DatasetDir "E:\PCAPs_members" `
  -OutputRoot "D:\doh-results\windows-scale" `
  -Stages 250 `
  -IncludeFull
```

`-IncludeFull` đặt `max_flows_per_capture`, `max_flows_per_class`, và `max_windows_per_class` thành `null`; các giới hạn an toàn packet/byte/archive vẫn giữ nguyên. Đây mới là uncapped theo flow/window quota. Nếu RAM tăng gần tuyến tính ở stage 100 → 250, dừng ở stage 250 và báo cáo đường hội tụ; không gọi stage đó là “full dataset”.

## 6. Artifact cần mang về

Mỗi thư mục `stage-<N>-<task>` phải có:

- `experiment_manifest.json` — config, hardware, caps, counters, tổng thời gian;
- `metrics.json` — accuracy, precision, recall, F1, FPR, AUC;
- `latency_benchmarks.json` và `.csv` — collection/preprocessing/inference/end-to-end;
- `training_history.csv`;
- confusion matrices;
- `console.log`.

Không cần copy raw PCAP vào Git. Nén riêng thư mục output và đưa lại vào `artifacts/windows-scale/` để generate bảng convergence và cập nhật slide.

## 7. Cách đọc latency

- `traffic_collection_delay`: thời gian thực của traffic để thu đủ `l` clump đầu tiên.
- `preprocessing_latency`: normalize, pad/mask, tạo tensor và copy sang device; không gồm disk I/O.
- `inference_latency`: forward pass của model đã warm-up, batch size 1; CUDA được synchronize trước/sau phép đo.
- `end_to_end_latency`: tổng ba thành phần trên từng sample.

So sánh thời gian phải giữ cùng window, task, split và định nghĩa latency. Không so trực tiếp paper “flow duration” với GPU inference-only rồi kết luận tăng tốc end-to-end.
