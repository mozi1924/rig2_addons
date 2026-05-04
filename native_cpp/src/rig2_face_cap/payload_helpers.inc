PyObject* sanitize_head_quaternion_impl(PyObject* payload) {
  if (!payload || !PyDict_Check(payload)) {
    return new_none();
  }

  const double w = object_to_double_or(dict_get_item(payload, "w"), 1.0);
  const double x = object_to_double_or(dict_get_item(payload, "x"), 0.0);
  const double y = object_to_double_or(dict_get_item(payload, "y"), 0.0);
  const double z = object_to_double_or(dict_get_item(payload, "z"), 0.0);

  if (!std::isfinite(w) || !std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {
    return new_none();
  }

  const double magnitude = std::sqrt((w * w) + (x * x) + (y * y) + (z * z));
  if (magnitude <= 1e-8) {
    return new_none();
  }

  PyRef out(PyTuple_New(4));
  if (!out) {
    return nullptr;
  }
  if (PyTuple_SetItem(out.get(), 0, PyFloat_FromDouble(w / magnitude)) < 0 ||
      PyTuple_SetItem(out.get(), 1, PyFloat_FromDouble(x / magnitude)) < 0 ||
      PyTuple_SetItem(out.get(), 2, PyFloat_FromDouble(y / magnitude)) < 0 ||
      PyTuple_SetItem(out.get(), 3, PyFloat_FromDouble(z / magnitude)) < 0) {
    return nullptr;
  }

  return out.release();
}

bool quaternions_close_impl(PyObject* lhs, PyObject* rhs, double epsilon, bool* out) {
  if (!out) {
    return false;
  }

  if (lhs == Py_None || rhs == Py_None || !lhs || !rhs) {
    *out = (lhs == rhs);
    return true;
  }

  const Py_ssize_t left_len = PySequence_Size(lhs);
  const Py_ssize_t right_len = PySequence_Size(rhs);
  if (left_len < 0 || right_len < 0) {
    PyErr_Clear();
    *out = false;
    return true;
  }

  const Py_ssize_t size = (std::min)(left_len, right_len);

  for (Py_ssize_t i = 0; i < size; ++i) {
    PyRef left_item(PySequence_GetItem(lhs, i));
    PyRef right_item(PySequence_GetItem(rhs, i));
    if (!left_item || !right_item) {
      PyErr_Clear();
      *out = false;
      return true;
    }

    double a = PyFloat_AsDouble(left_item.get());
    if (PyErr_Occurred()) {
      return false;
    }
    double b = PyFloat_AsDouble(right_item.get());
    if (PyErr_Occurred()) {
      return false;
    }

    if (std::abs(a - b) > epsilon) {
      *out = false;
      return true;
    }
  }

  *out = true;
  return true;
}

bool blendshape_dicts_equal_impl(PyObject* lhs, PyObject* rhs, bool* out) {
  if (!out) {
    return false;
  }

  const bool lhs_is_dict = lhs && PyDict_Check(lhs);
  const bool rhs_is_dict = rhs && PyDict_Check(rhs);
  const Py_ssize_t lhs_size = lhs_is_dict ? PyDict_Size(lhs) : 0;
  const Py_ssize_t rhs_size = rhs_is_dict ? PyDict_Size(rhs) : 0;

  if (lhs_size < 0 || rhs_size < 0) {
    return false;
  }

  if (lhs_size == 0 && rhs_size == 0) {
    *out = true;
    return true;
  }

  if (!lhs_is_dict || !rhs_is_dict) {
    *out = false;
    return true;
  }

  const int eq = PyObject_RichCompareBool(lhs, rhs, Py_EQ);
  if (eq < 0) {
    return false;
  }
  *out = eq != 0;
  return true;
}

PyObject* sanitize_packet_payload(PyObject* packet) {
  if (!packet || !PyDict_Check(packet)) {
    return new_none();
  }

  PyObject* faces = dict_get_item(packet, "faces");
  if (!faces || !PyList_Check(faces)) {
    faces = PyList_New(0);
    if (!faces) {
      return nullptr;
    }
  } else {
    Py_INCREF(faces);
  }
  PyRef faces_holder(faces);

  int face_count = static_cast<int>(PyList_Size(faces));
  PyObject* face_count_obj = dict_get_item(packet, "faceCount");
  if (face_count_obj) {
    long parsed = PyLong_AsLong(face_count_obj);
    if (!PyErr_Occurred()) {
      face_count = static_cast<int>(parsed);
    } else {
      PyErr_Clear();
    }
  }

  PyObject* sent_at = dict_get_item(packet, "sentAt");
  if (!sent_at || sent_at == Py_None) {
    sent_at = PyUnicode_FromString("");
    if (!sent_at) {
      return nullptr;
    }
  } else {
    Py_INCREF(sent_at);
  }
  PyRef sent_at_holder(sent_at);

  PyRef sanitized_faces(PyList_New(0));
  if (!sanitized_faces) {
    return nullptr;
  }

  const Py_ssize_t faces_len = PyList_Size(faces);
  for (Py_ssize_t i = 0; i < faces_len; ++i) {
    PyObject* face = PyList_GetItem(faces, i);
    PyRef sanitized_face(PyDict_New());
    if (!sanitized_face) {
      return nullptr;
    }

    if (!face || !PyDict_Check(face)) {
      PyRef empty_blendshapes(PyDict_New());
      if (!empty_blendshapes) {
        return nullptr;
      }
      if (PyDict_SetItemString(sanitized_face.get(), "blendshapes", empty_blendshapes.get()) < 0 ||
          PyDict_SetItemString(sanitized_face.get(), "head_quaternion", Py_None) < 0) {
        return nullptr;
      }
      if (PyList_Append(sanitized_faces.get(), sanitized_face.get()) < 0) {
        return nullptr;
      }
      continue;
    }

    PyObject* blendshape_payload = dict_get_item(face, "blendshapes");
    if (!blendshape_payload || !PyDict_Check(blendshape_payload)) {
      blendshape_payload = PyDict_New();
      if (!blendshape_payload) {
        return nullptr;
      }
    } else {
      Py_INCREF(blendshape_payload);
    }
    PyRef blendshape_payload_holder(blendshape_payload);

    PyRef sanitized_blendshapes(PyDict_New());
    if (!sanitized_blendshapes) {
      return nullptr;
    }

    Py_ssize_t pos = 0;
    PyObject* key = nullptr;
    PyObject* value = nullptr;
    while (PyDict_Next(blendshape_payload, &pos, &key, &value)) {
      PyRef key_text(PyObject_Str(key));
      if (!key_text) {
        PyErr_Clear();
        continue;
      }

      PyRef clamped(clamp01_object(value));
      if (!clamped) {
        PyErr_Clear();
        continue;
      }

      if (PyDict_SetItem(sanitized_blendshapes.get(), key_text.get(), clamped.get()) < 0) {
        return nullptr;
      }
    }

    PyObject* head_quaternion = Py_None;
    PyObject* head_pose = dict_get_item(face, "headPose");
    if (head_pose && PyDict_Check(head_pose)) {
      PyObject* raw = dict_get_item(head_pose, "quaternionWxyz");
      PyRef sanitized(sanitize_head_quaternion_impl(raw));
      if (!sanitized) {
        return nullptr;
      }
      head_quaternion = sanitized.release();
    } else {
      Py_INCREF(Py_None);
      head_quaternion = Py_None;
    }
    PyRef head_quaternion_holder(head_quaternion);

    if (PyDict_SetItemString(sanitized_face.get(), "blendshapes", sanitized_blendshapes.get()) < 0 ||
        PyDict_SetItemString(sanitized_face.get(), "head_quaternion", head_quaternion_holder.get()) < 0) {
      return nullptr;
    }

    if (PyList_Append(sanitized_faces.get(), sanitized_face.get()) < 0) {
      return nullptr;
    }
  }

  PyRef sent_at_text(PyObject_Str(sent_at_holder.get()));
  if (!sent_at_text) {
    return nullptr;
  }

  PyRef out(PyDict_New());
  if (!out) {
    return nullptr;
  }

  if (PyDict_SetItemString(out.get(), "faces", sanitized_faces.get()) < 0 ||
      dict_set_item_string_owned(out.get(), "face_count", PyLong_FromLong((std::max)(0, face_count))) < 0 ||
      PyDict_SetItemString(out.get(), "sent_at", sent_at_text.get()) < 0) {
    return nullptr;
  }

  return out.release();
}

bool read_file_utf8(const std::string& filepath, std::string* out) {
  return rig2_shared::read_file_bytes_utf8(filepath, out);
}

bool read_u16_le(const unsigned char* bytes, Py_ssize_t len, Py_ssize_t offset, uint16_t* out) {
  if (!bytes || !out || offset < 0 || offset + 2 > len) {
    return false;
  }
  *out = static_cast<uint16_t>(bytes[offset] | (bytes[offset + 1] << 8));
  return true;
}

bool read_u32_le(const unsigned char* bytes, Py_ssize_t len, Py_ssize_t offset, uint32_t* out) {
  if (!bytes || !out || offset < 0 || offset + 4 > len) {
    return false;
  }
  *out = static_cast<uint32_t>(
      (bytes[offset]) |
      (bytes[offset + 1] << 8) |
      (bytes[offset + 2] << 16) |
      (bytes[offset + 3] << 24));
  return true;
}

bool read_f32_le(const unsigned char* bytes, Py_ssize_t len, Py_ssize_t offset, float* out) {
  uint32_t raw = 0;
  if (!read_u32_le(bytes, len, offset, &raw)) {
    return false;
  }
  static_assert(sizeof(float) == sizeof(uint32_t), "float must be 32-bit");
  float value = 0.0f;
  std::memcpy(&value, &raw, sizeof(float));
  *out = value;
  return true;
}

PyObject* extract_schema_names_impl(PyObject* payload) {
  PyRef empty(PyList_New(0));
  if (!empty) {
    return nullptr;
  }
  if (!payload || !PyDict_Check(payload)) {
    return empty.release();
  }

  std::vector<PyObject*> candidates = {
      dict_get_item(payload, "schema"),
      dict_get_item(payload, "blendshapeNames"),
      dict_get_item(payload, "blendshapesSchema"),
  };

  auto sanitize_name_list = [](PyObject* list_obj) -> PyObject* {
    PyRef out(PyList_New(0));
    if (!out) {
      return nullptr;
    }

    const Py_ssize_t len = PyList_Size(list_obj);
    for (Py_ssize_t i = 0; i < len; ++i) {
      PyObject* item = PyList_GetItem(list_obj, i);
      if (!item) {
        continue;
      }
      if (!(PyUnicode_Check(item) || PyLong_Check(item) || PyFloat_Check(item))) {
        continue;
      }
      PyRef text(PyObject_Str(item));
      if (!text) {
        PyErr_Clear();
        continue;
      }
      if (PyList_Append(out.get(), text.get()) < 0) {
        return nullptr;
      }
    }

    return out.release();
  };

  for (PyObject* candidate : candidates) {
    if (!candidate) {
      continue;
    }

    if (PyList_Check(candidate)) {
      PyObject* out = sanitize_name_list(candidate);
      if (!out) {
        return nullptr;
      }
      return out;
    }

    if (PyDict_Check(candidate)) {
      const char* nested_keys[] = {"blendshapeNames", "names", "channels"};
      for (const char* nested_key : nested_keys) {
        PyObject* names = dict_get_item(candidate, nested_key);
        if (!names || !PyList_Check(names)) {
          continue;
        }
        PyObject* out = sanitize_name_list(names);
        if (!out) {
          return nullptr;
        }
        return out;
      }
    }
  }

  return empty.release();
}

bool try_positive_float(PyObject* obj, double* out_value) {
  if (!out_value) {
    return false;
  }
  double value = 0.0;
  if (!object_to_double(obj, &value)) {
    return false;
  }
  if (value <= 0.0) {
    return false;
  }
  *out_value = value;
  return true;
}

bool extract_video_fps_impl(PyObject* payload, double* out_video_fps) {
  if (!out_video_fps) {
    return false;
  }
  if (!payload || !PyDict_Check(payload)) {
    return false;
  }

  PyObject* video_payload = dict_get_item(payload, "video");
  if (video_payload && PyDict_Check(video_payload)) {
    const char* keys[] = {"frameRate", "fps"};
    for (const char* key : keys) {
      double fps = 0.0;
      if (try_positive_float(dict_get_item(video_payload, key), &fps)) {
        *out_video_fps = fps;
        return true;
      }
    }
  }

  const char* keys[] = {"videoFps", "videoFPS", "videoFrameRate", "frameRate", "fps"};
  for (const char* key : keys) {
    PyObject* value = dict_get_item(payload, key);
    if (!value) {
      continue;
    }

    if (PyDict_Check(value)) {
      const char* nested_keys[] = {"value", "fps", "frameRate"};
      for (const char* nested_key : nested_keys) {
        double fps = 0.0;
        if (try_positive_float(dict_get_item(value, nested_key), &fps)) {
          *out_video_fps = fps;
          return true;
        }
      }
    }

    double fps = 0.0;
    if (try_positive_float(value, &fps)) {
      *out_video_fps = fps;
      return true;
    }
  }

  return false;
}

PyObject* extract_faces_impl(PyObject* frame_payload) {
  if (!frame_payload || !PyDict_Check(frame_payload)) {
    return PyList_New(0);
  }

  PyObject* faces = dict_get_item(frame_payload, "faces");
  if (faces && PyList_Check(faces)) {
    Py_INCREF(faces);
    return faces;
  }

  PyObject* compact_faces = dict_get_item(frame_payload, "f");
  if (compact_faces && PyList_Check(compact_faces)) {
    Py_INCREF(compact_faces);
    return compact_faces;
  }

  PyObject* face = dict_get_item(frame_payload, "face");
  if (face && PyDict_Check(face)) {
    PyRef list(PyList_New(1));
    if (!list) {
      return nullptr;
    }
    Py_INCREF(face);
    if (PyList_SetItem(list.get(), 0, face) < 0) {
      Py_DECREF(face);
      return nullptr;
    }
    return list.release();
  }

  return PyList_New(0);
}

double extract_frame_position_impl(PyObject* frame_payload, int fallback_index, double video_fps) {
  if (!frame_payload || !PyDict_Check(frame_payload)) {
    return static_cast<double>(fallback_index);
  }

  const char* direct_keys[] = {"frame", "frameIndex", "videoFrame", "position", "i"};
  for (const char* key : direct_keys) {
    double out = 0.0;
    if (object_to_double(dict_get_item(frame_payload, key), &out)) {
      return out;
    }
  }

  const char* time_keys[] = {"timeSeconds", "time", "timestampSeconds", "t"};
  for (const char* key : time_keys) {
    double out = 0.0;
    if (object_to_double(dict_get_item(frame_payload, key), &out)) {
      return out * video_fps;
    }
  }

  const char* ms_keys[] = {"timestampMs", "timeMs", "ts"};
  for (const char* key : ms_keys) {
    double out = 0.0;
    if (object_to_double(dict_get_item(frame_payload, key), &out)) {
      return (out / 1000.0) * video_fps;
    }
  }

  return static_cast<double>(fallback_index);
}

PyObject* blendshapes_from_payload_impl(PyObject* payload, PyObject* schema_names) {
  PyRef out(PyDict_New());
  if (!out) {
    return nullptr;
  }

  if (payload && PyDict_Check(payload)) {
    Py_ssize_t pos = 0;
    PyObject* key = nullptr;
    PyObject* value = nullptr;
    while (PyDict_Next(payload, &pos, &key, &value)) {
      PyRef key_text(PyObject_Str(key));
      if (!key_text) {
        PyErr_Clear();
        continue;
      }

      PyRef clamped(clamp01_object(value));
      if (!clamped) {
        PyErr_Clear();
        continue;
      }

      if (PyDict_SetItem(out.get(), key_text.get(), clamped.get()) < 0) {
        return nullptr;
      }
    }
    return out.release();
  }

  if (payload && PyList_Check(payload)) {
    const Py_ssize_t payload_len = PyList_Size(payload);
    const Py_ssize_t schema_len = PyList_Check(schema_names) ? PyList_Size(schema_names) : 0;
    const Py_ssize_t max_len = (std::min)(payload_len, schema_len);

    for (Py_ssize_t i = 0; i < max_len; ++i) {
      PyObject* value = PyList_GetItem(payload, i);
      PyObject* schema_name = PyList_GetItem(schema_names, i);
      if (!schema_name) {
        continue;
      }

      PyRef key_text(PyObject_Str(schema_name));
      if (!key_text) {
        PyErr_Clear();
        continue;
      }

      PyRef clamped(clamp01_object(value));
      if (!clamped) {
        PyErr_Clear();
        continue;
      }

      if (PyDict_SetItem(out.get(), key_text.get(), clamped.get()) < 0) {
        return nullptr;
      }
    }

    return out.release();
  }

  return out.release();
}

PyObject* normalize_head_quaternion_impl(PyObject* face_payload) {
  if (!face_payload || !PyDict_Check(face_payload)) {
    return new_none();
  }

  PyRef candidates(PyList_New(0));
  if (!candidates) {
    return nullptr;
  }

  PyObject* candidate = dict_get_item(face_payload, "headQuaternion");
  if (candidate) {
    if (PyList_Append(candidates.get(), candidate) < 0) {
      return nullptr;
    }
  }
  candidate = dict_get_item(face_payload, "quaternionWxyz");
  if (candidate) {
    if (PyList_Append(candidates.get(), candidate) < 0) {
      return nullptr;
    }
  }

  PyObject* head_pose = dict_get_item(face_payload, "headPose");
  if (head_pose && PyDict_Check(head_pose)) {
    PyObject* hp_candidate = dict_get_item(head_pose, "quaternionWxyz");
    if (hp_candidate && PyList_Append(candidates.get(), hp_candidate) < 0) {
      return nullptr;
    }
    hp_candidate = dict_get_item(head_pose, "headQuaternion");
    if (hp_candidate && PyList_Append(candidates.get(), hp_candidate) < 0) {
      return nullptr;
    }
  }

  PyObject* compact_head_pose = dict_get_item(face_payload, "hp");
  if (compact_head_pose && (PyList_Check(compact_head_pose) || PyTuple_Check(compact_head_pose))) {
    const Py_ssize_t size = PySequence_Size(compact_head_pose);
    if (size >= 7) {
      PyRef mapped(PyDict_New());
      if (!mapped) {
        return nullptr;
      }

      PyRef w_value(PySequence_GetItem(compact_head_pose, 3));
      PyRef x_value(PySequence_GetItem(compact_head_pose, 4));
      PyRef y_value(PySequence_GetItem(compact_head_pose, 5));
      PyRef z_value(PySequence_GetItem(compact_head_pose, 6));
      if (!w_value || !x_value || !y_value || !z_value) {
        return nullptr;
      }

      if (PyDict_SetItemString(mapped.get(), "w", w_value.get()) < 0 ||
          PyDict_SetItemString(mapped.get(), "x", x_value.get()) < 0 ||
          PyDict_SetItemString(mapped.get(), "y", y_value.get()) < 0 ||
          PyDict_SetItemString(mapped.get(), "z", z_value.get()) < 0) {
        return nullptr;
      }

      if (PyList_Append(candidates.get(), mapped.get()) < 0) {
        return nullptr;
      }
    }
  }

  const Py_ssize_t candidate_count = PyList_Size(candidates.get());
  for (Py_ssize_t i = 0; i < candidate_count; ++i) {
    PyObject* current = PyList_GetItem(candidates.get(), i);

    PyRef sanitized(sanitize_head_quaternion_impl(current));
    if (!sanitized) {
      return nullptr;
    }
    if (sanitized.get() != Py_None) {
      return sanitized.release();
    }

    if (current && (PyList_Check(current) || PyTuple_Check(current)) && PySequence_Size(current) >= 4) {
      PyRef mapped(PyDict_New());
      if (!mapped) {
        return nullptr;
      }

      PyRef w_value(PySequence_GetItem(current, 0));
      PyRef x_value(PySequence_GetItem(current, 1));
      PyRef y_value(PySequence_GetItem(current, 2));
      PyRef z_value(PySequence_GetItem(current, 3));
      if (!w_value || !x_value || !y_value || !z_value) {
        return nullptr;
      }

      if (PyDict_SetItemString(mapped.get(), "w", w_value.get()) < 0 ||
          PyDict_SetItemString(mapped.get(), "x", x_value.get()) < 0 ||
          PyDict_SetItemString(mapped.get(), "y", y_value.get()) < 0 ||
          PyDict_SetItemString(mapped.get(), "z", z_value.get()) < 0) {
        return nullptr;
      }

      PyRef sanitized_seq(sanitize_head_quaternion_impl(mapped.get()));
      if (!sanitized_seq) {
        return nullptr;
      }
      if (sanitized_seq.get() != Py_None) {
        return sanitized_seq.release();
      }
    }
  }

  return new_none();
}

PyObject* normalize_face_payload_impl(PyObject* face_payload, PyObject* schema_names) {
  if (!face_payload || !PyDict_Check(face_payload)) {
    PyRef out(PyDict_New());
    if (!out) {
      return nullptr;
    }
    PyRef empty_blendshapes(PyDict_New());
    if (!empty_blendshapes) {
      return nullptr;
    }

    if (dict_set_item_string_owned(out.get(), "index", PyLong_FromLong(0)) < 0 ||
        PyDict_SetItemString(out.get(), "blendshapes", empty_blendshapes.get()) < 0 ||
        PyDict_SetItemString(out.get(), "head_quaternion", Py_None) < 0) {
      return nullptr;
    }
    return out.release();
  }

  PyObject* blendshape_payload = dict_get_item(face_payload, "blendshapes");
  if (!blendshape_payload) {
    blendshape_payload = dict_get_item(face_payload, "blendshapeValues");
  }
  if (!blendshape_payload) {
    blendshape_payload = dict_get_item(face_payload, "b");
  }

  long face_index = 0;
  PyObject* index_value = dict_get_item(face_payload, "index");
  if (!index_value) {
    index_value = dict_get_item(face_payload, "i");
  }

  if (index_value) {
    face_index = PyLong_AsLong(index_value);
    if (PyErr_Occurred()) {
      PyErr_Clear();
      face_index = 0;
    }
  }

  PyRef blendshapes(blendshapes_from_payload_impl(blendshape_payload, schema_names));
  if (!blendshapes) {
    return nullptr;
  }

  PyRef head_quaternion(normalize_head_quaternion_impl(face_payload));
  if (!head_quaternion) {
    return nullptr;
  }

  PyRef out(PyDict_New());
  if (!out) {
    return nullptr;
  }
  if (dict_set_item_string_owned(out.get(), "index", PyLong_FromLong(std::max<long>(0, face_index))) < 0 ||
      PyDict_SetItemString(out.get(), "blendshapes", blendshapes.get()) < 0 ||
      PyDict_SetItemString(out.get(), "head_quaternion", head_quaternion.get()) < 0) {
    return nullptr;
  }

  return out.release();
}

PyObject* extract_frame_payloads_impl(PyObject* payload) {
  if (payload && PyList_Check(payload)) {
    Py_INCREF(payload);
    return payload;
  }

  if (payload && PyDict_Check(payload)) {
    const char* keys[] = {"frames", "packets", "samples"};
    for (const char* key : keys) {
      PyObject* frames = dict_get_item(payload, key);
      if (frames && PyList_Check(frames)) {
        Py_INCREF(frames);
        return frames;
      }
    }
  }

  return PyList_New(0);
}
