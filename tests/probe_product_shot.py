"""用 Qwen-Image-2.1 把参考图转为白底标准商品图（图生图 / 参考图编辑）。

用法：python tests/probe_product_shot.py
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SD = os.path.join(ROOT, "runtime", "sdcpp", "bin", "sd-cli.exe")
BIN = os.path.join(ROOT, "runtime", "sdcpp", "bin")
CUDA = os.path.join(ROOT, "runtime", "sdcpp", "cuda")
REF = os.path.join(ROOT, "dece2567a0ebd461b39e504ff173ecf5.jpg")
OUT = os.path.join(ROOT, "runtime", "shots", "product-white.png")

MODEL = os.path.join(ROOT, "qwen_image_2.1-Q4_K_M.gguf")
VAE = os.path.join(ROOT, "models", "image", "qwen_image_2.1_vae_bf16.safetensors")
LLM = os.path.join(ROOT, "models", "image", "Qwen3VL-8B-Instruct-Q4_K_M.gguf")
VISION = os.path.join(ROOT, "models", "image", "mmproj-Qwen3VL-8B-Instruct-F16.gguf")

PROMPT = (
    "把参考图中的这条印花长裤做成专业电商白底商品图。"
    "【必须删除】彻底去掉画面中所有的水印文字「Bubble」、粉色泡泡图标、半透明水印层，"
    "去掉衣架、挂钩、墙面、木板等全部背景物体，背景中不留任何文字或图案。"
    "【背景】替换为纯白色 #FFFFFF，绝对均匀、无渐变、无阴影杂色、无竖线纹理。"
    "【主体】裤子按原始款式、颜色、花纹、下摆滚边和版型忠实保留，"
    "正面平铺居中展示，裤腰到裤脚完整入画，裤腿自然垂顺。"
    "【布光】柔和均匀的影棚柔光，裤脚下方仅保留极淡的自然接触阴影。"
    "高分辨率，织物纹理与印花细节清晰锐利，标准商品摄影。"
)

STEPS = int(os.environ.get("STEPS", "20"))
CFG = os.environ.get("CFG", "4.0")
SEED = int(os.environ.get("SEED", "20261019"))
W = int(os.environ.get("W", "768"))
H = int(os.environ.get("H", "1024"))

args = ["--diffusion-model", MODEL, "--vae", VAE, "--llm", LLM, "--llm_vision", VISION,
        "-r", REF, "-p", PROMPT,
        "--cfg-scale", CFG, "--sampling-method", "euler", "--offload-to-cpu",
        "-W", str(W), "-H", str(H), "--steps", str(STEPS), "--seed", str(SEED),
        "--flow-shift", "3",
        "-o", OUT]

env = dict(os.environ)
env["PATH"] = BIN + os.pathsep + CUDA + os.pathsep + env["PATH"]
env["PYTHONIOENCODING"] = "utf-8"

print("参考图: %s (%s 字节)" % (REF, os.path.getsize(REF) if os.path.isfile(REF) else "缺失"))
print("输出  : %s" % OUT)
print("参数  : %dx%d  steps=%s  cfg=%s  seed=%s" % (W, H, STEPS, CFG, SEED))
sys.stdout.flush()

t0 = time.time()
p = subprocess.run([SD] + args, cwd=ROOT, env=env, capture_output=True)
log = (p.stdout.decode("utf-8", errors="replace") + p.stderr.decode("utf-8", errors="replace"))
dur = time.time() - t0

keep = [l for l in log.splitlines() if any(k in l for k in
        ("error", "Error", "ERROR", "save result", "completed in", "s/it", "warning", "failed"))]
for l in keep[-25:]:
    print("  ", l[:220])
print("耗时 %.1f 秒  rc=%s" % (dur, p.returncode))
if os.path.isfile(OUT):
    print("出图成功：%s  %s 字节" % (OUT, os.path.getsize(OUT)))
else:
    print("未生成输出文件")
    print(log[-3000:])