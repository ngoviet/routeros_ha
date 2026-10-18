# RouterOS (MikroTik) for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![GitHub release](https://img.shields.io/github/v/release/ngoviet/routeros_ha)](https://github.com/ngoviet/routeros_ha/releases)
[![Validate](https://github.com/ngoviet/routeros_ha/actions/workflows/validate.yml/badge.svg)](https://github.com/ngoviet/routeros_ha/actions/workflows/validate.yml)
[![Test](https://github.com/ngoviet/routeros_ha/actions/workflows/test.yml/badge.svg)](https://github.com/ngoviet/routeros_ha/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/github/license/ngoviet/routeros_ha)](LICENSE)

**English** · [Tiếng Việt](README.vi.md)

Control and monitor a **MikroTik RouterOS 7** router from Home Assistant through the
built-in **REST API**. The main job is **blocking / unblocking internet access per device**
with a switch; on top of that you get router health sensors and update notifications.

- **One switch per block rule** — every firewall filter rule whose comment starts with a
  prefix (default `Block IP - `) becomes a switch. New rules show up automatically.
- **Blocking takes effect immediately** — open connections of the device are dropped, so a
  running video or game stops too (not only new connections).
- **Router health** — CPU, RAM, storage, uptime, DHCP clients, temperatures, fan speed,
  voltage / power, fan and PSU problems.
- **Ethernet ports** — link, link speed and RX/TX rate of every ethernet / SFP port, also on
  CRS switches (read-only user is enough). Feeds network-map cards such as
  [lan-topo-card](https://github.com/ngoviet/lan-topo-card).
- **Update notifications** — RouterOS and RouterBOARD firmware (read-only, never installs).
- **No extra dependencies** — talks to the router with Home Assistant's own `aiohttp`.
- UI setup (config flow), re-authentication, options, diagnostics, English and Vietnamese UI.

> Tested on **CCR2004-16G-2S+ / RouterOS 7.24.4**. Requires **RouterOS 7.1+** (the REST API
> was added in 7.1) and **Home Assistant 2026.9** or newer.

## Contents

- [1. Prepare the router](#1-prepare-the-router)
- [2. Install](#2-install)
- [3. Add the integration](#3-add-the-integration)
- [Entities](#entities)
- [How blocking works](#how-blocking-works)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [Removal](#removal)
- [Development](#development)

## 1. Prepare the router

Run these commands in a RouterOS terminal (WinBox → *New Terminal*, or SSH).

### 1.1 Enable the REST API

The REST API is served by the `www` (HTTP) or `www-ssl` (HTTPS) service — *IP → Services*.

```routeros
# HTTP on port 80 (simplest, fine on a trusted LAN)
/ip/service set www disabled=no

# …or HTTPS on port 443 (needs a certificate; self-signed works, see below)
/certificate add name=rest-api common-name=router
/certificate sign rest-api
/ip/service set www-ssl disabled=no certificate=rest-api
```

Restricting the service to your LAN is a good idea:
`/ip/service set www address=192.168.88.0/24`.

### 1.2 Create a dedicated user

Create a group with only the `read`, `write` and `rest-api` policies, and a user for Home
Assistant. Limiting `address` to the IP of your Home Assistant host is recommended.

```routeros
/user/group add name=ha-rest policy=read,write,rest-api,!local,!telnet,!ssh,!ftp,!reboot,!policy,!test,!winbox,!password,!web,!sniff,!sensitive,!romon,!api
/user add name=ha group=ha-rest address=192.168.88.10/32 password="a-long-random-password"
```

`write` is needed to toggle block rules and to drop connections. Without it every sensor
still works, but the switches fail. For a switch you only monitor (ports, health), a
read-only group is enough:

```routeros
/user/group add name=ha-read policy=read,rest-api,!local,!telnet,!ssh,!ftp,!reboot,!write,!policy,!test,!winbox,!password,!web,!sniff,!sensitive,!romon,!api
/user add name=ha-ro group=ha-read address=192.168.88.10/32 password="a-long-random-password"
```

### 1.3 Create one block rule per device

For each device you want to control, add a `forward` **drop** rule that matches the
device, with a comment that starts with the block prefix, and leave it **disabled** (=
device not blocked). Give the device a static DHCP lease so its IP never changes.

```routeros
# static lease for the device (optional but recommended)
/ip/dhcp-server/lease add address=192.168.88.20 mac-address=AA:BB:CC:DD:EE:FF comment="Living room TV"

# find the position: note the number of the first forward rule that ACCEPTS LAN traffic
/ip/firewall/filter print

# the block rule — the switch will be called "Block Living room TV"
/ip/firewall/filter add chain=forward action=drop src-address=192.168.88.20 \
    comment="Block IP - Living room TV" disabled=yes place-before=<number>
```

Notes:

- The rule must sit **above** any rule that accepts the device's traffic (for example a
  final "accept LAN → WAN" rule). You can also drag it into place in WinBox.
  Keeping it below `accept established,related` / `fasttrack` is fine: the integration
  drops the device's open connections when blocking (see
  [How blocking works](#how-blocking-works)).
- The rule may match anything RouterOS supports (`src-mac-address`, `src-address-list`,
  `in-interface`…). Dropping open connections only works when the rule has a single
  `src-address` IP.
- The switch name comes from the comment after the prefix (`Living room TV`). Renaming the
  comment creates a new switch; the old one becomes unavailable (see [Limitations](#limitations)).

## 2. Install

### HACS (recommended)

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ngoviet&repository=routeros_ha&category=integration)

Click the button above, or add it by hand:

1. Open **HACS** → menu **⋮** → **Custom repositories**.
2. Repository `https://github.com/ngoviet/routeros_ha`, type **Integration** → **Add**.
3. Search for **RouterOS (MikroTik)** in HACS → **Download**.
4. **Restart Home Assistant.**

HACS will notify you about new releases from then on.

### Manual

1. Download `routeros_ha` from the [latest release](https://github.com/ngoviet/routeros_ha/releases/latest)
   (or clone the repository).
2. Copy the folder `custom_components/routeros_ha` to `<config>/custom_components/routeros_ha`
   on your Home Assistant host.
3. **Restart Home Assistant.**

## 3. Add the integration

[![Open your Home Assistant instance and start setting up RouterOS (MikroTik).](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=routeros_ha)

Or go to **Settings → Devices & services → Add integration → RouterOS (MikroTik)**.

| Field | Description |
|---|---|
| Host | IP or hostname of the router, e.g. `192.168.88.1` (a pasted URL is accepted) |
| Port | `80` for `www`, `443` for `www-ssl`, or your custom port |
| Use HTTPS | Enable when using `www-ssl` |
| Verify SSL certificate | Leave **off** for a self-signed certificate |
| Username / Password | The user created in step 1.2 |

Each router is added once (identified by its serial number / software ID). Several routers
can be added as separate entries.

### Options

**Settings → Devices & services → RouterOS (MikroTik) → Configure**:

| Option | Default | Description |
|---|---|---|
| Update interval | 30 s | How often the router is polled (10–600 s) |
| Block rule comment prefix | `Block IP - ` | Filter rules whose comment starts with this become switches |
| Drop open connections when blocking | on | Remove the device's connection-tracking entries when blocking |
| Monitor ethernet ports | on | Link, link speed and RX/TX rate per ethernet / SFP port (3 entities per port) |

Changing options reloads the integration; no restart needed.

## Entities

All entities belong to one device named after the router identity (`/system/identity`).

| Entity | Type | Source | Notes |
|---|---|---|---|
| **Block &lt;name&gt;** | switch | `/ip/firewall/filter` | One per rule with the prefix. **On = rule enabled = device blocked.** Attributes: `src_address`, `comment`, `rule_id` |
| CPU load | sensor (%) | `/system/resource` | |
| Memory usage | sensor (%) | `/system/resource` | |
| Storage usage | sensor (%) | `/system/resource` | Diagnostic |
| Uptime | sensor (timestamp) | `/system/resource` | Time the router booted |
| DHCP clients | sensor | `/ip/dhcp-server/lease` | Number of leases with status `bound`. Not created on a device without a DHCP server (e.g. a CRS switch) |
| **&lt;port&gt; link** | binary sensor (connectivity) | `/interface` `running` | One per ethernet / SFP port. Attributes: `port`, `default_name`, `comment`, `rate` (`1Gbps`), `speed_mbps`, `disabled`, `link_downs`, `mac_address`, and the device plugged in: `device`, `device_ip`, `device_mac`, `device_source` |
| **&lt;port&gt; RX** / **TX** | sensor (data rate) | `/interface` `rx-byte` / `tx-byte` | Average rate between two polls, from the router's point of view: RX = received on the port, TX = sent out of it. Attributes: `port`, `direction`. Empty after the first poll |
| CPU temperature, Fan1 speed, … | sensor | `/system/health` | Created from whatever the router reports (°C, RPM, V, W, A) |
| Fan, PSU1, PSU2, … | binary sensor (problem) | `/system/health` `*-state` | On when the value is not `ok` (e.g. a dual-PSU router with one power cord → PSU2 = problem). Diagnostic |
| RouterOS | update | `/system/package/update` | Checked every 12 hours. **Read-only** |
| RouterBOARD firmware | update | `/system/routerboard` | Only on RouterBOARD hardware. **Read-only** |

The update entities have no *Install* button on purpose: installing RouterOS reboots the
router and takes the whole network down for a minute or two — not something a misclick on
a dashboard should do. Upgrade from WinBox / WebFig (the device page has a link to WebFig).

Health sensors depend on the model: CHR / x86 has no `/system/health`, so those entities are
simply not created.

Port entities are keyed by the port's `default-name`, so renaming a port on the router keeps
the entity; the `port` attribute follows the current name. The link speed comes from
`/interface/ethernet/monitor`, read only when a port goes up/down and every 5 minutes. RX/TX
sensors change on every poll: with many ports, consider excluding the ones you do not need
from the recorder.

**Device on a port** (`device` attribute): the LLDP/MNDP/CDP neighbor on that port
(`/ip/neighbor`, e.g. an access point or another switch); otherwise the MAC addresses learned
on the port (`/interface/bridge/host`) are looked up in the DHCP leases: if exactly one of
them has a lease **comment**, that name wins (a PC with VMs behind it still shows the PC), and
a port with a single MAC falls back to the lease host name. A switch without a DHCP server
uses the leases of the other routers added to the integration. When a device goes quiet and
leaves the MAC table, its name is kept for an hour.

## How blocking works

Turning a switch **on** sets the rule to `disabled=no`; turning it **off** sets
`disabled=yes`. The new state shows in Home Assistant right away and is confirmed on the next
poll. Rules toggled directly on the router (WinBox, scripts, scheduler) are picked up on the
next poll as well.

Most firewalls have `accept established,related` (and often `fasttrack`) **before** the
block rules, so a drop rule alone only stops **new** connections — an ongoing stream would
keep playing. When *Drop open connections when blocking* is on, the integration also deletes
the entries in `/ip/firewall/connection` whose source is the device IP, so the block is
effective immediately. Unblocking does not touch connections.

## Examples

### Block the kids' devices at bedtime

```yaml
automation:
  - alias: "Bedtime: block kids' devices"
    triggers:
      - trigger: time
        at: "22:00:00"
    actions:
      - action: switch.turn_on
        target:
          entity_id:
            - switch.router_block_kids_tablet
            - switch.router_block_living_room_tv

  - alias: "Morning: unblock kids' devices"
    triggers:
      - trigger: time
        at: "06:30:00"
    actions:
      - action: switch.turn_off
        target:
          entity_id:
            - switch.router_block_kids_tablet
            - switch.router_block_living_room_tv
```

### Dashboard card

```yaml
type: entities
title: Internet access
entities:
  - entity: switch.router_block_kids_tablet
  - entity: switch.router_block_living_room_tv
```

Entity IDs depend on your router identity and rule comments — check
**Settings → Devices & services → RouterOS (MikroTik)** for the real ones.

## Troubleshooting

| Problem | What to check |
|---|---|
| *Invalid username/password…* | User/password, the group has `rest-api`, and the user's `address` allows the Home Assistant IP |
| *Cannot connect…* | `www` / `www-ssl` is enabled and allows the HA IP (`/ip/service print`), port and HTTPS setting match; try `http://<router>/rest/system/identity` in a browser |
| HTTPS fails | Turn off *Verify SSL certificate* for a self-signed certificate |
| Switch fails with an error | The user lacks the `write` policy, or the rule was deleted on the router |
| No switches | Comments must start **exactly** with the prefix (case and trailing space matter) |
| Device still has internet when blocked | The rule is below an accept rule for that device, or the device also uses IPv6 (see [Limitations](#limitations)) |
| Update entity never shows a new version | The router itself cannot reach `upgrade.mikrotik.com` |

Debug logging:

```yaml
logger:
  logs:
    custom_components.routeros_ha: debug
```

When opening an issue, attach the diagnostics file (device page → **⋮ → Download
diagnostics**); passwords, usernames and serial numbers are redacted.

## Limitations

- Block rules are **IPv4** (`/ip/firewall/filter`). If your LAN has IPv6 internet, a blocked
  device can still go out over IPv6 — add a matching `/ipv6/firewall/filter` rule yourself
  or disable IPv6 for that device.
- Dropping open connections needs a single IP in `src-address` (not a range or list).
- A rule deleted on the router leaves an unavailable switch behind; reload the integration,
  then delete the entity.
- The connection table is read in full when blocking; on routers with a very large number
  of connections this can take a few seconds.

## Removal

1. **Settings → Devices & services → RouterOS (MikroTik) → ⋮ → Delete**.
2. Remove the repository in HACS (or delete `custom_components/routeros_ha`), restart.
3. Optionally remove the `ha` user and group on the router. Block rules stay as they are.

## Development

- Tests: `pip install -r requirements_test.txt && pytest` (Linux / macOS / WSL; Home
  Assistant does not run natively on Windows). CI runs Hassfest, the HACS action and the
  test suite on every push.
- Release: bump `version` in `custom_components/routeros_ha/manifest.json`, then push a tag
  `v<version>` or run the **Release** workflow from the Actions tab. HACS picks up GitHub
  releases.
- `tools/make_brand.py` regenerates `brand/icon.png` / `icon@2x.png` (original artwork —
  intentionally not the MikroTik logo). Home Assistant 2026.3+ reads the `brand/` folder
  directly.
- `tools/deploy.py` copies the integration to a Home Assistant host over SSH
  (`pip install paramiko`; settings in `.env`, see `.env.example`).
- `tools/migrate_entity_ids.py [--apply]` renames entity IDs to those of the
  [`mikrotik_router`](https://github.com/tomaae/homeassistant-mikrotik_router) integration
  so dashboards and history carry over (`pip install websockets`). The ID mapping at the
  top of the script matches the author's setup — edit it for yours and run without
  `--apply` first.

## License

[MIT](LICENSE)
