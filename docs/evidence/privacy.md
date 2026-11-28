# Minh chứng: bảo vệ dữ liệu nếp sinh hoạt

Hiện trạng ngày 28/11/2026, trên môi trường dev. Trang này đối chiếu với mã nguồn; các test nêu dưới đây là test có
trong repo, **không được chạy lại khi viết trang này**. Yêu cầu gốc:
[intent.md](../work/2026-11-28-privacy-load-data/intent.md).

**Đọc trước:** việc chặn theo đồng ý đang **tắt** trên máy chủ (`consent_enforced = False`), và việc dọn hằng đêm cho
bảng thường **chưa bật** (`RETENTION_TIERS=false`). Xem mục "Chưa làm".

## Ba minh chứng ban giám khảo yêu cầu

| Minh chứng | Ở đâu |
|---|---|
| Sơ đồ luồng dữ liệu | [Sơ đồ tổng quan](../diagrams/privacy-data-flow.svg); [bộ chi tiết](../diagrams/privacy/index.html): tác nhân, chức năng, hai ma trận, DFD |
| Màn hình quyền riêng tư | **Chưa có ảnh** (xem "Ảnh chụp") |
| Thử phân quyền | [Trước khi sửa](privacy/permission-matrix-before.md); [sau khi sửa](privacy/permission-matrix-after.md) (chạy thật 28/11, 57 thao tác khớp, 6 ca database đạt); test `tests/test_permissions.py` |

Bổ sung: [bảng mối đe dọa](privacy/threats.md); [quy trình sự cố 72 giờ và đầu vào đánh giá tác động](privacy/incident-72h.md) (bản nháp).

## Từng ý của đề

### "Dữ liệu phụ tải theo giờ có thể tiết lộ lịch sinh hoạt gia đình"

Chúng tôi rà toàn bộ nơi lưu, người đọc và nơi gửi đi trước khi sửa: [audit.md](../work/2026-11-28-privacy-load-data/audit.md).

### "Giảm độ chi tiết phải lưu/chia sẻ"

**Chia sẻ: đã làm. Lưu: đã áp thời hạn theo bậc cho số đo; bảng thường chưa dọn theo bậc.**

| Đã làm | Minh chứng |
|---|---|
| AI mặc định chỉ xem theo ngày; chủ nhà tự bật theo giờ. Nhà demo (dữ liệu công khai) đặt theo giờ | `tests/db/test_roles.py::test_a_daily_token_sees_days_not_hours`; `tests/test_copilot_tools.py::test_text2sql_tokens_carry_the_level` |
| AI không còn đọc được view theo phút, lượt bật/tắt, tên nhà, mã bưu chính, số người | `tests/db/test_roles.py::test_copilot_reads_no_minute_runs_or_identity` |
| Ở mức ngày: không đọc số theo phút ban đêm, cảnh báo bỏ giờ | `tests/test_copilot_tools.py`: `test_at_daily_standby_reads_no_night_minutes`, `test_at_daily_alerts_give_the_day_only`, `test_at_daily_an_odd_hour_alert_keeps_no_start_hour` |
| Email, số điện thoại, số giấy tờ trong câu hỏi bị che trước khi lưu và gửi | `tests/test_privacy.py`; `tests/test_copilot_api.py::test_the_guard_reads_the_redacted_question` |
| Gọi OpenRouter kèm yêu cầu không lưu, không dùng để huấn luyện | `tests/test_copilot_llm.py::test_openrouter_is_asked_to_keep_and_train_on_nothing` |
| Thời hạn theo bậc cho số đo, áp ngày 28/11/2026 | `scripts/apply_retention.py`; so trước và sau trên database dùng chung (không phải trên bản sao): hóa đơn và tổng theo giờ, theo ngày không đổi; database 3161 MB còn 1165 MB |
| Đo chất lượng Wappi ở hai mức (một nhà, một lượt) | [d2-ai-detail](../eval/d2-ai-detail-2026-11-28.md) |

Ở mức theo giờ, công cụ xem điện chờ vẫn đọc số theo phút trong hệ thống và gửi cho AI kết quả theo từng đêm.

Thời gian lưu hôm nay: số thô 30 ngày; tổng theo phút 90; theo giờ 400; theo ngày 800; lượt bật/tắt 90; dự đoán theo
giờ 400 (nhà có mô hình); cảnh báo, dự báo không có hạn; hóa đơn 25 kỳ; trò chuyện đến khi xóa; âm thanh đọc 30 ngày; nhật ký gửi ngoài 90 ngày.

### "Giới hạn quyền truy cập"

| Đã làm | Minh chứng |
|---|---|
| Chủ nhà mời người thân bằng mã dùng một lần; mức mặc định là chỉ theo ngày; đổi mức, gỡ; thành viên tự rời | `tests/test_members.py` |
| Người "chỉ theo ngày" bị từ chối số mịn hơn một ngày, kể cả khi hỏi Wappi, đặt nhắc, nhận mail cảnh báo | `tests/test_members.py::test_a_daily_member_gets_no_figure_finer_than_a_day`, `test_a_daily_member_sets_no_watch_on_the_moment`, `test_wappi_answers_a_daily_member_by_day`; `tests/test_insight_api.py::test_a_daily_members_alert_mail_names_nothing` |
| Mỗi thao tác API có mã trả về mong đợi cho bảy chủ thể; thêm route mà thiếu dòng thì test đỏ | `tests/test_permissions.py` |
| Vai database của AI chỉ thấy nhà trong token; không đọc bảng gốc, không ghi | `tests/db/test_roles.py` |
| Dịch vụ text2sql đòi khóa ở mọi router (trừ own-knowledge, có khóa riêng) | `wattprint-text2sql-mcp/tests/test_service_key.py` |
| Admin chỉ xem danh sách tài khoản, không có API đọc dữ liệu một nhà | cột admin của bảng thử quyền |

