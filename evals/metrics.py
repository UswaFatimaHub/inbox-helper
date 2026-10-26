"""deepeval metrics for the inbox helper.

Rule metrics are deterministic (no LLM) and wrap evals/rules.py. Judge metrics use an LLM and only run on cases
that have a draft. Test-case metadata carries the golden's expectations and the app's result.
"""
from deepeval.metrics import BaseMetric, FaithfulnessMetric, GEval
from deepeval.test_case import LLMTestCase, SingleTurnParams

from .rules import draft_verdict, intent_verdict, review_verdict


class _RuleMetric(BaseMetric):
    name = "rule"
    _required_params = [SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.METADATA]

    def __init__(self, threshold: float = 1.0):
        self.threshold = threshold
        self.include_reason = True
        self.strict_mode = False
        self.async_mode = True
        self.verbose_mode = False
        self.evaluation_model = "rules (no LLM)"

    def _verdict(self, test_case: LLMTestCase) -> tuple[float, str]:
        raise NotImplementedError

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        self.score, self.reason = self._verdict(test_case)
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return self.error is None and bool(self.success)

    @property
    def __name__(self):
        return self.name


class IntentMetric(_RuleMetric):
    """The primary intent is one of the golden's acceptable intents."""
    name = "Intent"

    def _verdict(self, tc):
        return intent_verdict(tc.metadata["result"], tc.metadata["expected"])


class ReviewRoutingMetric(_RuleMetric):
    """Must-raise flags are present and must-prioritise messages are at the top of the review queue."""
    name = "Review routing"

    def _verdict(self, tc):
        return review_verdict(tc.metadata["result"], tc.metadata["expected"])


class DraftRulesMetric(_RuleMetric):
    """App code checks, forbidden text, sign-off, length, and 'no draft' for quarantined messages."""
    name = "Draft rules"

    def __init__(self, policy_text: str, threshold: float = 1.0):
        super().__init__(threshold)
        self.policy_text = policy_text

    def _verdict(self, tc):
        return draft_verdict(tc.actual_output or "", tc.metadata["message"], tc.metadata["expected"],
                             self.policy_text)


def rule_metrics(policy_text: str) -> list[BaseMetric]:
    return [IntentMetric(), ReviewRoutingMetric(), DraftRulesMetric(policy_text)]


POLICY_COMPLIANCE_STEPS = [
    "The input is a message sent to a recruiting team's inbox and the actual output is the team's draft reply. "
    "The context is the reviewer checklist for this message: lines starting 'MUST:' are things the reply has to "
    "convey or do, lines starting 'MUST NOT:' are things it must avoid, and lines starting 'POLICY:' are the "
    "policy rules that apply.",
    "For each MUST line, decide whether the actual output satisfies it. The same meaning is enough; exact wording "
    "is not required.",
    "For each MUST NOT line, decide whether the actual output violates it. A single violation is a serious failure "
    "and the score must be close to 0.",
    "Check that the reply does not state, promise, or confirm anything (dates, times, decisions, salary, links, "
    "completed actions, company rules) that is supported neither by the input message nor by the POLICY lines.",
    "Give a high score only if every MUST is met and no MUST NOT is violated; lower it for each MUST that is missed.",
]

REPLY_QUALITY_STEPS = [
    "The input is a message sent to a recruiting team's inbox, the actual output is a draft reply, and the "
    "expected output is a reference reply written by a reviewer. The reference shows one good answer; the draft "
    "does not need to match its wording or structure.",
    "Check that the draft addresses every request in the input at least as completely and concretely as the "
    "reference does.",
    "Check the tone: warm, plain and professional; written as the team ('we'), never as 'I'; no mention of AI, "
    "tools, or what records can or cannot be seen; if the sender is frustrated or upset, the draft briefly "
    "acknowledges it without admitting fault.",
    "Check the form: same language as the input, addresses the person by first name when known, concise "
    "(about 40-110 words, or a single line when the reference is a single line), signed 'Brightpath Recruiting Team'.",
    "Lower the score for drafts that are vaguer than the reference, add unnecessary content, or would need "
    "significant editing before a recruiter could send them.",
]


def judge_metrics(judge, names: list[str]) -> list[BaseMetric]:
    available = {
        # Every claim in the draft must be supported by the policy or the candidate's own message.
        "faithfulness": lambda: FaithfulnessMetric(threshold=0.8, model=judge, include_reason=True),
        "policy": lambda: GEval(
            name="Policy compliance", model=judge, threshold=0.7, evaluation_steps=POLICY_COMPLIANCE_STEPS,
            evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.CONTEXT]),
        "quality": lambda: GEval(
            name="Reply quality", model=judge, threshold=0.6, evaluation_steps=REPLY_QUALITY_STEPS,
            evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT,
                               SingleTurnParams.EXPECTED_OUTPUT]),
    }
    return [available[n]() for n in names]


JUDGE_METRIC_NAMES = ("faithfulness", "policy", "quality")
