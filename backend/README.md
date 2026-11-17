# Backend SmartFood · bản local để review

Ứng dụng FastAPI chạy theo kiến trúc modular monolith. Mỗi thư mục dưới đây là một phần nghiệp vụ của mục 8.3 trong Description. Máy chủ dùng chung phiên đăng nhập W1, kiểm tra quyền theo hộ tại thời điểm yêu cầu, ghi bằng giao dịch SQLite và phục vụ đặc tả trực tiếp ở `/openapi.json`.

| Thư mục | Yêu cầu | Điều cần kiểm tra |
|---|---|---|
| [auth](auth/) | FR-01 | Đăng ký, đăng nhập, logout, cookie phiên, giới hạn thử sai |
| [households](households/) | FR-02–04 | Mã mời một lượt, quyền Owner/Member, chuyển chủ và rút quyền |
| [catalog](catalog/) | FR-06–08 | Tra cứu có dấu, chọn khi trùng bí danh, gợi ý gần đúng, quy đổi g/ml/quả theo quy cách từng dòng |
| [inventory](inventory/) | FR-07–10, 17, 21 | Tạo/sửa lô, FIFO, xác nhận sử dụng, sổ biến động, kiểm kê và snapshot có thời điểm đồng bộ |
| [receipts](receipts/) | FR-05–07 | Upload PNG/JPEG, Windows OCR, tách tên/lượng/đơn vị, sửa bản nháp theo phiên bản và xác nhận toàn bộ một lần |
| [monitoring](monitoring/) | FR-11–12 | Hạn thiếu, ước tính, sắp tới hạn, quá hạn và lô bị đánh dấu. Trạng thái đọc theo từng tài khoản |
| [dietary_recipes](dietary_recipes/) | FR-14–15 | Hồ sơ riêng, công thức và nguyên liệu theo khẩu phần. CLI nạp dữ liệu đã kiểm duyệt |
| [recommendation](recommendation/) | FR-15 | Hai cách xếp hạng dùng chung điều kiện loại trừ. Kết quả có điểm bao phủ, nguyên liệu cần mua và mức tận dụng lô sắp đến hạn |
| [meal_grocery](meal_grocery/) | FR-16, 18 | Lập/sửa/xóa bữa, tính lượng thiếu theo ngày và FIFO, xác nhận danh sách mua rồi đánh dấu từng mục |
| [waste_reports](waste_reports/) | FR-19–20 | Ghi bỏ đi qua API biến động kho, thống kê theo sản phẩm, đơn vị, ngày và lý do. Quá hạn chỉ tạo cảnh báo |
| [audit_config](audit_config/) | FR-22 | Migration, cấu hình DB, nhật ký nghiệp vụ, giờ Việt Nam và khóa chống gửi lặp. Middleware HTTP ở main.py |

## Chạy một bản để kiểm tra

Mở PowerShell tại thư mục repo AI_Food. Cài Python 3.14 x64, tạo venv theo README gốc và cài `requirements-browser.txt` để chạy cả API và Chrome. Đặt DB riêng cho review trước khi mở server.

```powershell
$env:SMARTFOOD_DB = Join-Path (Get-Location) 'var/backend-review.sqlite3'
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 --no-proxy-headers
```