Giới hạn: người vận hành có quyền máy chủ và database vẫn đọc được mọi dữ liệu.

### "Cho phép xóa lịch sử"

| Đã làm | Minh chứng |
|---|---|
| Chủ nhà xóa lịch sử điện trước một ngày hoặc tất cả, ở mọi tầng lưu; nhà khác không đổi; nhà demo từ chối | `tests/test_erase_history.py` (API `DELETE /homes/current/history`) |
| Công tơ gửi lại lô cũ không đưa dữ liệu đã xóa quay lại | `test_a_meter_cannot_send_the_erased_readings_again` |
| Hóa đơn tính lại theo số còn giữ; dự đoán hằng đêm không dựng lại ngày đã xóa | `test_bills_follow_the_daily_totals`, `test_the_nightly_refresh_does_not_predict_erased_days_again` |
| Mỗi người xóa mọi trò chuyện của mình kèm âm thanh | `test_all_my_chats_go_at_once` |
| Xóa tài khoản | `tests/test_delete_account.py` |

Xóa lịch sử điện **không** xóa trò chuyện (câu trả lời cũ có thể còn chứa số liệu); đó là nút riêng. Dữ liệu đã gửi
cho dịch vụ ngoài không xóa được từ WattPrint.

### "Nêu rõ khi gọi dịch vụ ngoài"

| Đã làm (phần máy chủ) | Minh chứng |
|---|---|
| Một cửa ra chung; địa chỉ bên ngoài chỉ nằm ở cấu hình và cửa này | `app/common/outbound.py`; `tests/test_outbound.py` |
| Nhật ký mỗi lần gửi (bên nhận, mục đích, loại dữ liệu, mức; không ghi nội dung), xem 30 ngày, giữ 90 ngày | `tests/test_consent.py::test_the_outbound_log_lists_my_last_30_days` |
| Mỗi câu trả lời của Wappi kèm danh sách đã gửi | `tests/test_copilot_api.py::test_each_answer_lists_what_it_sent_out` |
| Đồng ý theo mục đích (Wappi, giọng nói, email), mỗi lần đổi thêm một dòng; **chặn đang tắt** | `tests/test_consent.py` (test tự bật việc chặn nếu cần) |
| Bấm 👎 chỉ gửi đánh giá; nội dung đi Telegram khi người dùng tích chọn | `tests/test_consent.py::test_a_shared_thumbs_down_shows_in_my_log` |
| API tóm tắt "đang giữ gì, từ ngày nào" | `GET /homes/current/privacy`; `tests/test_privacy_overview.py` |

| Bên nhận | Nhận gì |
|---|---|
| OpenRouter (ngoài Việt Nam) | Câu hỏi đã che, hội thoại, số liệu theo mức ngày hoặc giờ |
| AstralX (vị trí máy chủ chưa rõ) | Như trên khi làm dự phòng; âm thanh gốc (không che được); câu trả lời cần đọc |
| OpenWeather | Tọa độ tỉnh, không kèm người |
| Telegram | Đánh giá 👎; nội dung nếu người dùng tích |
| SMTP | Địa chỉ email, cảnh báo, tóm tắt tuần |
| Google và mail tài khoản của Keycloak | Đăng nhập, xác minh; **không** qua cửa ra chung, không ghi nhật ký |

## Ảnh chụp (chỗ trống, ảnh nằm ở repo web)

- [ ] `ANH-1` Trang Quyền riêng tư, chủ nhà
- [ ] `ANH-2` Trang Quyền riêng tư, thành viên chỉ theo ngày
- [ ] `ANH-3` Hộp đồng ý Wappi
- [ ] `ANH-4` Hộp đồng ý giọng nói
- [ ] `ANH-5` Dòng báo dưới ô chat và mục "Đã gửi ra ngoài"
- [ ] `ANH-6` Hộp xác nhận xóa lịch sử

## Chưa làm

1. **Dọn hằng đêm cho bảng thường** theo bậc chưa bật (`RETENTION_TIERS=false`): cảnh báo, kết quả công cụ, nhật ký
   NILM, lô công tơ chưa bị dọn theo thời hạn mới. Biểu đồ chưa ghi chú khi chi tiết theo phút đã hết hạn.
2. **Chặn theo đồng ý đang tắt** (`app/config.py`, `consent_enforced`): chờ giao diện hỏi đồng ý được triển khai.
3. Giao diện: trang Quyền riêng tư, ô nhập mã mời, ẩn khối cho người "chỉ theo ngày", ảnh chụp. Trong
   [checklist](../work/2026-11-28-privacy-load-data/checklist.md) các mục web chưa được đánh dấu xong.
4. Trang chính sách trên web công khai chưa sửa theo mã mới.
5. AstralX: chưa biết nơi đặt máy chủ, thời gian giữ; chưa gửi kèm yêu cầu không lưu dữ liệu.
6. Che dữ liệu cá nhân chỉ theo mẫu, chưa nhận ra tên người và địa chỉ.
7. Tệp mô hình tách thiết bị riêng của nhà chưa xóa theo tài khoản (hiện chỉ huấn luyện từ dữ liệu công khai).
8. Chưa thử tấn công (dụ Wappi đọc nhà khác, vượt mức xem), chưa kiểm cấu hình bảo mật máy prod.
9. Chưa triển khai lên prod; căn cứ pháp lý chưa đối chiếu bản Công báo.
