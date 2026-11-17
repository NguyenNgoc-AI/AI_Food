# Kiểm thử W1

Chạy từ gốc repo, trên môi trường đã cài requirements. Các test tạo DB riêng trong thư mục tạm, tự chọn cổng loopback và dừng server khi kết thúc.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -p browser_g1.py -v
```

Ca trình duyệt dùng Google Chrome đã cài và Playwright. Tám test API/DB gồm đăng ký và phiên, bảo vệ yêu cầu sửa dữ liệu, schema và rollback, từ chối truy cập chéo hộ, thu hồi quyền, chuyển chủ và audit, giới hạn mã mời, cạnh tranh dùng mã và cạnh tranh chuyển chủ. Test Chrome dùng ba phiên riêng và hai hộ, ở viewport rộng 390 px. Kiểm tra trang kết nối độc lập theo [README](../README.md).

Các ca tương ứng TC-AUTH-01 là truy cập hộ khác, TC-AUTH-02 là truy cập sau khi bị xóa membership, TC-OWNER-01 là chuyển Owner, thay quyền và ghi audit. Các phép đo OCR, gợi ý món và mô phỏng lãng phí thuộc các mốc sau.
