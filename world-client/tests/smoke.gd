## Headless smoke test for the world client (no network needed).
## Builds the 3D world view from canned snapshots and checks the scene
## graph reacts the way the live client needs: terrain instanced once,
## objects rebuilt per snapshot, agents created/moved/removed, movement
## targets interpolated.
##
## Run: tools/godot.cmd --headless --path world-client --script res://tests/smoke.gd

extends SceneTree

var view = null
var stage := 0


func _initialize() -> void:
	for path in ["res://scripts/world_view.gd", "res://scripts/api.gd", "res://scripts/free_cam.gd", "res://scripts/main.gd"]:
		var script = load(path)
		if script == null:
			print("SMOKE FAIL: %s does not compile" % path)
			quit(1)
			return
	view = load("res://scripts/world_view.gd").new()
	root.add_child(view)


func _process(_delta: float) -> bool:
	match stage:
		0:
			stage = 1
			_check_initial()
			return false
		1:
			stage = 2
			_apply_second_snapshot()
			return false
		2:
			_check_after_update()
			return true
	return false


func _fail(msg: String) -> void:
	print("  FAIL: " + msg)


func _snapshot(initial: bool) -> Dictionary:
	var objects := []
	var entities := {}
	if initial:
		objects = [
			{"id": 1, "type": "tree", "position": {"x": 2, "y": 3}},
			{"id": 2, "type": "food", "position": {"x": 4, "y": 3}},
			{"id": 3, "type": "stone", "position": {"x": 3, "y": 4}},
		]
		entities = {"1": {"x": 2, "y": 2}, "2": {"x": 4, "y": 2}}
	else:
		# agent 1 moved, agent 2 despawned, agent 3 spawned, food picked up
		objects = [
			{"id": 1, "type": "tree", "position": {"x": 2, "y": 3}},
			{"id": 3, "type": "stone", "position": {"x": 3, "y": 4}},
		]
		entities = {"1": {"x": 3, "y": 2}, "3": {"x": 1, "y": 1}}
	return {
		"seed": "s", "width": 6, "height": 6, "tick": 3 if initial else 4,
		"terrain": [
			"######",
			"#~~..#",
			"#....#",
			"#.t.f#",
			"#..s.#",
			"######",
		],
		"objects": objects,
		"entities": entities,
	}


func _check_initial() -> void:
	if view == null or view.terrain_root == null:
		_fail("view or its roots missing (did _ready run?)")
		quit(1)
		return

	view.build_terrain(_snapshot(true))
	view.update_state(_snapshot(true))

	# '#' cells: 6+6 border rows + 2 per middle row = 20; '~' cells: 2
	var instanced := 0
	for child in view.terrain_root.get_children():
		if child is MultiMeshInstance3D:
			instanced += child.multimesh.instance_count
	if instanced != 22:
		_fail("terrain instances = %d, expected 22 (20 walls + 2 water)" % instanced)

	if view.agents_root.get_child_count() != 2:
		_fail("agent count = %d, expected 2" % view.agents_root.get_child_count())
	if view.objects_root.get_child_count() != 3:
		_fail("object count = %d, expected 3" % view.objects_root.get_child_count())
	if view.agent_count() != 2:
		_fail("agent registry = %d, expected 2" % view.agent_count())


func _apply_second_snapshot() -> void:
	view.update_state(_snapshot(false))


func _check_after_update() -> void:
	var failures := 0

	# agent 2's node was queue_free'd last frame; a fresh agent 3 exists
	if view.agents_root.get_child_count() != 2:
		_fail("agent node count after update = %d, expected 2" % view.agents_root.get_child_count())
		failures += 1
	if view.agent_count() != 2:
		_fail("agent registry after update = %d, expected 2" % view.agent_count())
		failures += 1

	# objects rebuilt: food gone after pickup
	if view.objects_root.get_child_count() != 2:
		_fail("object count after pickup = %d, expected 2" % view.objects_root.get_child_count())
		failures += 1

	# agent 1's node must reach its new snapshot cell (3, 2) once the
	# interpolation completes — drive one full-weight frame to verify the
	# target was set, without depending on frame timing
	view._process(1.0)
	var a1 = view.agent_node(1)
	if a1 == null:
		_fail("agent 1 missing after update")
		failures += 1
	else:
		var expected := Vector3(3.5, 0.45, 2.5)
		if a1.position.distance_to(expected) > 0.01:
			_fail("agent 1 at %s, expected %s (interpolation did not reach target)" % [a1.position, expected])
			failures += 1

	if failures == 0:
		print("SMOKE OK")
		quit(0)
	else:
		print("SMOKE FAIL: %d failure(s)" % failures)
		quit(1)
