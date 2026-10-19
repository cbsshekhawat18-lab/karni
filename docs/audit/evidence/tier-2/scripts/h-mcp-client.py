"""Speak raw JSON-RPC (newline-delimited, MCP stdio transport) to `karni mcp`."""
import json, os, subprocess, sys, time, select

T2 = os.environ["T2"]
cmd = [f"{T2}/.venv/bin/karni", "mcp", "--project", f"{T2}/auditapp"]
print("$", " ".join(cmd))
p = subprocess.Popen(cmd, cwd=f"{T2}/auditapp", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

def send(msg):
    raw = json.dumps(msg)
    print(">>>", raw)
    p.stdin.write(raw + "\n"); p.stdin.flush()

def recv(timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r, _, _ = select.select([p.stdout], [], [], 0.5)
        if r:
            line = p.stdout.readline()
            if not line:
                return None
            print("<<<", line.strip()[:3000])
            return json.loads(line)
    print("<<< (timeout)")
    return None

send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "tier2-audit", "version": "0"}}})
init = recv()
send({"jsonrpc": "2.0", "method": "notifications/initialized"})
send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
tools = recv()
send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "rules", "arguments": {"code": "K109"}}})
r3 = recv()
send({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "check", "arguments": {"path": "shop/serializers.py"}}})
r4 = recv()
send({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "context", "arguments": {}}})
r5 = recv(60)
p.stdin.close()
try:
    p.wait(timeout=10)
except subprocess.TimeoutExpired:
    p.terminate()
err = p.stderr.read()
print("--- stderr ---"); print(err[-2000:])
print("--- summary ---")
if tools: print("tools:", [(t["name"], list((t.get("inputSchema") or {}).get("properties", {}).keys())) for t in tools["result"]["tools"]])
for name, r in (("rules K109", r3), ("check serializers.py", r4), ("context", r5)):
    if r and "result" in r:
        txt = "".join(c.get("text", "") for c in r["result"].get("content", []))
        print(f"\n[{name}] isError={r['result'].get('isError')}\n{txt[:1200]}")
    else:
        print(f"\n[{name}] no result: {r}")
