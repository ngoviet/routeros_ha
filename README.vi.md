# RouterOS (MikroTik) cho Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![GitHub release](https://img.shields.io/github/v/release/ngoviet/routeros_ha)](https://github.com/ngoviet/routeros_ha/releases)
[![Validate](https://github.com/ngoviet/routeros_ha/actions/workflows/validate.yml/badge.svg)](https://github.com/ngoviet/routeros_ha/actions/workflows/validate.yml)
[![Test](https://github.com/ngoviet/routeros_ha/actions/workflows/test.yml/badge.svg)](https://github.com/ngoviet/routeros_ha/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/github/license/ngoviet/routeros_ha)](LICENSE)

[English](README.md) · **Tiếng Việt**

Điều khiển và giám sát router **MikroTik RouterOS 7** từ Home Assistant qua **REST API** có
sẵn trên router. Việc chính: **chặn / bỏ chặn mạng của từng thiết bị** bằng công tắc; kèm
các sensor sức khoẻ router và thông báo có bản cập nhật.

- **Mỗi rule chặn = một công tắc** — rule firewall filter nào có comment bắt đầu bằng tiền tố
  (mặc định `Block IP - `) sẽ thành một switch. Thêm rule mới là switch tự xuất hiện.
- **Chặn có hiệu lực ngay** — cắt luôn các kết nối đang mở của thiết bị, nên video/game đang
  chạy cũng dừng (không chỉ chặn kết nối mới).
- **Sức khoẻ router** — CPU, RAM, bộ nhớ lưu trữ, uptime, số thiết bị DHCP, nhiệt độ, tốc độ
  quạt, điện áp / công suất, sự cố quạt và nguồn.
- **Cổng ethernet** — link, tốc độ link và lưu lượng RX/TX của từng cổng ethernet / SFP, dùng
  được cả cho switch CRS (user chỉ-đọc là đủ). Làm nguồn cho card sơ đồ mạng như
  [lan-topo-card](https://github.com/ngoviet/lan-topo-card).
- **Thông báo cập nhật** — RouterOS và firmware RouterBOARD (chỉ đọc, không bao giờ tự cài).
- **Không thư viện ngoài** — dùng `aiohttp` có sẵn của Home Assistant.
- Cài đặt bằng giao diện (config flow), đăng nhập lại, tuỳ chọn, diagnostics, giao diện tiếng
  Anh và tiếng Việt.

> Đã kiểm tra trên **CCR2004-16G-2S+ / RouterOS 7.24.4**. Cần **RouterOS 7.1+** (REST API có
> từ 7.1) và **Home Assistant 2026.9** trở lên.

## Mục lục

- [1. Chuẩn bị trên router](#1-chuẩn-bị-trên-router)
- [2. Cài đặt](#2-cài-đặt)
- [3. Thêm integration](#3-thêm-integration)
- [Entity](#entity)
- [Cơ chế chặn](#cơ-chế-chặn)
- [Ví dụ](#ví-dụ)
- [Xử lý sự cố](#xử-lý-sự-cố)
- [Giới hạn](#giới-hạn)
- [Gỡ bỏ](#gỡ-bỏ)
- [Phát triển](#phát-triển)

## 1. Chuẩn bị trên router

Chạy các lệnh dưới trong terminal RouterOS (WinBox → *New Terminal*, hoặc SSH).

### 1.1 Bật REST API

REST API chạy trên service `www` (HTTP) hoặc `www-ssl` (HTTPS) — *IP → Services*.

```routeros
# HTTP cổng 80 (đơn giản nhất, dùng được trong LAN tin cậy)
/ip/service set www disabled=no

# …hoặc HTTPS cổng 443 (cần chứng chỉ; tự ký cũng được, xem bên dưới)
/certificate add name=rest-api common-name=router
/certificate sign rest-api
/ip/service set www-ssl disabled=no certificate=rest-api
```

Nên giới hạn service chỉ cho LAN: `/ip/service set www address=192.168.88.0/24`.

### 1.2 Tạo user riêng

Tạo group chỉ có policy `read`, `write`, `rest-api` và một user cho Home Assistant. Nên giới
hạn `address` về đúng IP của máy chạy Home Assistant.

```routeros
/user/group add name=ha-rest policy=read,write,rest-api,!local,!telnet,!ssh,!ftp,!reboot,!policy,!test,!winbox,!password,!web,!sniff,!sensitive,!romon,!api
/user add name=ha group=ha-rest address=192.168.88.10/32 password="mat-khau-dai-ngau-nhien"
```

Switch chỉ để giám sát (cổng, sức khoẻ) thì dùng group chỉ-đọc là đủ:

```routeros
/user/group add name=ha-read policy=read,rest-api,!local,!telnet,!ssh,!ftp,!reboot,!write,!policy,!test,!winbox,!password,!web,!sniff,!sensitive,!romon,!api
/user add name=ha-ro group=ha-read address=192.168.88.10/32 password="mat-khau-dai-ngau-nhien"
```

Cần `write` để bật/tắt rule chặn và cắt kết nối. Thiếu `write` thì mọi sensor vẫn chạy nhưng
công tắc báo lỗi.

### 1.3 Tạo rule chặn cho từng thiết bị

Với mỗi thiết bị cần điều khiển: thêm 1 rule `forward` **drop** khớp với thiết bị, comment bắt
đầu bằng tiền tố chặn, để ở trạng thái **disabled** (= chưa chặn). Nên đặt DHCP lease tĩnh để
IP thiết bị không đổi.

```routeros
# lease tĩnh cho thiết bị (không bắt buộc nhưng nên làm)
/ip/dhcp-server/lease add address=192.168.88.20 mac-address=AA:BB:CC:DD:EE:FF comment="Tivi phong khach"

# xem vị trí: ghi lại số thứ tự của rule forward đầu tiên CHO PHÉP traffic LAN
/ip/firewall/filter print

# rule chặn — công tắc sẽ tên "Chặn Tivi phong khach"
/ip/firewall/filter add chain=forward action=drop src-address=192.168.88.20 \
    comment="Block IP - Tivi phong khach" disabled=yes place-before=<số thứ tự>
```

Lưu ý:

- Rule phải nằm **trên** mọi rule cho phép traffic của thiết bị (vd rule cuối "accept LAN →
  WAN"). Có thể kéo thả trong WinBox cho đúng vị trí.
- Rule có thể khớp theo bất cứ gì RouterOS hỗ trợ (`src-mac-address`, `src-address-list`,
  `in-interface`…). Riêng việc cắt kết nối đang mở chỉ chạy khi `src-address` là một IP đơn.
- Tên công tắc lấy từ phần comment sau tiền tố (`Tivi phong khach`). Đổi comment sẽ sinh công
  tắc mới; công tắc cũ thành unavailable (xem [Giới hạn](#giới-hạn)).

## 2. Cài đặt

### HACS (khuyên dùng)

[![Mở Home Assistant và mở repo này trong HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ngoviet&repository=routeros_ha&category=integration)

Bấm nút trên, hoặc thêm bằng tay:

1. Mở **HACS** → menu **⋮** → **Custom repositories**.
2. Repository `https://github.com/ngoviet/routeros_ha`, loại **Integration** → **Add**.
3. Tìm **RouterOS (MikroTik)** trong HACS → **Download**.
4. **Khởi động lại Home Assistant.**

Từ đó HACS sẽ báo khi có bản phát hành mới.

### Thủ công

1. Tải `routeros_ha` từ [bản phát hành mới nhất](https://github.com/ngoviet/routeros_ha/releases/latest)
   (hoặc clone repo).
2. Chép thư mục `custom_components/routeros_ha` vào `<config>/custom_components/routeros_ha`
   trên máy chạy Home Assistant.
3. **Khởi động lại Home Assistant.**

## 3. Thêm integration

[![Mở Home Assistant và bắt đầu thêm RouterOS (MikroTik).](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=routeros_ha)

Hoặc vào **Cài đặt → Thiết bị & Dịch vụ → Thêm tích hợp → RouterOS (MikroTik)**.

| Trường | Ý nghĩa |
|---|---|
| Địa chỉ router | IP hoặc hostname, vd `192.168.88.1` (dán cả URL cũng được) |
| Cổng | `80` cho `www`, `443` cho `www-ssl`, hoặc cổng bạn đã đổi |
| Dùng HTTPS | Bật khi dùng `www-ssl` |
| Kiểm tra chứng chỉ SSL | **Tắt** nếu dùng chứng chỉ tự ký |
| Tên đăng nhập / Mật khẩu | User đã tạo ở bước 1.2 |

Mỗi router chỉ thêm được một lần (nhận diện bằng serial / software ID). Nhiều router thì thêm
thành nhiều mục riêng.

### Tuỳ chọn

**Cài đặt → Thiết bị & Dịch vụ → RouterOS (MikroTik) → Cấu hình**:

| Tuỳ chọn | Mặc định | Ý nghĩa |
|---|---|---|
| Chu kỳ cập nhật | 30 s | Bao lâu hỏi router một lần (10–600 s) |
| Tiền tố comment của rule chặn | `Block IP - ` | Rule filter có comment bắt đầu bằng chuỗi này thành công tắc |
| Cắt luôn các kết nối đang mở khi chặn | bật | Xoá connection-tracking của thiết bị khi chặn |
| Theo dõi cổng ethernet | bật | Link, tốc độ link, lưu lượng RX/TX từng cổng ethernet / SFP (3 entity / cổng) |

Đổi tuỳ chọn là integration tự nạp lại, không cần khởi động lại.

## Entity

Mọi entity thuộc một thiết bị mang tên identity của router (`/system/identity`).

| Entity | Loại | Nguồn | Ghi chú |
|---|---|---|---|
| **Chặn &lt;tên&gt;** | switch | `/ip/firewall/filter` | Một cái / rule có tiền tố. **Bật = rule bật = thiết bị mất mạng.** Thuộc tính: `src_address`, `comment`, `rule_id` |
| Tải CPU | sensor (%) | `/system/resource` | |
| RAM đã dùng | sensor (%) | `/system/resource` | |
| Bộ nhớ lưu trữ đã dùng | sensor (%) | `/system/resource` | Diagnostic |
| Thời điểm khởi động | sensor (timestamp) | `/system/resource` | Lúc router khởi động |
| Thiết bị DHCP | sensor | `/ip/dhcp-server/lease` | Số lease đang `bound`. Không tạo trên máy không chạy DHCP server (vd switch CRS) |
| **&lt;cổng&gt; link** | binary sensor (connectivity) | `/interface` `running` | Một cái / cổng ethernet, SFP. Thuộc tính: `port`, `default_name`, `comment`, `rate` (`1Gbps`), `speed_mbps`, `disabled`, `link_downs`, `mac_address` |
| **&lt;cổng&gt; RX** / **TX** | sensor (data rate) | `/interface` `rx-byte` / `tx-byte` | Tốc độ trung bình giữa 2 lần đọc, theo chiều của router: RX = nhận vào ở cổng, TX = gửi ra. Thuộc tính: `port`, `direction`. Lần đọc đầu chưa có số |
| CPU temperature, Fan1 speed, … | sensor | `/system/health` | Tự tạo theo những gì router báo (°C, RPM, V, W, A) |
| Fan, PSU1, PSU2, … | binary sensor (problem) | `/system/health` `*-state` | Bật khi giá trị khác `ok` (vd router 2 nguồn chỉ cắm 1 dây → PSU2 = sự cố). Diagnostic |
| RouterOS | update | `/system/package/update` | Kiểm tra mỗi 12 giờ. **Chỉ đọc** |
| Firmware RouterBOARD | update | `/system/routerboard` | Chỉ có trên phần cứng RouterBOARD. **Chỉ đọc** |

Entity update cố ý không có nút *Install*: cài RouterOS làm router khởi động lại, cả mạng mất
1–2 phút — không để một cú bấm nhầm trên dashboard làm việc đó. Nâng cấp bằng WinBox / WebFig
(trang thiết bị có link mở WebFig).

Sensor health tuỳ model: CHR / x86 không có `/system/health` nên các entity đó không được tạo.

Entity cổng gắn theo `default-name` nên đổi tên cổng trên router vẫn giữ entity; thuộc tính
`port` theo tên hiện tại. Tốc độ link đọc từ `/interface/ethernet/monitor`, chỉ khi có cổng
lên/xuống và mỗi 5 phút. Sensor RX/TX đổi mỗi lần đọc: nhiều cổng thì nên loại các cổng không
cần lịch sử khỏi recorder.

## Cơ chế chặn

Bật công tắc → rule thành `disabled=no`; tắt → `disabled=yes`. Trạng thái mới hiện ngay trên
Home Assistant và được xác nhận ở lần poll sau. Rule bật/tắt trực tiếp trên router (WinBox,
script, scheduler) cũng được cập nhật ở lần poll sau.

Firewall thường có rule `accept established,related` (hay cả `fasttrack`) đứng **trước** các
rule chặn → bật rule drop chỉ chặn kết nối **mới**; video đang xem vẫn tiếp tục. Khi bật tuỳ
chọn *Cắt luôn các kết nối đang mở khi chặn*, integration xoá thêm các dòng
`/ip/firewall/connection` có nguồn là IP thiết bị nên chặn có hiệu lực ngay. Bỏ chặn không đụng
gì tới connection.

## Ví dụ

### Chặn thiết bị của trẻ con giờ đi ngủ

```yaml
automation:
  - alias: "Giờ ngủ: chặn thiết bị của con"
    triggers:
      - trigger: time
        at: "22:00:00"
    actions:
      - action: switch.turn_on
        target:
          entity_id:
            - switch.router_chan_ipad_cua_con
            - switch.router_chan_tivi_phong_khach

  - alias: "Buổi sáng: bỏ chặn thiết bị của con"
    triggers:
      - trigger: time
        at: "06:30:00"
    actions:
      - action: switch.turn_off
        target:
          entity_id:
            - switch.router_chan_ipad_cua_con
            - switch.router_chan_tivi_phong_khach
```

### Thẻ dashboard

```yaml
type: entities
title: Truy cập Internet
entities:
  - entity: switch.router_chan_ipad_cua_con
  - entity: switch.router_chan_tivi_phong_khach
```

entity_id phụ thuộc identity router và comment rule — xem id thật trong
**Cài đặt → Thiết bị & Dịch vụ → RouterOS (MikroTik)**.

## Xử lý sự cố

| Hiện tượng | Kiểm tra |
|---|---|
| *Sai tên đăng nhập/mật khẩu…* | User/mật khẩu, group có `rest-api`, `address` của user cho phép IP Home Assistant |
| *Không kết nối được…* | `www` / `www-ssl` đã bật và cho phép IP HA (`/ip/service print`), cổng và HTTPS khớp; thử mở `http://<router>/rest/system/identity` bằng trình duyệt |
| HTTPS lỗi | Tắt *Kiểm tra chứng chỉ SSL* nếu chứng chỉ tự ký |
| Bấm công tắc báo lỗi | User thiếu policy `write`, hoặc rule đã bị xoá trên router |
| Không có công tắc nào | Comment phải bắt đầu **đúng** bằng tiền tố (phân biệt hoa thường và dấu cách cuối) |
| Chặn rồi vẫn có mạng | Rule nằm dưới một rule accept của thiết bị, hoặc thiết bị đi IPv6 (xem [Giới hạn](#giới-hạn)) |
| Update không bao giờ báo bản mới | Bản thân router không ra được `upgrade.mikrotik.com` |

Bật log debug:

```yaml
logger:
  logs:
    custom_components.routeros_ha: debug
```

Khi mở issue, đính kèm file diagnostics (trang thiết bị → **⋮ → Tải xuống chẩn đoán**); mật
khẩu, tên đăng nhập và serial đã được che.

## Giới hạn

- Rule chặn là **IPv4** (`/ip/firewall/filter`). Nếu LAN có Internet IPv6, thiết bị bị chặn
  vẫn có thể ra ngoài bằng IPv6 — tự thêm rule tương ứng ở `/ipv6/firewall/filter` hoặc tắt
  IPv6 cho thiết bị đó.
- Cắt kết nối đang mở cần `src-address` là một IP đơn (không phải dải hay danh sách).
- Rule bị xoá trên router để lại một công tắc unavailable; nạp lại integration rồi xoá entity.
- Khi chặn, integration đọc toàn bộ bảng connection; router có rất nhiều kết nối thì có thể
  mất vài giây.

## Gỡ bỏ

1. **Cài đặt → Thiết bị & Dịch vụ → RouterOS (MikroTik) → ⋮ → Xoá**.
2. Gỡ repo trong HACS (hoặc xoá `custom_components/routeros_ha`), khởi động lại.
3. Tuỳ ý xoá user và group `ha` trên router. Các rule chặn vẫn giữ nguyên.

## Phát triển

- Test: `pip install -r requirements_test.txt && pytest` (Linux / macOS / WSL; Home Assistant
  không chạy trực tiếp trên Windows). CI chạy Hassfest, HACS action và bộ test mỗi lần push.
- Phát hành: tăng `version` trong `custom_components/routeros_ha/manifest.json`, rồi push tag
  `v<version>` hoặc chạy workflow **Release** ở tab Actions. HACS lấy bản từ GitHub release.
- `tools/make_brand.py` sinh lại `brand/icon.png` / `icon@2x.png` (thiết kế gốc — cố ý không
  dùng logo MikroTik). Home Assistant 2026.3+ đọc thẳng thư mục `brand/`.
- `tools/deploy.py` chép integration lên máy Home Assistant qua SSH (`pip install paramiko`;
  cấu hình trong `.env`, xem `.env.example`).
- `tools/migrate_entity_ids.py [--apply]` đổi entity_id về id của integration
  [`mikrotik_router`](https://github.com/tomaae/homeassistant-mikrotik_router) để dashboard và
  lịch sử giữ nguyên (`pip install websockets`). Bảng ánh xạ id ở đầu script theo cấu hình của
  tác giả — sửa lại cho phù hợp và chạy thử không `--apply` trước.

## Giấy phép

[MIT](LICENSE)
