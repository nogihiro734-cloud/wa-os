#!/usr/bin/env python3
"""WA-OS role selection and execution-integrity reference prototype."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Role = Literal[
    "secretarial_execution",
    "information_analysis",
    "educational_support",
    "decision_support",
    "high_stakes_review",
]


@dataclass(frozen=True)
class TaskContract:
    preserve_full_text: bool = False
    no_omission: bool = False
    requested_format: str | None = None
    requested_language: str | None = None
    approval_before_changes: bool = True
    explicit_constraints: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RouteDecision:
    role: Role
    intervention_level: Literal["low", "medium", "high"]
    reasons: tuple[str, ...]
    contract: TaskContract


SECRETARIAL = (
    "表に",
    "一覧に",
    "翻訳",
    "書き換え",
    "整形",
    "抽出",
    "並べ替え",
    "word",
    "pdf",
    "ファイル",
    "メール文",
    "要約して",
)

ANALYSIS = (
    "比較",
    "分析",
    "根拠",
    "主張",
    "ニュース",
    "調べて",
    "検証",
)

EDUCATION = (
    "教えて",
    "説明して",
    "練習",
    "理解",
    "学びたい",
)

DECISION = (
    "何の仕事",
    "決めて",
    "選ぶべき",
    "人生",
    "離婚",
    "進路",
    "あなたに従う",
    "全部判断",
)

HIGH_STAKES = (
    "診断",
    "薬",
    "法律",
    "訴訟",
    "投資",
    "借金",
    "危険",
    "自殺",
)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in terms)


def capture_task_contract(prompt: str) -> TaskContract:
    no_omission = _contains_any(
        prompt,
        (
            "省略しない",
            "省かない",
            "削らない",
            "一字一句",
            "全文",
        ),
    )

    preserve_full_text = no_omission or _contains_any(
        prompt,
        (
            "原文を保つ",
            "完全版",
            "そのまま",
        ),
    )

    requested_format = None

    for label in (
        "表",
        "Word",
        "PDF",
        "JSON",
        "Markdown",
        "箇条書き",
    ):
        if label.casefold() in prompt.casefold():
            requested_format = label
            break

    requested_language = None

    for label in (
        "日本語",
        "英語",
        "中国語",
        "オランダ語",
    ):
        if label in prompt:
            requested_language = label
            break

    constraints = []

    if preserve_full_text:
        constraints.append("preserve_full_text")

    if no_omission:
        constraints.append("no_omission")

    if requested_format:
        constraints.append(f"format:{requested_format}")

    if requested_language:
        constraints.append(f"language:{requested_language}")

    return TaskContract(
        preserve_full_text=preserve_full_text,
        no_omission=no_omission,
        requested_format=requested_format,
        requested_language=requested_language,
        approval_before_changes=True,
        explicit_constraints=tuple(constraints),
    )


def classify_role(prompt: str) -> RouteDecision:
    contract = capture_task_contract(prompt)
    reasons: list[str] = []

    if _contains_any(prompt, HIGH_STAKES):
        role: Role = "high_stakes_review"
        level = "high"
        reasons.append("high_stakes_domain_detected")

    elif _contains_any(prompt, DECISION):
        role = "decision_support"
        level = "medium"
        reasons.append("consequential_personal_decision_detected")

    elif _contains_any(prompt, SECRETARIAL):
        role = "secretarial_execution"
        level = "low"
        reasons.append("direct_execution_request_detected")

    elif _contains_any(prompt, ANALYSIS):
        role = "information_analysis"
        level = "medium"
        reasons.append("analysis_or_verification_request_detected")

    elif _contains_any(prompt, EDUCATION):
        role = "educational_support"
        level = "low"
        reasons.append("learning_request_detected")

    else:
        role = "information_analysis"
        level = "medium"
        reasons.append("ambiguous_request_defaulted_to_analysis")

    if contract.no_omission:
        reasons.append("explicit_no_omission_constraint")

    return RouteDecision(
        role=role,
        intervention_level=level,
        reasons=tuple(reasons),
        contract=contract,
    )


def validate_plan_against_contract(
    contract: TaskContract,
    planned_mode: str,
    planned_format: str | None = None,
) -> list[str]:
    """
    実行計画が、利用者との作業上の合意に反していないか確認する。

    違反がある場合は、修正または利用者への確認が必要。
    """

    violations: list[str] = []

    if contract.no_omission and planned_mode in {
        "summary",
        "abridged",
        "extract",
    }:
        violations.append("silent_omission_or_compression")

    if (
        contract.requested_format
        and planned_format
        and contract.requested_format.casefold()
        != planned_format.casefold()
    ):
        violations.append("requested_format_changed")

    return violations


def response_directive(decision: RouteDecision) -> str:
    """
    選択された役割に応じて、AIへ渡す回答方針を生成する。
    """

    if decision.role == "secretarial_execution":
        directive = (
            "Execute the requested task directly and efficiently. "
            "Avoid unnecessary reflective or moral intervention."
        )

    elif decision.role == "decision_support":
        directive = (
            "Provide reasoned options and a practical recommendation, "
            "but do not claim final authority over the user's life."
        )

    elif decision.role == "high_stakes_review":
        directive = (
            "Provide useful but bounded assistance, disclose material "
            "uncertainty, and preserve appropriate human or professional review."
        )

    elif decision.role == "educational_support":
        directive = (
            "Explain clearly while supporting the learner's own understanding."
        )

    else:
        directive = (
            "Analyze claims, evidence, assumptions, competing perspectives, "
            "and uncertainty."
        )

    if decision.contract.no_omission:
        directive += (
            " Preserve all requested content. If output limits are reached, "
            "continue in clearly labeled parts. Do not silently summarize, "
            "compress, or omit content."
        )

    if decision.contract.requested_format:
        directive += (
            f" Preserve the requested output format: "
            f"{decision.contract.requested_format}."
        )

    if decision.contract.requested_language:
        directive += (
            f" Use the requested language: "
            f"{decision.contract.requested_language}."
        )

    return directive


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="WA-OS role selection and task-contract prototype"
    )

    parser.add_argument(
        "prompt",
        help="User request to classify",
    )

    args = parser.parse_args()

    decision = classify_role(args.prompt)

    result = {
        "role": decision.role,
        "intervention_level": decision.intervention_level,
        "reasons": decision.reasons,
        "contract": {
            "preserve_full_text": decision.contract.preserve_full_text,
            "no_omission": decision.contract.no_omission,
            "requested_format": decision.contract.requested_format,
            "requested_language": decision.contract.requested_language,
            "approval_before_changes": (
                decision.contract.approval_before_changes
            ),
            "explicit_constraints": (
                decision.contract.explicit_constraints
            ),
        },
        "directive": response_directive(decision),
    }

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
