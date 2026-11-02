"""Which video encoder this computer can use. Every renderer writes its settings for NVENC (the Nvidia card's encoder) and passes them through `adapt`,
which keeps them when NVENC opens here and turns them into the matching libx264 (processor) settings when it does not (no Nvidia card, or a driver too old
for the installed ffmpeg)."""
import subprocess

_nvenc: bool | None = None

PRESETS = {"p1": "ultrafast", "p2": "superfast", "p3": "veryfast", "p4": "faster", "p5": "fast", "p6": "medium", "p7": "slow"}
DROPPED = {"-rc", "-b:v", "-forced-idr", "-spatial-aq", "-temporal-aq"}          # NVENC-only options, each followed by its value


def nvenc_available() -> bool:
    """True when ffmpeg can open h264_nvenc here. Probed once per run."""
    global _nvenc
    if _nvenc is None:
        try:
            r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1", "-frames:v", "1",
                                "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True, timeout=60)
            _nvenc = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _nvenc = False
    return _nvenc


def to_x264(args: list) -> list:
    """NVENC settings -> libx264 settings: preset p1..p7 -> ultrafast..slow, -cq N -> -crf N, NVENC-only options dropped."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a in DROPPED or (a == "-tune" and args[i + 1:i + 2] == ["hq"]):
            i += 2
            continue
        if a == "h264_nvenc":
            out.append("libx264")
        elif a == "-preset" and i + 1 < len(args) and args[i + 1] in PRESETS:
            out += ["-preset", PRESETS[args[i + 1]]]
            i += 1
        elif a == "-cq":
            out.append("-crf")
        else:
            out.append(a)
        i += 1
    return out


def adapt(args: list) -> list:
    """`args` as written for h264_nvenc, in a form that works on this computer."""
    return list(args) if nvenc_available() else to_x264(args)
