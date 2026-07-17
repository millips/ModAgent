"""战役3 块1:classify_oserror —— 文件操作错误的可行动归因。"""
import os, sys, errno, tempfile

from modagent import diagnostics as diag

allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

def mkerr(errno_=None, winerror=None):
    e = OSError()
    if errno_ is not None:
        e.errno = errno_
    if winerror is not None:
        e.winerror = winerror
    return e

# ── 各 errno/winerror 分支 ──
r = diag.classify_oserror(mkerr(winerror=32))
check("A1 sharing violation → locked", r["code"] == "locked" and "退出游戏" in r["action"])

r = diag.classify_oserror(mkerr(errno_=errno.EACCES))
check("A2 EACCES → permission", r["code"] == "permission" and "只读" in r["action"])

r = diag.classify_oserror(mkerr(winerror=5))
check("A3 winerror 5 → permission", r["code"] == "permission")

r = diag.classify_oserror(mkerr(errno_=errno.ENOSPC), path=os.getcwd())
check("A4 ENOSPC → disk_full + 剩余空间", r["code"] == "disk_full" and "剩余" in r["reason"],
      f"reason={r['reason']}")

r = diag.classify_oserror(mkerr(errno_=errno.ENOENT))
check("A5 ENOENT → not_found", r["code"] == "not_found")

r = diag.classify_oserror(mkerr(errno_=errno.EROFS))
check("A6 EROFS → readonly", r["code"] == "readonly")

r = diag.classify_oserror(mkerr(errno_=9999))
check("A7 unknown errno → unknown", r["code"] == "unknown")

# 优先级:同时有 winerror 32 和 EACCES(Windows 锁文件的典型组合)→ 判 locked 而非 permission
r = diag.classify_oserror(mkerr(errno_=errno.EACCES, winerror=32))
check("A8 sharing+EACCES prioritizes locked", r["code"] == "locked")

# 每个结果都带非空的 action(可行动性保证)
for code in ("locked", "permission", "disk_full", "not_found", "readonly", "unknown"):
    rr = diag.classify_oserror(mkerr(winerror=32) if code == "locked" else
                               mkerr(errno_={"permission": errno.EACCES, "disk_full": errno.ENOSPC,
                                             "not_found": errno.ENOENT, "readonly": errno.EROFS,
                                             "unknown": 9999}[code]))
    check(f"A9-{code} has non-empty action", bool(rr["action"].strip()))

# ── 真实文件锁(Windows:打开文件时删除 → PermissionError winerror 32)──
if sys.platform == "win32":
    tmp = tempfile.mkdtemp()
    locked = os.path.join(tmp, "locked.bin")
    with open(locked, "w") as f:
        f.write("data")
    fh = open(locked, "r")   # 持有读句柄
    try:
        os.remove(locked)
        check("B1 real lock raised", False, "expected PermissionError")
    except OSError as ex:
        r = diag.classify_oserror(ex, path=locked)
        check("B1 real file-lock classified", r["code"] in ("locked", "permission"),
              f"code={r['code']} winerror={getattr(ex,'winerror',None)}")
    finally:
        fh.close()
else:
    check("B1 (skipped, non-win32)", True)

print("\nALL PASS" if allok else "\nSOME FAILED")
