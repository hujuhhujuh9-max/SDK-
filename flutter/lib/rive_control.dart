import 'dart:async';

import 'package:flet/flet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/widgets.dart';
import 'package:rive/rive.dart' as rive;

/// Supplements the retained flet_rive extension. Place it before that extension
/// because Flet resolves widget factories in order. Both Python wire formats use
/// canonical artboard/use_artboard_size keys; legacy aliases remain accepted.
class SdkRiveExtension extends FletExtension {
  @override
  Widget? createWidget(Key? key, Control control) =>
      control.type == 'Rive' || control.type == 'sdk_rive_interactive'
      ? SdkRiveControl(key: key, control: control)
      : null;
}

typedef SdkRiveFileLoader =
    Future<rive.File?> Function(
      String path,
      bool isFile,
      Map<String, String>? headers,
    );

class SdkRiveControl extends StatefulWidget {
  const SdkRiveControl({super.key, required this.control, this.loadFile});

  final Control control;

  /// Tests may use Factory.flutter for CPU-rendered output. Production uses the
  /// same Factory.rive native renderer as the pinned flet_rive adapter.
  final SdkRiveFileLoader? loadFile;

  @override
  State<SdkRiveControl> createState() => _SdkRiveControlState();
}

class _SdkRiveControlState extends State<SdkRiveControl>
    with WidgetsBindingObserver {
  rive.File? _file;
  SdkRivePainter? _painter;
  String? _path;
  bool _isFile = false;
  Map<String, String>? _headers;
  List<Object?>? _selection;
  String? _error;
  int _generation = 0;
  bool _loading = false;
  bool _foreground = true;
  bool _tickerEnabled = true;
  bool _alive = true;

  Control get control => widget.control;
  bool get interactive => control.type == 'sdk_rive_interactive';

  @override
  void initState() {
    super.initState();
    _foreground =
        WidgetsBinding.instance.lifecycleState == null ||
        WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed;
    WidgetsBinding.instance.addObserver(this);
    control.addInvokeMethodListener(_invokeMethod);
  }

  @override
  void didUpdateWidget(covariant SdkRiveControl oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.control, control)) {
      oldWidget.control.removeInvokeMethodListener(_invokeMethod);
      control.addInvokeMethodListener(_invokeMethod);
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _tickerEnabled = TickerMode.valuesOf(context).enabled;
    _syncPlayback('visibility');
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    _syncPlayback(state.name);
  }

  void _syncPlayback(String reason, {bool notifyInitial = false}) {
    final painter = _painter;
    if (painter == null) return;
    final active =
        _foreground &&
        _tickerEnabled &&
        control.visible &&
        control.getBool('playing', true)! &&
        painter.speedMultiplier > 0;
    if (painter.active == active && !notifyInitial) return;
    painter.active = active;
    _emitLater('lifecycle', {
      'active': active,
      'reason': reason,
    }, expectedPainter: painter);
    debugPrint(
      'SDK_RIVE_PLAYBACK id=${control.id} active=$active reason=$reason',
    );
  }

  void _emitLater(
    String name,
    Map<String, dynamic> payload, {
    SdkRivePainter? expectedPainter,
  }) {
    final generation = _generation;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_alive &&
          mounted &&
          generation == _generation &&
          (expectedPainter == null || identical(_painter, expectedPainter))) {
        // Generic Flet ControlEvent handlers deserialize a dictionary by field
        // name. Carry the scalar payload in its data field, including Rive's
        // own name without overwriting the Flet event name.
        control.triggerEvent(name, {'data': payload});
      }
    });
  }

  Future<dynamic> _invokeMethod(String method, dynamic args) async {
    final painter = _painter;
    if (!_alive || painter == null || _loading || _error != null) {
      return {'accepted': false, 'ready': false, 'reason': 'not_ready'};
    }
    if (method == 'snapshot') return {'ready': true, ...painter.snapshot};
    if (method == 'fire') {
      if (!interactive) {
        return {'accepted': false, 'reason': 'interactive_control_required'};
      }
      final name = args is Map ? args['name'] : null;
      if (name is! String || name.isEmpty) {
        return {'accepted': false, 'reason': 'invalid_trigger_name'};
      }
      return painter.fire(name);
    }
    return {'accepted': false, 'reason': 'unknown_method'};
  }

  List<Object?> _readSelection() => [
    control.getString('artboard') ?? control.getString('art_board'),
    interactive,
    interactive ? control.getString('state_machine') : null,
    interactive ? const <String>[] : _stringList('animations'),
    interactive ? const <String>[] : _stringList('state_machines'),
  ];

  List<String> _stringList(String name) =>
      List<String>.from(control.get(name) ?? const <String>[]);

  bool _sameSelection(List<Object?>? a, List<Object?> b) =>
      a != null &&
      a[0] == b[0] &&
      a[1] == b[1] &&
      a[2] == b[2] &&
      listEquals(a[3] as List<String>, b[3] as List<String>) &&
      listEquals(a[4] as List<String>, b[4] as List<String>);

  void _disposePainter() {
    _painter?.dispose();
    _painter = null;
    _selection = null;
  }

  void _disposeFile() {
    _disposePainter();
    _file?.dispose();
    _file = null;
  }

  void _syncSource(String src) {
    final source = control.backend.getAssetSource(src);
    final headers = control.get('headers') == null
        ? null
        : Map<String, String>.from(control.get('headers'));
    if (_path == source.path &&
        _isFile == source.isFile &&
        mapEquals(_headers, headers)) {
      return;
    }
    final generation = ++_generation;
    _disposeFile();
    _path = source.path;
    _isFile = source.isFile;
    _headers = headers;
    _error = null;
    _loading = true;
    unawaited(_load(source.path, source.isFile, headers, generation));
  }

  static Future<rive.File?> _defaultLoader(
    String path,
    bool isFile,
    Map<String, String>? headers,
  ) => isFile
      ? rive.File.path(path, riveFactory: rive.Factory.rive)
      : rive.File.url(path, riveFactory: rive.Factory.rive, headers: headers);

  Future<void> _load(
    String path,
    bool isFile,
    Map<String, String>? headers,
    int generation,
  ) async {
    rive.File? loaded;
    try {
      loaded = await (widget.loadFile ?? _defaultLoader)(path, isFile, headers);
      if (!_alive || !mounted || generation != _generation) {
        loaded?.dispose();
        return;
      }
      if (loaded == null) throw StateError('Rive file could not be decoded');
      _file = loaded;
      loaded = null; // ownership transferred; catch/dispose handles _file
      _loading = false;
      _syncPainter();
      setState(() {});
    } catch (error) {
      loaded?.dispose();
      if (!_alive || !mounted || generation != _generation) return;
      _loading = false;
      _disposeFile();
      _reportError(error);
      setState(() {});
    }
  }

  void _reportError(Object error) {
    final message = error.toString();
    if (_error == message) return;
    _error = message;
    _emitLater('error', {
      'message': message,
      'source': control.getString('src'),
    });
    debugPrint('SDK_RIVE_ERROR id=${control.id} message=$message');
  }

  void _syncPainter() {
    final file = _file;
    if (file == null) return;
    final selection = _readSelection();
    if (!_sameSelection(_selection, selection)) {
      _disposePainter();
      late final SdkRivePainter painter;
      painter = SdkRivePainter.create(
        file,
        artboardName: selection[0] as String?,
        interactive: interactive,
        machineName: selection[2] as String?,
        animationNames: selection[3] as List<String>,
        machineNames: selection[4] as List<String>,
        emit: (name, data) => _emitLater(name, data, expectedPainter: painter),
      );
      _painter = painter;
      _selection = selection;
      _applyProperties(painter, notifyInitial: true);
      _emitLater('ready', painter.manifest, expectedPainter: painter);
      debugPrint(
        'SDK_RIVE_READY id=${control.id} artboard=${painter.artboard!.name}',
      );
    } else {
      _applyProperties(_painter!);
    }
  }

  void _applyProperties(SdkRivePainter painter, {bool notifyInitial = false}) {
    final speed = control.getDouble('speed_multiplier', 1)!;
    if (!speed.isFinite || speed < 0) {
      throw ArgumentError('Rive speed must be finite and nonnegative');
    }
    painter.speedMultiplier = speed;
    painter.fit = _toRiveFit(control.getBoxFit('fit'));
    painter.alignment =
        control.getAlignment('alignment') ?? rive.RiveDefaults.alignment;
    if (interactive) {
      painter.applyInputs(
        Map<String, dynamic>.from(control.get('numbers') ?? const {}),
        Map<String, dynamic>.from(control.get('booleans') ?? const {}),
      );
    }
    _error = null;
    if (notifyInitial) {
      // Apply the selected initial pose and saved inputs before a paused
      // reconstruction freezes. This consumes no animation time; freezing a
      // brand-new artboard before this initialization leaves it unpainted.
      painter.advance(0);
    }
    _syncPlayback('properties', notifyInitial: notifyInitial);
  }

  @override
  Widget build(BuildContext context) {
    try {
      final src = control.getString('src');
      if (src == null || src.isEmpty) throw ArgumentError('Rive requires src');
      _syncSource(src);
      if (!_loading) _syncPainter();
    } catch (error) {
      _reportError(error);
    }
    Widget child;
    final painter = _painter;
    if (_error != null) {
      child = ErrorControl('Rive failed: $_error');
    } else if (painter == null) {
      child = control.buildWidget('placeholder') ?? const SizedBox.shrink();
    } else {
      child = rive.RiveArtboardWidget(
        key: ObjectKey(painter),
        artboard: painter.artboard!,
        painter: painter,
      );
      final useSize =
          control.getBool('use_artboard_size') ??
          control.getBool('use_art_board_size', false)!;
      if (useSize) {
        // Use the already owned artboard; never allocate a sizing-only instance.
        final bounds = painter.artboard!.bounds;
        child = SizedBox(
          width: bounds.width,
          height: bounds.height,
          child: child,
        );
      }
      final clip = control.getRect('clip_rect');
      if (clip != null)
        child = ClipRect(clipper: _RiveClipper(clip), child: child);
    }
    return LayoutControl(control: control, child: child);
  }

  @override
  void dispose() {
    _alive = false;
    ++_generation; // late file completions release their own file, not this one
    WidgetsBinding.instance.removeObserver(this);
    control.removeInvokeMethodListener(_invokeMethod);
    _disposeFile();
    debugPrint('SDK_RIVE_DISPOSED id=${control.id}');
    super.dispose();
  }
}

