#if defined(_WIN32)
using SocketHandle = SOCKET;
constexpr SocketHandle kInvalidSocket = INVALID_SOCKET;
#else
using SocketHandle = int;
constexpr SocketHandle kInvalidSocket = -1;
#endif

void close_socket(SocketHandle* socket_handle) {
  if (!socket_handle || *socket_handle == kInvalidSocket) {
    return;
  }
#if defined(_WIN32)
  closesocket(*socket_handle);
#else
  close(*socket_handle);
#endif
  *socket_handle = kInvalidSocket;
}

void shutdown_socket(SocketHandle socket_handle) {
  if (socket_handle == kInvalidSocket) {
    return;
  }
#if defined(_WIN32)
  shutdown(socket_handle, SD_BOTH);
#else
  shutdown(socket_handle, SHUT_RDWR);
#endif
}

double now_seconds() {
  using Clock = std::chrono::system_clock;
  const auto elapsed = Clock::now().time_since_epoch();
  return std::chrono::duration_cast<std::chrono::duration<double>>(elapsed).count();
}

struct FaceCapReceiverState {
  std::mutex mutex;
  std::thread worker;
  std::atomic<bool> stop_requested{false};
  bool thread_running = false;
  bool bind_failed = false;
  bool is_listening = false;
  std::string host;
  int port = 0;
  std::string client_address;
  uint64_t packet_count = 0;
  uint64_t dropped_packet_count = 0;
  double last_packet_time = 0.0;
  std::string last_sent_at;
  std::string status_message = "Stopped";
  std::string last_error;
  std::string transport_mode = "websocket";
  std::string transport_encoding;
  uint64_t packet_revision = 0;
  uint64_t polled_revision = 0;
  PyObject* latest_packet = nullptr;
  SocketHandle server_socket = kInvalidSocket;
  SocketHandle client_socket = kInvalidSocket;
};

FaceCapReceiverState g_receiver_state;

void clear_latest_packet_locked(FaceCapReceiverState* state) {
  if (!state || !state->latest_packet) {
    return;
  }
  Py_DECREF(state->latest_packet);
  state->latest_packet = nullptr;
}

void set_receiver_error(FaceCapReceiverState* state, const std::string& message) {
  if (!state) {
    return;
  }
  std::lock_guard<std::mutex> lock(state->mutex);
  state->last_error = message;
  state->status_message = message.empty() ? state->status_message : message;
}

bool send_all(SocketHandle socket_handle, const char* data, size_t size) {
  if (socket_handle == kInvalidSocket || !data) {
    return false;
  }
  size_t sent = 0;
  while (sent < size) {
#if defined(_WIN32)
    const int rc = send(socket_handle, data + sent, static_cast<int>(size - sent), 0);
#else
    const ssize_t rc = send(socket_handle, data + sent, size - sent, 0);
#endif
    if (rc <= 0) {
      return false;
    }
    sent += static_cast<size_t>(rc);
  }
  return true;
}

bool wait_socket_readable(SocketHandle socket_handle, int timeout_ms) {
  if (socket_handle == kInvalidSocket) {
    return false;
  }

  fd_set readfds;
  FD_ZERO(&readfds);
  FD_SET(socket_handle, &readfds);

  timeval tv{};
  tv.tv_sec = timeout_ms / 1000;
  tv.tv_usec = (timeout_ms % 1000) * 1000;

#if defined(_WIN32)
  const int rc = select(0, &readfds, nullptr, nullptr, &tv);
#else
  const int rc = select(socket_handle + 1, &readfds, nullptr, nullptr, &tv);
#endif
  return rc > 0 && FD_ISSET(socket_handle, &readfds);
}

