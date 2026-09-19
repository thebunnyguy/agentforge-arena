import json, sys, pathlib, collections
A, B = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])   # dirs containing tasks/<id>.json
MUT = ("mutants_generated","mutants_unsupported","mutants_declared_equivalent","mutants_intercepted_by_regression_or_scope","mutants_relevant","killed_total","killed_by_hidden_test","killed_by_timeout_or_error","survived_count","kill_rate")
PROV = ("task_json_hash","snapshot_hash","reference_hash","grading_hash","controls_hash")
def digest(p):
    d = json.loads(p.read_text())
    mut = next((c for c in d["checks"] if c["check_id"].startswith("mutation")), None)
    return {
        "version": d["task_version"], "status": d["status"],
        "checks": [(c["check_id"], c["status"], c["severity"]) for c in d["checks"]],
        "controls": [(c["name"], c["kind"], c["verdict"], c["matched_expectation"], c["status"]) for c in d["controls"]],
        "mutation": {k: (mut["evidence"].get(k) if mut else None) for k in MUT},
        "survived": sorted(str(s) for s in (mut["evidence"].get("survived") or [])) if mut else [],
        "findings": sorted((f.get("finding_id") or f.get("id") or f.get("check_id"), f.get("severity")) for f in d.get("findings", [])),
        "provenance": {k: d["provenance"].get(k) for k in PROV},
    }
ta = {p.stem: p for p in (A/"tasks").glob("*.json")}; tb = {p.stem: p for p in (B/"tasks").glob("*.json")}
common = sorted(set(ta) & set(tb)); only = sorted(set(ta) ^ set(tb))
diffs = collections.defaultdict(list)
for t in common:
    x, y = digest(ta[t]), digest(tb[t])
    for k in x:
        if x[k] != y[k]: diffs[t].append((k, x[k], y[k]))
counts = lambda P: collections.Counter(digest(p)["status"] for p in P.values())
print(f"A={A.name}  B={B.name}")
print(f"tasks compared: {len(common)}  (only in one side: {only or 'none'})")
print("status counts A:", dict(counts({t: ta[t] for t in common})))
print("status counts B:", dict(counts({t: tb[t] for t in common})))
if not diffs: print("RESULT: IDENTICAL on status, every check result, every control verdict, mutation accounting, findings and provenance hashes for all", len(common), "tasks")
else:
    print("RESULT: DIFFERENCES")
    for t, ds in diffs.items():
        for k, x, y in ds: print(f"  {t} :: {k}\n      A={x}\n      B={y}")