/// Owns one artboard and all associated animations, machines, inputs and
/// listeners. The caller owns the file and disposes it after this painter.
base class SdkRivePainter extends rive.BasicArtboardPainter
    with rive.RivePointerEventMixin {
  SdkRivePainter._(rive.Artboard ownedArtboard, this._emit) {
    super.artboardChanged(ownedArtboard);
  }

  static SdkRivePainter create(
    rive.File file, {
    String? artboardName,
    bool interactive = false,
    String? machineName,
    List<String> animationNames = const [],
    List<String> machineNames = const [],
    void Function(String, Map<String, dynamic>)? emit,
  }) {
    final artboard = artboardName == null
        ? file.defaultArtboard()
        : file.artboard(artboardName);
    if (artboard == null)
      throw ArgumentError('Unknown Rive artboard: $artboardName');
    final painter = SdkRivePainter._(artboard, emit);
    try {
      if (interactive) {
        final machine = machineName == null
            ? artboard.defaultStateMachine()
            : artboard.stateMachine(machineName);
        if (machine == null)
          throw ArgumentError('Unknown Rive state machine: $machineName');
        painter._addMachine(machine);
        // ignore: deprecated_member_use
        for (final input in machine.inputs) {
          painter._inputs[input.name] = input;
        }
      } else if (animationNames.isEmpty && machineNames.isEmpty) {
        final machine = artboard.defaultStateMachine();
        if (machine != null) {
          painter._addMachine(machine);
        } else if (artboard.animationCount() > 0) {
          painter._animations.add(artboard.animationAt(0));
        }
      } else {
        for (final name in animationNames) {
          final animation = artboard.animationNamed(name);
          if (animation == null)
            throw ArgumentError('Unknown Rive animation: $name');
          painter._animations.add(animation);
        }
        for (final name in machineNames) {
          final machine = artboard.stateMachine(name);
          if (machine == null)
            throw ArgumentError('Unknown Rive state machine: $name');
          painter._addMachine(machine);
        }
      }
      painter._lastInputs = painter.snapshot;
      return painter;
    } catch (_) {
      painter.dispose();
      rethrow;
    }
  }

  final void Function(String, Map<String, dynamic>)? _emit;
  final List<rive.Animation> _animations = [];
  final List<rive.StateMachine> _machines = [];
  final Map<rive.StateMachine, rive.OnRiveEvent> _eventListeners = {};
  final List<rive.CallbackHandler> _stateListeners = [];
  final Map<String, rive.Input> _inputs = {};
  Map<String, dynamic> _lastInputs = {};
  bool _active = true;
  bool _disposed = false;
  bool _previousHit = false;
  double speedMultiplier = 1;

  bool get disposed => _disposed;
  bool get active => _active && !_disposed;
  set active(bool value) {
    if (_disposed || _active == value) return;
    _active = value;
    notifyListeners();
  }

  void _addMachine(rive.StateMachine machine) {
    _machines.add(machine);
    machine.addAdvanceRequestListener(_requestAdvance);
    void listener(rive.Event event) {
      if (_disposed) return;
      try {
        final properties = <String, dynamic>{};
        for (final entry in event.properties.entries) {
          final value = entry.value.value;
          if (value is bool ||
              value is String ||
              (value is num && value.isFinite)) {
            properties[entry.key] = value;
          }
        }
        final payload = <String, dynamic>{
          'name': event.name,
          'type': event.type.name,
          'machine': machine.name,
          'seconds_delay': event.secondsDelay,
          'properties': properties,
        };
        if (event is rive.OpenUrlEvent) {
          payload['url'] = event.url;
          payload['target'] = event.target.name;
        }
        _emit?.call('event', payload);
      } finally {
        // The pinned FFI callback hands out owned native event/property
        // wrappers. Copy scalars, then close them; waiting for GC retains the
        // machine and file past navigation. No wrapper escapes this listener.
        for (final property in event.properties.values) {
          property.dispose();
        }
        event.dispose();
      }
    }

    _eventListeners[machine] = listener;
    machine.addEventListener(listener);
    // This callback exists in the pinned native runtime; Rive recommends data
    // binding for new assets. Keep its version boundary explicit in our docs.
    _stateListeners.add(
      // ignore: deprecated_member_use, invalid_use_of_internal_member
      machine.onStateChanged((name) {
        if (!_disposed)
          _emit?.call('state_change', {'machine': machine.name, 'state': name});
      }),
    );
  }

  void _requestAdvance() {
    if (active) scheduleRepaint();
  }

  Map<String, dynamic> get snapshot => {
    'numbers': {
      for (final entry in _inputs.entries)
        if (entry.value is rive.NumberInput)
          entry.key: (entry.value as rive.NumberInput).value,
    },
    'booleans': {
      for (final entry in _inputs.entries)
        if (entry.value is rive.BooleanInput)
          entry.key: (entry.value as rive.BooleanInput).value,
    },
  };

  Map<String, dynamic> get manifest => {
    'artboard': artboard!.name,
    'width': artboard!.bounds.width,
    'height': artboard!.bounds.height,
    'machines': _machines.map((machine) => machine.name).toList(),
    'animations': _animations.map((animation) => animation.name).toList(),
    'active': active,
    'speed_multiplier': speedMultiplier,
    'inputs': {
      for (final entry in _inputs.entries)
        entry.key: entry.value is rive.NumberInput
            ? 'number'
            : entry.value is rive.BooleanInput
            ? 'boolean'
            : 'trigger',
    },
    ...snapshot,
  };

  void applyInputs(
    Map<String, dynamic> numbers,
    Map<String, dynamic> booleans,
  ) {
    if (_disposed) throw StateError('Rive painter disposed');
    // Validate the entire update before applying any value.
    for (final entry in numbers.entries) {
      if (_inputs[entry.key] is! rive.NumberInput ||
          entry.value is! num ||
          !(entry.value as num).isFinite) {
        throw ArgumentError(
          'Unknown or invalid Rive number input: ${entry.key}',
        );
      }
    }
    for (final entry in booleans.entries) {
      if (_inputs[entry.key] is! rive.BooleanInput || entry.value is! bool) {
        throw ArgumentError(
          'Unknown or invalid Rive boolean input: ${entry.key}',
        );
      }
    }
    var changed = false;
    for (final entry in numbers.entries) {
      final input = _inputs[entry.key] as rive.NumberInput;
      final value = (entry.value as num).toDouble();
      if (input.value != value) {
        input.value = value;
        changed = true;
      }
    }
    for (final entry in booleans.entries) {
      final input = _inputs[entry.key] as rive.BooleanInput;
      if (input.value != entry.value) {
        input.value = entry.value;
        changed = true;
      }
    }
    if (changed) {
      _emitInputs();
      _requestAdvance();
    }
  }

  Map<String, dynamic> fire(String name) {
    if (!active)
      return {
        'accepted': false,
        'reason': _disposed ? 'disposed' : 'suspended',
      };
    final input = _inputs[name];
    if (input is! rive.TriggerInput)
      return {'accepted': false, 'reason': 'unknown_trigger'};
    input.fire();
    // Consume the command immediately, and flush events from the previous
    // native advance. Nothing is replayed on foregrounding or reconstruction.
    advance(0);
    advance(0);
    _requestAdvance();
    return {'accepted': true, 'name': name, 'machine': _machines.single.name};
  }

  void _emitInputs() {
    final values = snapshot;
    if (!mapEquals(_lastInputs['numbers'], values['numbers']) ||
        !mapEquals(_lastInputs['booleans'], values['booleans'])) {
      _lastInputs = values;
      _emit?.call('input_change', values);
    }
  }

  @override
  bool advance(double elapsedSeconds) {
    // Check before advancing: the pinned RiveWidgetController.active check is
    // after its native advance, which would still consume time while paused.
    if (!active) return false;
    final elapsed = elapsedSeconds * speedMultiplier;
    var needsFrame = false;
    for (final animation in _animations) {
      needsFrame = animation.advanceAndApply(elapsed) || needsFrame;
    }
    for (final machine in _machines) {
      needsFrame = machine.advanceAndApply(elapsed) || needsFrame;
    }
    if (_animations.isEmpty && _machines.isEmpty) {
      needsFrame = super.advance(elapsed);
    }
    _emitInputs();
    return needsFrame;
  }

  @override
  bool hitTest(Offset position) {
    if (!active || artboard == null) return false;
    final point = localToArtboard(
      position: position,
      artboardBounds: artboard!.bounds,
      fit: fit,
      alignment: alignment,
      size: size,
      scaleFactor: layoutScaleFactor,
    );
    return _machines.any((machine) => machine.hitTest(point)) || _previousHit;
  }

  @override
  void pointerEvent(PointerEvent event, HitTestEntry<HitTestTarget> entry) {
    if (!active || artboard == null) return;
    final point = localToArtboard(
      position: event.localPosition,
      artboardBounds: artboard!.bounds,
      fit: fit,
      alignment: alignment,
      size: size,
      scaleFactor: layoutScaleFactor,
    );
    var hit = false;
    for (final machine in _machines) {
      final result = switch (event) {
        PointerDownEvent() => machine.pointerDown(
          point,
          pointerId: event.pointer,
        ),
        PointerUpEvent() => machine.pointerUp(point, pointerId: event.pointer),
        PointerMoveEvent() || PointerHoverEvent() => machine.pointerMove(
          point,
          pointerId: event.pointer,
        ),
        PointerExitEvent() || PointerCancelEvent() => machine.pointerExit(
          point,
          pointerId: event.pointer,
        ),
        _ => rive.HitResult.none,
      };
      hit = hit || result != rive.HitResult.none;
    }
    if (hit || _previousHit) {
      if (event is PointerDownEvent ||
          event is PointerUpEvent ||
          event is PointerCancelEvent)
        advance(0);
      _requestAdvance();
    }
    _previousHit = hit;
  }

  @override
  void dispose() {
    if (_disposed) return;
    _disposed = true;
    for (final handler in _stateListeners) {
      handler.dispose();
    }
    _stateListeners.clear();
    for (final input in _inputs.values) {
      input.dispose();
    }
    _inputs.clear();
    for (final machine in _machines) {
      machine.removeAdvanceRequestListener(_requestAdvance);
      machine.removeEventListener(_eventListeners[machine]!);
      machine.dispose();
    }
    _machines.clear();
    _eventListeners.clear();
    for (final animation in _animations) {
      animation.dispose();
    }
    _animations.clear();
    artboard?.dispose();
    super.dispose();
  }
}

class _RiveClipper extends CustomClipper<Rect> {
  _RiveClipper(this.rect);
  final Rect rect;
  @override
  Rect getClip(Size size) => rect;
  @override
  bool shouldReclip(_RiveClipper oldClipper) => oldClipper.rect != rect;
}

rive.Fit _toRiveFit(BoxFit? fit) => switch (fit) {
  BoxFit.fill => rive.Fit.fill,
  BoxFit.contain => rive.Fit.contain,
  BoxFit.cover => rive.Fit.cover,
  BoxFit.fitHeight => rive.Fit.fitHeight,
  BoxFit.fitWidth => rive.Fit.fitWidth,
  BoxFit.none => rive.Fit.none,
  BoxFit.scaleDown => rive.Fit.scaleDown,
  _ => rive.RiveDefaults.fit,
};
