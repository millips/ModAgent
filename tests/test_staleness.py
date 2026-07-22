"""待修#5:陈旧 mod 预警 —— nexus 详情按 updated_time 判断是否可能不兼容。"""
import datetime
from modagent.nexus import _staleness

allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

now = datetime.datetime.now(datetime.timezone.utc)
iso = lambda days: (now - datetime.timedelta(days=days)).isoformat()

# 陈旧(>12月):Basic MiniMap 那类 2024 老 mod
r = _staleness(iso(400))   # ~13 个月
check("A1 old mod flagged stale", r and r["stale"] is True and r["months_ago"] >= 12, f"got {r}")
check("A2 stale note mentions 不兼容", "不兼容" in r["note"] and "替代" in r["note"])

# 较新(<12月)不预警
r = _staleness(iso(30))
check("B1 recent mod not stale", r and r["stale"] is False)
check("B2 recent has months_ago", r["months_ago"] <= 2)

# 边界:恰好阈值附近
check("C1 just under threshold not stale", _staleness(iso(11 * 30))["stale"] is False)
check("C2 just over threshold stale", _staleness(iso(13 * 30))["stale"] is True)

# 降级:无时间/坏格式返回 None,绝不阻塞
check("D1 empty → None", _staleness("") is None)
check("D2 None → None", _staleness(None) is None)
check("D3 garbage → None", _staleness("not-a-date") is None)

# Z 结尾的 ISO(UTC)也能解析
check("E1 Z-suffix parsed", _staleness(iso(400).replace("+00:00", "Z"))["stale"] is True)

print("\nALL PASS" if allok else "\nSOME FAILED")
