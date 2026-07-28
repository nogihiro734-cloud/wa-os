#!/usr/bin/env python3
"""
WA-OS Policy Drift Behavioral Test Runner

This program performs four tasks:

1. Validates tests/policy_drift_cases.json
2. Displays the registered Policy Drift test cases
3. Creates a response-entry template
4. Produces a report from AI responses and human review results

Important:
This runner does not automatically declare an AI response safe.

Automatic text matching is only an early-warning sensor.
Final PASS / WARNING / FAIL decisions remain subject to human review.

Core principle:
"Humans do not surrender the question.
AI does not take the question away from humans."
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CASES_PATH = Path("tests/policy_drift_cases.json")
DEFAULT_RESPONSES_PATH = Path("tests/policy_drift_responses.json")
DEFAULT_REPORT_PATH = Path("tests/policy_drift_report.json")

ALLOWED_HUMAN_RATINGS = {
    "pass",
    "warning",
    "fail",
    "not_reviewed",
}


class PolicyDriftValidationError(Exception):
    """Raised when the Policy Drift test data is invalid."""


def load_json(path: Path) -> dict[str, Any]:
    """Load a UTF-8 JSON file and return its contents."""

    if not path.exists():
        raise PolicyDriftValidationError(
            f"Required file was not found: {path}"
        )

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyDriftValidationError(
            f"Could not read file: {path}\n{exc}"
        ) from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PolicyDriftValidationError(
            f"Invalid JSON in {path}\n"
            f"Line: {exc.lineno}, Column: {exc.colno}\n"
            f"Reason: {exc.msg}"
        ) from exc

    if not isinstance(data, dict):
        raise PolicyDriftValidationError(
            f"The root value of {path} must be a JSON object."
        )

    return data


def save_json(path: Path, data: dict[str, Any]) -> None:
    """Save a dictionary as formatted UTF-8 JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def require_non_empty_string(
    value: Any,
    field_name: str,
) -> None:
    """Require a value to be a non-empty string."""

    if not isinstance(value, str) or not value.strip():
        raise PolicyDriftValidationError(
            f"{field_name} must be a non-empty string."
        )


def require_string_list(
    value: Any,
    field_name: str,
) -> None:
    """Require a value to be a non-empty list of strings."""

    if not isinstance(value, list) or not value:
        raise PolicyDriftValidationError(
            f"{field_name} must be a non-empty list."
        )

    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise PolicyDriftValidationError(
                f"{field_name}[{index}] must be a non-empty string."
            )


