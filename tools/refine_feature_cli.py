import argparse
import sys
from pathlib import Path

# ✅ Ensure project root is on sys.path so `import agents...` works
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.feature_refiner_agent import FeatureRefinerAgent, RefinerConfig  # noqa: E402


def refine_file(agent: FeatureRefinerAgent, feature_path: Path, in_place: bool, out_dir: Path):
    raw = feature_path.read_text(encoding="utf-8")
    refined = agent.refine(raw)

    if in_place:
        backup = feature_path.with_suffix(feature_path.suffix + ".bak")
        if not backup.exists():
            backup.write_text(raw, encoding="utf-8")
        feature_path.write_text(refined, encoding="utf-8")
        print(f"✅ Refined in-place: {feature_path} (backup: {backup.name})")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / feature_path.name
        out_path.write_text(refined, encoding="utf-8")
        print(f"✅ Refined output: {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features-dir", default="features", help="Directory containing .feature files")
    ap.add_argument("--in-place", action="store_true", help="Overwrite .feature files in place (creates .bak once)")
    ap.add_argument("--out-dir", default="features/_normalized", help="Output directory if not in-place")
    ap.add_argument("--no-llm", action="store_true", help="Disable LLM refine; deterministic only")
    args = ap.parse_args()

    cfg = RefinerConfig(use_llm=not args.no_llm)
    agent = FeatureRefinerAgent(cfg)

    features_dir = Path(args.features_dir)
    out_dir = Path(args.out_dir)

    if not features_dir.exists():
        raise SystemExit(f"Features dir not found: {features_dir.resolve()}")

    feature_files = list(features_dir.rglob("*.feature"))
    if not feature_files:
        raise SystemExit(f"No .feature files found under: {features_dir.resolve()}")

    for fp in feature_files:
        refine_file(agent, fp, in_place=args.in_place, out_dir=out_dir)


if __name__ == "__main__":
    main()