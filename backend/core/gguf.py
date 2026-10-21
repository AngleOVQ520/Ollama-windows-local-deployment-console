"""GGUF 元数据解析器（纯 Python，流式读取，不加载权重）。

支持 GGUF v2 / v3。会跳过 tokenizer 等大数组，只保留标量与短数组，
并通过张量信息累加得到真实参数量。
"""
from __future__ import annotations

import os
import struct
from typing import Any, BinaryIO, Dict, Optional

from ..i18n import T

GGUF_MAGIC = b"GGUF"

# GGUF 元数据值类型
T_UINT8, T_INT8, T_UINT16, T_INT16, T_UINT32, T_INT32, T_FLOAT32, T_BOOL, \
    T_STRING, T_ARRAY, T_UINT64, T_INT64, T_FLOAT64 = range(13)

_SCALAR = {
    T_UINT8: ("<B", 1), T_INT8: ("<b", 1), T_UINT16: ("<H", 2), T_INT16: ("<h", 2),
    T_UINT32: ("<I", 4), T_INT32: ("<i", 4), T_FLOAT32: ("<f", 4), T_BOOL: ("<?", 1),
    T_UINT64: ("<Q", 8), T_INT64: ("<q", 8), T_FLOAT64: ("<d", 8),
}

# llama.cpp LLAMA_FTYPE -> 量化名称
FILE_TYPES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1",
    10: "Q2_K", 11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M",
    16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K", 19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S",
    22: "IQ3_XS", 23: "IQ3_XXS", 24: "IQ1_S", 25: "IQ4_NL", 26: "IQ3_S", 27: "IQ3_M",
    28: "IQ2_S", 29: "IQ2_M", 30: "IQ4_XS", 31: "IQ1_M", 32: "BF16", 36: "TQ1_0",
    37: "TQ2_0", 38: "MXFP4_MOE",
}

# 超过该长度的数组只记录长度，不保留内容
MAX_KEEP_ARRAY = 64


class GGUFError(Exception):
    pass


class _Reader:
    def __init__(self, fp: BinaryIO, version: int):
        self.fp = fp
        self.version = version

    def read(self, n: int) -> bytes:
        b = self.fp.read(n)
        if len(b) != n:
            raise GGUFError(T("文件意外结束"))
        return b

    def u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.read(8))[0]

    def count(self) -> int:
        return self.u32() if self.version == 1 else self.u64()

    def string(self) -> str:
        n = self.count()
        if n > 1 << 26:
            raise GGUFError(T("字符串长度异常"))
        return self.read(n).decode("utf-8", errors="replace")

    def skip_string(self) -> None:
        n = self.count()
        self.fp.seek(n, os.SEEK_CUR)

    def scalar(self, vtype: int) -> Any:
        fmt, size = _SCALAR[vtype]
        return struct.unpack(fmt, self.read(size))[0]

    def value(self, vtype: int) -> Any:
        if vtype in _SCALAR:
            return self.scalar(vtype)
        if vtype == T_STRING:
            return self.string()
        if vtype == T_ARRAY:
            etype = self.u32()
            n = self.count()
            if n <= MAX_KEEP_ARRAY:
                return [self.value(etype) for _ in range(n)]
            # 大数组：快速跳过
            if etype in _SCALAR:
                self.fp.seek(_SCALAR[etype][1] * n, os.SEEK_CUR)
            elif etype == T_STRING:
                for _ in range(n):
                    self.skip_string()
            else:
                for _ in range(n):
                    self.value(etype)
            return {"__array__": True, "type": etype, "length": n}
        raise GGUFError(T("未知的元数据类型 %s") % vtype)


