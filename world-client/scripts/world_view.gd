## Builds and maintains the 3D representation of a world snapshot.
## Terrain is built once per world (instanced walls and water); objects
## and agents are refreshed per snapshot; agent nodes interpolate toward
## their latest snapshot position. This node only draws — world truth
## stays server-side.

extends Node3D

const CELL := 1.0
const AGENT_HEIGHT := 0.45

var terrain_root: Node3D
var objects_root: Node3D
var agents_root: Node3D

var _terrain_built_for := ""
var _agents := {}          # id -> Node3D
var _agent_targets := {}   # id -> Vector3


func _ready() -> void:
	terrain_root = Node3D.new()
	objects_root = Node3D.new()
	agents_root = Node3D.new()
	add_child(terrain_root)
	add_child(objects_root)
	add_child(agents_root)


static func _material(albedo: Color, emission := Color.BLACK, energy := 0.0) -> StandardMaterial3D:
	var mat := StandardMaterial3D.new()
	mat.albedo_color = albedo
	if energy > 0.0:
		mat.emission_enabled = true
		mat.emission = emission
		mat.emission_energy_multiplier = energy
	return mat


static func _cell_center(x: int, y: int, height: float) -> Vector3:
	return Vector3((x + 0.5) * CELL, height, (y + 0.5) * CELL)


func build_terrain(snapshot: Dictionary) -> void:
	var key := "%s/%s/%s" % [snapshot.get("seed"), snapshot.get("width"), snapshot.get("height")]
	if key == _terrain_built_for:
		return
	_terrain_built_for = key
	for child in terrain_root.get_children():
		child.queue_free()

	var width := int(snapshot.get("width", 0))
	var height := int(snapshot.get("height", 0))
	var terrain: Array = snapshot.get("terrain", [])

	var ground := PlaneMesh.new()
	ground.size = Vector2(width * CELL, height * CELL)
	var ground_instance := MeshInstance3D.new()
	ground_instance.mesh = ground
	ground_instance.material_override = _material(Color(0.016, 0.05, 0.033))
	ground_instance.position = Vector3(width * 0.5 * CELL, 0.0, height * 0.5 * CELL)
	terrain_root.add_child(ground_instance)

	var wall_cells: Array[Vector3] = []
	var water_cells: Array[Vector3] = []
	for y in range(height):
		var row: String = terrain[y] if y < terrain.size() else ""
		for x in range(width):
			var ch := row[x] if x < row.length() else "."
			if ch == "#":
				wall_cells.append(_cell_center(x, y, 0.6))
			elif ch == "~":
				water_cells.append(_cell_center(x, y, 0.08))

	terrain_root.add_child(_instanced_cells(wall_cells, _material(Color(0.10, 0.14, 0.12), Color(0.1, 0.55, 0.3), 0.25), Vector3(1.0, 1.2, 1.0)))
	terrain_root.add_child(_instanced_cells(water_cells, _material(Color(0.05, 0.22, 0.24), Color(0.1, 0.45, 0.5), 0.2), Vector3(1.0, 0.16, 1.0)))


func _instanced_cells(cells: Array[Vector3], mat: Material, size: Vector3) -> MultiMeshInstance3D:
	var box := BoxMesh.new()
	box.size = size
	var multimesh := MultiMesh.new()
	multimesh.transform_format = MultiMesh.TRANSFORM_3D
	multimesh.mesh = box
	multimesh.instance_count = cells.size()
	for i in range(cells.size()):
		multimesh.set_instance_transform(i, Transform3D(Basis.IDENTITY, cells[i]))
	var instance := MultiMeshInstance3D.new()
	instance.multimesh = multimesh
	instance.material_override = mat
	return instance


func update_state(snapshot: Dictionary) -> void:
	_update_objects(snapshot.get("objects", []))
	_update_agents(snapshot.get("entities", {}))


