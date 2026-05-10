import re


BONE_DATA_PATH_RE = re.compile(r'pose\.bones\["([^"]+)"\]\.')


def get_action(armature):
    if not armature.animation_data:
        return None
    return armature.animation_data.action


def get_keyed_frames(action, source_bone_names):
    source_frames = set()
    action_frames = set()

    for fcurve in action.fcurves:
        match = BONE_DATA_PATH_RE.match(fcurve.data_path)
        for keyframe in fcurve.keyframe_points:
            frame_number = int(round(keyframe.co.x))
            action_frames.add(frame_number)
            if match and match.group(1) in source_bone_names:
                source_frames.add(frame_number)

    frames = source_frames or action_frames
    if not frames:
        return []

    first_frame = min(frames)
    last_frame = max(frames)
    return list(range(first_frame, last_frame + 1))
