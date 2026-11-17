# Tiến độ sản phẩm

| Bước | Hiện vật |
|---|---|
| W1-01 | Khởi động local, trang kiểm tra và GET /api/health |
| W1-02 | Schema 2, migration từ DB trống hoặc phiên bản 1, một hộ chính và đúng một Owner |
| W1-03 | Đăng ký, đăng nhập, phiên cookie có thể thu hồi, đăng xuất |
| W1-04 | Tạo hộ, danh sách thành viên, phân tách dữ liệu theo membership hiện hành |
| W1-05 | Tạo, dùng, thu hồi và hết hạn mã mời 24 giờ, một lượt |
| W1-06 | Rời hộ, xóa thành viên, chuyển Owner và audit trong giao dịch |
| W1-07 | Giao diện tiếng Việt ở /household |
| W1-08 | Test API/DB, test E2E Chrome với hai hộ và hướng dẫn demo |

Chạy lại bằng [hướng dẫn kiểm thử](evaluation.md). Tiếp theo là W2, danh mục thực phẩm, đơn vị, lô tồn và sổ biến động. Xác định DB cho môi trường triển khai và quy tắc đơn vị trước khi tạo schema kho.
