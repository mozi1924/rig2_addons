void stop_receiver_impl(FaceCapReceiverState* state) {
  if (!state) {
    return;
  }

  std::thread worker;
  SocketHandle server_socket = kInvalidSocket;
  SocketHandle client_socket = kInvalidSocket;
  {
    std::lock_guard<std::mutex> lock(state->mutex);
    state->stop_requested.store(true);
    server_socket = state->server_socket;
    client_socket = state->client_socket;
    if (state->worker.joinable()) {
      worker = std::move(state->worker);
    }
  }

  shutdown_socket(client_socket);
  shutdown_socket(server_socket);
  close_socket(&client_socket);
  close_socket(&server_socket);

  if (worker.joinable()) {
    worker.join();
  }

  PyGILState_STATE gil = PyGILState_Ensure();
  {
    std::lock_guard<std::mutex> lock(state->mutex);
    clear_latest_packet_locked(state);
    state->thread_running = false;
    state->bind_failed = false;
    state->is_listening = false;
    state->client_address.clear();
    state->packet_count = 0;
    state->dropped_packet_count = 0;
    state->last_packet_time = 0.0;
    state->last_sent_at.clear();
    state->status_message = "Stopped";
    state->last_error.clear();
    state->transport_mode = state->receiver_protocol.empty()
        ? std::string(kReceiverProtocolLiveLinkFace)
        : state->receiver_protocol;
    state->transport_encoding.clear();
    state->packet_revision = 0;
    state->polled_revision = 0;
    state->server_socket = kInvalidSocket;
    state->client_socket = kInvalidSocket;
  }
  PyGILState_Release(gil);
}

PyObject* method_start_receiver(PyObject*, PyObject* args, PyObject* kwargs) {
  static const char* kwlist[] = {"host", "port", "options", nullptr};
  PyObject* host_obj = nullptr;
  int port = 0;
  PyObject* options_obj = Py_None;
  if (!PyArg_ParseTupleAndKeywords(
          args,
          kwargs,
          "Oi|O:start_receiver",
          const_cast<char**>(kwlist),
          &host_obj,
          &port,
          &options_obj)) {
    return nullptr;
  }

  std::string receiver_protocol = kReceiverProtocolLiveLinkFace;
  if (options_obj && options_obj != Py_None && PyDict_Check(options_obj)) {
    PyObject* protocol_obj = dict_get_item(options_obj, "receiver_protocol");
    const std::string protocol_text = py_object_to_utf8(protocol_obj);
    if (protocol_text == kReceiverProtocolWebSocket) {
      receiver_protocol = kReceiverProtocolWebSocket;
    } else if (protocol_text == kReceiverProtocolLiveLinkFace) {
      receiver_protocol = kReceiverProtocolLiveLinkFace;
    }
  }

  const std::string host = py_object_to_utf8(host_obj);
  if (host.empty()) {
    PyErr_SetString(PyExc_ValueError, "host must be a non-empty string");
    return nullptr;
  }
  if (port <= 0 || port > 65535) {
    PyErr_SetString(PyExc_ValueError, "port must be in range [1, 65535]");
    return nullptr;
  }

  Py_BEGIN_ALLOW_THREADS
  stop_receiver_impl(&g_receiver_state);
  Py_END_ALLOW_THREADS

  {
    std::lock_guard<std::mutex> lock(g_receiver_state.mutex);
    g_receiver_state.stop_requested.store(false);
    g_receiver_state.thread_running = true;
    g_receiver_state.bind_failed = false;
    g_receiver_state.is_listening = false;
    g_receiver_state.host = host;
    g_receiver_state.port = port;
    g_receiver_state.client_address.clear();
    g_receiver_state.packet_count = 0;
    g_receiver_state.dropped_packet_count = 0;
    g_receiver_state.last_packet_time = 0.0;
    g_receiver_state.last_sent_at.clear();
    g_receiver_state.status_message = "Starting";
    g_receiver_state.last_error.clear();
    g_receiver_state.transport_mode = receiver_protocol;
    g_receiver_state.receiver_protocol = receiver_protocol;
    g_receiver_state.transport_encoding.clear();
    g_receiver_state.packet_revision = 0;
    g_receiver_state.polled_revision = 0;
    g_receiver_state.server_socket = kInvalidSocket;
    g_receiver_state.client_socket = kInvalidSocket;
  }

  g_receiver_state.worker = std::thread(receiver_thread_main, &g_receiver_state, host, port, receiver_protocol);
  Py_RETURN_TRUE;
}

PyObject* method_stop_receiver(PyObject*, PyObject*) {
  Py_BEGIN_ALLOW_THREADS
  stop_receiver_impl(&g_receiver_state);
  Py_END_ALLOW_THREADS
  Py_RETURN_NONE;
}

