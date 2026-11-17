# SmartFood AI

## W1 · Tài khoản và hộ gia đình

Khởi chạy theo các lệnh Windows bên dưới, rồi mở [trang hộ gia đình](http://127.0.0.1:8000/household). Bạn có thể đăng ký, đăng nhập, tạo hộ, chia sẻ mã mời, quản lý thành viên, chuyển chủ hộ và rời hộ. [Demo hai hộ](docs/demo.md) · [Test G1](docs/evaluation.md) · [Mô hình dữ liệu](docs/data.md).

Ứng dụng tự tạo SQLite tại `var/smartfood.sqlite3`. Có thể đặt biến môi trường `SMARTFOOD_DB` trỏ tới đường dẫn DB cục bộ riêng trước khi khởi động. Khởi động lại sẽ giữ dữ liệu. Thử nghiệm tự động dùng DB tạm. Dùng môi trường loopback cho demo. Trang cần được mở qua HTTP.

Mã mời có hiệu lực 24 giờ, dùng một lần. Phiên đăng nhập có hiệu lực 7 ngày. Cookie là HttpOnly, SameSite=Strict và có Secure khi dùng HTTPS. API sửa dữ liệu yêu cầu header `X-SmartFood: 1`, được trang Web gửi cùng origin. Danh mục endpoint và schema có tại [OpenAPI](http://127.0.0.1:8000/docs). Chế độ thử yêu cầu trên Swagger cần gửi thêm header này.

## W1-01 · Kiểm tra kết nối Web–API

FastAPI phục vụ trang Web và API từ cùng một tiến trình. Trang tiếng Việt gửi yêu cầu đến `/api/health` khi mở và khi bấm **Thử lại**.

### Chạy trên Windows

Mở PowerShell tại thư mục chứa tệp này. Dùng Python 3.14 trên Windows x64 (phiên bản kiểm thử 3.14.5).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Nếu lệnh `python` mở Microsoft Store, dùng `py -3.14 -m venv .venv` hoặc gọi trực tiếp đường dẫn đến Python 3.14 đã cài ở bước đầu.

### Kiểm tra

1. Mở [trang kiểm tra](http://127.0.0.1:8000/). Trang hiển thị **Đã kết nối API** sau khi nhận phản hồi hợp lệ.
2. Từ cửa sổ PowerShell khác, chạy `Invoke-RestMethod http://127.0.0.1:8000/api/health`. Trường `status` phải bằng `ok`; phản hồi HTTP có mã 200 và kiểu JSON.
3. Giữ trang đang mở. Nhấn Ctrl+C trong cửa sổ chạy Uvicorn. Trên trang, bấm **Thử lại** để thấy **Chưa kết nối được API**.
4. Chạy lại lệnh Uvicorn, rồi bấm **Thử lại** trên cùng trang. Trạng thái phải trở về **Đã kết nối API**.

Mỗi lần kiểm tra bỏ qua cache và chờ tối đa 5 giây. Endpoint kiểm tra khả năng phản hồi của tiến trình ứng dụng. Dữ liệu tài khoản, hộ gia đình và kho thuộc các phần việc tiếp theo.
