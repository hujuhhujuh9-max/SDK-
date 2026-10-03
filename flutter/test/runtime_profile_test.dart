import 'package:fixed_flet/runtime_profile.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('records only while active and calculates nearest-rank percentiles', () {
    final profile = FrameProfile();
    profile.record(1, 1, 1);
    profile.start();
    for (final total in [1000, 2000, 3000, 20000]) {
      profile.record(total ~/ 2, total ~/ 4, total);
    }
    final report = profile.stop();
    expect(report['frames'], 4);
    expect(report['total_p50_us'], 2000);
    expect(report['total_p95_us'], 20000);
    expect(report['over_budget_frames'], 1);
    profile.record(999, 999, 999);
    expect(profile.stop()['frames'], 4);
  });

  test('bounds storage and reports dropped samples', () {
    final profile = FrameProfile(limit: 2);
    profile.start();
    for (var i = 0; i < 3; i++) {
      profile.record(i, i, i);
    }
    final report = profile.stop();
    expect(report['frames'], 3);
    expect(report['recorded_frames'], 2);
    expect(report['dropped_samples'], 1);
  });

  test('new profiling windows discard the previous measurements', () {
    final profile = FrameProfile();
    profile.start();
    profile.record(50, 60, 100);
    profile.stop();
    profile.start();
    final report = profile.stop();
    expect(report['frames'], 0);
    expect(report['total_p95_us'], 0);
  });
}
