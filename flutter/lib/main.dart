import 'package:flet/flet.dart';
import 'package:flutter/widgets.dart';
import 'extensions.dart';

void main(List<String> arguments) {
  if (arguments.length != 2) {
    throw StateError('The Ren\'Py host must supply its Flet socket and assets.');
  }
  WidgetsFlutterBinding.ensureInitialized();
  runApp(FletApp(
    pageUrl: arguments[0],
    assetsDir: arguments[1],
    extensions: initializeFletExtensions(),
    reconnectIntervalMs: 200,
    reconnectTimeoutMs: 60000,
  ));
}
