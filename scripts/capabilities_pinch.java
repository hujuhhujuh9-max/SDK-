import android.os.SystemClock;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.MotionEvent;
import java.lang.reflect.Method;

/** A shell-UID Android acceptance driver, never packaged in the application. */
public final class capabilities_pinch {
    private final Object manager;
    private final Method inject;
    private final long downTime = SystemClock.uptimeMillis();
    private int accepted = 0;

    private capabilities_pinch() throws Exception {
        Class<?> type;
        try {
            type = Class.forName("android.hardware.input.InputManagerGlobal");
        } catch (ClassNotFoundException olderAndroid) {
            type = Class.forName("android.hardware.input.InputManager");
        }
        manager = type.getMethod("getInstance").invoke(null);
        inject = type.getMethod("injectInputEvent", InputEvent.class, int.class);
    }

    private void event(int action, int pointers, float x0, float x1, float y) throws Exception {
        MotionEvent.PointerProperties[] properties = new MotionEvent.PointerProperties[pointers];
        MotionEvent.PointerCoords[] coordinates = new MotionEvent.PointerCoords[pointers];
        for (int index = 0; index < pointers; index++) {
            properties[index] = new MotionEvent.PointerProperties();
            properties[index].id = index;
            properties[index].toolType = MotionEvent.TOOL_TYPE_FINGER;
            coordinates[index] = new MotionEvent.PointerCoords();
            coordinates[index].x = index == 0 ? x0 : x1;
            coordinates[index].y = y;
            coordinates[index].pressure = 1;
            coordinates[index].size = 1;
        }
        MotionEvent event = MotionEvent.obtain(downTime, SystemClock.uptimeMillis(), action, pointers,
                properties, coordinates, 0, 0, 1, 1, 0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0);
        try {
            if (!Boolean.TRUE.equals(inject.invoke(manager, event, 2))) {
                throw new IllegalStateException("Android rejected injected pointer event");
            }
            accepted++;
        } finally {
            event.recycle();
        }
    }

    public static void main(String[] args) {
        try {
            if (args.length != 4) throw new IllegalArgumentException("Expected center x, y, initial radius, final radius");
            float x = Float.parseFloat(args[0]), y = Float.parseFloat(args[1]);
            float initial = Float.parseFloat(args[2]), end = Float.parseFloat(args[3]);
            if (!(x > end && y > 0 && initial >= 16 && end > initial && end < 2048)) {
                throw new IllegalArgumentException("Pinch coordinates are outside fixture limits");
            }
            capabilities_pinch driver = new capabilities_pinch();
            driver.event(MotionEvent.ACTION_DOWN, 1, x - initial, x + initial, y);
            driver.event(MotionEvent.ACTION_POINTER_DOWN | (1 << MotionEvent.ACTION_POINTER_INDEX_SHIFT),
                    2, x - initial, x + initial, y);
            for (int step = 1; step <= 20; step++) {
                SystemClock.sleep(25);
                float radius = initial + (end - initial) * step / 20;
                driver.event(MotionEvent.ACTION_MOVE, 2, x - radius, x + radius, y);
            }
            driver.event(MotionEvent.ACTION_POINTER_UP | (1 << MotionEvent.ACTION_POINTER_INDEX_SHIFT),
                    2, x - end, x + end, y);
            driver.event(MotionEvent.ACTION_UP, 1, x - end, x + end, y);
            System.out.println("SDK_CAP_PINCH {\"accepted_events\":" + driver.accepted
                    + ",\"pointers\":2,\"initial_radius\":" + initial + ",\"final_radius\":" + end + "}");
        } catch (Exception error) {
            error.printStackTrace();
            System.exit(1);
        }
    }
}
