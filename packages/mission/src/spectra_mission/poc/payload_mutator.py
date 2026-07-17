"""POC Payload Mutator — auto-mutates payloads that get filtered/blocked.

When a payload is partially blocked (WAF, input filter, encoding issue),
this module applies systematic mutations to bypass the filter:
- Encoding variations (URL, Base64, Unicode)
- Obfuscation (case changes, whitespace injection, comment insertion)
- Alternative syntax (different ways to express the same attack)
- Character substitution (Unicode normalization tricks)
"""

from __future__ import annotations

import base64
import logging
import urllib.parse
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MutationResult:
    """Result of payload mutation."""

    original: str
    mutated: str
    technique: str
    description: str


class PayloadMutator:
    """Generates mutated variants of a payload to bypass filters.

    Usage:
        mutator = PayloadMutator()
        for variant in mutator.mutate("{{7*7}}", technique="ssti"):
            print(variant.technique, "→", variant.mutated)
    """

    # ── Mutation strategies per technique ─────────────────────────────

    TECHNIQUE_STRATEGIES: dict[str, list[str]] = {
        "ssti": ["url_encode", "hex_encode", "unicode_normalize", "case_variation", "whitespace"],
        "sqli": ["url_encode", "hex_encode", "comment_injection", "case_variation", "whitespace", "alternative_syntax"],
        "xss": ["html_entity", "url_encode", "unicode_normalize", "case_variation", "alternative_syntax"],
        "command_injection": ["url_encode", "base64_encode", "whitespace", "alternative_syntax", "unicode_normalize"],
        "path_traversal": ["url_encode", "double_encode", "unicode_normalize", "alternative_syntax"],
        "ldap_injection": ["url_encode", "unicode_normalize", "whitespace"],
        "xxe": ["url_encode", "hex_encode", "case_variation"],
        "deserialization": ["base64_encode", "url_encode", "hex_encode"],
    }

    def mutate(
        self,
        payload: str,
        technique: str = "generic",
        *,
        max_variants: int = 20,
        include_original: bool = False,
    ) -> list[MutationResult]:
        """Generate mutated variants of a payload.

        Args:
            payload: Original payload string
            technique: Attack technique category (ssti, sqli, xss, etc.)
            max_variants: Maximum number of variants to generate
            include_original: Include the original payload as a variant

        Returns:
            List of MutationResult objects with mutated payloads
        """
        strategies = self.TECHNIQUE_STRATEGIES.get(
            technique, self.TECHNIQUE_STRATEGIES.get("generic", ["url_encode", "base64_encode"])
        )
        results: list[MutationResult] = []

        if include_original:
            results.append(
                MutationResult(
                    original=payload,
                    mutated=payload,
                    technique="original",
                    description="Unmodified original payload",
                )
            )

        for strategy in strategies:
            method = getattr(self, f"_mutate_{strategy}", None)
            if method is None:
                continue

            try:
                mutated = method(payload)
                if mutated and mutated != payload:
                    results.append(
                        MutationResult(
                            original=payload,
                            mutated=mutated,
                            technique=strategy,
                            description=f"Applied {strategy} transformation",
                        )
                    )
            except Exception as exc:
                logger.debug("Mutation %s failed for payload: %s", strategy, exc)

            if len(results) >= max_variants:
                break

        return results

    # ── Mutation strategies ───────────────────────────────────────────

    def _mutate_url_encode(self, payload: str) -> str:
        """URL-encode the payload."""
        return urllib.parse.quote(payload, safe="")

    def _mutate_double_encode(self, payload: str) -> str:
        """Double URL-encode the payload."""
        return urllib.parse.quote(urllib.parse.quote(payload, safe=""), safe="")

    def _mutate_base64_encode(self, payload: str) -> str:
        """Base64-encode the payload."""
        return base64.b64encode(payload.encode()).decode()

    def _mutate_hex_encode(self, payload: str) -> str:
        """Hex-encode the payload."""
        return "".join(f"\\x{ord(c):02x}" for c in payload)

    def _mutate_unicode_normalize(self, payload: str) -> str:
        """Apply Unicode normalization tricks (fullwidth, homoglyphs)."""
        # Replace ASCII with fullwidth equivalents
        result = []
        for c in payload:
            code = ord(c)
            if 0x21 <= code <= 0x7E:
                result.append(chr(code - 0x20 + 0xFF00))
            else:
                result.append(c)
        return "".join(result)

    def _mutate_case_variation(self, payload: str) -> str:
        """Random case variation (useful for bypassing case-sensitive filters)."""
        import random

        random.seed(hash(payload) % 10000)
        return "".join(c.upper() if random.random() > 0.5 else c.lower() for c in payload)

    def _mutate_whitespace(self, payload: str) -> str:
        """Inject alternative whitespace characters."""
        # Replace spaces with tabs, newlines, or other whitespace chars
        alternatives = ["\t", "\n", "\r", "\v", "\f"]
        result = []
        for i, c in enumerate(payload):
            if c == " ":
                result.append(alternatives[i % len(alternatives)])
            else:
                result.append(c)
        return "".join(result)

    def _mutate_comment_injection(self, payload: str) -> str:
        """Inject SQL-style comments to break filter patterns."""
        # Insert /**/ between characters
        return "/**/".join(list(payload))

    def _mutate_html_entity(self, payload: str) -> str:
        """Encode payload as HTML entities."""
        return "".join(f"&#{ord(c)};" for c in payload)

    def _mutate_alternative_syntax(self, payload: str) -> str:
        """Try alternative syntax for common patterns."""
        replacements = {
            "cat ": "ca\\t ",
            "&&": "& &",
            "||": "| |",
            "${": "{${",
            "{{": "{ {",
            "}}": "} }",
            "sleep": "sle\\ep",
            "benchmark": "ben\\chmark",
            "load_file": "loa\\d_file",
            "into outfile": "into/**/outfile",
            "union select": "union/**/select",
            "order by": "order/**/by",
        }
        result = payload
        for old, new in replacements.items():
            if old in result:
                result = result.replace(old, new)
        return result