Dùng [Swagger](http://127.0.0.1:8001/docs) để đọc hợp đồng, hoặc gửi HTTP trực tiếp. Mọi yêu cầu ngoài GET/HEAD/OPTIONS cần header `X-SmartFood: 1`. Giữ cookie từ login. API đã đăng nhập nhận thêm `X-SmartFood-Actor` để phát hiện đổi tài khoản. Lệnh sau chạy cả bộ test với dữ liệu tạm.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "*.py" -v
```

## Luồng để review từng phần

1. Tạo tài khoản và household. GET `/api/catalog/products` để xem ID. POST `/api/catalog/preview` với `{"product_id":1,"quantity":"0.125","unit":"kg"}` trả 125000 bước, tương ứng 125 g. Bước lưu là 0,001 g/ml hoặc một quả. DTO nhận số dạng chuỗi và từ chối quy đổi sai nhóm.
2. Dùng đường dẫn hộ `/api/households/{hid}`. POST `inventory/batches` với dữ liệu lượng, ngày nhận, nguồn hạn và request_key. POST `inventory/batches/{bid}/count-preview` chỉ tính chênh. Gửi `movements` loại adjust với lượng thực đếm và version để xác nhận. Kiểm tra sổ bằng GET `ledger`. Chỉ lô có hạn từ nhãn/người dùng, còn hạn và chưa bị đánh dấu mới được hệ thống đề xuất.
3. POST `receipts` với thân request là bytes ảnh và Content-Type image/png hoặc image/jpeg. Ảnh tối đa 5 MiB và 12 triệu pixel. Ảnh gốc chỉ xử lý trong bộ nhớ rồi giải phóng. SHA-256 cho biết có ảnh giống hệt trong cùng hộ. Backend giữ văn bản OCR, dòng đã sửa và kết quả xác nhận. PUT bản nháp với version trước khi POST confirm. Nếu không có OCR hoặc ảnh mờ, người dùng có thể nhập tay qua kho.
4. PUT `/api/me/dietary` với danh sách dị ứng, nhãn chế độ ăn bắt buộc và ID sản phẩm thích. Bao gồm cả danh sách rỗng nếu người dùng đã xác nhận. Với cùng người ăn và tồn, thử POST recommendations lần lượt method content và multi. Xem phần thiếu sau khi kiểm tra ràng buộc. Trọng số là cấu hình demo để so sánh, chưa hiệu chỉnh trên tập development.
5. POST meals, GET groceries với start/end. Gửi lại đúng items đã xem để xác nhận grocery-lists, rồi đánh dấu purchased. Các thao tác này giữ nguyên tồn. Chỉ lệnh consume/waste/adjust đã xác nhận mới ghi biến động. GET reports cho biết lượng theo từng sản phẩm tính bằng bước cơ sở, khoảng ngày tính theo giờ Việt Nam.
6. Đăng nhập tài khoản ngoài hộ và thử lại các đường dẫn trên. Bộ [test mới](../tests/test_backend.py) chạy các trường hợp giao dịch đồng thời, retry, rollback, phân quyền, OCR và ràng buộc.

## Dữ liệu và điều kiện vận hành

Schema 3 thêm catalog, schema 4 thêm các bảng nghiệp vụ. Hai migration tiếp sau W1 trong cùng cơ chế giao dịch. Để tái lập hoặc phục hồi DB có dữ liệu, tạo bản sao SQLite nhất quán trước khi nâng cấp rồi dùng DB bản sao. Bốn thực phẩm và hai công thức do dự án biên soạn cho demo. Có thể nạp thêm dữ liệu đã kiểm duyệt bằng `python -m backend.catalog.import_reviewed products.json` và `python -m backend.dietary_recipes.import_reviewed recipes.json`. Schema đầu vào ở hai tệp import. Bí danh và tên dùng chung hàm chuẩn hóa phía server.

Chính sách của bản local dùng ngưỡng nhắc hạn 3 ngày, múi giờ UTC+7, OCR Windows Runtime với ngôn ngữ đã cài trên máy. KIE dùng quy tắc dòng tên–lượng–đơn vị. Hạn ước tính phải được người dùng kiểm tra trước khi đưa lô vào gợi ý. Danh mục tham chiếu và từ vựng dị ứng chỉ có độ phủ demo. Hồ sơ có dị ứng ngoài từ vựng hoặc công thức thiếu thông tin bị loại khỏi nhóm đủ điều kiện. Dữ liệu đầu vào thực tế, EXP-01–03, tích hợp cache offline của Web, Web Push tùy chọn và staging được theo dõi trong kế hoạch cấp đồ án.
