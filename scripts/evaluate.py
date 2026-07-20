"""
测评命令行工具
用法:
    python scripts/evaluate.py --mode regex                    # 仅正则
    python scripts/evaluate.py --mode ai                       # 仅AI
    python scripts/evaluate.py --mode compare                  # 对比
    python scripts/evaluate.py --export report.json            # 导出
"""
import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.evaluator import Evaluator


def main():
    parser = argparse.ArgumentParser(description="Waybill AI Parser Evaluation")
    parser.add_argument("--data", default="data/labels.json")
    parser.add_argument("--pdf-dir", default=".")
    parser.add_argument("--mode", choices=["ai", "regex", "compare"], default="compare")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--export", default="")
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()

    data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.data) \
        if not os.path.isabs(args.data) else args.data

    if not os.path.exists(data_path):
        print(f"\n  ERROR: Label file not found: {data_path}")
        print(f"  Create one first. Template: data/labels_example.json\n")
        return 1

    with open(data_path, "r", encoding="utf-8") as f:
        labeled = json.load(f)

    test_cases = labeled.get("test_cases", [])
    if not test_cases:
        print("\n  ERROR: No test cases in label file\n")
        return 1

    print(f"\n  Loaded {len(test_cases)} test cases")

    api_key = args.api_key or os.getenv("DEEPSEEK_API_KEY", "")
    evaluator = Evaluator(api_key=api_key, model=args.model)

    if args.mode == "compare":
        result = evaluator.run_comparison(test_cases, pdf_dir=args.pdf_dir)
        evaluator.print_report(result["AI mode"])
        print("\n  === COMPARISON ===")
        print(f"     AI weighted F1:    {result['comparison']['AI weighted F1']} / 100")
        print(f"     Regex weighted F1: {result['comparison']['Regex weighted F1']} / 100")
        print(f"     AI improvement:    {result['comparison']['AI improvement']}")
    elif args.mode == "ai":
        result = evaluator.evaluate_batch(test_cases, pdf_dir=args.pdf_dir, use_ai=True)
        evaluator.print_report(result)
    else:
        result = evaluator.evaluate_batch(test_cases, pdf_dir=args.pdf_dir, use_ai=False)
        evaluator.print_report(result)

    if args.export:
        export_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.export) \
            if not os.path.isabs(args.export) else args.export
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"  Report exported: {export_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
