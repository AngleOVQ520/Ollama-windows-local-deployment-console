"""项目内所有路径的唯一来源。所有读写都限制在项目目录内。"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
MODELS_DIR = os.path.join(ROOT, "models")
RUNTIME_DIR = os.path.join(ROOT, "runtime")
PYLIB_DIR = os.path.join(RUNTIME_DIR, "pylib")
LOG_DIR = os.path.join(RUNTIME_DIR, "logs")
TMP_DIR = os.path.join(RUNTIME_DIR, "tmp")
HOME_DIR = os.path.join(RUNTIME_DIR, "home")
PYCACHE_DIR = os.path.join(RUNTIME_DIR, "pycache")
WEB_DIR = os.path.join(ROOT, "web")
STATIC_DIR = os.path.join(WEB_DIR, "static")
DB_PATH = os.path.join(DATA_DIR, "app.db")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
DEFAULT_PARTITION_DIR = os.path.join(MODELS_DIR, "default")
# 生图：产出图片与参考图上传目录（都限制在项目目录内）
IMAGE_OUT_DIR = os.path.join(DATA_DIR, "images")
IMAGE_UPLOAD_DIR = os.path.join(TMP_DIR, "image-uploads")
IMAGE_ASSET_DIR = os.path.join(MODELS_DIR, "image")
SDCPP_DIR = os.path.join(RUNTIME_DIR, "sdcpp")


def ensure_dirs():
    for d in (DATA_DIR, MODELS_DIR, LOG_DIR, TMP_DIR, HOME_DIR, PYCACHE_DIR, BACKUP_DIR,
              DEFAULT_PARTITION_DIR, IMAGE_OUT_DIR, IMAGE_UPLOAD_DIR, IMAGE_ASSET_DIR,
              os.path.join(HOME_DIR, "AppData", "Local"),
              os.path.join(HOME_DIR, "AppData", "Roaming")):
        os.makedirs(d, exist_ok=True)


def sandbox_env(base=None):
    """子进程环境：把 HOME / APPDATA / TEMP 全部重定向到项目 runtime 目录。"""
    env = dict(base if base is not None else os.environ)
    env.update({
        "USERPROFILE": HOME_DIR,
        "HOME": HOME_DIR,
        "LOCALAPPDATA": os.path.join(HOME_DIR, "AppData", "Local"),
        "APPDATA": os.path.join(HOME_DIR, "AppData", "Roaming"),
        "TEMP": TMP_DIR,
        "TMP": TMP_DIR,
    })
    return env
