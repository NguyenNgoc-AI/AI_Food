# W1 · Mô hình dữ liệu

Schema 1 nằm trong [migration SQL](../migrations/001_foundation.sql). Khi khởi động, FastAPI gọi migration trong một giao dịch. Lệnh thủ công là `python -m backend.db`. SQLite lưu phiên bản ở `PRAGMA user_version`. Ứng dụng từ chối phiên bản chưa hỗ trợ và bật foreign keys trên mỗi kết nối.

| Bảng | Dữ liệu và ràng buộc |
|---|---|
| users | Tên đăng nhập chuẩn hóa chữ thường, duy nhất. Mật khẩu được băm bằng scrypt với salt ngẫu nhiên riêng |
| sessions | Hash SHA-256 của token ngẫu nhiên, khóa người dùng, hạn 7 ngày. Logout xóa phiên trên server |
| households | Tên hộ và đúng một owner_id bắt buộc. Khóa ngoại ghép (id, owner_id) trỏ tới thành viên cùng hộ và được kiểm tra lúc commit |
| memberships | Một hàng cho mỗi tài khoản đang thuộc hộ. Khóa chính user_id chặn việc thuộc hai hộ cùng lúc. Role Owner được suy ra từ households.owner_id. Rời hộ xóa quan hệ hoạt động |
| invitations | Thuộc một hộ, lưu hash mã mời, thời điểm hết hạn, trạng thái thu hồi và tài khoản đã dùng. Mã gốc trả về một lần khi tạo |
| audit_events | Hộ, tác nhân, hành động, đối tượng, thời điểm UTC dạng Unix, lý do và kết quả của biến động đã commit. Với hành động invite/join/revoke_invite, target_id là ID lời mời. Với hành động thành viên, đó là ID tài khoản |
| invite_attempts | Số lần thử mã sai của tài khoản trong cửa sổ 5 phút |
| login_attempts | [Migration 002](../migrations/002_login_attempts.sql) bổ sung giới hạn đăng nhập cho DB hiện có. Cửa sổ 5 phút có tối đa 10 lượt lỗi/đang xử lý theo tên chuẩn hóa và 50 theo địa chỉ client. Lượt thành công trả lại suất. HTTP 429 kèm Retry-After |

SQLite được chọn cho W1 local. `BEGIN IMMEDIATE` tuần tự hóa các lệnh ghi trước khi kiểm tra quyền hiện hành, tiêu thụ mã và chuyển chủ. Khóa ngoại hoãn đến commit cho phép tạo hộ và membership Owner trong cùng giao dịch. Nếu một bước lỗi, cả giao dịch được hoàn tác. SQLite chỉ có một writer tại một thời điểm. Đánh giá lại PostgreSQL cho môi trường nhiều tiến trình hoặc staging trước W2.
