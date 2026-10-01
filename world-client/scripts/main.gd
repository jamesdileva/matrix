## Flood world client: connects to the Simulation API, renders the Void
## in 3D, and lets you fly or follow agents.
##
## Environment overrides:
##   FLOOD_API    backend base URL (default http://127.0.0.1:8000)
##   FLOOD_SEED   world seed to create (default "matrix")
##   FLOOD_SMOKE  =1 -> headless self-test: connect, wait for a live
##                snapshot with agents, print FLOOD_SMOKE OK/FAIL, quit.

extends Node3D

const ApiScript := preload("res://scripts/api.gd")
const WorldViewScript := preload("res://scripts/world_view.gd")
const FreeCameraScript := preload("res://scripts/free_cam.gd")

const POLL_INTERVAL := 0.2
const EVENT_POLL_INTERVAL := 0.5
const SMOKE_TIMEOUT := 25.0

var api
var world_view
var cam: Camera3D

var status_label: Label
var tick_label: Label
var event_log: RichTextLabel

var world_id := -1
var terrain_built := false
var last_event_id := 0

var _state_busy := false
var _events_busy := false
var _state_timer := 0.0
var _event_timer := 0.0
var _retry_timer := 0.0
var _connecting := false
var _smoke := false
var _smoke_done := false
var _smoke_deadline := 0
var _last_tick := -1
var _last_agent_count := 0


func _ready() -> void:
	_smoke = OS.get_environment("FLOOD_SMOKE") != ""
	_build_scene()
	api = ApiScript.new(self)
	api.request_finished.connect(_on_api_response)
	_try_connect()
	if _smoke:
		_smoke_deadline = Time.get_ticks_msec() + int(SMOKE_TIMEOUT * 1000)


func _build_scene() -> void:
	var world_env := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.008, 0.02, 0.014)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.25, 0.5, 0.35)
	env.ambient_light_energy = 0.5
	env.fog_enabled = true
	env.fog_light_color = Color(0.02, 0.07, 0.045)
	env.fog_density = 0.012
	world_env.environment = env
	add_child(world_env)

	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-52, 35, 0)
	sun.light_energy = 0.7
	sun.light_color = Color(0.85, 1.0, 0.9)
	sun.shadow_enabled = true
	add_child(sun)

	world_view = WorldViewScript.new()
	add_child(world_view)

	cam = FreeCameraScript.new()
	cam.position = Vector3(16, 18, 30)
	add_child(cam)

	_build_ui()


func _build_ui() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)

	status_label = _label(layer, Vector2(12, 10))
	tick_label = _label(layer, Vector2(12, 34))

	event_log = RichTextLabel.new()
	event_log.position = Vector2(12, 62)
	event_log.size = Vector2(460, 150)
	event_log.scroll_active = false
	event_log.scroll_following = true
	event_log.add_theme_color_override("default_color", Color(0.5, 0.95, 0.65))
	event_log.add_theme_font_size_override("normal_font_size", 13)
	event_log.add_theme_constant_override("outline_size", 4)
	layer.add_child(event_log)

	var help := Label.new()
	help.text = "LMB agent: follow · LMB empty / Esc: release · hold RMB: look · WASD/QE: move · wheel: speed"
	help.add_theme_color_override("font_color", Color(0.4, 0.8, 0.5, 0.85))
	help.add_theme_font_size_override("font_size", 12)
	help.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_LEFT)
	help.position = Vector2(12, -28)
	layer.add_child(help)


func _label(layer: CanvasLayer, pos: Vector2) -> Label:
	var label := Label.new()
	label.position = pos
	label.add_theme_color_override("font_color", Color(0.55, 1.0, 0.7))
	label.add_theme_font_size_override("font_size", 14)
	label.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.8))
	label.add_theme_constant_override("outline", 3)
	layer.add_child(label)
	return label


func _set_status(text: String) -> void:
	status_label.text = "FLOOD · " + text


func _try_connect() -> void:
	if _connecting:
		return
	_connecting = true
	_set_status("connecting to %s ..." % api.base_url)
	api.create_world(OS.get_environment("FLOOD_SEED") if OS.get_environment("FLOOD_SEED") != "" else "matrix", 3, 6.0)


