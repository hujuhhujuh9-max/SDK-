import 'dart:async';
import 'package:flet/flet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'extensions.dart';

void main(List<String> arguments) {
  if (arguments.length != 2) {
    throw StateError('The Ren\'Py host must supply its Flet socket and assets.');
  }
  WidgetsFlutterBinding.ensureInitialized();
  FletDeepLinkingBootstrap.install();
  runApp(FletApp(
    pageUrl: arguments[0],
    assetsDir: arguments[1],
    extensions: initializeFletExtensions(),
    reconnectIntervalMs: 200,
    reconnectTimeoutMs: 60000,
  ));
  if (kDebugMode) unawaited(checkSensitiveContent());
}

Future<void> checkSensitiveContent() async {
  const channel = MethodChannel('flutter/sensitivecontent');
  final supported = await channel.invokeMethod<bool>(
      'SensitiveContent.isSupported').timeout(const Duration(seconds: 10));
  if (supported == true) {
    final sensitivity = await channel.invokeMethod<int>(
        'SensitiveContent.getContentSensitivity').timeout(const Duration(seconds: 10));
    if (sensitivity == null) throw StateError('Missing native content sensitivity');
  }
  debugPrint('SDK_RUNNER_SENSITIVE_CONTENT_READY supported=$supported');
}
