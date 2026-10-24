"""Build an installable archive with an explicit allowlist (never include keys)."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    "__init__.py",
    "requirements.txt",
    "pyproject.toml",
    "LICENSE",
    "README.md",
    "README.en.md",
    "api_keys.example.json",
]
FOLDERS = ["simple_api", "web", "locales", "examples", "docs"]


def package():
    destination = ROOT / "dist" / "comfyui-simple-api-0.1.0.zip"
    destination.parent.mkdir(exist_ok=True)
    paths = [ROOT / name for name in FILES]
    for folder in FOLDERS:
        paths.extend(
            path
            for path in (ROOT / folder).rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        )
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(
                path, "comfyui-simple-api/" + path.relative_to(ROOT).as_posix()
            )
    print(destination)


if __name__ == "__main__":
    package()
