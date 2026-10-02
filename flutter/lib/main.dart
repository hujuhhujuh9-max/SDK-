import 'package:flet/flet.dart';
import 'package:flutter/material.dart';

void main(List<String> arguments) {
  if (arguments.length != 1) {
    throw StateError('The Ren\'Py host must supply its private Flet socket.');
  }
  runApp(MaterialApp(
    debugShowCheckedModeBanner: false,
    theme: ThemeData.dark(),
    home: FletApp(
      pageUrl: arguments.single,
      assetsDir: '',
      reconnectIntervalMs: 200,
      reconnectTimeoutMs: 60000,
    ),
  ));
}
