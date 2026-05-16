"""
Domain Intelligence Engine
===========================
Detects lookalike domains, typosquatting, homograph attacks,
and brand impersonation using multiple similarity algorithms.

Confidence scoring:
  0–20   = trusted / clean
  21–55  = review needed
  56–80  = suspicious / possible impersonation
  81–100 = confirmed impersonation / scam domain
"""

from __future__ import annotations

import re
import unicodedata
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Homograph / confusable character map (unicode lookalikes → ASCII)
# ---------------------------------------------------------------------------
_CONFUSABLES: Dict[str, str] = {
    # Cyrillic
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x",
    "у": "y", "і": "i", "ї": "i", "ь": "b",
    # Greek
    "α": "a", "β": "b", "γ": "y", "δ": "d", "ε": "e", "ζ": "z",
    "η": "n", "θ": "0", "ι": "i", "κ": "k", "λ": "l", "μ": "u",
    "ν": "v", "ξ": "x", "ο": "o", "π": "n", "ρ": "p", "σ": "o",
    "τ": "t", "υ": "u", "φ": "o", "χ": "x", "ψ": "y", "ω": "w",
    # Common digit/letter substitutions
    "0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "6": "b",
    "7": "t", "8": "b", "9": "g",
    # Latin extended lookalikes
    "ā": "a", "á": "a", "à": "a", "â": "a", "ä": "a", "ã": "a",
    "ē": "e", "é": "e", "è": "e", "ê": "e", "ë": "e",
    "ī": "i", "í": "i", "ì": "i", "î": "i", "ï": "i",
    "ō": "o", "ó": "o", "ò": "o", "ô": "o", "ö": "o", "õ": "o",
    "ū": "u", "ú": "u", "ù": "u", "û": "u", "ü": "u",
    "ý": "y", "ÿ": "y",
    "ñ": "n", "ç": "c", "ß": "ss",
    # Punctuation that appears in IDN abuse
    "’": "'", "“": '"', "”": '"',
}

# ---------------------------------------------------------------------------
# Well-known brand → canonical domain registry
# Keep sorted so binary search is possible if this grows large.
# ---------------------------------------------------------------------------
_BRAND_DOMAINS: Dict[str, List[str]] = {
    "paypal": ["paypal.com"],
    "google": ["google.com", "gmail.com", "googlemail.com"],
    "microsoft": ["microsoft.com", "outlook.com", "live.com", "hotmail.com", "office.com", "office365.com"],
    "apple": ["apple.com", "icloud.com"],
    "amazon": ["amazon.com", "amazon.co.uk", "amazon.de", "amazonses.com", "aws.amazon.com"],
    "facebook": ["facebook.com", "fb.com", "instagram.com"],
    "twitter": ["twitter.com", "x.com"],
    "linkedin": ["linkedin.com"],
    "netflix": ["netflix.com"],
    "dropbox": ["dropbox.com"],
    "docusign": ["docusign.com", "docusign.net"],
    "chase": ["chase.com", "jpmorganchase.com"],
    "bankofamerica": ["bankofamerica.com"],
    "wellsfargo": ["wellsfargo.com"],
    "citibank": ["citi.com", "citibank.com"],
    "hsbc": ["hsbc.com"],
    "fedex": ["fedex.com"],
    "ups": ["ups.com"],
    "dhl": ["dhl.com"],
    "usps": ["usps.com"],
    "irs": ["irs.gov"],
    "ssa": ["ssa.gov"],
    "stripe": ["stripe.com"],
    "shopify": ["shopify.com"],
    "zoom": ["zoom.us", "zoom.com"],
    "slack": ["slack.com"],
    "salesforce": ["salesforce.com"],
    "adobe": ["adobe.com"],
    "github": ["github.com"],
    "coinbase": ["coinbase.com"],
    "binance": ["binance.com"],
}

