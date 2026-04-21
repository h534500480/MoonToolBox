#define UNICODE
#define _UNICODE

#include <windows.h>

#include <string>
#include <vector>

namespace {

constexpr int kSidebarWidth = 230;
constexpr int kTopbarHeight = 56;

HMENU menu_id(int id) {
    return reinterpret_cast<HMENU>(static_cast<INT_PTR>(id));
}

enum class PageId {
    PcdMap,
    PcdTile,
    Network,
    Costmap,
};

enum ControlId {
    ID_NAV_MAP = 1001,
    ID_NAV_TILE,
    ID_NAV_NETWORK,
    ID_NAV_COSTMAP,
    ID_ACTION_PRIMARY,
    ID_ACTION_SECONDARY,
    ID_STATUS_LABEL,
    ID_PAGE_TITLE,
    ID_OUTPUT_BOX,
    ID_FIELD_1,
    ID_FIELD_2,
    ID_FIELD_3,
    ID_FIELD_4,
    ID_FIELD_5,
    ID_FIELD_6,
};

struct AppState {
    HWND window = nullptr;
    HWND topbar = nullptr;
    HWND sidebar = nullptr;
    HWND content = nullptr;
    HWND page_title = nullptr;
    HWND status = nullptr;
    HWND output = nullptr;
    HWND primary_button = nullptr;
    HWND secondary_button = nullptr;
    HWND labels[6] = {};
    HWND edits[6] = {};
    HWND nav_buttons[4] = {};
    PageId current_page = PageId::PcdMap;
};

AppState g_app;

std::wstring page_title(PageId page) {
    switch (page) {
    case PageId::PcdMap:
        return L"pcd -> pgm";
    case PageId::PcdTile:
        return L"pcd slicing";
    case PageId::Network:
        return L"ip check";
    case PageId::Costmap:
        return L"bag replay";
    }
    return L"tool";
}

std::wstring page_status(PageId page) {
    switch (page) {
    case PageId::PcdMap:
        return L"C++ pcd map core is connected to the new framework.";
    case PageId::PcdTile:
        return L"C++ tile splitter framework is ready.";
    case PageId::Network:
        return L"C++ network scanner framework is ready.";
    case PageId::Costmap:
        return L"C++ costmap framework is ready.";
    }
    return L"Ready";
}

void set_control_text(HWND control, const std::wstring& text) {
    SetWindowTextW(control, text.c_str());
}

void append_output(const std::wstring& text) {
    const int length = GetWindowTextLengthW(g_app.output);
    SendMessageW(g_app.output, EM_SETSEL, length, length);
    SendMessageW(g_app.output, EM_REPLACESEL, FALSE, reinterpret_cast<LPARAM>(text.c_str()));
}

void configure_page(PageId page) {
    g_app.current_page = page;
    set_control_text(g_app.page_title, page_title(page));
    set_control_text(g_app.status, page_status(page));
    SetWindowTextW(g_app.output, L"");

    std::wstring primary = L"Run";
    std::wstring secondary = L"Load Config";
    std::wstring label_texts[6];
    std::wstring values[6];

    switch (page) {
    case PageId::PcdMap:
        primary = L"Generate Map";
        secondary = L"Browse";
        label_texts[0] = L"Input PCD";
        label_texts[1] = L"Output Dir";
        label_texts[2] = L"Base Name";
        label_texts[3] = L"Resolution";
        label_texts[4] = L"Clip Min Z";
        label_texts[5] = L"Clip Max Z";
        values[0] = L"G:\\path\\map.pcd";
        values[1] = L"G:\\ros_proj\\ros_tool\\output";
        values[2] = L"map";
        values[3] = L"0.05";
        values[4] = L"-1.0";
        values[5] = L"2.0";
        append_output(L"[INFO] pcd map page ready\r\n");
        append_output(L"[INFO] next step: wire this button to pcd_map_cli.exe\r\n");
        break;
    case PageId::PcdTile:
        primary = L"Split Tiles";
        secondary = L"Browse";
        label_texts[0] = L"Input PCD";
        label_texts[1] = L"Output Dir";
        label_texts[2] = L"Tile Size";
        label_texts[3] = L"Overlap";
        label_texts[4] = L"Format";
        label_texts[5] = L"Zip Output";
        values[0] = L"G:\\path\\map.pcd";
        values[1] = L"G:\\ros_proj\\ros_tool\\output_tiles";
        values[2] = L"20.0";
        values[3] = L"0.0";
        values[4] = L"binary";
        values[5] = L"false";
        append_output(L"[INFO] pcd slicing page ready\r\n");
        append_output(L"[INFO] metadata stub is implemented in C++\r\n");
        break;
    case PageId::Network:
        primary = L"Scan Network";
        secondary = L"Export";
        label_texts[0] = L"Prefix";
        label_texts[1] = L"Start";
        label_texts[2] = L"End";
        label_texts[3] = L"Timeout(ms)";
        label_texts[4] = L"Filter";
        label_texts[5] = L"Threads";
        values[0] = L"192.168.1";
        values[1] = L"1";
        values[2] = L"32";
        values[3] = L"400";
        values[4] = L"";
        values[5] = L"64";
        append_output(L"[INFO] network page ready\r\n");
        append_output(L"[INFO] C++ scanner skeleton returns mock devices\r\n");
        break;
    case PageId::Costmap:
        primary = L"Process Costmap";
        secondary = L"Browse";
        label_texts[0] = L"Input YAML";
        label_texts[1] = L"Output Dir";
        label_texts[2] = L"FPS";
        label_texts[3] = L"Export GIF";
        label_texts[4] = L"Threshold";
        label_texts[5] = L"Footprint";
        values[0] = L"G:\\path\\costmap.yaml";
        values[1] = L"G:\\ros_proj\\ros_tool\\output_costmap";
        values[2] = L"2.0";
        values[3] = L"true";
        values[4] = L"99";
        values[5] = L"0.70x0.40";
        append_output(L"[INFO] costmap page ready\r\n");
        append_output(L"[INFO] summary export stub is implemented in C++\r\n");
        break;
    }

    SetWindowTextW(g_app.primary_button, primary.c_str());
    SetWindowTextW(g_app.secondary_button, secondary.c_str());
    for (int i = 0; i < 6; ++i) {
        SetWindowTextW(g_app.labels[i], label_texts[i].c_str());
        SetWindowTextW(g_app.edits[i], values[i].c_str());
    }
}

void layout(HWND hwnd) {
    RECT rc{};
    GetClientRect(hwnd, &rc);
    const int width = rc.right - rc.left;
    const int height = rc.bottom - rc.top;

    MoveWindow(g_app.topbar, 0, 0, width, kTopbarHeight, TRUE);
    MoveWindow(g_app.sidebar, 0, kTopbarHeight, kSidebarWidth, height - kTopbarHeight, TRUE);
    MoveWindow(g_app.content, kSidebarWidth, kTopbarHeight, width - kSidebarWidth, height - kTopbarHeight, TRUE);

    int sidebar_y = 18;
    for (int i = 0; i < 4; ++i) {
        MoveWindow(g_app.nav_buttons[i], 18, sidebar_y, kSidebarWidth - 36, 38, TRUE);
        sidebar_y += 46;
    }

    const int content_x = 24;
    int y = 18;
    MoveWindow(g_app.page_title, content_x, y, 460, 28, TRUE);
    y += 36;
    MoveWindow(g_app.status, content_x, y, width - kSidebarWidth - 48, 22, TRUE);
    y += 32;

    for (int i = 0; i < 6; ++i) {
        MoveWindow(g_app.labels[i], content_x, y + i * 46, 130, 22, TRUE);
        MoveWindow(g_app.edits[i], content_x + 140, y + i * 46 - 2, width - kSidebarWidth - 200, 26, TRUE);
    }

    y += 6 * 46 + 8;
    MoveWindow(g_app.primary_button, content_x, y, 140, 34, TRUE);
    MoveWindow(g_app.secondary_button, content_x + 152, y, 140, 34, TRUE);
    y += 48;
    MoveWindow(g_app.output, content_x, y, width - kSidebarWidth - 48, height - kTopbarHeight - y - 18, TRUE);
}

void on_primary_action() {
    switch (g_app.current_page) {
    case PageId::PcdMap:
        append_output(L"[ACTION] generate map clicked\r\n");
        append_output(L"[NEXT] hook to pcd_map_cli.exe with collected parameters\r\n");
        break;
    case PageId::PcdTile:
        append_output(L"[ACTION] split tiles clicked\r\n");
        append_output(L"[NEXT] hook to pcd_tile_cli.exe\r\n");
        break;
    case PageId::Network:
        append_output(L"[ACTION] scan network clicked\r\n");
        append_output(L"[NEXT] hook to network_scan_cli.exe\r\n");
        break;
    case PageId::Costmap:
        append_output(L"[ACTION] process costmap clicked\r\n");
        append_output(L"[NEXT] hook to costmap_cli.exe\r\n");
        break;
    }
}

LRESULT CALLBACK WindowProc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    switch (message) {
    case WM_CREATE: {
        HFONT font = static_cast<HFONT>(GetStockObject(DEFAULT_GUI_FONT));
        g_app.window = hwnd;
        g_app.topbar = CreateWindowExW(0, L"STATIC", L" ROS Tool Suite /tools/cpp", WS_CHILD | WS_VISIBLE, 0, 0, 0, 0, hwnd, nullptr, nullptr, nullptr);
        g_app.sidebar = CreateWindowExW(0, L"STATIC", L"", WS_CHILD | WS_VISIBLE, 0, 0, 0, 0, hwnd, nullptr, nullptr, nullptr);
        g_app.content = CreateWindowExW(0, L"STATIC", L"", WS_CHILD | WS_VISIBLE, 0, 0, 0, 0, hwnd, nullptr, nullptr, nullptr);
        g_app.page_title = CreateWindowExW(0, L"STATIC", L"", WS_CHILD | WS_VISIBLE, 0, 0, 0, 0, g_app.content, menu_id(ID_PAGE_TITLE), nullptr, nullptr);
        g_app.status = CreateWindowExW(0, L"STATIC", L"", WS_CHILD | WS_VISIBLE, 0, 0, 0, 0, g_app.content, menu_id(ID_STATUS_LABEL), nullptr, nullptr);
        g_app.primary_button = CreateWindowExW(0, L"BUTTON", L"", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON, 0, 0, 0, 0, g_app.content, menu_id(ID_ACTION_PRIMARY), nullptr, nullptr);
        g_app.secondary_button = CreateWindowExW(0, L"BUTTON", L"", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON, 0, 0, 0, 0, g_app.content, menu_id(ID_ACTION_SECONDARY), nullptr, nullptr);
        g_app.output = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE | WS_VSCROLL | ES_LEFT | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY, 0, 0, 0, 0, g_app.content, menu_id(ID_OUTPUT_BOX), nullptr, nullptr);

        const wchar_t* nav_texts[4] = {L"pcd -> pgm", L"pcd slicing", L"ip check", L"bag replay"};
        const int nav_ids[4] = {ID_NAV_MAP, ID_NAV_TILE, ID_NAV_NETWORK, ID_NAV_COSTMAP};
        for (int i = 0; i < 4; ++i) {
            g_app.nav_buttons[i] = CreateWindowExW(0, L"BUTTON", nav_texts[i], WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON, 0, 0, 0, 0, g_app.sidebar, menu_id(nav_ids[i]), nullptr, nullptr);
            SendMessageW(g_app.nav_buttons[i], WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
        }

        for (int i = 0; i < 6; ++i) {
            g_app.labels[i] = CreateWindowExW(0, L"STATIC", L"", WS_CHILD | WS_VISIBLE, 0, 0, 0, 0, g_app.content, menu_id(ID_FIELD_1 + i), nullptr, nullptr);
            g_app.edits[i] = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL, 0, 0, 0, 0, g_app.content, nullptr, nullptr, nullptr);
            SendMessageW(g_app.labels[i], WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
            SendMessageW(g_app.edits[i], WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
        }

        SendMessageW(g_app.topbar, WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
        SendMessageW(g_app.page_title, WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
        SendMessageW(g_app.status, WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
        SendMessageW(g_app.primary_button, WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
        SendMessageW(g_app.secondary_button, WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
        SendMessageW(g_app.output, WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);

        configure_page(PageId::PcdMap);
        layout(hwnd);
        return 0;
    }
    case WM_SIZE:
        layout(hwnd);
        return 0;
    case WM_COMMAND: {
        switch (LOWORD(wparam)) {
        case ID_NAV_MAP:
            configure_page(PageId::PcdMap);
            return 0;
        case ID_NAV_TILE:
            configure_page(PageId::PcdTile);
            return 0;
        case ID_NAV_NETWORK:
            configure_page(PageId::Network);
            return 0;
        case ID_NAV_COSTMAP:
            configure_page(PageId::Costmap);
            return 0;
        case ID_ACTION_PRIMARY:
            on_primary_action();
            return 0;
        case ID_ACTION_SECONDARY:
            append_output(L"[ACTION] secondary button clicked\r\n");
            return 0;
        default:
            return 0;
        }
    }
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    default:
        return DefWindowProcW(hwnd, message, wparam, lparam);
    }
}

}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int show_command) {
    const wchar_t class_name[] = L"RosToolSuiteWindow";

    WNDCLASSW wc{};
    wc.lpfnWndProc = WindowProc;
    wc.hInstance = instance;
    wc.lpszClassName = class_name;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);

    RegisterClassW(&wc);

    HWND window = CreateWindowExW(
        0,
        class_name,
        L"ROS Tool Suite C++",
        WS_OVERLAPPEDWINDOW,
        CW_USEDEFAULT,
        CW_USEDEFAULT,
        1280,
        860,
        nullptr,
        nullptr,
        instance,
        nullptr);

    if (window == nullptr) {
        return 0;
    }

    ShowWindow(window, show_command);
    UpdateWindow(window);

    MSG msg{};
    while (GetMessageW(&msg, nullptr, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    return 0;
}
