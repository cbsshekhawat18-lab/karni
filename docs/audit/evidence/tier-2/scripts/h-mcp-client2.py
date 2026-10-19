import json, os, subprocess, sys, time, select
T2 = os.environ["T2"]
cmd = [f"{T2}/.venv/bin/karni", "mcp"]
env = dict(os.environ, VIRTUAL_ENV=f"{T2}/.venv", PATH=f"{T2}/.venv/bin:" + os.environ["PATH"])
print("$ VIRTUAL_ENV=$T2/.venv", " ".join(cmd), "(cwd = project)")
p = subprocess.Popen(cmd, cwd=f"{T2}/auditapp", env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
def send(m):
    raw=json.dumps(m); print(">>>", raw); p.stdin.write(raw+"\n"); p.stdin.flush()
def recv(t=60):
    dl=time.time()+t
    while time.time()<dl:
        r,_,_=select.select([p.stdout],[],[],0.5)
        if r:
            line=p.stdout.readline()
            if not line: return None
            print("<<<", line.strip()[:2500]); return json.loads(line)
    print("<<< (timeout)"); return None
send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"tier2-audit","version":"0"}}}); recv()
send({"jsonrpc":"2.0","method":"notifications/initialized"})
send({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"context","arguments":{}}}); r=recv()
send({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"rules","arguments":{"procedure":"new-page"}}}); r2=recv()
send({"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"check","arguments":{"path":"/nonexistent.py"}}}); r3=recv()
p.stdin.close(); p.wait(timeout=10)
print("--- stderr ---", p.stderr.read()[-800:])
