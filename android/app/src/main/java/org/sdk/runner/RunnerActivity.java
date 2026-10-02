package org.sdk.runner;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.util.Log;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.widget.FrameLayout;
import io.flutter.FlutterInjector;
import io.flutter.embedding.android.ExclusiveAppComponent;
import io.flutter.embedding.android.FlutterTextureView;
import io.flutter.embedding.android.FlutterView;
import io.flutter.embedding.engine.FlutterEngine;
import io.flutter.embedding.engine.dart.DartExecutor;
import io.flutter.plugin.platform.PlatformPlugin;
import java.io.File;
import java.util.Arrays;
import org.renpy.android.PythonSDLActivity;

/** Ren'Py owns SDL/Python; this Activity only attaches a Flutter UI engine. */
public final class RunnerActivity extends PythonSDLActivity
        implements ExclusiveAppComponent<Activity> {
    private FlutterEngine flutter;
    private FlutterView flutterView;
    private PlatformPlugin platform;
    private boolean fletInput;

    @Override public Activity getAppComponent() { return this; }
    @Override public void detachFromFlutterEngine() {
        if (flutterView != null) flutterView.detachFromFlutterEngine();
    }

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        fletInput = state != null && state.getBoolean("runner.fletInput");
        if (mFrameLayout == null) throw new IllegalStateException("Ren'Py surface was not created");
        flutter = new FlutterEngine(this);
        flutter.getActivityControlSurface().attachToActivity(this, getLifecycle());
        flutter.getActivityControlSurface().onRestoreInstanceState(
                state == null ? null : state.getBundle("runner.flutter.plugins"));
        flutter.getRestorationChannel().setRestorationData(
                state == null ? null : state.getByteArray("runner.flutter.framework"));
        platform = new PlatformPlugin(this, flutter.getPlatformChannel());
        flutterView = new FlutterView(this, new FlutterTextureView(this));
        flutterView.attachToFlutterEngine(flutter);
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
                new DartExecutor.DartEntrypoint(assets, "main"), Arrays.asList(
                        socket, new File(getFilesDir(), "flet-assets").getAbsolutePath()));
        Log.i("SDKRunner", "SDK_RUNNER_FLUTTER_ATTACHED pid=" + android.os.Process.myPid());
    }

    @Override protected void onResume() {
        super.onResume();
        if (flutter != null) {
            flutter.getRenderer().restoreSurfaceProducers();
            flutter.getLifecycleChannel().appIsResumed();
            if (fletInput) flutterView.requestFocus();
        }
    }
    @Override protected void onPostResume() {
        super.onPostResume();
        if (platform != null) platform.updateSystemUiOverlays();
        if (flutter != null) flutter.getPlatformViewsController().onResume();
    }
    @Override protected void onPause() {
        if (flutter != null) flutter.getLifecycleChannel().appIsInactive();
        super.onPause();
    }
    @Override public void onStop() {
        if (flutter != null) flutter.getLifecycleChannel().appIsPaused();
        super.onStop();
    }
    @Override public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        if (flutter != null) {
            if (focused) flutter.getLifecycleChannel().aWindowIsFocused();
            else flutter.getLifecycleChannel().noWindowsAreFocused();
            if (focused && fletInput) flutterView.requestFocus();
        }
    }
    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
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
        // Keep Android Back out of Flutter's asynchronous keyboard redispatch.
        // The host owns this callback; the active Flet view receives popRoute.
        if (flutter != null && fletInput && event.getKeyCode() == KeyEvent.KEYCODE_BACK) {
            if (event.getAction() == KeyEvent.ACTION_UP && !event.isCanceled()) onBackPressed();
            return true;
        }
        if (flutterView != null && flutterView.hasFocus() && flutterView.dispatchKeyEvent(event)) return true;
        return super.dispatchKeyEvent(event);
    }
    @Override public boolean dispatchTouchEvent(MotionEvent event) {
        if (event.getActionMasked() == MotionEvent.ACTION_DOWN && flutterView != null) {
            int[] location = new int[2];
            flutterView.getLocationOnScreen(location);
            float x = event.getRawX(), y = event.getRawY();
            fletInput = x >= location[0] && x < location[0] + flutterView.getWidth()
                    && y >= location[1] && y < location[1] + flutterView.getHeight();
            if (fletInput) flutterView.requestFocus();
            else mLayout.requestFocus();
        }
        return super.dispatchTouchEvent(event);
    }
    @Override public void onBackPressed() {
        if (flutter != null && fletInput) {
            Log.i("SDKRunner", "SDK_RUNNER_BACK owner=flet");
            flutter.getNavigationChannel().popRoute();
        }
        else super.onBackPressed();
    }
    @Override protected void onSaveInstanceState(Bundle state) {
        super.onSaveInstanceState(state);
        state.putBoolean("runner.fletInput", fletInput);
        if (flutter != null) {
            Bundle plugins = new Bundle();
            flutter.getActivityControlSurface().onSaveInstanceState(plugins);
            state.putBundle("runner.flutter.plugins", plugins);
            state.putByteArray("runner.flutter.framework",
                    flutter.getRestorationChannel().getRestorationData());
        }
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
        super.onDestroy();
    }
}
