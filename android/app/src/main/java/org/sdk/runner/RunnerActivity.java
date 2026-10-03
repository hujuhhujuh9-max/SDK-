package org.sdk.runner;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Build;
import android.util.Log;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.window.BackEvent;
import android.widget.FrameLayout;
import androidx.activity.BackEventCompat;
import androidx.activity.OnBackPressedCallback;
import io.flutter.FlutterInjector;
import io.flutter.embedding.android.ExclusiveAppComponent;
import io.flutter.embedding.android.FlutterTextureView;
import io.flutter.embedding.android.FlutterView;
import io.flutter.embedding.engine.FlutterEngine;
import io.flutter.embedding.engine.dart.DartExecutor;
import io.flutter.plugin.platform.PlatformPlugin;
import io.flutter.plugin.view.SensitiveContentPlugin;
import java.io.File;
import java.util.Arrays;
import org.renpy.android.PythonSDLActivity;

/** Ren'Py owns SDL/Python; this Activity only attaches a Flutter UI engine. */
public final class RunnerActivity extends PythonSDLActivity
        implements ExclusiveAppComponent<Activity>, PlatformPlugin.PlatformPluginDelegate {
    private FlutterEngine flutter;
    private FlutterView flutterView;
    private PlatformPlugin platform;
    private SensitiveContentPlugin sensitiveContent;
    private boolean fletInput;
    private boolean frameworkHandlesBack;
    private boolean gestureInFlet;
    private boolean gestureProgressLogged;
    private final OnBackPressedCallback back = new OnBackPressedCallback(true) {
        @Override public void handleOnBackPressed() {
            if (gestureInFlet && flutter != null && Build.VERSION.SDK_INT >= 34) {
                gestureInFlet = false;
                Log.i("SDKRunner", "SDK_RUNNER_BACK_GESTURE committed");
                flutter.getBackGestureChannel().commitBackGesture();
            } else RunnerActivity.this.onBackPressed();
        }
        @Override public void handleOnBackStarted(BackEventCompat event) {
            // Android can intercept an edge swipe before dispatchTouchEvent.
            // Its Y coordinate selects the panel; edge X may lie in system insets.
            // Key-injected Back can report (0, 0); retain keyboard focus then.
            if (flutterView != null && (event.getTouchX() != 0 || event.getTouchY() != 0)) {
                int[] location = new int[2];
                flutterView.getLocationOnScreen(location);
                fletInput = event.getTouchY() >= location[1]
                        && event.getTouchY() < location[1] + flutterView.getHeight();
                if (fletInput) flutterView.requestFocus();
            }
            gestureProgressLogged = false;
            Log.i("SDKRunner", "SDK_RUNNER_BACK_DISPATCH fletInput=" + fletInput
                    + " framework=" + frameworkHandlesBack + " y=" + event.getTouchY());
            gestureInFlet = flutter != null && fletInput && frameworkHandlesBack
                    && Build.VERSION.SDK_INT >= 34;
            if (gestureInFlet) {
                Log.i("SDKRunner", "SDK_RUNNER_BACK_GESTURE started");
                flutter.getBackGestureChannel().startBackGesture(androidBackEvent(event));
            }
        }
        @Override public void handleOnBackProgressed(BackEventCompat event) {
            if (gestureInFlet && flutter != null && Build.VERSION.SDK_INT >= 34) {
                if (!gestureProgressLogged) {
                    Log.i("SDKRunner", "SDK_RUNNER_BACK_GESTURE progressed");
                    gestureProgressLogged = true;
                }
                flutter.getBackGestureChannel().updateBackGestureProgress(androidBackEvent(event));
            }
        }
        @Override public void handleOnBackCancelled() {
            if (gestureInFlet && flutter != null && Build.VERSION.SDK_INT >= 34) {
                Log.i("SDKRunner", "SDK_RUNNER_BACK_GESTURE cancelled");
                flutter.getBackGestureChannel().cancelBackGesture();
            }
            gestureInFlet = false;
        }
    };

    private static BackEvent androidBackEvent(BackEventCompat event) {
        return new BackEvent(event.getTouchX(), event.getTouchY(),
                event.getProgress(), event.getSwipeEdge());
    }

    @Override public void setFrameworkHandlesBack(boolean handles) {
        frameworkHandlesBack = handles;
        Log.i("SDKRunner", "SDK_RUNNER_BACK_STATE framework=" + handles);
    }
    @Override public boolean popSystemNavigator() {
        backToRenpy();
        return true;
    }
    private void backToRenpy() {
        // FragmentActivity also uses this dispatcher. Avoid reentering our
        // callback when SDL decides that Android may finish the Activity.
        back.setEnabled(false);
        try { super.onBackPressed(); }
        finally { back.setEnabled(true); }
    }

    @Override public Activity getAppComponent() { return this; }
    @Override public void detachFromFlutterEngine() {
        if (flutterView != null) flutterView.detachFromFlutterEngine();
    }

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        fletInput = getIntent().getData() != null
                || (state != null && state.getBoolean("runner.fletInput"));
        if (mFrameLayout == null) throw new IllegalStateException("Ren'Py surface was not created");
        flutter = new FlutterEngine(this);
        flutter.getActivityControlSurface().attachToActivity(this, getLifecycle());
        flutter.getActivityControlSurface().onRestoreInstanceState(
                state == null ? null : state.getBundle("runner.flutter.plugins"));
        flutter.getRestorationChannel().setRestorationData(
                state == null ? null : state.getByteArray("runner.flutter.framework"));
        platform = new PlatformPlugin(this, flutter.getPlatformChannel(), this);
        flutterView = new FlutterView(this, new FlutterTextureView(this));
        flutterView.setId(View.generateViewId());
        flutterView.attachToFlutterEngine(flutter);
        if (fletInput) flutterView.requestFocus();
        mFrameLayout.addView(flutterView,
                new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, 1, Gravity.BOTTOM));
        sensitiveContent = new SensitiveContentPlugin(flutterView.getId(), this,
                flutter.getSensitiveContentChannel());
        getOnBackPressedDispatcher().addCallback(this, back);
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
        if (getIntent().getData() != null)
            flutter.getNavigationChannel().setInitialRoute(getIntent().getData().toString());
        flutter.getDartExecutor().executeDartEntrypoint(
                new DartExecutor.DartEntrypoint(assets, "main"), Arrays.asList(
                        socket, new File(getFilesDir(), "flet-assets").getAbsolutePath()));
        Log.i("SDKRunner", "SDK_RUNNER_FLUTTER_ATTACHED pid=" + android.os.Process.myPid());
    }

    @Override protected void onStart() {
        super.onStart();
        if (flutterView != null) flutterView.setVisibility(View.VISIBLE);
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
        if (flutter != null) {
            flutter.getLifecycleChannel().appIsPaused();
            flutter.getRenderer().onTrimMemory(TRIM_MEMORY_BACKGROUND);
            flutterView.setVisibility(View.GONE);
        }
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
        if (flutter != null) {
            flutter.getActivityControlSurface().onNewIntent(intent);
            if (intent.getData() != null) {
                fletInput = true;
                flutterView.requestFocus();
                flutter.getNavigationChannel().pushRouteInformation(intent.getData().toString());
            }
        }
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
            if (level >= TRIM_MEMORY_RUNNING_LOW) {
                flutter.getDartExecutor().notifyLowMemoryWarning();
                flutter.getSystemChannel().sendMemoryPressureWarning();
            }
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
        else backToRenpy();
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
        back.remove();
        if (flutter != null) {
            flutter.getLifecycleChannel().appIsDetached();
            detachFromFlutterEngine();
            platform.destroy();
            sensitiveContent.destroy();
            flutter.getActivityControlSurface().detachFromActivity();
            flutter.destroy();
            flutter = null;
        }
        super.onDestroy();
    }
}
