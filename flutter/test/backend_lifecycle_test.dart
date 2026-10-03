import 'dart:async';
import 'dart:typed_data';

import 'package:flet/flet.dart';
import 'package:flutter_test/flutter_test.dart';

class _Channel implements FletBackendChannel {
  _Channel({this.failure, this.gate});

  final Object? failure;
  final Completer<void>? gate;
  late FletBackendChannelOnDisconnectCallback onDisconnect;
  late FletBackendChannelOnPacketCallback onPacket;
  final List<Uint8List> sent = [];
  int connectAttempts = 0;
  int disconnectCalls = 0;

  @override
  Future<void> connect() async {
    connectAttempts++;
    if (gate != null) await gate!.future;
    if (failure != null) throw failure!;
  }

  @override
  bool get isLocalConnection => true;

  @override
  int get defaultReconnectIntervalMs => 200;

  @override
  void send(Uint8List packet) => sent.add(Uint8List.fromList(packet));

  @override
  void disconnect() => disconnectCalls++;
}

class _Factory {
  _Factory(this.create);

  final _Channel Function(int attempt) create;
  final List<_Channel> channels = [];

  FletBackendChannelBuilder get builder => ({
        required FletBackendChannelOnDisconnectCallback onDisconnect,
        required FletBackendChannelOnPacketCallback onPacket,
      }) {
        final channel = create(channels.length);
        channels.add(channel);
        channel.onDisconnect = onDisconnect;
        channel.onPacket = onPacket;
        return channel;
      };
}

FletBackend _backend(_Factory factory) => FletBackend(
      pageUri: Uri.parse('mock'),
      assetsDir: '',
      extensions: [],
      multiView: false,
      channelBuilder: factory.builder,
    );

void main() {
  testWidgets('disposing cancels a queued reconnect', (tester) async {
    final factory = _Factory((_) => _Channel(failure: StateError('not ready')));
    final backend = _backend(factory);
    await backend.connect();
    backend.dispose();
    await tester.pump(const Duration(milliseconds: 500));
    expect(factory.channels, hasLength(1));
    expect(factory.channels.single.sent, isEmpty);
  });

  testWidgets('an active backend still retries a temporary failure',
      (tester) async {
    final factory = _Factory((attempt) =>
        _Channel(failure: attempt == 0 ? StateError('not ready') : null));
    final backend = _backend(factory);
    await backend.connect();
    await tester.pump(const Duration(milliseconds: 200));
    await tester.pump();
    expect(factory.channels, hasLength(2));
    expect(factory.channels.last.sent, hasLength(1));
    backend.dispose();
  });

  testWidgets('duplicate disconnect callbacks schedule one retry',
      (tester) async {
    final factory = _Factory((_) => _Channel());
    final backend = _backend(factory);
    await backend.connect();
    factory.channels.single.onDisconnect();
    factory.channels.single.onDisconnect();
    await tester.pump(const Duration(milliseconds: 200));
    await tester.pump();
    expect(factory.channels, hasLength(2));
    backend.dispose();
  });

  testWidgets('a connect finishing after disposal closes without registering',
      (tester) async {
    final gate = Completer<void>();
    final factory = _Factory((_) => _Channel(gate: gate));
    final backend = _backend(factory);
    final connecting = backend.connect();
    final channel = factory.channels.single;
    backend.dispose();
    gate.complete();
    await connecting;
    expect(channel.sent, isEmpty);
    expect(channel.disconnectCalls, 2);
    await backend.connect();
    expect(factory.channels, hasLength(1));
  });

  for (final failure in [
    StateError('connection lost'),
    const FletAppStartupException('startup failed'),
  ]) {
    testWidgets('a late ${failure.runtimeType} leaves disposed state untouched',
        (tester) async {
      final gate = Completer<void>();
      final factory = _Factory((_) => _Channel(gate: gate, failure: failure));
      final backend = _backend(factory);
      final connecting = backend.connect();
      backend.dispose();
      gate.complete();
      await connecting;
      expect(backend.error, isEmpty);
      await tester.pump(const Duration(milliseconds: 500));
      expect(factory.channels, hasLength(1));
    });
  }

  testWidgets('packets queued after disposal are ignored', (tester) async {
    final factory = _Factory((_) => _Channel());
    final backend = _backend(factory);
    await backend.connect();
    backend.dispose();
    // Type byte 0, MsgPack [sessionCrashed(6), {'message': 'late'}].
    factory.channels.single.onPacket(Uint8List.fromList([
      0x00, 0x92, 0x06, 0x81, 0xa7, ...'message'.codeUnits,
      0xa4, ...'late'.codeUnits,
    ]));
    expect(backend.error, isEmpty);
  });

  testWidgets('a genuine startup failure still settles on its error',
      (tester) async {
    final factory = _Factory((_) =>
        _Channel(failure: const FletAppStartupException('startup failed')));
    final backend = _backend(factory);
    await backend.connect();
    expect(backend.isLoading, isFalse);
    expect(backend.error, 'startup failed');
    expect(backend.bootStatus.value.error, contains('startup failed'));
    await tester.pump(const Duration(milliseconds: 500));
    expect(factory.channels, hasLength(1));
    backend.dispose();
  });
}