bool recv_append(SocketHandle socket_handle, std::vector<unsigned char>* buffer, size_t chunk_size) {
  if (socket_handle == kInvalidSocket || !buffer || chunk_size == 0) {
    return false;
  }

  std::vector<unsigned char> scratch(chunk_size);
#if defined(_WIN32)
  const int rc = recv(socket_handle, reinterpret_cast<char*>(scratch.data()), static_cast<int>(chunk_size), 0);
#else
  const ssize_t rc = recv(socket_handle, scratch.data(), chunk_size, 0);
#endif
  if (rc <= 0) {
    return false;
  }
  const size_t received = static_cast<size_t>(rc);
  buffer->insert(buffer->end(), scratch.begin(), scratch.begin() + static_cast<std::ptrdiff_t>(received));
  return true;
}

bool recv_until_marker(
    FaceCapReceiverState* state,
    SocketHandle socket_handle,
    std::vector<unsigned char>* buffer,
    const std::string& marker,
    std::string* out) {
  if (!state || socket_handle == kInvalidSocket || !buffer || !out) {
    return false;
  }

  while (!state->stop_requested.load()) {
    const auto found = std::search(buffer->begin(), buffer->end(), marker.begin(), marker.end());
    if (found != buffer->end()) {
      const size_t end_index = static_cast<size_t>(std::distance(buffer->begin(), found)) + marker.size();
      out->assign(buffer->begin(), buffer->begin() + static_cast<std::ptrdiff_t>(end_index));
      buffer->erase(buffer->begin(), buffer->begin() + static_cast<std::ptrdiff_t>(end_index));
      return true;
    }
    if (!wait_socket_readable(socket_handle, kReceiverSocketTimeoutMs)) {
      continue;
    }
    if (!recv_append(socket_handle, buffer, 4096)) {
      return false;
    }
  }
  return false;
}

bool read_exact(
    FaceCapReceiverState* state,
    SocketHandle socket_handle,
    std::vector<unsigned char>* buffer,
    size_t size,
    std::vector<unsigned char>* out) {
  if (!state || socket_handle == kInvalidSocket || !buffer || !out) {
    return false;
  }

  while (!state->stop_requested.load() && buffer->size() < size) {
    if (!wait_socket_readable(socket_handle, kReceiverSocketTimeoutMs)) {
      continue;
    }
    if (!recv_append(socket_handle, buffer, (std::max)(size_t(4096), size - buffer->size()))) {
      return false;
    }
  }

  if (buffer->size() < size) {
    return false;
  }

  out->assign(buffer->begin(), buffer->begin() + static_cast<std::ptrdiff_t>(size));
  buffer->erase(buffer->begin(), buffer->begin() + static_cast<std::ptrdiff_t>(size));
  return true;
}

struct ParsedWebSocketFrame {
  uint8_t opcode = 0;
  std::vector<unsigned char> payload;
};

bool recv_frame(
    FaceCapReceiverState* state,
    SocketHandle socket_handle,
    std::vector<unsigned char>* buffer,
    ParsedWebSocketFrame* out_frame) {
  if (!state || socket_handle == kInvalidSocket || !buffer || !out_frame) {
    return false;
  }

  std::vector<unsigned char> header;
  if (!read_exact(state, socket_handle, buffer, 2, &header)) {
    return false;
  }
  const uint8_t first_byte = header[0];
  const uint8_t second_byte = header[1];
  const uint8_t opcode = first_byte & 0x0F;
  const bool masked = (second_byte & 0x80) != 0;
  uint64_t payload_length = second_byte & 0x7F;

  if (payload_length == 126) {
    std::vector<unsigned char> ext;
    if (!read_exact(state, socket_handle, buffer, 2, &ext)) {
      return false;
    }
    payload_length = (static_cast<uint64_t>(ext[0]) << 8) | static_cast<uint64_t>(ext[1]);
  } else if (payload_length == 127) {
    std::vector<unsigned char> ext;
    if (!read_exact(state, socket_handle, buffer, 8, &ext)) {
      return false;
    }
    payload_length = 0;
    for (size_t i = 0; i < 8; ++i) {
      payload_length = (payload_length << 8) | static_cast<uint64_t>(ext[i]);
    }
  }

  if (payload_length > static_cast<uint64_t>(std::numeric_limits<size_t>::max())) {
    return false;
  }

  std::vector<unsigned char> mask;
  if (masked) {
    if (!read_exact(state, socket_handle, buffer, 4, &mask)) {
      return false;
    }
  }

  std::vector<unsigned char> payload;
  if (payload_length > 0) {
    if (!read_exact(state, socket_handle, buffer, static_cast<size_t>(payload_length), &payload)) {
      return false;
    }
  }

  if (masked) {
    for (size_t i = 0; i < payload.size(); ++i) {
      payload[i] ^= mask[i % 4];
    }
  }

  out_frame->opcode = opcode;
  out_frame->payload = std::move(payload);
  return true;
}

