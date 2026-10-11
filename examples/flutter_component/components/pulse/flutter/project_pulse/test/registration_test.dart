// These are SDK integration tests, copied into the generated fixed_flet module.
import 'package:fixed_flet/project_extensions.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'pulse_test.dart' as fixture;

void main() {
  testWidgets('generated project registration renders the new component', (tester) async {
    final factories = initializeProjectExtensions();
    expect(factories, hasLength(1));
    final backend = fixture.RecordingBackend();
    final control = fixture.pulse(backend, running: false);
    final widget = factories.single.createWidget(null, control);
    expect(widget, isNotNull);
    await tester.pumpWidget(MaterialApp(home: Center(child: widget)));
    await tester.pumpAndSettle();
    expect(fixture.painter(tester).value, 25);
    final rectangle = tester.getRect(find.byKey(const ValueKey('project-pulse-painter')));
    await tester.tapAt(Offset(rectangle.right - 10, rectangle.center.dy));
    await tester.pump();
    expect(backend.events.any((event) => event.name == 'change'), isTrue);
    await tester.pumpWidget(const SizedBox.shrink());
    expect(tester.binding.transientCallbackCount, 0);
    backend.dispose();
  });
}
