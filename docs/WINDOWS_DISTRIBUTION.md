# Windows 离线发行版

适用 Windows 10/11 x64。发行包包含 Python 编译后的后端、托盘、四个 Release C++ 算法、网页与所需运行库。目标电脑不需要 Python、Node.js、CMake 或 Visual Studio，也不需要联网下载这些依赖。页面由系统默认浏览器打开，建议使用 Edge 或 Chrome。

## 安装与启动

运行 ROSPlatformSetup.exe，安装后打开桌面/开始菜单的 ROSPlatform。便携包解压后运行 runtime/ROSPlatform.exe；不要只复制该 EXE，旁边的运行库必须完整保留。

程序只监听 127.0.0.1，不使用局域网固定 IP，不对其他电脑开放文件操作接口。首次优先 8100，之后优先上次实际端口；冲突时系统分配空闲端口。程序持有监听套接字直到退出，不采用先探测后释放的方式。浏览器自动打开实际地址，不要固定收藏端口。再次启动同一用户实例会校验身份并打开已有页面，托盘“退出平台”关闭本进程服务。

机器人地址是独立的 ROS Bridge WebSocket 地址，在平台设置中填写；机器人仍需运行 ROS 节点及 rosbridge。平台离线安装并不包含机器人上的 ROS 系统。

个人数据保存在 `%LOCALAPPDATA%\ROSPlatform\UserData`，其中 desktop.log 为日志，endpoint.json 记录实际端口，config 为后端配置，browser-profile.json 保存任务及界面偏好。导航运行租约不保存，重启不会自动下发任务。浏览器设置同步用于跨端口恢复，重要任务仍可使用任务文件导出。安装升级/卸载均保留个人数据。

## 开发电脑构建

需要 Python 3.12 x64（含 Tcl/Tk）、Node.js/npm、CMake、Ninja、VS C++ Build Tools、Inno Setup 6。首次构建需要网络获取依赖；依赖版本固定在 scripts/requirements-package.txt 与 frontend/package-lock.json，安装到目标电脑时无需下载。

```powershell
cd G:\ros_proj\ros_platform
.\scripts\build_installer.cmd
```

输出为 release/ROSPlatformSetup.exe、release/ROSPlatform.zip 及 SHA256 校验文件。只构建便携包可运行 scripts/build_dist.cmd。程序清单按运行文件白名单汇集，不复制源码、地图、个人 ROS 地址、任务或日志；打包前重新编译 C++ 并检查源码/调试符号泄露。C++ 静态链接 MSVC 运行库，后端依赖由 Nuitka standalone 汇集。

## 交付边界

编译减少源码直接暴露，不保证不能逆向；浏览器执行的 JavaScript 仍然可查看。代码签名证书未配置时安装程序未签名，Windows 可能显示发布者验证提示。Linux/ARM 不适用本安装包；需要另行构建。

测试模式：`runtime\ROSPlatform.exe --headless --no-browser --data-dir "D:\临时验证数据" --port 8100`。仅 --data-dir 指定的位置会存储测试状态，--port 为优先值而非强制值。默认启动不显示控制台，异常记录在数据目录 desktop.log 并显示错误窗口。
