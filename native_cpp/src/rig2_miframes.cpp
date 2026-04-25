#include <Python.h>

#include <algorithm>
#include <cctype>
#include <string>

namespace {

constexpr int kApiVersion = 1;

PyObject* g_models = nullptr;

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

const char* kModelsJson = R"JSON({
  "steve": {
    "name": "Rig2 Steve (MI Direct)",
    "bones": {
      "root": {
        "target_rot": "MI_Root",
        "target_pos_scl": "MI_Root",
        "handler_rot": "standard",
        "handler_pos_scl": "pos_scl",
        "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"}
      },
      "head": {
        "target_rot": "MI_Head",
        "target_pos_scl": "MI_P_Head",
        "handler_rot": "standard",
        "handler_pos_scl": "pos_scl",
        "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"}
      },
      "body": {
        "target_rot": "MI_Body Lower",
        "target_pos_scl": "MI_Body",
        "handler_rot": "standard",
        "handler_pos_scl": "pos_scl",
        "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"}
      },
      "left_arm": {
        "target_rot": "MI_arm.upper.L",
        "target_pos_scl": "MI_arm.L",
        "handler_rot": "standard",
        "handler_pos_scl": "pos_scl",
        "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"}
      },
      "right_arm": {
        "target_rot": "MI_arm.upper.R",
        "target_pos_scl": "MI_arm.R",
        "handler_rot": "standard",
        "handler_pos_scl": "pos_scl",
        "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"}
      },
      "left_leg": {
        "target_rot": "MI_leg.upper.L",
        "target_pos_scl": "MI_leg.L",
        "handler_rot": "standard",
        "handler_pos_scl": "pos_scl",
        "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"},
        "axis_scale": {"X": 1.0, "Y": -1.0, "Z": -1.0}
      },
      "right_leg": {
        "target_rot": "MI_leg.upper.R",
        "target_pos_scl": "MI_leg.R",
        "handler_rot": "standard",
        "handler_pos_scl": "pos_scl",
        "axis_map": {"X": "ROT_X", "Y": "ROT_Y", "Z": "ROT_Z"},
        "axis_scale": {"X": 1.0, "Y": -1.0, "Z": -1.0}
      }
    },
    "bend_targets": {
      "left_arm": "MI_arm.lower.L",
      "right_arm": "MI_arm.lower.R",
      "left_leg": "MI_leg.lower.L",
      "right_leg": "MI_leg.lower.R",
      "body": "MI_Body Upper"
    },
    "ik_targets": {
      "left_arm": {
        "ik_target_bone": "MI_arm.ik.target.L",
        "ik_pole_bone": "MI_arm.ik.pt.L",
        "logic_ik_prop": "mi_ik_arm.L"
      },
      "right_arm": {
        "ik_target_bone": "MI_arm.ik.target.R",
        "ik_pole_bone": "MI_arm.ik.pt.R",
        "logic_ik_prop": "mi_ik_arm.R"
      },
      "left_leg": {
        "ik_target_bone": "MI_leg.ik.target.L",
        "ik_pole_bone": "MI_leg.ik.pt.L",
        "logic_ik_prop": "mi_ik_leg.L"
      },
      "right_leg": {
        "ik_target_bone": "MI_leg.ik.target.R",
        "ik_pole_bone": "MI_leg.ik.pt.R",
        "logic_ik_prop": "mi_ik_leg.R"
      }
    }
  }
})JSON";

PyObject* dict_get_item(PyObject* dict_obj, const char* key) {
  if (!dict_obj || !PyDict_Check(dict_obj)) {
    return nullptr;
  }
  return PyDict_GetItemString(dict_obj, key);
}

double object_to_double_or(PyObject* value, double fallback) {
  if (!value) {
    return fallback;
  }
  double out = PyFloat_AsDouble(value);
  if (PyErr_Occurred()) {
    PyErr_Clear();
    return fallback;
  }
  return out;
}