bool send_ws_frame(SocketHandle socket_handle, const unsigned char* payload, size_t size, uint8_t opcode) {
  if (socket_handle == kInvalidSocket) {
    return false;
  }

  std::vector<unsigned char> header;
  header.reserve(14);
  header.push_back(static_cast<unsigned char>(0x80 | (opcode & 0x0F)));

  if (size < 126) {
    header.push_back(static_cast<unsigned char>(size));
  } else if (size <= 0xFFFF) {
    header.push_back(126);
    header.push_back(static_cast<unsigned char>((size >> 8) & 0xFF));
    header.push_back(static_cast<unsigned char>(size & 0xFF));
  } else {
    header.push_back(127);
    for (int i = 7; i >= 0; --i) {
      header.push_back(static_cast<unsigned char>((static_cast<uint64_t>(size) >> (i * 8)) & 0xFF));
    }
  }

  if (!send_all(socket_handle, reinterpret_cast<const char*>(header.data()), header.size())) {
    return false;
  }
  if (size == 0) {
    return true;
  }
  return send_all(socket_handle, reinterpret_cast<const char*>(payload), size);
}

std::string sniff_packet_type_text(const std::string& raw_message) {
  std::string sample = raw_message;
  if (sample.size() > 256) {
    sample.resize(256);
  }

  const std::string type_token = "\"type\"";
  const size_t type_pos = sample.find(type_token);
  if (type_pos == std::string::npos) {
    return std::string();
  }

  const size_t colon_pos = sample.find(':', type_pos + type_token.size());
  if (colon_pos == std::string::npos) {
    return std::string();
  }

  size_t value_start = colon_pos + 1;
  while (value_start < sample.size() && std::isspace(static_cast<unsigned char>(sample[value_start]))) {
    ++value_start;
  }
  if (value_start >= sample.size() || sample[value_start] != '"') {
    return std::string();
  }

  ++value_start;
  const size_t value_end = sample.find('"', value_start);
  if (value_end == std::string::npos || value_end <= value_start) {
    return std::string();
  }

  return sample.substr(value_start, value_end - value_start);
}

