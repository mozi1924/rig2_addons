PyObject* method_backend_name(PyObject*, PyObject*) {
  return PyUnicode_FromString("rig2_face_cap_cpp");
}

PyObject* method_clamp01(PyObject*, PyObject* args) {
  PyObject* value = nullptr;
  if (!PyArg_ParseTuple(args, "O:clamp01", &value)) {
    return nullptr;
  }
  return clamp01_object(value);
}

PyObject* method_discover_local_ipv4(PyObject*, PyObject* args, PyObject* kwargs) {
  static const char* kwlist[] = {"preferred_host", nullptr};
  PyObject* preferred_host_obj = PyUnicode_FromString("");
  if (!preferred_host_obj) {
    return nullptr;
  }
  PyRef preferred_holder(preferred_host_obj);

  if (!PyArg_ParseTupleAndKeywords(
          args,
          kwargs,
          "|O:discover_local_ipv4",
          const_cast<char**>(kwlist),
          &preferred_host_obj)) {
    return nullptr;
  }

  const std::string preferred = py_object_to_utf8(preferred_host_obj);
  const std::string resolved = discover_local_ipv4_impl(preferred);
  return PyUnicode_FromString(resolved.c_str());
}

PyObject* method_sniff_packet_type(PyObject*, PyObject* args) {
  PyObject* raw_message = nullptr;
  if (!PyArg_ParseTuple(args, "O:sniff_packet_type", &raw_message)) {
    return nullptr;
  }

  if (!raw_message || !PyUnicode_Check(raw_message)) {
    return new_none();
  }

  PyRef text_bytes(PyUnicode_AsUTF8String(raw_message));
  if (!text_bytes) {
    PyErr_Clear();
    return new_none();
  }
  const char* text = PyBytes_AsString(text_bytes.get());
  if (!text) {
    PyErr_Clear();
    return new_none();
  }

  std::string sample(text);
  if (sample.size() > 256) {
    sample.resize(256);
  }

  const std::string type_token = "\"type\"";
  const size_t type_pos = sample.find(type_token);
  if (type_pos == std::string::npos) {
    return new_none();
  }

  size_t colon_pos = sample.find(':', type_pos + type_token.size());
  if (colon_pos == std::string::npos) {
    return new_none();
  }

  size_t value_start = colon_pos + 1;
  while (value_start < sample.size() && std::isspace(static_cast<unsigned char>(sample[value_start]))) {
    ++value_start;
  }
  if (value_start >= sample.size() || sample[value_start] != '"') {
    return new_none();
  }

  ++value_start;
  size_t value_end = sample.find('"', value_start);
  if (value_end == std::string::npos || value_end <= value_start) {
    return new_none();
  }

  const std::string packet_type = sample.substr(value_start, value_end - value_start);
  return PyUnicode_FromStringAndSize(packet_type.c_str(), static_cast<Py_ssize_t>(packet_type.size()));
}

PyObject* method_resolve_transport_encoding(PyObject*, PyObject* args, PyObject* kwargs) {
  static const char* kwlist[] = {"protocol", "raw_message", nullptr};
  PyObject* protocol = nullptr;
  PyObject* raw_message = Py_None;
  if (!PyArg_ParseTupleAndKeywords(
          args,
          kwargs,
          "O|O:resolve_transport_encoding",
          const_cast<char**>(kwlist),
          &protocol,
          &raw_message)) {
    return nullptr;
  }
  (void)raw_message;

  const std::string protocol_text = py_object_to_utf8(protocol);
  if (protocol_text == kBinarySubprotocol) {
    return PyUnicode_FromString("binary");
  }
  if (protocol_text == kJsonSubprotocol) {
    return PyUnicode_FromString("json");
  }
  return new_none();
}

PyObject* method_sanitize_head_quaternion(PyObject*, PyObject* args) {
  PyObject* payload = nullptr;
  if (!PyArg_ParseTuple(args, "O:sanitize_head_quaternion", &payload)) {
    return nullptr;
  }
  return sanitize_head_quaternion_impl(payload);
}

