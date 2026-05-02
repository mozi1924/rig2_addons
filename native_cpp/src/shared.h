#pragma once

#include <Python.h>

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <ctime>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <utility>
#include <string>

namespace rig2_shared {

struct LicenseState {
  int ok = 0;
  int integrity_ok = 0;
  int64_t expires_at = 0;
  std::string device_id;
  std::string feature_id;
  std::string error;
};

inline void set_license_error(LicenseState* state, const std::string& message) {
  if (state) {
    state->error = message;
  }
}

inline void clear_license_state(LicenseState* state, const char* failure_message = nullptr) {
  if (!state) {
    return;
  }
  state->ok = 0;
  state->integrity_ok = 0;
  state->expires_at = 0;
  state->device_id.clear();
  state->feature_id.clear();
  set_license_error(state, failure_message ? failure_message : "");
}

inline void apply_authorized_license_state(LicenseState* state, const std::string& device_id,
                                           const std::string& feature_id,
                                           int64_t expires_at) {
  if (!state) {
    return;
  }
  state->ok = 1;
  state->integrity_ok = 1;
  state->expires_at = expires_at;
  state->device_id = device_id;
  state->feature_id = feature_id;
  set_license_error(state, "");
}

inline PyObject* build_license_status(const LicenseState& state) {
  PyObject* result = PyDict_New();
  if (!result) {
    return nullptr;
  }

  PyObject* expires = PyLong_FromLongLong(state.expires_at);
  if (!expires) {
    Py_DECREF(result);
    return nullptr;
  }

  if (PyDict_SetItemString(result, "authorized", state.ok ? Py_True : Py_False) < 0 ||
      PyDict_SetItemString(result, "expires_at", expires) < 0) {
    Py_DECREF(expires);
    Py_DECREF(result);
    return nullptr;
  }
  Py_DECREF(expires);

  PyObject* reason = PyUnicode_FromString(state.error.c_str());
  if (!reason) {
    Py_DECREF(result);
    return nullptr;
  }
  if (PyDict_SetItemString(result, "reason", reason) < 0) {
    Py_DECREF(reason);
    Py_DECREF(result);
    return nullptr;
  }
  Py_DECREF(reason);
  return result;
}

inline const char* license_error_message(const LicenseState& state) {
  return state.error.empty() ? "License required. Activate your license in Addon Preferences."
                             : state.error.c_str();
}

class PyRef {
 public:
  explicit PyRef(PyObject* obj = nullptr) : obj_(obj) {}
  ~PyRef() { Py_XDECREF(obj_); }

  PyRef(const PyRef&) = delete;
  PyRef& operator=(const PyRef&) = delete;

  PyRef(PyRef&& other) noexcept : obj_(other.obj_) { other.obj_ = nullptr; }
  PyRef& operator=(PyRef&& other) noexcept {
    if (this != &other) {
      Py_XDECREF(obj_);
      obj_ = other.obj_;
      other.obj_ = nullptr;
    }
    return *this;
  }

  PyObject* get() const { return obj_; }
  PyObject* release() {
    PyObject* out = obj_;
    obj_ = nullptr;
    return out;
  }

  explicit operator bool() const { return obj_ != nullptr; }

