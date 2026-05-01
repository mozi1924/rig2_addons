#if defined(_WIN32) && !defined(NOMINMAX)
#define NOMINMAX
#endif

#include <Python.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstring>
#include <cstdint>
#include <fstream>
#include <limits>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#if defined(_WIN32)
#include <Winsock2.h>
#include <Ws2tcpip.h>
#if defined(min)
#undef min
#endif
#if defined(max)
#undef max
#endif
#pragma comment(lib, "Ws2_32.lib")
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

#include "shared.h"

namespace {

constexpr int kApiVersion = 3;

// Embedded license secret shared with the Python licensing layer.
// Each native module has an independent secret.
static const unsigned char kLicenseSecret[32] = {
    0xa3, 0xf7, 0xb2, 0xc9, 0xd1, 0xe4, 0x58, 0x07,
    0x6f, 0x32, 0x19, 0xac, 0x4b, 0x6d, 0x0e, 0x87,
    0x15, 0xc2, 0xf9, 0x3a, 0x8b, 0x4e, 0x76, 0x12,
    0xd5, 0xa0, 0x98, 0xc3, 0xf7, 0xe1, 0xb6, 0x49,
};

// License state — set via set_license_state(), checked by sensitive methods.
static rig2_shared::LicenseState g_license_state;

// Expected SHA-256 hashes of critical Python files (hex).
// Generated at build time by scripts/generate_integrity_hashes.py.
#include "integrity_hashes.h"

static PyObject* method_set_license_state(PyObject*, PyObject* args) {
    const char* device_id = nullptr;
    const char* hmac_hex = nullptr;
    uint64_t expires_at = 0;
    if (!PyArg_ParseTuple(args, "sKs:set_license_state",
                          &device_id, &expires_at, &hmac_hex))
        return nullptr;

    rig2_shared::apply_license_state(
        &g_license_state,
        rig2_shared::hmac_sha256_verify(kLicenseSecret, device_id, (int64_t)expires_at,
                                        hmac_hex),
        (int64_t)expires_at,
        "Face Capture native license verification failed. "
        "Re-sync the license or reinstall the binary.");
    Py_RETURN_NONE;
}

static PyObject* method_verify_integrity(PyObject*, PyObject* args) {
    PyObject* hashes_dict = nullptr;
    if (!PyArg_ParseTuple(args, "O!:verify_integrity", &PyDict_Type,
                          &hashes_dict))
        return nullptr;

    rig2_shared::verify_integrity_hashes(hashes_dict, kExpectedPyHashes, "Face Capture",
                                         &g_license_state);
    Py_RETURN_NONE;
}

static PyObject* method_get_license_status(PyObject*, PyObject*) {
    return rig2_shared::build_license_status(g_license_state);
}
constexpr const char* kWebsocketMagic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
constexpr const char* kJsonSubprotocol = "r2fmc.json.v1";
constexpr const char* kBinarySubprotocol = "r2fmc.bin.v1";
constexpr int kReceiverDefaultBacklog = 8;
constexpr int kReceiverSocketTimeoutMs = 500;

constexpr uint32_t kBinaryPacketMagic = 0x5232464D;
constexpr uint8_t kBinaryPacketVersion = 1;
constexpr uint8_t kBinaryMessageBlendshapes = 1;
constexpr uint8_t kFaceFlagHeadPose = 1 << 0;
constexpr uint8_t kFaceFlagTransformationMatrix = 1 << 1;
constexpr size_t kHeadPoseFloatCount = 7;
constexpr size_t kTransformationMatrixFloatCount = 16;

PyObject* method_parse_packet_text(PyObject*, PyObject* args);
PyObject* method_parse_schema_message(PyObject*, PyObject* args);
PyObject* method_parse_binary_packet(PyObject*, PyObject* args);

using rig2_shared::PyRef;
using rig2_shared::dict_get_item;
using rig2_shared::dict_set_item_string_owned;
using rig2_shared::new_none;
using rig2_shared::object_to_double;
using rig2_shared::object_to_double_or;
using rig2_shared::py_object_to_utf8;

#define CHECK_LICENSE() RIG2_CHECK_LICENSE(g_license_state)

PyObject* clamp01_object(PyObject* obj) {
  const double raw = object_to_double_or(obj, 0.0);
  const double clamped = (std::max)(0.0, (std::min)(1.0, raw));
  return PyFloat_FromDouble(clamped);
}


bool normalize_ipv4_address(const std::string& address, std::string* normalized) {
  if (!normalized) {
    return false;
  }
  normalized->clear();

  std::string input = address;
  input.erase(input.begin(), std::find_if(input.begin(), input.end(), [](unsigned char c) {
                return !std::isspace(c);
              }));
  input.erase(
      std::find_if(input.rbegin(), input.rend(), [](unsigned char c) { return !std::isspace(c); }).base(),
      input.end());
  if (input.empty()) {
    return false;
  }

  in_addr addr{};
  if (inet_pton(AF_INET, input.c_str(), &addr) != 1) {
    return false;
  }

  char buffer[INET_ADDRSTRLEN] = {0};
  if (!inet_ntop(AF_INET, &addr, buffer, sizeof(buffer))) {
    return false;
  }

  *normalized = buffer;
  return true;
}

bool is_preferred_lan_ipv4(const std::string& address) {
  in_addr addr{};
  if (inet_pton(AF_INET, address.c_str(), &addr) != 1) {
    return false;
  }

  uint32_t host = ntohl(addr.s_addr);
  const uint8_t octet1 = static_cast<uint8_t>((host >> 24) & 0xFF);
  const uint8_t octet2 = static_cast<uint8_t>((host >> 16) & 0xFF);

  if (host == 0) {
    return false;
  }
  if (octet1 == 127) {
    return false;
  }
  if (octet1 == 169 && octet2 == 254) {
    return false;
  }

  return true;
}

void add_candidate_ipv4(
    const std::string& address,
    std::vector<std::string>* candidates,
    std::vector<std::string>* seen) {
  if (!candidates || !seen) {
    return;
  }

  std::string normalized;
  if (!normalize_ipv4_address(address, &normalized)) {
    return;
  }

  if (std::find(seen->begin(), seen->end(), normalized) != seen->end()) {
    return;
  }

  seen->push_back(normalized);
  candidates->push_back(normalized);
}

std::string discover_local_ipv4_impl(const std::string& preferred_host) {
  std::string normalized_host;
  normalize_ipv4_address(preferred_host, &normalized_host);

  if (!normalized_host.empty() && is_preferred_lan_ipv4(normalized_host)) {
    return normalized_host;
  }

  std::vector<std::string> candidates;
  std::vector<std::string> seen;

  if (!normalized_host.empty() && normalized_host != "0.0.0.0") {
    add_candidate_ipv4(normalized_host, &candidates, &seen);
  }

  const std::array<std::pair<const char*, uint16_t>, 2> probe_targets = {
      std::make_pair("192.0.2.1", 80),
      std::make_pair("8.8.8.8", 80),
  };

#if defined(_WIN32)
  WSADATA wsa_data;
  const bool wsa_ok = WSAStartup(MAKEWORD(2, 2), &wsa_data) == 0;
#endif

  for (const auto& target : probe_targets) {
    int sock = static_cast<int>(socket(AF_INET, SOCK_DGRAM, 0));
#if defined(_WIN32)
    if (sock == INVALID_SOCKET) {
      continue;
    }
#else
    if (sock < 0) {
      continue;
    }
#endif

    sockaddr_in remote{};
    remote.sin_family = AF_INET;
    remote.sin_port = htons(target.second);
    if (inet_pton(AF_INET, target.first, &remote.sin_addr) == 1) {
      if (connect(sock, reinterpret_cast<sockaddr*>(&remote), sizeof(remote)) == 0) {
        sockaddr_in local{};
        socklen_t len = static_cast<socklen_t>(sizeof(local));
        if (getsockname(sock, reinterpret_cast<sockaddr*>(&local), &len) == 0) {
          char ip_text[INET_ADDRSTRLEN] = {0};
          if (inet_ntop(AF_INET, &local.sin_addr, ip_text, sizeof(ip_text))) {
            add_candidate_ipv4(ip_text, &candidates, &seen);
          }
        }
      }
    }

#if defined(_WIN32)
    closesocket(sock);
#else
    close(sock);
#endif
  }

#if defined(_WIN32)
  if (wsa_ok) {
    WSACleanup();
  }
#endif

  for (const std::string& candidate : candidates) {
    if (is_preferred_lan_ipv4(candidate)) {
      return candidate;
    }
  }

  if (!normalized_host.empty() && normalized_host != "0.0.0.0") {
    return normalized_host;
  }

  for (const std::string& candidate : candidates) {
    if (candidate != "0.0.0.0") {
      return candidate;
    }
  }

  return std::string();
}

#include "rig2_face_cap/receiver_core.inc"

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

PyObject* json_loads(PyObject* input_text) {
  PyRef json_module(PyImport_ImportModule("json"));
  if (!json_module) {
    return nullptr;
  }

  PyRef loads_fn(PyObject_GetAttrString(json_module.get(), "loads"));
  if (!loads_fn || !PyCallable_Check(loads_fn.get())) {
    PyErr_SetString(PyExc_RuntimeError, "Failed to resolve json.loads");
    return nullptr;
  }

  return PyObject_CallFunctionObjArgs(loads_fn.get(), input_text, nullptr);
}

bool read_file_utf8(const std::string& filepath, std::string* out) {
  if (!out) {
    return false;
  }

  std::ifstream input(filepath, std::ios::in | std::ios::binary);
  if (!input.is_open()) {
    return false;
  }

  std::ostringstream buffer;
  buffer << input.rdbuf();
  *out = buffer.str();
  return true;
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

#include "rig2_face_cap/receiver_api.inc"

#undef CHECK_LICENSE

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

    PyObject* lhs_blendshape_obj = nullptr;
    PyObject* rhs_blendshape_obj = nullptr;

    if (lhs_face && PyDict_Check(lhs_face)) {
      lhs_blendshape_obj = dict_get_item(lhs_face, "blendshapes");
    }
    if (rhs_face && PyDict_Check(rhs_face)) {
      rhs_blendshape_obj = dict_get_item(rhs_face, "blendshapes");
    }

    PyRef lhs_blendshapes(PyDict_New());
    PyRef rhs_blendshapes(PyDict_New());
    if (!lhs_blendshapes || !rhs_blendshapes) {
      return nullptr;
    }

    if (lhs_blendshape_obj && PyDict_Check(lhs_blendshape_obj)) {
      PyRef copied(PyDict_Copy(lhs_blendshape_obj));
      if (!copied) {
        return nullptr;
      }
      lhs_blendshapes = std::move(copied);
    }
    if (rhs_blendshape_obj && PyDict_Check(rhs_blendshape_obj)) {
      PyRef copied(PyDict_Copy(rhs_blendshape_obj));
      if (!copied) {
        return nullptr;
      }
      rhs_blendshapes = std::move(copied);
    }

    const int blendshape_equal = PyObject_RichCompareBool(
        lhs_blendshapes.get(), rhs_blendshapes.get(), Py_EQ);
    if (blendshape_equal < 0) {
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

      PyRef raw_value(PyFloat_FromDouble(value));
      if (!raw_value) {
        return nullptr;
      }
      PyRef clamped(clamp01_object(raw_value.get()));
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

PyMethodDef kMethods[] = {
    {"backend_name", method_backend_name, METH_NOARGS, "Return native backend name."},
    {"clamp01", method_clamp01, METH_VARARGS, "Clamp value to [0, 1]."},
    {
        "discover_local_ipv4",
        reinterpret_cast<PyCFunction>(method_discover_local_ipv4),
        METH_VARARGS | METH_KEYWORDS,
        "Discover a local IPv4 address.",
    },
    {"face_payloads_equal", method_face_payloads_equal, METH_VARARGS, "Compare face payloads."},
    {"parse_binary_packet", method_parse_binary_packet, METH_VARARGS, "Parse binary face packet."},
    {"parse_packet_text", method_parse_packet_text, METH_VARARGS, "Parse JSON face packet."},
    {"parse_schema_message", method_parse_schema_message, METH_VARARGS, "Parse schema packet."},
    {
        "quaternions_close",
        reinterpret_cast<PyCFunction>(method_quaternions_close),
        METH_VARARGS | METH_KEYWORDS,
        "Compare quaternion tuples.",
    },
    {
        "resolve_transport_encoding",
        reinterpret_cast<PyCFunction>(method_resolve_transport_encoding),
        METH_VARARGS | METH_KEYWORDS,
        "Resolve transport encoding from negotiated protocol.",
    },
    {"sanitize_head_quaternion", method_sanitize_head_quaternion, METH_VARARGS, "Sanitize quaternion payload."},
    {"sniff_packet_type", method_sniff_packet_type, METH_VARARGS, "Sniff packet type from JSON text."},
    {
        "load_offline_face_cap_payload",
        method_load_offline_face_cap_payload,
        METH_VARARGS,
        "Load and normalize offline face capture payload.",
    },
    {
        "start_receiver",
        reinterpret_cast<PyCFunction>(method_start_receiver),
        METH_VARARGS | METH_KEYWORDS,
        "Start native websocket receiver.",
    },
    {"stop_receiver", method_stop_receiver, METH_NOARGS, "Stop native websocket receiver."},
    {"poll_latest_packet", method_poll_latest_packet, METH_NOARGS, "Poll latest packet from receiver."},
    {"get_receiver_stats", method_get_receiver_stats, METH_NOARGS, "Get receiver runtime stats."},
    {"set_license_state", method_set_license_state, METH_VARARGS,
     "Set internal license state (device_id, expires_at, hmac_proof)."},
    {"verify_integrity", method_verify_integrity, METH_VARARGS,
     "Verify integrity of critical Python source files."},
    {"get_license_status", method_get_license_status, METH_NOARGS,
     "Return native authorization status."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef kModuleDef = {
    PyModuleDef_HEAD_INIT,
    "rig2_face_cap",
    "Rig2 native face capture backend.",
    -1,
    kMethods,
};

}  // namespace

PyMODINIT_FUNC PyInit_rig2_face_cap(void) {
  PyObject* module = PyModule_Create(&kModuleDef);
  if (!module) {
    return nullptr;
  }

  if (PyModule_AddIntConstant(module, "RIG2_FACE_CAP_API_VERSION", kApiVersion) < 0 ||
      PyModule_AddStringConstant(module, "BINARY_SUBPROTOCOL", kBinarySubprotocol) < 0 ||
      PyModule_AddStringConstant(module, "JSON_SUBPROTOCOL", kJsonSubprotocol) < 0 ||
      PyModule_AddStringConstant(module, "WEBSOCKET_MAGIC", kWebsocketMagic) < 0) {
    Py_DECREF(module);
    return nullptr;
  }

  return module;
}
