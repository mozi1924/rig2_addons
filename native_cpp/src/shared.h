#pragma once

// ============================================================================
// Rig2 Shared — Pure utility helpers (no licensing, no validation)
// ============================================================================
//
// All functions live in the rig2_shared namespace and are header-only so
// every native module (.cpp) gets its own copy.
// ============================================================================

#include <Python.h>

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>

#if defined(_WIN32)
#include <windows.h>
#endif

namespace rig2_shared {

// ---------------------------------------------------------------------------
// Python API helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// UTF-8 file I/O (platform-aware)
// ---------------------------------------------------------------------------

inline std::string join_utf8_paths(std::string base_path, const std::string& relative_path) {
  if (base_path.empty()) {
    return relative_path;
  }
  const char tail = base_path.back();
#if defined(_WIN32)
  if (tail != '/' && tail != '\\') {
    base_path.push_back('\\');
  }
#else
  if (tail != '/') {
    base_path.push_back('/');
  }
#endif
  return base_path + relative_path;
}

#if defined(_WIN32)
inline std::wstring utf8_to_wstring(const std::string& text) {
  if (text.empty()) {
    return std::wstring();
  }
  const int required = MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, nullptr, 0);
  if (required <= 0) {
    return std::wstring();
  }
  std::wstring result(static_cast<size_t>(required - 1), L'\0');
  if (MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, result.data(), required) <= 0) {
    return std::wstring();
  }
  return result;
}
#endif

inline FILE* open_file_read_utf8(const std::string& path, bool binary) {
#if defined(_WIN32)
  const std::wstring wide_path = utf8_to_wstring(path);
  if (wide_path.empty()) {
    return nullptr;
  }
  return _wfopen(wide_path.c_str(), binary ? L"rb" : L"r");
#else
  return std::fopen(path.c_str(), binary ? "rb" : "r");
#endif
}

inline bool read_file_bytes_utf8(const std::string& path, std::string* out) {
  if (!out) {
    return false;
  }

  FILE* handle = open_file_read_utf8(path, true);
  if (!handle) {
    return false;
  }

  std::string data;
  char buffer[65536];
  size_t read_count = 0;
  while ((read_count = std::fread(buffer, 1, sizeof(buffer), handle)) > 0) {
    data.append(buffer, read_count);
  }
  const bool ok = std::ferror(handle) == 0;
  std::fclose(handle);
  if (!ok) {
    return false;
  }
  *out = std::move(data);
  return true;
}

inline bool get_file_size_utf8(const std::string& path, long long* size_out) {
  if (!size_out) {
    return false;
  }

  FILE* handle = open_file_read_utf8(path, true);
  if (!handle) {
    return false;
  }
  if (std::fseek(handle, 0, SEEK_END) != 0) {
    std::fclose(handle);
    return false;
  }
  const long long size = static_cast<long long>(std::ftell(handle));
  std::fclose(handle);
  if (size < 0) {
    return false;
  }
  *size_out = size;
  return true;
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
  static PyObject* loads_fn = nullptr;
  if (!loads_fn) {
    PyRef json_module(PyImport_ImportModule("json"));
    if (!json_module) {
      return nullptr;
    }

    PyObject* resolved = PyObject_GetAttrString(json_module.get(), "loads");
    if (!resolved || !PyCallable_Check(resolved)) {
      Py_XDECREF(resolved);
      PyErr_SetString(PyExc_RuntimeError,
                      failure_message ? failure_message : "Failed to resolve json.loads");
      return nullptr;
    }
    loads_fn = resolved;
  }

  return PyObject_CallFunctionObjArgs(loads_fn, input_text, nullptr);
}

inline std::string json_dumps(PyObject* obj) {
  if (!obj) {
    return std::string();
  }
  static PyObject* dumps_fn = nullptr;
  if (!dumps_fn) {
    PyRef json_module(PyImport_ImportModule("json"));
    if (!json_module) {
      PyErr_Clear();
      return std::string();
    }

    PyObject* resolved = PyObject_GetAttrString(json_module.get(), "dumps");
    if (!resolved || !PyCallable_Check(resolved)) {
      Py_XDECREF(resolved);
      PyErr_Clear();
      return std::string();
    }
    dumps_fn = resolved;
  }

  PyRef dumped(PyObject_CallFunctionObjArgs(dumps_fn, obj, nullptr));
  if (!dumped) {
    PyErr_Clear();
    return std::string();
  }
  return py_object_to_utf8(dumped.get());
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

}  // namespace rig2_shared
