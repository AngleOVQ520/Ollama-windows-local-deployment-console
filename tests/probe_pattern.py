"""用 Qwen-Image-2.1 从参考图提取印花，输出铺满整图的图案（不含产品）。

用法：python tests/probe_pattern.py
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SD = os.path.join(ROOT, "runtime", "sdcpp", "bin", "sd-cli.exe")
BIN = os.path.join(ROOT, "runtime", "sdcpp", "bin")
CUDA = os.path.join(ROOT, "runtime", "sdcpp", "cuda")
# 用已去水印的白底图做参考，避免把原图水印「Bubble」一并复刻进印花
REF = os.path.join(ROOT, "runtime", "shots", "product-white-v2.png")
OUT = os.path.join(ROOT, "runtime", "shots", "pattern-tile.png")

MODEL = os.path.join(ROOT, "qwen_image_2.1-Q4_K_M.gguf")
VAE = os.path.join(ROOT, "models", "image", "qwen_image_2.1_vae_bf16.safetensors")
LLM = os.path.join(ROOT, "models", "image", "Qwen3VL-8B-Instruct-Q4_K_M.gguf")
VISION = os.path.join(ROOT, "models", "image", "mmproj-Qwen3VL-8B-Instruct-F16.gguf")

PROMPT = (
    "参考图是一块印花面料的平铺照。请把这幅印花完整提取出来，输出一张铺满整张图片的印花图案。"
    "画面从边缘到边缘全部被该印花铺满，四方连续、可无缝拼接。"
    "配色严格保持原样：浅米白（象牙白）为底色，酒红／枣红色的佩斯利、花卉与几何纹样均匀密布；"
    "保留曼陀罗团花、藤蔓花枝、菱形与三角滚边等细节元素。"
    "整体是明亮通透的浅色平面印花，底色必须保持大面积的米白，不得整体压暗。"
    "画面中不要出现裤子、裤腰、裤腿、缝线、衣架、模特、立体褶皱、投影。"
    "不要出现任何文字、水印、标识。平面正视、均匀布光、纹理清晰锐利。"
)

NEGATIVE = (
    "墨绿色, 黑色背景, 深色, 暗调, 布料微距, 针织纹理, 灯芯绒, 裤子, 裤腿, 服装, 产品, "
    "衣架, 模特, 立体, 褶皱, 阴影, 文字, 水印, Bubble, 边框, 空白, 单一物体, "
    "dark, black background, fabric closeup, knit texture, corduroy, garment, pants, "
    "hanger, watermark, text, shadow"
)

STEPS = int(os.environ.get("STEPS", "24"))
CFG = float(os.environ.get("CFG", "5.0"))
SEED = int(os.environ.get("SEED", "20261021"))
W = int(os.environ.get("W", "1024"))
H = int(os.environ.get("H", "1024"))

args = ["--diffusion-model", MODEL, "--vae", VAE, "--llm", LLM, "--llm_vision", VISION,
        "-r", REF, "-p", PROMPT, "-n", NEGATIVE,
        "--cfg-scale", str(CFG), "--sampling-method", "euler", "--offload-to-cpu",
        "-W", str(W), "-H", str(H), "--steps", str(STEPS), "--seed", str(SEED),
        "--flow-shift", "3",
        "-o", OUT]

env = dict(os.environ)
env["PATH"] = BIN + os.pathsep + CUDA + os.pathsep + env["PATH"]
env["PYTHONIOENCODING"] = "utf-8"

print("参考图: %s" % REF)
print("输出  : %s" % OUT)
print("参数  : %dx%d  steps=%s  cfg=%s  seed=%s" % (W, H, STEPS, CFG, SEED))
sys.stdout.flush()

t0 = time.time()
p = subprocess.run([SD] + args, cwd=ROOT, env=env, capture_output=True)
log = p.stdout.decode("utf-8", errors="replace") + p.stderr.decode("utf-8", errors="replace")
dur = time.time() - t0

keep = [l for l in log.splitlines() if any(k in l for k in
        ("error", "Error", "ERROR", "save result", "completed in", "s/it", "failed"))]
for l in keep[-18:]:
    print("  ", l[:220])
print("耗时 %.1f 秒  rc=%s" % (dur, p.returncode))
if os.path.isfile(OUT):
    print("出图成功：%s  %s 字节" % (OUT, os.path.getsize(OUT)))
else:
    print("未生成输出文件")
    print(log[-3000:])