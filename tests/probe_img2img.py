"""sd-cli 图生图（参考图编辑）能力探针。
用法：python tests/probe_img2img.py
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SD = os.path.join(ROOT, "runtime", "sdcpp", "bin", "sd-cli.exe")
BIN = os.path.join(ROOT, "runtime", "sdcpp", "bin")
CUDA = os.path.join(ROOT, "runtime", "sdcpp", "cuda")
REF = os.path.join(ROOT, "runtime", "shots", "t2i-probe.png")
OUT = os.path.join(ROOT, "runtime", "shots", "i2i-probe.png")


def run(args, tag):
    env = dict(os.environ)
    env["PATH"] = BIN + os.pathsep + CUDA + os.pathsep + env["PATH"]
    env["PYTHONIOENCODING"] = "utf-8"
    t0 = time.time()
    p = subprocess.run([SD] + args, cwd=ROOT, env=env, capture_output=True)
    out = p.stdout.decode("utf-8", errors="replace")
    err = p.stderr.decode("utf-8", errors="replace")
    dur = time.time() - t0
    print("== %s == rc=%s  %.1fs" % (tag, p.returncode, dur))
    tail = [l for l in (out + err).splitlines() if l.strip()][-8:]
    for l in tail:
        print("   ", l[:200])
    return p.returncode


base = ["--diffusion-model", os.path.join(ROOT, "qwen_image_2.1-Q4_K_M.gguf"),
        "--vae", os.path.join(ROOT, "models", "image", "qwen_image_2.1_vae_bf16.safetensors"),
        "--llm", os.path.join(ROOT, "models", "image", "Qwen3VL-8B-Instruct-Q4_K_M.gguf"),
        "--cfg-scale", "6.0", "--sampling-method", "euler", "--offload-to-cpu",
        "-W", "1024", "-H", "1024", "--steps", "20", "--seed", "42"]

WORKFLOWS = [
    ("图生图 · 纯参考图（无文字指令，-r）", base + ["-r", REF, "-p", "一只猫", "-o", OUT]),
    ("图生图 · 参考图 + 编辑指令（-r + -p）", base + [
        "--llm_vision", os.path.join(ROOT, "models", "image", "mmproj-Qwen3VL-8B-Instruct-F16.gguf"),
        "-r", REF, "-p", "把牌子上的文字 'qwen2.1.cpp' 改成 '欧拉玛最终兵器'，保持字体与构图不变", "-o", OUT]),
    ("图生图 · 双参考图（-r 两次）", base + [
        "--llm_vision", os.path.join(ROOT, "models", "image", "mmproj-Qwen3VL-8B-Instruct-F16.gguf"),
        "-r", REF, "-r", REF,
        "-p", "把两张图的猫合成同一场景，牌子文字改为 '双图合成'", "-o", OUT]),
]

for tag, args in WORKFLOWS:
    rc = run(args, tag)
    ok = os.path.isfile(OUT) and os.path.getsize(OUT) > 10000
    print("   出图: %s (%s 字节)" % (ok, os.path.getsize(OUT) if os.path.isfile(OUT) else 0))
    if ok:
        import shutil
        shutil.move(OUT, OUT.replace("i2i-probe", "i2i-%d" % WORKFLOWS.index((tag, args))))
    if rc != 0 and not ok:
        print("   → 该用法不可用")