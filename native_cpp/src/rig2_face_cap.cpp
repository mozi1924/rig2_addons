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

// License state — set via set_license_state(), checked by sensitive methods.
static rig2_shared::LicenseState g_license_state;

RIG2_DEFINE_LICENSE_METHODS("face_cap", "rig2_face_cap")
constexpr const char* kWebsocketMagic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
constexpr const char* kJsonSubprotocol = "r2fmc.json.v1";
constexpr const char* kBinarySubprotocol = "r2fmc.bin.v1";
constexpr const char* kReceiverProtocolLiveLinkFace = "livelinkface";
constexpr const char* kReceiverProtocolWebSocket = "websocket";
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
PyObject* sanitize_head_quaternion_impl(PyObject* payload);

using rig2_shared::PyRef;
using rig2_shared::dict_get_item;
using rig2_shared::dict_set_item_string_owned;
using rig2_shared::json_loads;
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

#include "rig2_face_cap/discovery.inc"

#include "rig2_face_cap/receiver_core.inc"

#include "rig2_face_cap/payload_helpers.inc"

#include "rig2_face_cap/receiver_api.inc"

#undef CHECK_LICENSE

#include "rig2_face_cap/public_methods.inc"

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
    {"apply_native_grant", method_apply_native_grant, METH_VARARGS,
     "Apply a signed native grant token and verify manifests."},
    {"clear_license_state", method_clear_license_state, METH_VARARGS,
     "Clear the current native authorization state."},
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
#if defined(_WIN32)
  static bool winsock_ready = false;
  if (!winsock_ready) {
    WSADATA wsa_data;
    if (WSAStartup(MAKEWORD(2, 2), &wsa_data) == 0) {
      winsock_ready = true;
    }
  }
#endif

  PyObject* module = PyModule_Create(&kModuleDef);
  if (!module) {
    return nullptr;
  }

  if (rig2_shared::add_int_constant_or_cleanup(module, "RIG2_FACE_CAP_API_VERSION",
                                               kApiVersion) < 0 ||
      rig2_shared::add_string_constant_or_cleanup(module, "BINARY_SUBPROTOCOL",
                                                  kBinarySubprotocol) < 0 ||
      rig2_shared::add_string_constant_or_cleanup(module, "JSON_SUBPROTOCOL",
                                                  kJsonSubprotocol) < 0 ||
      rig2_shared::add_string_constant_or_cleanup(module, "WEBSOCKET_MAGIC",
                                                  kWebsocketMagic) < 0) {
    return nullptr;
  }

  return module;
}
