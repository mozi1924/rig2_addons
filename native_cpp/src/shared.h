#pragma once

#include <Python.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

namespace rig2_shared {

struct LicenseState {
  int ok = 0;
  int64_t expires_at = 0;
  std::string error;
};

inline void set_license_error(LicenseState* state, const std::string& message) {
  if (state) {
    state->error = message;
  }
}

inline bool hmac_sha256_verify(const unsigned char (&secret)[32], const char* device_id,
                               int64_t expires_at, const char* hmac_hex) {
  if (!device_id || !hmac_hex) {
    return false;
  }

  char msg[512];
  const int msg_len = snprintf(msg, sizeof(msg), "%s:%lld", device_id,
                               static_cast<long long>(expires_at));
  if (msg_len <= 0 || msg_len >= static_cast<int>(sizeof(msg))) {
    return false;
  }

  PyObject* hmac_mod = PyImport_ImportModule("hmac");
  if (!hmac_mod) {
    PyErr_Clear();
    return false;
  }

  PyObject* secret_bytes =
      PyBytes_FromStringAndSize(reinterpret_cast<const char*>(secret), 32);
  if (!secret_bytes) {
    Py_DECREF(hmac_mod);
    PyErr_Clear();
    return false;
  }

  PyObject* msg_bytes = PyBytes_FromStringAndSize(msg, msg_len);
  if (!msg_bytes) {
    Py_DECREF(secret_bytes);
    Py_DECREF(hmac_mod);
    PyErr_Clear();
    return false;
  }

  PyObject* hmac_new = PyObject_GetAttrString(hmac_mod, "new");
  if (!hmac_new) {
    Py_DECREF(msg_bytes);
    Py_DECREF(secret_bytes);
    Py_DECREF(hmac_mod);
    PyErr_Clear();
    return false;
  }

  PyObject* sha256_str = PyUnicode_FromString("sha256");
  if (!sha256_str) {
    Py_DECREF(hmac_new);
    Py_DECREF(msg_bytes);
    Py_DECREF(secret_bytes);
    Py_DECREF(hmac_mod);
    PyErr_Clear();
    return false;
  }

  PyObject* new_args = Py_BuildValue("(O,O)", secret_bytes, msg_bytes);
  PyObject* new_kw = Py_BuildValue("{s:O}", "digestmod", sha256_str);
  PyObject* hmac_obj = PyObject_Call(hmac_new, new_args, new_kw);
  Py_DECREF(new_kw);
  Py_DECREF(new_args);
  Py_DECREF(sha256_str);
  Py_DECREF(hmac_new);
  Py_DECREF(msg_bytes);
  Py_DECREF(secret_bytes);

  if (!hmac_obj) {
    Py_DECREF(hmac_mod);
    PyErr_Clear();
    return false;
  }

  PyObject* computed_hex = PyObject_CallMethod(hmac_obj, "hexdigest", nullptr);
  Py_DECREF(hmac_obj);
  Py_DECREF(hmac_mod);
  if (!computed_hex) {
    PyErr_Clear();
    return false;
  }

  PyObject* computed_utf8 =
      PyUnicode_AsEncodedString(computed_hex, "utf-8", "strict");
  Py_DECREF(computed_hex);
  if (!computed_utf8) {
    return false;
  }

  const char* computed_str = PyBytes_AsString(computed_utf8);
  const bool match = computed_str && strcmp(computed_str, hmac_hex) == 0;
  Py_DECREF(computed_utf8);
  return match;
}

inline void apply_license_state(LicenseState* state, bool authorized, int64_t expires_at,
                                const char* failure_message) {
  if (!state) {
    return;
  }

  if (authorized) {
    state->ok = 1;
    state->expires_at = expires_at;
    set_license_error(state, "");
  } else {
    state->ok = 0;
    state->expires_at = 0;
    set_license_error(state, failure_message ? failure_message : "");
  }
}

inline bool verify_integrity_hashes(PyObject* hashes_dict, const char* const* expected_hashes,
                                    const char* module_name, LicenseState* state) {
  if (!hashes_dict || !PyDict_Check(hashes_dict) || !expected_hashes || !module_name ||
      !state) {
    return false;
  }

  for (int i = 0; expected_hashes[i] != nullptr; i += 2) {
    const char* fname = expected_hashes[i];
    const char* expected = expected_hashes[i + 1];
    if (!expected || !expected[0]) {
      continue;
    }

    PyObject* actual = PyDict_GetItemString(hashes_dict, fname);
    if (!actual) {
      set_license_error(
          state, std::string(module_name) + " integrity check failed: missing hash for " +
                     fname + ".");
      state->ok = 0;
      state->expires_at = 0;
      return false;
    }

    PyObject* actual_utf8 = PyUnicode_AsEncodedString(actual, "utf-8", "strict");
    if (!actual_utf8) {
      set_license_error(state,
                        std::string(module_name) +
                            " integrity check failed while reading hash for " + fname + ".");
      state->ok = 0;
      state->expires_at = 0;
      return false;
    }

    const char* actual_str = PyBytes_AsString(actual_utf8);
    const bool matches = actual_str && strcmp(actual_str, expected) == 0;
    Py_DECREF(actual_utf8);
    if (!matches) {
      set_license_error(
          state, std::string(module_name) + " integrity check failed: " + fname +
                     " does not match the binary build. Rebuild or reinstall the native binary.");
      state->ok = 0;
      state->expires_at = 0;
      return false;
    }
  }

  return true;
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

}  // namespace rig2_shared

#define RIG2_CHECK_LICENSE(state)                                                        \
  do {                                                                                   \
    if (!(state).ok) {                                                                   \
      PyErr_SetString(PyExc_PermissionError, rig2_shared::license_error_message(state)); \
      return nullptr;                                                                    \
    }                                                                                    \
  } while (0)
