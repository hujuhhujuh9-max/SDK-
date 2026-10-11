import 'package:flet/flet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

class Backend extends FletBackend {
  Backend()
    : super(
        pageUri: Uri.parse('mock'),
        assetsDir: '',
        extensions: [],
        multiView: false,
      ) {
    isLoading = false;
  }
  final events = <({int id, String name, dynamic data})>[];
  @override
  void onRouteUpdated(String newRoute) {
    route = newRoute;
  }

  @override
  void triggerControlEventById(int id, String name, [dynamic data]) {
    events.add((id: id, name: name, data: data));
  }
}

class Fixture {
  final backend = Backend();
  Fixture({bool guarded = true, bool confirm = true, bool rootOnly = false}) {
    backend.page.update({
      'window': null,
      'route': rootOnly ? '/app' : '/app/notebook',
      'platform': 'android',
      '_overlay': {'_c': 'Overlay', '_i': 40, 'controls': []},
      '_dialogs': {'_c': 'Dialogs', '_i': 41, 'controls': []},
      'views': [
        {
          '_c': 'View',
          '_i': 10,
          'route': '/app',
          'can_pop': false,
          'on_confirm_pop': true,
          'controls': [
            {'_c': 'Text', '_i': 11, 'value': 'Home'},
          ],
        },
        if (!rootOnly)
          {
            '_c': 'View',
            '_i': 20,
            'route': '/app/notebook',
            'can_pop': !guarded,
            'on_confirm_pop': confirm,
            'controls': [
              {'_c': 'Text', '_i': 21, 'value': 'Notebook'},
            ],
          },
      ],
    });
  }
  Control get top => backend.page.children('views').last;
  Future<void> mount(WidgetTester tester) async {
    await tester.pumpWidget(
      ChangeNotifierProvider<FletBackend>.value(
        value: backend,
        child: ControlWidget(control: backend.page),
      ),
    );
    await tester.pumpAndSettle();
  }

  Future<Control> dialog(WidgetTester tester, int id) async {
    final list = backend.page.child('_dialogs')!;
    final control = Control.fromMap(
      {
        '_c': 'AlertDialog',
        '_i': id,
        'open': true,
        'on_dismiss': true,
        'content': {'_c': 'Text', '_i': id + 1, 'value': 'Replace story'},
      },
      backend,
      parent: list,
    );
    list.properties['controls'] = [control];
    list.notify();
    await tester.pumpAndSettle();
    expect(find.text('Replace story'), findsOneWidget);
    return control;
  }

  Iterable<({int id, String name, dynamic data})> get pops => backend.events
      .where((e) => e.name == 'view_pop' || e.name == 'confirm_pop');
  Future<void> close(WidgetTester tester) async {
    await tester.pumpWidget(const SizedBox.shrink());
    backend.dispose();
  }
}

void main() {
  testWidgets('unguarded Flet view reproduces modal Back hiding notebook', (
    tester,
  ) async {
    final f = Fixture(guarded: false, confirm: false);
    await f.mount(tester);
    final d = await f.dialog(tester, 60);
    await tester.binding.handlePopRoute();
    expect(f.pops.single.name, 'view_pop');
    // The existing Python dismiss_dialog closes only the modal.
    d.updateProperties({'open': false}, notify: true);
    await tester.pumpAndSettle();
    expect(find.text('Notebook'), findsNothing);
    expect(find.text('Home'), findsOneWidget);
    expect(
      f.backend.page.children('views').last.getString('route'),
      '/app/notebook',
    );
    await f.close(tester);
  });

  testWidgets('guarded replacement modal consumes Back without removing view', (
    tester,
  ) async {
    final f = Fixture();
    await f.mount(tester);
    final old = await f.dialog(tester, 60);
    old.updateProperties({'open': false}, notify: true);
    await tester.pumpAndSettle();
    final replacement = await f.dialog(tester, 70);
    f.backend.events.clear();
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(f.pops, isEmpty);
    expect(replacement.getBool('open'), false);
    expect(find.text('Replace story'), findsNothing);
    expect(find.text('Notebook'), findsOneWidget);
    expect(f.backend.events.where((e) => e.name == 'dismiss'), hasLength(1));
    await f.close(tester);
  });

  testWidgets(
    'false confirmation leaves Dart stack intact for Python navigation',
    (tester) async {
      final f = Fixture();
      await f.mount(tester);
      final top = f.top;
      await tester.binding.handlePopRoute();
      expect(f.pops.single.name, 'confirm_pop');
      expect(f.pops.single.id, top.id);
      await top.invokeMethod('confirm_pop', {
        'should_pop': false,
      }, const Duration(seconds: 1));
      await tester.pumpAndSettle();
      expect(find.text('Notebook'), findsOneWidget);
      expect(f.backend.events.where((e) => e.name == 'view_pop'), isEmpty);
      // SDK Python navigation owns the next declared page stack.
      f.backend.page.properties['views'] = [
        f.backend.page.children('views').first,
      ];
      f.backend.page.notify();
      await tester.pumpAndSettle();
      expect(find.text('Home'), findsOneWidget);
      expect(f.backend.events.where((e) => e.name == 'view_pop'), isEmpty);
      await f.close(tester);
    },
  );

  testWidgets(
    'explicit can_pop false without callback retains refusal policy',
    (tester) async {
      final f = Fixture(confirm: false);
      await f.mount(tester);
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      expect(f.pops, isEmpty);
      expect(find.text('Notebook'), findsOneWidget);
      await f.close(tester);
    },
  );

  testWidgets(
    'callback alone with can_pop true does not request confirmation',
    (tester) async {
      final f = Fixture(guarded: false);
      await f.mount(tester);
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      expect(f.pops.single.name, 'view_pop');
      expect(find.text('Notebook'), findsNothing);
      await f.close(tester);
    },
  );

  testWidgets('guarded sole app root still delivers confirmation to Python', (
    tester,
  ) async {
    final f = Fixture(rootOnly: true);
    await f.mount(tester);
    await tester.binding.handlePopRoute();
    expect(f.pops.single.name, 'confirm_pop');
    await f.top.invokeMethod('confirm_pop', {
      'should_pop': false,
    }, const Duration(seconds: 1));
    await tester.pumpAndSettle();
    expect(find.text('Home'), findsOneWidget);
    await f.close(tester);
  });
}
