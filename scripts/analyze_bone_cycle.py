import bpy
from collections import defaultdict


ARMATURE_CANDIDATES = [
    "OBRig2 Armature",
    "Rig2 Armature",
]
FOCUS_BONES = {
    "Head root",
    "Face_BlendShapes",
    "crontrol",
    "Crontrol Location point.001",
    "logo",
}


def constraint_target_bones(constraint, armature_obj):
    refs = []
    target = getattr(constraint, "target", None)
    subtarget = getattr(constraint, "subtarget", "")
    if target == armature_obj and subtarget:
        refs.append((subtarget, f"{constraint.type}:{constraint.name}"))

    if hasattr(constraint, "targets"):
        for idx, item in enumerate(constraint.targets):
            tgt = getattr(item, "target", None)
            sub = getattr(item, "subtarget", "")
            if tgt == armature_obj and sub:
                refs.append((sub, f"{constraint.type}:{constraint.name}[{idx}]"))
    return refs


def build_graph(armature_obj):
    graph = defaultdict(list)
    pose_bones = armature_obj.pose.bones

    for pb in pose_bones:
        if pb.parent:
            graph[pb.name].append((pb.parent.name, "pose_parent"))
            graph[pb.parent.name].append((pb.name, "child"))

        for con in pb.constraints:
            for target_name, label in constraint_target_bones(con, armature_obj):
                graph[pb.name].append((target_name, label))
    return graph


def find_cycles(graph, focus_only=None, max_depth=12):
    cycles = []
    seen = set()

    def dfs(start, node, path_nodes, path_edges, visited):
        if len(path_nodes) > max_depth:
            return
        for nxt, label in graph.get(node, []):
            if focus_only and nxt not in focus_only and node not in focus_only:
                continue
            if nxt == start and len(path_nodes) > 1:
                cycle_nodes = tuple(path_nodes + [start])
                key = min(
                    tuple(cycle_nodes[i:-1] + cycle_nodes[:i] + (start,))
                    for i in range(len(cycle_nodes) - 1)
                )
                if key not in seen:
                    seen.add(key)
                    cycles.append((path_nodes + [start], path_edges + [label]))
            elif nxt not in visited:
                dfs(
                    start,
                    nxt,
                    path_nodes + [nxt],
                    path_edges + [label],
                    visited | {nxt},
                )

    starts = focus_only or set(graph.keys())
    for start in starts:
        dfs(start, start, [start], [], {start})
    return cycles


def print_bone_details(armature_obj):
    print(f"Armature: {armature_obj.name}")
    for bone_name in sorted(FOCUS_BONES):
        pb = armature_obj.pose.bones.get(bone_name)
        if not pb:
            print(f"\n[BONE] {bone_name} (missing)")
            continue
        print(f"\n[BONE] {pb.name}")
        print(f"  parent: {pb.parent.name if pb.parent else '<none>'}")
        children = [child.name for child in pb.children]
        print(f"  children: {children if children else '<none>'}")
        if not pb.constraints:
            print("  constraints: <none>")
        else:
            print("  constraints:")
            for con in pb.constraints:
                target = getattr(con, "target", None)
                subtarget = getattr(con, "subtarget", "")
                target_name = getattr(target, "name", None)
                print(
                    "   - "
                    f"{con.name} [{con.type}] mute={con.mute} influence={con.influence}"
                )
                print(
                    "     "
                    f"target={target_name or '<none>'} subtarget={subtarget or '<none>'}"
                )
                for ref_name, label in constraint_target_bones(con, armature_obj):
                    print(f"     armature_ref={ref_name} via {label}")


def resolve_armature():
    for name in ARMATURE_CANDIDATES:
        armature_obj = bpy.data.objects.get(name)
        if armature_obj and armature_obj.type == "ARMATURE":
            return armature_obj

    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            return obj

    raise SystemExit("No armature object found")


def main():
    armature_obj = resolve_armature()

    print_bone_details(armature_obj)

    graph = build_graph(armature_obj)
    print("\n[GRAPH EDGES AMONG FOCUS BONES]")
    for src in sorted(FOCUS_BONES):
        for dst, label in graph.get(src, []):
            if dst in FOCUS_BONES:
                print(f"  {src} --{label}--> {dst}")

    cycles = find_cycles(graph, focus_only=FOCUS_BONES)
    print("\n[POSSIBLE CYCLES AMONG FOCUS BONES]")
    if not cycles:
        print("  <none found>")
        return

    for idx, (nodes, labels) in enumerate(cycles, start=1):
        print(f"  Cycle {idx}:")
        for i, label in enumerate(labels):
            print(f"    {nodes[i]} --{label}--> {nodes[i + 1]}")


if __name__ == "__main__":
    main()
