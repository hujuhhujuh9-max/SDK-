import 'dart:ui' as ui;

import 'package:flet/flet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:project_pulse/project_pulse.dart';

class RecordingBackend extends FletBackend {
  RecordingBackend() : super(pageUri: Uri.parse('mock'), assetsDir: '',
      extensions: [Extension()], multiView: false);

  final events = <({String name, dynamic data})>[];

  @override
  void triggerControlEvent(Control control, String eventName, [dynamic eventData]) {
    if (control.hasEventHandler(eventName)) {
      events.add((name: eventName, data: eventData));
    }
  }
}

Control pulse(RecordingBackend backend, {bool running = true}) => Control(
  id: 100, type: 'project_pulse.PulseDial', backend: backend,
  properties: {'value': 25.0, 'intensity': 0.7, 'running': running,
    'period_ms': 1000, 'width': 240.0, 'height': 240.0,
    'on_change': true, 'on_lifecycle': true, 'on_error': true},
);

Future<void> mount(WidgetTester tester, Control control) => tester.pumpWidget(
  MaterialApp(home: Center(child: RepaintBoundary(
    key: const ValueKey('pulse-boundary'),
    child: Extension().createWidget(null, control)!,
  ))),
);

PulsePainter painter(WidgetTester tester) => tester.widget<CustomPaint>(
  find.byKey(const ValueKey('project-pulse-painter'))).painter! as PulsePainter;

Future<Uint8List> pixels(WidgetTester tester) async => (await tester.runAsync(() async {
  final boundary = tester.renderObject<RenderRepaintBoundary>(
    find.byKey(const ValueKey('pulse-boundary')));
  final image = await boundary.toImage(pixelRatio: 1);
  final bytes = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
  image.dispose();
  return bytes!.buffer.asUint8List();
}))!;

void main() {
  test('factory participates in Flet dispatch and declines unknown types', () {
    final backend = RecordingBackend();
    expect(Extension().createWidget(null, pulse(backend)), isA<PulseDialControl>());
    final unknown = Control(id: 101, type: 'Other', properties: {}, backend: backend);
    expect(Extension().createWidget(null, unknown), isNull);
    backend.dispose();
  });

  testWidgets('package asset, property patches and tap events work', (tester) async {
    final backend = RecordingBackend();
    final control = pulse(backend, running: false);
    await mount(tester, control);
    await tester.pumpAndSettle();
    expect(painter(tester).accent, const Color(0xff25b8c5));
    expect(backend.events.where((event) => event.name == 'error'), isEmpty);
    expect(painter(tester).value, 25);
    final originalPixels = await pixels(tester);
    control.properties.addAll({'value': 72.5, 'intensity': 0.3});
    control.notify();
    await tester.pump();
    expect(painter(tester).value, 72.5);
    expect(painter(tester).intensity, 0.3);
    expect(listEquals(originalPixels, await pixels(tester)), isFalse);
    final rect = tester.getRect(find.byKey(const ValueKey('project-pulse-painter')));
    await tester.tapAt(Offset(rect.right - 12, rect.center.dy));
    await tester.pump();
    final event = backend.events.lastWhere((event) => event.name == 'change');
    expect(event.data['value'], closeTo(25, 0.01));
    expect(event.data['source'], 'tap');
    // A tap is a result; the Python model owns the accepted selection.
    expect(control.properties['value'], 72.5);
    await tester.pumpWidget(const SizedBox.shrink());
    backend.dispose();
  });

  testWidgets('background pauses, resume plays and removal releases callbacks', (tester) async {
    final backend = RecordingBackend();
    final control = pulse(backend);
    await mount(tester, control);
    await tester.pump(const Duration(milliseconds: 230));
    final moving = painter(tester).phase;
    await tester.pump(const Duration(milliseconds: 130));
    expect(painter(tester).phase, isNot(moving));
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump();
    final paused = painter(tester).phase;
    await tester.pump(const Duration(milliseconds: 400));
    expect(painter(tester).phase, paused);
    final pauseEvent = backend.events.lastWhere((event) => event.name == 'lifecycle');
    expect(pauseEvent.data, {'phase': 'paused', 'running': false});
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 180));
    expect(painter(tester).phase, isNot(paused));
    await tester.pumpWidget(const SizedBox.shrink());
    final eventCount = backend.events.length;
    control.properties['running'] = false;
    control.notify();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump(const Duration(milliseconds: 500));
    expect(backend.events.length, eventCount);
    expect(tester.binding.transientCallbackCount, 0);
    expect(tester.takeException(), isNull);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    // Reconstructing has the Python value, with a fresh local ticker.
    control.properties.addAll({'value': 81.0, 'running': false});
    await mount(tester, control);
    await tester.pumpAndSettle();
    expect(painter(tester).value, 81);
    expect(painter(tester).phase, 0);
    await tester.pumpWidget(const SizedBox.shrink());
    backend.dispose();
  });

  testWidgets('asset failure returns an error and disabled controls ignore taps', (tester) async {
    final backend = RecordingBackend();
    final control = pulse(backend, running: false);
    control.properties.addAll({'palette_asset': 'missing.json', 'disabled': true});
    await mount(tester, control);
    await tester.pumpAndSettle();
    expect(backend.events.where((event) => event.name == 'error'), hasLength(1));
    await tester.tap(find.byKey(const ValueKey('project-pulse-painter')));
    await tester.pump();
    expect(backend.events.where((event) => event.name == 'change'), isEmpty);
    await tester.pumpWidget(const SizedBox.shrink());
    backend.dispose();
  });
}
