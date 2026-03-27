#include "common.h"
#include <errno.h>
#include <stdint.h>

#define SERVICE_NAME "protection_mgr"

static protection_group_t group;
static protected_connection_t conns[MAX_CONNS];
static int notify_socket;

bool refresh_protected_connections(void)
{
    udp_message_t req = {0};
    req.msg_type = MSG_GET_CONNECTIONS;
    req.status = STATUS_REQUEST;

    udp_message_t resp = {0};
    if (!send_udp_message_and_receive(notify_socket, &req, &resp, CONN_MANAGER_UDP))
    {
        LOG(LOG_ERROR, "Failed to fetch connections from conn_mgr");
        return false;
    }

    if (resp.status != STATUS_SUCCESS)
    {
        LOG(LOG_ERROR, "conn_mgr returned failure for MSG_GET_CONNECTIONS");
        return false;
    }

    udp_get_connections_reply_t *all = (udp_get_connections_reply_t *)resp.payload;
    memset(conns, 0, sizeof(conns));

    int idx = 0;
    for (int i = 0; i < all->conn_count && idx < MAX_CONNS; i++)
    {
        conn_t *c = &all->all_connections[i];
        if (c->line_port != PROTECTION_LINE_A && c->line_port != PROTECTION_LINE_B)
            continue;

        conns[idx].in_use = true;
        conns[idx].client_port = c->client_port;
        conns[idx].original_line_port = c->line_port;
        conns[idx].current_line_port = c->line_port;
        conns[idx].switched = false;
        strncpy(conns[idx].conn_name, c->conn_name, MAX_CONN_NAME_CHARACTER - 1);
        idx++;
    }

    LOG(LOG_INFO, "Protected connections snapshot loaded: %d", idx);
    return true;
}

void initialize_protection()
{
    memset(&group, 0, sizeof(group));
    memset(conns, 0, sizeof(conns));

    group.active = false;
    group.line_a = PROTECTION_LINE_A;
    group.line_b = PROTECTION_LINE_B;
    group.switchover_count = 0;

    LOG(LOG_INFO, "Protection manager initialized");
}

void switch_connection_line(const char *conn_name, uint8_t new_line_port)
{
    udp_message_t req = {0};
    req.msg_type = MSG_SWITCH_CONNECTION_LINE;
    req.status = STATUS_REQUEST;

    udp_switch_connection_line_request_t *payload = (udp_switch_connection_line_request_t *)req.payload;
    strncpy(payload->name, conn_name, MAX_CONN_NAME_CHARACTER - 1);
    payload->new_line_port = new_line_port;

    send_udp_message_one_way(notify_socket, &req, CONN_MANAGER_UDP);
}

void handle_set_protection_group(udp_message_t *response)
{
    if (group.active)
    {
        set_error_msg(response, "protection group already active");
        return;
    }

    if (!refresh_protected_connections())
    {
        set_error_msg(response, "failed to snapshot connections");
        return;
    }

    group.active = true;
    group.switchover_count = 0;
    response->status = STATUS_SUCCESS;

    LOG(LOG_INFO, "Protection group activated: port-%u <-> port-%u",
        group.line_a, group.line_b);
}

void handle_delete_protection_group(udp_message_t *response)
{
    if (!group.active)
    {
        set_error_msg(response, "protection group not active");
        return;
    }

    // go through each connection and move back to original line if currently switched
    for (int i = 0; i < MAX_CONNS; i++)
    {
        if (conns[i].in_use && conns[i].current_line_port != conns[i].original_line_port)
        {
            uint8_t original = conns[i].original_line_port;
            switch_connection_line(conns[i].conn_name, original);
            conns[i].current_line_port = original;
            conns[i].switched = false;
        }
    }

    group.active = false;
    response->status = STATUS_SUCCESS;

    LOG(LOG_INFO, "Protection group deactivated");
}

void handle_get_protection_group(udp_message_t *response)
{
    udp_get_protection_group_reply_t *reply = (udp_get_protection_group_reply_t *)response->payload;
    memset(reply, 0, sizeof(*reply));

    reply->group = group;

    for (int i = 0; i < MAX_CONNS; i++)
    {
        if (!conns[i].in_use)
            continue;

        reply->conns[reply->conn_count] = conns[i];
        reply->conn_count++;
    }

    response->status = STATUS_SUCCESS;
    LOG(LOG_DEBUG, "Returned protection group state: active=%d, conns=%d",
        group.active, reply->conn_count);
}

