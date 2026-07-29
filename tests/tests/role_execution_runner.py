#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wa_os_role_router import (
    classify_role,
    validate_plan_against_contract,
)


CASES_FILE = Path(__file__).with_name(
    "role_execution_cases.json"
)


def load_test_cases() -> dict:
    """
    role_execution_cases.json を読み込む。
    """

    if not CASES_FILE.exists():
        raise FileNotFoundError(
            f"Test case file not found: {CASES_FILE}"
        )

    with CASES_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def run_role_test(
    case: dict,
    failures: list[str],
) -> None:
    """
    役割選択と介入レベルを確認する。
    """

    decision = classify_role(case["prompt"])

    expected_role = case["expected_role"]
    expected_intervention = case[
        "expected_intervention"
    ]

    if decision.role != expected_role:
        failures.append(
            f"{case['id']}: "
            f"role={decision.role}, "
            f"expected={expected_role}"
        )

    if (
        decision.intervention_level
        != expected_intervention
    ):
        failures.append(
            f"{case['id']}: "
            f"intervention="
            f"{decision.intervention_level}, "
            f"expected={expected_intervention}"
        )


def run_constraint_test(
    case: dict,
    failures: list[str],
) -> None:
    """
    全文保持、省略禁止、形式、言語などの
    作業条件が正しく取得されているか確認する。
    """

    decision = classify_role(case["prompt"])

    actual_constraints = set(
        decision.contract.explicit_constraints
    )

    required_constraints = case.get(
        "required_constraints",
        [],
    )

    for required_constraint in required_constraints:
        if required_constraint not in actual_constraints:
            failures.append(
                f"{case['id']}: "
                f"missing constraint "
                f"{required_constraint}"
            )


def run_forbidden_mode_test(
    case: dict,
    failures: list[str],
) -> None:
    """
    省略禁止の依頼を、要約や短縮へ
    勝手に変更できないことを確認する。
    """

    decision = classify_role(case["prompt"])

    forbidden_modes = case.get(
        "forbidden_plan_modes",
        [],
    )

    for planned_mode in forbidden_modes:
        violations = (
            validate_plan_against_contract(
                contract=decision.contract,
                planned_mode=planned_mode,
                planned_format=(
                    decision.contract.requested_format
                ),
            )
        )

        if not violations:
            failures.append(
                f"{case['id']}: "
                f"forbidden mode "
                f"{planned_mode} was not blocked"
            )


def run_case(
    case: dict,
    failures: list[str],
) -> None:
    """
    1件のテストケースについて、
    すべての検査を実行する。
    """

    run_role_test(
        case=case,
        failures=failures,
    )

    run_constraint_test(
        case=case,
        failures=failures,
    )

    run_forbidden_mode_test(
        case=case,
        failures=failures,
    )


def main() -> int:
    """
    WA-OS Role Selection and
    Execution Integrity テストを実行する。
    """

    try:
        suite = load_test_cases()

    except FileNotFoundError as error:
        print(
            "=" * 72
        )
        print(
            "WA-OS ROLE / "
            "EXECUTION INTEGRITY TEST"
        )
        print(
            "=" * 72
        )
        print(
            "Result: ERROR"
        )
        print(
            str(error)
        )
        return 1

    except json.JSONDecodeError as error:
        print(
            "=" * 72
        )
        print(
            "WA-OS ROLE / "
            "EXECUTION INTEGRITY TEST"
        )
        print(
            "=" * 72
        )
        print(
            "Result: ERROR"
        )
        print(
            "Invalid JSON in "
            "role_execution_cases.json"
        )
        print(
            str(error)
        )
        return 1

    cases = suite.get(
        "cases",
        [],
    )

    failures: list[str] = []

    for case in cases:
        run_case(
            case=case,
            failures=failures,
        )

    print(
        "=" * 72
    )
    print(
        "WA-OS ROLE / "
        "EXECUTION INTEGRITY TEST"
    )
    print(
        "=" * 72
    )
    print(
        f"Suite: "
        f"{suite.get('suite_name', 'Unknown')}"
    )
    print(
        f"Cases: {len(cases)}"
    )

    if failures:
        print(
            "Result: FAIL"
        )

        for failure in failures:
            print(
                f"- {failure}"
            )

        return 1

    print(
        "Result: PASS"
    )
    print(
        "Role selection and "
        "task-contract checks passed."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
