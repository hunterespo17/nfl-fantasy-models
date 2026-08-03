"""
Temporary diagnostic. Reproduces the training step and writes a full report
(library versions, data profile, and the complete error) to
outputs/diagnose.txt so it can be reviewed. Safe to delete afterward.

    py scripts\\_diagnose.py
"""
import io
import os
import pathlib
import platform
import sys
import traceback

os.environ.setdefault("POLARS_SKIP_CPU_CHECK", "1")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

_buf = io.StringIO()


def log(*parts) -> None:
    line = " ".join(str(p) for p in parts)
    print(line)
    _buf.write(line + "\n")


def _version(mod_name: str) -> str:
    try:
        mod = __import__(mod_name)
        return getattr(mod, "__version__", "?")
    except Exception as exc:  # noqa: BLE001
        return f"(not importable: {exc})"


def main() -> None:
    log("=" * 60)
    log("ENVIRONMENT")
    log("=" * 60)
    log("python  ", sys.version.replace("\n", " "))
    log("platform", platform.platform(), "| machine:", platform.machine())
    for m in ("numpy", "pandas", "scipy", "sklearn", "joblib", "nflreadpy", "polars", "pyarrow"):
        log(f"{m:10}", _version(m))

    try:
        from src import config, data, features, model

        log("\n" + "=" * 60)
        log("FEATURES TABLE")
        log("=" * 60)
        feat = data.load_df("features", folder=config.PROCESSED_DIR)
        if feat is None:
            log("No features table found — run scripts/02 first.")
            return
        log("shape:", feat.shape)
        log("seasons:", sorted(int(s) for s in feat["season"].dropna().unique()))
        log("positions:", sorted(feat["position"].dropna().unique().tolist()))

        numeric, categorical = features.feature_columns(feat)
        log("numeric features:", len(numeric))
        log("categorical features:", categorical)

        # dtype sanity — a numeric feature stored as object could break sklearn.
        import numpy as np

        dt = feat[numeric].dtypes
        log("numeric dtypes present:", sorted({str(x) for x in dt}))
        non_float = [c for c in numeric if not np.issubdtype(feat[c].dtype, np.number)]
        log("NON-numeric feature columns (should be empty):", non_float)
        arr = feat[numeric].to_numpy(dtype="float64", na_value=np.nan)
        log("any +/-inf in numeric block:", bool(np.isinf(arr).any()))
        log("all-NaN numeric columns:", [c for c in numeric if feat[c].isna().all()])
        log("rows with NaN target:", int(feat["fantasy_points"].isna().sum()))

        log("\n" + "=" * 60)
        log("REPRODUCE TRAINING (this is where step 3 failed)")
        log("=" * 60)
        seasons = sorted(int(s) for s in feat["season"].dropna().unique())
        holdout = seasons[-1]
        train = feat[feat["season"] < holdout]
        log(f"training on seasons < {holdout}: {train.shape[0]:,} rows")
        try:
            model.train_weekly_model(train, numeric, categorical)
            log("RESULT: training SUCCEEDED on the train subset (unexpected).")
            model.train_weekly_model(feat, numeric, categorical)
            log("RESULT: training SUCCEEDED on the full data too.")
        except Exception:
            log("RESULT: training FAILED. Full traceback below:\n")
            log(traceback.format_exc())
    except Exception:
        log("\nUnexpected error while running diagnostic:\n")
        log(traceback.format_exc())
    finally:
        try:
            from src import config

            out_dir = pathlib.Path(config.OUTPUT_DIR)
        except Exception:
            out_dir = pathlib.Path(__file__).resolve().parents[1] / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "diagnose.txt").write_text(_buf.getvalue(), encoding="utf-8")
        print(f"\nWrote full report to: {out_dir / 'diagnose.txt'}")


if __name__ == "__main__":
    main()
