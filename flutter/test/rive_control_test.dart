import 'dart:async';
import 'dart:convert';
import 'dart:ffi' hide Size;
import 'dart:io' as io;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flet/flet.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rive/rive.dart' as rive;
import 'package:rive_native/src/ffi/dynamic_library_helper.dart';

import '../lib/rive_control.dart';

class _Backend extends FletBackend {
  _Backend()
    : super(
        pageUri: Uri.parse('mock'),
        assetsDir: io.Directory('test/assets/rive').absolute.path,
        extensions: [SdkRiveExtension()],
        multiView: false,
      );

  final events = <({String name, dynamic data})>[];

  @override
  void triggerControlEvent(
    Control control,
    String eventName, [
    dynamic eventData,
  ]) {
    events.add((name: eventName, data: eventData));
  }
}

Future<rive.File> _decode(String name) async => (await rive.File.decode(
  await io.File('test/assets/rive/$name').readAsBytes(),
  riveFactory: rive.Factory.flutter,
))!;

// Counters come from the actual native debug library, not adapter bookkeeping.
int _count(String name) => DynamicLibraryHelper.nativeLib
    .lookupFunction<Uint32 Function(), int Function()>(name)();

List<int> _counts() => [
  _count('debugFileCount'),
  _count('debugArtboardCount'),
  _count('debugStateMachineCount'),
  _count('debugAnimationCount'),
];

Control _control(
  _Backend backend,
  String src, {
  String type = 'sdk_rive_interactive',
  Map<String, dynamic>? properties,
}) => Control(
  id: 1,
  type: type,
  properties: {'src': src, ...?properties},
  backend: backend,
);

Widget _host(Widget child) => MaterialApp(
  home: Align(alignment: Alignment.topLeft, child: child),
);

Future<Uint8List> _pixels(
  WidgetTester tester,
  GlobalKey key, {
  String? output,
}) async {
  final boundary =
      key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
  return (await tester.runAsync(() async {
    final image = await boundary.toImage(pixelRatio: 1);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
    if (output != null) {
      final png = await image.toByteData(format: ui.ImageByteFormat.png);
      final file = io.File('build/rive-evidence/$output');
      await file.parent.create(recursive: true);
      await file.writeAsBytes(png!.buffer.asUint8List());
    }
    image.dispose();
    return Uint8List.fromList(bytes!.buffer.asUint8List());
  }))!;
}

