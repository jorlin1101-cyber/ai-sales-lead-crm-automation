import re
import unicodedata

from lead_cleaner.schemas.policy import SecuritySignals


PatternRule = tuple[str, re.Pattern[str]]


PROMPT_INJECTION_PATTERNS: tuple[PatternRule, ...] = (
    (
        "ignore_previous_instructions",
        re.compile(
            r"(?:\b(?:ignore|disregard|forget)\b.{0,60}"
            r"\b(?:previous|prior|above|earlier|all)\b.{0,30}"
            r"\b(?:instructions?|rules?|prompts?)\b)"
            r"|(?:(?:忽略|无视|忘掉|忘记).{0,30}"
            r"(?:之前|先前|以上|上面|原有|所有).{0,20}"
            r"(?:指令|规则|提示词|要求))",
        ),
    ),
    (
        "override_score",
        re.compile(
            r"(?:\b(?:set|change|override|assign)\b.{0,40}"
            r"\b(?:lead\s+)?(?:score|rating)\b.{0,20}"
            r"(?:\bto\b|\bas\b|=).{0,10}\d{1,3}\b)"
            r"|(?:\b(?:give|award)\b.{0,30}\b(?:me|this\s+lead)\b.{0,20}"
            r"\d{1,3}\s*(?:points?|score)\b)"
            r"|(?:(?:把|将).{0,20}(?:分数|评分|得分).{0,20}"
            r"(?:设为|设置为|改为|修改为|调到|=).{0,10}\d{1,3})"
            r"|(?:给我.{0,10}\d{1,3}\s*分)",
        ),
    ),
    (
        "reveal_system_prompt",
        re.compile(
            r"(?:\b(?:reveal|show|print|display|repeat|leak|output)\b.{0,40}"
            r"\b(?:system\s+prompt|hidden\s+prompt|developer\s+message|"
            r"internal\s+instructions?)\b)"
            r"|(?:(?:显示|展示|输出|打印|泄露|告诉我|重复).{0,30}"
            r"(?:系统提示词|隐藏提示词|开发者消息|内部指令|系统指令))",
        ),
    ),
    (
        "bypass_policy",
        re.compile(
            r"(?:\b(?:bypass|circumvent|disable)\b.{0,30}"
            r"\b(?:security|safety|scoring|guardrails?|filters?|your\s+rules)\b)"
            r"|(?:(?:绕过|规避|关闭|禁用|跳过).{0,30}"
            r"(?:安全限制|安全规则|评分规则|评分策略|过滤器|系统限制))",
        ),
    ),
    (
        "role_override",
        re.compile(
            r"(?:\b(?:you\s+are\s+now|act\s+as|pretend\s+to\s+be|enter)\b.{0,40}"
            r"\b(?:developer|system|administrator|unrestricted|jailbreak)\b)"
            r"|(?:(?:你现在是|扮演|假装是|进入).{0,30}"
            r"(?:开发者模式|系统模式|管理员模式|无限制模式|越狱模式))",
        ),
    ),
)


KNOWLEDGE_INJECTION_PATTERNS: tuple[PatternRule, ...] = (
    (
        "knowledge_base_instruction_injection",
        re.compile(
            r"(?:\b(?:knowledge\s+base|retrieved\s+(?:document|context)|"
            r"reference\s+document)\b.{0,80}"
            r"\b(?:ignore|override|instruction|system\s+prompt)\b)"
            r"|(?:(?:知识库|检索文档|检索内容|参考文档).{0,80}"
            r"(?:忽略|覆盖|指令|系统提示词|评分规则))",
        ),
    ),
)


def normalize_security_text(text: str) -> str:
    """Normalize harmless text variations without changing its meaning."""

    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(normalized.split())


def find_matching_codes(text: str, patterns: tuple[PatternRule, ...]) -> list[str]:
    """Return each matched rule code once, in a stable rule order."""

    return [code for code, pattern in patterns if pattern.search(text)]


def detect_security_signals(message: str) -> SecuritySignals:
    """Detect review signals in a lead message using deterministic rules.

    A match is only a reason to review the message. It is not proof that the
    sender is malicious, and this function never changes a lead's score.
    """

    normalized_message = normalize_security_text(message)
    prompt_codes = find_matching_codes(normalized_message, PROMPT_INJECTION_PATTERNS)
    knowledge_codes = find_matching_codes(
        normalized_message,
        KNOWLEDGE_INJECTION_PATTERNS,
    )

    return SecuritySignals(
        injection_suspected=bool(prompt_codes),
        matched_pattern_codes=[*prompt_codes, *knowledge_codes],
        knowledge_injection_suspected=bool(knowledge_codes),
    )
