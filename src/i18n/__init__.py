import bpy
import os
import json

translations_dict = {}

def load_translations():
    global translations_dict
    translations_dict.clear()
    
    i18n_dir = os.path.dirname(__file__)
    
    for filename in os.listdir(i18n_dir):
        if filename.endswith(".json"):
            lang = filename[:-5]
            filepath = os.path.join(i18n_dir, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                    translations_dict[lang] = {}
                    for msgid, msgstr in data.items():
                        # Support contextual translation format "context|msgid" (optional)
                        # but normally just fall back to wildcard
                        translations_dict[lang][("*", msgid)] = msgstr
                        translations_dict[lang][("Operator", msgid)] = msgstr
                except Exception as e:
                    print(f"Rig2 i18n Error loading {filename}: {e}")

def register():
    load_translations()
    try:
        bpy.app.translations.register(__name__, translations_dict)
    except ValueError:
        bpy.app.translations.unregister(__name__)
        bpy.app.translations.register(__name__, translations_dict)

def unregister():
    try:
        bpy.app.translations.unregister(__name__)
    except ValueError:
        pass
