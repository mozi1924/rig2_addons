struct ParsedWebSocketFrame {
  uint8_t opcode = 0;
  std::vector<unsigned char> payload;
};

bool recv_frame(
    FaceCapReceiverState* state,
    SocketHandle socket_handle,
    std::vector<unsigned char>* buffer,
    std::vector<unsigned char>* scratch,
    ParsedWebSocketFrame* out_frame) {
  if (!state || socket_handle == kInvalidSocket || !buffer || !scratch || !out_frame) {
    return false;
  }

  std::vector<unsigned char> header;
  if (!read_exact(state, socket_handle, buffer, scratch, 2, &header)) {
    return false;
  }
  const uint8_t first_byte = header[0];
  const uint8_t second_byte = header[1];
  const uint8_t opcode = first_byte & 0x0F;
  const bool masked = (second_byte & 0x80) != 0;
  uint64_t payload_length = second_byte & 0x7F;

  if (payload_length == 126) {
    std::vector<unsigned char> ext;
    if (!read_exact(state, socket_handle, buffer, scratch, 2, &ext)) {
      return false;
    }
    payload_length = (static_cast<uint64_t>(ext[0]) << 8) | static_cast<uint64_t>(ext[1]);
  } else if (payload_length == 127) {
    std::vector<unsigned char> ext;
    if (!read_exact(state, socket_handle, buffer, scratch, 8, &ext)) {
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
    if (!read_exact(state, socket_handle, buffer, scratch, 4, &mask)) {
      return false;
    }
  }

  std::vector<unsigned char> payload;
  if (payload_length > 0) {
    if (!read_exact(state, socket_handle, buffer, scratch, static_cast<size_t>(payload_length), &payload)) {
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
  {
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
