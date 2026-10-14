# RouterOS (MikroTik) cho Home Assistant

Điều khiển và giám sát router **MikroTik RouterOS 7** qua **REST API** — gọn, không thư viện
ngoài (dùng `aiohttp` có sẵn của HA). Việc chính: **chặn / bỏ chặn mạng của từng thiết bị**
bằng công tắc, cộng các sensor sức khoẻ router.

> Đã kiểm tra trên **CCR2004-16G-2S+ / RouterOS 7.24.4**. Cần RouterOS **7.1+** (có REST API).

## Chuẩn bị trên router

1. Bật service `www` (HTTP, cổng 80) hoặc `www-ssl` (HTTPS) — *IP → Services*.
2. Tạo user riêng cho HA, group chỉ có `read`, `write`, `rest-api` (không cần quyền khác),
   nên giới hạn `address` về IP của HA:

   ```
   /user/group add name=ha-rest policy=read,write,rest-api,!local,!telnet,!ssh,!ftp,!reboot,!policy,!test,!winbox,!password,!web,!sniff,!sensitive,!romon,!api
   /user add name=ha group=ha-rest address=<IP của HA>/32 password=<mật khẩu>
   ```
3. Với mỗi thiết bị cần chặn: 1 rule `forward` **drop** theo `src-address` của thiết bị
   (nên đặt DHCP lease tĩnh), comment bắt đầu bằng tiền tố chặn (mặc định `Block IP - `),
   để rule ở trạng thái **disabled**:

   ```
   /ip/firewall/filter add chain=forward action=drop src-address=192.168.10.20 comment="Block IP - Tivi 1" disabled=yes place-before=<rule accept-all cuối>
   ```

## Cài đặt

1. HACS → *Custom repositories* → thêm repo này (loại *Integration*) → cài **RouterOS (MikroTik)**,
   hoặc chép `custom_components/routeros_ha` vào `/config/custom_components/`.
2. Khởi động lại Home Assistant.
3. *Cài đặt → Thiết bị & Dịch vụ → Thêm tích hợp → RouterOS (MikroTik)* → địa chỉ router, cổng,
   HTTPS, user + mật khẩu ở trên.

Tuỳ chọn: chu kỳ cập nhật (mặc định 30 s, 10–600 s) · tiền tố comment rule chặn ·
cắt kết nối đang mở khi chặn (mặc định bật).

## Entity

| Entity | Nguồn REST | Ghi chú |
|---|---|---|
| **Chặn &lt;tên&gt;** (switch) | `/ip/firewall/filter` | 1 switch / rule có comment bắt đầu bằng tiền tố. **Bật = rule bật = thiết bị mất mạng.** Rule mới trên router tự thành switch ở lần poll sau |
| Tải CPU · RAM đã dùng · Bộ nhớ lưu trữ đã dùng (%) | `/system/resource` | |
| Thời điểm khởi động (timestamp) | `/system/resource` `uptime` | |
| Thiết bị DHCP | `/ip/dhcp-server/lease` `status=bound` | |
| Nhiệt độ, tốc độ quạt, điện áp… | `/system/health` | Tự tạo theo những gì router báo (`type` C / RPM / V / W / A) |
| Fan · PSU1 · PSU2 (problem) | `/system/health` `*-state` | Bật khi giá trị khác `ok` (vd router chỉ cắm 1 nguồn → PSU2 = sự cố) |
| RouterOS · Firmware RouterBOARD (update) | `/system/package/update`, `/system/routerboard` | **Chỉ đọc**, không có nút Install (cài RouterOS = router khởi động lại). Kiểm tra bản mới mỗi 12 giờ |

### Vì sao cần "cắt kết nối đang mở"

Firewall thường có rule `accept established,related` đứng **trước** các rule chặn → bật rule
drop chỉ chặn kết nối **mới**; video/game đang chạy vẫn tiếp tục. Khi bật chặn, integration xoá
các dòng `/ip/firewall/connection` có nguồn là IP thiết bị nên chặn có hiệu lực ngay. Bỏ chặn
không đụng gì tới connection.

## Công cụ (cho người phát triển)

- `python tools/deploy.py` — chép integration lên HA qua SSH (cần `.env`, xem `.env.example`).
- `python tools/make_brand.py` — sinh `brand/` (icon/logo đúng quy cách home-assistant/brands).
- `python tools/migrate_entity_ids.py [--apply]` — chuyển từ HACS `mikrotik_router` (tomaae):
  đổi entity_id mới về id cũ để dashboard và lịch sử giữ nguyên.
- Test: `pip install -r requirements_test.txt && pytest`.

## Giấy phép

MIT
