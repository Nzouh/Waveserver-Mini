Personal help and dictionary on how to implement stuff

## connections
- Connections are 1-31 chars
- Section 4.2 has all the rules

```c
#define PORT_MANAGER_UDP (5001)
#define CONN_MANAGER_UDP (5002)
#define TRAFFIC_MGR_UDP (5003)

#define MAX_UDP_MSG_SIZE (512)
#define MAX_CONN_NAME_CHARACTER (32)
#define MAX_OTN_PAYLOAD_SIZE (128)

#define MAX_CONNS (4)

#define LOG_FILE_PATH "wsmini.log"
```

Have all of this in common.h and lots of structs

section 4.2
**Role:** Manages the cross-connect table. Links client ports to line ports
and validates that connections are legal.

**Responsibilities:**
- Create connections: validate, store in connection table
- Delete connections: remove from table, free the client port
- Provide route lookups to Traffic Manager (given a client port, return the connected
  line port and connection state)
- When notified of a port going down, mark all affected connections as DOWN
- When notified of a port coming back up, mark affected connections as UP

**Validation Rules (on create):**
1. One port must be a client port (3–6), the other must be a line port (1–2)
2. Operational state for both client and line port must be up.
3. The client port must not already be in a connection
4. Connection names must be unique and between 1 - 31 characters


**Data Owned:**
- `conn_t conns[MAX_CONNS]` — the connection table holds up to 4 connections. Each
  entry stores a connection name, client port, line port, and operational state. An
  entry with `client_port == 0` means no connection exists in that position — it's
  available for a new `create connection` command.

Example connection table (after creating 3 connections, then port 1 goes down):

```
 Name   Client  Line  Operational State
 ─────  ──────  ────  ─────────────────
 xc-1      3      1   DOWN
 xc-2      4      1   DOWN
 xc-3      5      2   UP
```

Port 1 has a fault, so both connections using Line Port 1 (xc-1, xc-2) are marked
DOWN. Connection xc-3 uses Line Port 2 which is healthy, so it stays UP.

**Does NOT do:**
- Does not manage port state (that's Port Manager's job)
- Does not forward traffic (that's Traffic Manager's job)