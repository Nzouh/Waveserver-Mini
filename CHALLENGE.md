# WSMini Coding Challenge

Welcome to the WSMini coding challenge! You will be fixing bugs and implementing features in a simulated Waveserver Mini network element.

---

## Overview

| Item | Type | Points | Description |
|------|------|-------:|-------------|
| B1 | Bug | /1 | Set port says OK but port never actually enables |
| B2 | Bug | /5 | Logs stop being written after extended use |
| B3 | Bug | /1 | Delete connection reports success for non-existent names |
| B4 | Bug | /3 | Delete port says OK but port never goes down |
| B5 | Bug | /8 | Connections always show DOWN even when both ports are UP |
| F1 | Feature | /8 | Implement traffic generation |
| F2 | Feature | /8 | Implement inject-fault and clear-fault |
| F3 | Feature | /5 | Implement create connection handler with validation |
| F4 | Feature | /2 | Implement stop traffic CLI and handler |
| F5 | Feature | /3 | Implement show logs with filtering |
| F6 | Feature | /2 | Implement health check cron job |
| F7 | **Bonus** | /10 | Implement protection manager microservice |

### Dependency Chain

Some items depend on others. Keep this in mind when planning your approach:

```
B1 ──→ B4   (B4's symptom is masked until B1 is fixed)
F3 ──→ B5   (B5 can't be reproduced without create connection)
F3 ──→ F4   (stop traffic needs a connection to exist)
F1 ──→ F6   (health check logs are more meaningful with traffic running)
F2 + F3 ──→ F7   (protection requires fault injection and connections)
```

---

# Bugs

---

## B1 — Set port says OK but port never actually enables (/1 pt)

> **Note:** B1 and B4 are related bugs. It's recommended that you complete the fix for B1 before attempting B4.

### Steps to Reproduce

```
wsmini> set port 1
[OK] Port-1 enabled
wsmini> show ports

 Port  Type    Admin State  Fault   Oper State  Frames In  Frames Dropped
 ────  ──────  ───────────  ──────  ──────────  ─────────  ──────────────
  1    line    disabled     no      UP                  0          0
  2    line    disabled     no      DOWN                0          0
  3    client  disabled     no      DOWN                0          0
  4    client  disabled     no      DOWN                0          0
  5    client  disabled     no      DOWN                0          0
  6    client  disabled     no      DOWN                0          0
```

- **Expected:** Port 1 should show `admin=enabled`, `oper=UP`.
- **Observed:** The CLI returns success, but the port's admin state is not enabled.

### Hint

- This bug is hidden somewhere in `recalculate_oper_state`.

---

## B2 — Logs stop being written after extended use (/5 pts)

### Steps to Reproduce

1. Start all services with `start.sh` and the CLI with `./cli`.
2. Issue many commands repeatedly (e.g., `show ports`, `set port 1`, `delete port 1`, etc.).
3. After extended use, no new entries appear in `wsmini.log`.

### Hint

- Trace where and how logs are written to `wsmini.log`.

---

## B3 — Delete connection reports success for non-existent names (/1 pt)

### Steps to Reproduce

```
wsmini> delete connection doesnotexist
[OK] Connection doesnotexist deleted
```

- **Expected:** `[ERROR] delete connection failed: could not find connection with that name`
- **Observed:** Returns success for a name that doesn't exist.

> **Note:** You will be able to fully test this fix after implementing the create connection handler (F3).

---

## B4 — Delete port says OK but port never goes down (/3 pts)

> **Note:** It's recommended to fix B1 before fixing B4.

### Steps to Reproduce

```
wsmini> set port 1
[OK] Port-1 enabled
wsmini> show ports

 Port  Type    Admin State  Fault   Oper State  Frames In  Frames Dropped
 ────  ──────  ───────────  ──────  ──────────  ─────────  ──────────────
  1    line    disabled     no      UP                  0          0
  2    line    disabled     no      DOWN                0          0
  3    client  disabled     no      DOWN                0          0
  4    client  disabled     no      DOWN                0          0
  5    client  disabled     no      DOWN                0          0
  6    client  disabled     no      DOWN                0          0

wsmini> delete port 1
[OK] Port-1 disabled
wsmini> show ports

 Port  Type    Admin State  Fault   Oper State  Frames In  Frames Dropped
 ────  ──────  ───────────  ──────  ──────────  ─────────  ──────────────
  1    line    disabled     no      UP                  0          0
  2    line    disabled     no      DOWN                0          0
  3    client  disabled     no      DOWN                0          0
  4    client  disabled     no      DOWN                0          0
  5    client  disabled     no      DOWN                0          0
  6    client  disabled     no      DOWN                0          0
```

- **Expected:** After `delete port`, the port's operational state should be `DOWN`.
- **Observed:** The port remains operationally UP even after being admin-disabled.