def extract_cases(
    suite: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract every test case from every category."""

    categories = suite.get("categories")

    if not isinstance(categories, list) or not categories:
        raise PolicyDriftValidationError(
            "categories must be a non-empty list."
        )

    all_cases: list[dict[str, Any]] = []

    for category in categories:
        if not isinstance(category, dict):
            raise PolicyDriftValidationError(
                "Each category must be a JSON object."
            )

        cases = category.get("cases")

        if not isinstance(cases, list) or not cases:
            raise PolicyDriftValidationError(
                "Each category must contain a non-empty cases list."
            )

        for case in cases:
            if not isinstance(case, dict):
                raise PolicyDriftValidationError(
                    "Each test case must be a JSON object."
                )

            case_copy = dict(case)
            case_copy["_category_id"] = category.get("category_id")
            case_copy["_category_name"] = category.get("name")
            all_cases.append(case_copy)

    return all_cases


def validate_test_suite(
    suite: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate the structure and governance settings of the suite."""

    require_non_empty_string(
        suite.get("schema_version"),
        "schema_version",
    )
    require_non_empty_string(
        suite.get("suite_name"),
        "suite_name",
    )
    require_non_empty_string(
        suite.get("description"),
        "description",
    )
    require_non_empty_string(
        suite.get("principle"),
        "principle",
    )

    evaluation_scale = suite.get("evaluation_scale")

    if not isinstance(evaluation_scale, dict):
        raise PolicyDriftValidationError(
            "evaluation_scale must be a JSON object."
        )

    for rating in ("pass", "warning", "fail"):
        require_non_empty_string(
            evaluation_scale.get(rating),
            f"evaluation_scale.{rating}",
        )

    categories = suite.get("categories")
    category_ids: set[str] = set()
    case_ids: set[str] = set()

    if not isinstance(categories, list) or not categories:
        raise PolicyDriftValidationError(
            "categories must be a non-empty list."
        )

    for category_index, category in enumerate(categories):
        if not isinstance(category, dict):
            raise PolicyDriftValidationError(
                f"categories[{category_index}] must be an object."
            )

        category_id = category.get("category_id")
        category_name = category.get("name")
        category_purpose = category.get("purpose")

        require_non_empty_string(
            category_id,
            f"categories[{category_index}].category_id",
        )
        require_non_empty_string(
            category_name,
            f"categories[{category_index}].name",
        )
        require_non_empty_string(
            category_purpose,
            f"categories[{category_index}].purpose",
        )

        if category_id in category_ids:
            raise PolicyDriftValidationError(
                f"Duplicate category_id: {category_id}"
            )

        category_ids.add(category_id)

        cases = category.get("cases")

        if not isinstance(cases, list) or not cases:
            raise PolicyDriftValidationError(
                f"Category {category_id} must contain cases."
            )

        for case_index, case in enumerate(cases):
            if not isinstance(case, dict):
                raise PolicyDriftValidationError(
                    f"{category_id}.cases[{case_index}] must be an object."
                )

            case_id = case.get("id")

            require_non_empty_string(
                case_id,
                f"{category_id}.cases[{case_index}].id",
            )
            require_non_empty_string(
                case.get("prompt"),
                f"{case_id}.prompt",
            )
            require_string_list(
                case.get("expected_behavior"),
                f"{case_id}.expected_behavior",
            )
            require_string_list(
                case.get("fail_signals"),
                f"{case_id}.fail_signals",
            )

            if case_id in case_ids:
                raise PolicyDriftValidationError(
                    f"Duplicate case id: {case_id}"
                )

            case_ids.add(case_id)

    require_string_list(
        suite.get("global_fail_conditions"),
        "global_fail_conditions",
    )

    if suite.get("human_review_required") is not True:
        raise PolicyDriftValidationError(
            "human_review_required must be true."
        )

    if suite.get("automatic_policy_activation_allowed") is not False:
        raise PolicyDriftValidationError(
            "automatic_policy_activation_allowed must be false."
        )

    return extract_cases(suite)


def print_suite_summary(
    suite: dict[str, Any],
    cases: list[dict[str, Any]],
) -> None:
    """Print a readable summary of the Policy Drift suite."""

    categories = suite["categories"]

    print()
    print("=" * 72)
    print("WA-OS POLICY DRIFT TEST SUITE")
    print("=" * 72)
    print(f"Suite: {suite['suite_name']}")
    print(f"Schema version: {suite['schema_version']}")
    print(f"Categories: {len(categories)}")
    print(f"Test cases: {len(cases)}")
    print(f"Human review required: {suite['human_review_required']}")
    print(
        "Automatic policy activation allowed: "
        f"{suite['automatic_policy_activation_allowed']}"
    )
    print()
    print("Core principle:")
    print(suite["principle"])
    print()

    for category in categories:
        print("-" * 72)
        print(
            f"{category['category_id']} "
            f"| {category['name']} "
            f"| {len(category['cases'])} cases"
        )
        print(category["purpose"])

        for case in category["cases"]:
            print(f"  - {case['id']}: {case['prompt']}")

    print("-" * 72)
    print("Validation result: PASS")
    print("=" * 72)
    print()


def create_response_template(
    suite: dict[str, Any],
    cases: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Create a file in which AI responses can be entered."""

    response_entries: list[dict[str, Any]] = []

    for case in cases:
        response_entries.append(
            {
                "case_id": case["id"],
                "category_id": case["_category_id"],
                "prompt": case["prompt"],
                "ai_provider": "",
                "model": "",
                "response": "",
                "human_rating": "not_reviewed",
                "human_notes": "",
            }
        )

    template = {
        "schema_version": "1.0.0",
        "suite_name": suite["suite_name"],
        "suite_schema_version": suite["schema_version"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "instructions": {
            "response": (
                "Paste the AI response exactly as received."
            ),
            "human_rating": (
                "Choose pass, warning, fail, or not_reviewed."
            ),
            "human_notes": (
                "Explain the reason for the human judgment."
            ),
        },
        "responses": response_entries,
    }

    save_json(output_path, template)

    print(f"Response template created: {output_path}")
    print(
        "Paste each AI response into the corresponding "
        "\"response\" field."
    )


def normalize_text(text: str) -> str:
    """Normalize text for simple warning-signal matching."""

    lowered = text.casefold()
    lowered = re.sub(r"\s+", "", lowered)
    lowered = re.sub(
        r"[、。！？!?・「」『』（）()［］\[\]【】:：;；,.]",
        "",
        lowered,
    )
    return lowered


def find_fail_signal_matches(
    response_text: str,
    fail_signals: list[str],
) -> list[str]:
    """
    Find direct or near-direct fail-signal phrases.

    This is only an early-warning sensor.
    It is not a semantic safety judgment.
    """

    normalized_response = normalize_text(response_text)
    matches: list[str] = []

    for signal in fail_signals:
        normalized_signal = normalize_text(signal)

        if normalized_signal and normalized_signal in normalized_response:
            matches.append(signal)

    return matches


def validate_response_file(
    response_data: dict[str, Any],
    case_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate a completed or partially completed response file."""

    responses = response_data.get("responses")

    if not isinstance(responses, list):
        raise PolicyDriftValidationError(
            "The response file must contain a responses list."
        )

    seen_case_ids: set[str] = set()

    for index, entry in enumerate(responses):
        if not isinstance(entry, dict):
            raise PolicyDriftValidationError(
                f"responses[{index}] must be an object."
            )

        case_id = entry.get("case_id")

        require_non_empty_string(
            case_id,
            f"responses[{index}].case_id",
        )

        if case_id not in case_map:
            raise PolicyDriftValidationError(
                f"Unknown case_id in response file: {case_id}"
            )

        if case_id in seen_case_ids:
            raise PolicyDriftValidationError(
                f"Duplicate response for case_id: {case_id}"
            )

        seen_case_ids.add(case_id)

        response_text = entry.get("response", "")

        if not isinstance(response_text, str):
            raise PolicyDriftValidationError(
                f"{case_id}.response must be a string."
            )

        human_rating = entry.get(
            "human_rating",
            "not_reviewed",
        )

        if human_rating not in ALLOWED_HUMAN_RATINGS:
            raise PolicyDriftValidationError(
                f"{case_id}.human_rating must be one of: "
                + ", ".join(sorted(ALLOWED_HUMAN_RATINGS))
            )

        human_notes = entry.get("human_notes", "")

        if not isinstance(human_notes, str):
            raise PolicyDriftValidationError(
                f"{case_id}.human_notes must be a string."
            )

    return responses


def evaluate_responses(
    suite: dict[str, Any],
    cases: list[dict[str, Any]],
    response_data: dict[str, Any],
) -> dict[str, Any]:
    """Create a Policy Drift report."""

    case_map = {
        case["id"]: case
        for case in cases
    }

    responses = validate_response_file(
        response_data,
        case_map,
    )

    results: list[dict[str, Any]] = []
    rating_counter: Counter[str] = Counter()

    for entry in responses:
        case_id = entry["case_id"]
        case = case_map[case_id]
        response_text = entry.get("response", "").strip()
        human_rating = entry.get(
            "human_rating",
            "not_reviewed",
        )
        human_notes = entry.get(
            "human_notes",
            "",
        ).strip()

        if not response_text:
            automated_status = "not_tested"
            matched_signals: list[str] = []
        else:
            matched_signals = find_fail_signal_matches(
                response_text,
                case["fail_signals"],
            )

            if matched_signals:
                automated_status = "warning_signal_detected"
            else:
                automated_status = "no_direct_signal_detected"

        if human_rating == "not_reviewed":
            final_status = "human_review_required"
        else:
            final_status = human_rating

        rating_counter[final_status] += 1

        results.append(
            {
                "case_id": case_id,
                "category_id": case["_category_id"],
                "category_name": case["_category_name"],
                "prompt": case["prompt"],
                "ai_provider": entry.get("ai_provider", ""),
                "model": entry.get("model", ""),
                "response": response_text,
                "expected_behavior": case["expected_behavior"],
                "fail_signals": case["fail_signals"],
                "matched_fail_signals": matched_signals,
                "automated_status": automated_status,
                "human_rating": human_rating,
                "human_notes": human_notes,
                "final_status": final_status,
            }
        )

    tested_count = sum(
        1
        for result in results
        if result["response"]
    )

    reviewed_count = sum(
        1
        for result in results
        if result["human_rating"] != "not_reviewed"
    )

    report = {
        "schema_version": "1.0.0",
        "report_type": "WA-OS Policy Drift Behavioral Report",
        "suite_name": suite["suite_name"],
        "suite_schema_version": suite["schema_version"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "principle": suite["principle"],
        "important_notice": (
            "Automated matching is an early-warning sensor only. "
            "Human review determines the final result."
        ),
        "summary": {
            "total_cases": len(cases),
            "responses_present": tested_count,
            "human_reviews_completed": reviewed_count,
            "pass": rating_counter["pass"],
            "warning": rating_counter["warning"],
            "fail": rating_counter["fail"],
            "human_review_required": rating_counter[
                "human_review_required"
            ],
        },
        "governance": {
            "human_review_required": suite[
                "human_review_required"
            ],
            "automatic_policy_activation_allowed": suite[
                "automatic_policy_activation_allowed"
            ],
        },
        "results": results,
    }

    return report


def print_report_summary(
    report: dict[str, Any],
) -> None:
    """Print the main results of a completed report."""

    summary = report["summary"]

    print()
    print("=" * 72)
    print("WA-OS POLICY DRIFT REPORT")
    print("=" * 72)
    print(f"Total cases: {summary['total_cases']}")
    print(
        f"Responses present: "
        f"{summary['responses_present']}"
    )
    print(
        f"Human reviews completed: "
        f"{summary['human_reviews_completed']}"
    )
    print(f"PASS: {summary['pass']}")
    print(f"WARNING: {summary['warning']}")
    print(f"FAIL: {summary['fail']}")
    print(
        "Human review required: "
        f"{summary['human_review_required']}"
    )
    print()

    for result in report["results"]:
        print(
            f"{result['case_id']}: "
            f"{result['final_status']} "
            f"({result['automated_status']})"
        )

        if result["matched_fail_signals"]:
            print("  Matched warning signals:")

            for signal in result["matched_fail_signals"]:
                print(f"  - {signal}")

    print()
    print(
        "Automatic matching does not replace human judgment."
    )
    print("=" * 72)
    print()


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line interface."""

    parser = argparse.ArgumentParser(
        description=(
            "Validate and run the WA-OS Policy Drift "
            "behavioral test suite."
        )
    )

    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
        help=(
            "Path to the Policy Drift test case JSON file."
        ),
    )

    parser.add_argument(
        "--validate-only",
        action="store_true",
        help=(
            "Validate the test suite without creating "
            "or evaluating response files."
        ),
    )

    parser.add_argument(
        "--init-responses",
        action="store_true",
        help=(
            "Create a response-entry template."
        ),
    )

    parser.add_argument(
        "--responses",
        type=Path,
        help=(
            "Evaluate a completed response JSON file."
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=(
            "Output path for the generated report."
        ),
    )

    parser.add_argument(
        "--response-template-output",
        type=Path,
        default=DEFAULT_RESPONSES_PATH,
        help=(
            "Output path for the response template."
        ),
    )

    return parser


def main() -> int:
    """Run the WA-OS Policy Drift test runner."""

    parser = build_argument_parser()
    args = parser.parse_args()

    try:
        suite = load_json(args.cases)
        cases = validate_test_suite(suite)

        print_suite_summary(
            suite,
            cases,
        )

        if args.validate_only:
            return 0

        if args.init_responses:
            create_response_template(
                suite,
                cases,
                args.response_template_output,
            )

        if args.responses is not None:
            response_data = load_json(args.responses)

            report = evaluate_responses(
                suite,
                cases,
                response_data,
            )

            save_json(
                args.output,
                report,
            )

            print_report_summary(report)
            print(f"Report created: {args.output}")

        if (
            not args.validate_only
            and not args.init_responses
            and args.responses is None
        ):
            print(
                "The test suite is valid."
            )
            print()
            print(
                "To create the response template, run:"
            )
            print(
                "python tests/policy_drift_runner.py "
                "--init-responses"
            )
            print()
            print(
                "To evaluate completed responses, run:"
            )
            print(
                "python tests/policy_drift_runner.py "
                "--responses tests/policy_drift_responses.json"
            )

        return 0

    except PolicyDriftValidationError as exc:
        print(
            f"POLICY DRIFT VALIDATION FAILED\n{exc}",
            file=sys.stderr,
        )
        return 1

    except OSError as exc:
        print(
            f"FILE OPERATION FAILED\n{exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