std::string compute_websocket_accept(const std::string& websocket_key) {
  if (websocket_key.empty()) {
    return std::string();
  }

  PyGILState_STATE gil = PyGILState_Ensure();
  std::string accept_value;

  PyRef hashlib_module(PyImport_ImportModule("hashlib"));
  PyRef base64_module(PyImport_ImportModule("base64"));
  if (!hashlib_module || !base64_module) {
    PyErr_Clear();
    PyGILState_Release(gil);
    return std::string();
  }

  PyRef sha1_fn(PyObject_GetAttrString(hashlib_module.get(), "sha1"));
  PyRef b64encode_fn(PyObject_GetAttrString(base64_module.get(), "b64encode"));
  if (!sha1_fn || !b64encode_fn || !PyCallable_Check(sha1_fn.get()) || !PyCallable_Check(b64encode_fn.get())) {
    PyErr_Clear();
    PyGILState_Release(gil);
    return std::string();
  }

  const std::string input = websocket_key + kWebsocketMagic;
  PyRef input_bytes(PyBytes_FromStringAndSize(input.c_str(), static_cast<Py_ssize_t>(input.size())));
  if (!input_bytes) {
    PyErr_Clear();
    PyGILState_Release(gil);
    return std::string();
  }

  PyRef sha1_obj(PyObject_CallFunctionObjArgs(sha1_fn.get(), input_bytes.get(), nullptr));
  if (!sha1_obj) {
    PyErr_Clear();
    PyGILState_Release(gil);
    return std::string();
  }

  PyRef digest(PyObject_CallMethod(sha1_obj.get(), "digest", nullptr));
  if (!digest) {
    PyErr_Clear();
    PyGILState_Release(gil);
    return std::string();
  }

  PyRef encoded(PyObject_CallFunctionObjArgs(b64encode_fn.get(), digest.get(), nullptr));
  if (!encoded) {
    PyErr_Clear();
    PyGILState_Release(gil);
    return std::string();
  }

  const char* encoded_text = PyBytes_AsString(encoded.get());
  if (encoded_text) {
    accept_value = encoded_text;
  } else {
    PyErr_Clear();
  }

  PyGILState_Release(gil);
  return accept_value;
}

PyObject* parse_packet_text_native(const std::string& raw_message) {
  PyRef raw_text(PyUnicode_FromStringAndSize(raw_message.c_str(), static_cast<Py_ssize_t>(raw_message.size())));
  if (!raw_text) {
    return nullptr;
  }
  PyRef args(PyTuple_New(1));
  if (!args) {
    return nullptr;
  }
  Py_INCREF(raw_text.get());
  if (PyTuple_SetItem(args.get(), 0, raw_text.get()) < 0) {
    return nullptr;
  }
  PyObject* parsed = method_parse_packet_text(nullptr, args.get());
  if (!parsed || parsed == Py_None) {
    Py_XDECREF(parsed);
    return nullptr;
  }
  return parsed;
}

PyObject* parse_schema_message_native(const std::string& raw_message) {
  PyRef raw_text(PyUnicode_FromStringAndSize(raw_message.c_str(), static_cast<Py_ssize_t>(raw_message.size())));
  if (!raw_text) {
    return nullptr;
  }
  PyRef args(PyTuple_New(1));
  if (!args) {
    return nullptr;
  }
  Py_INCREF(raw_text.get());
  if (PyTuple_SetItem(args.get(), 0, raw_text.get()) < 0) {
    return nullptr;
  }
  PyObject* parsed = method_parse_schema_message(nullptr, args.get());
  if (!parsed || parsed == Py_None || !PyList_Check(parsed)) {
    Py_XDECREF(parsed);
    return nullptr;
  }
  return parsed;
}

PyObject* parse_binary_packet_native(const std::vector<unsigned char>& payload, PyObject* schema_names) {
  if (!schema_names) {
    return nullptr;
  }

  PyRef payload_bytes(PyBytes_FromStringAndSize(
      reinterpret_cast<const char*>(payload.data()),
      static_cast<Py_ssize_t>(payload.size())));
  if (!payload_bytes) {
    return nullptr;
  }

  PyRef args(PyTuple_New(2));
  if (!args) {
    return nullptr;
  }
  Py_INCREF(payload_bytes.get());
  Py_INCREF(schema_names);
  if (PyTuple_SetItem(args.get(), 0, payload_bytes.get()) < 0 ||
      PyTuple_SetItem(args.get(), 1, schema_names) < 0) {
    return nullptr;
  }

  PyObject* parsed = method_parse_binary_packet(nullptr, args.get());
  if (!parsed || parsed == Py_None) {
    Py_XDECREF(parsed);
    return nullptr;
  }
  return parsed;
}

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
  buffer.reserve(4096);

  std::string request_text;
  if (!recv_until_marker(state, client_socket, &buffer, "\r\n\r\n", &request_text)) {
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
    if (!recv_frame(state, client_socket, &buffer, &frame)) {
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
