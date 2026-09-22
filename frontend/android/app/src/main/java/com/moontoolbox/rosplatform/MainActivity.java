// 功能说明：Android 全屏容器与键盘遮挡信息桥接，页面按实际可用区域放置输入层。
package com.moontoolbox.rosplatform;

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
        ViewCompat.setOnApplyWindowInsetsListener(decorView, (view, insets) -> {
            if (getBridge() != null && getBridge().getWebView() != null) {
                View webView = getBridge().getWebView();
                int[] webLocation = new int[2], decorLocation = new int[2];
                webView.getLocationOnScreen(webLocation);
                decorView.getLocationOnScreen(decorLocation);
                int ime = insets.isVisible(WindowInsetsCompat.Type.ime()) ? insets.getInsets(WindowInsetsCompat.Type.ime()).bottom : 0;
                int overlap = ime == 0 ? 0 : Math.max(0, webLocation[1] + webView.getHeight() - (decorLocation[1] + decorView.getHeight() - ime));
                // 只传数值；CSS 像素换算使用 WebView 的实际设备像素比。
                getBridge().getWebView().evaluateJavascript("window.dispatchEvent(new CustomEvent('ros-window-insets',{detail:{imeOverlap:" + overlap + "/(window.devicePixelRatio||1)}}))", null);
            }
            return WindowInsetsCompat.CONSUMED;
        });

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
        registerPlugin(RosFilePickerPlugin.class);
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
