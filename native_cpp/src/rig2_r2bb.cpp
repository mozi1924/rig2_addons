#include <Python.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include "shared.h"

namespace {

constexpr int kApiVersion = 1;

static rig2_shared::LicenseState g_license_state;

using rig2_shared::PyRef;

struct Entry {
  std::string base_bone;
  std::string mi_bone;
  std::string export_name;
  std::array<double, 3> rotation_axis_signs{{1.0, 1.0, 1.0}};
  std::array<double, 3> transform_axis_signs{{1.0, 1.0, 1.0}};
};

int axis_index(const std::string& axis) {
  if (axis == "X") return 0;
  if (axis == "Y") return 1;
  if (axis == "Z") return 2;
  return -1;
}

std::string py_string(PyObject* obj) {
  if (!obj) return "";
  PyRef str_obj(PyObject_Str(obj));
  if (!str_obj) return "";
  PyRef utf8_bytes(PyUnicode_AsEncodedString(str_obj.get(), "utf-8", "strict"));
  if (!utf8_bytes) return "";
  const char* raw = PyBytes_AsString(utf8_bytes.get());
  return raw ? std::string(raw) : std::string();
}

std::string trim(const std::string& value) {
  auto begin = std::find_if_not(value.begin(), value.end(), [](unsigned char c) { return std::isspace(c); });
  auto end = std::find_if_not(value.rbegin(), value.rend(), [](unsigned char c) { return std::isspace(c); }).base();
  if (begin >= end) return "";
  return std::string(begin, end);
}

double normalize_sign(PyObject* obj) {
  if (!obj) return 1.0;
  const double value = PyFloat_Check(obj) || PyLong_Check(obj) ? PyFloat_AsDouble(obj) : 1.0;
  return value < 0.0 ? -1.0 : 1.0;
}

std::array<double, 3> parse_axis_signs(PyObject* obj) {
  std::array<double, 3> signs{{1.0, 1.0, 1.0}};
  if (!obj || !PyDict_Check(obj)) {
    return signs;
  }

  PyObject* key = nullptr;
  PyObject* value = nullptr;
  Py_ssize_t pos = 0;
  while (PyDict_Next(obj, &pos, &key, &value)) {
    const int index = axis_index(py_string(key));
    if (index < 0) {
      continue;
    }
    signs[static_cast<size_t>(index)] = normalize_sign(value);
  }
  return signs;
}

bool parse_entry(PyObject* obj, Entry* out) {
  if (!out || !obj || !PyDict_Check(obj)) {
    return false;
  }

  Entry entry;
  entry.base_bone = trim(py_string(PyDict_GetItemString(obj, "base_bone")));
  entry.mi_bone = trim(py_string(PyDict_GetItemString(obj, "mi_bone")));
  entry.export_name = trim(py_string(PyDict_GetItemString(obj, "export_name")));
  if (entry.base_bone.empty() && entry.mi_bone.empty() && entry.export_name.empty()) {
    return false;
  }
  entry.rotation_axis_signs = parse_axis_signs(PyDict_GetItemString(obj, "rotation_axis_signs"));
  entry.transform_axis_signs = parse_axis_signs(PyDict_GetItemString(obj, "transform_axis_signs"));
  *out = std::move(entry);
  return true;
}

std::vector<Entry> normalize_entries(PyObject* entries_obj) {
  std::vector<Entry> entries;
  if (!entries_obj || !PySequence_Check(entries_obj)) {
    return entries;
  }

  const Py_ssize_t count = PySequence_Size(entries_obj);
  for (Py_ssize_t index = 0; index < count; ++index) {
    PyRef item(PySequence_GetItem(entries_obj, index));
    Entry entry;
    if (parse_entry(item.get(), &entry)) {
      entries.push_back(std::move(entry));
    }
  }
  return entries;
}

PyObject* build_axis_dict(const std::array<double, 3>& signs) {
  PyObject* result = PyDict_New();
  if (!result) return nullptr;
  PyDict_SetItemString(result, "X", PyFloat_FromDouble(signs[0]));
  PyDict_SetItemString(result, "Y", PyFloat_FromDouble(signs[1]));
  PyDict_SetItemString(result, "Z", PyFloat_FromDouble(signs[2]));
  return result;
}

PyObject* build_entry_dict(const Entry& entry) {
  PyObject* result = PyDict_New();
  if (!result) return nullptr;

  PyDict_SetItemString(result, "base_bone", PyUnicode_FromString(entry.base_bone.c_str()));
  PyDict_SetItemString(result, "mi_bone", PyUnicode_FromString(entry.mi_bone.c_str()));
  PyDict_SetItemString(result, "export_name", PyUnicode_FromString(entry.export_name.c_str()));
  PyRef rotation(build_axis_dict(entry.rotation_axis_signs));
  PyRef transform(build_axis_dict(entry.transform_axis_signs));
  if (!rotation || !transform) {
    Py_DECREF(result);
    return nullptr;
  }
  PyDict_SetItemString(result, "rotation_axis_signs", rotation.get());
  PyDict_SetItemString(result, "transform_axis_signs", transform.get());
  return result;
}

static PyObject* method_apply_native_grant(PyObject*, PyObject* args) {
  const char* grant_token = nullptr;
  const char* jwks_json = nullptr;
  const char* addon_root = nullptr;
  const char* module_path = nullptr;
  if (!PyArg_ParseTuple(args, "ssss:apply_native_grant", &grant_token, &jwks_json, &addon_root, &module_path)) {
    return nullptr;
  }

  rig2_shared::apply_native_grant(
      &g_license_state, grant_token, jwks_json, addon_root, module_path, "r2bb", "rig2_r2bb");
  Py_RETURN_NONE;
}

static PyObject* method_clear_license_state(PyObject*, PyObject*) {
  rig2_shared::clear_license_state(
      &g_license_state, "License required. Activate your license in Addon Preferences.");
  Py_RETURN_NONE;
}

static PyObject* method_get_license_status(PyObject*, PyObject*) {
  return rig2_shared::build_license_status(g_license_state);
}

static PyObject* method_backend_name(PyObject*, PyObject*) {
  return PyUnicode_FromString("native");
}

static PyObject* method_normalize_mapping_entries(PyObject*, PyObject* args) {
  RIG2_CHECK_LICENSE(g_license_state);
  PyObject* entries_obj = nullptr;
  if (!PyArg_ParseTuple(args, "O:normalize_mapping_entries", &entries_obj)) {
    return nullptr;
  }

  const std::vector<Entry> entries = normalize_entries(entries_obj);
  PyObject* result = PyList_New(static_cast<Py_ssize_t>(entries.size()));
  if (!result) return nullptr;
  for (Py_ssize_t index = 0; index < static_cast<Py_ssize_t>(entries.size()); ++index) {
    PyObject* entry_dict = build_entry_dict(entries[static_cast<size_t>(index)]);
    if (!entry_dict) {
      Py_DECREF(result);
      return nullptr;
    }
    PyList_SetItem(result, index, entry_dict);
  }
  return result;
}

static PyObject* method_mapping_entries_to_pairs(PyObject*, PyObject* args) {
  RIG2_CHECK_LICENSE(g_license_state);
  PyObject* entries_obj = nullptr;
  if (!PyArg_ParseTuple(args, "O:mapping_entries_to_pairs", &entries_obj)) {
    return nullptr;
  }

  const std::vector<Entry> entries = normalize_entries(entries_obj);
  PyObject* result = PyList_New(0);
  if (!result) return nullptr;
  for (const Entry& entry : entries) {
    if (entry.base_bone.empty() || entry.mi_bone.empty()) {
      continue;
    }
    PyRef pair(PyTuple_New(2));
    if (!pair) {
      Py_DECREF(result);
      return nullptr;
    }
    PyTuple_SetItem(pair.get(), 0, PyUnicode_FromString(entry.base_bone.c_str()));
    PyTuple_SetItem(pair.get(), 1, PyUnicode_FromString(entry.mi_bone.c_str()));
    PyList_Append(result, pair.get());
  }
  return result;
}

static PyObject* method_mapping_entries_to_export_bones(PyObject*, PyObject* args) {
  RIG2_CHECK_LICENSE(g_license_state);
  PyObject* entries_obj = nullptr;
  if (!PyArg_ParseTuple(args, "O:mapping_entries_to_export_bones", &entries_obj)) {
    return nullptr;
  }

  const std::vector<Entry> entries = normalize_entries(entries_obj);
  std::vector<std::string> export_bones;
  for (const Entry& entry : entries) {
    if (entry.mi_bone.empty()) continue;
    if (std::find(export_bones.begin(), export_bones.end(), entry.mi_bone) == export_bones.end()) {
      export_bones.push_back(entry.mi_bone);
    }
  }

  PyObject* result = PyList_New(static_cast<Py_ssize_t>(export_bones.size()));
  if (!result) return nullptr;
  for (Py_ssize_t index = 0; index < static_cast<Py_ssize_t>(export_bones.size()); ++index) {
    PyList_SetItem(result, index, PyUnicode_FromString(export_bones[static_cast<size_t>(index)].c_str()));
  }
  return result;
}

static PyObject* method_mapping_entries_to_export_name_map(PyObject*, PyObject* args) {
  RIG2_CHECK_LICENSE(g_license_state);
  PyObject* entries_obj = nullptr;
  if (!PyArg_ParseTuple(args, "O:mapping_entries_to_export_name_map", &entries_obj)) {
    return nullptr;
  }

  const std::vector<Entry> entries = normalize_entries(entries_obj);
  PyObject* result = PyDict_New();
  if (!result) return nullptr;
  for (const Entry& entry : entries) {
    if (entry.mi_bone.empty() || entry.export_name.empty()) continue;
    PyDict_SetItemString(result, entry.mi_bone.c_str(), PyUnicode_FromString(entry.export_name.c_str()));
  }
  return result;
}

static PyObject* build_axis_map(PyObject* entries_obj, bool rotation) {
  const std::vector<Entry> entries = normalize_entries(entries_obj);
  PyObject* result = PyDict_New();
  if (!result) return nullptr;
  for (const Entry& entry : entries) {
    if (entry.mi_bone.empty()) continue;
    PyRef axis_dict(build_axis_dict(rotation ? entry.rotation_axis_signs : entry.transform_axis_signs));
    if (!axis_dict) {
      Py_DECREF(result);
      return nullptr;
    }
    PyDict_SetItemString(result, entry.mi_bone.c_str(), axis_dict.get());
  }
  return result;
}

static PyObject* method_mapping_entries_to_rotation_axis_signs(PyObject*, PyObject* args) {
  RIG2_CHECK_LICENSE(g_license_state);
  PyObject* entries_obj = nullptr;
  if (!PyArg_ParseTuple(args, "O:mapping_entries_to_rotation_axis_signs", &entries_obj)) {
    return nullptr;
  }
  return build_axis_map(entries_obj, true);
}

static PyObject* method_mapping_entries_to_transform_axis_signs(PyObject*, PyObject* args) {
  RIG2_CHECK_LICENSE(g_license_state);
  PyObject* entries_obj = nullptr;
  if (!PyArg_ParseTuple(args, "O:mapping_entries_to_transform_axis_signs", &entries_obj)) {
    return nullptr;
  }
  return build_axis_map(entries_obj, false);
}

PyMethodDef kMethods[] = {
    {"backend_name", method_backend_name, METH_NOARGS, "Return backend name."},
    {"normalize_mapping_entries", method_normalize_mapping_entries, METH_VARARGS, "Normalize R2BB mapping entries."},
    {"mapping_entries_to_pairs", method_mapping_entries_to_pairs, METH_VARARGS, "Build base->MI bone pairs."},
    {"mapping_entries_to_export_bones", method_mapping_entries_to_export_bones, METH_VARARGS, "Build exported MI bone list."},
    {"mapping_entries_to_export_name_map", method_mapping_entries_to_export_name_map, METH_VARARGS, "Build MI->export name map."},
    {"mapping_entries_to_rotation_axis_signs", method_mapping_entries_to_rotation_axis_signs, METH_VARARGS, "Build MI rotation sign map."},
    {"mapping_entries_to_transform_axis_signs", method_mapping_entries_to_transform_axis_signs, METH_VARARGS, "Build MI transform sign map."},
    {"apply_native_grant", method_apply_native_grant, METH_VARARGS, "Apply a signed native grant token."},
    {"clear_license_state", method_clear_license_state, METH_NOARGS, "Clear the native license state."},
    {"get_license_status", method_get_license_status, METH_NOARGS, "Return native license status."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef kModuleDef = {
    PyModuleDef_HEAD_INIT,
    "rig2_r2bb",
    "Rig2 native R2BB backend.",
    -1,
    kMethods,
};

}  // namespace

PyMODINIT_FUNC PyInit_rig2_r2bb(void) {
  PyObject* module = PyModule_Create(&kModuleDef);
  if (!module) {
    return nullptr;
  }

  if (PyModule_AddIntConstant(module, "RIG2_R2BB_API_VERSION", kApiVersion) < 0) {
    Py_DECREF(module);
    return nullptr;
  }

  return module;
}
