import 'package:flutter/foundation.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/services.dart';

/// Bounded, debug-only measurements; no frame callback runs in release builds.
class FrameProfile {
  FrameProfile({this.limit = 600, this.budgetUs = 16667});
  final int limit;
  final int budgetUs;
  final List<(int, int, int)> _samples = [];
  final Stopwatch _elapsed = Stopwatch();
  bool active = false;
  int _frames = 0;

  void start() {
    _samples.clear();
    _frames = 0;
    active = true;
    _elapsed.reset();
    _elapsed.start();
  }

  void record(int buildUs, int rasterUs, int totalUs) {
    if (!active) return;
    _frames++;
    if (_samples.length < limit) _samples.add((buildUs, rasterUs, totalUs));
  }

  int _percentile(List<int> samples, double fraction) {
    if (samples.isEmpty) return 0;
    samples.sort();
    return samples[(samples.length * fraction).ceil() - 1];
  }

  Map<String, Object> stop() {
    active = false;
    _elapsed.stop();
    final build = _samples.map((sample) => sample.$1).toList();
    final raster = _samples.map((sample) => sample.$2).toList();
    final total = _samples.map((sample) => sample.$3).toList();
    return {
      'scope': 'Flutter frame timings in a debug Android build; excludes SDL',
      'frames': _frames,
      'recorded_frames': _samples.length,
      'dropped_samples': _frames - _samples.length,
      'elapsed_ms': _elapsed.elapsedMicroseconds / 1000,
      'frame_budget_us': budgetUs,
      'over_budget_frames': total.where((value) => value > budgetUs).length,
      'build_p50_us': _percentile(build, 0.5),
      'build_p95_us': _percentile(build, 0.95),
      'raster_p50_us': _percentile(raster, 0.5),
      'raster_p95_us': _percentile(raster, 0.95),
      'total_p50_us': _percentile(total, 0.5),
      'total_p95_us': _percentile(total, 0.95),
    };
  }
}

void installRuntimeProbes() {
  if (!kDebugMode) return;
  final profile = FrameProfile();
  SchedulerBinding.instance.addTimingsCallback((List<FrameTiming> timings) {
    for (final frame in timings) {
      profile.record(frame.buildDuration.inMicroseconds,
          frame.rasterDuration.inMicroseconds, frame.totalSpan.inMicroseconds);
    }
  });
  const MethodChannel('sdk.runner/profile').setMethodCallHandler((call) async {
    if (call.method == 'start') {
      profile.start();
      return {'started': true};
    }
    if (call.method == 'stop') return profile.stop();
    throw MissingPluginException('Unknown profiling command');
  });
  HardwareKeyboard.instance.addHandler((event) {
    if (event.logicalKey == LogicalKeyboardKey.f1) {
      final kind = event is KeyDownEvent ? 'down' : event is KeyUpEvent ? 'up' : 'repeat';
      debugPrint('SDK_RUNNER_UNHANDLED_F1 $kind synthesized=${event.synthesized}');
    }
    return false;
  });
}
