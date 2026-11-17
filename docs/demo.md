# Demo G1 · Hai hộ và ba tài khoản

1. Chạy ứng dụng theo [README](../README.md). Mở /household bằng ba profile trình duyệt riêng để cookie của ba người độc lập. Có thể dùng test Chrome để tự động tạo ba profile tạm.
2. Đăng ký và đăng nhập ba tài khoản A, B và C. A tạo Nhà A. C tạo Nhà C. B chưa có hộ.
3. A tạo mã rồi thu hồi. B nhập mã đó, trang hiển thị lỗi. A phát hành mã khác, B dùng mã mới và thấy Nhà A. Mã dùng thành công chỉ được dùng một lần.
4. A làm mới danh sách và chuyển quyền cho B. Sau khi làm mới, B có quyền tạo mã và quản lý thành viên. A mất quyền chủ hộ.
5. B xóa A khỏi hộ. Request tiếp theo của A tới Nhà A bị từ chối. A làm mới để xem màn hình tạo hoặc tham gia hộ. C vẫn thấy Nhà C.
6. B tạo mã khác cho A tham gia lại. A bấm Rời hộ. B đăng xuất rồi mở lại trang, ứng dụng yêu cầu đăng nhập. Các ca gọi API chéo hộ, phiên cũ và chuyển quyền cạnh tranh có trong [bộ test](../tests/test_foundation.py).