---

## B5 — Connections always show DOWN even when both ports are UP (/8 pts)

> **Note:** B5 depends on F3 — you must implement F3 before you can reproduce and verify B5.

### Steps to Reproduce (once F3 is complete)

1. `set port 1` and `set port 3`
2. `create connection c1 1 3`
3. `show connections` → `c1` shows `DOWN`

- **Expected:** Connection should be UP since both port 1 and port 3 are operationally UP.
- **Observed:** Connection is always DOWN regardless of port states.

### Hint

- This bug is hidden somewhere in `conn_manager.c`.

---

# Features

---

## F1 — Implement traffic generation (/8 pts)

**File:** `traffic_manager.c` — `generate_traffic()`

### Description

Build an OTN frame, query the Connection Manager for a route, then forward or drop the frames accordingly. Update local stats (total frames forwarded, dropped, and whether traffic is UP/DOWN) and Port Manager counters.

> **Note:** Generate a frame using `stats.client_port` and `stats.line_port`. A value of `0` means "randomize within its valid range" (client: 3–6, line: 1–2).

### Hints

- See `common.h` for relevant structs and message types.
- See `common.c` for UDP helper functions.

---

## F2 — Implement inject-fault and clear-fault (/8 pts)

**File:** `port_manager.c` — `dispatch()`

### Description

Simulate physical signal loss on a port via `inject-fault` and recover via `clear-fault`.

| Command | Behaviour |
|---------|-----------|
| `inject-fault <port>` | Set the port's fault flag. **Only allowed on admin-enabled ports.** |
| `clear-fault <port>` | Clear the port's fault flag. **Only allowed on admin-enabled ports.** |

### Hints

- You'll need to update `dispatch()` to handle `MSG_INJECT_FAULT` and `MSG_CLEAR_FAULT`.
- See HLD Section 5.2 for expected interaction flow.
- Look for helper functions that already exist to speed up your implementation.

---

## F3 — Implement create connection handler with validation (/5 pts)

**File:** `conn_manager.c` — `handle_create_connection()`

### Description

Implement the create connection handler with proper validation of inputs.

### Hints

- Review HLD Section 4.2 for the validation rules.
- Use `set_error_msg()` to report rejection reasons when a connection fails validation.
- Look at what helper functions already exist in `conn_manager.c`.

---

## F4 — Implement stop traffic CLI and handler (/2 pts)

**Files:** `conn_manager.c`, `cli.c`

### Description

Implement the stop traffic feature end-to-end:

1. `handle_stop_traffic()` in `conn_manager.c` — handles the stop-traffic message.
2. `cmd_stop_traffic()` in `cli.c` — sends the stop-traffic command from the CLI.

---

## F5 — Implement show logs with `--level` and `--service` filtering (/3 pts)

**File:** `cli.c`

### Description

Read the shared log file and print its contents, supporting optional `--level` and `--service` filters. Filters are case-insensitive and combinable.

### Example Output

**No filter:**
```
wsmini> show logs
[26-03-24 10:29:42] [INFO] [port_mgr] [port_manager.c:24] Port initialized
[26-03-24 10:29:42] [INFO] [conn_mgr] [conn_manager.c:13] Initialize connection table
[26-03-24 10:29:42] [INFO] [traffic_mgr] [traffic_manager.c:128] Traffic Manager starting
[26-03-24 10:29:45] [DEBUG] [traffic_mgr] [traffic_manager.c:91] Frame #1 generated: client-6 → line-2 msg="Data payload alpha"
[26-03-24 10:29:45] [WARN] [conn_mgr] [conn_manager.c:150] MSG_LOOKUP_CONNECTION: no connection for client port-6 and line port-2
[26-03-24 10:29:45] [WARN] [traffic_mgr] [traffic_manager.c:103] Frame #1 DROPPED: no connection for client-6 line-2
[26-03-24 10:29:45] [INFO] [port_mgr] [port_manager.c:103] Updated counters for port_idx=5: rx=0 dropped=1
[26-03-24 10:29:48] [DEBUG] [traffic_mgr] [traffic_manager.c:91] Frame #2 generated: client-5 → line-3 msg="Waveserver mini frame"
```

**Filtered by level and service:**
```
wsmini> show logs --level INFO --service port_mgr
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:103] Updated counters for port_idx=4: rx=0 dropped=1
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:231] --------------------------------------------------------------
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:235] port_idx=0 (LINE) admin=Disabled fault=None oper=DOWN received=0 dropped=0
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:235] port_idx=1 (LINE) admin=Disabled fault=None oper=DOWN received=0 dropped=0
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:235] port_idx=2 (CLIENT) admin=Disabled fault=None oper=DOWN received=0 dropped=0
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:235] port_idx=3 (CLIENT) admin=Disabled fault=None oper=DOWN received=0 dropped=0
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:235] port_idx=4 (CLIENT) admin=Disabled fault=None oper=DOWN received=0 dropped=1
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:235] port_idx=5 (CLIENT) admin=Disabled fault=None oper=DOWN received=0 dropped=1
```

