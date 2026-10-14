# -*- coding: utf-8 -*-
"""
图片上传工具：把 data/images/ 下的文章图片上传到你的文件服务器。

支持三种模式（upload/config.json 里 type 字段）：
  webdav  — NAS / 坚果云 / Alist / Nextcloud 等，PUT + 自动 MKCOL 建目录
  http    — 任意接收 PUT 的自建服务（可选 Bearer token / 自定义头）
  s3      — S3 / MinIO / OSS 兼容（需要 boto3：pip install boto3）

用法:
  python upload/upload_images.py            # 按 upload/config.json 上传（增量，跳过已传）
  python upload/upload_images.py --dry      # 只列出将上传的文件
  python upload/upload_images.py --force    # 忽略清单全部重传

上传成功后：
  - 若 auto_switch_site_to_remote=true，自动把 site.config.json 的
    image_base_url 切到 public_base_url → 重新 python generator/build.py 即完成切换。
"""
import base64
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
IMAGES_DIR = ROOT / "data" / "images"
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.json"
SITE_CONFIG = ROOT / "site.config.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print("未找到 upload/config.json。请先：")
        print("  cp upload/config.example.json upload/config.json  然后填写你的服务器信息。")
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def collect_files() -> list:
    if not IMAGES_DIR.exists():
        print("没有 data/images/ 目录，请先运行爬虫。")
        sys.exit(1)
    files = sorted(p for p in IMAGES_DIR.rglob("*") if p.is_file())
    if not files:
        print("data/images/ 为空。")
        sys.exit(1)
    return files


class Uploader:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.mode = cfg.get("type", "webdav")
        self.s = requests.Session()
        headers = dict(cfg.get("headers") or {})
        if self.mode == "webdav":
            if cfg.get("username"):
                basic = base64.b64encode(
                    f"{cfg['username']}:{cfg.get('password','')}".encode()).decode()
                headers["Authorization"] = f"Basic {basic}"
        elif self.mode == "http":
            if cfg.get("token"):
                headers["Authorization"] = f"Bearer {cfg['token']}"
        self.s.headers.update(headers)
        if self.mode == "s3":
            import boto3  # noqa
            self.s3 = boto3.client("s3")
            self.bucket = cfg["s3_bucket"]
            self.prefix = cfg.get("s3_prefix", "").lstrip("/")

    def remote_key(self, rel: str) -> str:
        return rel.replace("\\", "/")

    def ensure_dir_webdav(self, rel_dir: str):
        parts = [p for p in rel_dir.split("/") if p]
        cur = self.cfg["endpoint"].rstrip("/")
        for part in parts:
            cur += "/" + part
            try:
                r = self.s.request("MKCOL", cur + "/", timeout=20)
                if r.status_code not in (200, 201, 301, 405):
                    print(f"  MKCOL {cur}/ -> {r.status_code}")
            except requests.RequestException as e:
                print(f"  MKCOL fail {cur}: {e}")

    def upload_one(self, path: Path) -> str:
        rel = path.relative_to(IMAGES_DIR)
        key = self.remote_key(str(rel))
        data = path.read_bytes()
        if self.mode == "webdav":
            self.ensure_dir_webdav(str(rel.parent))
            url = self.cfg["endpoint"].rstrip("/") + "/" + key
            r = self.s.put(url, data=data, timeout=120)
            r.raise_for_status()
        elif self.mode == "http":
            url = self.cfg["endpoint"].rstrip("/") + "/" + key
            r = self.s.put(url, data=data, timeout=120)
            r.raise_for_status()
        elif self.mode == "s3":
            self.s3.put_object(
                Bucket=self.bucket, Key=(self.prefix + key).lstrip("/"), Body=data)
        else:
            raise ValueError(f"未知 type: {self.mode}")
        return key


def switch_site_to_remote(cfg: dict):
    public = (cfg.get("public_base_url") or "").rstrip("/")
    if not cfg.get("auto_switch_site_to_remote") or not public:
        return
    conf = {}
    if SITE_CONFIG.exists():
        conf = json.loads(SITE_CONFIG.read_text(encoding="utf-8"))
    if conf.get("image_base_url") == public:
        return
    conf["image_base_url"] = public + "/"
    SITE_CONFIG.write_text(json.dumps(conf, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"site.config.json image_base_url → {public}/  （重新运行 generator/build.py 生效）")


def main():
    dry = "--dry" in sys.argv
    force = "--force" in sys.argv
    cfg = load_config()
    files = collect_files()
    manifest = {}
    if MANIFEST_PATH.exists() and not force:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    todo = []
    for p in files:
        rel = p.relative_to(IMAGES_DIR).as_posix()
        stat = p.stat()
        sig = f"{stat.st_size}:{int(stat.st_mtime)}"
        if not force and manifest.get(rel) == sig:
            continue
        todo.append(p)
    print(f"共 {len(files)} 张图片，待上传 {len(todo)} 张（mode={cfg.get('type')}）")
    if dry:
        for p in todo[:30]:
            print("  ", p.relative_to(IMAGES_DIR).as_posix())
        if len(todo) > 30:
            print(f"  ... 等 {len(todo)} 张")
        return
    if not todo:
        switch_site_to_remote(cfg)
        print("没有需要上传的新图片。")
        return

    up = Uploader(cfg)
    ok = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=int(cfg.get("concurrency", 4))) as pool:
        futs = {pool.submit(up.upload_one, p): p for p in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            p = futs[fut]
            rel = p.relative_to(IMAGES_DIR).as_posix()
            try:
                fut.result()
                ok += 1
                stat = p.stat()
                manifest[rel] = f"{stat.st_size}:{int(stat.st_mtime)}"
            except Exception as e:
                fail += 1
                print(f"  FAIL {rel}: {e}")
            if i % 200 == 0:
                print(f"  progress {i}/{len(todo)} ok={ok} fail={fail} {time.time()-t0:.0f}s")

    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"完成：成功 {ok}，失败 {fail}，用时 {time.time()-t0:.0f}s")
    if fail == 0:
        switch_site_to_remote(cfg)


if __name__ == "__main__":
    main()
