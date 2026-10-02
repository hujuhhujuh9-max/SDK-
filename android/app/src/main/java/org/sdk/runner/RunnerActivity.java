package org.sdk.runner;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.util.Log;
import android.view.Gravity;
import android.view.KeyEvent;
import android.widget.FrameLayout;
import androidx.lifecycle.Lifecycle;
import androidx.lifecycle.LifecycleOwner;
import androidx.lifecycle.LifecycleRegistry;
import io.flutter.FlutterInjector;
import io.flutter.embedding.android.ExclusiveAppComponent;
import io.flutter.embedding.android.FlutterTextureView;
import io.flutter.embedding.android.FlutterView;
import io.flutter.embedding.engine.FlutterEngine;
import io.flutter.embedding.engine.dart.DartExecutor;
import io.flutter.plugin.platform.PlatformPlugin;
import java.io.File;
import java.util.Collections;
import org.renpy.android.PythonSDLActivity;

/** Ren'Py owns SDL/Python; this Activity only attaches a Flutter UI engine. */
public final class RunnerActivity extends PythonSDLActivity
        implements LifecycleOwner, ExclusiveAppComponent<Activity> {
    private final LifecycleRegistry lifecycle = new LifecycleRegistry(this);
    private FlutterEngine flutter;
    private FlutterView flutterView;
    private PlatformPlugin platform;

    @Override public Lifecycle getLifecycle() { return lifecycle; }
    @Override public Activity getAppComponent() { return this; }
    @Override public void detachFromFlutterEngine() {
        if (flutterView != null) flutterView.detachFromFlutterEngine();
    }

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_CREATE);
        if (mFrameLayout == null) throw new IllegalStateException("Ren'Py surface was not created");
        flutter = new FlutterEngine(this);
        flutter.getActivityControlSurface().attachToActivity(this, lifecycle);
        platform = new PlatformPlugin(this, flutter.getPlatformChannel());
        flutterView = new FlutterView(this, new FlutterTextureView(this));
        flutterView.attachToFlutterEngine(flutter);
        flutterView.setOnTouchListener((view, event) -> { view.requestFocus(); return false; });
        mFrameLayout.addView(flutterView,
                new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, 1, Gravity.BOTTOM));
        mFrameLayout.addOnLayoutChangeListener((view, l, t, r, b, ol, ot, or, ob) -> {
            int height = b - t;
            if (height < 2) return;
            int fletHeight = Math.max(1, height * 2 / 5);
            FrameLayout.LayoutParams sdl = (FrameLayout.LayoutParams) mLayout.getLayoutParams();
            if (sdl.height != height - fletHeight) {
                sdl.height = height - fletHeight;
                mLayout.setLayoutParams(sdl);
            }
            FrameLayout.LayoutParams flet = (FrameLayout.LayoutParams) flutterView.getLayoutParams();
            if (flet.height != fletHeight) {
                flet.height = fletHeight;
                flutterView.setLayoutParams(flet);
            }
        });
        String socket = new File(getFilesDir(), "flet.sock").getAbsolutePath();
        String assets = FlutterInjector.instance().flutterLoader().findAppBundlePath();
        flutter.getDartExecutor().executeDartEntrypoint(
                new DartExecutor.DartEntrypoint(assets, "main"), Collections.singletonList(socket));
        Log.i("SDKRunner", "SDK_RUNNER_FLUTTER_ATTACHED pid=" + android.os.Process.myPid());
    }

    @Override protected void onStart() {
        super.onStart();
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_START);
    }
    @Override protected void onResume() {
        super.onResume();
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_RESUME);
        if (flutter != null) flutter.getLifecycleChannel().appIsResumed();
    }
    @Override protected void onPostResume() {
        super.onPostResume();
        if (platform != null) platform.updateSystemUiOverlays();
    }
    @Override protected void onPause() {
        if (flutter != null) flutter.getLifecycleChannel().appIsInactive();
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_PAUSE);
        super.onPause();
    }
    @Override protected void onStop() {
        if (flutter != null) flutter.getLifecycleChannel().appIsPaused();
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_STOP);
        super.onStop();
    }
    @Override public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        if (flutter != null) {
            if (focused) flutter.getLifecycleChannel().aWindowIsFocused();
            else flutter.getLifecycleChannel().noWindowsAreFocused();
        }
    }
    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (flutter != null) flutter.getActivityControlSurface().onNewIntent(intent);
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (flutter != null) flutter.getActivityControlSurface().onActivityResult(request, result, data);
    }
    @Override public void onRequestPermissionsResult(int request, String[] names, int[] results) {
        super.onRequestPermissionsResult(request, names, results);
        if (flutter != null) flutter.getActivityControlSurface().onRequestPermissionsResult(request, names, results);
    }
    @Override protected void onUserLeaveHint() {
        super.onUserLeaveHint();
        if (flutter != null) flutter.getActivityControlSurface().onUserLeaveHint();
    }
    @Override public void onTrimMemory(int level) {
        super.onTrimMemory(level);
        if (flutter != null) {
            flutter.getRenderer().onTrimMemory(level);
            flutter.getPlatformViewsController().onTrimMemory(level);
            if (level >= TRIM_MEMORY_RUNNING_LOW) flutter.getSystemChannel().sendMemoryPressureWarning();
        }
    }
    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        if (flutterView != null && flutterView.hasFocus() && flutterView.dispatchKeyEvent(event)) return true;
        return super.dispatchKeyEvent(event);
    }
    @Override public void onBackPressed() {
        if (flutterView != null && flutterView.hasFocus()) flutter.getNavigationChannel().popRoute();
        else super.onBackPressed();
    }
    @Override protected void onDestroy() {
        if (flutter != null) {
            flutter.getLifecycleChannel().appIsDetached();
            detachFromFlutterEngine();
            platform.destroy();
            flutter.getActivityControlSurface().detachFromActivity();
            flutter.destroy();
            flutter = null;
        }
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_DESTROY);
        super.onDestroy();
    }
}