def read_gguf(path: str, with_tensors: bool = True) -> Dict[str, Any]:
    """读取 GGUF 文件头，返回 {version, tensor_count, metadata, param_count}。"""
    with open(path, "rb", buffering=1 << 20) as fp:
        if fp.read(4) != GGUF_MAGIC:
            raise GGUFError(T("不是有效的 GGUF 文件"))
        version = struct.unpack("<I", fp.read(4))[0]
        if version not in (1, 2, 3):
            raise GGUFError(T("不支持的 GGUF 版本 %s") % version)
        r = _Reader(fp, version)
        tensor_count = r.count()
        kv_count = r.count()
        if kv_count > 1 << 20 or tensor_count > 1 << 24:
            raise GGUFError(T("GGUF 头部数据异常"))
        meta: Dict[str, Any] = {}
        for _ in range(kv_count):
            key = r.string()
            vtype = r.u32()
            meta[key] = r.value(vtype)
        param_count: Optional[int] = None
        mtp_tensors = 0
        if with_tensors:
            total = 0
            for _ in range(tensor_count):
                name = r.string()
                n_dims = r.u32()
                if n_dims > 8:
                    raise GGUFError(T("张量维度异常"))
                elems = 1
                for _ in range(n_dims):
                    elems *= r.u64()
                r.u32()  # ggml type
                r.u64()  # offset
                total += elems
                # MTP / NextN / 草稿头张量识别（Qwen3.5 用 mtp.*，llama.cpp 原生布局用 nextn.*）
                low = name.lower()
                if low.startswith("mtp.") or low.startswith("nextn.") or ".nextn." in low or "mtp_head" in low:
                    mtp_tensors += 1
            param_count = total
    return {"version": version, "tensor_count": tensor_count, "metadata": meta,
            "param_count": param_count, "mtp_tensors": mtp_tensors}


def summarize(info: Dict[str, Any]) -> Dict[str, Any]:
    """从原始元数据中提炼列表展示需要的字段。"""
    meta = info.get("metadata", {})
    arch = meta.get("general.architecture") or ""
    ctx = meta.get("%s.context_length" % arch) if arch else None
    if ctx is None:
        for k, v in meta.items():
            if k.endswith(".context_length") and isinstance(v, int):
                ctx = v
                break
    ftype = meta.get("general.file_type")
    # MTP 判定：显式的 n_layer_nextn / mtp 元数据键，或存在 mtp.* / nextn.* 张量
    mtp_keys = [k for k in meta if "nextn" in k.lower() or "mtp" in k.lower()]
    mtp_layers = next((meta[k] for k in mtp_keys
                       if isinstance(meta[k], int) and ("predict_layers" in k.lower() or "n_layer_nextn" in k.lower()
                                                        or "mtp_num_hidden_layers" in k.lower() or k.lower().endswith("nextn"))), None)
    mtp_tensor_count = info.get("mtp_tensors") or 0
    return {
        "architecture": arch,
        "name": meta.get("general.name") or "",
        "basename": meta.get("general.basename") or "",
        "size_label": meta.get("general.size_label") or "",
        "finetune": meta.get("general.finetune") or "",
        "organization": meta.get("general.organization") or "",
        "context_length": int(ctx) if isinstance(ctx, (int, float)) else None,
        "embedding_length": meta.get("%s.embedding_length" % arch),
        "block_count": meta.get("%s.block_count" % arch),
        "head_count": meta.get("%s.attention.head_count" % arch),
        "expert_count": meta.get("%s.expert_count" % arch),
        "file_type": FILE_TYPES.get(ftype, str(ftype) if ftype is not None else ""),
        "quantization_version": meta.get("general.quantization_version"),
        "param_count": info.get("param_count"),
        "has_chat_template": "tokenizer.chat_template" in meta,
        "gguf_version": info.get("version"),
        "tensor_count": info.get("tensor_count"),
        "mtp_tensor_count": mtp_tensor_count,
        "mtp_layers": mtp_layers,
        "mtp_metadata_keys": mtp_keys[:8],
        "has_mtp": bool(mtp_layers or mtp_tensor_count),
    }


def public_metadata(info: Dict[str, Any], max_str: int = 400) -> Dict[str, Any]:
    """返回可安全序列化给前端的元数据（截断长字符串）。"""
    out = {}
    for k, v in info.get("metadata", {}).items():
        if isinstance(v, str) and len(v) > max_str:
            v = v[:max_str] + T("…（共 %d 字符）") % len(v)
        elif isinstance(v, dict) and v.get("__array__"):
            v = T("[数组 · %d 项]") % v["length"]
        elif isinstance(v, list) and len(v) > 16:
            v = v[:16] + ["…"]
        out[k] = v
    return out


def format_params(n: Optional[int]) -> str:
    if not n:
        return ""
    if n >= 1e12:
        return "%.2fT" % (n / 1e12)
    if n >= 1e9:
        return "%.2fB" % (n / 1e9)
    if n >= 1e6:
        return "%.0fM" % (n / 1e6)
    return str(n)