PyObject* method_poll_latest_packet(PyObject*, PyObject*) {
  PyRef out(PyDict_New());
  if (!out) {
    return nullptr;
  }

  PyObject* packet = nullptr;
  std::string transport_encoding;
  {
    std::lock_guard<std::mutex> lock(g_receiver_state.mutex);
    if (g_receiver_state.latest_packet && g_receiver_state.packet_revision != g_receiver_state.polled_revision) {
      packet = g_receiver_state.latest_packet;
      Py_INCREF(packet);
      g_receiver_state.polled_revision = g_receiver_state.packet_revision;
    }
    transport_encoding = g_receiver_state.transport_encoding;
  }

  if (packet) {
    if (PyDict_SetItemString(out.get(), "packet", packet) < 0) {
      Py_DECREF(packet);
      return nullptr;
    }
    Py_DECREF(packet);
  } else if (PyDict_SetItemString(out.get(), "packet", Py_None) < 0) {
    return nullptr;
  }

  if (transport_encoding.empty()) {
    if (PyDict_SetItemString(out.get(), "transport_encoding", Py_None) < 0) {
      return nullptr;
    }
  } else if (dict_set_item_string_owned(
                 out.get(),
                 "transport_encoding",
                 PyUnicode_FromString(transport_encoding.c_str())) < 0) {
    return nullptr;
  }

  return out.release();
}

PyObject* method_get_receiver_stats(PyObject*, PyObject*) {
  std::string host;
  int port = 0;
  bool is_listening = false;
  bool bind_failed = false;
  std::string client_address;
  uint64_t packet_count = 0;
  uint64_t dropped_packet_count = 0;
  double last_packet_time = 0.0;
  std::string last_sent_at;
  std::string status_message;
  std::string last_error;
  std::string transport_mode;
  std::string transport_encoding;
  {
    std::lock_guard<std::mutex> lock(g_receiver_state.mutex);
    host = g_receiver_state.host;
    port = g_receiver_state.port;
    is_listening = g_receiver_state.is_listening;
    bind_failed = g_receiver_state.bind_failed;
    client_address = g_receiver_state.client_address;
    packet_count = g_receiver_state.packet_count;
    dropped_packet_count = g_receiver_state.dropped_packet_count;
    last_packet_time = g_receiver_state.last_packet_time;
    last_sent_at = g_receiver_state.last_sent_at;
    status_message = g_receiver_state.status_message;
    last_error = g_receiver_state.last_error;
    transport_mode = g_receiver_state.transport_mode;
    transport_encoding = g_receiver_state.transport_encoding;
  }

  PyRef out(PyDict_New());
  if (!out) {
    return nullptr;
  }

  if (dict_set_item_string_owned(out.get(), "host", PyUnicode_FromString(host.c_str())) < 0 ||
      dict_set_item_string_owned(out.get(), "port", PyLong_FromLong(port)) < 0 ||
      dict_set_item_string_owned(out.get(), "is_listening", PyBool_FromLong(is_listening ? 1 : 0)) < 0 ||
      dict_set_item_string_owned(out.get(), "bind_failed", PyBool_FromLong(bind_failed ? 1 : 0)) < 0 ||
      dict_set_item_string_owned(out.get(), "client_address", PyUnicode_FromString(client_address.c_str())) < 0 ||
      dict_set_item_string_owned(out.get(), "packet_count", PyLong_FromUnsignedLongLong(packet_count)) < 0 ||
      dict_set_item_string_owned(
          out.get(), "dropped_packet_count", PyLong_FromUnsignedLongLong(dropped_packet_count)) < 0 ||
      dict_set_item_string_owned(out.get(), "last_packet_time", PyFloat_FromDouble(last_packet_time)) < 0 ||
      dict_set_item_string_owned(out.get(), "last_sent_at", PyUnicode_FromString(last_sent_at.c_str())) < 0 ||
      dict_set_item_string_owned(out.get(), "status_message", PyUnicode_FromString(status_message.c_str())) < 0 ||
      dict_set_item_string_owned(out.get(), "last_error", PyUnicode_FromString(last_error.c_str())) < 0 ||
      dict_set_item_string_owned(out.get(), "transport_mode", PyUnicode_FromString(transport_mode.c_str())) < 0) {
    return nullptr;
  }

  if (transport_encoding.empty()) {
    if (PyDict_SetItemString(out.get(), "transport_encoding", Py_None) < 0) {
      return nullptr;
    }
  } else if (
      dict_set_item_string_owned(out.get(), "transport_encoding", PyUnicode_FromString(transport_encoding.c_str())) <
      0) {
    return nullptr;
  }

  return out.release();
}