# Flatten: normalized_domain → brand_name
_CANONICAL: Dict[str, str] = {}
_BRAND_CORE_NAMES: List[str] = []
for _brand, _domains in _BRAND_DOMAINS.items():
    _BRAND_CORE_NAMES.append(_brand)
    for _d in _domains:
        _CANONICAL[_d.lower()] = _brand


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DomainThreatResult:
    domain: str
    is_lookalike: bool = False
    impersonated_brand: Optional[str] = None
    impersonated_domain: Optional[str] = None
    confidence_score: int = 0          # 0–100 (higher = more suspicious)
    threat_type: Optional[str] = None  # e.g. "typosquatting", "homograph", "subdomain_deception"
    reasons: List[str] = field(default_factory=list)
    levenshtein_distance: Optional[int] = None
    visual_score: Optional[float] = None
    classification: str = "unknown"    # trusted / clean / review / suspicious / scam / unknown


@dataclass
class SenderThreatResult:
    sender_email: str
    domain: str
    domain_threat: DomainThreatResult
    spf_valid: Optional[bool] = None
    dkim_valid: Optional[bool] = None
    is_trusted: bool = False
    overall_threat_score: int = 0      # 0–100
    classification: str = "unknown"    # trusted / clean / review / suspicious / scam


# ---------------------------------------------------------------------------
# Core algorithms
# ---------------------------------------------------------------------------

