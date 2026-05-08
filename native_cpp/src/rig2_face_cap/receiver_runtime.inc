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
  if (!state->receiver_protocol.empty()) {
    state->transport_mode = state->receiver_protocol;
  }
  state->transport_encoding = transport_encoding;
  if (state->transport_mode == kReceiverProtocolLiveLinkFace) {
    state->status_message = "Receiving LiveLinkFace UDP packets";
  } else {
    state->status_message = transport_encoding == "binary"
        ? "Receiving binary blendshape packets"
        : "Receiving JSON blendshape packets";
  }

  PyObject* sent_at_obj = dict_get_item(packet, "sent_at");
  state->last_sent_at = py_object_to_utf8(sent_at_obj);
}

constexpr std::array<const char*, 61> kLiveLinkFaceBlendshapeNames = {
    "eyeBlinkLeft",
    "eyeLookDownLeft",
    "eyeLookInLeft",
    "eyeLookOutLeft",
    "eyeLookUpLeft",
    "eyeSquintLeft",
    "eyeWideLeft",
    "eyeBlinkRight",
    "eyeLookDownRight",
    "eyeLookInRight",
    "eyeLookOutRight",
    "eyeLookUpRight",
    "eyeSquintRight",
    "eyeWideRight",
    "jawForward",
    "jawLeft",
    "jawRight",
    "jawOpen",
    "mouthClose",
    "mouthFunnel",
    "mouthPucker",
    "mouthLeft",
    "mouthRight",
    "mouthSmileLeft",
    "mouthSmileRight",
    "mouthFrownLeft",
    "mouthFrownRight",
    "mouthDimpleLeft",
    "mouthDimpleRight",
    "mouthStretchLeft",
    "mouthStretchRight",
    "mouthRollLower",
    "mouthRollUpper",
    "mouthShrugLower",
    "mouthShrugUpper",
    "mouthPressLeft",
    "mouthPressRight",
    "mouthLowerDownLeft",
    "mouthLowerDownRight",
    "mouthUpperUpLeft",
    "mouthUpperUpRight",
    "browDownLeft",
    "browDownRight",
    "browInnerUp",
    "browOuterUpLeft",
    "browOuterUpRight",
    "cheekPuff",
    "cheekSquintLeft",
    "cheekSquintRight",
    "noseSneerLeft",
    "noseSneerRight",
    "TongueOut",
    "headYaw",
    "headPitch",
    "headRoll",
    "leftEyeYaw",
    "leftEyePitch",
    "leftEyeRoll",
    "rightEyeYaw",
    "rightEyePitch",
    "rightEyeRoll",
};

bool read_u32_be_bytes(const unsigned char* bytes, size_t len, size_t offset, uint32_t* out) {
  if (!bytes || !out || offset + 4 > len) {
    return false;
  }
  *out = (static_cast<uint32_t>(bytes[offset]) << 24) |
         (static_cast<uint32_t>(bytes[offset + 1]) << 16) |
         (static_cast<uint32_t>(bytes[offset + 2]) << 8) |
         static_cast<uint32_t>(bytes[offset + 3]);
  return true;
}

bool read_i32_be_bytes(const unsigned char* bytes, size_t len, size_t offset, int32_t* out) {
  if (!out) {
    return false;
  }
  uint32_t raw = 0;
  if (!read_u32_be_bytes(bytes, len, offset, &raw)) {
    return false;
  }
  *out = static_cast<int32_t>(raw);
  return true;
}

bool read_f32_be_bytes(const unsigned char* bytes, size_t len, size_t offset, float* out) {
  if (!out) {
    return false;
  }
  uint32_t raw = 0;
  if (!read_u32_be_bytes(bytes, len, offset, &raw)) {
    return false;
  }
  static_assert(sizeof(float) == sizeof(uint32_t), "float must be 32-bit");
  float value = 0.0f;
  std::memcpy(&value, &raw, sizeof(float));
  *out = value;
  return true;
}

