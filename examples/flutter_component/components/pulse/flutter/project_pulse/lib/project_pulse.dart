import 'dart:convert';
import 'dart:math' as math;

import 'package:flet/flet.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class Extension extends FletExtension {
  @override
  Widget? createWidget(Key? key, Control control) =>
      control.type == 'project_pulse.PulseDial'
          ? PulseDialControl(key: key, control: control)
          : null;
}

/// A new Flutter component. The only shared API is Flet's existing Control.
class PulseDialControl extends StatefulWidget {
  const PulseDialControl({super.key, required this.control});

  final Control control;

  @override
  State<PulseDialControl> createState() => _PulseDialControlState();
}

class _PulseDialControlState extends State<PulseDialControl>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver {
  late final AnimationController _animation;
  bool _foreground = true;
  bool _tickerEnabled = true;
  String? _asset;
  Color _accent = const Color(0xff25b8c5);
  int _assetGeneration = 0;

  Control get control => widget.control;

  @override
  void initState() {
    super.initState();
    _foreground = WidgetsBinding.instance.lifecycleState == null ||
        WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed;
    _animation = AnimationController(vsync: this);
    control.addListener(_propertiesChanged);
    WidgetsBinding.instance.addObserver(this);
    _syncProperties();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _lifecycle('mounted');
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _tickerEnabled = TickerMode.of(context);
    _syncAnimation();
  }

  @override
  void didUpdateWidget(covariant PulseDialControl oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.control, control)) {
      oldWidget.control.removeListener(_propertiesChanged);
      control.addListener(_propertiesChanged);
    }
    _syncProperties();
  }

  void _propertiesChanged() {
    if (!mounted) return;
    _syncProperties();
    setState(() {});
  }

  void _syncProperties() {
    final duration = Duration(milliseconds:
        control.getInt('period_ms', 1600)!.clamp(200, 10000).toInt());
    if (_animation.duration != duration) {
      _animation.duration = duration;
      if (_animation.isAnimating) _animation.repeat();
    }
    _syncAnimation();
    final asset = control.getString('palette_asset', 'assets/palette.json')!;
    if (_asset != asset) {
      _asset = asset;
      _loadPalette(asset, ++_assetGeneration);
    }
  }

  Future<void> _loadPalette(String asset, int generation) async {
    try {
      final text = await rootBundle.loadString('packages/project_pulse/$asset');
      final palette = jsonDecode(text) as Map<String, dynamic>;
      final accent = palette['accent'] as String;
      if (!RegExp(r'^#[0-9a-fA-F]{6}$').hasMatch(accent)) {
        throw const FormatException('Invalid palette accent');
      }
      if (!mounted || generation != _assetGeneration) return;
      setState(() => _accent = Color(int.parse('ff${accent.substring(1)}', radix: 16)));
    } catch (error) {
      if (!mounted || generation != _assetGeneration) return;
      control.triggerEvent('error', {'message': 'Palette could not be loaded: $error'});
    }
  }

  void _syncAnimation() {
    final running = _foreground && _tickerEnabled &&
        control.visible && control.getBool('running', true)!;
    if (running && !_animation.isAnimating) _animation.repeat();
    if (!running && _animation.isAnimating) _animation.stop();
  }

  void _lifecycle(String phase) => control.triggerEvent('lifecycle', {
        'phase': phase,
        'running': _animation.isAnimating,
      });

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    _syncAnimation();
    _lifecycle(state.name);
  }

  @override
  void dispose() {
    ++_assetGeneration;
    WidgetsBinding.instance.removeObserver(this);
    control.removeListener(_propertiesChanged);
    _animation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final value = control.getDouble('value', 25)!.clamp(0.0, 100.0).toDouble();
    final intensity = control.getDouble('intensity', 0.7)!.clamp(0.0, 1.0).toDouble();
    return LayoutControl(
      control: control,
      child: SizedBox.square(
        dimension: 240,
        child: LayoutBuilder(builder: (context, constraints) =>
          GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTapUp: control.disabled ? null : (details) {
              final point = details.localPosition -
                  Offset(constraints.maxWidth / 2, constraints.maxHeight / 2);
              final radians = (math.atan2(point.dy, point.dx) + math.pi / 2) %
                  (2 * math.pi);
              control.triggerEvent('change', {
                'value': radians / (2 * math.pi) * 100,
                'source': 'tap',
              });
            },
            child: AnimatedBuilder(
              animation: _animation,
              builder: (context, _) => CustomPaint(
                key: const ValueKey('project-pulse-painter'),
                painter: PulsePainter(value: value, intensity: intensity,
                    phase: _animation.value, accent: _accent),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class PulsePainter extends CustomPainter {
  const PulsePainter({required this.value, required this.intensity,
    required this.phase, required this.accent});

  final double value;
  final double intensity;
  final double phase;
  final Color accent;

  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    final radius = size.shortestSide * 0.36;
    canvas.drawCircle(center, radius + 16,
        Paint()..color = const Color(0xff16202c));
    for (var index = 0; index < 3; index++) {
      final wave = (phase + index / 3) % 1;
      canvas.drawCircle(center, radius * (0.3 + wave * 0.7), Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..color = accent.withValues(alpha: (1 - wave) * intensity));
    }
    canvas.drawArc(Rect.fromCircle(center: center, radius: radius),
        -math.pi / 2, value / 100 * math.pi * 2, false, Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 9
          ..strokeCap = StrokeCap.round
          ..color = accent);
    final angle = value / 100 * math.pi * 2 - math.pi / 2;
    canvas.drawCircle(center + Offset(math.cos(angle), math.sin(angle)) * radius,
        7, Paint()..color = Colors.white);
  }

  @override
  bool shouldRepaint(covariant PulsePainter oldDelegate) =>
      oldDelegate.value != value || oldDelegate.intensity != intensity ||
      oldDelegate.phase != phase || oldDelegate.accent != accent;
}