std::string normalize_part_name_impl(PyObject* part_name_obj) {
  if (!part_name_obj) {
    return "root";
  }

  PyRef as_str(PyObject_Str(part_name_obj));
  if (!as_str || !PyUnicode_Check(as_str.get())) {
    PyErr_Clear();
    return "root";
  }

  PyRef utf8_bytes(PyUnicode_AsUTF8String(as_str.get()));
  if (!utf8_bytes) {
    PyErr_Clear();
    return "root";
  }
  const char* utf8 = PyBytes_AsString(utf8_bytes.get());
  if (!utf8) {
    PyErr_Clear();
    return "root";
  }

  std::string normalized(utf8);
  auto not_space = [](unsigned char c) { return !std::isspace(c); };
  normalized.erase(normalized.begin(), std::find_if(normalized.begin(), normalized.end(), not_space));
  normalized.erase(
      std::find_if(normalized.rbegin(), normalized.rend(), not_space).base(),
      normalized.end());

  std::transform(
      normalized.begin(), normalized.end(), normalized.begin(),
      [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

  if (normalized.empty()) {
    return "root";
  }
  return normalized;
}

PyObject* build_transition_info(PyObject* values) {
  PyRef transition(PyDict_New());
  if (!transition) {
    return nullptr;
  }

  PyObject* transition_type = dict_get_item(values, "TRANSITION");
  if (transition_type) {
    Py_INCREF(transition_type);
  } else {
    transition_type = PyUnicode_FromString("linear");
    if (!transition_type) {
      return nullptr;
    }
  }

  if (PyDict_SetItemString(transition.get(), "type", transition_type) < 0) {
    Py_DECREF(transition_type);
    return nullptr;
  }
  Py_DECREF(transition_type);

  const double ease_in_x = object_to_double_or(dict_get_item(values, "EASE_IN_X"), 1.0);
  const double ease_in_y = object_to_double_or(dict_get_item(values, "EASE_IN_Y"), 0.0);
  const double ease_out_x = object_to_double_or(dict_get_item(values, "EASE_OUT_X"), 0.0);
  const double ease_out_y = object_to_double_or(dict_get_item(values, "EASE_OUT_Y"), 1.0);

  PyRef ease_in(PyTuple_New(2));
  PyRef ease_out(PyTuple_New(2));
  if (!ease_in || !ease_out) {
    return nullptr;
  }

  if (PyTuple_SetItem(ease_in.get(), 0, PyFloat_FromDouble(ease_in_x)) < 0 ||
      PyTuple_SetItem(ease_in.get(), 1, PyFloat_FromDouble(ease_in_y)) < 0 ||
      PyTuple_SetItem(ease_out.get(), 0, PyFloat_FromDouble(ease_out_x)) < 0 ||
      PyTuple_SetItem(ease_out.get(), 1, PyFloat_FromDouble(ease_out_y)) < 0) {
    return nullptr;
  }

  if (PyDict_SetItemString(transition.get(), "ease_in", ease_in.get()) < 0 ||
      PyDict_SetItemString(transition.get(), "ease_out", ease_out.get()) < 0) {
    return nullptr;
  }

  return transition.release();
}

int append_transition(PyObject* transitions, PyObject* bone_name, double time, PyObject* transition) {
  if (!bone_name) {
    return 0;
  }

  const int is_truthy = PyObject_IsTrue(bone_name);
  if (is_truthy < 0) {
    return -1;
  }
  if (!is_truthy) {
    return 0;
  }

  PyObject* bucket = PyDict_GetItemWithError(transitions, bone_name);
  if (!bucket) {
    if (PyErr_Occurred()) {
      return -1;
    }
    PyRef new_bucket(PyList_New(0));
    if (!new_bucket) {
      return -1;
    }
    if (PyDict_SetItem(transitions, bone_name, new_bucket.get()) < 0) {
      return -1;
    }
    bucket = PyDict_GetItemWithError(transitions, bone_name);
    if (!bucket) {
      return -1;
    }
  }

  PyRef item(PyTuple_New(2));
  if (!item) {
    return -1;
  }
  if (PyTuple_SetItem(item.get(), 0, PyFloat_FromDouble(time)) < 0) {
    return -1;
  }
  Py_INCREF(transition);
  if (PyTuple_SetItem(item.get(), 1, transition) < 0) {
    Py_DECREF(transition);
    return -1;
  }

  if (PyList_Append(bucket, item.get()) < 0) {
    return -1;
  }
  return 0;
}

int seed_transition_bucket(PyObject* transitions, PyObject* bone_name) {
  if (!bone_name) {
    return 0;
  }
  const int is_truthy = PyObject_IsTrue(bone_name);
  if (is_truthy < 0) {
    return -1;
  }
  if (!is_truthy) {
    return 0;
  }

  PyObject* bucket = PyDict_GetItemWithError(transitions, bone_name);
  if (bucket) {
    return 0;
  }
  if (PyErr_Occurred()) {
    return -1;
  }

  PyRef new_bucket(PyList_New(0));
  if (!new_bucket) {
    return -1;
  }
  if (PyDict_SetItem(transitions, bone_name, new_bucket.get()) < 0) {
    return -1;
  }
  return 0;
}

int preseed_transition_buckets(PyObject* transitions, PyObject* bones_cfg, PyObject* bend_cfg) {
  Py_ssize_t pos = 0;
  PyObject* part_name = nullptr;
  PyObject* bone_cfg = nullptr;
  while (PyDict_Next(bones_cfg, &pos, &part_name, &bone_cfg)) {
    if (!bone_cfg || !PyDict_Check(bone_cfg)) {
      continue;
    }
    PyObject* rot_target = dict_get_item(bone_cfg, "target_rot");
    PyObject* pos_target = dict_get_item(bone_cfg, "target_pos_scl");
    PyObject* target = dict_get_item(bone_cfg, "target");
    if (seed_transition_bucket(transitions, rot_target) < 0 ||
        seed_transition_bucket(transitions, pos_target) < 0 ||
        seed_transition_bucket(transitions, target) < 0) {
      return -1;
    }
  }

  pos = 0;
  PyObject* bend_part = nullptr;
  PyObject* bend_target = nullptr;
  while (PyDict_Next(bend_cfg, &pos, &bend_part, &bend_target)) {
    if (seed_transition_bucket(transitions, bend_target) < 0) {
      return -1;
    }
  }
  return 0;
}

int append_operation_item(PyObject* operations, Py_ssize_t* write_index, PyObject* op) {
  const Py_ssize_t preallocated = PyList_Size(operations);
  if (*write_index < preallocated) {
    if (PyList_SetItem(operations, *write_index, op) < 0) {  // steals `op`
      return -1;
    }
    *write_index += 1;
    return 0;
  }

  if (PyList_Append(operations, op) < 0) {
    Py_DECREF(op);
    return -1;
  }
  Py_DECREF(op);
  *write_index += 1;
  return 0;
}

int append_operation(
    PyObject* operations,
    Py_ssize_t* write_index,
    double time,
    PyObject* part_name,
    PyObject* values,
    PyObject* bone_name,
    PyObject* handler_kind,
    PyObject* handler_name) {
  PyRef op(PyDict_New());
  if (!op) {
    return -1;
  }

  PyRef time_value(PyFloat_FromDouble(time));
  if (!time_value) {
    return -1;
  }
  if (PyDict_SetItemString(op.get(), "time", time_value.get()) < 0) {
    return -1;
  }
  if (PyDict_SetItemString(op.get(), "part_name", part_name) < 0) {
    return -1;
  }
  if (PyDict_SetItemString(op.get(), "values", values) < 0) {
    return -1;
  }
  if (PyDict_SetItemString(op.get(), "bone_name", bone_name) < 0) {
    return -1;
  }

  if (PyDict_SetItemString(op.get(), "handler_kind", handler_kind) < 0) {
    return -1;
  }

  if (!handler_name) {
    handler_name = Py_None;
  }
  if (PyDict_SetItemString(op.get(), "handler_name", handler_name) < 0) {
    return -1;
  }

  return append_operation_item(operations, write_index, op.release());
}

PyObject* normalize_part_name_cached(PyObject* cache, PyObject* part_name_obj) {
  PyObject* cache_key = part_name_obj ? part_name_obj : Py_None;
  PyObject* cached = PyDict_GetItemWithError(cache, cache_key);
  if (cached) {
    Py_INCREF(cached);
    return cached;
  }
  if (PyErr_Occurred()) {
    PyErr_Clear();
  }

  const std::string normalized = normalize_part_name_impl(part_name_obj);
  PyRef normalized_obj(PyUnicode_FromString(normalized.c_str()));
  if (!normalized_obj) {
    return nullptr;
  }

  if (PyDict_SetItem(cache, cache_key, normalized_obj.get()) < 0) {
    PyErr_Clear();
  }
  return normalized_obj.release();
}

PyObject* get_dict_or_empty(PyObject* obj, const char* key) {
  PyObject* value = dict_get_item(obj, key);
  if (value && PyDict_Check(value)) {
    Py_INCREF(value);
    return value;
  }
  return PyDict_New();
}

int init_models_cache() {
  if (g_models) {
    return 0;
  }

  PyRef json_module(PyImport_ImportModule("json"));
  if (!json_module) {
    return -1;
  }

  PyRef loads_fn(PyObject_GetAttrString(json_module.get(), "loads"));
  if (!loads_fn || !PyCallable_Check(loads_fn.get())) {
    PyErr_SetString(PyExc_RuntimeError, "Failed to resolve json.loads for rig2_miframes.");
    return -1;
  }

  PyRef json_text(PyUnicode_FromString(kModelsJson));
  if (!json_text) {
    return -1;
  }

  PyRef models(PyObject_CallFunctionObjArgs(loads_fn.get(), json_text.get(), nullptr));
  if (!models || !PyDict_Check(models.get())) {
    PyErr_SetString(PyExc_RuntimeError, "Failed to parse internal model registry.");
    return -1;
  }

  g_models = models.release();
  return 0;
}

PyObject* method_backend_name(PyObject*, PyObject*) {
  return PyUnicode_FromString("rig2_miframes_cpp");
}

PyObject* method_get_models(PyObject*, PyObject*) {
  if (init_models_cache() < 0) {
    return nullptr;
  }
  Py_INCREF(g_models);
  return g_models;
}

PyObject* method_get_model_config(PyObject*, PyObject* args) {
  PyObject* model_key = nullptr;
  if (!PyArg_ParseTuple(args, "O:get_model_config", &model_key)) {
    return nullptr;
  }

  if (init_models_cache() < 0) {
    return nullptr;
  }

  PyObject* value = PyDict_GetItemWithError(g_models, model_key);
  if (!value) {
    if (PyErr_Occurred()) {
      return nullptr;
    }
    Py_RETURN_NONE;
  }

  Py_INCREF(value);
  return value;
}

PyObject* method_plan_miframes_keyframe_ops(PyObject*, PyObject* args) {
  PyObject* data = nullptr;
  PyObject* config = nullptr;
  double start_frame = 0.0;
  double fps_scale = 1.0;

  if (!PyArg_ParseTuple(
          args,
          "OOdd:plan_miframes_keyframe_ops",
          &data,
          &config,
          &start_frame,
          &fps_scale)) {
    return nullptr;
  }

  PyRef bones_cfg(get_dict_or_empty(config, "bones"));
  PyRef bend_cfg(get_dict_or_empty(config, "bend_targets"));
  if (!bones_cfg || !bend_cfg) {
    return nullptr;
  }

  PyObject* keyframes = dict_get_item(data, "keyframes");
  if (!keyframes || !PyList_Check(keyframes)) {
    keyframes = PyList_New(0);
    if (!keyframes) {
      return nullptr;
    }
  } else {
    Py_INCREF(keyframes);
  }
  PyRef keyframes_holder(keyframes);

  const Py_ssize_t keyframe_count = PyList_Size(keyframes);
  const Py_ssize_t estimated_operation_count = keyframe_count > 0 ? keyframe_count * 3 : 0;

  PyRef operations(PyList_New(estimated_operation_count));
  PyRef transitions(PyDict_New());
  PyRef part_name_cache(PyDict_New());
  if (!operations || !transitions || !part_name_cache) {
    return nullptr;
  }
  if (preseed_transition_buckets(transitions.get(), bones_cfg.get(), bend_cfg.get()) < 0) {
    return nullptr;
  }

  PyRef kind_rot(PyUnicode_FromString("rot"));
  PyRef kind_pos_scl(PyUnicode_FromString("pos_scl"));
  PyRef kind_bend(PyUnicode_FromString("bend"));
  PyRef handler_standard(PyUnicode_FromString("standard"));
  PyRef handler_pos_scl(PyUnicode_FromString("pos_scl"));
  PyRef handler_bend(PyUnicode_FromString("bend"));
  if (!kind_rot || !kind_pos_scl || !kind_bend || !handler_standard || !handler_pos_scl || !handler_bend) {
    return nullptr;
  }

  Py_ssize_t operation_write_index = 0;
  for (Py_ssize_t i = 0; i < keyframe_count; ++i) {
    PyObject* keyframe = PyList_GetItem(keyframes, i);
    if (!keyframe || !PyDict_Check(keyframe)) {
      continue;
    }

    PyObject* position_obj = dict_get_item(keyframe, "position");
    PyObject* part_name_obj = dict_get_item(keyframe, "part_name");
    PyObject* values = dict_get_item(keyframe, "values");

    const double position = object_to_double_or(position_obj, 0.0);
    const double time = start_frame + (position * fps_scale);

    PyRef part_name(normalize_part_name_cached(part_name_cache.get(), part_name_obj));
    if (!part_name) {
      return nullptr;
    }

    PyRef values_holder;
    if (!values || !PyDict_Check(values)) {
      values_holder = PyRef(PyDict_New());
      if (!values_holder) {
        return nullptr;
      }
      values = values_holder.get();
    }

    PyRef transition(build_transition_info(values));
    if (!transition) {
      return nullptr;
    }

    PyObject* bone_cfg = PyDict_GetItemWithError(bones_cfg.get(), part_name.get());
    if (bone_cfg && PyDict_Check(bone_cfg)) {
      PyObject* rot_target = dict_get_item(bone_cfg, "target_rot");
      PyObject* pos_target = dict_get_item(bone_cfg, "target_pos_scl");
      PyObject* target = dict_get_item(bone_cfg, "target");
      PyObject* handler_rot = dict_get_item(bone_cfg, "handler_rot");
      PyObject* handler_pos = dict_get_item(bone_cfg, "handler_pos_scl");

      if (append_transition(transitions.get(), rot_target, time, transition.get()) < 0 ||
          append_transition(transitions.get(), pos_target, time, transition.get()) < 0 ||
          append_transition(transitions.get(), target, time, transition.get()) < 0) {
        return nullptr;
      }

      if (rot_target) {
        const int truthy = PyObject_IsTrue(rot_target);
        if (truthy < 0) {
          return nullptr;
        }
        if (truthy) {
          PyObject* handler_name = handler_rot ? handler_rot : handler_standard.get();
          if (append_operation(
                  operations.get(),
                  &operation_write_index,
                  time,
                  part_name.get(),
                  values,
                  rot_target,
                  kind_rot.get(),
                  handler_name) < 0) {
            return nullptr;
          }
        }
      }

      if (pos_target) {
        const int truthy = PyObject_IsTrue(pos_target);
        if (truthy < 0) {
          return nullptr;
        }
        if (truthy) {
          PyObject* handler_name = handler_pos ? handler_pos : handler_pos_scl.get();
          if (append_operation(
                  operations.get(),
                  &operation_write_index,
                  time,
                  part_name.get(),
                  values,
                  pos_target,
                  kind_pos_scl.get(),
                  handler_name) < 0) {
            return nullptr;
          }
        }
      }
    }

    PyObject* bend_target = PyDict_GetItemWithError(bend_cfg.get(), part_name.get());
    if (bend_target) {
      const int truthy = PyObject_IsTrue(bend_target);
      if (truthy < 0) {
        return nullptr;
      }
      if (truthy) {
        if (append_transition(transitions.get(), bend_target, time, transition.get()) < 0) {
          return nullptr;
        }
        if (append_operation(
                operations.get(),
                &operation_write_index,
                time,
                part_name.get(),
                values,
                bend_target,
                kind_bend.get(),
                handler_bend.get()) < 0) {
          return nullptr;
        }
      }
    }
  }

  if (operation_write_index < estimated_operation_count) {
    if (PyList_SetSlice(operations.get(), operation_write_index, estimated_operation_count, nullptr) < 0) {
      return nullptr;
    }
  }

  PyRef result(PyDict_New());
  if (!result) {
    return nullptr;
  }

  if (PyDict_SetItemString(result.get(), "operations", operations.get()) < 0 ||
      PyDict_SetItemString(result.get(), "transitions", transitions.get()) < 0) {
    return nullptr;
  }

  return result.release();
}

PyMethodDef kMethods[] = {
    {"backend_name", method_backend_name, METH_NOARGS, "Return native backend name."},
    {"get_models", method_get_models, METH_NOARGS, "Return model registry."},
    {"get_model_config", method_get_model_config, METH_VARARGS, "Return one model config."},
    {
        "plan_miframes_keyframe_ops",
        method_plan_miframes_keyframe_ops,
        METH_VARARGS,
        "Plan miframes keyframe operations.",
    },
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef kModuleDef = {
    PyModuleDef_HEAD_INIT,
    "rig2_miframes",
    "Rig2 native miframes backend.",
    -1,
    kMethods,
};

}  // namespace

PyMODINIT_FUNC PyInit_rig2_miframes(void) {
  PyObject* module = PyModule_Create(&kModuleDef);
  if (!module) {
    return nullptr;
  }

  if (PyModule_AddIntConstant(module, "RIG2_MIFRAMES_API_VERSION", kApiVersion) < 0) {
    Py_DECREF(module);
    return nullptr;
  }

  if (init_models_cache() < 0) {
    Py_DECREF(module);
    return nullptr;
  }

  return module;
}
