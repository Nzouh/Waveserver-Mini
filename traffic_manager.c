#include "common.h"
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#include <errno.h>

#define SERVICE_NAME "traffic_mgr"

static traffic_stats_t stats;
static int client_socket = 0;

void initialize_stats()
{
    memset(&stats, 0, sizeof(stats));
    stats.next_frame_id = 1; // Start from 1
    LOG(LOG_INFO, "Traffic stats initialized");
}

void generate_traffic()
{
    otn_frame_t pkt = {0};
    uint8_t cport;
    uint8_t lport;

    if (stats.client_port == 0)
        cport = (rand() % 4) + 3;
    else
        cport = stats.client_port;

    if (stats.line_port == 0)
        lport = (rand() % 2) + 1;
    else
        lport = stats.line_port;

    pkt.header.client_port = cport;
    pkt.header.line_port = lport;
    pkt.header.frame_id = stats.next_frame_id++;

    snprintf(pkt.data, sizeof(pkt.data),
             "f-%u c-%u l-%u",
             pkt.header.frame_id,
             pkt.header.client_port,
             pkt.header.line_port);

    udp_message_t out = {0};
    udp_message_t in = {0};
    udp_route_lookup_request_t q = {0};

    out.msg_type = MSG_LOOKUP_CONNECTION;
    out.status = STATUS_REQUEST;

    q.client_port = pkt.header.client_port;
    q.line_port = pkt.header.line_port;

    memcpy(out.payload, &q, sizeof(q));

    if (!send_udp_message_and_receive(client_socket, &out, &in, CONN_MANAGER_UDP))
    {
        stats.total_dropped++;

        udp_message_t upd = {0};
        udp_counter_update_t cnt = {0};

        upd.msg_type = MSG_UPDATE_COUNTERS;
        upd.status = STATUS_REQUEST;

        cnt.port_id = pkt.header.client_port;
        cnt.pkts_rx = 0;
        cnt.pkts_dropped = 1;

        memcpy(upd.payload, &cnt, sizeof(cnt));
        send_udp_message_one_way(client_socket, &upd, PORT_MANAGER_UDP);

        return;
    }

    if (in.status == STATUS_SUCCESS)
    {
        udp_route_lookup_reply_t r = {0};
        memcpy(&r, in.payload, sizeof(r));

        if (r.operational_state == CONN_UP)
        {
            stats.total_forwarded++;

            udp_message_t upd = {0};
            udp_counter_update_t cnt = {0};

            upd.msg_type = MSG_UPDATE_COUNTERS;
            upd.status = STATUS_REQUEST;

            cnt.port_id = pkt.header.client_port;
            cnt.pkts_rx = 1;
            cnt.pkts_dropped = 0;

            memcpy(upd.payload, &cnt, sizeof(cnt));
            send_udp_message_one_way(client_socket, &upd, PORT_MANAGER_UDP);

            return;
        }
    }

    stats.total_dropped++;

    udp_message_t upd = {0};
    udp_counter_update_t cnt = {0};

    upd.msg_type = MSG_UPDATE_COUNTERS;
    upd.status = STATUS_REQUEST;

    cnt.port_id = pkt.header.client_port;
    cnt.pkts_rx = 0;
    cnt.pkts_dropped = 1;

    memcpy(upd.payload, &cnt, sizeof(cnt));
    send_udp_message_one_way(client_socket, &upd, PORT_MANAGER_UDP);
}
void handle_get_traffic_stats(udp_message_t *resp)
{
    resp->msg_type = MSG_GET_TRAFFIC_STATS;
    resp->status = STATUS_SUCCESS;
    memcpy(resp->payload, &stats, sizeof(stats));
    LOG(LOG_DEBUG, "Returning traffic stats");
}

void handle_start_traffic(const udp_message_t *req, udp_message_t *resp)
{
    const udp_start_traffic_request_t *udp_request = (const udp_start_traffic_request_t *)req->payload;
    stats.client_port = udp_request->client_port;
    stats.line_port = udp_request->line_port;

    resp->status = STATUS_FAILURE;

    if (stats.line_port != 0 && (stats.line_port < 1 || stats.line_port > 2)) 
    {
        LOG(LOG_ERROR, "[ERROR] Line port must be 1 or 2, got %d\n", stats.line_port);
        return;
    }

    if (stats.client_port != 0 && (stats.client_port < 3 || stats.client_port > 6))
    {
        LOG(LOG_ERROR, "[ERROR] Client port must be 3–6, got %d\n", stats.client_port);
        return;
    }

    stats.running = true;
    resp->status = STATUS_SUCCESS;
    LOG(LOG_INFO, "Traffic started (client=%u, line=%u, 0=random)",
        stats.client_port, stats.line_port);
}

void handle_stop_traffic(udp_message_t *resp)
{
    // TODO: F4 — Stop Traffic Handler (/2 pts)
}

bool dispatch(const udp_message_t *req, udp_message_t *resp)
{
    bool send_reply = true;

    resp->msg_type = req->msg_type;
    resp->status = STATUS_FAILURE;

    switch ((msg_type_t)req->msg_type)
    {
    case MSG_GET_TRAFFIC_STATS:
        handle_get_traffic_stats(resp);
        break;
    case MSG_START_TRAFFIC:
    {
        handle_start_traffic(req, resp);
        break;
    }
    case MSG_STOP_TRAFFIC:
        handle_stop_traffic(resp);
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
    initialize_stats();
    srand(time(NULL)); // Seed random

    int server_socket = create_udp_server(TRAFFIC_MGR_UDP);
    if (server_socket < 0)
    {
        LOG(LOG_ERROR, "Failed to create server socket - exiting");
        return 1;
    }

    client_socket = create_udp_client();
    if (client_socket < 0)
    {
        LOG(LOG_ERROR, "Failed to create client socket - exiting");
        return 1;
    }

    struct timeval rx_timeout = {.tv_sec = 1, .tv_usec = 0};
    setsockopt(server_socket, SOL_SOCKET, SO_RCVTIMEO, &rx_timeout, sizeof(rx_timeout));

    time_t last_traffic = time(NULL);

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

        time_t now = time(NULL);
        if (stats.running && now - last_traffic >= 3)
        {
            generate_traffic();
            last_traffic = now;
        }
    }
    return 0;
}