import sys
import platform


def get_operating_system():
    system = sys.platform

    if system.startswith("linux"):
        return "linux"

    elif system == "win32":
        return "windows"

    elif system == "darwin":
        return "macos"

    return "unsupported"


def get_architecture():
    return platform.machine()


def get_platform_info():

    return {
        "operating_system": get_operating_system(),
        "architecture": get_architecture(),
        "python_version": platform.python_version(),
        "system": platform.system()
    }


if __name__ == "__main__":
    print(get_platform_info())