from pathlib import Path
import sys


def _prefer_project_venv() -> None:
    project_root = Path(__file__).resolve().parent.parent
    site_packages = project_root / ".venv" / "Lib" / "site-packages"
    if site_packages.exists():
        site_packages_str = str(site_packages)
        if site_packages_str not in sys.path:
            sys.path.insert(0, site_packages_str)


_prefer_project_venv()
