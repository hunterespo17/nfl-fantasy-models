"""Does the page compute the same projection the model does?

src/calibration.py `apply` and the `ptsAtK` function inside src/report.py are the
same maths written twice, in two languages. They have to agree, because the model
writes proj_ppg into the board and then the PAGE recomputes it from the composite
on every slider move -- so a mismatch shows up as numbers that change the instant
you touch a weight and change back when you reset it.

The comment in calibration.py has claimed for a while that "there is a test that
projects the same board both ways and compares". There wasn't. This is it.

It pulls the real knots off every built board, feeds both implementations the same
composites -- including values deliberately past both ends, which is where the two
are most likely to drift -- and fails if they ever differ by more than a
ten-thousandth of a point.
"""
import json, re, subprocess, sys, shutil
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import calibration

BOARDS = ROOT / "outputs" / "boards"
TOL = 1e-4


def js_fn() -> str:
    """Lift ptsAtK (and the HI_DAMP it reads) straight out of report.py.

    Deliberately extracted from the shipping source rather than copied here --
    a copy would pass this test forever while the page drifted underneath it.
    """
    src = (ROOT / "src" / "report.py").read_text(encoding="utf-8")
    m = re.search(r"const HI_DAMP=[^;]+;", src)
    if not m:
        raise SystemExit("FAIL: HI_DAMP not found in report.py")
    damp = m.group(0)
    i = src.index("function ptsAtK(")
    depth, j = 0, src.index("{", i)
    k = j
    while True:
        if src[k] == "{": depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0: break
        k += 1
    return damp + "\n" + src[i:k + 1]


def main() -> int:
    if not shutil.which("node"):
        print("  skip  node not installed -- cannot compare the page's copy")
        return 0
    boards = sorted(BOARDS.glob("*.json"))
    if not boards:
        print("  skip  no built boards to compare")
        return 0

    fn = js_fn()
    worst, worst_where = 0.0, ""
    for bp in boards:
        d = json.loads(bp.read_text(encoding="utf-8"))
        cal = (d.get("result") or {}).get("calib") or {}
        kn = cal.get("knots") or []
        a, b = float(cal.get("a") or 0.0), float(cal.get("b") or 0.25)
        if len(kn) < 2:
            continue
        lo = min(k[0] for k in kn)
        hi = max(k[0] for k in kn)
        pad = max(10.0, 0.25 * (hi - lo))
        # inside the range, and well past BOTH ends -- the ends are the whole point
        cs = list(np.linspace(lo - pad, hi + pad, 400)) + [k[0] for k in kn]

        py = calibration.apply(np.array(cs, dtype="float64"), a, b, kn)
        script = (fn + "\nconst KN=" + json.dumps(kn) + ";"
                  + "const CS=" + json.dumps([float(x) for x in cs]) + ";"
                  + f"const A={a},B={b};"
                  + "console.log(JSON.stringify(CS.map(c=>ptsAtK(c,KN,A,B))));")
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        if out.returncode != 0:
            print(f"  FAIL  {bp.stem}: the page's copy would not run --\n{out.stderr.strip()[:400]}")
            return 1
        js = np.array(json.loads(out.stdout), dtype="float64")
        diff = np.abs(js - py)
        i = int(np.argmax(diff))
        if diff[i] > worst:
            worst, worst_where = float(diff[i]), f"{bp.stem} at composite {cs[i]:.1f}"
        if diff[i] > TOL:
            print(f"  FAIL  {bp.stem}: model and page disagree by {diff[i]:.4f} pts "
                  f"at composite {cs[i]:.1f} (model {py[i]:.4f}, page {js[i]:.4f})")
            return 1
    print(f"  ok    model and page project identically on {len(boards)} boards "
          f"(worst gap {worst:.2e} pts, {worst_where})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
