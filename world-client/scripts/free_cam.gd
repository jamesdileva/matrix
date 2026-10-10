## Fly camera with follow mode.
## Fly: WASD move, QE down/up, hold RMB to look around, wheel = speed.
## Follow: main.gd locks onto an agent node; the camera orbits it, WASD
## moves the orbit offset, Esc or clicking empty space releases.

extends Camera3D

var move_speed := 10.0
var follow_target: Node3D = null

## When frozen, the camera still looks but takes no movement input —
## participant mode (S20) drives the avatar instead.
var frozen := false

var _follow_offset := Vector3(0, 6, 9)
var _yaw := 0.0
var _pitch := -0.45
var _looking := false


func _ready() -> void:
	near = 0.05
	far = 500.0
	current = true


func is_following() -> bool:
	return follow_target != null and is_instance_valid(follow_target)


func follow(target: Node3D) -> void:
	follow_target = target
	var basis := Basis.from_euler(Vector3(_pitch, _yaw, 0))
	_follow_offset = -(-basis.z) * 10.0 + Vector3(0, 3, 0)
	_follow_offset.y = maxf(_follow_offset.y, 2.0)


func release() -> void:
	follow_target = null


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_RIGHT:
			_looking = event.pressed
		elif event.button_index == MOUSE_BUTTON_WHEEL_UP and event.pressed:
			move_speed = clampf(move_speed * 1.15, 1.0, 80.0)
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN and event.pressed:
			move_speed = clampf(move_speed / 1.15, 1.0, 80.0)
	elif event is InputEventMouseMotion and _looking:
		_yaw -= event.relative.x * 0.004
		_pitch = clampf(_pitch - event.relative.y * 0.004, -1.4, 1.2)
	elif event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
		release()


func _process(delta: float) -> void:
	var input := _movement_vector() if not frozen else Vector3.ZERO
	if is_following():
		_apply_follow(delta, input)
	else:
		_apply_free(delta, input)


func _movement_vector() -> Vector3:
	var v := Vector3.ZERO
	if Input.is_physical_key_pressed(KEY_W):
		v += Vector3.FORWARD
	if Input.is_physical_key_pressed(KEY_S):
		v += Vector3.BACK
	if Input.is_physical_key_pressed(KEY_A):
		v += Vector3.LEFT
	if Input.is_physical_key_pressed(KEY_D):
		v += Vector3.RIGHT
	if Input.is_physical_key_pressed(KEY_E):
		v += Vector3.UP
	if Input.is_physical_key_pressed(KEY_Q):
		v += Vector3.DOWN
	return v


func _apply_free(delta: float, input: Vector3) -> void:
	rotation = Vector3(_pitch, _yaw, 0)
	if input != Vector3.ZERO:
		global_position += (transform.basis * input).normalized() * move_speed * delta


func _apply_follow(delta: float, input: Vector3) -> void:
	rotation = Vector3(_pitch, _yaw, 0)
	if input != Vector3.ZERO:
		_follow_offset += (transform.basis * input).normalized() * move_speed * delta
	_follow_offset.y = clampf(_follow_offset.y, 1.5, 40.0)
	_follow_offset.x = clampf(_follow_offset.x, -30.0, 30.0)
	_follow_offset.z = clampf(_follow_offset.z, -30.0, 30.0)
	global_position = follow_target.global_position + _follow_offset
	look_at(follow_target.global_position + Vector3(0, 0.3, 0))