def _levenshtein(a: str, b: str) -> int:
    """Classic Levenshtein edit distance — O(|a|·|b|)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = curr
    return prev[-1]


def _normalize_homographs(text: str) -> str:
    """Replace confusable unicode characters with ASCII equivalents."""
    # NFD first to decompose accents, then map custom confusables
    nfd = unicodedata.normalize("NFD", text)
    result = []
    for ch in nfd:
        # Strip combining diacritics (category Mn)
        if unicodedata.category(ch) == "Mn":
            continue
        result.append(_CONFUSABLES.get(ch, ch))
    return "".join(result).lower()


def _extract_domain_parts(domain: str) -> Tuple[str, str, str]:
    """Return (subdomain, sld, tld) e.g. 'mail.paypal.com' → ('mail','paypal','com')."""
    domain = domain.lower().strip().rstrip(".")
    parts = domain.split(".")
    if len(parts) >= 3:
        tld = ".".join(parts[-2:]) if parts[-2] in {
            "co", "com", "net", "org", "gov", "edu", "ac", "or"
        } else parts[-1]
        if "." in tld:
            sld = parts[-3]
            sub = ".".join(parts[:-3]) if len(parts) > 3 else ""
        else:
            sld = parts[-2]
            sub = ".".join(parts[:-2]) if len(parts) > 2 else ""
    elif len(parts) == 2:
        sld, tld = parts[0], parts[1]
        sub = ""
    else:
        sld, tld, sub = parts[0], "", ""
    return sub, sld, tld


def _visual_similarity_score(a: str, b: str) -> float:
    """
    Combined visual similarity score between two strings (0.0–1.0).
    Uses normalised Levenshtein + character overlap ratio.
    """
    if not a or not b:
        return 0.0
    max_len = max(len(a), len(b))
    lev = _levenshtein(a, b)
    lev_sim = 1.0 - lev / max_len
    # Bigram overlap
    def bigrams(s: str) -> set:
        return {s[i:i+2] for i in range(len(s) - 1)}
    bg_a = bigrams(a)
    bg_b = bigrams(b)
    union = bg_a | bg_b
    if union:
        bigram_sim = len(bg_a & bg_b) / len(union)
    else:
        bigram_sim = 1.0 if a == b else 0.0
    return 0.6 * lev_sim + 0.4 * bigram_sim


# ---------------------------------------------------------------------------
# Typosquatting generators — produce candidate mutations of a brand name
# ---------------------------------------------------------------------------

def _generate_typos(name: str) -> List[str]:
    """Generate common typosquatting mutations of a brand/domain name."""
    candidates: set = set()
    # Character deletion
    for i in range(len(name)):
        candidates.add(name[:i] + name[i+1:])
    # Character duplication
    for i, ch in enumerate(name):
        candidates.add(name[:i] + ch + name[i:])
    # Adjacent swap
    for i in range(len(name) - 1):
        s = list(name)
        s[i], s[i+1] = s[i+1], s[i]
        candidates.add("".join(s))
    # Common replacements
    replacements = {
        "a": ["4", "@"],
        "e": ["3"],
        "i": ["1", "l", "!"],
        "l": ["1", "i"],
        "o": ["0"],
        "s": ["5", "$"],
        "g": ["9"],
    }
    for i, ch in enumerate(name):
        for rep in replacements.get(ch, []):
            candidates.add(name[:i] + rep + name[i+1:])
    # Remove the original
    candidates.discard(name)
    return list(candidates)


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class DomainIntelligenceEngine:
    """
    Analyses a sender domain against known trusted brands and user-registered
    trusted domains.  Returns a structured threat result with a 0-100 score.
    """

    # Known suspicious TLD patterns that are common in phishing
    _SUSPICIOUS_TLDS = {
        "tk", "ml", "ga", "cf", "gq",   # Free TLDs abused for phishing
        "xyz", "top", "click", "loan",
        "work", "party", "gdn", "bid",
        "win", "download", "review",
    }

    # Deceptive keyword patterns in SLD names
    _DECEPTIVE_KEYWORDS_RE = re.compile(
        r"(secure|login|verify|account|update|confirm|alert|bank|support|"
        r"helpdesk|payment|invoice|billing|access|portal|auth|authenticate|"
        r"validation|customer|service|manager|online|web|mail|smtp|imap)",
        re.I
    )

    def __init__(self, trusted_domains: Optional[List[str]] = None):
        # User-registered trusted domains (exact matches only)
        self._user_trusted: set = set()
        if trusted_domains:
            for d in trusted_domains:
                self._user_trusted.add(d.lower().strip())

        # Pre-compute normalised brand SLDs → brand name for fast lookup
        self._brand_sld_map: Dict[str, str] = {}
        for brand, domains in _BRAND_DOMAINS.items():
            for d in domains:
                _, sld, _ = _extract_domain_parts(d)
                self._brand_sld_map[sld] = brand
                # Also map normalised SLD
                normalised = _normalize_homographs(sld)
                self._brand_sld_map[normalised] = brand

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_trusted_domain(self, domain: str) -> None:
        self._user_trusted.add(domain.lower().strip())

    def remove_trusted_domain(self, domain: str) -> None:
        self._user_trusted.discard(domain.lower().strip())

    def analyse(self, domain: str) -> DomainThreatResult:
        """
        Analyse a single domain and return a DomainThreatResult.
        """
        domain = (domain or "").lower().strip().lstrip("@")
        result = DomainThreatResult(domain=domain)

        if not domain or "." not in domain:
            return result

        # 1. Exact trusted domain — immediately safe
        if self._is_exact_trusted(domain):
            result.confidence_score = 0
            result.classification = "clean"
            return result

        sub, sld, tld = _extract_domain_parts(domain)
        normalised_sld = _normalize_homographs(sld)

        # 2. Check homograph / confusable normalisation against brand SLDs
        self._check_homograph(result, sld, normalised_sld, tld)

        # 3. Levenshtein similarity against all known brand names
        if not result.is_lookalike:
            self._check_levenshtein(result, sld, normalised_sld, tld)

        # 4. Subdomain deception (e.g. paypal.com.malicious.xyz)
        if not result.is_lookalike:
            self._check_subdomain_deception(result, domain, sub, sld, tld)

        # 5. Deceptive keyword injection (e.g. paypal-secure-login.com)
        self._check_deceptive_keywords(result, sld, tld)

        # 6. Suspicious TLD penalty
        if tld in self._SUSPICIOUS_TLDS:
            result.confidence_score = min(100, result.confidence_score + 15)
            result.reasons.append(f"suspicious free TLD '.{tld}' commonly used in phishing")

        # 7. Visual similarity score against impersonated domain (if found)
        if result.impersonated_domain:
            _, imp_sld, _ = _extract_domain_parts(result.impersonated_domain)
            result.visual_score = _visual_similarity_score(
                _normalize_homographs(sld), _normalize_homographs(imp_sld)
            )

        # Clamp and assign classification label
        result.confidence_score = max(0, min(100, result.confidence_score))
        result.classification = _score_to_level(result.confidence_score)

        return result

    def analyse_sender(
        self,
        sender_email: str,
        spf_valid: Optional[bool] = None,
        dkim_valid: Optional[bool] = None,
        user_trusted_senders: Optional[set] = None,
    ) -> SenderThreatResult:
        """
        Full sender-level analysis including SPF/DKIM penalties.
        Returns a SenderThreatResult with an overall_threat_score 0–100.
        """
        email = (sender_email or "").lower().strip()
        domain = email.split("@")[-1] if "@" in email else email

        # User has explicitly trusted this sender
        is_trusted = bool(
            user_trusted_senders and (email in user_trusted_senders or domain in user_trusted_senders)
        )

        domain_threat = self.analyse(domain)
        overall = domain_threat.confidence_score

        # SPF/DKIM failures add significant weight
        if spf_valid is False:
            overall = min(100, overall + 20)
            domain_threat.reasons.append("SPF validation failed")
        if dkim_valid is False:
            overall = min(100, overall + 15)
            domain_threat.reasons.append("DKIM validation failed")

        if is_trusted:
            overall = max(0, overall - 40)
            classification = "trusted"
        elif overall <= 20:
            classification = "trusted"
        elif overall <= 55:
            classification = "review"
        elif overall <= 80:
            classification = "suspicious"
        else:
            classification = "scam"

        return SenderThreatResult(
            sender_email=email,
            domain=domain,
            domain_threat=domain_threat,
            spf_valid=spf_valid,
            dkim_valid=dkim_valid,
            is_trusted=is_trusted,
            overall_threat_score=overall,
            classification=classification,
        )

    # ------------------------------------------------------------------
    # Internal checks
    # ------------------------------------------------------------------

    def _is_exact_trusted(self, domain: str) -> bool:
        return domain in self._user_trusted or domain in _CANONICAL

    def _check_homograph(
        self, result: DomainThreatResult, sld: str, normalised_sld: str, tld: str
    ) -> None:
        """Detect unicode homograph attacks by normalising confusables."""
        if sld == normalised_sld:
            return  # Pure ASCII — no homograph risk from this check

        if normalised_sld in self._brand_sld_map:
            brand = self._brand_sld_map[normalised_sld]
            canonical = _BRAND_DOMAINS[brand][0]
            result.is_lookalike = True
            result.impersonated_brand = brand
            result.impersonated_domain = canonical
            result.threat_type = "homograph_attack"
            result.confidence_score = min(100, result.confidence_score + 88)
            result.reasons.append(
                f"unicode homograph attack: '{sld}' visually resembles '{normalised_sld}' "
                f"(impersonating {brand})"
            )

    def _check_levenshtein(
        self, result: DomainThreatResult, sld: str, normalised_sld: str, tld: str
    ) -> None:
        """Detect typosquatting via edit distance against known brand SLDs."""
        best_dist = 999
        best_brand: Optional[str] = None
        best_brand_sld: Optional[str] = None

        for brand_sld, brand in self._brand_sld_map.items():
            # Skip short names to reduce false positives
            if len(brand_sld) < 4:
                continue
            dist = _levenshtein(normalised_sld, brand_sld)
            if dist < best_dist:
                best_dist = dist
                best_brand = brand
                best_brand_sld = brand_sld

        if best_brand is None:
            return

        # Dynamic threshold: allow at most 15% edit distance (min 1, max 3)
        threshold = min(3, max(1, int(len(best_brand_sld) * 0.15)))

        if 0 < best_dist <= threshold:
            canonical = _BRAND_DOMAINS[best_brand][0]
            result.is_lookalike = True
            result.impersonated_brand = best_brand
            result.impersonated_domain = canonical
            result.levenshtein_distance = best_dist
            score_delta = {1: 75, 2: 55, 3: 35}.get(best_dist, 20)
            result.confidence_score = min(100, result.confidence_score + score_delta)
            result.threat_type = result.threat_type or "typosquatting"
            result.reasons.append(
                f"typosquatting: '{sld}.{tld}' resembles '{canonical}' "
                f"(edit distance {best_dist})"
            )

    def _check_subdomain_deception(
        self,
        result: DomainThreatResult,
        full_domain: str,
        sub: str,
        sld: str,
        tld: str,
    ) -> None:
        """Detect abuse like paypal.com.evil.xyz or secure-paypal.evil.com."""
        # Check if a trusted brand name appears in a non-authoritative position
        full_normalised = _normalize_homographs(full_domain)
        for brand, domains in _BRAND_DOMAINS.items():
            for canon in domains:
                _, canon_sld, _ = _extract_domain_parts(canon)
                if canon_sld in full_normalised and not self._is_exact_trusted(full_domain):
                    # Only flag if the official SLD is NOT the registered SLD
                    if sld != canon_sld:
                        result.is_lookalike = True
                        result.impersonated_brand = brand
                        result.impersonated_domain = canon
                        result.threat_type = "subdomain_deception"
                        result.confidence_score = min(100, result.confidence_score + 65)
                        result.reasons.append(
                            f"subdomain deception: '{full_domain}' embeds '{canon_sld}' "
                            f"to impersonate {brand}"
                        )
                        return

    def _check_deceptive_keywords(
        self, result: DomainThreatResult, sld: str, tld: str
    ) -> None:
        """Penalise domains embedding security-related lures alongside brand names."""
        if self._DECEPTIVE_KEYWORDS_RE.search(sld):
            result.confidence_score = min(100, result.confidence_score + 20)
            result.reasons.append(
                f"deceptive keyword in domain name: '{sld}' contains security/login lure term"
            )

    # ------------------------------------------------------------------
    # Batch analysis
    # ------------------------------------------------------------------

    def analyse_bulk(self, domains: List[str]) -> Dict[str, DomainThreatResult]:
        return {d: self.analyse(d) for d in domains}

    def get_threat_summary(self, domain: str) -> Dict:
        """Return a JSON-serialisable summary of the threat result."""
        r = self.analyse(domain)
        return {
            "domain": r.domain,
            "is_lookalike": r.is_lookalike,
            "impersonated_brand": r.impersonated_brand,
            "impersonated_domain": r.impersonated_domain,
            "confidence_score": r.confidence_score,
            "threat_level": _score_to_level(r.confidence_score),
            "classification": r.classification,
            "threat_type": r.threat_type,
            "reasons": r.reasons,
            "levenshtein_distance": r.levenshtein_distance,
            "visual_score": round(r.visual_score, 3) if r.visual_score is not None else None,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_to_level(score: int) -> str:
    if score <= 20:
        return "clean"
    if score <= 55:
        return "review"
    if score <= 80:
        return "suspicious"
    return "critical"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: Optional[DomainIntelligenceEngine] = None


def get_engine() -> DomainIntelligenceEngine:
    global _engine
    if _engine is None:
        _engine = DomainIntelligenceEngine()
    return _engine


def analyse_domain(domain: str) -> Dict:
    return get_engine().get_threat_summary(domain)


def analyse_sender(
    sender_email: str,
    spf_valid: Optional[bool] = None,
    dkim_valid: Optional[bool] = None,
    user_trusted_senders: Optional[set] = None,
) -> SenderThreatResult:
    return get_engine().analyse_sender(
        sender_email,
        spf_valid=spf_valid,
        dkim_valid=dkim_valid,
        user_trusted_senders=user_trusted_senders,
    )
