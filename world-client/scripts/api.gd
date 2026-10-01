## Minimal REST client for the Flood Simulation API.
## Every call eventually fires request_finished(kind, data, error).
## Requests run on short-lived HTTPRequest nodes, so several can be
## in flight at once (state poll + events poll).

extends RefCounted

signal request_finished(kind: String, data: Dictionary, error: String)

var base_url: String
var _owner: Node


func _init(owner: Node, base: String = "") -> void:
	_owner = owner
	base_url = base
	if base_url == "":
		base_url = OS.get_environment("FLOOD_API")
	if base_url == "":
		base_url = "http://127.0.0.1:8000"


func create_world(seed_name: String, agents: int, tick_rate: float) -> void:
	_request(
		HTTPClient.METHOD_POST,
		"/api/worlds",
		"create",
		JSON.stringify({"seed": seed_name, "agents": agents, "tick_rate": tick_rate}),
	)


func get_state(world_id: int) -> void:
	_request(HTTPClient.METHOD_GET, "/api/worlds/%d" % world_id, "state")


func get_events(world_id: int, since_id: int) -> void:
	_request(
		HTTPClient.METHOD_GET,
		"/api/worlds/%d/events?since_id=%d&limit=100" % [world_id, since_id],
		"events",
	)


func _request(method: int, path: String, kind: String, body := "") -> void:
	var http := HTTPRequest.new()
	http.timeout = 5.0
	_owner.add_child(http)
	var headers := PackedStringArray()
	if body != "":
		headers.append("Content-Type: application/json")
	var err := http.request(base_url + path, headers, method, body)
	if err != OK:
		http.queue_free()
		request_finished.emit(kind, {}, "request_error_%d" % err)
		return
	http.request_completed.connect(
		func(_result: int, code: int, _headers: PackedStringArray, raw: PackedByteArray) -> void:
			var data := {}
			var text := raw.get_string_from_utf8()
			if raw.size() > 0 and (text.begins_with("{") or text.begins_with("[")):
				var parsed = JSON.parse_string(text)
				if parsed is Dictionary:
					data = parsed
			var error := "" if code >= 200 and code < 300 else "http_%d" % code
			request_finished.emit(kind, data, error)
			http.queue_free()
	)