void handle_protection_fault_event(const udp_message_t *request)
{
    const udp_protection_fault_event_t *payload = (const udp_protection_fault_event_t *)request->payload;
    uint8_t port_id = payload->port_id;
    bool fault_active = payload->fault_active;

    if (!group.active)
    {
        LOG(LOG_DEBUG, "Ignoring fault event on port-%u: protection group inactive", port_id);
        return;
    }

    if (port_id != PROTECTION_LINE_A && port_id != PROTECTION_LINE_B)
    {
        LOG(LOG_WARN, "Ignoring fault event on non-member port-%u", port_id);
        return;
    }

    uint8_t peer_port = (port_id == PROTECTION_LINE_A) ? PROTECTION_LINE_B : PROTECTION_LINE_A;

    if (fault_active)
    {
        // go through each port and switch connections using the faulty port to the other port
        for (int i = 0; i < MAX_CONNS; i++)
        {
            if (!conns[i].in_use || conns[i].current_line_port != port_id)
                continue;

            conns[i].current_line_port = peer_port;
            conns[i].switched = true;
            group.switchover_count++;

            LOG(LOG_INFO, "Protection switchover: %s moved from port-%u -> port-%u",
                conns[i].conn_name, port_id, peer_port);

            switch_connection_line(conns[i].conn_name, peer_port);
        }
    }
    else
    {
        for (int i = 0; i < MAX_CONNS; i++)
        {
            if (!conns[i].in_use || conns[i].original_line_port != port_id)
                continue;
            if (conns[i].current_line_port == port_id)
                continue;

            uint8_t prev_line = conns[i].current_line_port;
            conns[i].current_line_port = port_id;
            conns[i].switched = false;

            LOG(LOG_INFO, "Revertive switch: %s moved from port-%u -> port-%u",
                conns[i].conn_name, prev_line, port_id);

            switch_connection_line(conns[i].conn_name, port_id);
        }
    }
}

bool dispatch(const udp_message_t *req, udp_message_t *resp)
{
    bool send_reply = true;
    resp->msg_type = req->msg_type;
    resp->status = STATUS_FAILURE;

    switch ((msg_type_t)req->msg_type)
    {
    case MSG_SET_PROTECTION_GROUP:
        handle_set_protection_group(resp);
        break;
    case MSG_DELETE_PROTECTION_GROUP:
        handle_delete_protection_group(resp);
        break;
    case MSG_GET_PROTECTION_GROUP:
        handle_get_protection_group(resp);
        break;
    case MSG_PROTECTION_FAULT_EVENT:
        handle_protection_fault_event(req);
        send_reply = false;
        break;
    default:
        LOG(LOG_WARN, "Unknown msg_type: %d", req->msg_type);
        send_reply = false;
        break;
    }

    return send_reply;
}

int main()
{
    log_init(SERVICE_NAME);
    initialize_protection();

    int server_socket = create_udp_server(PROTECTION_MGR_UDP);
    if (server_socket < 0)
    {
        LOG(LOG_ERROR, "Failed to create server socket - exiting");
        return 1;
    }

    notify_socket = create_udp_client();
    if (notify_socket < 0)
    {
        LOG(LOG_ERROR, "Failed to create notify socket - exiting");
        return 1;
    }

    while (true)
    {
        udp_message_t req = {0};
        struct sockaddr_in sender;
        socklen_t sender_len = sizeof(sender);

        ssize_t n = recvfrom(server_socket, &req, sizeof(req), 0, (struct sockaddr *)&sender, &sender_len);
        if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK)
        {
            LOG(LOG_ERROR, "recvfrom failed");
        }
        else if (n > 0)
        {
            udp_message_t resp = {0};
            if (dispatch(&req, &resp) &&
                (sendto(server_socket, &resp, sizeof(resp), 0, (struct sockaddr *)&sender, sender_len) < 0))
            {
                LOG(LOG_ERROR, "sendto reply failed");
            }
        }
    }

    return 0;
}