func _update_objects(objects: Array) -> void:
	for child in objects_root.get_children():
		child.queue_free()
	for obj in objects:
		var pos: Dictionary = obj.get("position", {})
		if pos.is_empty():
			continue
		var kind := str(obj.get("type", "?"))
		var instance := MeshInstance3D.new()
		instance.mesh = _object_mesh(kind)
		instance.material_override = _object_material(kind)
		instance.position = _cell_center(int(pos.get("x", 0)), int(pos.get("y", 0)), 0.25)
		objects_root.add_child(instance)


func _object_mesh(kind: String) -> Mesh:
	match kind:
		"tree":
			var trunk := CylinderMesh.new()
			trunk.top_radius = 0.10
			trunk.bottom_radius = 0.14
			trunk.height = 0.6
			return trunk
		"stone":
			var rock := BoxMesh.new()
			rock.size = Vector3(0.4, 0.35, 0.4)
			return rock
		"food":
			var berry := SphereMesh.new()
			berry.radius = 0.14
			berry.height = 0.28
			return berry
	var fallback := BoxMesh.new()
	fallback.size = Vector3(0.3, 0.3, 0.3)
	return fallback


func _object_material(kind: String) -> StandardMaterial3D:
	match kind:
		"tree":
			return _material(Color(0.03, 0.14, 0.08), Color(0.2, 0.9, 0.5), 0.6)
		"stone":
			return _material(Color(0.35, 0.38, 0.36))
		"food":
			return _material(Color(0.2, 0.04, 0.1), Color(1.0, 0.3, 0.55), 0.9)
	return _material(Color(0.6, 0.6, 0.6), Color(0.8, 0.8, 0.8), 0.3)


func _update_agents(entities: Dictionary) -> void:
	var seen := {}
	for id_key in entities.keys():
		var id := int(id_key)
		var pos: Dictionary = entities[id_key]
		var target := _cell_center(int(pos.get("x", 0)), int(pos.get("y", 0)), AGENT_HEIGHT)
		seen[id] = true
		if _agents.has(id):
			_agent_targets[id] = target
		else:
			var node := _make_agent(id)
			node.position = target
			agents_root.add_child(node)
			_agents[id] = node
			_agent_targets[id] = target
	for id in _agents.keys():
		if not seen.has(id):
			_agents[id].queue_free()
			_agents.erase(id)
			_agent_targets.erase(id)


func _make_agent(id: int) -> Node3D:
	var root := Node3D.new()
	root.name = "Agent%d" % id
	var body := MeshInstance3D.new()
	var capsule := CapsuleMesh.new()
	capsule.radius = 0.22
	capsule.height = 0.8
	body.mesh = capsule
	body.material_override = _material(Color(0.05, 0.25, 0.12), Color(0.2, 1.0, 0.5), 1.1)
	root.add_child(body)
	var label := Label3D.new()
	label.text = "Agent %d" % id
	label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	label.font_size = 40
	label.pixel_size = 0.004
	label.modulate = Color(0.55, 1.0, 0.7)
	label.outline_size = 8
	label.position = Vector3(0, 0.85, 0)
	root.add_child(label)
	return root


func _process(delta: float) -> void:
	var weight := clampf(delta * 10.0, 0.0, 1.0)
	for id in _agents:
		var node: Node3D = _agents[id]
		if _agent_targets.has(id):
			node.position = node.position.lerp(_agent_targets[id], weight)


func agent_node(id: int) -> Node3D:
	return _agents.get(id)


func agent_count() -> int:
	return _agents.size()


## Screen-space agent picking: nearest agent label within max_pixels of
## the click. Deliberately collider-free — the client owns no physics.
func pick_agent(screen_point: Vector2, camera: Camera3D, max_pixels := 42.0) -> int:
	var best := -1
	var best_dist := max_pixels
	for id in _agents:
		var node: Node3D = _agents[id]
		if camera.is_position_behind(node.global_position):
			continue
		var projected := camera.unproject_position(node.global_position + Vector3(0, 0.4, 0))
		var dist := projected.distance_to(screen_point)
		if dist < best_dist:
			best_dist = dist
			best = id
	return best