PyObject* parse_livelinkface_datagram(const unsigned char* bytes, size_t len) {
  if (!bytes || len < 62) {
    return nullptr;
  }

  const size_t uuid_end = 41;
  const size_t name_len_offset = uuid_end;
  const size_t name_start = 45;
  if (len < name_start) {
    return nullptr;
  }

  int32_t name_length = 0;
  if (!read_i32_be_bytes(bytes, len, name_len_offset, &name_length)) {
    return nullptr;
  }
  if (name_length < 0 || name_length > 4096) {
    return nullptr;
  }

  const size_t name_end = name_start + static_cast<size_t>(name_length);
  if (name_end > len) {
    return nullptr;
  }

  if (len < name_end + 17) {
    return nullptr;
  }

  int32_t frame_number = 0;
  float sub_frame = 0.0f;
  int32_t fps = 0;
  int32_t denominator = 0;
  const size_t frame_meta_offset = name_end;
  if (!read_i32_be_bytes(bytes, len, frame_meta_offset, &frame_number) ||
      !read_f32_be_bytes(bytes, len, frame_meta_offset + 4, &sub_frame) ||
      !read_i32_be_bytes(bytes, len, frame_meta_offset + 8, &fps) ||
      !read_i32_be_bytes(bytes, len, frame_meta_offset + 12, &denominator)) {
    return nullptr;
  }
  (void)sub_frame;
  (void)fps;
  (void)denominator;

  const uint8_t data_length = bytes[frame_meta_offset + 16];
  if (data_length != kLiveLinkFaceBlendshapeNames.size()) {
    return nullptr;
  }

  const size_t blendshape_offset = frame_meta_offset + 17;
  const size_t required_size = blendshape_offset + (static_cast<size_t>(data_length) * 4);
  if (required_size > len) {
    return nullptr;
  }

  std::array<float, 61> values = {};
  for (size_t i = 0; i < values.size(); ++i) {
    float value = 0.0f;
    if (!read_f32_be_bytes(bytes, len, blendshape_offset + (i * 4), &value)) {
      return nullptr;
    }
    values[i] = std::isfinite(static_cast<double>(value)) ? value : 0.0f;
  }

  PyRef blendshapes(PyDict_New());
  if (!blendshapes) {
    return nullptr;
  }
  for (size_t i = 0; i < values.size(); ++i) {
    const bool should_clamp = i <= 51;
    const double normalized_value = should_clamp
        ? (std::max)(0.0, (std::min)(1.0, static_cast<double>(values[i])))
        : static_cast<double>(values[i]);
    PyRef key(PyUnicode_FromString(kLiveLinkFaceBlendshapeNames[i]));
    PyRef py_value(PyFloat_FromDouble(normalized_value));
    if (!key || !py_value || PyDict_SetItem(blendshapes.get(), key.get(), py_value.get()) < 0) {
      return nullptr;
    }
    if (i == 51) {
      PyRef alias_key(PyUnicode_FromString("tongueOut"));
      if (!alias_key || PyDict_SetItem(blendshapes.get(), alias_key.get(), py_value.get()) < 0) {
        return nullptr;
      }
    }
  }

  PyRef head_quaternion(Py_None);
  Py_INCREF(head_quaternion.get());
  {
    const double llf_yaw = static_cast<double>(values[52]);
    const double llf_pitch = static_cast<double>(values[53]);
    const double llf_roll = static_cast<double>(values[54]);

    // Keep the downstream behavior aligned with the existing WebSocket path:
    // - runtime consumes a quaternion as rotation around X/Y/Z axes.
    // - LiveLinkFace provides HeadYaw/HeadPitch/HeadRoll channels.
    // Map LLF channels into X/Y/Z rotation order before quaternion synthesis.
    const double mapped_x_roll = llf_pitch;
    const double mapped_y_pitch = llf_yaw;
    const double mapped_z_yaw = llf_roll;

    if (std::isfinite(mapped_x_roll) && std::isfinite(mapped_y_pitch) && std::isfinite(mapped_z_yaw)) {
      const double cy = std::cos(mapped_z_yaw * 0.5);
      const double sy = std::sin(mapped_z_yaw * 0.5);
      const double cp = std::cos(mapped_y_pitch * 0.5);
      const double sp = std::sin(mapped_y_pitch * 0.5);
      const double cr = std::cos(mapped_x_roll * 0.5);
      const double sr = std::sin(mapped_x_roll * 0.5);

      PyRef quaternion_payload(PyDict_New());
      if (!quaternion_payload) {
        return nullptr;
      }
      if (dict_set_item_string_owned(quaternion_payload.get(), "w", PyFloat_FromDouble((cr * cp * cy) + (sr * sp * sy))) < 0 ||
          dict_set_item_string_owned(quaternion_payload.get(), "x", PyFloat_FromDouble((sr * cp * cy) - (cr * sp * sy))) < 0 ||
          dict_set_item_string_owned(quaternion_payload.get(), "y", PyFloat_FromDouble((cr * sp * cy) + (sr * cp * sy))) < 0 ||
          dict_set_item_string_owned(quaternion_payload.get(), "z", PyFloat_FromDouble((cr * cp * sy) - (sr * sp * cy))) < 0) {
        return nullptr;
      }
      PyRef sanitized_quaternion(sanitize_head_quaternion_impl(quaternion_payload.get()));
      if (!sanitized_quaternion) {
        return nullptr;
      }
      head_quaternion = std::move(sanitized_quaternion);
    }
  }

  PyRef face_payload(PyDict_New());
  if (!face_payload) {
    return nullptr;
  }
  if (PyDict_SetItemString(face_payload.get(), "blendshapes", blendshapes.get()) < 0 ||
      PyDict_SetItemString(face_payload.get(), "head_quaternion", head_quaternion.get()) < 0) {
    return nullptr;
  }

  PyRef faces(PyList_New(0));
  if (!faces || PyList_Append(faces.get(), face_payload.get()) < 0) {
    return nullptr;
  }

  PyRef out(PyDict_New());
  if (!out) {
    return nullptr;
  }
  PyRef sent_at(PyUnicode_FromFormat("%d", frame_number));
  if (!sent_at) {
    return nullptr;
  }
  if (PyDict_SetItemString(out.get(), "faces", faces.get()) < 0 ||
      dict_set_item_string_owned(out.get(), "face_count", PyLong_FromLong(1)) < 0 ||
      PyDict_SetItemString(out.get(), "sent_at", sent_at.get()) < 0) {
    return nullptr;
  }
  return out.release();
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
    state->transport_mode = kReceiverProtocolWebSocket;
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

void receiver_thread_main(
    FaceCapReceiverState* state,
    std::string host,
    int port,
    std::string receiver_protocol) {
  if (!state) {
    return;
  }

  const bool use_websocket = (receiver_protocol == kReceiverProtocolWebSocket);

#if defined(_WIN32)
  WSADATA wsa_data;
  const bool wsa_ok = WSAStartup(MAKEWORD(2, 2), &wsa_data) == 0;
  (void)wsa_ok;
#endif

  SocketHandle server_socket = static_cast<SocketHandle>(socket(AF_INET, use_websocket ? SOCK_STREAM : SOCK_DGRAM, 0));
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
      (use_websocket && listen(server_socket, kReceiverDefaultBacklog) != 0)) {
    close_socket(&server_socket);
    std::lock_guard<std::mutex> lock(state->mutex);
    state->bind_failed = true;
    const std::string scheme = use_websocket ? "ws" : "udp";
    state->status_message = "Face Capture receiver failed on " + scheme + "://" + host + ":" + std::to_string(port);
    state->last_error = state->status_message;
    return;
  }

  {
    std::lock_guard<std::mutex> lock(state->mutex);
    state->server_socket = server_socket;
    state->bind_failed = false;
    state->is_listening = true;
    state->transport_mode = use_websocket ? kReceiverProtocolWebSocket : kReceiverProtocolLiveLinkFace;
    const std::string scheme = use_websocket ? "ws" : "udp";
    state->status_message = "Listening on " + scheme + "://" + host + ":" + std::to_string(port);
    state->last_error.clear();
  }

  if (use_websocket) {
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
  } else {
    std::vector<unsigned char> datagram;
    datagram.resize(4096);

    while (!state->stop_requested.load()) {
      if (!wait_socket_readable(server_socket, kReceiverSocketTimeoutMs)) {
        continue;
      }

      sockaddr_in client_addr{};
      socklen_t client_len = static_cast<socklen_t>(sizeof(client_addr));
#if defined(_WIN32)
      const int rc = recvfrom(
          server_socket,
          reinterpret_cast<char*>(datagram.data()),
          static_cast<int>(datagram.size()),
          0,
          reinterpret_cast<sockaddr*>(&client_addr),
          &client_len);
#else
      const ssize_t rc = recvfrom(
          server_socket,
          datagram.data(),
          datagram.size(),
          0,
          reinterpret_cast<sockaddr*>(&client_addr),
          &client_len);
#endif
      if (rc <= 0) {
        continue;
      }

      const size_t received = static_cast<size_t>(rc);
      char ip_text[INET_ADDRSTRLEN] = {0};
      inet_ntop(AF_INET, &client_addr.sin_addr, ip_text, sizeof(ip_text));
      const std::string address_text = std::string(ip_text) + ":" + std::to_string(ntohs(client_addr.sin_port));

      {
        std::lock_guard<std::mutex> lock(state->mutex);
        state->client_address = address_text;
        state->transport_mode = kReceiverProtocolLiveLinkFace;
      }

      PyGILState_STATE msg_gil = PyGILState_Ensure();
      PyObject* packet = parse_livelinkface_datagram(datagram.data(), received);
      if (packet) {
        ingest_native_packet(state, packet, "binary");
      } else {
        std::lock_guard<std::mutex> lock(state->mutex);
        state->last_error = "Ignored an invalid LiveLinkFace UDP packet.";
      }
      PyGILState_Release(msg_gil);
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