func _on_api_response(kind: String, data: Dictionary, error: String) -> void:
	match kind:
		"create":
			_connecting = false
			if error != "":
				_set_status("backend unreachable (%s) — retrying" % error)
				return
			world_id = int(data.get("id", -1))
			terrain_built = false
			last_event_id = 0
			_state_busy = false
			_events_busy = false
			_set_status("live · world %d · seed %s" % [world_id, data.get("seed", "?")])
		"state":
			_state_busy = false
			if world_id == -1:
				return
			if error != "":
				_set_status("state error: %s" % error)
				return
			_apply_state(data)
		"events":
			_events_busy = false
			if world_id != -1 and error == "":
				_apply_events(data)


func _apply_state(data: Dictionary) -> void:
	if not terrain_built:
		world_view.build_terrain(data)
		terrain_built = true
		var w := int(data.get("width", 32))
		var h := int(data.get("height", 32))
		cam.position = Vector3(w * 0.5, maxf(w, h) * 0.9 + 6.0, h + 8.0)
		cam.look_at(Vector3(w * 0.5, 0.0, h * 0.5))
	world_view.update_state(data)
	_last_tick = int(data.get("tick", 0))
	var entities: Dictionary = data.get("entities", {})
	_last_agent_count = entities.size()
	tick_label.text = "tick %d · %d agents%s" % [
		_last_tick, _last_agent_count,
		" · PAUSED" if bool(data.get("paused", false)) else "",
	]
	if _smoke and not _smoke_done and _last_agent_count > 0:
		_smoke_finish(true)


func _apply_events(data: Dictionary) -> void:
	var events: Array = data.get("events", [])
	if events.is_empty():
		return
	var lines := PackedStringArray()
	for e in events:
		last_event_id = maxi(last_event_id, int(e.get("id", 0)))
		lines.append(_format_event(e))
	event_log.text += "\n".join(lines) + "\n"
	var all_lines := event_log.text.split("\n")
	if all_lines.size() > 80:
		var kept := all_lines.slice(all_lines.size() - 50)
		event_log.text = "\n".join(kept)


func _format_event(e: Dictionary) -> String:
	var kind := str(e.get("type", "?"))
	var payload: Dictionary = e.get("payload", {})
	var detail := ""
	if kind == "ACTION_EXECUTED" or kind == "ACTION_REJECTED":
		var action: Dictionary = payload.get("action", {})
		detail = str(action.get("action", "?"))
		if payload.has("reason"):
			detail += " -> %s" % payload.get("reason")
	elif kind == "OBJECT_CREATED":
		detail = str(payload.get("type", "?"))
	var actor = e.get("actor_id")
	var who := "world" if actor == null else "agent %d" % int(actor)
	return "[%s] %s: %s" % [who, kind.to_lower(), detail]


func _process(delta: float) -> void:
	if _smoke and not _smoke_done and Time.get_ticks_msec() > _smoke_deadline:
		_smoke_finish(false)
		return
	if world_id == -1:
		_retry_timer += delta
		if _retry_timer >= 2.0 and not _connecting:
			_retry_timer = 0.0
			_try_connect()
		return
	_state_timer += delta
	_event_timer += delta
	if _state_timer >= POLL_INTERVAL and not _state_busy:
		_state_timer = 0.0
		_state_busy = true
		api.get_state(world_id)
	if _event_timer >= EVENT_POLL_INTERVAL and not _events_busy:
		_event_timer = 0.0
		_events_busy = true
		api.get_events(world_id, last_event_id)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		if cam.is_following():
			cam.release()
			_set_status("released")
		else:
			var id: int = world_view.pick_agent(event.position, cam)
			if id != -1:
				var node = world_view.agent_node(id)
				if node != null:
					cam.follow(node)
					_set_status("following agent %d — LMB/Esc to release" % id)


func _smoke_finish(ok: bool) -> void:
	if _smoke_done:
		return
	_smoke_done = true
	if ok:
		print("FLOOD_SMOKE OK world=%d tick=%d agents=%d" % [world_id, _last_tick, _last_agent_count])
		get_tree().quit(0)
	else:
		print("FLOOD_SMOKE FAIL: no live snapshot with agents in time")
		get_tree().quit(1)
