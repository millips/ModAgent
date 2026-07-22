"""战役3 块3:export_diag_bundle —— 诊断包脱敏导出。
重点:绝不含任何明文 API key(配置按字段名脱敏 + 全文 _scrub 兜底)。"""
import os, sys, json, tempfile, zipfile

from modagent import diagnostics as diag
from modagent.config import Config
from modagent.db import InstalledMod

TMP = tempfile.mkdtemp()
OUT = os.path.join(TMP, "out")
allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

def w(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f: f.write(data)

# 造游戏 + 框架日志(日志里故意混入一个疑似 key,测 _scrub 兜底)
G = os.path.join(TMP, "REPO")
NEXUS_KEY = "abcdef0123456789abcdef0123456789abcdef01"   # 40 位十六进制,像 Nexus key
LLM_KEY = "sk-proj-SUPERSECRETLLMKEY1234567890"
w(os.path.join(G, "BepInEx", "LogOutput.log"),
  f"[Info] starting\n[Error] leaked token in log: {LLM_KEY}\n[Info] done")

cfg = Config(nexus_api_key=NEXUS_KEY, llm_api_key=LLM_KEY, tavily_api_key="tvly-xyz789abc123def456",
             game_slug="repo", game_root=G)
mods = [InstalledMod(id="m1", name="MoreHead", version="1.5", snapshot_id="",
                     installed_by="modagent", game_slug="repo")]
oplog = [{"id": 1, "timestamp": 123.0, "action": "install",
          "details": json.dumps({"id": "m1", "note": f"key was {NEXUS_KEY}"})}]

r = diag.export_diag_bundle(G, "repo", cfg, mods, oplog, out_dir=OUT, app_version="v1.0-dev")
check("A1 bundle created", "bundle" in r and os.path.exists(r["bundle"]))
check("A2 marked redacted", r.get("redacted") is True)

# 打开 zip 检查内容
with zipfile.ZipFile(r["bundle"]) as z:
    names = z.namelist()
    blobs = {n: z.read(n).decode("utf-8", errors="replace") for n in names}

check("B1 has manifest", "manifest.json" in names)
check("B2 has operation_log", "operation_log.json" in names)
check("B3 has framework log", any(n.startswith("logs/BepInEx") for n in names))

manifest = json.loads(blobs["manifest.json"])
check("C1 manifest has version/platform", manifest.get("app_version") == "v1.0-dev"
      and "python" in manifest and "platform" in manifest)
check("C2 installed mods listed", manifest["installed_mods"][0]["name"] == "MoreHead")
check("C3 frameworks detected", manifest["frameworks"] == ["BepInEx"])
# 配置脱敏:三个 key 字段抹掉,非敏感字段保留
cr = manifest["config_redacted"]
check("C4 nexus key redacted", cr["nexus_api_key"] == "***REDACTED***")
check("C5 llm key redacted", cr["llm_api_key"] == "***REDACTED***")
check("C6 tavily key redacted", cr["tavily_api_key"] == "***REDACTED***")
check("C7 non-secret field kept", cr.get("game_slug") == "repo")

# ── 核心安全断言:整个 zip 的任何文件都不得出现明文 key ──
def leaked(secret):
    return [n for n, b in blobs.items() if secret in b]
check("D1 nexus key nowhere in bundle", not leaked(NEXUS_KEY), f"leaked in {leaked(NEXUS_KEY)}")
check("D2 llm key nowhere in bundle", not leaked(LLM_KEY), f"leaked in {leaked(LLM_KEY)}")
check("D3 tavily key nowhere in bundle", not leaked("tvly-xyz789abc123def456"))
# _scrub 兜底:日志里混入的 key 也被抹(证明不止靠字段名脱敏)
check("D4 scrub caught key in log body",
      "***REDACTED***" in blobs[[n for n in names if n.startswith("logs/")][0]])

# ── 边界:游戏目录不存在 ──
r2 = diag.export_diag_bundle(os.path.join(TMP, "gone"), "repo", cfg, mods, oplog, out_dir=OUT)
check("E1 missing game dir → error", "error" in r2)

# ── 无 operation_log 也能打包 ──
r3 = diag.export_diag_bundle(G, "repo", cfg, mods, None, out_dir=OUT)
check("E2 works without oplog", "bundle" in r3 and "operation_log.json" not in
      zipfile.ZipFile(r3["bundle"]).namelist())

print("\nALL PASS" if allok else "\nSOME FAILED")
