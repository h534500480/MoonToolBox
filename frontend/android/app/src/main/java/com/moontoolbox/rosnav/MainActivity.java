package com.moontoolbox.rosnav;

import android.content.res.Configuration;
import android.os.Bundle;
import android.view.View;

import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.core.view.WindowInsetsControllerCompat;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    /**
     * 功能说明：
     * 进入 Android 端后持续启用沉浸式全屏，避免横屏主视图被系统状态栏、
     * 导航栏或安全区额外挤占空间。某些机型旋转或切后台后会恢复系统栏，
     * 因此需要在多个生命周期阶段重复应用。
     */
    private void applyImmersiveMode() {
        if (getWindow() == null || getWindow().getDecorView() == null) {
            return;
        }

        View decorView = getWindow().getDecorView();
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        ViewCompat.setOnApplyWindowInsetsListener(decorView, (view, insets) -> WindowInsetsCompat.CONSUMED);

        WindowInsetsControllerCompat controller =
            ViewCompat.getWindowInsetsController(decorView);
        if (controller == null) {
            return;
        }

        controller.setSystemBarsBehavior(
            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        );
        controller.hide(WindowInsetsCompat.Type.systemBars());
        controller.hide(WindowInsetsCompat.Type.displayCutout());
        decorView.requestApplyInsets();
    }

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        applyImmersiveMode();
    }

    @Override
    public void onResume() {
        super.onResume();
        applyImmersiveMode();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            applyImmersiveMode();
        }
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        applyImmersiveMode();
    }
}
