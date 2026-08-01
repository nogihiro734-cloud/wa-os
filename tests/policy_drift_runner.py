#!/usr/bin/env python3
"""
WA-OS Policy Drift Behavioral Test Runner

Purpose
-------
Validate the WA-OS Policy Drift test suite and evaluate responses collected
from multiple AI providers.

Important governance rule
-------------------------
Automatic phrase matching is only an early-warning sensor.
PASS / WARNING / FAIL must be determined by human review.
This runner never activates or changes policy automatically.

Supported response formats
--------------------------
The runner accepts both:

1. Full-response format
   "response": "AI response exactly as received"

2. Summary format
   "response_summary": "Human-readable summary of the response"

If both fields exist, "response" is used for automated phrase matching.
If only "response_summary" exists, the summary is used instead.

Usage
-----
Validate the case suite only:

    python tests/policy_drift_runner.py --validate-only

Validate responses and generate a report:

    python tests/policy_drift_runner.py \
        --responses tests/policy_drift_responses.json \
        --output tests/policy_drift_report.json

Create an empty multi-provider response template:

    python tests/policy_drift_runner.py \
        --init-responses \
        --providers ChatGPT,Gemini,Claude,Perplexity \
        --response-template-output tests/policy_drift_responses_template.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from wa_os_policy_drift import evaluate_policy_drift

DEFAULT_CASES_PATH = Path("tests/policy_drift_cases.json")
DEFAULT_RESPONSES_PATH = Path("tests/policy_drift_responses.json")
DEFAULT_REPORT_PATH = Path("tests/policy_drift_report.json")

ALLOWED_RATINGS = {"pass", "warning", "fail", "not_reviewed"}


class PolicyDriftValidationError(Exception):
    """Raised when the test suite or response file is invalid."""


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from UTF-8, UTF-8 BOM, or ASCII-safe JSON."""
    if not path.exists():
        raise PolicyDriftValidationError(f"Required file not found: {path}")

    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PolicyDriftValidationError(
            f"Could not decode {path} as UTF-8: {exc}"
        ) from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PolicyDriftValidationError(
            f"Invalid JSON in {path}: "
            f"line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(data, dict):
        raise PolicyDriftValidationError(
            f"The root of {path} must be a JSON object."
        )

    return data


def save_json(path: Path, data: dict[str, Any]) -> None:
    """Write readable UTF-8 JSON without BOM."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyDriftValidationError(
            f"{field_name} must be a non-empty string."
        )
    return value.strip()


def require_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise PolicyDriftValidationError(
            f"{field_name} must be a non-empty list."
        )

    result: list[str] = []
    for index, item in enumerate(value):
        result.append(
            require_non_empty_string(item, f"{field_name}[{index}]")
        )
    return result


def validate_suite(suite: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the test suite and return flattened test cases."""
    require_non_empty_string(suite.get("schema_version"), "schema_version")
    require_non_empty_string(suite.get("suite_name"), "suite_name")

    if "description" in suite:
        require_non_empty_string(suite.get("description"), "description")
    if "principle" in suite:
        require_non_empty_string(suite.get("principle"), "principle")

    if suite.get("human_review_required") is not True:
        raise PolicyDriftValidationError(
            "human_review_required must be true."
        )

    if suite.get("automatic_policy_activation_allowed") is not False:
        raise PolicyDriftValidationError(
            "automatic_policy_activation_allowed must be false."
        )

    categories = suite.get("categories")
    if not isinstance(categories, list) or not categories:
        raise PolicyDriftValidationError(
            "categories must be a non-empty list."
        )

    seen_category_ids: set[str] = set()
    seen_case_ids: set[str] = set()
    flattened_cases: list[dict[str, Any]] = []

    for category_index, category in enumerate(categories):
        if not isinstance(category, dict):
            raise PolicyDriftValidationError(
                f"categories[{category_index}] must be an object."
            )

        category_id = require_non_empty_string(
            category.get("category_id"),
            f"categories[{category_index}].category_id",
        )

        if category_id in seen_category_ids:
            raise PolicyDriftValidationError(
                f"Duplicate category_id: {category_id}"
            )
        seen_category_ids.add(category_id)

        category_name = require_non_empty_string(
            category.get("name"),
            f"{category_id}.name",
        )

        if "purpose" in category:
            require_non_empty_string(
                category.get("purpose"),
                f"{category_id}.purpose",
            )

        category_cases = category.get("cases")
        if not isinstance(category_cases, list) or not category_cases:
            raise PolicyDriftValidationError(
                f"{category_id}.cases must be a non-empty list."
            )

        for case_index, case in enumerate(category_cases):
            if not isinstance(case, dict):
                raise PolicyDriftValidationError(
                    f"{category_id}.cases[{case_index}] must be an object."
                )

            case_id = require_non_empty_string(
                case.get("id"),
                f"{category_id}.cases[{case_index}].id",
            )

            if case_id in seen_case_ids:
                raise PolicyDriftValidationError(
                    f"Duplicate case id: {case_id}"
                )
            seen_case_ids.add(case_id)

            prompt = require_non_empty_string(
                case.get("prompt"),
                f"{case_id}.prompt",
            )

            expected_behavior = require_string_list(
                case.get("expected_behavior"),
                f"{case_id}.expected_behavior",
            )

            fail_signals = require_string_list(
                case.get("fail_signals"),
                f"{case_id}.fail_signals",
            )

            flattened_cases.append(
                {
                    "id": case_id,
                    "prompt": prompt,
                    "expected_behavior": expected_behavior,
                    "fail_signals": fail_signals,
                    "_category_id": category_id,
                    "_category_name": category_name,
                }
            )

    if "global_fail_conditions" in suite:
        require_string_list(
            suite.get("global_fail_conditions"),
            "global_fail_conditions",
        )

    return flattened_cases


def normalize_text(text: str) -> str:
    """Normalize Japanese and Latin text for simple direct phrase matching."""
    normalized = text.casefold()
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(
        r"[、。！？!?・「」『』（）()［］\[\]【】〈〉<>：:；;,.…—―\-_/]",
        "",
        normalized,
    )
    return normalized


def direct_fail_signal_matches(
    response_text: str,
    fail_signals: Iterable[str],
) -> list[str]:
    """Return only literal/near-literal matches after normalization."""
    normalized_response = normalize_text(response_text)
    matches: list[str] = []

    for signal in fail_signals:
        normalized_signal = normalize_text(signal)
        if normalized_signal and normalized_signal in normalized_response:
            matches.append(signal)

    return matches


def get_response_text(entry: dict[str, Any]) -> tuple[str, str]:
    """
    Return response text and the field used.

    Priority:
    1. response
    2. response_summary
    """
    response = entry.get("response")
    if isinstance(response, str) and response.strip():
        return response.strip(), "response"

    summary = entry.get("response_summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip(), "response_summary"

    return "", "none"


def validate_responses(
    response_document: dict[str, Any],
    case_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate response entries for multi-provider use."""
    responses = response_document.get("responses")
    if not isinstance(responses, list) or not responses:
        raise PolicyDriftValidationError(
            "responses must be a non-empty list."
        )

    seen_response_ids: set[str] = set()
    seen_case_provider_pairs: set[tuple[str, str]] = set()

    validated: list[dict[str, Any]] = []

    for index, entry in enumerate(responses):
        if not isinstance(entry, dict):
            raise PolicyDriftValidationError(
                f"responses[{index}] must be an object."
            )

        case_id = require_non_empty_string(
            entry.get("case_id"),
            f"responses[{index}].case_id",
        )

        if case_id not in case_map:
            raise PolicyDriftValidationError(
                f"Unknown case_id in responses[{index}]: {case_id}"
            )

        category_id = require_non_empty_string(
            entry.get("category_id"),
            f"responses[{index}].category_id",
        )

        expected_category_id = case_map[case_id]["_category_id"]
        if category_id != expected_category_id:
            raise PolicyDriftValidationError(
                f"responses[{index}].category_id must be "
                f"{expected_category_id}, not {category_id}."
            )

        provider = require_non_empty_string(
            entry.get("ai_provider"),
            f"responses[{index}].ai_provider",
        )

        model_value = entry.get("model", provider)
        model = require_non_empty_string(
            model_value,
            f"responses[{index}].model",
        )

        response_id_value = entry.get("response_id")
        if isinstance(response_id_value, str) and response_id_value.strip():
            response_id = response_id_value.strip()
        else:
            response_id = (
                f"{case_id}-{provider.lower().replace(' ', '-')}"
            )

        if response_id in seen_response_ids:
            raise PolicyDriftValidationError(
                f"Duplicate response_id: {response_id}"
            )
        seen_response_ids.add(response_id)

        pair = (case_id, provider)
        if pair in seen_case_provider_pairs:
            raise PolicyDriftValidationError(
                f"Duplicate provider response for {case_id}: {provider}"
            )
        seen_case_provider_pairs.add(pair)

        rating = entry.get("human_rating", "not_reviewed")
        if rating not in ALLOWED_RATINGS:
            raise PolicyDriftValidationError(
                f"{response_id}.human_rating must be one of: "
                + ", ".join(sorted(ALLOWED_RATINGS))
            )

        human_notes = entry.get("human_notes", "")
        if not isinstance(human_notes, str):
            raise PolicyDriftValidationError(
                f"{response_id}.human_notes must be a string."
            )

        response_text, response_field = get_response_text(entry)

        if not response_text and rating != "not_reviewed":
            raise PolicyDriftValidationError(
                f"{response_id} has rating '{rating}' but no response "
                "or response_summary text."
            )

        prompt_in_entry = entry.get("prompt")
        if isinstance(prompt_in_entry, str) and prompt_in_entry.strip():
            if prompt_in_entry.strip() != case_map[case_id]["prompt"]:
                raise PolicyDriftValidationError(
                    f"{response_id}.prompt does not match the suite prompt."
                )

        validated_entry = dict(entry)
        validated_entry["response_id"] = response_id
        validated_entry["model"] = model
        validated_entry["_response_text"] = response_text
        validated_entry["_response_field"] = response_field
        validated.append(validated_entry)

    return validated


def infer_sensor_context(case: dict[str, Any]) -> tuple[bool, bool]:
    """Infer conservative evaluator context from the behavioral case."""
    category_id = case["_category_id"]
    request_is_harmless = category_id == "excessive_refusal"
    uncertainty_expected = category_id in {
        "unsupported_certainty",
        "narrative_bias",
    }
    return request_is_harmless, uncertainty_expected


def automated_evaluation(
    case: dict[str, Any],
    response_text: str,
    response_field: str,
) -> dict[str, Any]:
    """Run the WA-OS drift sensor without replacing human judgment."""
    if not response_text:
        return {
            "available": False,
            "comparison_eligible": False,
            "source_quality": "none",
            "drift_detected": False,
            "overall_severity": "none",
            "categories": [],
            "signals": [],
        }

    request_is_harmless, uncertainty_expected = infer_sensor_context(case)
    result = evaluate_policy_drift(
        response_text,
        request_is_harmless=request_is_harmless,
        uncertainty_expected=uncertainty_expected,
    ).to_dict()

    signals = result.get("signals", [])
    return {
        "available": True,
        "comparison_eligible": response_field == "response",
        "source_quality": (
            "verbatim_response"
            if response_field == "response"
            else "human_summary_limited"
        ),
        "drift_detected": result["drift_detected"],
        "overall_severity": result["overall_severity"],
        "categories": [signal["category"] for signal in signals],
        "signals": signals,
    }


def human_rating_indicates_drift(rating: str) -> bool | None:
    """Map reviewed ratings to a drift/no-drift value for comparison."""
    if rating == "pass":
        return False
    if rating in {"warning", "fail"}:
        return True
    return None


def build_report(
    suite: dict[str, Any],
    cases: list[dict[str, Any]],
    response_document: dict[str, Any],
) -> dict[str, Any]:
    """Build a human-review-centered multi-provider report."""
    case_map = {case["id"]: case for case in cases}
    responses = validate_responses(response_document, case_map)

    overall_counts: Counter[str] = Counter()
    provider_counts: dict[str, Counter[str]] = defaultdict(Counter)
    case_counts: dict[str, Counter[str]] = defaultdict(Counter)
    category_counts: dict[str, Counter[str]] = defaultdict(Counter)
    comparison_counts: Counter[str] = Counter()
    sensor_counts: Counter[str] = Counter()
    sensor_category_counts: Counter[str] = Counter()

    results: list[dict[str, Any]] = []

    for entry in responses:
        case = case_map[entry["case_id"]]
        response_text = entry.pop("_response_text")
        response_field = entry.pop("_response_field")

        matched_signals = direct_fail_signal_matches(
            response_text,
            case["fail_signals"],
        )
        sensor_result = automated_evaluation(case, response_text, response_field)

        rating = entry.get("human_rating", "not_reviewed")
        sensor_counts["evaluated"] += int(sensor_result["available"])
        sensor_counts["drift_detected"] += int(sensor_result["drift_detected"])
        sensor_counts[sensor_result["source_quality"]] += 1
        for sensor_category in sensor_result["categories"]:
            sensor_category_counts[sensor_category.value] += 1

        human_drift = human_rating_indicates_drift(rating)
        if (
            human_drift is None
            or not sensor_result["available"]
            or not sensor_result["comparison_eligible"]
        ):
            comparison = "not_comparable"
        elif human_drift == sensor_result["drift_detected"]:
            comparison = "agreement"
        elif sensor_result["drift_detected"]:
            comparison = "sensor_only"
        else:
            comparison = "human_only"
        comparison_counts[comparison] += 1
        final_status = (
            "human_review_required"
            if rating == "not_reviewed"
            else rating
        )

        overall_counts[final_status] += 1
        provider_counts[entry["ai_provider"]][final_status] += 1
        case_counts[entry["case_id"]][final_status] += 1
        category_counts[entry["category_id"]][final_status] += 1

        results.append(
            {
                **entry,
                "prompt": case["prompt"],
                "category_name": case["_category_name"],
                "response_text_source": response_field,
                "expected_behavior": case["expected_behavior"],
                "fail_signals": case["fail_signals"],
                "matched_direct_fail_signals": matched_signals,
                "automated_status": (
                    "warning_signal_detected"
                    if matched_signals
                    else "no_direct_signal_detected"
                ),
                "wa_os_sensor": sensor_result,
                "human_sensor_comparison": comparison,
                "final_status": final_status,
            }
        )

    providers = sorted(provider_counts)
    expected_pairs = len(cases) * len(providers)
    actual_pairs = len(responses)

    missing_pairs: list[dict[str, str]] = []
    existing_pairs = {
        (entry["case_id"], entry["ai_provider"])
        for entry in responses
    }

    for case in cases:
        for provider in providers:
            if (case["id"], provider) not in existing_pairs:
                missing_pairs.append(
                    {
                        "case_id": case["id"],
                        "ai_provider": provider,
                    }
                )

    return {
        "schema_version": "2.0.0",
        "report_type": (
            "WA-OS Multi-Provider Policy Drift Behavioral Report"
        ),
        "suite_name": suite["suite_name"],
        "suite_schema_version": suite["schema_version"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "principle": suite.get(
            "principle",
            "Humans do not surrender the question. "
            "AI does not take the question away from humans.",
        ),
        "important_notice": (
            "Automated phrase matching is an early-warning sensor only. "
            "Human review determines PASS, WARNING, or FAIL. "
            "Account history, memory, personalization, and search context "
            "may have influenced provider responses."
        ),
        "coverage": {
            "providers": providers,
            "total_cases": len(cases),
            "expected_case_provider_pairs": expected_pairs,
            "actual_case_provider_pairs": actual_pairs,
            "complete": not missing_pairs,
            "missing_pairs": missing_pairs,
        },
        "summary": {
            "total_responses": len(responses),
            **dict(overall_counts),
        },
        "provider_summary": {
            provider: dict(counts)
            for provider, counts in sorted(provider_counts.items())
        },
        "case_summary": {
            case_id: dict(counts)
            for case_id, counts in sorted(case_counts.items())
        },
        "category_summary": {
            category_id: dict(counts)
            for category_id, counts in sorted(category_counts.items())
        },
        "wa_os_sensor_summary": {
            **dict(sensor_counts),
            "category_counts": dict(sensor_category_counts),
            "notice": (
                "Sensor findings from response_summary fields are preliminary "
                "because summaries are not verbatim provider output."
            ),
        },
        "human_sensor_comparison": {
            **dict(comparison_counts),
            "comparable_responses": (
                comparison_counts["agreement"]
                + comparison_counts["sensor_only"]
                + comparison_counts["human_only"]
            ),
            "agreement_rate": (
                comparison_counts["agreement"]
                / (
                    comparison_counts["agreement"]
                    + comparison_counts["sensor_only"]
                    + comparison_counts["human_only"]
                )
                if (
                    comparison_counts["agreement"]
                    + comparison_counts["sensor_only"]
                    + comparison_counts["human_only"]
                )
                else None
            ),
            "interpretation": (
                "Only verbatim AI responses are eligible for agreement "
                "measurement. Human-written summaries may omit wording that "
                "the sensor needs. This is diagnostic evidence, not an "
                "autonomous policy decision."
            ),
        },
        "governance": {
            "human_review_required": suite.get(
                "human_review_required",
                True,
            ),
            "automatic_policy_activation_allowed": suite.get(
                "automatic_policy_activation_allowed",
                False,
            ),
        },
        "results": results,
    }


def create_response_template(
    suite: dict[str, Any],
    cases: list[dict[str, Any]],
    providers: list[str],
    output_path: Path,
) -> None:
    """Create an empty response template for all provider/case pairs."""
    entries: list[dict[str, Any]] = []

    for case in cases:
        for provider in providers:
            slug = provider.lower().replace(" ", "-")
            entries.append(
                {
                    "response_id": f"{case['id']}-{slug}",
                    "case_id": case["id"],
                    "category_id": case["_category_id"],
                    "prompt": case["prompt"],
                    "ai_provider": provider,
                    "model": provider,
                    "test_language": "ja",
                    "context_mode": "unknown",
                    "context_note": "",
                    "response": "",
                    "human_rating": "not_reviewed",
                    "human_notes": "",
                }
            )

    document = {
        "schema_version": "2.0.0",
        "suite_name": suite["suite_name"],
        "suite_schema_version": suite["schema_version"],
        "instructions": {
            "response": "Paste the AI response exactly as received.",
            "human_rating": (
                "Choose pass, warning, fail, or not_reviewed."
            ),
            "human_notes": (
                "Explain the reason for the human judgment."
            ),
        },
        "responses": entries,
    }

    save_json(output_path, document)


def print_suite_summary(
    suite: dict[str, Any],
    cases: list[dict[str, Any]],
) -> None:
    print("=" * 72)
    print("WA-OS POLICY DRIFT TEST SUITE")
    print("=" * 72)
    print(f"Suite: {suite['suite_name']}")
    print(f"Schema version: {suite['schema_version']}")
    print(f"Categories: {len(suite['categories'])}")
    print(f"Cases: {len(cases)}")
    print("Validation result: PASS")
    print("=" * 72)


def print_report_summary(report: dict[str, Any]) -> None:
    print()
    print("=" * 72)
    print("WA-OS MULTI-PROVIDER POLICY DRIFT REPORT")
    print("=" * 72)

    for key, value in report["summary"].items():
        print(f"{key}: {value}")

    print()
    print("Coverage:")
    for key, value in report["coverage"].items():
        if key != "missing_pairs":
            print(f"  {key}: {value}")

    print()
    print("WA-OS sensor summary:")
    for key, value in report["wa_os_sensor_summary"].items():
        if key != "notice":
            print(f"  {key}: {value}")

    print()
    print("Human / WA-OS sensor comparison:")
    for key, value in report["human_sensor_comparison"].items():
        if key != "interpretation":
            print(f"  {key}: {value}")

    print()
    print("Provider summary:")
    for provider, counts in report["provider_summary"].items():
        print(f"  {provider}: {counts}")

    if report["coverage"]["missing_pairs"]:
        print()
        print("Missing case/provider pairs:")
        for missing in report["coverage"]["missing_pairs"]:
            print(
                f"  - {missing['case_id']} / "
                f"{missing['ai_provider']}"
            )

    print("=" * 72)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate WA-OS Policy Drift cases and "
            "multi-provider response files."
        )
    )

    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
        help="Path to policy_drift_cases.json",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the case suite and exit.",
    )
    parser.add_argument(
        "--responses",
        type=Path,
        help="Path to policy_drift_responses.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Path for the generated report.",
    )
    parser.add_argument(
        "--init-responses",
        action="store_true",
        help="Create an empty multi-provider response template.",
    )
    parser.add_argument(
        "--providers",
        default="ChatGPT,Gemini,Claude,Perplexity",
        help="Comma-separated provider names.",
    )
    parser.add_argument(
        "--response-template-output",
        type=Path,
        default=DEFAULT_RESPONSES_PATH,
        help="Path for a newly created response template.",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        suite = load_json(args.cases)
        cases = validate_suite(suite)
        print_suite_summary(suite, cases)

        if args.validate_only:
            return 0

        performed_action = False

        if args.init_responses:
            providers = [
                provider.strip()
                for provider in args.providers.split(",")
                if provider.strip()
            ]

            if not providers:
                raise PolicyDriftValidationError(
                    "At least one provider is required."
                )

            create_response_template(
                suite,
                cases,
                providers,
                args.response_template_output,
            )
            print(
                "Response template created: "
                f"{args.response_template_output}"
            )
            performed_action = True

        if args.responses:
            response_document = load_json(args.responses)
            report = build_report(
                suite,
                cases,
                response_document,
            )
            save_json(args.output, report)
            print_report_summary(report)
            print(f"Report created: {args.output}")
            performed_action = True

        if not performed_action:
            print(
                "No report action selected. Use one of:\n"
                "  --validate-only\n"
                "  --init-responses\n"
                "  --responses tests/policy_drift_responses.json"
            )

        return 0

    except (PolicyDriftValidationError, OSError) as exc:
        print(
            "POLICY DRIFT VALIDATION FAILED",
            file=sys.stderr,
        )
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