 private:
  PyObject* obj_;
};

inline PyObject* dict_get_item(PyObject* dict_obj, const char* key) {
  if (!dict_obj || !PyDict_Check(dict_obj)) {
    return nullptr;
  }
  return PyDict_GetItemString(dict_obj, key);
}

inline bool object_to_double(PyObject* obj, double* out) {
  if (!obj || !out) {
    return false;
  }
  const double value = PyFloat_AsDouble(obj);
  if (PyErr_Occurred()) {
    PyErr_Clear();
    return false;
  }
  *out = value;
  return true;
}

inline double object_to_double_or(PyObject* obj, double fallback) {
  double value = fallback;
  if (object_to_double(obj, &value)) {
    return value;
  }
  return fallback;
}

inline PyObject* new_none() {
  Py_INCREF(Py_None);
  return Py_None;
}

inline int dict_set_item_string_owned(PyObject* dict_obj, const char* key,
                                      PyObject* value) {
  if (!value) {
    return -1;
  }
  const int rc = PyDict_SetItemString(dict_obj, key, value);
  Py_DECREF(value);
  return rc;
}

inline std::string py_object_to_utf8(PyObject* obj) {
  if (!obj) {
    return std::string();
  }

  if (PyUnicode_Check(obj)) {
    PyRef utf8_bytes(PyUnicode_AsUTF8String(obj));
    if (!utf8_bytes) {
      PyErr_Clear();
      return std::string();
    }
    const char* utf8 = PyBytes_AsString(utf8_bytes.get());
    if (!utf8) {
      PyErr_Clear();
      return std::string();
    }
    return std::string(utf8);
  }

  PyRef text(PyObject_Str(obj));
  if (!text) {
    PyErr_Clear();
    return std::string();
  }

  PyRef utf8_bytes(PyUnicode_AsUTF8String(text.get()));
  if (!utf8_bytes) {
    PyErr_Clear();
    return std::string();
  }
  const char* utf8 = PyBytes_AsString(utf8_bytes.get());
  if (!utf8) {
    PyErr_Clear();
    return std::string();
  }
  return std::string(utf8);
}

inline std::string trim_ascii(std::string text) {
  const auto not_space = [](unsigned char c) { return !std::isspace(c); };
  text.erase(text.begin(), std::find_if(text.begin(), text.end(), not_space));
  text.erase(std::find_if(text.rbegin(), text.rend(), not_space).base(), text.end());
  return text;
}

inline std::string lowercase_ascii(std::string text) {
  std::transform(text.begin(), text.end(), text.begin(), [](unsigned char c) {
    return static_cast<char>(std::tolower(c));
  });
  return text;
}

inline std::string normalize_ascii_key(PyObject* obj, const char* fallback) {
  const std::string fallback_value = fallback ? fallback : "";
  if (!obj) {
    return fallback_value;
  }

  PyRef as_str(PyObject_Str(obj));
  if (!as_str || !PyUnicode_Check(as_str.get())) {
    PyErr_Clear();
    return fallback_value;
  }

  std::string normalized = py_object_to_utf8(as_str.get());
  if (normalized.empty()) {
    return fallback_value;
  }

  normalized = lowercase_ascii(trim_ascii(std::move(normalized)));
  if (normalized.empty()) {
    return fallback_value;
  }
  return normalized;
}

inline PyObject* get_dict_or_empty(PyObject* obj, const char* key) {
  PyObject* value = dict_get_item(obj, key);
  if (value && PyDict_Check(value)) {
    Py_INCREF(value);
    return value;
  }
  return PyDict_New();
}

inline PyObject* json_loads(PyObject* input_text, const char* failure_message = nullptr) {
  PyRef json_module(PyImport_ImportModule("json"));
  if (!json_module) {
    return nullptr;
  }

  PyRef loads_fn(PyObject_GetAttrString(json_module.get(), "loads"));
  if (!loads_fn || !PyCallable_Check(loads_fn.get())) {
    PyErr_SetString(PyExc_RuntimeError,
                    failure_message ? failure_message : "Failed to resolve json.loads");
    return nullptr;
  }

  return PyObject_CallFunctionObjArgs(loads_fn.get(), input_text, nullptr);
}

inline int add_int_constant_or_cleanup(PyObject* module, const char* name, long value) {
  if (!module || !name || PyModule_AddIntConstant(module, name, value) < 0) {
    Py_XDECREF(module);
    return -1;
  }
  return 0;
}

inline int add_string_constant_or_cleanup(PyObject* module, const char* name,
                                          const char* value) {
  if (!module || !name || !value || PyModule_AddStringConstant(module, name, value) < 0) {
    Py_XDECREF(module);
    return -1;
  }
  return 0;
}

inline PyObject* b64url_decode(const std::string& input) {
  std::string padded = input;
  const size_t rem = padded.size() % 4;
  if (rem) {
    padded.append(4 - rem, '=');
  }
  PyRef base64_module(PyImport_ImportModule("base64"));
  if (!base64_module) {
    return nullptr;
  }
  PyRef decode_fn(PyObject_GetAttrString(base64_module.get(), "urlsafe_b64decode"));
  if (!decode_fn || !PyCallable_Check(decode_fn.get())) {
    return nullptr;
  }
  PyRef data(PyBytes_FromStringAndSize(padded.data(), static_cast<Py_ssize_t>(padded.size())));
  if (!data) {
    return nullptr;
  }
  return PyObject_CallFunctionObjArgs(decode_fn.get(), data.get(), nullptr);
}

inline PyObject* py_int_from_bytes(PyObject* bytes_obj) {
  if (!bytes_obj) {
    return nullptr;
  }
  PyRef from_bytes(PyObject_GetAttrString(reinterpret_cast<PyObject*>(&PyLong_Type), "from_bytes"));
  if (!from_bytes || !PyCallable_Check(from_bytes.get())) {
    return nullptr;
  }
  PyRef order(PyUnicode_FromString("big"));
  if (!order) {
    return nullptr;
  }
  return PyObject_CallFunctionObjArgs(from_bytes.get(), bytes_obj, order.get(), nullptr);
}

inline std::string sha256_hex_file(const std::string& path) {
  std::ifstream input(path.c_str(), std::ios::in | std::ios::binary);
  if (!input) {
    return std::string();
  }
  std::ostringstream buffer;
  buffer << input.rdbuf();
  const std::string data = buffer.str();

  PyRef hashlib_module(PyImport_ImportModule("hashlib"));
  if (!hashlib_module) {
    PyErr_Clear();
    return std::string();
  }
  PyRef sha256_fn(PyObject_GetAttrString(hashlib_module.get(), "sha256"));
  if (!sha256_fn || !PyCallable_Check(sha256_fn.get())) {
    PyErr_Clear();
    return std::string();
  }
  PyRef payload(PyBytes_FromStringAndSize(data.data(), static_cast<Py_ssize_t>(data.size())));
  if (!payload) {
    PyErr_Clear();
    return std::string();
  }
  PyRef sha_obj(PyObject_CallFunctionObjArgs(sha256_fn.get(), payload.get(), nullptr));
  if (!sha_obj) {
    PyErr_Clear();
    return std::string();
  }
  PyRef hex_obj(PyObject_CallMethod(sha_obj.get(), "hexdigest", nullptr));
  if (!hex_obj) {
    PyErr_Clear();
    return std::string();
  }
  return py_object_to_utf8(hex_obj.get());
}

inline bool jwt_audience_matches(PyObject* audience_obj, const char* expected) {
  if (!expected || !expected[0]) {
    return true;
  }
  if (!audience_obj) {
    return false;
  }
  if (PyList_Check(audience_obj) || PyTuple_Check(audience_obj)) {
    const Py_ssize_t count = PySequence_Size(audience_obj);
    for (Py_ssize_t i = 0; i < count; ++i) {
      PyRef item(PySequence_GetItem(audience_obj, i));
      if (py_object_to_utf8(item.get()) == expected) {
        return true;
      }
    }
    return false;
  }
  return py_object_to_utf8(audience_obj) == expected;
}

inline bool verify_rs256_jwt_from_jwks(const std::string& token, const std::string& jwks_json,
                                       const char* expected_audience,
                                       const char* expected_issuer,
                                       const char* expected_type,
                                       PyObject** payload_out,
                                       std::string* error_out) {
  if (payload_out) {
    *payload_out = nullptr;
  }
  const size_t dot1 = token.find('.');
  const size_t dot2 = dot1 == std::string::npos ? std::string::npos : token.find('.', dot1 + 1);
  if (dot1 == std::string::npos || dot2 == std::string::npos) {
    if (error_out) *error_out = "Malformed native grant token.";
    return false;
  }

  const std::string header_part = token.substr(0, dot1);
  const std::string payload_part = token.substr(dot1 + 1, dot2 - dot1 - 1);
  const std::string signature_part = token.substr(dot2 + 1);

  PyRef header_bytes(b64url_decode(header_part));
  PyRef payload_bytes(b64url_decode(payload_part));
  PyRef signature_bytes(b64url_decode(signature_part));
  if (!header_bytes || !payload_bytes || !signature_bytes) {
    if (error_out) *error_out = "Failed to decode native grant token.";
    PyErr_Clear();
    return false;
  }

  PyRef header_text(PyUnicode_FromEncodedObject(header_bytes.get(), "utf-8", "strict"));
  PyRef payload_text(PyUnicode_FromEncodedObject(payload_bytes.get(), "utf-8", "strict"));
  PyRef jwks_text(PyUnicode_FromStringAndSize(jwks_json.data(), static_cast<Py_ssize_t>(jwks_json.size())));
  if (!header_text || !payload_text || !jwks_text) {
    if (error_out) *error_out = "Failed to decode native grant JSON.";
    PyErr_Clear();
    return false;
  }

  PyRef header_obj(json_loads(header_text.get(), "Failed to parse native grant header"));
  PyRef payload_obj(json_loads(payload_text.get(), "Failed to parse native grant payload"));
  PyRef jwks_obj(json_loads(jwks_text.get(), "Failed to parse JWKS"));
  if (!header_obj || !payload_obj || !jwks_obj || !PyDict_Check(header_obj.get()) ||
      !PyDict_Check(payload_obj.get()) || !PyDict_Check(jwks_obj.get())) {
    if (error_out) *error_out = "Failed to parse native grant data.";
    PyErr_Clear();
    return false;
  }

  if (py_object_to_utf8(dict_get_item(header_obj.get(), "alg")) != "RS256") {
    if (error_out) *error_out = "Unsupported native grant algorithm.";
    return false;
  }

  const std::string expected_type_value = expected_type ? expected_type : "";
  if (!expected_type_value.empty() &&
      py_object_to_utf8(dict_get_item(payload_obj.get(), "typ")) != expected_type_value) {
    if (error_out) *error_out = "Unexpected native grant token type.";
    return false;
  }

  if (!jwt_audience_matches(dict_get_item(payload_obj.get(), "aud"), expected_audience)) {
    if (error_out) *error_out = "Native grant audience mismatch.";
    return false;
  }
  if (expected_issuer && expected_issuer[0] &&
      py_object_to_utf8(dict_get_item(payload_obj.get(), "iss")) != expected_issuer) {
    if (error_out) *error_out = "Native grant issuer mismatch.";
    return false;
  }

  const std::string kid = py_object_to_utf8(dict_get_item(header_obj.get(), "kid"));
  PyObject* keys_obj = dict_get_item(jwks_obj.get(), "keys");
  if (!keys_obj || !PySequence_Check(keys_obj)) {
    if (error_out) *error_out = "JWKS missing keys.";
    return false;
  }

  PyRef jwk_obj;
  const Py_ssize_t key_count = PySequence_Size(keys_obj);
  for (Py_ssize_t i = 0; i < key_count; ++i) {
    PyRef item(PySequence_GetItem(keys_obj, i));
    if (!item || !PyDict_Check(item.get())) {
      continue;
    }
    if (kid.empty() || py_object_to_utf8(dict_get_item(item.get(), "kid")) == kid) {
      jwk_obj = std::move(item);
      break;
    }
  }
  if (!jwk_obj && key_count == 1) {
    jwk_obj = PyRef(PySequence_GetItem(keys_obj, 0));
  }
  if (!jwk_obj || !PyDict_Check(jwk_obj.get())) {
    if (error_out) *error_out = "JWKS key not found for native grant.";
    return false;
  }

  PyRef modulus_bytes(b64url_decode(py_object_to_utf8(dict_get_item(jwk_obj.get(), "n"))));
  PyRef exponent_bytes(b64url_decode(py_object_to_utf8(dict_get_item(jwk_obj.get(), "e"))));
  PyRef modulus_int(py_int_from_bytes(modulus_bytes.get()));
  PyRef exponent_int(py_int_from_bytes(exponent_bytes.get()));
  PyRef signature_int(py_int_from_bytes(signature_bytes.get()));
  if (!modulus_int || !exponent_int || !signature_int) {
    if (error_out) *error_out = "Failed to decode JWKS key material.";
    PyErr_Clear();
    return false;
  }

  PyRef hashlib_module(PyImport_ImportModule("hashlib"));
  PyRef sha256_fn(hashlib_module ? PyObject_GetAttrString(hashlib_module.get(), "sha256") : nullptr);
  std::string signing_input = header_part + "." + payload_part;
  PyRef signing_bytes(
      PyBytes_FromStringAndSize(signing_input.data(), static_cast<Py_ssize_t>(signing_input.size())));
  if (!sha256_fn || !PyCallable_Check(sha256_fn.get()) || !signing_bytes) {
    if (error_out) *error_out = "Failed to initialize native grant verifier.";
    PyErr_Clear();
    return false;
  }
  PyRef sha_obj(PyObject_CallFunctionObjArgs(sha256_fn.get(), signing_bytes.get(), nullptr));
  PyRef digest_bytes(sha_obj ? PyObject_CallMethod(sha_obj.get(), "digest", nullptr) : nullptr);
  if (!digest_bytes) {
    if (error_out) *error_out = "Failed to hash native grant payload.";
    PyErr_Clear();
    return false;
  }

  static const unsigned char kDigestInfoPrefix[] = {
      0x30, 0x31, 0x30, 0x0D, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01,
      0x65, 0x03, 0x04, 0x02, 0x01, 0x05, 0x00, 0x04, 0x20,
  };
  char* digest_ptr = nullptr;
  Py_ssize_t digest_len = 0;
  if (PyBytes_AsStringAndSize(digest_bytes.get(), &digest_ptr, &digest_len) < 0 || !digest_ptr ||
      digest_len != 32) {
    if (error_out) *error_out = "Invalid native grant digest.";
    PyErr_Clear();
    return false;
  }

  char* modulus_ptr = nullptr;
  Py_ssize_t modulus_len = 0;
  if (PyBytes_AsStringAndSize(modulus_bytes.get(), &modulus_ptr, &modulus_len) < 0 || modulus_len <= 0) {
    if (error_out) *error_out = "Invalid RSA modulus.";
    PyErr_Clear();
    return false;
  }

  std::string padded;
  padded.push_back('\x00');
  padded.push_back('\x01');
  const size_t digest_info_len = sizeof(kDigestInfoPrefix) + static_cast<size_t>(digest_len);
  if (static_cast<size_t>(modulus_len) <= digest_info_len + 3) {
    if (error_out) *error_out = "RSA modulus too short.";
    return false;
  }
  padded.append(static_cast<size_t>(modulus_len) - digest_info_len - 3, '\xFF');
  padded.push_back('\x00');
  padded.append(reinterpret_cast<const char*>(kDigestInfoPrefix), sizeof(kDigestInfoPrefix));
  padded.append(digest_ptr, static_cast<size_t>(digest_len));

  PyRef expected_bytes(
      PyBytes_FromStringAndSize(padded.data(), static_cast<Py_ssize_t>(padded.size())));
  PyRef expected_int(py_int_from_bytes(expected_bytes.get()));
  PyRef decrypted_int(PyNumber_Power(signature_int.get(), exponent_int.get(), modulus_int.get()));
  if (!expected_int || !decrypted_int) {
    if (error_out) *error_out = "Failed to verify native grant signature.";
    PyErr_Clear();
    return false;
  }

  const int matches = PyObject_RichCompareBool(decrypted_int.get(), expected_int.get(), Py_EQ);
  if (matches != 1) {
    if (error_out) *error_out = "Native grant signature is invalid.";
    return false;
  }

  PyObject* exp_obj = dict_get_item(payload_obj.get(), "exp");
  const long long exp_value = exp_obj ? PyLong_AsLongLong(exp_obj) : 0;
  if (!exp_obj || PyErr_Occurred()) {
    if (error_out) *error_out = "Native grant missing expiration.";
    PyErr_Clear();
    return false;
  }
  if (exp_value <= static_cast<long long>(std::time(nullptr))) {
    if (error_out) *error_out = "Native grant expired. Sync your license.";
    return false;
  }

  if (payload_out) {
    *payload_out = payload_obj.release();
  }
  return true;
}

inline bool validate_native_manifest(PyObject* payload_obj, const std::string& addon_root,
                                     const std::string& module_path,
                                     const char* expected_feature_id,
                                     const char* expected_module_name,
                                     std::string* error_out) {
  if (!payload_obj || !PyDict_Check(payload_obj)) {
    if (error_out) *error_out = "Native grant payload is invalid.";
    return false;
  }
  if (py_object_to_utf8(dict_get_item(payload_obj, "feature_id")) !=
      std::string(expected_feature_id ? expected_feature_id : "")) {
    if (error_out) *error_out = "Native grant feature mismatch.";
    return false;
  }

  PyObject* py_manifest = dict_get_item(payload_obj, "py_manifest");
  PyObject* files_obj = py_manifest ? dict_get_item(py_manifest, "files") : nullptr;
  if (!files_obj || !PySequence_Check(files_obj)) {
    if (error_out) *error_out = "Native grant missing Python manifest.";
    return false;
  }
  const Py_ssize_t file_count = PySequence_Size(files_obj);
  for (Py_ssize_t i = 0; i < file_count; ++i) {
    PyRef item(PySequence_GetItem(files_obj, i));
    if (!item || !PyDict_Check(item.get())) {
      if (error_out) *error_out = "Python manifest entry is invalid.";
      return false;
    }
    const std::string relative_path = py_object_to_utf8(dict_get_item(item.get(), "path"));
    const std::string expected_sha = py_object_to_utf8(dict_get_item(item.get(), "sha256"));
    if (relative_path.empty() || expected_sha.empty()) {
      if (error_out) *error_out = "Python manifest entry is incomplete.";
      return false;
    }
    const std::string actual_sha = sha256_hex_file(addon_root + "/" + relative_path);
    if (actual_sha.empty()) {
      if (error_out) *error_out = "Failed to hash protected source file: " + relative_path;
      return false;
    }
    if (actual_sha != expected_sha) {
      if (error_out) *error_out = "Integrity check failed for " + relative_path + ".";
      return false;
    }
  }

  PyObject* artifact_manifest = dict_get_item(payload_obj, "artifact_manifest");
  if (!artifact_manifest || !PyDict_Check(artifact_manifest)) {
    if (error_out) *error_out = "Native grant missing artifact manifest.";
    return false;
  }
  if (py_object_to_utf8(dict_get_item(artifact_manifest, "module")) !=
      std::string(expected_module_name ? expected_module_name : "")) {
    if (error_out) *error_out = "Artifact manifest module mismatch.";
    return false;
  }
  const std::string expected_sha = py_object_to_utf8(dict_get_item(artifact_manifest, "artifact_sha256"));
  PyObject* size_obj = dict_get_item(artifact_manifest, "artifact_size");
  const long long expected_size = size_obj ? PyLong_AsLongLong(size_obj) : 0;
  if (module_path.empty() || expected_sha.empty() || expected_size <= 0) {
    if (error_out) *error_out = "Artifact manifest is incomplete.";
    PyErr_Clear();
    return false;
  }
  std::ifstream binary_input(module_path.c_str(), std::ios::binary | std::ios::ate);
  if (!binary_input) {
    if (error_out) *error_out = "Native binary path is unavailable for verification.";
    return false;
  }
  const long long actual_size = static_cast<long long>(binary_input.tellg());
  if (actual_size != expected_size) {
    if (error_out) *error_out = "Native binary size mismatch.";
    return false;
  }
  const std::string actual_sha = sha256_hex_file(module_path);
  if (actual_sha != expected_sha) {
    if (error_out) *error_out = "Native binary digest mismatch.";
    return false;
  }
  return true;
}

inline bool apply_native_grant(LicenseState* state, const char* grant_token, const char* jwks_json,
                               const char* addon_root, const char* module_path,
                               const char* expected_feature_id, const char* expected_module_name,
                               const char* audience = "rig2-native",
                               const char* issuer = "orbisauth-worker") {
  if (!state || !grant_token || !jwks_json || !addon_root || !module_path) {
    clear_license_state(state, "Native grant inputs are incomplete.");
    return false;
  }
  std::string verify_error;
  PyObject* payload_raw = nullptr;
  if (!verify_rs256_jwt_from_jwks(grant_token, jwks_json, audience, issuer, "native_grant",
                                  &payload_raw, &verify_error)) {
    clear_license_state(state, verify_error.c_str());
    return false;
  }
  PyRef payload(payload_raw);
  std::string integrity_error;
  if (!validate_native_manifest(payload.get(), addon_root, module_path, expected_feature_id,
                                expected_module_name, &integrity_error)) {
    clear_license_state(state, integrity_error.c_str());
    return false;
  }
  const std::string device_id = py_object_to_utf8(dict_get_item(payload.get(), "device_id"));
  PyObject* exp_obj = dict_get_item(payload.get(), "exp");
  const long long expires_at = exp_obj ? PyLong_AsLongLong(exp_obj) : 0;
  if (device_id.empty() || expires_at <= 0 || PyErr_Occurred()) {
    PyErr_Clear();
    clear_license_state(state, "Native grant missing required claims.");
    return false;
  }
  apply_authorized_license_state(state, device_id, expected_feature_id ? expected_feature_id : "",
                                 static_cast<int64_t>(expires_at));
  return true;
}

inline bool ensure_license_valid(LicenseState* state) {
  if (!state || !state->ok) {
    return false;
  }
  if (!state->integrity_ok) {
    clear_license_state(state, "Native integrity check failed. Reinstall the addon and binary.");
    return false;
  }
  if (state->expires_at > 0 && static_cast<int64_t>(std::time(nullptr)) >= state->expires_at) {
    clear_license_state(state, "Native grant expired. Sync your license.");
    return false;
  }
  if (state->device_id.empty() || state->feature_id.empty()) {
    clear_license_state(state, "Native grant is incomplete.");
    return false;
  }
  return true;
}

}  // namespace rig2_shared

#define RIG2_CHECK_LICENSE(state)                                                        \
  do {                                                                                   \
    if (!rig2_shared::ensure_license_valid(&(state))) {                                  \
      PyErr_SetString(PyExc_PermissionError, rig2_shared::license_error_message(state)); \
      return nullptr;                                                                    \
    }                                                                                    \
  } while (0)
