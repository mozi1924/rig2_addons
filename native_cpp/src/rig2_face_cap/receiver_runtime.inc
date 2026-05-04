void ingest_native_packet(FaceCapReceiverState* state, PyObject* packet, const std::string& transport_encoding) {
  if (!state || !packet || !PyDict_Check(packet)) {
    Py_XDECREF(packet);
    return;
  }

  std::lock_guard<std::mutex> lock(state->mutex);
  if (state->latest_packet && state->packet_revision != state->polled_revision) {
    state->dropped_packet_count += 1;
  }
  clear_latest_packet_locked(state);
  state->latest_packet = packet;
  state->packet_count += 1;
  state->packet_revision += 1;
  state->last_packet_time = now_seconds();
  state->last_error.clear();
  state->transport_mode = "websocket";
  state->transport_encoding = transport_encoding;
  state->status_message = transport_encoding == "binary"
      ? "Receiving binary blendshape packets"
      : "Receiving JSON blendshape packets";

  PyObject* sent_at_obj = dict_get_item(packet, "sent_at");
  state->last_sent_at = py_object_to_utf8(sent_at_obj);
}

void handle_client(FaceCapReceiverState* state, SocketHandle client_socket, const std::string& address_text) {
  if (!state || client_socket == kInvalidSocket) {
    return;
  }

  std::vector<unsigned char> buffer;
  std::vector<unsigned char>& scratch = state->recv_scratch;
  buffer.reserve(4096);
  scratch.clear();
  scratch.reserve(8192);

  std::string request_text;
  if (!recv_until_marker(state, client_socket, &buffer, &scratch, "\r\n\r\n", &request_text)) {
    return;
  }

  std::string websocket_key;
  std::vector<std::string> requested_protocols;
  {
    std::istringstream stream(request_text);
    std::string line;
    bool first_line = true;
    while (std::getline(stream, line)) {
      if (!line.empty() && line.back() == '\r') {
        line.pop_back();
      }
      if (first_line) {
        first_line = false;
        continue;
      }
      const size_t colon = line.find(':');
      if (colon == std::string::npos) {
        continue;
      }
      std::string key = line.substr(0, colon);
      std::string value = line.substr(colon + 1);
      key.erase(std::remove_if(key.begin(), key.end(), [](unsigned char c) { return std::isspace(c); }), key.end());
      value.erase(value.begin(), std::find_if(value.begin(), value.end(), [](unsigned char c) { return !std::isspace(c); }));
      std::transform(key.begin(), key.end(), key.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

      if (key == "sec-websocket-key") {
        websocket_key = value;
      } else if (key == "sec-websocket-protocol") {
        std::stringstream protocol_stream(value);
        std::string item;
        while (std::getline(protocol_stream, item, ',')) {
          item.erase(item.begin(), std::find_if(item.begin(), item.end(), [](unsigned char c) { return !std::isspace(c); }));
          item.erase(std::find_if(item.rbegin(), item.rend(), [](unsigned char c) { return !std::isspace(c); }).base(), item.end());
          if (!item.empty()) {
            requested_protocols.push_back(item);
          }
        }
      }
    }
  }

  if (websocket_key.empty()) {
    return;
  }

  std::string selected_protocol;
  if (std::find(requested_protocols.begin(), requested_protocols.end(), kBinarySubprotocol) != requested_protocols.end()) {
    selected_protocol = kBinarySubprotocol;
  } else if (std::find(requested_protocols.begin(), requested_protocols.end(), kJsonSubprotocol) != requested_protocols.end()) {
    selected_protocol = kJsonSubprotocol;
  }

  const std::string accept_value = compute_websocket_accept(websocket_key);
  if (accept_value.empty()) {
    return;
  }

  std::string response =
      "HTTP/1.1 101 Switching Protocols\r\n"
      "Upgrade: websocket\r\n"
      "Connection: Upgrade\r\n"
      "Sec-WebSocket-Accept: " + accept_value + "\r\n";
  if (!selected_protocol.empty()) {
    response += "Sec-WebSocket-Protocol: " + selected_protocol + "\r\n";
  }
  response += "\r\n";
  if (!send_all(client_socket, response.c_str(), response.size())) {
    return;
  }

  {
    std::lock_guard<std::mutex> lock(state->mutex);
    state->client_address = address_text;
    state->status_message = "Client connected: " + address_text;
    state->last_error.clear();
    if (!selected_protocol.empty()) {
      state->transport_encoding = (selected_protocol == kBinarySubprotocol) ? "binary" : "json";
    }
  }

  PyObject* schema_names = nullptr;
  PyGILState_STATE gil = PyGILState_Ensure();
  schema_names = PyList_New(0);
  PyGILState_Release(gil);
  if (!schema_names) {
    return;
  }

  while (!state->stop_requested.load()) {
    ParsedWebSocketFrame frame;
    if (!recv_frame(state, client_socket, &buffer, &scratch, &frame)) {
      break;
    }

    if (frame.opcode == 0x8) {
      send_ws_frame(client_socket, nullptr, 0, 0x8);
      break;
    }
    if (frame.opcode == 0x9) {
      send_ws_frame(client_socket, frame.payload.data(), frame.payload.size(), 0xA);
      continue;
    }

    if (frame.opcode == 0x1) {
      const std::string raw_message(frame.payload.begin(), frame.payload.end());
      const std::string packet_type = sniff_packet_type_text(raw_message);

      PyGILState_STATE msg_gil = PyGILState_Ensure();
      if (packet_type == "schema") {
        PyObject* parsed_schema = parse_schema_message_native(raw_message);
        if (parsed_schema) {
          Py_DECREF(schema_names);
          schema_names = parsed_schema;
          std::lock_guard<std::mutex> lock(state->mutex);
          state->transport_encoding = "binary";
        }
      } else if (packet_type == "blendshapes") {
        PyObject* packet = parse_packet_text_native(raw_message);
        if (packet) {
          ingest_native_packet(state, packet, "json");
        } else {
          std::lock_guard<std::mutex> lock(state->mutex);
          state->last_error = "Ignored an invalid JSON blendshape packet.";
        }
      }
      PyGILState_Release(msg_gil);
      continue;
    }

    if (frame.opcode == 0x2) {
      PyGILState_STATE msg_gil = PyGILState_Ensure();
      PyObject* packet = parse_binary_packet_native(frame.payload, schema_names);
      if (packet) {
        ingest_native_packet(state, packet, "binary");
      } else {
        std::lock_guard<std::mutex> lock(state->mutex);
        state->last_error = "Ignored an invalid binary blendshape packet.";
      }
      PyGILState_Release(msg_gil);
      continue;
    }
  }

  gil = PyGILState_Ensure();
  Py_DECREF(schema_names);
  PyGILState_Release(gil);

  std::lock_guard<std::mutex> lock(state->mutex);
  state->client_address.clear();
  state->transport_encoding.clear();
  if (state->is_listening && !state->bind_failed) {
    state->status_message = "Listening on ws://" + state->host + ":" + std::to_string(state->port);
  }
}

void receiver_thread_main(FaceCapReceiverState* state, std::string host, int port) {
  if (!state) {
    return;
  }

#if defined(_WIN32)
  WSADATA wsa_data;
  const bool wsa_ok = WSAStartup(MAKEWORD(2, 2), &wsa_data) == 0;
  (void)wsa_ok;
#endif

  SocketHandle server_socket = static_cast<SocketHandle>(socket(AF_INET, SOCK_STREAM, 0));
  if (server_socket == kInvalidSocket) {
    set_receiver_error(state, "Face Capture receiver failed: socket() failed.");
    return;
  }

  int reuse = 1;
  setsockopt(server_socket, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char*>(&reuse), sizeof(reuse));

  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_port = htons(static_cast<uint16_t>(port));
  if (inet_pton(AF_INET, host.c_str(), &addr.sin_addr) != 1) {
    close_socket(&server_socket);
    set_receiver_error(state, "Face Capture receiver failed: invalid listen host.");
    return;
  }

  if (bind(server_socket, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0 ||
      listen(server_socket, kReceiverDefaultBacklog) != 0) {
    close_socket(&server_socket);
    std::lock_guard<std::mutex> lock(state->mutex);
    state->bind_failed = true;
    state->status_message = "Face Capture receiver failed on ws://" + host + ":" + std::to_string(port);
    state->last_error = state->status_message;
    return;
  }

  {
    std::lock_guard<std::mutex> lock(state->mutex);
    state->server_socket = server_socket;
    state->bind_failed = false;
    state->is_listening = true;
    state->status_message = "Listening on ws://" + host + ":" + std::to_string(port);
    state->last_error.clear();
  }

  while (!state->stop_requested.load()) {
    if (!wait_socket_readable(server_socket, kReceiverSocketTimeoutMs)) {
      continue;
    }

    sockaddr_in client_addr{};
    socklen_t client_len = static_cast<socklen_t>(sizeof(client_addr));
    SocketHandle client_socket = accept(server_socket, reinterpret_cast<sockaddr*>(&client_addr), &client_len);
    if (client_socket == kInvalidSocket) {
      continue;
    }

    configure_connected_socket(client_socket);

    char ip_text[INET_ADDRSTRLEN] = {0};
    inet_ntop(AF_INET, &client_addr.sin_addr, ip_text, sizeof(ip_text));
    const std::string address_text = std::string(ip_text) + ":" + std::to_string(ntohs(client_addr.sin_port));

    {
      std::lock_guard<std::mutex> lock(state->mutex);
      state->client_socket = client_socket;
    }

    handle_client(state, client_socket, address_text);

    shutdown_socket(client_socket);
    close_socket(&client_socket);
    {
      std::lock_guard<std::mutex> lock(state->mutex);
      state->client_socket = kInvalidSocket;
    }
  }

  shutdown_socket(server_socket);
  close_socket(&server_socket);

  {
    std::lock_guard<std::mutex> lock(state->mutex);
    state->server_socket = kInvalidSocket;
    state->client_socket = kInvalidSocket;
    state->is_listening = false;
    state->client_address.clear();
    state->transport_encoding.clear();
    if (state->status_message != "Stopped") {
      state->status_message = "Stopped";
    }
  }

#if defined(_WIN32)
  WSACleanup();
#endif
}
