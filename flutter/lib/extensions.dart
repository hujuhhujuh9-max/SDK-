import 'package:flet/flet.dart';
import 'package:flutter/foundation.dart';
import 'package:flet_ads/flet_ads.dart' as flet_ads;
import 'package:flet_audio/flet_audio.dart' as flet_audio;
import 'package:flet_audio_recorder/flet_audio_recorder.dart' as flet_audio_recorder;
import 'package:flet_camera/flet_camera.dart' as flet_camera;
import 'package:flet_charts/flet_charts.dart' as flet_charts;
import 'package:flet_code_editor/flet_code_editor.dart' as flet_code_editor;
import 'package:flet_color_pickers/flet_color_pickers.dart' as flet_color_pickers;
import 'package:flet_datatable2/flet_datatable2.dart' as flet_datatable2;
import 'package:flet_flashlight/flet_flashlight.dart' as flet_flashlight;
import 'package:flet_geolocator/flet_geolocator.dart' as flet_geolocator;
import 'package:flet_lottie/flet_lottie.dart' as flet_lottie;
import 'package:flet_local_auth/flet_local_auth.dart' as flet_local_auth;
import 'package:flet_map/flet_map.dart' as flet_map;
import 'package:flet_permission_handler/flet_permission_handler.dart' as flet_permission_handler;
import 'package:flet_rive/flet_rive.dart' as flet_rive;
import 'package:flet_secure_storage/flet_secure_storage.dart' as flet_secure_storage;
import 'package:flet_spinkit/flet_spinkit.dart' as flet_spinkit;
import 'package:flet_video/flet_video.dart' as flet_video;
import 'package:flet_webview/flet_webview.dart' as flet_webview;

List<FletExtension> initializeFletExtensions() {
  final extensions = <FletExtension>[
    flet_ads.Extension(),
    flet_audio.Extension(),
    flet_audio_recorder.Extension(),
    flet_camera.Extension(),
    flet_charts.Extension(),
    flet_code_editor.Extension(),
    flet_color_pickers.Extension(),
    flet_datatable2.Extension(),
    flet_flashlight.Extension(),
    flet_geolocator.Extension(),
    flet_lottie.Extension(),
    flet_local_auth.Extension(),
    flet_map.Extension(),
    flet_permission_handler.Extension(),
    flet_rive.Extension(),
    flet_secure_storage.Extension(),
    flet_spinkit.Extension(),
    flet_video.Extension(),
    flet_webview.Extension(),
  ];
  for (final extension in extensions) {
    // Keep ads registered, but the release example has no AdMob identity.
    // Explicit production ads need their own manifest ID and initialization.
    if (kReleaseMode && extension is flet_ads.Extension) continue;
    extension.ensureInitialized();
  }
  debugPrint('SDK_RUNNER_EXTENSIONS_READY count=${extensions.length}');
  return extensions;
}
