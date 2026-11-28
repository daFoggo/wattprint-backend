# Plan Đ5. Thành viên và mức xem (lane L: quyền truy cập, migration)

Yêu cầu: spec.md R4.1–R4.4, R4.6. Bắt đầu sửa code sau khi review Đ4 đóng; base của gói review lấy sau lượt sửa đó.

## Quyết định

- Cột `tb_home_member.detail` (`full|daily`, NOT NULL, mặc định `full` cho dòng sẵn có); nhận lời mời thì ghi `daily`.
- Mã mời: 10 ký tự ngẫu nhiên (bỏ ký tự dễ nhầm), chỉ lưu SHA-256, hạn 7 ngày, dùng một lần (một câu UPDATE
  `... WHERE used_at IS NULL`). Bảng `tb_home_invite` có sẵn, vai luôn là `member`. Giới hạn số lần nhập sai mỗi người.
- Route trả **chỉ** số mịn (`/series`, `/stream`, `/activity`, `/expected`): 403 `detail_restricted`.
- Route trộn (`/overview`, `/devices`, `/devices/{id}`, `/alerts`): giữ số theo ngày, bỏ trường mịn (`live`, `on`,
  `watts`, `power`, `cycles`; giờ trong cảnh báo). Khác chữ R4.3 (403 mọi route) vì 403 sẽ mất luôn số ngày.
- Wappi và cảnh báo tự đặt: mức = thấp hơn giữa nhà và người hỏi (người tạo cảnh báo).
- Gỡ hoặc tự rời: xóa trò chuyện, cảnh báo tự đặt, kế hoạch của người đó ở nhà này, để không còn thư hay tin
  nào mang số của nhà gửi tới họ. `/stream` đang mở kiểm tra lại quyền trong vòng lặp.
- Chủ nhà không tự rời (đã có "xóa tài khoản").

## Việc, theo thứ tự (mỗi việc test đỏ trước)

1. Migration cột `detail` (chạy `alembic upgrade head` TRƯỚC khi sửa model), kiểm quyền của vai app trên
   `tb_home_invite`, `tests/db`. Rules: migrations.md.
2. `home`: `OwnerMembership`, `DetailedMembership`, service mời / nhận / danh sách / đổi mức / gỡ / rời;
   `tests/test_members.py`. Route: `POST /homes/current/invites`, `POST /homes/invites/accept`,
   `GET /homes/current/members`, `PATCH|DELETE /homes/current/members/{user_id}`, `DELETE /homes/current/membership`.
3. Chặn và cắt trường ở `energy`, `expect`, `insight`; Wappi (`copilot/services/chat.py`) và watches theo mức người dùng.
4. `tests/test_permissions.py`: thêm chủ thể "thành viên theo ngày" và các route mới; in lại bảng minh chứng.
5. Web: ô nhập mã ở màn "Chưa có nhà", ẩn khối theo giờ kèm lý do (làm cùng Đ6).

## Rủi ro

- Sửa model là có hiệu lực trên prod ngay (một container); migration chỉ thêm cột, có mặc định.
- Sót một route mịn: bảng thử quyền liệt kê mọi route, thêm kiểm tra route nào chưa có dòng thì test đỏ.
