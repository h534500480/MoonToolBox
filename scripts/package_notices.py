"""功能说明：为离线发行包保留 Python/前端依赖的版本、许可和版权文本。"""
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys


def main():
    """读取构建环境元数据，只复制许可文本，不把依赖源码或缓存放入发行目录。"""
    target = Path(sys.argv[1]) / "licenses"
    target.mkdir(parents=True, exist_ok=True)
    inventory = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        inventory.append({"name": name, "version": distribution.version, "license": distribution.metadata.get("License-Expression") or distribution.metadata.get("License", "见许可文件")})
        for file in distribution.files or []:
            if file.name.lower().startswith(("license", "copying", "notice")) and file.suffix.lower() not in {".py", ".pyc"}:
                destination = target / "python" / name / str(file).replace("/", "_").replace("\\", "_")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(distribution.locate_file(file), destination)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copyfile(python_license, target / "Python-LICENSE.txt")
    frontend = Path(sys.argv[2])
    lock = json.loads((frontend / "package-lock.json").read_text(encoding="utf-8"))
    for relative, package in lock.get("packages", {}).items():
        if not relative or package.get("dev"):
            continue
        inventory.append({"name": relative, "version": package.get("version"), "license": package.get("license")})
        directory = frontend / relative
        for file in directory.iterdir():
            if file.is_file() and file.name.lower().startswith(("license", "copying", "notice")):
                destination = target / "frontend" / relative.replace("/", "_") / file.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, destination)
    (target / "dependency-versions.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
