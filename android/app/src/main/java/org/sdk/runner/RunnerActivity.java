package org.sdk.runner;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.graphics.Rect;
import android.view.WindowInsets;
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
import io.flutter.embedding.engine.renderer.FlutterUiDisplayListener;
import io.flutter.plugin.common.MethodChannel;
import org.json.JSONObject;
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
    private boolean keyboardShown;
    private boolean firstFlutterFrame;
    private boolean frameworkHandlesBack;
    private boolean gestureInFlet;
    private boolean gestureProgressLogged;
    private String presentation = "scene";
    private String viewportPresentation;
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
            if (flutterView != null
                    && (event.getSwipeEdge() == BackEventCompat.EDGE_LEFT
                        || event.getSwipeEdge() == BackEventCompat.EDGE_RIGHT)
                    && (event.getTouchX() != 0 || event.getTouchY() != 0)) {
                int[] location = new int[2];
                flutterView.getLocationOnScreen(location);
                fletInput = event.getTouchY() >= location[1]
                        && event.getTouchY() < location[1] + flutterView.getHeight();
                if (fletInput) flutterView.requestFocus();
            }
            gestureProgressLogged = false;
            Log.i("SDKRunner", "SDK_RUNNER_BACK_DISPATCH fletInput=" + fletInput
                    + " framework=" + frameworkHandlesBack + " edge=" + event.getSwipeEdge()
                    + " y=" + event.getTouchY());
            gestureInFlet = flutter != null && fletInput && frameworkHandlesBack
                    && !presentation.equals("scene") && !presentation.equals("interlude")
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
        if (flutter != null && !presentation.equals("diagnostics")) {
            flutter.getNavigationChannel().pushRouteInformation(
                    presentation.equals("scene") || presentation.equals("interlude") ? "/menu" : "/");
        } else backToRenpy();
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
        flutter.getRenderer().addIsDisplayingFlutterUiListener(new FlutterUiDisplayListener() {
            @Override public void onFlutterUiDisplayed() { firstFlutterFrame = true; }
            @Override public void onFlutterUiNoLongerDisplayed() {}
        });
        flutter.getActivityControlSurface().attachToActivity(this, getLifecycle());
        flutter.getActivityControlSurface().onRestoreInstanceState(
                state == null ? null : state.getBundle("runner.flutter.plugins"));
        flutter.getRestorationChannel().setRestorationData(
                state == null ? null : state.getByteArray("runner.flutter.framework"));
        platform = new PlatformPlugin(this, flutter.getPlatformChannel(), this);
        // Interludes paint over SDL; returning to the story hides Flutter.
        // A non-opaque TextureView lets transparent corners reveal Ren'Py.
        FlutterTextureView texture = new FlutterTextureView(this);
        texture.setOpaque(false);
        flutterView = new FlutterView(this, texture);
        flutterView.setId(View.generateViewId());
        flutterView.attachToFlutterEngine(flutter);
        if (fletInput) flutterView.requestFocus();
        mFrameLayout.addView(flutterView,
                new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, 1, Gravity.BOTTOM));
        sensitiveContent = new SensitiveContentPlugin(flutterView.getId(), this,
                flutter.getSensitiveContentChannel());
        getOnBackPressedDispatcher().addCallback(this, back);
        // SDL's fullscreen window does not resize itself for the IME. Keep the
        // scene and its controls inside the usable window on small displays.
        mFrameLayout.addOnLayoutChangeListener((view, l, t, r, b, ol, ot, or, ob) -> layoutPanels());
        mFrameLayout.getViewTreeObserver().addOnGlobalLayoutListener(this::layoutPanels);
        flutterView.setOnApplyWindowInsetsListener((view, insets) -> {
            layoutPanels();
            // The host already places Flutter above the IME. Passing the whole
            // window's keyboard inset into this smaller view would shrink it twice.
            if (Build.VERSION.SDK_INT >= 30) {
                return view.onApplyWindowInsets(new WindowInsets.Builder(insets)
                        .setInsets(WindowInsets.Type.ime(), android.graphics.Insets.NONE).build());
            }
            if (keyboardShown) {
                return view.onApplyWindowInsets(insets.replaceSystemWindowInsets(
                        insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                        insets.getSystemWindowInsetRight(), 0));
            }
            return view.onApplyWindowInsets(insets);
        });
        String socket = new File(getFilesDir(), "flet.sock").getAbsolutePath();
        String assets = FlutterInjector.instance().flutterLoader().findAppBundlePath();
        if (getIntent().getData() != null)
            flutter.getNavigationChannel().setInitialRoute(getIntent().getData().toString());
        flutter.getDartExecutor().executeDartEntrypoint(
                new DartExecutor.DartEntrypoint(assets, "main"), Arrays.asList(
                        socket, new File(getFilesDir(), "flet-assets").getAbsolutePath()));
        Log.i("SDKRunner", "SDK_RUNNER_FLUTTER_ATTACHED pid=" + android.os.Process.myPid());
        debugProfile(getIntent());
    }

    /** Called through JNI by the Flet event loop; Android owns the view mutation. */
    public void setRunnerPresentation(String mode) {
        if (!mode.equals("scene") && !mode.equals("interlude")
                && !mode.equals("page") && !mode.equals("diagnostics"))
            throw new IllegalArgumentException("Unknown runner presentation: " + mode);
        runOnUiThread(() -> {
            presentation = mode;
            if (mode.equals("scene")) {
                fletInput = false;
                mLayout.requestFocus();
            } else if (!mode.equals("diagnostics")) {
                fletInput = true;
                if (flutterView != null) flutterView.requestFocus();
            }
            layoutPanels();
        });
    }

    private void layoutPanels() {
        if (flutterView == null || mFrameLayout == null) return;
        int height = mFrameLayout.getHeight();
        if (height < 2) return;
        int[] origin = new int[2];
        mFrameLayout.getLocationOnScreen(origin);
        int keyboardTop = origin[1] + height;
        WindowInsets insets = getWindow().getDecorView().getRootWindowInsets();
        keyboardShown = false;
        if (Build.VERSION.SDK_INT >= 30 && insets != null) {
            keyboardShown = insets.isVisible(WindowInsets.Type.ime());
            if (keyboardShown) {
                keyboardTop = getWindowManager().getCurrentWindowMetrics().getBounds().bottom
                        - insets.getInsets(WindowInsets.Type.ime()).bottom;
            }
        } else {
            Rect visible = new Rect();
            mFrameLayout.getWindowVisibleDisplayFrame(visible);
            // Legacy Android reports keyboard occlusion through the visible frame.
            // Ignore smaller differences from transient system/navigation bars.
            keyboardShown = origin[1] + height - visible.bottom > height / 6;
            if (keyboardShown) keyboardTop = visible.bottom;
        }
        int overlap = Math.min(height - 2, Math.max(0, origin[1] + height - keyboardTop));
        int available = height - overlap;
        boolean sceneOnly = presentation.equals("scene");
        int fletHeight = sceneOnly ? 0 : presentation.equals("diagnostics")
                ? Math.max(1, available * 2 / 5) : available;
        int sceneHeight = presentation.equals("diagnostics") ? available - fletHeight : available;
        int visibility = sceneOnly ? View.INVISIBLE : View.VISIBLE;
        FrameLayout.LayoutParams sdl = (FrameLayout.LayoutParams) mLayout.getLayoutParams();
        FrameLayout.LayoutParams flet = (FrameLayout.LayoutParams) flutterView.getLayoutParams();
        boolean changed = sdl.height != sceneHeight
                || flet.height != Math.max(1, fletHeight) || flet.bottomMargin != overlap
                || flutterView.getVisibility() != visibility || !presentation.equals(viewportPresentation);
        if (!changed) return;
        viewportPresentation = presentation;
        if (sdl.height != sceneHeight) {
            sdl.height = sceneHeight;
            mLayout.setLayoutParams(sdl);
        }
        if (flet.height != Math.max(1, fletHeight) || flet.bottomMargin != overlap) {
            flet.height = Math.max(1, fletHeight);
            flet.bottomMargin = overlap;
            flutterView.setLayoutParams(flet);
        }
        flutterView.setVisibility(visibility);
        Log.i("SDKRunner", "SDK_RUNNER_VIEWPORT {\"presentation\":\"" + presentation
                + "\",\"scene_height\":" + sceneHeight + ",\"height\":" + height
                + ",\"ime_overlap\":" + overlap + ",\"flet_top\":" + (origin[1] + available - fletHeight)
                + ",\"flet_height\":" + fletHeight + ",\"keyboard_top\":" + keyboardTop + "}");
    }

    @Override protected void onStart() {
        super.onStart();
        if (flutterView != null) layoutPanels();
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
        debugProfile(intent);
    }
    private void debugProfile(Intent intent) {
        String command = intent.getStringExtra("runner.profile");
        if (flutter == null || command == null
                || (getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) == 0) return;
        if (!command.equals("start") && !command.equals("stop")) return;
        new MethodChannel(flutter.getDartExecutor().getBinaryMessenger(), "sdk.runner/profile")
                .invokeMethod(command, null, new MethodChannel.Result() {
                    @Override public void success(Object result) {
                        Log.i("SDKRunner", "SDK_RUNNER_FRAME_PROFILE " + command + " "
                                + String.valueOf(JSONObject.wrap(result)));
                    }
                    @Override public void error(String code, String message, Object details) {
                        Log.e("SDKRunner", "SDK_RUNNER_FRAME_PROFILE_ERROR " + code + " " + message);
                    }
                    @Override public void notImplemented() {
                        Log.e("SDKRunner", "SDK_RUNNER_FRAME_PROFILE_ERROR unavailable");
                    }
                });
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
            if (firstFlutterFrame && level >= TRIM_MEMORY_RUNNING_LOW) {
                flutter.getDartExecutor().notifyLowMemoryWarning();
                flutter.getSystemChannel().sendMemoryPressureWarning();
            }
        }
    }
    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        // Keep Android Back out of Flutter's asynchronous keyboard redispatch.
        // The host owns this callback; the active Flet view receives popRoute.
        if (flutter != null && (fletInput || !presentation.equals("diagnostics"))
                && event.getKeyCode() == KeyEvent.KEYCODE_BACK) {
            if (event.getAction() == KeyEvent.ACTION_UP && !event.isCanceled()) onBackPressed();
            return true;
        }
        return super.dispatchKeyEvent(event);
    }
    @Override public boolean dispatchTouchEvent(MotionEvent event) {
        if (event.getActionMasked() == MotionEvent.ACTION_DOWN && flutterView != null) {
            int[] location = new int[2];
            flutterView.getLocationOnScreen(location);
            float x = event.getRawX(), y = event.getRawY();
            fletInput = flutterView.getVisibility() == View.VISIBLE
                    && x >= location[0] && x < location[0] + flutterView.getWidth()
                    && y >= location[1] && y < location[1] + flutterView.getHeight();
            if (fletInput) flutterView.requestFocus();
            else mLayout.requestFocus();
        }
        return super.dispatchTouchEvent(event);
    }
    @Override public void onBackPressed() {
        if (flutter != null && (presentation.equals("scene") || presentation.equals("interlude"))) {
            // Back opens the same menu during native dialogue or an interlude.
            flutter.getNavigationChannel().pushRouteInformation("/menu");
        } else if (flutter != null && fletInput) {
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