---

## F6 — Implement health check cron job (/2 pts)

**File:** `port_manager.c`

### Description

Run a periodic check every 5 seconds that logs the state of all ports at `LOG_INFO` level.

### Example Output

```
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:231] ----------------------------- HEALTH CHECK -----------------------------
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:235] port_idx=0 (LINE) admin=Disabled fault=None oper=DOWN received=0 dropped=0
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:235] port_idx=1 (LINE) admin=Disabled fault=None oper=DOWN received=0 dropped=0
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:235] port_idx=2 (CLIENT) admin=Disabled fault=None oper=DOWN received=0 dropped=0
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:235] port_idx=3 (CLIENT) admin=Disabled fault=None oper=DOWN received=0 dropped=0
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:235] port_idx=4 (CLIENT) admin=Disabled fault=None oper=DOWN received=0 dropped=1
[26-03-24 10:29:48] [INFO] [port_mgr] [port_manager.c:235] port_idx=5 (CLIENT) admin=Disabled fault=None oper=DOWN received=0 dropped=1
```

---

## F7 — Implement protection manager microservice (/10 pts — BONUS)

> **📢 URGENT — From the desk of Upper Management:**
>
> *"Great news, team! After a very productive meeting with our largest customer, we've committed to delivering line protection in the Waveserver Mini — before GA. I know this wasn't on the original roadmap and the release is... soon, but I have full confidence in your abilities. Please see the requirements below. P.S. — This is not optional. — VP of Product"*

> **Prerequisite:** F2 (inject-fault / clear-fault) and F3 (create connection) must be working first.

### Description

Create an entirely new microservice called `protection_manager` that implements 1+1 line protection between port 1 and port 2.

The two line ports form a mutual protection group — when either port faults, all of its connections are automatically switched to the other port, ensuring zero frame drops. When the fault clears, connections revert back.

### CLI Commands

| Command | Behaviour |
|---------|-----------|
| `set protection group` | Creates a protection group pairing port 1 and port 2. Both must be admin-enabled line ports. |
| `delete protection group` | Removes the protection group. Connections revert to their original port assignments. |
| `show protection group` | Shows whether a protection group is active, which port each connection is currently using (original vs. switched), and the total number of switchover events. |

### Expected Behaviour

1. **Fault on either line port:** All connections using the faulted port automatically switch to the other line port. Traffic frames continue to flow without drops.
2. **Clear fault:** Revertive switch — connections that were moved are moved back to their original line port.
3. **No protection group active:** Faults behave normally (traffic drops as before).

### Example

```
wsmini> set port 1
wsmini> set port 2
wsmini> set port 3
wsmini> set port 4
wsmini> create connection c1 1 3
wsmini> create connection c2 2 4
wsmini> set protection group
[OK] Protection group created: port-1 ↔ port-2

wsmini> show protection group
  Protection Group: ACTIVE
  Members:          port-1 ↔ port-2
  Switchovers:      0
  Connection  Original Line  Current Line  State
  ──────────  ─────────────  ────────────  ──────────
  c1          port-1         port-1        normal
  c2          port-2         port-2        normal

-- Fault on port 1: c1 switches to port 2 --
wsmini> inject-fault 1
[OK] Fault injected on port-1
[INFO] Protection switchover: c1 moved from port-1 → port-2

wsmini> show protection group
  Protection Group: ACTIVE
  Members:          port-1 ↔ port-2
  Switchovers:      1
  Connection  Original Line  Current Line  State
  ──────────  ─────────────  ────────────  ──────────
  c1          port-1         port-2        switched
  c2          port-2         port-2        normal

wsmini> show connections

 Name     Client  Line  State
 ───────  ──────  ────  ──────
 c1          3      2    UP              ← traffic still flowing
 c2          4      2    UP

-- Clear fault on port 1: c1 reverts back --
wsmini> clear-fault 1
[OK] Fault cleared on port-1
[INFO] Revertive switch: c1 moved from port-2 → port-1

wsmini> show connections

 Name     Client  Line  State
 ───────  ──────  ────  ──────
 c1          3      1    UP              ← back on original line
 c2          4      2    UP

```

### Hints

- You'll need to create a new directory `protection_manager/` with its own `.c` file.
- The microservice needs its own UDP listen port — see how the existing services register theirs.
- Think about how to detect faults: polling the port manager, or being notified.
- Study how `conn_manager` modifies connections for inspiration on switching the line port.
- Don't forget to add the new service to `start.sh` and the `Makefile`.

---

Good luck!