int _differentPixels(Uint8List a, Uint8List b) {
  expect(a.length, b.length);
  var changed = 0;
  for (var i = 0; i < a.length; i += 4) {
    if (a[i] != b[i] || a[i + 1] != b[i + 1] || a[i + 2] != b[i + 2]) changed++;
  }
  return changed;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('registered extension accepts stock and interactive controls only', () {
    final backend = _Backend();
    final extension = SdkRiveExtension();
    expect(
      extension.createWidget(null, _control(backend, 'x', type: 'Rive')),
      isA<SdkRiveControl>(),
    );
    expect(
      extension.createWidget(null, _control(backend, 'x')),
      isA<SdkRiveControl>(),
    );
    expect(
      extension.createWidget(null, _control(backend, 'x', type: 'Text')),
      isNull,
    );
    backend.dispose();
  });

  test(
    'actual native number and boolean values update atomically and dispose',
    () async {
      final before = _counts();
      final file = await _decode('tree_loading_bar.riv');
      final painter = SdkRivePainter.create(
        file,
        interactive: true,
        machineName: 'Loading',
      );
      expect(painter.manifest['inputs'], {
        'Progress': 'number',
        'Downloading': 'boolean',
      });
      painter.applyInputs({'Progress': 65.0}, {'Downloading': false});
      expect(painter.snapshot, {
        'numbers': {'Progress': 65.0},
        'booleans': {'Downloading': false},
      });
      expect(
        () => painter.applyInputs({'Progress': 90.0}, {'missing': true}),
        throwsArgumentError,
      );
      expect(painter.snapshot['numbers'], {'Progress': 65.0});
      expect(
        () => painter.applyInputs({'Progress': double.nan}, {}),
        throwsArgumentError,
      );
      painter.dispose();
      painter.dispose();
      file.dispose();
      expect(
        _counts(),
        before,
        reason: 'Native file/artboard/machine allocations must balance',
      );
    },
  );

  test(
    'real trigger emits typed events once; suspended and reconstructed triggers do not replay',
    () async {
      final before = _counts();
      final events = <({String name, Map<String, dynamic> data})>[];
      final file = await _decode('events_test.riv');
      final painter = SdkRivePainter.create(
        file,
        interactive: true,
        emit: (name, data) => events.add((name: name, data: data)),
      );
      expect(painter.manifest['inputs'], {
        'FireBothEvents': 'trigger',
        'FireOpenUrlEvent': 'trigger',
        'FireGeneralEvent': 'trigger',
      });
      expect(painter.fire('missing'), {
        'accepted': false,
        'reason': 'unknown_trigger',
      });
      painter.active = false;
      expect(painter.fire('FireGeneralEvent'), {
        'accepted': false,
        'reason': 'suspended',
      });
      painter.advance(10);
      expect(events.where((event) => event.name == 'event'), isEmpty);
      painter.active = true;
      expect(painter.fire('FireGeneralEvent')['accepted'], true);
      final actual = events.where((event) => event.name == 'event').single.data;
      expect(actual['name'], 'SomeGeneralEvent');
      expect(actual['type'], 'general');
      expect(actual['properties'], {
        'SomeNumber': 11.0,
        'SomeBoolean': true,
        'SomeString': 'Something',
      });
      final receipt = io.File('build/rive-evidence/event.json');
      receipt.parent.createSync(recursive: true);
      receipt.writeAsStringSync('${jsonEncode(actual)}\n');
      for (var frame = 0; frame < 120; frame++) {
        painter.advance(1 / 60);
      }
      expect(events.where((event) => event.name == 'event'), hasLength(1));
      expect(painter.fire('FireOpenUrlEvent')['accepted'], true);
      final url = events.where((event) => event.name == 'event').last.data;
      expect(url['url'], 'https://rive.app');
      expect(url['target'], 'parent');
      painter.dispose();
      expect(painter.fire('FireGeneralEvent'), {
        'accepted': false,
        'reason': 'disposed',
      });
      final count = events.length;
      final rebuilt = SdkRivePainter.create(
        file,
        interactive: true,
        emit: (name, data) => events.add((name: name, data: data)),
      );
      rebuilt.advance(1);
      rebuilt.advance(1);
      expect(
        events.skip(count).where((event) => event.name == 'event'),
        isEmpty,
      );
      rebuilt.dispose();
      file.dispose();
      expect(_counts(), before);
    },
  );

  test(
    'bad artboard/machine/animation selection releases allocations',
    () async {
      final before = _counts();
      final file = await _decode('events_test.riv');
      final loaded = _counts();
      expect(
        () => SdkRivePainter.create(file, artboardName: 'missing'),
        throwsArgumentError,
      );
      expect(_counts(), loaded);
      expect(
        () => SdkRivePainter.create(
          file,
          interactive: true,
          machineName: 'missing',
        ),
        throwsArgumentError,
      );
      expect(_counts(), loaded);
      expect(
        () => SdkRivePainter.create(
          file,
          animationNames: ['Timeline 1', 'missing'],
        ),
        throwsArgumentError,
      );
      expect(_counts(), loaded);
      file.dispose();
      expect(_counts(), before);
    },
  );

  testWidgets(
    'stock canonical nondefault artboard and intrinsic size do not create sizing allocations',
    (tester) async {
      final before = _counts();
      final backend = _Backend();
      final file = await tester.runAsync(
        () => _decode('runtime_nested_inputs.riv'),
      );
      final defaultArtboard = file!.defaultArtboard()!;
      final defaultName = defaultArtboard.name;
      defaultArtboard.dispose();
      final control = _control(
        backend,
        'runtime_nested_inputs.riv',
        type: 'Rive',
        properties: {'artboard': 'CircleOuter', 'use_artboard_size': true},
      );
      var loads = 0;
      final widget = SdkRiveControl(
        control: control,
        loadFile: (path, isFile, headers) async {
          loads++;
          return file;
        },
      );
      await tester.pumpWidget(_host(widget));
      await tester.pump();
      final artboardWidget = tester.widget<rive.RiveArtboardWidget>(
        find.byType(rive.RiveArtboardWidget),
      );
      expect(defaultName, isNot('CircleOuter'));
      expect(artboardWidget.artboard.name, 'CircleOuter');
      final bounds = artboardWidget.artboard.bounds;
      expect(
        tester.getSize(find.byType(rive.RiveArtboardWidget)),
        Size(bounds.width, bounds.height),
      );
      final mounted = _counts();
      for (var refresh = 0; refresh < 20; refresh++) {
        await tester.pumpWidget(
          _host(SdkRiveControl(control: control, loadFile: widget.loadFile)),
        );
        await tester.pump();
        expect(_counts(), mounted);
      }
      expect(loads, 1);
      control.properties['artboard'] = defaultName;
      await tester.pumpWidget(
        _host(SdkRiveControl(control: control, loadFile: widget.loadFile)),
      );
      await tester.pump();
      expect(
        tester
            .widget<rive.RiveArtboardWidget>(
              find.byType(rive.RiveArtboardWidget),
            )
            .artboard
            .name,
        defaultName,
      );
      expect(
        loads,
        1,
        reason: 'Changing artboard should reuse the loaded file',
      );
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      expect(_counts(), before);
      expect(control.hasInvokeMethodListeners, false);
      backend.dispose();
    },
  );

  testWidgets('number and boolean inputs alter matched-time rendered output', (
    tester,
  ) async {
    final before = _counts();
    final file = await tester.runAsync(() => _decode('tree_loading_bar.riv'));
    final painters = <SdkRivePainter>[];
    for (final values in [(25.0, true), (85.0, true), (85.0, false)]) {
      final painter = SdkRivePainter.create(
        file!,
        interactive: true,
        machineName: 'Loading',
      );
      painter.applyInputs({'Progress': values.$1}, {'Downloading': values.$2});
      for (var frame = 0; frame < 120; frame++) {
        painter.advance(1 / 60);
      }
      painter.active = false;
      painters.add(painter);
    }
    tester.view.physicalSize = const Size(1080, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final keys = List.generate(3, (_) => GlobalKey());
    await tester.pumpWidget(
      _host(
        Row(
          children: [
            for (var i = 0; i < 3; i++)
              RepaintBoundary(
                key: keys[i],
                child: SizedBox(
                  width: 320,
                  height: 220,
                  child: rive.RiveArtboardWidget(
                    artboard: painters[i].artboard!,
                    painter: painters[i],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
    await tester.pump();
    final low = await _pixels(tester, keys[0], output: 'matched-25-true.png');
    final high = await _pixels(tester, keys[1], output: 'matched-85-true.png');
    final off = await _pixels(tester, keys[2], output: 'matched-85-false.png');
    expect(
      _differentPixels(low, high),
      greaterThan(100),
      reason: 'Same elapsed time isolates the number input',
    );
    expect(
      _differentPixels(high, off),
      greaterThan(100),
      reason: 'Same elapsed time/progress isolates the boolean input',
    );
    await tester.pumpWidget(const SizedBox.shrink());
    for (final painter in painters) {
      painter.dispose();
    }
    file!.dispose();
    expect(_counts(), before);
  });

  testWidgets(
    'actual playback, number/bool effect, pause/background/resume and restored values produce pixels',
    (tester) async {
      final before = _counts();
      final backend = _Backend();
      final file = await tester.runAsync(() => _decode('tree_loading_bar.riv'));
      final control = _control(
        backend,
        'tree_loading_bar.riv',
        properties: {
          'width': 320.0,
          'height': 220.0,
          'state_machine': 'Loading',
          'numbers': {'Progress': 25.0},
          'booleans': {'Downloading': true},
        },
      );
      final key = GlobalKey();
      Widget view() => _host(
        RepaintBoundary(
          key: key,
          child: SdkRiveControl(
            control: control,
            loadFile: (path, isFile, headers) async => file,
          ),
        ),
      );
      await tester.pumpWidget(view());
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      final a = await _pixels(tester, key, output: 'forest-25-playing-a.png');
      await tester.pump(const Duration(milliseconds: 400));
      final b = await _pixels(tester, key, output: 'forest-25-playing-b.png');
      expect(
        _differentPixels(a, b),
        greaterThan(10),
        reason: 'Playback must alter actual output',
      );
      control.properties['playing'] = false;
      await tester.pumpWidget(view());
      await tester.pump();
      final paused = await _pixels(tester, key, output: 'forest-paused.png');
      await tester.pump(const Duration(seconds: 2));
      expect(_differentPixels(paused, await _pixels(tester, key)), 0);
      control.properties['playing'] = true;
      await tester.pumpWidget(view());
      await tester.pump();
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump();
      final background = await _pixels(tester, key);
      await tester.pump(const Duration(seconds: 2));
      expect(_differentPixels(background, await _pixels(tester, key)), 0);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      final resumed = await _pixels(tester, key, output: 'forest-resumed.png');
      expect(_differentPixels(background, resumed), greaterThan(10));
      control.properties['numbers'] = {'Progress': 85.0};
      await tester.pumpWidget(view());
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));
      final progressed = await _pixels(tester, key, output: 'forest-85.png');
      expect(_differentPixels(resumed, progressed), greaterThan(100));
      control.properties['booleans'] = {'Downloading': false};
      await tester.pumpWidget(view());
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));
      final stopped = await _pixels(
        tester,
        key,
        output: 'forest-downloading-false.png',
      );
      expect(_differentPixels(progressed, stopped), greaterThan(10));
      final saved = await control.invokeMethod(
        'snapshot',
        null,
        const Duration(seconds: 1),
      );
      expect(saved['numbers'], {'Progress': 85.0});
      expect(saved['booleans'], {'Downloading': false});
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      expect(_counts(), before);
      final reopenedFile = await tester.runAsync(
        () => _decode('tree_loading_bar.riv'),
      );
      final reopened = _control(
        backend,
        'tree_loading_bar.riv',
        properties: {
          'state_machine': 'Loading',
          'numbers': saved['numbers'],
          'booleans': saved['booleans'],
        },
      );
      await tester.pumpWidget(
        _host(
          SdkRiveControl(
            control: reopened,
            loadFile: (path, isFile, headers) async => reopenedFile,
          ),
        ),
      );
      await tester.pump();
      final restored = await reopened.invokeMethod(
        'snapshot',
        null,
        const Duration(seconds: 1),
      );
      expect(restored, saved);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      expect(_counts(), before);
      backend.dispose();
    },
  );

  testWidgets(
    'a source load finishing after replacement or unmount is released',
    (tester) async {
      final before = _counts();
      final backend = _Backend();
      final first = Completer<rive.File?>();
      final second = Completer<rive.File?>();
      var loads = 0;
      Future<rive.File?> loader(
        String path,
        bool isFile,
        Map<String, String>? headers,
      ) => ++loads == 1 ? first.future : second.future;
      final control = _control(backend, 'first.riv');
      await tester.pumpWidget(
        _host(SdkRiveControl(control: control, loadFile: loader)),
      );
      control.properties['src'] = 'second.riv';
      await tester.pumpWidget(
        _host(SdkRiveControl(control: control, loadFile: loader)),
      );
      expect(loads, 2);
      final firstFile = await tester.runAsync(() => _decode('events_test.riv'));
      final secondFile = await tester.runAsync(
        () => _decode('events_test.riv'),
      );
      second.complete(secondFile);
      await tester.pump();
      final current = _counts();
      first.complete(firstFile);
      await tester.pump();
      expect(_counts()[0], current[0] - 1);
      expect(find.byType(rive.RiveArtboardWidget), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      expect(_counts(), before);
      final late = Completer<rive.File?>();
      await tester.pumpWidget(
        _host(
          SdkRiveControl(
            control: _control(backend, 'late.riv'),
            loadFile: (path, isFile, headers) => late.future,
          ),
        ),
      );
      await tester.pumpWidget(const SizedBox.shrink());
      final lateFile = await tester.runAsync(() => _decode('events_test.riv'));
      late.complete(lateFile);
      await tester.pump();
      expect(_counts(), before);
      backend.dispose();
    },
  );
}