PyObject* method_quaternions_close(PyObject*, PyObject* args, PyObject* kwargs) {
  static const char* kwlist[] = {"lhs", "rhs", "epsilon", nullptr};
  PyObject* lhs = nullptr;
  PyObject* rhs = nullptr;
  double epsilon = 1e-6;
  if (!PyArg_ParseTupleAndKeywords(
          args,
          kwargs,
          "OO|d:quaternions_close",
          const_cast<char**>(kwlist),
          &lhs,
          &rhs,
          &epsilon)) {
    return nullptr;
  }

  bool is_close = false;
  if (!quaternions_close_impl(lhs, rhs, epsilon, &is_close)) {
    return nullptr;
  }
  if (is_close) {
    Py_RETURN_TRUE;
  }
  Py_RETURN_FALSE;
}

PyObject* method_face_payloads_equal(PyObject*, PyObject* args) {
  PyObject* lhs_faces = nullptr;
  PyObject* rhs_faces = nullptr;
  if (!PyArg_ParseTuple(args, "OO:face_payloads_equal", &lhs_faces, &rhs_faces)) {
    return nullptr;
  }

  if (lhs_faces == rhs_faces) {
    Py_RETURN_TRUE;
  }

  if (lhs_faces == Py_None || rhs_faces == Py_None) {
    if (lhs_faces == rhs_faces) {
      Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
  }

  const Py_ssize_t left_len = PySequence_Size(lhs_faces);
  const Py_ssize_t right_len = PySequence_Size(rhs_faces);
  if (left_len < 0 || right_len < 0) {
    PyErr_Clear();
    Py_RETURN_FALSE;
  }

  if (left_len != right_len) {
    Py_RETURN_FALSE;
  }

  for (Py_ssize_t i = 0; i < left_len; ++i) {
    PyRef lhs_face_ref(PySequence_GetItem(lhs_faces, i));
    PyRef rhs_face_ref(PySequence_GetItem(rhs_faces, i));
    if (!lhs_face_ref || !rhs_face_ref) {
      PyErr_Clear();
      Py_RETURN_FALSE;
    }
    PyObject* lhs_face = lhs_face_ref.get();
    PyObject* rhs_face = rhs_face_ref.get();

    PyObject* lhs_blendshape_obj = (lhs_face && PyDict_Check(lhs_face)) ? dict_get_item(lhs_face, "blendshapes")
                                                                         : nullptr;
    PyObject* rhs_blendshape_obj = (rhs_face && PyDict_Check(rhs_face)) ? dict_get_item(rhs_face, "blendshapes")
                                                                         : nullptr;

    bool blendshape_equal = false;
    if (!blendshape_dicts_equal_impl(lhs_blendshape_obj, rhs_blendshape_obj, &blendshape_equal)) {
      return nullptr;
    }
    if (!blendshape_equal) {
      Py_RETURN_FALSE;
    }

    PyObject* lhs_quat = (lhs_face && PyDict_Check(lhs_face)) ? dict_get_item(lhs_face, "head_quaternion") : Py_None;
    PyObject* rhs_quat = (rhs_face && PyDict_Check(rhs_face)) ? dict_get_item(rhs_face, "head_quaternion") : Py_None;

    bool quat_equal = false;
    if (!quaternions_close_impl(lhs_quat ? lhs_quat : Py_None, rhs_quat ? rhs_quat : Py_None, 1e-6, &quat_equal)) {
      return nullptr;
    }
    if (!quat_equal) {
      Py_RETURN_FALSE;
    }
  }

  Py_RETURN_TRUE;
}

PyObject* method_parse_packet_text(PyObject*, PyObject* args) {
  PyObject* packet_text = nullptr;
  if (!PyArg_ParseTuple(args, "O:parse_packet_text", &packet_text)) {
    return nullptr;
  }

  PyRef parsed(json_loads(packet_text));
  if (!parsed) {
    PyErr_Clear();
    return new_none();
  }

  return sanitize_packet_payload(parsed.get());
}

PyObject* method_parse_schema_message(PyObject*, PyObject* args) {
  PyObject* raw_message = nullptr;
  if (!PyArg_ParseTuple(args, "O:parse_schema_message", &raw_message)) {
    return nullptr;
  }

  PyRef packet(json_loads(raw_message));
  if (!packet) {
    PyErr_Clear();
    return new_none();
  }

  if (!PyDict_Check(packet.get())) {
    return new_none();
  }

  PyObject* packet_type = dict_get_item(packet.get(), "type");
  PyObject* packet_format = dict_get_item(packet.get(), "format");

  if (!packet_type || !packet_format) {
    return new_none();
  }

  const std::string type_text = py_object_to_utf8(packet_type);
  const std::string format_text = py_object_to_utf8(packet_format);
  if (type_text != "schema" || format_text != kBinarySubprotocol) {
    return new_none();
  }

  PyObject* blendshape_names = dict_get_item(packet.get(), "blendshapeNames");
  if (!blendshape_names || !PyList_Check(blendshape_names)) {
    return PyList_New(0);
  }

  PyRef sanitized_names(PyList_New(0));
  if (!sanitized_names) {
    return nullptr;
  }

  const Py_ssize_t name_count = PyList_Size(blendshape_names);
  for (Py_ssize_t i = 0; i < name_count; ++i) {
    PyObject* item = PyList_GetItem(blendshape_names, i);
    if (item && PyUnicode_Check(item)) {
      if (PyList_Append(sanitized_names.get(), item) < 0) {
        return nullptr;
      }
    }
  }

  return sanitized_names.release();
}

PyObject* method_parse_binary_packet(PyObject*, PyObject* args) {
  PyObject* packet_bytes_obj = nullptr;
  PyObject* schema_names = nullptr;
  if (!PyArg_ParseTuple(args, "OO:parse_binary_packet", &packet_bytes_obj, &schema_names)) {
    return nullptr;
  }

  PyRef packet_bytes(PyBytes_FromObject(packet_bytes_obj));
  if (!packet_bytes) {
    PyErr_Clear();
    return new_none();
  }

  char* raw_bytes = nullptr;
  Py_ssize_t len = 0;
  if (PyBytes_AsStringAndSize(packet_bytes.get(), &raw_bytes, &len) != 0 || !raw_bytes) {
    PyErr_Clear();
    return new_none();
  }
  const auto* bytes = reinterpret_cast<const unsigned char*>(raw_bytes);

  if (len < 24) {
    return new_none();
  }

  uint32_t magic = 0;
  uint32_t frame_timestamp_ms = 0;
  uint16_t face_count = 0;

  if (!read_u32_le(bytes, len, 0, &magic) || !read_u32_le(bytes, len, 8, &frame_timestamp_ms) ||
      !read_u16_le(bytes, len, 20, &face_count)) {
    return new_none();
  }

  const uint8_t version = bytes[4];
  const uint8_t message_type = bytes[5];

  if (magic != kBinaryPacketMagic || version != kBinaryPacketVersion ||
      message_type != kBinaryMessageBlendshapes) {
    return new_none();
  }

  if (!PyList_Check(schema_names) && !PyTuple_Check(schema_names)) {
    return new_none();
  }

  const Py_ssize_t schema_len = PySequence_Size(schema_names);
  if (schema_len < 0) {
    PyErr_Clear();
    return new_none();
  }

  Py_ssize_t offset = 24;
  PyRef faces_payload(PyList_New(0));
  if (!faces_payload) {
    return nullptr;
  }

  for (uint16_t face_index = 0; face_index < face_count; ++face_index) {
    if (len - offset < 8) {
      return new_none();
    }

    uint16_t blendshape_count = 0;
    if (!read_u16_le(bytes, len, offset + 2, &blendshape_count)) {
      return new_none();
    }
    const uint8_t flags = bytes[offset + 4];
    offset += 8;

    if (blendshape_count > static_cast<uint16_t>(schema_len)) {
      return new_none();
    }

    PyRef head_quaternion(new_none());

    if ((flags & kFaceFlagHeadPose) != 0) {
      const Py_ssize_t head_pose_bytes = static_cast<Py_ssize_t>(kHeadPoseFloatCount * 4);
      if (len - offset < head_pose_bytes) {
        return new_none();
      }

      float head_pose_values[kHeadPoseFloatCount] = {0.0f};
      for (size_t i = 0; i < kHeadPoseFloatCount; ++i) {
        if (!read_f32_le(bytes, len, offset + static_cast<Py_ssize_t>(i * 4), &head_pose_values[i])) {
          return new_none();
        }
      }

      PyRef quaternion_payload(PyDict_New());
      if (!quaternion_payload) {
        return nullptr;
      }
      if (dict_set_item_string_owned(quaternion_payload.get(), "w", PyFloat_FromDouble(head_pose_values[3])) < 0 ||
          dict_set_item_string_owned(quaternion_payload.get(), "x", PyFloat_FromDouble(head_pose_values[4])) < 0 ||
          dict_set_item_string_owned(quaternion_payload.get(), "y", PyFloat_FromDouble(head_pose_values[5])) < 0 ||
          dict_set_item_string_owned(quaternion_payload.get(), "z", PyFloat_FromDouble(head_pose_values[6])) < 0) {
        return nullptr;
      }

      PyRef sanitized_quaternion(sanitize_head_quaternion_impl(quaternion_payload.get()));
      if (!sanitized_quaternion) {
        return nullptr;
      }
      head_quaternion = std::move(sanitized_quaternion);
      offset += head_pose_bytes;
    }

    if ((flags & kFaceFlagTransformationMatrix) != 0) {
      const Py_ssize_t matrix_bytes = static_cast<Py_ssize_t>(kTransformationMatrixFloatCount * 4);
      if (len - offset < matrix_bytes) {
        return new_none();
      }
      offset += matrix_bytes;
    }

    const Py_ssize_t blendshape_bytes = static_cast<Py_ssize_t>(blendshape_count * 4);
    if (len - offset < blendshape_bytes) {
      return new_none();
    }

    PyRef face_blendshapes(PyDict_New());
    if (!face_blendshapes) {
      return nullptr;
    }

    for (uint16_t blendshape_index = 0; blendshape_index < blendshape_count; ++blendshape_index) {
      float value = 0.0f;
      if (!read_f32_le(bytes, len, offset, &value)) {
        return new_none();
      }
      offset += 4;

      PyRef key(PySequence_GetItem(schema_names, blendshape_index));
      if (!key) {
        return nullptr;
      }

      const double clamped_value = (std::max)(0.0, (std::min)(1.0, static_cast<double>(value)));
      PyRef clamped(PyFloat_FromDouble(clamped_value));
      if (!clamped) {
        return nullptr;
      }

      if (PyDict_SetItem(face_blendshapes.get(), key.get(), clamped.get()) < 0) {
        return nullptr;
      }
    }

    PyRef face_payload(PyDict_New());
    if (!face_payload) {
      return nullptr;
    }

    if (PyDict_SetItemString(face_payload.get(), "blendshapes", face_blendshapes.get()) < 0 ||
        PyDict_SetItemString(face_payload.get(), "head_quaternion", head_quaternion.get()) < 0) {
      return nullptr;
    }

    if (PyList_Append(faces_payload.get(), face_payload.get()) < 0) {
      return nullptr;
    }
  }

  PyRef out(PyDict_New());
  if (!out) {
    return nullptr;
  }

  PyRef sent_at(PyUnicode_FromFormat("%u", static_cast<unsigned int>(frame_timestamp_ms)));
  if (!sent_at) {
    return nullptr;
  }

  if (PyDict_SetItemString(out.get(), "faces", faces_payload.get()) < 0 ||
      dict_set_item_string_owned(out.get(), "face_count", PyLong_FromLong(std::max<int>(0, face_count))) < 0 ||
      PyDict_SetItemString(out.get(), "sent_at", sent_at.get()) < 0) {
    return nullptr;
  }

  return out.release();
}

PyObject* method_load_offline_face_cap_payload(PyObject*, PyObject* args) {
  RIG2_CHECK_LICENSE(g_license_state);
  PyObject* filepath_obj = nullptr;
  if (!PyArg_ParseTuple(args, "O:load_offline_face_cap_payload", &filepath_obj)) {
    return nullptr;
  }

  const std::string filepath = py_object_to_utf8(filepath_obj);
  if (filepath.empty()) {
    PyErr_SetString(PyExc_ValueError, "filepath must be a non-empty string");
    return nullptr;
  }

  std::string content;
  if (!read_file_utf8(filepath, &content)) {
    PyErr_SetString(PyExc_OSError, "failed to read face capture json file");
    return nullptr;
  }

  PyRef content_text(PyUnicode_FromStringAndSize(content.c_str(), static_cast<Py_ssize_t>(content.size())));
  if (!content_text) {
    return nullptr;
  }

  PyRef payload(json_loads(content_text.get()));
  if (!payload) {
    return nullptr;
  }

  PyRef schema_names(extract_schema_names_impl(payload.get()));
  if (!schema_names) {
    return nullptr;
  }

  double video_fps = 30.0;
  double extracted_video_fps = 0.0;
  if (extract_video_fps_impl(payload.get(), &extracted_video_fps)) {
    video_fps = extracted_video_fps;
  }

  PyRef frame_payloads(extract_frame_payloads_impl(payload.get()));
  if (!frame_payloads) {
    return nullptr;
  }

  PyRef frames(PyList_New(0));
  if (!frames) {
    return nullptr;
  }

  const Py_ssize_t frame_count = PyList_Check(frame_payloads.get()) ? PyList_Size(frame_payloads.get()) : 0;
  for (Py_ssize_t i = 0; i < frame_count; ++i) {
    PyObject* frame_payload = PyList_GetItem(frame_payloads.get(), i);
    const double source_frame = extract_frame_position_impl(frame_payload, static_cast<int>(i), video_fps);

    PyRef faces(extract_faces_impl(frame_payload));
    if (!faces) {
      return nullptr;
    }

    PyRef normalized_faces(PyList_New(0));
    if (!normalized_faces) {
      return nullptr;
    }

    const Py_ssize_t face_items = PyList_Check(faces.get()) ? PyList_Size(faces.get()) : 0;
    for (Py_ssize_t j = 0; j < face_items; ++j) {
      PyObject* face_payload = PyList_GetItem(faces.get(), j);
      PyRef normalized_face(normalize_face_payload_impl(face_payload, schema_names.get()));
      if (!normalized_face) {
        return nullptr;
      }
      if (PyList_Append(normalized_faces.get(), normalized_face.get()) < 0) {
        return nullptr;
      }
    }

    PyRef frame_entry(PyDict_New());
    if (!frame_entry) {
      return nullptr;
    }

    if (dict_set_item_string_owned(frame_entry.get(), "source_frame", PyFloat_FromDouble(source_frame)) < 0 ||
        PyDict_SetItemString(frame_entry.get(), "faces", normalized_faces.get()) < 0) {
      return nullptr;
    }

    if (PyList_Append(frames.get(), frame_entry.get()) < 0) {
      return nullptr;
    }
  }

  PyRef out(PyDict_New());
  if (!out) {
    return nullptr;
  }

  if (PyDict_SetItemString(out.get(), "schema_names", schema_names.get()) < 0 ||
      dict_set_item_string_owned(out.get(), "video_fps", PyFloat_FromDouble(video_fps)) < 0 ||
      PyDict_SetItemString(out.get(), "frames", frames.get()) < 0) {
    return nullptr;
  }

  return out.release();
}
